from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping


BranchDisposition = Literal["continue", "terminal"]
BranchPlacement = Literal["replace_node", "insert_after"]


@dataclass(frozen=True)
class CapabilityExecutionOutcome:
    outcome_id: str
    edge_label: str
    title: str
    summary: str
    node_type: str = "supporting_contract"
    disposition: BranchDisposition = "continue"
    writes_to: tuple[str, ...] = ("当前 Bot 回复",)
    completion_signals: tuple[str, ...] = ()
    target_node_id: str = ""


@dataclass(frozen=True)
class CapabilityExecutionBranchContract:
    contract_id: str
    decision_id: str
    title: str
    summary: str
    source: str
    placement: BranchPlacement
    anchor_node_id: str
    outcomes: tuple[CapabilityExecutionOutcome, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.contract_id.strip() or not self.decision_id.strip():
            raise ValueError("execution branch contract requires ids")
        if self.placement not in {"replace_node", "insert_after"}:
            raise ValueError(f"unsupported execution branch placement: {self.placement}")
        if len(self.outcomes) < 2:
            raise ValueError(f"execution branch contract {self.contract_id} requires at least two outcomes")
        outcome_ids = [item.outcome_id for item in self.outcomes]
        edge_labels = [item.edge_label for item in self.outcomes]
        if len(outcome_ids) != len(set(outcome_ids)):
            raise ValueError(f"execution branch contract {self.contract_id} has duplicate outcome ids")
        if len(edge_labels) != len(set(edge_labels)) or any(not item.strip() for item in edge_labels):
            raise ValueError(f"execution branch contract {self.contract_id} requires unique edge labels")


def _outcome(
    outcome_id: str,
    edge_label: str,
    title: str,
    summary: str,
    *,
    node_type: str = "supporting_contract",
    disposition: BranchDisposition = "continue",
    writes_to: tuple[str, ...] = ("当前 Bot 回复",),
    completion_signals: tuple[str, ...] = (),
    target_node_id: str = "",
) -> CapabilityExecutionOutcome:
    return CapabilityExecutionOutcome(
        outcome_id=outcome_id,
        edge_label=edge_label,
        title=title,
        summary=summary,
        node_type=node_type,
        disposition=disposition,
        writes_to=writes_to,
        completion_signals=completion_signals,
        target_node_id=target_node_id,
    )


def _replace_output(
    contract_id: str,
    title: str,
    summary: str,
    source: str,
    outcomes: tuple[CapabilityExecutionOutcome, ...],
) -> CapabilityExecutionBranchContract:
    return CapabilityExecutionBranchContract(
        contract_id=contract_id,
        decision_id="output-materialize",
        title=title,
        summary=summary,
        source=source,
        placement="replace_node",
        anchor_node_id="output-materialize",
        outcomes=outcomes,
    )


def validate_capability_execution_branch_contracts(
    registry: Mapping[str, tuple[CapabilityExecutionBranchContract, ...]],
) -> dict[str, tuple[CapabilityExecutionBranchContract, ...]]:
    validated = dict(registry)
    seen_contract_ids: set[str] = set()
    for label, contracts in validated.items():
        if not label.strip():
            raise ValueError("execution branch registry requires non-empty capability labels")
        seen_decision_ids: set[str] = set()
        seen_outcome_ids: set[str] = set()
        for contract in contracts:
            if contract.contract_id in seen_contract_ids:
                raise ValueError(f"duplicate execution branch contract_id: {contract.contract_id}")
            seen_contract_ids.add(contract.contract_id)
            if contract.decision_id in seen_decision_ids:
                raise ValueError(f"capability {label} has duplicate execution decision_id: {contract.decision_id}")
            seen_decision_ids.add(contract.decision_id)
            for outcome in contract.outcomes:
                if outcome.outcome_id in seen_outcome_ids:
                    raise ValueError(f"capability {label} has duplicate execution outcome_id: {outcome.outcome_id}")
                seen_outcome_ids.add(outcome.outcome_id)
    return validated


CAPABILITY_EXECUTION_BRANCH_CONTRACTS: dict[str, tuple[CapabilityExecutionBranchContract, ...]] = validate_capability_execution_branch_contracts({
    "待办": (
        _replace_output(
            "tag_router.todo.intake_mode.v1",
            "选择待办写入路径",
            "LLM 分流结果决定写入普通清单、父子清单、提醒任务，或停止并向用户明确说明容量/人工处理原因。",
            "openclaw_app/router/activity_daily.py::handle_待办 + _normalize_todo_intake",
            (
                _outcome(
                    "todo-checklist-only",
                    "checklist_only",
                    "写入普通 Obsidian checklist",
                    "把扁平待办清单写入 Obsidian 周记，不创建飞书提醒。",
                    node_type="storage_write",
                    writes_to=("Obsidian 周记 # 待办", "本地 archive"),
                    completion_signals=("普通 checklist 已写入",),
                ),
                _outcome(
                    "todo-structured-checklist",
                    "structured_checklist",
                    "写入父子待办清单",
                    "保留显式层级并写入 Obsidian，同时创建飞书父子待办记录。",
                    node_type="bitable_write",
                    writes_to=("Obsidian 周记 # 待办", "Feishu 待办父子记录"),
                    completion_signals=("父子层级已保留", "飞书记录逐项返回结果"),
                ),
                _outcome(
                    "todo-reminder-backed",
                    "reminder_backed",
                    "创建提醒型待办",
                    "抽取明确时间后创建飞书提醒，并同步写入 Obsidian checklist。",
                    node_type="bitable_write",
                    writes_to=("Feishu 待办提醒", "Obsidian 周记 # 待办", "本地 archive"),
                    completion_signals=("提醒记录已创建或明确返回写入警告",),
                ),
                _outcome(
                    "todo-pending-manual",
                    "pending_manual",
                    "等待补充待办信息",
                    "正文为空、冲突、置信度不足或无法产生可执行待办时停止业务写入。",
                    disposition="terminal",
                    completion_signals=("回复缺失信息和人工补充要求",),
                ),
                _outcome(
                    "todo-model-at-capacity",
                    "model_at_capacity",
                    "模型容量已满",
                    "同一模型的有界容量重试耗尽后停止业务写入，并向用户返回 DAILY_LLM_MODEL_AT_CAPACITY、英文底层详情和稍后重试建议。",
                    disposition="terminal",
                    completion_signals=("待办未创建、未落盘", "用户收到稳定容量错误码、详情和重试建议"),
                ),
            ),
        ),
    ),
    "检查": (
        _replace_output(
            "media_growth.verify_dispatch.v1",
            "选择检查能力",
            "根据明确输入字段进入清单查询、作品验收或发布前 Gate。",
            "openclaw_app/router/media_growth.py::_media_growth_verify_capability_id",
            (
                _outcome("media-check-checklist", "默认检查", "查询创作检查清单", "没有作品正文或发布包 ID 时返回创作检查清单。"),
                _outcome("media-check-acceptance", "作品内容/稿件", "进入作品验收", "检测到作品正文、稿件、脚本、成片路径或创作要求时进入作品验收。"),
                _outcome("media-check-publish-gate", "发布包/run_id", "进入发布准备 Gate", "检测到发布包 ID、创作 run_id 或创作记录 ID 时进入发布前 Gate。"),
            ),
        ),
    ),
    "复核": (
        _replace_output(
            "media_growth.review_action.v1",
            "执行人工复核动作",
            "复核动作直接改变 artifact 的质量状态、业务状态和前端可见性。",
            "selfmedia/growth/service.py::review_growth_artifact",
            (
                _outcome("growth-review-approve", "approve/通过", "通过复核", "标记为 cleaned/candidate，并允许进入前端候选。", node_type="storage_write", writes_to=("media_vault artifact", "growth summary")),
                _outcome("growth-review-verify", "verify/验收", "标记 verified", "标记为 verified/candidate，并允许进入前端候选。", node_type="storage_write", writes_to=("media_vault artifact", "growth summary")),
                _outcome("growth-review-reject", "reject/废弃", "废弃 artifact", "标记为 rejected，并从前端候选中移除。", node_type="storage_write", writes_to=("media_vault artifact", "growth summary")),
            ),
        ),
    ),
    "博主": (
        _replace_output(
            "tag_router.creator_profile.dispatch.v1",
            "选择博主档案动作",
            "统一入口根据能力字段进入查询、直接入库、候选生成或确认写入。",
            "openclaw_app/router/creator_profile_router.py::handle_博主 + handle_博主_入库",
            (
                _outcome("creator-profile-query", "查询", "查询博主档案", "读取现有博主档案并返回匹配结果。", node_type="data_fetch", writes_to=("当前 Bot 回复",)),
                _outcome("creator-profile-direct-upsert", "入库", "直接写入博主档案", "字段满足手工入库要求时直接写入 CreatorProfiles。", node_type="bitable_write", writes_to=("06_CreatorProfiles_达人账号档案",)),
                _outcome("creator-profile-candidate", "自动补全", "生成候选但暂不写入", "自动补全只生成候选和 run_id，等待人工确认。", disposition="terminal", writes_to=("本地候选运行 artifact",), completion_signals=("返回 run_id 和确认写入指令",)),
                _outcome("creator-profile-confirm", "确认写入 run_id", "确认候选并写入", "读取指定候选 run_id，应用人工修改后写入 CreatorProfiles。", node_type="bitable_write", writes_to=("06_CreatorProfiles_达人账号档案",)),
            ),
        ),
    ),
    "博主-入库": (
        _replace_output(
            "tag_router.creator_profile.upsert_mode.v1",
            "选择博主入库模式",
            "入库入口支持手工写入、自动候选和 run_id 确认三种真实路径。",
            "openclaw_app/router/creator_profile_router.py::handle_博主_入库",
            (
                _outcome("creator-upsert-manual", "手工字段", "手工写入档案", "校验必要字段后直接写入 CreatorProfiles。", node_type="bitable_write", writes_to=("06_CreatorProfiles_达人账号档案",)),
                _outcome("creator-upsert-candidate", "自动补全", "生成候选", "生成候选和证据，暂不写库。", disposition="terminal", writes_to=("本地候选运行 artifact",)),
                _outcome("creator-upsert-confirm", "确认写入", "确认候选写入", "根据 run_id 确认候选并写入 CreatorProfiles。", node_type="bitable_write", writes_to=("06_CreatorProfiles_达人账号档案",)),
            ),
        ),
    ),
    "衣橱": (
        _replace_output(
            "tag_router.wardrobe.write_mode.v1",
            "选择衣橱写入模式",
            "衣物 ID 和回复上下文决定新建、更新或停止等待人工关联。",
            "openclaw_app/router/wardrobe.py::handle_衣物_入库",
            (
                _outcome("wardrobe-create", "无 item_id", "新建衣物记录", "生成系统 item_id 并创建新的衣橱记录。", node_type="bitable_write", writes_to=("Feishu Bitable 衣橱",)),
                _outcome("wardrobe-update", "已有 item_id", "更新现有衣物记录", "按明确 item_id 更新字段和补充附件。", node_type="bitable_write", writes_to=("Feishu Bitable 衣橱",)),
                _outcome("wardrobe-link-pending", "补截图但未关联", "等待关联衣物 ID", "补充截图无法通过正文或回复上下文关联到衣物时停止写入。", disposition="terminal", completion_signals=("回复关联 item_id 的要求",)),
            ),
        ),
    ),
    "说明": (
        _replace_output(
            "tag_router.capability_matcher.path_status.v3",
            "判断能力路径是否明确",
            "能力匹配模型只允许返回 matched、ambiguous 或 needs_clarification，三种结果产生互斥用户输出。",
            "openclaw_app/services/capability_matcher.py::_validated_model_response",
            (
                _outcome("capability-path-matched", "matched", "返回可执行能力路径", "返回 1-5 个真实能力步骤和首步可复制指令。"),
                _outcome("capability-path-ambiguous", "ambiguous", "返回候选能力", "无法唯一选路时返回至少两个真实候选能力，不生成可执行指令。", disposition="terminal"),
                _outcome("capability-path-needs-clarification", "needs_clarification", "提出一个必要澄清问题", "关键事实不足时省略步骤，只返回一个必要问题和已知参数。", disposition="terminal"),
            ),
        ),
    ),
    "作品验收": (
        _replace_output(
            "tag_router.work_acceptance.verdict.v1",
            "处理作品验收结论",
            "验收结论决定是否允许推进 Content OS 状态。",
            "openclaw_app/router/work_acceptance.py + content_os_bridge.py::_maybe_apply_content_os_work_acceptance",
            (
                _outcome("work-acceptance-pass", "通过", "验收通过并尝试推进状态", "存在 Content OS project_id 时按状态机和证据尝试推进；否则只返回验收结果。", node_type="quality_check", writes_to=("作品验收回复", "Content OS 状态（条件满足时）")),
                _outcome("work-acceptance-fail", "不通过", "返回缺口且不推进状态", "列出不满足项和修改建议，Content OS 状态保持不变。", writes_to=("作品验收回复",)),
                _outcome("work-acceptance-uncertain", "不确定", "等待补充可见证据", "缺正文、缺要求或依赖不可见画面时不推进状态。", disposition="terminal"),
            ),
        ),
    ),
    "修改": (
        _replace_output(
            "tag_router.document_edit.apply_status.v1",
            "处理文档 patch 结果",
            "patch 应用结果区分完整成功、部分成功、人工处理和失败。",
            "openclaw_app/services/document_edit_contract.py::DocumentEditPatchApplyResult",
            (
                _outcome("document-edit-ok", "patch_apply_ok", "完整应用 patch", "所有安全文本操作已应用并通过读回。", node_type="document_render", writes_to=("目标 Feishu Docx 文档",)),
                _outcome("document-edit-partial", "patch_apply_partial", "部分应用并列出剩余项", "安全操作已应用，无法自动处理的项目明确列出。", node_type="document_render", writes_to=("目标 Feishu Docx 文档", "当前 Bot 回复")),
                _outcome("document-edit-manual", "patch_apply_manual", "转人工处理", "仅剩图片、附件、表格或未验证结构操作时停止自动写入。", disposition="terminal"),
                _outcome("document-edit-failed", "patch_apply_failed", "停止并返回失败", "合同、定位、写入或读回失败时不声称修改完成。", disposition="terminal"),
            ),
        ),
    ),
    "自媒体知识": (
        CapabilityExecutionBranchContract(
            contract_id="content_flow.source_route.v1",
            decision_id="content-flow-source-route",
            title="选择内容证据处理路径",
            summary="来源类型决定公众号正文提取、视频转写、图文 OCR 或人工补充路径。",
            source="content_flow_client.py::analyze + selfmedia/ingest/content_flow/src/pipeline.py",
            placement="insert_after",
            anchor_node_id="input-parse",
            outcomes=(
                _outcome("content-flow-wechat", "公众号文章", "抓取公众号正文与图集", "使用公众号专用提取器保存正文、图片，并在图集来源需要时执行 OCR。", node_type="data_fetch", writes_to=("content_flow/wechat_articles", "LLM request context")),
                _outcome("content-flow-video", "视频", "下载视频并转写音频", "下载视频和音频，生成逐字稿后进入内容分析。", node_type="data_fetch", writes_to=("content_flow media directory", "transcript")),
                _outcome("content-flow-image", "图文/动图", "下载图片并执行 OCR", "保存图片并按页面顺序执行 OCR，非视频路径跳过 ASR。", node_type="vision_read", writes_to=("content_flow image directory", "image OCR")),
                _outcome("content-flow-pending", "来源不完整", "等待补充来源证据", "抓取、图片、OCR 或来源证据不完整时停止入库。", disposition="terminal"),
            ),
        ),
    ),
    "转写": (
        CapabilityExecutionBranchContract(
            contract_id="tag_router.transcription.intake_mode.v1",
            decision_id="transcription-intake-mode",
            title="按 Bot 与消息身份选择录音入队路径",
            summary="Knowledge Bot 的每条裸音频按飞书 message ID 自动创建独立持久化任务；Daily Bot 继续使用录音批次确认流程。",
            source="transcription-queue.js::intake + transcription-job-queue.js::enqueue",
            placement="insert_after",
            anchor_node_id="transcribe-source",
            outcomes=(
                _outcome(
                    "transcription-knowledge-auto-enqueue",
                    "Knowledge Bot 新裸音频",
                    "自动创建独立转写任务",
                    "按当前飞书 message ID 只绑定本条消息的 MediaPath，持久化独立任务并立即返回任务 ID。",
                    node_type="storage_write",
                    writes_to=("transcription-queue", "transcription-jobs", "Knowledge Bot 即时回执"),
                    completion_signals=("source_message_id 与 MediaPath 已持久化", "任务已按 enqueue_order 进入 FIFO 队列"),
                ),
                _outcome(
                    "transcription-knowledge-idempotent-replay",
                    "Knowledge Bot 重复 message ID",
                    "返回原任务而不重复创建",
                    "同一飞书 message ID 重放时返回原任务 ID，不创建第二个批次或任务。",
                    disposition="terminal",
                    writes_to=("Knowledge Bot 即时回执",),
                    completion_signals=("返回原任务 ID", "任务总数不增加"),
                ),
                _outcome(
                    "transcription-daily-confirmed-batch",
                    "Daily Bot 已确认批次",
                    "确认后创建批次任务",
                    "按用户确认的批次绑定未消费录音，持久化任务并立即返回任务 ID。",
                    node_type="storage_write",
                    writes_to=("transcription-queue", "transcription-jobs", "Daily Bot 即时回执"),
                    completion_signals=("确认批次已入队", "任务 ID 已返回"),
                ),
                _outcome(
                    "transcription-daily-await-confirmation",
                    "Daily Bot 未确认批次",
                    "列出录音并等待确认",
                    "只返回当前未消费录音名称和批次号；用户确认前不创建后台任务。",
                    disposition="terminal",
                    writes_to=("Daily Bot 批次确认提示",),
                    completion_signals=("未创建转写任务", "返回批次号和确认指令"),
                ),
            ),
        ),
    ),
    "活动": (
        CapabilityExecutionBranchContract(
            contract_id="tag_router.activity.source_url.v1",
            decision_id="activity-source-route",
            title="处理活动来源链接",
            summary="活动正文中的链接会被判定为分析、跳过或忽略。",
            source="openclaw_app/router/activity_daily.py::_activity_source_url_decision",
            placement="insert_after",
            anchor_node_id="input-parse",
            outcomes=(
                _outcome("activity-source-analyze", "小红书正文链接", "分析链接正文", "对可分析的小红书链接调用 content-flow，并把提取内容合并进活动 Brief。", node_type="data_fetch", writes_to=("运行时活动 Brief 上下文",)),
                _outcome("activity-source-skip", "发布入口/模板页", "跳过非正文入口", "小红书发布入口或模板页不作为正文抓取来源。"),
                _outcome("activity-source-ignore", "不支持链接", "仅按消息正文处理", "非支持来源链接不自动抓取，活动仍按用户提供正文继续。"),
                _outcome("activity-source-pending", "分析失败", "保留失败并继续人工补充", "链接分析异常时记录 pending_manual 原因，不编造链接正文。", disposition="terminal"),
            ),
        ),
    ),
    "商单交付": (
        CapabilityExecutionBranchContract(
            contract_id="tag_router.commercial_delivery.script_type.v1",
            decision_id="commercial-script-type",
            title="选择脚本表格结构",
            summary="内容形式决定生成图片脚本或分镜脚本，随后进入同一个 Docx 原生表格渲染器。",
            source="openclaw_app/router/commercial_delivery.py::_commercial_delivery_script_table",
            placement="insert_after",
            anchor_node_id="prompt-commercial-delivery-draft-generation",
            outcomes=(
                _outcome("commercial-image-script", "图文", "生成图片脚本", "使用图片内容、拍摄指导、画面文案、产品露出和道具备注列。"),
                _outcome("commercial-storyboard", "视频", "生成分镜脚本", "使用场景、时长、拍摄指导、口播/字幕、产品露出和道具备注列。"),
            ),
        ),
    ),
    "删除": (
        CapabilityExecutionBranchContract(
            contract_id="tag_router.deletion.target_presence.v1",
            decision_id="delete-target-presence",
            title="检查删除目标 ID",
            summary="缺少明确目标 ID 时立即停止，不进入发现、预览或执行。",
            source="openclaw_app/router/deletion.py::handle_删除",
            placement="insert_after",
            anchor_node_id="input-parse",
            outcomes=(
                _outcome("delete-target-found", "目标 ID 明确", "继续解析删除目标", "按明确 ID 或 URL 发现对应能力与对象。", target_node_id="delete-target-resolution"),
                _outcome("delete-target-missing", "缺少目标 ID", "要求提供明确 ID", "只回复预览和确认删除格式，不执行任何删除。", disposition="terminal"),
            ),
        ),
        CapabilityExecutionBranchContract(
            contract_id="tag_router.deletion.confirmation.v1",
            decision_id="delete-confirmation-gate",
            title="确认删除门禁",
            summary="未明确确认时只返回预览，确认后才进入执行边界。",
            source="openclaw_app/router/deletion.py::_is_delete_apply_request",
            placement="replace_node",
            anchor_node_id="delete-confirmation-gate",
            outcomes=(
                _outcome("delete-preview-only", "未确认/仅预览", "返回删除预览", "展示对象级影响范围，不删除记录、文档或文件。", disposition="terminal"),
                _outcome("delete-confirmed", "确认删除", "进入删除执行边界", "只执行预览清单中已确认的对象。", target_node_id="delete-execution-boundary"),
            ),
        ),
        CapabilityExecutionBranchContract(
            contract_id="tag_router.deletion.result.v1",
            decision_id="delete-result-branch",
            title="汇总对象级删除结果",
            summary="执行结果区分自动完成、需人工处理和失败阻断。",
            source="openclaw_app/router/deletion_plan.py::execute_local_plan + deletion adapters",
            placement="insert_after",
            anchor_node_id="delete-execution-boundary",
            outcomes=(
                _outcome("delete-result-success", "deleted/already_absent", "自动删除完成", "支持且归属明确的对象已删除或已不存在。", node_type="quality_check", target_node_id="completion-check"),
                _outcome("delete-result-manual", "manual_required", "转人工处理", "不支持自动删除或缺少归属证明的对象保持人工处理。", disposition="terminal"),
                _outcome("delete-result-blocked", "failed/blocked", "删除失败或被阻断", "越界路径、服务缺失或对象级失败时明确返回阻断原因。", disposition="terminal"),
            ),
        ),
    ),
})


def capability_execution_branch_contracts(label: str) -> tuple[CapabilityExecutionBranchContract, ...]:
    return CAPABILITY_EXECUTION_BRANCH_CONTRACTS.get(str(label or "").strip(), ())
