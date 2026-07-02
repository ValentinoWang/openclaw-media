from __future__ import annotations

import json
from pathlib import Path

from .tag_router_common import *


CAPABILITY_DOCS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "capability_docs.json"


class SystemRoutesMixin:
    def _media_intake_prompt(self, message: Message) -> str:
        tag = message.entry_tag
        capability = TAG_CAPABILITY_MAP.get(tag)
        if tag == "博主":
            return ""
        if not is_media_intake_tag(tag, capability):
            return ""
        if str(message.body or "").strip():
            return ""
        if tag == "转写" and self._transcription_attachment_paths(message):
            return ""
        if tag == "转写-文字" and self._transcription_text_attachment_paths(message):
            return ""
        if MATERIAL_CREATION_TAG_RE.match(tag):
            downloaded_paths = (message.metadata or {}).get("downloaded_paths") or []
            if isinstance(downloaded_paths, list) and any(str(path).strip() for path in downloaded_paths):
                return ""
        if tag == "创作-灵感":
            downloaded_paths = (message.metadata or {}).get("downloaded_paths") or []
            if isinstance(downloaded_paths, list) and any(str(path).strip() for path in downloaded_paths):
                return ""
        if tag == "灵感>vlog":
            downloaded_paths = (message.metadata or {}).get("downloaded_paths") or []
            if isinstance(downloaded_paths, list) and any(str(path).strip() for path in downloaded_paths):
                return ""
        return render_media_intake_prompt(tag, capability)

    def handle_generic(self, message: Message) -> TaskResult:
        tag_rule = self.rule_service.get_tag_rule(message.entry_tag)
        title = f"{message.entry_tag}：{message.body[:30]}"
        sections = [("原始内容", message.body)]
        extra = {}
        if context_prompt := self._conversation_context_prompt(message):
            sections.append(("最近对话上下文", context_prompt))
            extra["conversation_context_count"] = self._conversation_context(message).get("loaded_count", 0)
        if default_tags := tag_rule.get("default_tags"):
            extra["tags"] = default_tags
        entry = self.archive_service.save_archive(message, title, sections, extra)
        doc_name = tag_rule.get("feishu_doc", f"{message.entry_tag}记录")
        fs = self._sync_entry_to_feishu(entry, message, doc_name, message.body)
        reply = ReplyService.archived(message.entry_tag, entry.local_path, fs.get("doc", ""))
        if warning := fs.get("warning"):
            reply = ReplyService.append_warning(reply, warning)
        result_extra: dict[str, Any] = {}
        if context_prompt:
            result_extra["conversation_context_count"] = self._conversation_context(message).get("loaded_count", 0)
        if message.entry_tag == "复盘" and self._looks_like_media_review(message.body):
            media_review = self._record_media_review_memory(message)
            result_extra["media_review"] = media_review
            if media_review.get("ok"):
                if media_review.get("reply"):
                    reply = f"{reply}\n\n{media_review['reply']}"
            else:
                reason = media_review.get("reply") or media_review.get("error") or "媒体复盘记忆写入失败"
                reply = ReplyService.append_warning(reply, reason)
        return TaskResult(ok=True, status="archived", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, feishu_doc=fs.get("doc", ""), extra=result_extra)

    def handle_创作检查(self, message: Message) -> TaskResult:
        body = str(message.body or "").strip()
        docs = self._matching_selfmedia_checklists(body)
        lines = ["相关 checklist 云文档："]
        for index, doc in enumerate(docs, start=1):
            lines.extend(
                [
                    f"{index}. {doc['title']}",
                    f"   {doc['url']}",
                    f"   {doc['summary']}",
                ]
            )
        lines.append("")
        lines.append("你可以先审阅这些云文档；后续如果要改清单内容，再用 `【自媒体-认知】` 补充对应认知。")
        return TaskResult(
            ok=True,
            status="selfmedia_checklist_replied",
            reply="\n".join(lines),
            task_id="",
            feishu_doc=docs[0]["url"] if docs else "",
            extra={"workflow": "selfmedia_checklist_lookup", "matched_count": len(docs)},
        )

    def handle_说明(self, message: Message) -> TaskResult:
        bot_label = self._current_capability_bot(message)
        if not bot_label:
            return TaskResult(
                ok=False,
                status="missing_bot_identity",
                reply="无法确定当前 Bot。请使用明确格式：`【说明】daily`、`【说明】media`、`【说明】knowledge`、`【说明】social` 或 `【说明】main`。",
                task_id="",
            )
        capabilities = self._bot_capabilities(bot_label)
        content = self._format_bot_capability_description(bot_label, capabilities)
        doc_links = self._capability_doc_links(bot_label)
        missing_links = [name for name, entry in doc_links.items() if not str(entry.get("url") or "").strip()]
        if missing_links:
            return TaskResult(
                ok=False,
                status="capability_doc_link_missing",
                reply="能力说明文档链接未配置："
                + "、".join(missing_links)
                + "。请先运行能力文档生成与飞书同步流程，写入 config/capability_docs.json。",
                task_id="",
                extra={
                    "bot": bot_label,
                    "missing_doc_links": missing_links,
                    "capability_docs_config": str(CAPABILITY_DOCS_CONFIG_PATH),
                },
            )
        return TaskResult(
            ok=True,
            status="bot_capability_description",
            reply=content,
            task_id="",
            extra={
                "bot": bot_label,
                "model": GUIDE_MODEL,
                "thinking": GUIDE_THINKING,
                "capability_count": len(capabilities),
                "capability_docs": doc_links,
            },
        )

    def _current_capability_bot(self, message: Message) -> str:
        body_label = self._normalize_capability_bot(message.body)
        if body_label:
            return body_label
        metadata = message.metadata or {}
        for key in BOT_CAPABILITY_IDENTITY_KEYS:
            label = self._normalize_capability_bot(metadata.get(key))
            if label:
                return label
        return ""

    def _normalize_capability_bot(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in BOT_CAPABILITY_IDENTITY_KEYS:
                normalized = self._normalize_capability_bot(value.get(key))
                if normalized:
                    return normalized
            return ""
        if isinstance(value, (list, tuple)):
            for item in value:
                normalized = self._normalize_capability_bot(item)
                if normalized:
                    return normalized
            return ""
        text = str(value or "").strip()
        if not text:
            return ""
        normalized_text = re.sub(r"\s+", " ", text.lower().replace("_", "-")).strip()
        return BOT_CAPABILITY_IDENTITIES.get(normalized_text, "")

    def _bot_capabilities(self, bot_label: str) -> list[Any]:
        if bot_label == "OpenClaw bot":
            return list(TAG_CAPABILITIES)
        extra_labels = BOT_CAPABILITY_EXTRA_LABELS.get(bot_label, set())
        result: list[Any] = []
        for capability in TAG_CAPABILITIES:
            if capability.bot in {"任意 Bot", bot_label} or capability.label in extra_labels:
                result.append(capability)
        return result

    def _single_fact_parts(self, text: str) -> list[str]:
        parts = [part.strip(" 。；;") for part in re.split(r"[；;]\s*", str(text or "")) if part.strip(" 。；;")]
        return parts or [str(text or "").strip()]

    def _format_capability_usage(self, label: str) -> str:
        usage_formats = TAG_USAGE_FORMATS.get(label, ())
        if usage_formats:
            cleaned = [str(item).strip().rstrip("。") for item in usage_formats if str(item).strip()]
            return "；".join(cleaned)
        if label in GUIDES:
            return f"`【{label}】` 后按填写模板补充内容"
        return f"`【{label}】正文内容`"

    def _format_capability_index_entry(self, capability: Any) -> str:
        label = str(capability.label)
        return (
            f"`【{label}】`：{capability.purpose}"
            f"，输入：{self._format_capability_usage(label)}"
            f"，输出：{capability.result}"
        )

    def _capability_group_key(self, label: str, labels: set[str]) -> str:
        if ">" in label:
            prefix = label.split(">", 1)[0]
            return prefix if prefix in labels else label
        if "-" in label:
            prefix = label.split("-", 1)[0]
            return prefix if prefix in labels else label
        return label

    def _group_capabilities(self, capabilities: list[Any]) -> list[tuple[str, list[Any]]]:
        labels = {str(capability.label) for capability in capabilities}
        groups: dict[str, list[Any]] = {}
        order: list[str] = []
        for capability in capabilities:
            key = self._capability_group_key(str(capability.label), labels)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(capability)
        return [(key, groups[key]) for key in order]

    def _format_capability_label_list(self, capabilities: list[Any]) -> list[str]:
        lines: list[str] = []
        for _, group in self._group_capabilities(capabilities):
            entries = "；".join(self._format_capability_index_entry(capability) for capability in group)
            lines.append(f"- {entries}")
        return lines

    def _capability_docs_config(self) -> dict[str, Any]:
        if not CAPABILITY_DOCS_CONFIG_PATH.exists():
            return {}
        try:
            payload = json.loads(CAPABILITY_DOCS_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _capability_doc_links(self, bot_label: str) -> dict[str, dict[str, Any]]:
        config = self._capability_docs_config()
        total = config.get("total") if isinstance(config.get("total"), dict) else {}
        bots = config.get("bots") if isinstance(config.get("bots"), dict) else {}
        bot_doc = bots.get(bot_label) if isinstance(bots.get(bot_label), dict) else {}
        return {"当前 Bot 文档": dict(bot_doc), "总文档": dict(total)}

    def _format_bot_capability_description(self, bot_label: str, capabilities: list[Any]) -> str:
        doc_links = self._capability_doc_links(bot_label)
        bot_doc = doc_links["当前 Bot 文档"]
        total_doc = doc_links["总文档"]
        lines = [
            "入口事实：",
            "- `【说明】` 是所有 Bot 的唯一能力说明入口。",
            "- `【说明】` 只返回能力说明文档链接和短入口，不执行归档、创作、入库或同步。",
            "- 发送格式固定为 `【标签】正文内容`。",
            "- 当前 Bot 只决定可用标签范围；`【说明】` 不是某个 Bot 的私有入口。",
            "",
            "当前 Bot：",
            f"- {bot_label}",
            f"- OpenClaw 模式：{GUIDE_MODEL} / {GUIDE_THINKING}",
            "",
            "完整说明文档：",
            f"- 当前 Bot 文档：{bot_doc.get('title') or bot_label}：{bot_doc.get('url') or '未配置'}",
            f"- 总文档：{total_doc.get('title') or 'OpenClaw 全部 Bot 能力说明'}：{total_doc.get('url') or '未配置'}",
            "",
            "输入写法：",
            "- 最小格式：`【标签】正文内容`。",
            "- 多字段格式：`【标签】\\n字段：内容\\n字段：内容`。",
            "- 带附件格式：先上传附件，再发送 `【标签】`。",
            "- 查说明：`【说明】` 或 `【说明】knowledge`",
        ]
        route_facts = (*COMMON_ROUTING_FACTS, *BOT_ROUTING_FACTS.get(bot_label, ()))
        if route_facts:
            lines.append("")
            lines.append("查看其他 Bot：")
        lines.extend(f"- {fact}" for fact in route_facts)
        overview = self._bot_capability_overview(bot_label)
        if overview:
            lines.append("")
            lines.append("当前 Bot 概览：")
            lines.extend(overview)
        common_entries = self._bot_common_entries(bot_label)
        if common_entries:
            lines.append("")
            lines.append("重点入口：")
            lines.extend(common_entries)
        lines.append("")
        lines.append(f"标签索引（{len(capabilities)} 个）：")
        lines.extend(self._format_capability_label_list(capabilities))
        return "\n".join(lines)

    def _bot_capability_overview(self, bot_label: str) -> list[str]:
        overviews: dict[str, list[str]] = {
            "Media bot": [
                "- Media bot 的核心目标是把自媒体素材、活动、拆解、创作、复盘串成 Content OS 工作流。",
                "- 主要处理：`【内容素材】`、`【拆解】`、`【创作】`、`【创作-灵感】`、`【素材创作】`、`【数据复盘】`、`【自媒体-认知】`。",
                "- 长期沉淀优先写入 `/home/ubuntu/obsidian-自媒体/`，结构化记录写入对应飞书多维表格或飞书文档。",
                "- 带上传素材的 `【素材创作】`、`【灵感>vlog】` 会直接处理附件；空正文业务标签先返回填写模板。",
                "- `【归档】`、`【补全】`、`【认知】`、`【学习】`、`【学习-整理】` 可以发给 Media bot，但执行者是 Knowledge bot。",
            ],
            "Daily bot": [
                "- Daily bot 管理待办、日程、正式开发任务和今日执行清单，并生成周记草稿。",
                "- 主要处理：`【待办】`、`【日程】`、`【待办-开发】`、`【今日】`、`【周记】`、`【开发-完成】`、`【开发-验证】`。",
                "- 待办按语义分流：普通清单写 Obsidian 当日 checklist；有明确时间、提醒或截止时写飞书提醒表，并在 Obsidian 留带飞书记录ID的镜像 checkbox。",
            ],
            "Knowledge bot": [
                "- Knowledge bot 的核心目标是把知识沉淀成可复用资产，不是只做一次性聊天摘要。",
                "- 原生处理：`【归档】`、`【补全】`、`【认知】`、`【学习】`、`【学习-整理】`。",
                "- 通过标签分流处理：`【自媒体知识】`、`【转写】`、`【转写-文字】`、`【补充】`、`【灵感】`、`【复盘】`、`【整理】`、`【最近】`、`【状态】`、`【同步】`。",
                "- `【转写】` / `【转写-文字】` 均生成会议纪要和原字稿；周记只留宏观总结、5句摘要和链接。",
                "- `【学习】` 会自动判断解释类或整理类；`【学习-整理】` 固定按整理类沉淀。",
                "- Obsidian 周记固定写入 `/home/ubuntu/obsidian-日记/Archieve/YYYYMMDD-YYYYMMDD.md`。",
                "- 学习文件固定写入 `/home/ubuntu/obsidian-日记/学习/每日学习/YYMMDD-主题.md`。",
            ],
            "Social bot": [
                "- Social bot 的核心目标是沉淀人物交互、关系状态、人脉合作和社交复盘。",
                "- 主要处理：`【社交】` 和 `【人脉】`；社交理论标签必须写在 `【社交】` 正文里。",
                "- `【社交】` 面向有持续交互和关系判断的对象；`【人脉】` 面向合作、资源、职业连接等非亲密关系。",
                "- 社交档案优先保留事实、交互证据、判断依据、风险点、下一步动作。",
                "- `【自媒体知识】`、`【转写】`、`【转写-文字】`、知识类标签可以发给 Social bot，但不会写入社交档案。",
            ],
            "OpenClaw bot": [
                "- OpenClaw bot 是统一入口说明，不是某个业务域的私有 Bot。",
                "- 它展示所有标签的入口、边界和分流方向，明显属于专用 Bot 的任务应交给对应 Bot。",
                "- 想查看某个 Bot 的专属说明，发送 `【说明】media`、`【说明】daily`、`【说明】knowledge`、`【说明】social` 或 `【说明】main`。",
                "- OpenClaw bot 不读取其他 Bot 的私有记忆，只说明可用入口和调用方式。",
            ],
        }
        return overviews.get(bot_label, [])

    def _bot_common_entries(self, bot_label: str) -> list[str]:
        entries: dict[str, list[str]] = {
            "Media bot": [
                "- `【内容素材】`：保存值得后续拆解、模仿、选题或复盘的作品链接。用法：`【内容素材】https://...`；多字段：`【内容素材】\\n链接：https://...\\n备注：这个开头值得拆`。",
                "- `【拆解】`：逐镜头拆作品结构、开头、转场、文案和可复刻点。用法：`【拆解】https://...`；可补：`【拆解】\\n链接：https://...\\n重点：开头和转场`。",
                "- `【创作】`：根据平台、账号、类型、主体和发布时间生成可执行初稿。用法：`【创作】\n平台：抖音\n账号：主账号\n类型：图文/视频\n主体：...\n发布时间：今晚8点`。",
                "- `【创作>小红书】`：小红书图文或视频标题、封面方向、正文/脚本结构生成。用法：`【创作>小红书】\n赛道：...\n类型：图文/视频\n主体：...\n发布时间：...`。",
                "- `【创作>抖音】`：抖音图文或视频脚本、分镜、口播、发布文案生成。用法：`【创作>抖音】类型=图文/视频 赛道=体育 主体=毕业季田径比赛 发布时间=今晚8点`。",
                "- `【创作-拍摄执行】`：把主题、人物、场地、参考和素材约束落成拍摄当天执行单。用法：`【创作-拍摄执行】平台=抖音 类型=视频 主体=毕业季田径比赛 场地=操场 人物=我和同学`。",
                "- `【创作咨询】`：不新建文档，只基于账号记忆、爆款表、活动表和复盘回答创作决策。用法：`【创作咨询】平台=小红书 账号=主账号 我最近适合做什么选题？`。",
                "- `【创作-灵感】`：把照片、视频、截图或文字想法整理成灵感卡。用法：先上传素材，再发 `【创作-灵感】这段素材想做成个人成长内容`。",
                "- `【素材创作】`：基于已上传素材做定位分析和初稿。用法：先上传图片或视频，再发 `【素材创作】平台=抖音 类型=图文/视频 账号=主账号 发布时间=今晚8点`。",
                "- `【数据复盘】`：识别平台后台截图并生成作品复盘。用法：先上传数据截图，再发 `【数据复盘】平台=小红书 账号=主账号 项目=... 复盘节点=24小时`。",
                "- `【创作检查】`：查询发布前、选题前或验收前 checklist。用法：`【创作检查】作品发布前看哪个清单？`。",
            ],
            "Daily bot": [
                "- `【待办】`：创建 Obsidian 待办清单或飞书提醒。用法：清单 `【待办】购买\\n1. 杠铃杆\\n2. 起泡器`；提醒 `【待办】2026-06-28 18:00 前购买杠铃杆，提前30分钟提醒`。",
                "- `【日程】`：记录明确开始时间或时间段的日历事件。用法：`【日程】明晚8点到9点和张三开会`；多字段：`【日程】\\n标题：...\\n开始：...\\n结束：...\\n地点：...`。",
                "- `【待办-开发】`：创建正式开发任务，写入 Obsidian checklist 与飞书多维表格结构化台账，并等待 checklist 勾选后由 Mac 侧 Codex high 追溯与回档梳理。用法：`【待办-开发】\\n机器：VM-0-14-ubuntu\\n地址：ubuntu@106.52.146.37\\n任务：修复 Knowledge bot 归档后 Mac 不同步的问题\\n验收：Mac 能看到新周记条目`。",
                "- `【今日】`：查询今日待办、日程或开发任务，不改写任务。用法：`【今日】`、`【今日】开发`、`【今日】提醒`。",
                "- `【周记】`：整理本周周记和 Daily 能力使用记录，生成自我模型候选草稿。用法：`【周记】` 或 `【周记】20260525-20260531`。",
                "- `【开发-完成】`：把开发任务标记完成。用法：`【开发-完成】任务ID`；或 `【开发-完成】关键词：修复同步`。",
                "- `【开发-验证】`：记录开发任务验证结果。用法：`【开发-验证】任务ID 验证通过`；或 `【开发-验证】关键词：修复同步 结果：通过`。",
                "- `【状态】`：查询最近任务或指定任务 ID。用法：`【状态】` 或 `【状态】任务ID`。",
            ],
            "Knowledge bot": [
                "- `【归档】`：整理知识、资料片段、网页摘录或零散观点，写入 Obsidian 周记 `# 知识`。用法：`【归档】需要归档的一段知识`；多字段：`【归档】\\n标题：...\\n来源：...\\n内容：...`。",
                "- `【补全】`：整理已有转写文字或口语化记录，去重复、补结构、保留关键细节，写入周记 `# 认知`。用法：`【补全】\\n主题：...\\n原文：已经转出来的文字稿`。",
                "- `【认知】`：整理经历、反思或判断；详文写 `认知/`，周记留宏观总结、5句摘要和链接。用法：`【认知】今天意识到：...`；多字段：`【认知】\\n标题：...\\n内容：...\\n待确认：...`。",
                "- `【学习】`：自动判断解释类或整理类；短概念会解释拆解，长资料会生成每日学习文件并挂到周记。用法：`【学习】概念名`；多字段：`【学习】\\n主题：...\\n材料：...\\n目标：...`。",
                "- `【学习-整理】`：强制按整理类沉淀长资料、课程笔记、文章、AI 回答；适合不想让系统自动判断时使用。用法：`【学习-整理】\\n主题：课程笔记\\n材料：...`。",
                "- `【自媒体知识】`：处理图文、视频或网页链接，提取自媒体方法论、案例、选题、结构和运营认知，写入自媒体知识表。用法：`【自媒体知识】\\n链接：https://...\\n平台：小红书\\n备注：重点提取选题方法`。",
                "- `【转写】`：处理上传录音，生成逐字稿、总结、Obsidian 会议纪要和原字稿；周记 `# 知识` 只留宏观总结、5句以内摘要、会议纪要链接和原字稿链接；已有文字稿改用 `【转写-文字】`。用法：先上传录音附件，再发 `【转写】`；可补：`【转写】\\n主题：...\\n参与人：...\\n要求：...`。",
                "- `【转写-文字】`：整理和合并已经由语音转文字得到的文字稿，生成总结、待解决问题、说话人标注、Obsidian 会议纪要和原字稿；周记 `# 知识` 只留宏观总结、5句以内摘要、会议纪要链接和原字稿链接。用法：`【转写-文字】\\n主题：...\\n文字稿：...`；也可先上传 `.txt` 或 `.md` 文字稿附件。",
                "- `【最近】`：查询最近归档、转写、学习、灵感、复盘等记录。用法：`【最近】10`、`【最近】学习 5条`、`【最近】今天`。",
                "- `【状态】`：查询最近任务或指定任务 ID 的处理状态。用法：`【状态】` 或 `【状态】20260509-082057-feishu-自媒体知识-b4ef`。",
                "- `【同步】`：对已经落到本地但飞书未成功写入的记录做补同步。用法：`【同步】飞书` 或 `【同步】重新处理任务 ID：...`。",
                "- `【说明】`：查看当前 Bot 能力说明文档。用法：`【说明】`；查看指定 Bot：`【说明】knowledge`、`【说明】media`、`【说明】daily`、`【说明】social`。",
            ],
            "Social bot": [
                "- `【社交】`：整理某个人的聊天记录、互动状态、关系判断、风险点和下一步行动。用法：`【社交】\\n对象：姓名\\n材料：聊天记录或截图说明\\n目标：更新交互档案`。",
                "- `【人脉】`：沉淀合作、资源、职业连接等非亲密关系。用法：`【人脉】\\n对象：张三\\n身份：AI教育创业者\\n城市：北京\\n需求：...\\n下次跟进：...`。",
                "- `【转写】`：处理上传录音，生成逐字稿、总结、会议纪要和原字稿；周记只留宏观总结、5句以内摘要和链接；不会写入社交档案。用法：先上传录音附件，再发 `【转写】`。",
                "- `【转写-文字】`：整理已有语音转文字稿并生成会议纪要和原字稿；周记只留宏观总结、5句以内摘要和链接；不会写入社交档案。用法：`【转写-文字】\\n主题：...\\n文字稿：...`。",
                "- `【归档】`：整理普通知识或资料片段，执行者是 Knowledge bot。用法：`【归档】需要归档的一段知识`。",
                "- `【补全】`：整理已有转写文字，执行者是 Knowledge bot。用法：`【补全】\\n主题：...\\n原文：...`。",
                "- `【认知】`：整理观察、经历或反思，执行者是 Knowledge bot；详文写 `认知/`，周记留宏观总结、5句摘要和链接。用法：`【认知】今天意识到：...`。",
                "- `【自媒体知识】`：处理自媒体链接，写入自媒体知识表；不会写入社交档案。用法：`【自媒体知识】\\n链接：https://...\\n平台：...`。",
                "- `【博主】`：商务邀约前查询已归档博主的主页链接、平台ID和账号名称。用法：`【博主】小王` 或 `【博主】平台：抖音 关键词：小王`。",
                "- `【博主-入库】`：把博主主页链接、平台ID、账号名称和人设信息写入达人账号档案。用法：`【博主-入库】\\n博主IP：小王\\n平台：小红书\\n平台ID：...\\n主页链接：https://...`。",
                "- `【最近】`：查询最近记录。用法：`【最近】10` 或 `【最近】社交 5条`。",
                "- `【状态】`：查询任务状态。用法：`【状态】` 或 `【状态】任务ID`。",
                "- `【说明】`：查看当前 Bot 能力说明文档。用法：`【说明】`；查看指定 Bot：`【说明】social`、`【说明】knowledge`。",
            ],
            "OpenClaw bot": [
                "- `【说明】`：查看当前统一入口说明。用法：`【说明】`；查看指定 Bot：`【说明】media`、`【说明】daily`、`【说明】knowledge`、`【说明】social`。",
                "- `【最近】`：查询最近归档或任务记录。用法：`【最近】10` 或 `【最近】灵感 5条`。",
                "- `【状态】`：查询最近任务或指定任务 ID。用法：`【状态】` 或 `【状态】任务ID`。",
                "- `【同步】`：补同步未同步记录。用法：`【同步】飞书` 或 `【同步】重新处理任务 ID：...`。",
                "- `【整理】`：按标签或时间整理最近记录。用法：`【整理】最近10条` 或 `【整理】今天 灵感`。",
                "- `【调研】`：做主题资料搜集或初步研究。用法：`【调研】主题：... 目标：...`。",
                "- `【复杂调研】`：需要多角度拆解和证据链的研究。用法：`【复杂调研】\\n主题：...\\n问题：...\\n输出要求：...`。",
                "- `【深度调研】`：需要完整研究框架、来源核验和结构化报告的问题。用法：`【深度调研】\\n主题：...\\n范围：...\\n交付：...`。",
            ],
        }
        return entries.get(bot_label, [])

    def _bot_capability_details(self, bot_label: str, label: str) -> list[str]:
        details = dict(self._shared_capability_details())
        details.update(self._bot_specific_capability_details(bot_label))
        return details.get(label, [])

    def _shared_capability_details(self) -> dict[str, list[str]]:
        return {
            "自媒体知识": [
                "  - 适合场景：小红书/抖音/网页里的自媒体方法论、案例、选题、内容结构和运营认知。",
                "  - 产出位置：写入自媒体知识表，后台区分图文和视频，并保留链接、平台、类型、分类、标签、摘要、核心观点、问题、应用建议和待验证项。",
                "  - 注意：没有证据的结构化字段留空；不把推断写成事实。",
            ],
            "转写": [
                "  - 适合场景：已经上传录音文件，需要逐字稿、内容总结和说话人标注。",
                "  - 产出位置：必须生成 Obsidian 会议纪要和原字稿，路径位于 `/home/ubuntu/obsidian-日记/会议纪要/整理版/` 与 `/home/ubuntu/obsidian-日记/会议纪要/原字稿/`；周记 `# 知识` 只保留宏观总结、5句以内摘要、会议纪要链接和原字稿链接。",
                "  - 注意：这是从音频生成文本；已有文字稿整理请用 `【转写-文字】`。",
            ],
            "转写-文字": [
                "  - 适合场景：已经拿到语音转文字稿，需要把多段文字稿整理、合并成会议纪要。",
                "  - 产出位置：必须生成 Obsidian 会议纪要和原字稿，路径位于 `/home/ubuntu/obsidian-日记/会议纪要/整理版/` 与 `/home/ubuntu/obsidian-日记/会议纪要/原字稿/`；周记 `# 知识` 只保留宏观总结、5句以内摘要、会议纪要链接和原字稿链接。",
                "  - 注意：不调用原始音频 ASR；录音文件请用 `【转写】`。",
            ],
            "归档": [
                "  - 适合场景：把知识、观点、资料片段、网页摘录整理进周记。",
                "  - 产出位置：写入对应周记 `# 知识` 小节。",
                "  - 注意：写入前会整理逻辑和标题，不做原文整段粘贴。",
            ],
            "补全": [
                "  - 适合场景：你已经有一段转写文字或口语化记录，需要去重复、补结构、保留细节。",
                "  - 产出位置：写入对应周记 `# 认知` 小节。",
                "  - 注意：不直接处理录音文件；录音文件请用 `【转写】`。",
            ],
            "认知": [
                "  - 适合场景：把经历、观察、复盘后的判断或方法论沉淀成个人认知条目。",
                "  - 产出位置：详文写入 Obsidian `认知/`，周记 `# 认知` 留宏观总结、5句摘要和链接。",
                "  - 注意：默认不写飞书知识表；原始录音请先用 `【转写】`，已有文字再用 `【认知】`。",
            ],
            "学习": [
                "  - 适合场景：概念解释、知识拆解、课程笔记、文章重点理解。",
                "  - 产出位置：生成每日学习文件，并在周记 `# 知识` 小节追加相对链接。",
                "  - 注意：短概念偏解释类；长资料偏整理类；可在正文写 `解释：` 或 `整理：` 明确模式。",
            ],
            "学习-整理": [
                "  - 适合场景：长资料、课程笔记、AI 回答、文章内容需要系统整理。",
                "  - 产出位置：生成每日学习文件，并在周记 `# 知识` 小节追加相对链接。",
                "  - 注意：固定整理类；会保留代码块、表格、定义、比喻和 Mermaid 结构。",
            ],
            "灵感": [
                "  - 适合场景：碎片想法、选题火花、临时观点、未来可展开的内容线。",
                "  - 产出位置：详文写入 Obsidian `灵感/归档/`，周记 `# 灵感` 留宏观总结、5句内摘要和详情链接。",
                "  - 注意：如果是 vlog 素材类灵感，优先用 Media bot 的 `【灵感>vlog】`。",
            ],
            "补充": [
                "  - 适合场景：给已有飞书文档追加新材料、修正观点或合并补充说明。",
                "  - 产出位置：读取指定或被回复的飞书文档，合并后覆盖回同一文档。",
                "  - 注意：正文里最好给出文档链接或回复目标文档消息。",
            ],
            "复盘": [
                "  - 适合场景：沉淀项目、学习、内容或账号表现的经验教训。",
                "  - 产出位置：本地归档，可同步飞书；像媒体数据复盘这类带平台指标的内容会写入媒体记忆。",
            ],
            "整理": [
                "  - 适合场景：汇总最近若干条记录，按标签或时间做复盘式整理。",
                "  - 输入补充：可写 `最近10条`、`今天`、`灵感` 等筛选条件。",
            ],
            "最近": [
                "  - 适合场景：查询最近保存的归档、转写、灵感、复盘等记录。",
                "  - 输入补充：可写数量或标签，例如 `【最近】10`、`【最近】灵感 5条`。",
            ],
            "状态": [
                "  - 适合场景：查询最近任务或指定任务 ID 的处理状态。",
                "  - 输入补充：不写正文查最近任务；写任务 ID 查指定任务。",
            ],
            "同步": [
                "  - 适合场景：本地已有记录但飞书同步失败或需要补同步。",
                "  - 输入补充：通常写 `【同步】飞书`。",
            ],
            "调研": [
                "  - 适合场景：主题资料搜集、行业问题、论文/技术/市场初步研究。",
                "  - 注意：需要更系统的研究时使用 `【复杂调研】` 或 `【深度调研】`。",
            ],
            "复杂调研": [
                "  - 适合场景：需要多角度拆解、对比、证据链和结论的研究问题。",
            ],
            "深度调研": [
                "  - 适合场景：需要更完整研究框架、来源核验和结构化报告的问题。",
            ],
            "研究": [
                "  - 适合场景：论文、技术、产品、市场或知识主题研究。",
            ],
        }

    def _bot_specific_capability_details(self, bot_label: str) -> dict[str, list[str]]:
        details_by_bot: dict[str, dict[str, list[str]]] = {
            "Media bot": {
                "内容素材": [
                    "  - 适合场景：保存值得后续拆解、模仿、选题或复盘的作品链接和素材判断。",
                    "  - 产出位置：写入内容素材链路，长期素材沉淀到 `/home/ubuntu/obsidian-自媒体/05_素材与爆款库/`。",
                    "  - 注意：只想刷新字段或下载素材时用 selfmedia `ingest`，不是这个标签。",
                ],
                "拆解": [
                    "  - 适合场景：需要逐镜头看开头、转场、节奏、结构、文案和可复刻点。",
                    "  - 产出位置：生成飞书拆解文档、记录表摘要，长期同款拆解写入 `/home/ubuntu/obsidian-自媒体/05_素材与爆款库/同款拆解/`。",
                    "  - 注意：必须给真实素材链接；如果只是记一个改编方向，用 `【拆解-再创】`。",
                ],
                "创作": [
                    "  - 适合场景：已有主题、平台、账号或发布时间，需要生成可执行初稿。",
                    "  - 必填字段：`平台`、`类型`、`赛道`、`主体`；使用 `【创作>小红书】` 或 `【创作>抖音】` 时，平台可由标签本身提供。",
                    "  - 建议字段：`发布时间`、`账号`、`用户想法`、`关键词`；如果要写入 Content OS 项目，再加 `项目=`。",
                    "  - 示例：`【创作>抖音】类型=图文/视频 赛道=体育 主体=毕业季田径比赛 发布时间=今晚8点 用户想法=把田径比赛和高考结束、毕业告别结合，开头0.5秒让人看懂是在比赛`。",
                    "  - 产出位置：创建创作文档，长期稿件进入 `/home/ubuntu/obsidian-自媒体/03_脚本生产/` 或内容项目目录。",
                    "  - 注意：正文越明确账号、类型、主体和发布时间，生成越稳定。",
                ],
                "创作>小红书": [
                    "  - 适合场景：小红书图文或视频选题、标题、封面方向、正文结构生成。",
                    "  - 注意：平台不决定内容形态；请显式写 `类型：图文` 或 `类型：视频`。",
                ],
                "创作>抖音": [
                    "  - 适合场景：抖音图文或视频脚本、分镜、口播、转场和发布文案生成。",
                    "  - 示例：`【创作>抖音】类型=图文/视频 赛道=体育 主体=毕业季田径比赛 发布时间=今晚8点`。",
                    "  - 注意：平台不决定内容形态；请显式写 `类型：图文` 或 `类型：视频`。",
                ],
                "创作-拍摄执行": [
                    "  - 适合场景：主题、人物、场地和参考已基本明确，需要现场拍摄路线、镜头、人员分工、B 方案和 checklist。",
                    "  - 产出位置：创建拍摄执行文档，并写入 `03_CreationRuns_创作运行`。",
                    "  - 注意：参考链接先作为素材证据读取；无法确认的链接内容不硬猜。",
                ],
                "创作咨询": [
                    "  - 适合场景：还没决定做什么，需要基于账号记忆、爆款表、活动表和复盘给建议。",
                    "  - 产出位置：只返回建议，不新建创作文档。",
                ],
                "创作-灵感": [
                    "  - 适合场景：把照片、视频、截图、文字想法整理成创作灵感卡和再创作方向。",
                    "  - 产出位置：写入 03_CreationRuns_创作运行；明确立项/初稿目标时创建 Content OS 项目包；只有存在本地素材绑定线索或 Mac 回写结果时，才创建或推进 Mac 素材匹配任务。",
                ],
                "素材创作": [
                    "  - 适合场景：已经上传图片或视频，希望基于素材做定位分析和初稿。",
                    "  - 产出位置：创建创作文档、作品档案，可更新账号监控记录。",
                    "  - 注意：先上传附件再发标签；或同一条消息带附件和标签。",
                ],
                "数据复盘": [
                    "  - 适合场景：上传平台后台截图，识别数据并生成作品复盘。",
                    "  - 产出位置：写入数据复盘表、复盘文档和媒体账号记忆；正文带项目时写入项目 `10_review.md`。",
                ],
                "自媒体-认知": [
                    "  - 适合场景：沉淀你对内容、账号、平台机制的认知或纠错。",
                    "  - 产出位置：写入自媒体认知池子文档；同标题会整合覆盖更新。",
                ],
                "创作检查": [
                    "  - 适合场景：想知道发布前、选题前或验收前应该看哪个 checklist。",
                    "  - 产出位置：只返回相关 checklist 文档链接，不新建记录。",
                ],
                "作品验收": [
                    "  - 适合场景：成片、文案或脚本完成后，对照创作要求逐项验收。",
                    "  - 产出位置：返回满足/不满足/不确定和修改建议；项目证据满足时推进状态。",
                ],
            },
            "Daily bot": {
                "待办": [
                    "  - 适合场景：购物、整理、当天执行清单，或需要未来某个时间提醒的事项。",
                    "  - 产出位置：普通清单写入 Obsidian 周记当天 checklist；带明确时间、提醒或截止的事项写入提醒与日程多维表格，并在 Obsidian 留镜像 checkbox。",
                    "  - 注意：Obsidian 勾选是执行入口；只有带飞书记录ID的 checkbox 会由 Mac 单向同步为飞书已完成。",
                ],
                "日程": [
                    "  - 适合场景：会议、约定、课程、出行等明确占用时间的事件。",
                    "  - 产出位置：创建飞书日历事件，同时写入提醒与日程多维表格。",
                    "  - 注意：最好提供标题、开始时间、地点或参与人。",
                ],
                "待办-开发": [
                    "  - 适合场景：需要正式追踪、复盘和回档的 bug、feature、脚本任务、自动化、运维、重构和验收项。",
                    "  - 产出位置：写入 Obsidian checklist 与飞书多维表格结构化台账；checklist 勾选后由 Mac 侧 Codex high 生成详细任务文档。",
                    "  - 注意：至少写清机器、地址、任务；验收和补充能省则省，但任务边界要足够让 Codex ssh 或本机探索。",
                ],
                "今日": [
                    "  - 适合场景：查看今天该做什么、有什么提醒、日程和开发任务。",
                    "  - 产出位置：返回轻量执行清单，不打开或改写多维表格。",
                ],
                "周记": [
                    "  - 适合场景：每周整理 Obsidian 周记和 Daily 能力使用记录，抽取自我模型候选。",
                    "  - 产出位置：写入 `/home/ubuntu/obsidian-日记/社交/自我模型/周记整理/` 草稿，并保存 draft 状态归档。",
                    "  - 注意：只生成候选草稿；不直接覆盖核心自我模型，不读取 Daily 原始 session。",
                ],
                "开发-完成": [
                    "  - 适合场景：开发需求已经实现并可关闭。",
                    "  - 注意：可以附结果、commit、验证结论。",
                ],
                "开发-验证": [
                    "  - 适合场景：开发需求实现后进入待验证或验收阶段。",
                    "  - 注意：可以附测试方式、待验证点和阻塞点。",
                ],
            },
            "Social bot": {
                "社交": [
                    "  - 适合场景：整理某个人的聊天记录、互动状态、关系判断、风险点和下一步行动。",
                    "  - 产出位置：生成或更新本地人物档案并同步 Obsidian；异性关系可同步一人一份飞书云文档；不写飞书多维表格。",
                    "  - 注意：必须给对象名或可识别身份；理论标签要放在正文里，不单独裸发。",
                ],
                "人脉": [
                    "  - 适合场景：合作对象、资源方、商务联系人、同学同事等非亲密关系档案。",
                    "  - 产出位置：生成或更新人脉档案，只写本地与 Obsidian；不写飞书云文档，不写飞书多维表格。",
                    "  - 注意：适合记录合作价值、需求、承诺、下一次触达时间。",
                ],
            },
            "OpenClaw bot": {
                "说明": [
                    "  - 适合场景：不知道该发给哪个 Bot 或不知道某个标签怎么写。",
                    "  - 输入补充：写 `media`、`daily`、`knowledge`、`social` 或 `main` 查看指定 Bot。",
                ],
                "最近": [
                    "  - 适合场景：查看标签路由归档里的最近记录。",
                ],
                "状态": [
                    "  - 适合场景：查询最近任务或指定任务 ID 的状态。",
                ],
            },
        }
        return details_by_bot.get(bot_label, {})

    def handle_最近(self, message: Message) -> TaskResult:
        query = self._parse_archive_query(message.body, default_limit=10)
        entries = self.archive_service.list_archives(limit=query["limit"], tag=query["tag"], created_on=query["created_on"])
        content = self._format_archive_list(entries) if entries else "暂无记录"
        entry = self.archive_service.save_archive(message, "最近记录查询", [("查询结果", content)])
        return TaskResult(ok=True, status="archived", reply=content, task_id=entry.frontmatter["id"], local_path=entry.local_path)

    def handle_同步(self, message: Message) -> TaskResult:
        body = message.body.strip() or "飞书"
        synced = 0
        failed = 0
        if "飞书" in body:
            unsynced_entries = [
                entry
                for entry in self.archive_service.list_archives(limit=50)
                if not entry.frontmatter.get("feishu_synced") and not entry.frontmatter.get("feishu_skip")
            ]
            for archive_entry in unsynced_entries:
                sync_result = self._sync_archive_entry(archive_entry)
                if sync_result.get("warning"):
                    failed += 1
                else:
                    synced += 1
            content = f"已触发同步：飞书\n成功：{synced}\n失败：{failed}"
        else:
            content = f"已触发同步：{body}"
        entry = self.archive_service.save_archive(message, "同步任务", [("同步目标", body), ("同步结果", content)])
        return TaskResult(ok=True, status="archived", reply=content, task_id=entry.frontmatter["id"], local_path=entry.local_path)

    def handle_状态(self, message: Message) -> TaskResult:
        query = message.body.strip()
        if query:
            target = self.archive_service.get_archive_by_id(query)
        else:
            latest = self.archive_service.list_archives(limit=1)
            target = latest[0] if latest else None
        if target is None:
            content = f"未找到任务：{query or 'latest'}"
        else:
            frontmatter = target.frontmatter
            content = "\n".join(
                [
                    f"任务ID：{frontmatter.get('id', '')}",
                    f"标签：{frontmatter.get('entry_tag', '')}",
                    f"状态：{frontmatter.get('status', '')}",
                    f"创建时间：{frontmatter.get('created_at', '')}",
                    f"本地路径：{target.local_path}",
                ]
            )
        entry = self.archive_service.save_archive(message, "状态查询", [("查询结果", content)])
        return TaskResult(ok=True, status="archived", reply=content, task_id=entry.frontmatter["id"], local_path=entry.local_path)

    def handle_整理(self, message: Message) -> TaskResult:
        return self._handle_summary(message, default_tag=None, archive_title="整理输出", doc_name="整理输出")

    def _handle_summary(self, message: Message, default_tag: str | None, archive_title: str, doc_name: str) -> TaskResult:
        query = self._parse_archive_query(message.body, default_tag=default_tag, default_limit=7)
        entries = self.archive_service.list_archives(limit=query["limit"], tag=query["tag"], created_on=query["created_on"])
        summary = self._build_summary_text(entries)
        filter_text = self._describe_query(query)
        entry = self.archive_service.save_archive(message, archive_title, [("整理条件", filter_text), ("整理结果", summary)])
        fs = self._sync_entry_to_feishu(entry, message, doc_name, message.body)
        reply = ReplyService.archived(message.entry_tag, entry.local_path, fs.get("doc", ""))
        if warning := fs.get("warning"):
            reply = ReplyService.append_warning(reply, warning)
        return TaskResult(ok=True, status="archived", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, feishu_doc=fs.get("doc", ""))

    def _sync_archive_entry(self, entry) -> dict[str, str]:
        tag = entry.frontmatter.get("entry_tag", "")
        doc_name = self.rule_service.get_tag_rule(tag).get("feishu_doc", f"{tag}记录")
        body = self._extract_primary_body(entry)
        message = Message(
            entry_tag=tag,
            raw_text=f"【{tag}】{body}",
            body=body,
            source=entry.frontmatter.get("source", self.source),
            chat_type=self.chat_type,
            created_at=now_in_tz(self.timezone),
        )
        return self._sync_entry_to_feishu(entry, message, doc_name, body)

    def _sync_entry_to_feishu(self, entry, message: Message, doc_name: str, body: str) -> dict[str, str]:
        try:
            content = self._feishu_block(message, entry.local_path, body)
            fs = self.feishu_service.append_entry(doc_name, content)
            self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": True, "feishu_doc": fs.get("doc", "")})
            return fs
        except Exception as exc:
            self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": False, "feishu_doc": doc_name, "feishu_error": str(exc)})
            return {"status": "pending_manual", "doc": doc_name, "warning": f"飞书同步失败：{exc}"}

    def _extract_primary_body(self, entry) -> str:
        if not entry.sections:
            return entry.title
        return entry.sections[0][1].strip() or entry.title

    def _parse_archive_query(
        self,
        body: str,
        *,
        default_tag: str | None = None,
        default_limit: int = 10,
    ) -> dict[str, Any]:
        text = body.strip()
        limit = default_limit
        if match := re.search(r"最近\s*(\d+)\s*条", text):
            limit = int(match.group(1))
        elif text.isdigit():
            limit = int(text)

        tag = default_tag
        for candidate in ["灵感", "待办", "日程", "周记", "活动", "内容素材", "自媒体知识", "转写-文字", "转写", "知识", "社交", "复盘", "整理"]:
            if candidate in text:
                tag = candidate
                break

        created_on = None
        if "今天" in text:
            created_on = now_in_tz(self.timezone).date()
        return {"limit": limit, "tag": tag, "created_on": created_on}

    def _format_archive_list(self, entries) -> str:
        return "\n".join(
            f"- {entry.frontmatter.get('created_at', '')} | {entry.frontmatter.get('entry_tag', '')} | {entry.title}"
            for entry in entries
        )

    def _truncate_transcript_reply(self, text: str, limit: int = 2500) -> str:
        cleaned = (text or "").strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[:limit].rstrip() + "\n\n...（已截断，完整逐字稿见本地归档或 transcript.txt）"

    def _build_summary_text(self, entries) -> str:
        if not entries:
            return "暂无匹配记录"
        lines = [f"- 共 {len(entries)} 条记录"]
        for entry in entries:
            preview = ""
            if entry.sections:
                preview = entry.sections[0][1].splitlines()[0].strip()
            lines.append(
                f"- {entry.frontmatter.get('created_at', '')} | {entry.frontmatter.get('entry_tag', '')} | {entry.title} | {preview}"
            )
        return "\n".join(lines)

    def _describe_query(self, query: dict[str, Any]) -> str:
        parts = [f"- 条数：{query['limit']}"]
        if query.get("tag"):
            parts.append(f"- 标签：{query['tag']}")
        if query.get("created_on"):
            parts.append(f"- 日期：{query['created_on'].strftime('%y%m%d')}")
        return "\n".join(parts)
