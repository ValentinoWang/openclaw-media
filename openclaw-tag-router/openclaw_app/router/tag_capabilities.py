from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from common.capability_execution import CapabilityExecutionBranchContract, capability_execution_branch_contracts
from selfmedia.growth.capability_registry import MEDIA_GROWTH_LABEL_CAPABILITIES, get_capability_spec


STYLE_POLISH_ENTRY_LABELS = ("网感", "文案优化", "改标题", "去AI味", "小红书文案", "抖音文案")
COLLECT_ALIAS_LABELS: tuple[str, ...] = ()
MEDIA_RESEARCH_LABELS = ("调研",)
MEDIA_GROWTH_MAIN_LABELS = ("策略", "Brief", "素材", "调研", "选题", "创作", "拍摄", "润色", "检查", "发布包", "复核", "复盘")


def _tuple(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw = [values]
    else:
        raw = list(values)
    return tuple(str(item).strip() for item in raw if str(item or "").strip())


@dataclass(frozen=True)
class TagCapability:
    label: str
    capability: str
    handler: str
    purpose: str
    result: str
    example: str
    bot: str = "任意 Bot"
    canonical_capability_id: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    lifecycle_layer: str = ""
    produces: tuple[str, ...] = field(default_factory=tuple)
    consumes: tuple[str, ...] = field(default_factory=tuple)
    writes_to: tuple[str, ...] = field(default_factory=tuple)
    default_mode: str = ""
    implementation_status: str = ""
    risk_level: str = ""
    visibility: str = ""
    source_system: str = ""
    ssot_refs: tuple[str, ...] = field(default_factory=tuple)
    requires_confirmation: bool = False
    frontend_group: str = ""
    execution_branches: tuple[CapabilityExecutionBranchContract, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        canonical = self.canonical_capability_id or _default_canonical_capability_id(self.label, self.capability)
        object.__setattr__(self, "canonical_capability_id", canonical)
        object.__setattr__(self, "aliases", _tuple(self.aliases) or _default_aliases(self.label))
        object.__setattr__(self, "lifecycle_layer", self.lifecycle_layer or _default_lifecycle_layer(self.label, canonical, self.capability))
        object.__setattr__(self, "produces", _tuple(self.produces) or _default_produces(canonical))
        object.__setattr__(self, "consumes", _tuple(self.consumes) or _default_consumes(canonical))
        object.__setattr__(self, "writes_to", _tuple(self.writes_to) or _default_writes_to(canonical, self.capability))
        object.__setattr__(self, "default_mode", self.default_mode or _default_mode(canonical, self.capability))
        object.__setattr__(self, "implementation_status", self.implementation_status or _default_implementation_status(canonical))
        object.__setattr__(self, "risk_level", self.risk_level or _default_risk_level(canonical, self.capability))
        object.__setattr__(self, "visibility", self.visibility or _default_visibility(self.label, canonical, self.capability))
        object.__setattr__(self, "source_system", self.source_system or _default_source_system(self.bot, self.capability, canonical))
        object.__setattr__(self, "ssot_refs", _tuple(self.ssot_refs) or _default_ssot_refs(canonical, self.capability))
        object.__setattr__(self, "frontend_group", self.frontend_group or _default_frontend_group(self.label, canonical))
        object.__setattr__(self, "execution_branches", self.execution_branches or capability_execution_branch_contracts(self.label))


def _default_canonical_capability_id(label: str, capability: str) -> str:
    if label in MEDIA_GROWTH_LABEL_CAPABILITIES:
        return MEDIA_GROWTH_LABEL_CAPABILITIES[label]
    explicit = {
        "灵感": "inspiration_archive",
        "灵感>vlog": "vlog_inspiration_capture",
        "归档": "knowledge_archive",
        "补全": "knowledge_completion",
        "认知": "knowledge_cognition_note",
        "学习": "knowledge_learning_note",
        "学习-整理": "knowledge_learning_organize",
        "说明": "system_help",
        "最近": "recent_records_lookup",
        "同步": "record_sync",
        "状态": "task_status_lookup",
        "整理": "recent_records_summary",
        "转写": "audio_transcription",
        "转写-文字": "text_transcript_cleanup",
        "日记": "daily_journal_entry",
        "周记": "weekly_self_model_summary",
        "开发-完成": "development_mark_done",
        "开发-验证": "development_mark_verify",
    }
    if label in explicit:
        return explicit[label]
    if label in STYLE_POLISH_ENTRY_LABELS or label == "润色":
        return "style_polish_run"
    if label == "素材":
        return "source_asset_intake"
    if label == "活动":
        return "activity_archive"
    if label == "热榜":
        return "platform_hotlist"
    if label in MEDIA_RESEARCH_LABELS:
        return "external_research_brief"
    if label == "选题":
        return "creation_decision_brief"
    if label == "拍摄" or label == "创作-拍摄执行":
        return "shooting_execution_plan"
    if label in {"检查", "创作检查"}:
        return "creation_checklist_lookup"
    if label == "作品验收":
        return "work_acceptance_report"
    if label == "发布包":
        return "publishing_pack_build"
    if label == "复核":
        return "media_growth_review"
    if label == "数据复盘":
        return "selfmedia_data_review"
    if label == "复盘":
        return "post_review_signal"
    if label == "策略":
        return "account_track_strategy"
    if label == "账号":
        return "owned_media_account_lookup"
    if label == "赛道":
        return "track_registry_lookup"
    return capability


def _default_aliases(label: str) -> tuple[str, ...]:
    return ()


def _default_lifecycle_layer(label: str, canonical: str, capability: str) -> str:
    spec = get_capability_spec(canonical)
    if spec is not None:
        return spec.lifecycle_layer
    if canonical in {"account_track_strategy", "content_principle", "content_cognition_doc"}:
        return "Strategy"
    if canonical in {"source_asset_intake", "raw_expression_capture"}:
        return "Collect"
    if canonical in {"creation_decision_brief", "external_research_brief", "candidate_backlog_triage", "topic_candidate_selection", "platform_hotlist"}:
        return "Decide"
    if canonical in {"creator_brief_to_draft", "shooting_execution_plan"} or capability.startswith("selfmedia_creation"):
        return "Create"
    if canonical == "style_polish_run":
        return "Polish"
    if canonical in {"creation_checklist_lookup", "work_acceptance_report", "publish_readiness_gate"}:
        return "Verify"
    if canonical == "publishing_pack_build":
        return "Publish"
    if canonical in {"post_review_signal", "manual_review_note"}:
        return "Learn"
    if canonical in {"daily_journal_entry", "weekly_self_model_summary"}:
        return "Daily"
    if canonical in {"owned_media_account_lookup", "track_registry_lookup", "track_creator_membership_query"}:
        return "Entity"
    if canonical in {"document_semantic_merge", "document_edit"} or capability in {"universal_deletion", "document_edit"}:
        return "Govern"
    return "Operate"


def _default_produces(canonical: str) -> tuple[str, ...]:
    spec = get_capability_spec(canonical)
    if spec is not None:
        return spec.produces
    mapping = {
        "daily_journal_entry": ("DailyJournalEntry",),
        "weekly_self_model_summary": ("WeeklySelfModelSummary",),
    }
    return mapping.get(canonical, ())


def _default_consumes(canonical: str) -> tuple[str, ...]:
    spec = get_capability_spec(canonical)
    if spec is not None:
        return spec.consumes
    mapping = {
        "weekly_self_model_summary": ("DailyJournalEntry",),
    }
    return mapping.get(canonical, ())


def _default_writes_to(canonical: str, capability: str) -> tuple[str, ...]:
    spec = get_capability_spec(canonical)
    if spec is not None:
        return spec.writes_to
    mapping = {
        "daily_journal_entry": ("/home/ubuntu/obsidian-日记/日记/YYYY-MM-DD.md",),
        "weekly_self_model_summary": ("/home/ubuntu/obsidian-日记/Archieve/YYYYMMDD-YYYYMMDD.md",),
    }
    return mapping.get(canonical, ("local_archive",) if capability in {"generic_archive", "summary"} else ())


def _default_mode(canonical: str, capability: str) -> str:
    spec = get_capability_spec(canonical)
    if spec is not None:
        return spec.default_mode
    if canonical in {"creation_checklist_lookup", "platform_hotlist"}:
        return "reply_only"
    if capability in {"universal_deletion", "document_edit"}:
        return "confirm_then_persist"
    if canonical == "publishing_pack_build":
        return "reply_and_persist"
    return "reply_and_persist"


def _default_implementation_status(canonical: str) -> str:
    spec = get_capability_spec(canonical)
    return spec.implementation_status if spec is not None else "external"


def _default_risk_level(canonical: str, capability: str) -> str:
    spec = get_capability_spec(canonical)
    if spec is not None:
        return spec.risk_level
    if capability == "universal_deletion":
        return "destructive"
    if canonical in {"publishing_pack_build", "publish_readiness_gate", "external_research_brief"}:
        return "medium"
    if capability == "document_edit":
        return "medium"
    return "low"


def _default_visibility(label: str, canonical: str, capability: str) -> str:
    if capability == "document_edit" or label == "修改":
        return "maintainer"
    return "public"


def _default_source_system(bot: str, capability: str, canonical: str) -> str:
    spec = get_capability_spec(canonical)
    if spec is not None:
        return spec.source_system
    if capability == "knowledge_delegate":
        return "knowledge"
    if bot == "Daily bot":
        return "daily"
    if bot == "Social bot":
        return "social"
    if canonical == "external_research_brief":
        return "media"
    if bot == "Knowledge bot":
        return "knowledge"
    return "media" if bot == "Media bot" else "hybrid"


def _default_ssot_refs(canonical: str, capability: str) -> tuple[str, ...]:
    spec = get_capability_spec(canonical)
    if spec is not None:
        return spec.ssot_refs
    mapping = {
        "daily_journal_entry": ("daily_journal_contract", "obsidian_daily_journal_files"),
        "weekly_self_model_summary": ("daily_journal_contract", "obsidian_daily_journal_files", "weekly_archive"),
    }
    return mapping.get(canonical, ())


def _default_frontend_group(label: str, canonical: str) -> str:
    spec = get_capability_spec(canonical)
    if spec is not None:
        return spec.frontend_group
    if canonical in {"source_asset_intake", "raw_expression_capture"}:
        return "素材 / 灵感池"
    if canonical in {"creation_decision_brief", "external_research_brief", "account_track_strategy", "platform_hotlist"}:
        return "选题与决策"
    if canonical in {"creator_brief_to_draft", "shooting_execution_plan"}:
        return "创作运行"
    if canonical == "style_polish_run":
        return "表达优化"
    if canonical in {"creation_checklist_lookup", "work_acceptance_report", "publish_readiness_gate"}:
        return "发布前 Gate"
    if canonical == "publishing_pack_build":
        return "发布准备"
    if canonical == "post_review_signal":
        return "数据复盘"
    if label in {"账号", "赛道", "博主", "博主-入库"}:
        return "账号内容地图"
    if canonical in {"daily_journal_entry", "weekly_self_model_summary"}:
        return "Daily 记录与复盘"
    return "能力目录"



TAG_CAPABILITIES: tuple[TagCapability, ...] = (
    TagCapability("思考", "deepmath_ceo_thinking_intake", "handle_思考", "接收 DeepMath CEO 原始思考，推荐可承担人员，生成不可变版本提案；批准后可创建并读回唯一正式任务", "仅接收 DeepMath 授权私聊，或显式 allowlist 群内授权提交人的 @Bot 消息；保存原文、附件与提交人后恰好调用一次结构化 LLM，分离事实/判断/假设并生成字段完整的最小实验、任务或其他候选。需要人员的候选只读 Directory 身份与部门、独立团队能力 Base 中人工确认且未过期的能力容量、实时 Tasks 和 Calendar 负荷，再由专用 LLM 推荐至多一名 DRI、一名 Reviewer和多名 Participant。公开卡片只携带不透明候选引用；人员未确认时不能批准，表单确认生成新不可变版本，批准前再次回读证据与负荷指纹。批准是执行授权，并经过唯一审批人、版本、签名、参数指纹和原子 claim 校验；修改、拒绝、仅保存、取消、过期或陈旧授权零执行。已批准且字段完整的任务创建仅写入唯一 DeepMath CEO Actions 清单，包含一名 DRI、可选 Reviewer、上海时区截止时间和一个任务提醒；只有 Tasks v2 精确读回后才成功，重放不新增，结果不确定时禁止盲重试。Calendar 与通知执行仍未开放。群内只回收件 ID，完整结果只在私聊处理", "【思考】我们是否应先用两个客户访谈验证 AI 数学助教的付费假设？", "DeepMath bot", canonical_capability_id="deepmath_ceo_thinking_intake", aliases=(), lifecycle_layer="Collect", produces=("DeepMathThinking", "DecisionCandidate", "ApprovalCandidate", "FeishuTaskReceipt"), consumes=("DeepMathOriginalEvidence", "DirectoryEvidence", "TeamCapabilityEvidence", "TasksWorkloadEvidence", "CalendarWorkloadEvidence"), writes_to=("DeepMath CEO Thinking / 思考收件箱", "DeepMath CEO Thinking / 决策池", "DeepMath CEO Thinking / 审批记录", "DeepMath CEO Actions / Feishu Tasks"), default_mode="reply_and_persist", implementation_status="implemented", risk_level="high", visibility="public", source_system="deepmath", ssot_refs=("daily.deepmath_ceo_thinking", "deepmath-ceo-thinking/ssot-development-paths.md"), requires_confirmation=True, frontend_group="DeepMath CEO Thinking"),
    TagCapability("灵感", "inspiration", "handle_灵感", "归档碎片想法和未来可展开的内容线", "详文写入 Obsidian `灵感/归档/`，周记 `# 灵感` 凝练宏观总结、5句内摘要和详情链接", "【灵感】用零基础音乐实验验证 AI 成长档案能否迁移到表达维度", produces=("InspirationArchive",), writes_to=("Obsidian 灵感/归档/*.md", "Obsidian Archieve weekly # 灵感"), implementation_status="implemented", risk_level="medium", requires_confirmation=True, source_system="knowledge"),
    TagCapability("灵感>vlog", "vlog_inspiration", "handle_灵感_vlog", "按 vlog 创作入口整理灵感和附件素材", "保存原始表达、最近上下文、附件时序索引；大文件上传 iCloud Drive，服务器只保留索引和临时缓存", "【灵感>vlog】今天散步想到一个开头：先拍路灯，再讲为什么普通人需要自己的AI工作流", "Media bot", writes_to=("Obsidian weekly # 灵感", "iCloud Drive vlog attachment index")),
    TagCapability("待办", "reminder", "handle_待办", "创建 Obsidian 待办清单或飞书提醒", "普通清单写入 Obsidian 周记顶部 `# 待办`；知识记录、素材记录或链接查看诉求也只整理成待办，不打开 Base/表格/文档、不请求飞书用户授权；有明确时间/提醒/截止时写入提醒与日程多维表格，并在 Obsidian 留带飞书记录ID的镜像 checkbox", "【待办】查看某条自媒体知识是否跟自己有关\n原链接：https://xhslink.com/xxxxx", "Daily bot"),
    TagCapability("日程", "calendar", "handle_日程", "创建飞书日历事件", "写入飞书日历，同时写入提醒与日程多维表格", "【日程】明天下午 3 点给客户回电话", "Daily bot"),
    TagCapability("日记", "daily_journal", "handle_日记", "记录每天真正值得保留的事实、情绪、判断、退缩、开发和经验", "按日写入独立 Obsidian 日记文件；模板字段和自由正文都会送入 LLM 整理成一段总结，原文保留在底部，空正文不写入；保存后同步投影到本周 Archieve 的 #YYYYMMDD -> ##日记 小节，使用 ### 主题标题和 3-5 句精炼总结；周记读取内部整理信号做索引和总结", "【日记】\n今天一句话：今天终于把 Daily 自我记录链路想清楚了\n今天最值得记录的一件事：决定把周记改成读取日记\n明天一个最小动作：晚上 22:00 填一条", "Daily bot"),
    TagCapability("待办-开发", "development_request", "handle_待办_开发", "创建正式开发任务并进入 Codex 追溯闭环", "生成正式开发任务卡，写入 Obsidian checklist 与飞书多维表格结构化台账；checklist 勾选后由 Mac 侧 Codex high 后置梳理", "【待办-开发】\n机器：VM-0-14-ubuntu\n地址：ubuntu@106.52.146.37\n任务：修复 Knowledge bot 归档后 Mac 不同步的问题\n验收：Mac 能看到新周记条目", "Daily bot"),
    TagCapability("今日", "daily_digest", "handle_今日", "查看今日提醒、日程、待办和开发任务", "读取本地归档生成轻量今日执行清单，不打开多维表格", "【今日】", "Daily bot"),
    TagCapability("周记", "weekly_self_model", "handle_周记", "每周读取日记并提取可复用的行为、情绪、决策、开发和经验信号", "读取本周独立日记文件，输出固定周记骨架和动态主题簇；少于 3 篇只写样本不足索引，不生成稳定模式结论", "【周记】20260525-20260531", "Daily bot"),
    TagCapability("衣橱", "wardrobe_item_ingest", "handle_衣物_入库", "把衣物实物照、淘宝标题、订单截图、洗标或吊牌整理进衣橱，并作为穿搭工作流主入口", "生成系统衣物ID，LLM 只写契约允许字段，Python 写入 Feishu 多维表 `衣橱`；后补截图必须带衣物ID，无法关联时返回 pending，不猜测更新对象", "【衣橱】优衣库黑色速干T，运动和通勤都能穿", "Daily bot", canonical_capability_id="wardrobe_item_ingest", aliases=(), lifecycle_layer="Daily", produces=("WardrobeItem",), consumes=("UserUpload", "WardrobeItemEvidence"), writes_to=("Feishu Bitable 衣橱 / WARDROBE_ITEMS_URL",), implementation_status="implemented", risk_level="medium", visibility="public", source_system="daily", ssot_refs=("wardrobe_os_v2", "docs/ai-harness/wardrobe-model-contract.json"), frontend_group="衣橱 / 穿搭"),
    TagCapability("穿搭", "wardrobe_recommendation", "handle_穿搭", "读取 Wardrobe OS 单品库，结合当前位置、自动天气和日程上下文生成今日穿搭或旅行行李建议", "只生成 Obsidian `物品/*.md` 推荐 artifact，不回写衣橱事实；用户可给当前位置/目的地，或由同次 Daily/待办/日程上下文的显式地点字段提供位置；系统通过 Open-Meteo 自动查天气；缺少位置或天气服务不可用时返回 pending，不用历史消息或普通待办正文猜测", "【穿搭】位置：深圳，今天通勤，晚上可能跑步", "Daily bot", canonical_capability_id="wardrobe_recommendation", aliases=(), lifecycle_layer="Daily", produces=("WardrobeRecommendationMarkdown",), consumes=("WardrobeItem", "DailyContext", "WeatherContext", "CurrentLocation"), writes_to=("Obsidian 物品/*.md",), implementation_status="implemented", risk_level="medium", visibility="public", source_system="daily", ssot_refs=("wardrobe_os_v2", "docs/ai-harness/wardrobe-model-contract.json", "docs/ai-harness/wardrobe-context-contract.json"), frontend_group="衣橱 / 穿搭"),
    TagCapability("开发-完成", "development_status_update", "handle_开发_完成", "标记开发需求完成", "按任务ID或关键词把开发需求卡更新为已完成", "【开发-完成】修复 Knowledge bot 归档后 Mac 不同步的问题", "Daily bot"),
    TagCapability("开发-验证", "development_status_update", "handle_开发_验证", "标记开发需求进入待验证", "按任务ID或关键词把开发需求卡更新为待验证", "【开发-验证】修复 Knowledge bot 归档后 Mac 不同步的问题", "Daily bot"),
    TagCapability("策略", "media_growth_strategy", "handle_media_growth", "MediaClaw v2 策略层入口（规划中），围绕自有账号、平台和赛道整理内容打法问题", "规划中；当前只接收输入并返回 not_implemented/待人工处理，不生成策略 artifact，不写 Feishu 表，也不把外部博主档案当自有账号画像", "【策略】账号=小王 平台=抖音 赛道=校园体育 目标=明确下月内容支柱", "Media bot"),
    TagCapability("Brief", "media_growth_commercial_brief", "handle_media_growth", "整理品牌或商单拍摄 Brief，并形成后续创作/拍摄可引用的结构化依据", "生成 CommercialBrief artifact，写入 media_vault/commercial_briefs；只整理和落盘 brief，不直接创建 03_CreationRuns，不替代发布前甲方确认", "【Brief】\n平台：抖音/小红书\nBrief：粘贴品牌拍摄要求全文\n目标：整理成后续拍摄执行可引用的结构化 brief", "Media bot"),
    TagCapability("素材", "media_growth_collect", "handle_media_growth", "MediaClaw v2 Collect 层唯一素材入口，归一链接、粘贴文字、活动 brief、转写稿文字和原始表达", "生成 SourceAsset artifact，默认 quality_status=pending_review；素材入口只保留【素材】，下游按用途进入暂存、入库、拆解、选题、创作或拍摄；当前入口不消费二进制附件", "【素材】\n素材类型：链接\n用途：暂存 / 入库 / 拆解 / 选题 / 创作 / 拍摄\n平台：小红书\n链接或文字素材：http://xhslink.com/o/16704LMMFPp\n补充说明：判断能不能做成个人表达选题", "Media bot"),
    TagCapability("选题", "media_growth_decide", "handle_media_growth", "MediaClaw v2 Decide 层入口，把素材、调研或复盘信号整理成可判断的选题 brief", "生成 DecisionBrief artifact，默认 pending_review；当前是证据整理/缺口标注，不等同完整 LLM 选题判断", "【选题】账号=小王 平台=抖音 赛道=校园体育 来源=source_asset_xxx 目标=判断下周是否拍", "Media bot"),
    TagCapability("拍摄", "media_growth_shoot", "handle_media_growth", "MediaClaw v2 拍摄执行入口，把已确认选题或草稿转成拍摄执行计划", "委托既有【创作-拍摄执行】链路生成拍摄执行单，并写入创作任务池子文档和 03_CreationRuns_创作运行可读运行索引；Growth 不复制第二套拍摄 runner", "【拍摄】平台=抖音 主体=校园体育训练复盘 拍摄目标=拍出训练前后变化 场地=操场 人物=我", "Media bot"),
    TagCapability("检查", "media_growth_verify", "handle_media_growth", "MediaClaw v2 Verify 层统一入口，按输入自动分流到清单查询、作品验收或发布前 gate", "当前由既有【创作检查】/【作品验收】链路承担；发布包 readiness gate runner 尚未本地接入，不伪造 gate 结果", "【检查】run_id=creation_run_123 目标=发布前检查", "Media bot"),
    TagCapability("发布包", "media_growth_publish_pack", "handle_media_growth", "MediaClaw v2 发布准备入口，只整理标题、封面、正文、标签、评论引导和发布前检查项", "生成 PublishingPack artifact，默认 pending_review；可用 草稿=/正文= 直接给正文，也可用 draft_id=/run_id= 引用既有 creation run；不自动发布，不生成已完成的 readiness gate 结论", "【发布包】平台=抖音 draft_id=creation_run_123", "Media bot"),
    TagCapability("复核", "media_growth_review", "handle_media_growth_review", "MediaClaw v2 artifact 人工复核入口", "按 artifact_id/source/artifact_ref 定位 media_vault artifact，执行通过复核、标记 verified 或废弃；写回原 result.json 并保留 review_history", "【复核】artifact_id=source_asset_20260704_001 动作=通过 备注=证据够用", "Media bot"),
    TagCapability("账号", "media_growth_owned_account", "handle_media_growth", "自有账号实体入口（规划中），用于定位 OwnedMediaAccount 与账号内容地图", "规划中；只代表自有账号，不读取或写入 06_CreatorProfiles 外部达人档案；当前返回 not_implemented/待人工处理，不新建 Feishu 字段", "【账号】平台=抖音 账号=小王 目标=查看内容定位", "Media bot"),
    TagCapability("赛道", "media_growth_track", "handle_media_growth", "查询或由维护者显式注册统一赛道实体", "读取 07_TrackRegistry_赛道注册表；动作=注册仅接受 Web 管理员 + TOTP 维护者会话，按赛道 ID/名称幂等写入 canonical TrackRegistry；普通租户只读，不从标签、简介或相似度合成赛道", "【赛道】\n动作：注册\n赛道名称：校园体育\n别名：高校体育、大学生运动\n适用平台：小红书、抖音", "Media bot", canonical_capability_id="track_registry_lookup", lifecycle_layer="Entity", produces=("TrackRegistry",), writes_to=("07_TrackRegistry_赛道注册表",), implementation_status="implemented", risk_level="medium", source_system="media", ssot_refs=("TrackRegistry", "docs/ai-harness/media-model-v2-contract.json"), frontend_group="账号内容地图"),
    TagCapability("赛道-关系", "media_growth_track_membership", "handle_media_growth", "查询、预览或确认赛道与博主档案关系", "读取 R03_TrackCreatorMembership；只有动作=关系确认、确认=是且包含角色、匹配分、匹配理由和证据引用时才写入。证据不足返回 pending_manual，禁止从标签、简介或相似度自动猜测", "【赛道-关系】\n动作：关系确认\n赛道ID：track_xxx\n达人档案ID：creator_xxx\n角色：标杆账号\n匹配分：90\n匹配理由：\n证据引用：https://...\n确认：是", "Media bot", canonical_capability_id="track_creator_membership_query", lifecycle_layer="Entity", produces=("TrackCreatorMembership",), consumes=("TrackRegistry", "CreatorProfile"), writes_to=("R03_TrackCreatorMembership_赛道博主关系",), implementation_status="implemented", risk_level="medium", source_system="media", ssot_refs=("TrackRegistry", "CreatorProfile", "docs/ai-harness/media-model-v2-contract.json"), frontend_group="账号内容地图"),
    TagCapability(
        "热榜",
        "platform_hotlist",
        "handle_热榜",
        "按平台、关键词、时间和标签查询可核验的小红书或抖音内容，并按点赞或发布时间排序",
        "先从公开搜索索引发现候选，再回读平台作品页核验 URL、标题、作者、点赞数和发布时间；结果仅代表本次可读取候选，不是平台官方全站榜；来源不可读时返回 pending_manual，不落盘、不伪造指标",
        "【热榜】\n平台：抖音\n关键词：脑机接口\n时间：近7天\n标签：WAIC, 前沿科技\n排序：点赞降序\n数量：20",
        "Media bot",
        canonical_capability_id="platform_hotlist",
        aliases=(),
        lifecycle_layer="Decide",
        produces=("VerifiedHotlistResult",),
        consumes=("Keyword", "TimeWindow", "PlatformPublicContent"),
        writes_to=("none",),
        default_mode="reply_only",
        implementation_status="implemented",
        risk_level="medium",
        visibility="public",
        source_system="media",
        ssot_refs=("selfmedia.hotlist.service.HotlistService", "platform_share_page", "brave_web_search"),
        frontend_group="选题与决策",
    ),
    TagCapability("活动", "activity", "handle_活动", "保存并压缩平台活动 Brief", "写入“近期活动”多维表格；需要长期 Markdown 时沉淀到 /home/ubuntu/obsidian-自媒体/02_选题活动/", "【活动】\n平台：小红书\n活动链接：https://example.com/activity\n活动标题：校园运动季", "Media bot", writes_to=("01_近期活动", "/home/ubuntu/obsidian-自媒体/02_选题活动/"), implementation_status="external"),
    TagCapability("修改", "document_edit", "handle_修改", "定向修改已有飞书文档", "读取正文显式链接或被回复的飞书 Docx 文档并识别文档家族；链接后紧贴“90秒/分钟/帧”等修改范围时，先分离真实 Feishu token 和范围文本，预检失败只返回稳定错误码，不暴露 API body、log_id 或排障链接。普通文档走分块文本 patch；拍摄执行文档必须唯一映射原 CreationRun，先生成并审核结构化叙事规划，再按规划整份重写并逐镜审核相邻转场、主体回流和场地跳转；连贯性低于90分或任何问题未清零时禁止写入，通过后才由 canonical shooting renderer 清空重建同一链接，分镜保持置顶、证据附录不展示，发布包用下一级标题明确区分作品标题、封面图方案、发布文案、话题互动和声音方案；不允许在拍摄执行回洗失败后降级到通用 patch。商单交付图片脚本原生表格补足行走 insert_table_row，并同步 COM01 契约。约束（选填）用于声明必须保护的标题、表格、事实或章节。", "【修改】\n文档链接：https://tcnwueberajc.feishu.cn/wiki/xxxx\n修改要求：根据客户反馈调整分镜、路线、必拍项和发布包，保持原产品事实与合规要求\n约束：保护原有产品事实、合规要求和未指定修改的原生表格", "Media bot", canonical_capability_id="document_edit", aliases=(), lifecycle_layer="Govern", produces=("FeishuDocxDocument",), consumes=("FeishuDocxDocument", "DocumentEditRequest", "CreationRun"), writes_to=("Feishu Docx explicit/replied target document", "media://tenants/<tenant_id>/creation_runs/<run_id>"), implementation_status="implemented", risk_level="medium", visibility="maintainer", source_system="media", ssot_refs=("document_edit_contract", "docs/ai-harness/media-creation-skill-reuse-contract.md"), frontend_group="文档维护"),
    TagCapability("拆解", "viral_deconstruction", "handle_拆解", "逐镜头拆解短视频/图文素材", "调用 selfmedia.deconstruct.viral_content 生成爆款拆解文档并写入拆解记录；同款拆解/结构库 Markdown 写入 /home/ubuntu/obsidian-自媒体/05_素材与爆款库/同款拆解/ 或 结构库/", "【拆解】https://v.douyin.com/xxxxx 重点看开头钩子和转场", "Media bot", writes_to=("02B_DeconstructionRuns_拆解运行", "/home/ubuntu/obsidian-自媒体/05_素材与爆款库/")),
    TagCapability("创作", "selfmedia_creation", "handle_creation", "按平台生成创作初稿", "同一创作链统一调用 media_creation；读取活动、素材/拆解、创作模式和商务机会，创建创作文档到创作任务池，并写入 03_CreationRuns_创作运行可读运行索引；正文明确立项/初稿目标时创建 Content OS 项目包；只有存在本地素材绑定线索或 Mac 回写结果时，才创建或推进 Mac 素材匹配任务；不建立第二套 handler 或 writer", "【创作】项目=20260520_400米比赛_第一视角 平台=抖音 类型=视频 赛道=体育 主体=第一视角挑战400米进53秒", "Media bot", writes_to=("03_CreationRuns_创作运行", "Feishu Docx creation task child document", "Content OS project package")),
    TagCapability("创作>小红书", "selfmedia_creation", "handle_creation", "小红书创作入口", "统一调用 media_creation；按明确类型生成小红书图文或视频稿件，创建创作任务池子文档，并写入 03_CreationRuns_创作运行可读运行索引", "【创作>小红书】类型=图文 赛道=职场成长 主体=25岁女生如何提升表达力 发布时间=今晚8点", "Media bot"),
    TagCapability("创作>抖音", "selfmedia_creation", "handle_creation", "抖音创作入口", "统一调用 media_creation；按明确类型生成抖音图文或视频稿件，创建创作任务池子文档，并写入 03_CreationRuns_创作运行可读运行索引", "【创作>抖音】类型=视频 赛道=体育 主体=毕业季田径比赛 发布时间=今晚8点", "Media bot"),
    TagCapability("创作-拍摄执行", "selfmedia_shooting_execution", "handle_shooting_execution", "把明确主题、场景、人物、参考和素材约束转换成拍摄执行单", "生成路线、镜头、人员、场地、B方案、现场 checklist、交付物清单和发布包；发布包用下一级标题明确区分作品标题、封面图方案、发布文案、话题互动和声音方案；写入创作任务池子文档和 03_CreationRuns_创作运行可读运行索引", "【创作-拍摄执行】平台=抖音 类型=视频 主体=毕业季田径比赛 拍摄目标=记录比赛过程和毕业氛围 场地=操场 人物=我和同学", "Media bot", implementation_status="external"),
    TagCapability("创作咨询", "selfmedia_creation_consultation", "handle_创作咨询", "基于现有数据表回答创作决策问题", "读取爆款内容积累表、近期活动、商务候选、账号记忆和复盘，输出创作建议，不新建文档", "【创作咨询】平台=小红书 账号=主账号 问题=我最近适合做什么选题？", "Media bot"),
    TagCapability("数据复盘", "selfmedia_data_review", "handle_数据复盘", "根据后台数据截图做作品复盘", "使用时先上传抖音或小红书后台数据截图，再发送【数据复盘】指令；系统复用飞书附件 batch 识别指标，整理复盘结论并写入数据复盘表、复盘文档和媒体账号记忆；正文带项目时同步写入项目内 10_review.md 并按状态机推进", "【数据复盘】平台=小红书 账号=主账号 项目=20260520_400米比赛_第一视角 复盘节点=24小时", "Media bot", canonical_capability_id="selfmedia_data_review", lifecycle_layer="Learn", produces=("PostReview", "MetricSnapshot"), consumes=("PublishedPost", "MetricScreenshot"), writes_to=("media://tenants/<tenant_id>/published_posts/*/review", "post_reviews", "metric_snapshot", "Content OS 10_review.md"), implementation_status="external", risk_level="medium", visibility="ops", source_system="media", ssot_refs=("selfmedia.review.data_review.handle_data_review_command", "post_reviews", "metric_snapshot"), frontend_group="数据复盘"),
    TagCapability("自媒体-认知", "selfmedia_cognition_accumulation", "handle_selfmedia_cognition", "沉淀或纠正自媒体认知", "由 OpenClaw 判断赛道和主旨，写入自媒体认知池子文档；同标题文档会整合覆盖更新", "【自媒体-认知】我以前以为低粉爆款说明账号方向对了，但现在看只能说明单条内容成立", "Media bot", writes_to=("Feishu Docx selfmedia cognition pool child document",)),
    TagCapability("创作检查", "selfmedia_checklist_lookup", "handle_创作检查", "查看创作相关检查清单", "根据正文场景返回可审阅的 checklist 云文档链接，不新建文档、不写入版本", "【创作检查】作品发布前看哪个清单？", "Media bot"),
    TagCapability("作品验收", "selfmedia_work_acceptance", "handle_作品验收", "逐项对照创作要求验收作品", "读取作品内容和创作要求，逐项判定满足、不满足或不确定，并给出证据、缺口和修改建议；正文带项目且验收通过时按状态机推进项目状态", "【作品验收】项目=20260520_400米比赛_第一视角 目标状态=final_ready 成片路径=/Users/.../Final.mp4 创作要求：... 作品内容：...", "Media bot"),
    TagCapability("润色", "style_polish", "handle_style_polish", "把已有文案改成自然、可直接发布的表达", "读取账号记忆与平台边界后由 Media 写作模型改写；聊天只返回成稿，诊断、评分和 source_trace 仅写 media_vault/style_polish_runs", "【润色】\n平台：抖音\n内容类型：标题/正文/封面文案\n目标：更有网感但不要编造事实\n原文：我想说明训练不是靠鸡血，而是靠复盘和稳定执行。", "Media bot"),
    TagCapability("网感", "style_polish", "handle_style_polish", "把平台表达写得更像真人内容", "复用唯一 style_polish LLM editor；减少模板腔和术语堆叠，不新增事实，不自动晋升 CreativePattern", "【网感】\n平台：小红书\n原文：这个训练方法其实适合没时间的人。", "Media bot"),
    TagCapability("文案优化", "style_polish", "handle_style_polish", "优化标题、正文、封面文案或评论回复", "复用唯一 style_polish LLM editor；默认只返回一个可直接使用的成稿，完整审计信息留在内部 artifact", "【文案优化】\n平台：抖音\n原文：我想把跑步复盘讲得更像短视频。", "Media bot"),
    TagCapability("改标题", "style_polish", "handle_style_polish", "只改标题或封面短句", "复用唯一 style_polish LLM editor；保留 must_keep 事实和 avoid 边界，不造数据或身份", "【改标题】\n平台：小红书\n必须保留：清华、短跑\n原文：清华学生为什么还要练短跑", "Media bot"),
    TagCapability("去AI味", "style_polish", "handle_style_polish", "把书面腔和模板腔改成自然中文", "复用唯一 style_polish LLM editor；先按 30 秒口头转述重组表达，只交付成稿，不生成新事实或新账号人格", "【去AI味】\n平台：抖音\n原文：在当今时代，训练和复盘具有重要意义。", "Media bot"),
    TagCapability("小红书文案", "style_polish", "handle_style_polish", "面向小红书的自然标题、正文和封面文案", "复用唯一 style_polish LLM editor；用第一人称现场感、短段落和具体判断改写，平台依据来自 config/platform_mechanisms/xiaohongshu.json", "【小红书文案】\n内容类型：图文标题\n原文：普通人怎么建立自己的内容复盘系统", "Media bot"),
    TagCapability("抖音文案", "style_polish", "handle_style_polish", "面向抖音的自然标题、正文和开场口播", "复用唯一 style_polish LLM editor；保留口头节奏和具体动作，平台依据来自 config/platform_mechanisms/douyin.json", "【抖音文案】\n内容类型：视频开头\n原文：我今天想讲一个关于训练复盘的反直觉想法", "Media bot"),
    TagCapability("删除", "universal_deletion", "handle_删除", "按明确 ID 预览或确认删除任意能力产生的运行产物", "逐项列出并删除 archive/inbox、json、markdown、转写中间产物、创作运行记录、文档或本地文件；公开 review_ 复盘引用先级联删除并读回全部 H01 指标快照，再删除并读回 04 发布复盘主记录；未确认只预览", "【删除】20260412-030515-qq-灵感-0056", visibility="maintainer"),
    TagCapability("自媒体知识", "selfmedia_knowledge", "handle_自媒体知识", "按自媒体知识链路处理图文/视频链接", "根据链接内容自动识别图文、公众号文章或视频；所有平台均保留原始 HTML、图片、OCR、转写和文案证据，但名称、全部文案、全部内容、摘要、分类、标签、问题和应用建议只接受带版本标记的 LLM 清洗结果；飞书写入还会核验 LLM 来源、原始证据位置和字段完整性。公众号动态页面以 picture_page_info_list 的全量原图清单为准，逐张 OCR 后先由 LLM 保真清洗全文，再生成结构化分析；任一图片缺失、损坏、尺寸不足、OCR 缺页、LLM 清洗字段缺失、写入凭据不一致或来源提取失败即停止入库并进入 pending_manual；历史记录不由普通消息隐式回洗", "【自媒体知识】https://mp.weixin.qq.com/s/xxxxx", "Knowledge bot"),
    TagCapability(
        "转写",
        "transcription",
        "handle_转写",
        "异步提取录音逐字稿并生成细节保真的会议纪要",
        "Knowledge Bot 收到每条裸音频后，按飞书 message ID 只绑定该消息自己的 MediaPath，自动创建独立持久化任务并立即返回任务 ID，无需二次确认；同一 message ID 重放只返回原任务，不重复创建。Daily Bot 继续按当前会话关联未消费录音、返回文件名和批次号，并在用户确认批次后入队。独立 worker 按持久化 enqueue_order 严格 FIFO 处理，并由发起任务的 Bot 主动推送 ASR、整理、完成或失败阶段。整理阶段先识别稳定对话人物及其会议角色，再按角色注册表逐段重洗文字稿；每个来源小段必须由 LLM 标记为保留后的具体内容、语义完全重复或纯噪声，缺段、未知角色、过多丢弃或明显过度压缩都会阻断完成。主纪要固定为“1 结论摘要、2 决策清单、3 议题分析与行动项、4 下次会议、5 细节保全附录（受限）、6 关联文档”：detail_coverage 与敏感权限信息逐条写入第 5 节正文；任何有业务含义的敏感细节都不能删除、泛化或省略，敏感性只允许标记可见范围、核验状态和公开权限。结论摘要和各清单不限制篇幅；行动项只记录来源中确实承诺或委派且负责人、交付物、验收标准、截止时间和依赖关系有依据的事项。需要独立展开的专题材料仅在非空时另存 Obsidian 专题附件文档，并从第 6 节关联文档超链接；原字稿单独保存角色识别结果、角色化文字稿和原始转录。全局 schema 修复默认最多 3 次且硬上限 5 次；每轮一致性定向修订后必须先通过 schema 再复检，坏 JSON 记为该轮失败并继续有界重试，只有耗尽上限或无法修订时才转人工。完成后覆盖写入 Obsidian 会议纪要和原字稿，周记只留宏观总结、5句内摘要和链接",
        "【转写】",
        "Daily bot",
        consumes=(
            "Knowledge Bot 单条裸音频的飞书 message ID 与独立 MediaPath",
            "Daily Bot 当前会话未消费录音附件",
            "Daily Bot 用户确认的转写批次",
        ),
        produces=("TranscriptionBatch", "TranscriptionJob", "RawTranscript", "MeetingNote", "RestrictedDetailAppendix"),
        writes_to=(
            "Local JSON / openclaw-tag-router/transcription-queue",
            "Local JSON / openclaw-tag-router/transcription-jobs",
            "Obsidian / 会议纪要/整理版（含受限细节附录） + 会议纪要/原字稿 + 非空时的会议纪要/专题附件",
            "Feishu 发起任务的 Bot / 即时回执、阶段与最终主动通知",
        ),
        source_system="feishu",
        ssot_refs=(
            "selfmedia-tools/openclaw-tag-router/transcription-queue.js",
            "selfmedia-tools/openclaw-tag-router/transcription-job-queue.js",
            "selfmedia-tools/openclaw-tag-router/transcription_worker.py",
            "selfmedia-tools/openclaw-tag-router/openclaw_app/router/transcription.py",
            "obsidian-日记/公共开发集/daily/2026-07-18/daily-transcription-async-task/异步转写任务管线.md",
        ),
        requires_confirmation=True,
    ),
    TagCapability("转写-文字", "transcription_text", "handle_转写_文字", "整理已有语音转文字稿", "不重新执行 ASR；合并正文或文字附件后，先识别稳定对话人物及其会议角色，再按角色注册表逐段重洗文字稿。每个来源小段由 LLM 标记为保留、语义完全重复或纯噪声，并用角色覆盖、来源覆盖和保真比例阻断未知角色、缺段和过度压缩。主纪要固定为“1 结论摘要、2 决策清单、3 议题分析与行动项、4 下次会议、5 细节保全附录（受限）、6 关联文档”：detail_coverage 与敏感权限信息逐条写入第 5 节；任何有业务含义的敏感细节都不能删除、泛化或省略，敏感性只允许标记可见范围、核验状态和公开权限。结论摘要和各清单不限制篇幅，开放问题、验证假设、风险与约束并入结论摘要且不重复；行动项只记录来源中确实承诺或委派且负责人、交付物、验收标准、截止时间和依赖关系有依据的事项。需要独立展开的专题材料仅在非空时另存 Obsidian 专题附件文档并从第 6 节关联文档超链接；原字稿单独保存角色识别结果、角色化文字稿和原始转录。全局 schema 修复默认最多 3 次且硬上限 5 次；每轮一致性定向修订后必须先通过 schema 再复检，坏 JSON 记为该轮失败并继续有界重试，只有耗尽上限或无法修订时才转人工；周记只留宏观总结、5句内摘要和链接", "【转写-文字】\n主题：会议主题\n文字稿：已经由语音转文字得到的文本", "Daily bot", produces=("RawTranscript", "MeetingNote", "RestrictedDetailAppendix", "TopicalAttachment"), writes_to=("Obsidian / 会议纪要/整理版（含受限细节附录） + 会议纪要/原字稿 + 非空时的会议纪要/专题附件",)),
    TagCapability("商务>ID", "id_business", "handle_id_business", "查询达人档案并处理 PR 商务信息", "先读 06_CreatorProfiles 的 canonical 达人身份与主页，再读写 05A/05B 商务事实；用户确认默认口径只补空缺的可协商字段，不覆盖账号/项目事实或报价；最终回复首行固定为“老师您好，这里是xx博主”，随后严格按对方提问字段和顺序逐行回答。小红书截图只有在真实主页内容可见时才算成功，登录页、空白页和安全限制页不得归档为有效主页截图", "【商务>ID】\n平台：小红书\n账号名称：示例博主\n补充说明：PR 询问主页链接，请生成可直接发送的回复", "Media bot", writes_to=("05A_PRContacts_PR联系人", "05B_BusinessOpportunities_商务候选")),
    TagCapability("商单交付", "commercial_delivery", "handle_商单交付", "根据品牌、产品、创作方向、Tags、可用博主档案和平台要求生成商单交付初稿", "创建飞书云文档子页面，设置为互联网所有人可编辑；文档必须包含单一标题、完整可直接发布正文、独立 Tags，以及原生表格承载图片脚本/分镜脚本；用户已给标题时沿用，未给标题时才生成一个可发布标题；不把多标题、正文和 CTA 混在一起；并把作品初稿链接、初稿时间、发布时间等摘要写入 COM01_CommercialDelivery_商单交付；PR备注选填，未填默认无特殊要求", "【商单交付】\n品牌：\n产品：\n博主名称：XXX\n平台：小红书\n内容形式：图文\n内容规格：5张图\n初稿时间：7月8日 18:00 前提交初稿\n发布时间：7月10日 20:00-22:00\n创作方向：\n产品卖点：\nTags：#品牌词 #产品词 #场景词\n标题（选填；已填则沿用，未填才生成）：\n博主人设 / 语气（选填；未填则从博主档案读取）：\n平台要求 / 禁区（选填；未填默认无特殊要求）：\nPR备注（选填；未填默认无特殊要求）：", "Media bot", canonical_capability_id="commercial_delivery_draft", aliases=(), lifecycle_layer="Create", produces=("CommercialDeliveryDraft", "FeishuDocxChildPage", "CommercialDeliveryRecord"), consumes=("BrandBrief", "ProductSellingPoints", "CreatorPersona", "PlatformRequirement"), writes_to=("Feishu Docx 子页面 / MEDIA_OS_COMMERCIAL_DELIVERY_PARENT_NODE_TOKEN", "Feishu Bitable COM01_CommercialDelivery_商单交付 / MEDIA_OS_COMMERCIAL_DELIVERY_URL"), implementation_status="implemented", risk_level="medium", visibility="public", source_system="media", ssot_refs=("commercial_delivery_contract", "docs/ai-harness/commercial-delivery-contract.json", "obsidian-日记/公共开发集/media/2026-07-05/commercial-delivery-capability/ssot-development-paths.md"), frontend_group="商务 / 商单交付"),
    TagCapability("博主", "creator_profile_lookup", "handle_博主", "查询外部达人、竞品或合作博主档案", "只读 06_CreatorProfiles_达人账号档案并返回外部系统唯一ID、账号名称、作者ID、主页链接、结构化身份信息、当前指标和档案链接；不执行入库，所有写入统一使用带确认策略的【博主-入库】；不是自有账号画像入口。商单交付继续使用独立【商单交付】入口", "【博主】\n能力：查询\n信息：小王", "Media bot", lifecycle_layer="Entity", produces=("CreatorProfile",), consumes=("06_CreatorProfiles_达人账号档案",), implementation_status="implemented", risk_level="low", source_system="media", ssot_refs=("CreatorProfile", "docs/ai-harness/media-model-v2-contract.json"), frontend_group="账号内容地图"),
    TagCapability("博主-入库", "creator_profile_upsert", "handle_博主_入库", "维护外部达人、竞品或合作博主账号身份字段", "统一 CreatorProfile v2 入库工作流：账号类型/内容领域复用 canonical expertise_domains，不新建 creator_type；支持手工字段 upsert、JSON 数组或空行/---分隔的批量入库，批量分支逐条复用同一单条 upsert 并返回逐行结果；支持从抖音或小红书主页链接解析平台、作者ID和账号名称并生成 candidate-only；解析证据不足时 pending/manual；用户用 run_id 确认后才写入 06_CreatorProfiles_达人账号档案，并在确认写入成功后写 H02_AccountMetricSnapshot_账号指标快照；不写 OwnedMediaAccount", "【博主-入库】\n主页链接：https://v.douyin.com/SJjgn_2KjYs/", "Media bot", lifecycle_layer="Entity", produces=("CreatorProfile", "AccountMetricSnapshot"), writes_to=("06_CreatorProfiles_达人账号档案", "H02_AccountMetricSnapshot_账号指标快照"), implementation_status="implemented", risk_level="medium", source_system="media", ssot_refs=("CreatorProfile", "AccountMetricSnapshot", "docs/ai-harness/media-model-v2-contract.json"), requires_confirmation=True, frontend_group="账号内容地图"),
    TagCapability("归档", "knowledge_delegate", "delegate:knowledge", "通用知识入口", "转交 knowledge Bot 处理", "【归档】2025-12-03 学习/知识相关内容...", "Knowledge bot"),
    TagCapability("补全", "knowledge_delegate", "delegate:knowledge", "通用知识补全入口", "转交 knowledge Bot 补齐内容", "【补全】2025-12-03 一段已转写文字...", "Knowledge bot"),
    TagCapability("认知", "knowledge_delegate", "delegate:knowledge", "通用认知沉淀入口", "详文写 `认知/`，周记 `# 认知` 留宏观总结、5句摘要和链接；默认不写飞书", "【认知】短期反馈不能代表长期能力", "Knowledge bot"),
    TagCapability("学习", "knowledge_delegate", "delegate:knowledge", "通用学习入口", "转交 knowledge Bot 沉淀学习资料", "【学习】API", "Knowledge bot"),
    TagCapability("学习-整理", "knowledge_delegate", "delegate:knowledge", "通用学习整理入口", "转交 knowledge Bot，强制按整理类沉淀学习资料", "【学习-整理】一段课程笔记或 AI 回答...", "Knowledge bot"),
    TagCapability("调研", "media_growth_research", "handle_media_growth", "MediaClaw 证据驱动调研入口", "生成 ExternalResearchBrief；只接收显式证据或链接摘要，无外部取证证据时返回 pending_manual，不把空壳 brief 当成研究结论", "【调研】账号=小王 平台=抖音 赛道=校园体育 问题=最近校园体育内容有哪些可做角度？", "Media bot", source_system="media"),
    TagCapability("社交", "social_archive", "handle_社交", "构建多维结构化人物档案", "分层生成/更新人物、原子主张、互动、关系快照、本人自述和行动事项等结构化档案，并生成 Obsidian 多文件阅读视图；异性关系可交付飞书云文档；不写飞书多维表格", "【社交】对象：美汁源 将这批截图写入结构化人物档案并生成阅读视图", "Social bot"),
    TagCapability("人脉", "contact_archive", "handle_人脉", "处理无性关系/合作人脉档案", "生成/更新人脉档案，只写本地与 Obsidian；不写飞书云文档，不写飞书多维表格", "【人脉】对象：张三 微信备注：张总-AI教育 记录今天聊到的需求和下次跟进", "Social bot"),
    TagCapability("复盘", "generic_archive", "handle_generic", "记录项目/内容/账号复盘", "默认本地归档并可同步飞书；Media bot 中显式 `流程=metrics_to_next_topics` 时写入 ReviewSignal artifact 并可续接【选题】", "【复盘】流程=metrics_to_next_topics 平台=小红书 播放=1000 收藏=300 结论=收藏明显高于点赞 下一步=做收藏理由拆解"),
    TagCapability("整理", "summary", "handle_整理", "汇总最近记录", "生成最近记录摘要", "【整理】最近10条素材", produces=("RecentRecordsSummary",), writes_to=("local archive", "configured Feishu document"), implementation_status="implemented", risk_level="medium", requires_confirmation=True),
    TagCapability("说明", "system", "handle_说明", "唯一的 Bot 能力文档、精确介绍和自然语言可执行路径引导入口", "空正文只返回总文档与当前 Bot 文档；指定公开能力时返回其用途、输入、产出和状态；描述需求时由 LLM 基于真实能力和用户资料给出需求理解、选路原因及当前完整可复制指令。多步骤只开放当前可执行步骤，真实上游结果绑定后才生成下一段指令；无法安全选路时明确说明未生成业务回复及缺少的事实。商务 PR 场景缺少博主 ID 或其他账号身份时必须直接说明，不得静默；不执行任何业务动作", "【说明】我有一条 AI 视频，想拆解后改成小红书稿"),
    TagCapability("最近", "system", "handle_最近", "查询最近归档", "返回最近 N 条记录", "【最近】10"),
    TagCapability("同步", "system", "handle_同步", "补同步未同步记录", "尝试同步最近未同步记录到飞书", "【同步】飞书", produces=("SyncReceipt",), writes_to=("configured Feishu destination", "local archive"), implementation_status="implemented", risk_level="medium", requires_confirmation=True),
    TagCapability("状态", "system", "handle_状态", "查询任务状态", "按任务 ID 或最近任务返回状态", "【状态】20260509-082057-feishu-自媒体知识-b4ef"),
)

TAG_LABELS: tuple[str, ...] = tuple(capability.label for capability in TAG_CAPABILITIES)
UNIVERSAL_KNOWLEDGE_TAGS: set[str] = {capability.label for capability in TAG_CAPABILITIES if capability.capability == "knowledge_delegate"}
MEDIA_RESEARCH_TAGS: set[str] = {capability.label for capability in TAG_CAPABILITIES if capability.canonical_capability_id == "external_research_brief"}
RESEARCH_KNOWLEDGE_TAGS = MEDIA_RESEARCH_TAGS
GENERIC_TAGS: set[str] = {capability.label for capability in TAG_CAPABILITIES if capability.handler == "handle_generic"}
SYSTEM_TAGS: set[str] = {capability.label for capability in TAG_CAPABILITIES if capability.capability == "system"}


def tag_capability_dicts() -> list[dict[str, Any]]:
    return [asdict(capability) for capability in TAG_CAPABILITIES]
