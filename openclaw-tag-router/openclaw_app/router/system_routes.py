from __future__ import annotations

from .tag_router_common import *


class SystemRoutesMixin:
    def _media_intake_prompt(self, message: Message) -> str:
        tag = message.entry_tag
        capability = TAG_CAPABILITY_MAP.get(tag)
        if not is_media_intake_tag(tag, capability):
            return ""
        if str(message.body or "").strip():
            return ""
        if tag == "转写" and self._transcription_attachment_paths(message):
            return ""
        if MATERIAL_CREATION_TAG_RE.match(tag):
            downloaded_paths = (message.metadata or {}).get("downloaded_paths") or []
            if isinstance(downloaded_paths, list) and any(str(path).strip() for path in downloaded_paths):
                return ""
        if tag == "创作-灵感":
            downloaded_paths = (message.metadata or {}).get("downloaded_paths") or []
            if isinstance(downloaded_paths, list) and any(str(path).strip() for path in downloaded_paths):
                return ""
        if tag == "灵感-vlog":
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

    def handle_规则(self, message: Message) -> TaskResult:
        rule = self.rule_service.update_rule_from_text(message.body)
        entry = self.archive_service.save_archive(message, "规则更新", [("原始内容", message.body), ("更新结果", yaml.safe_dump(rule, allow_unicode=True, sort_keys=False).strip())])
        tag_rule = self.rule_service.get_tag_rule("规则")
        fs = self._sync_entry_to_feishu(entry, message, tag_rule.get("feishu_doc", "规则记录"), message.body)
        reply = f"规则已更新\n结果：{rule.get('applied', '已记录')}\n本地路径：{entry.local_path}"
        if warning := fs.get("warning"):
            reply = ReplyService.append_warning(reply, warning)
        return TaskResult(ok=True, status="archived", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path)

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

    def _format_bot_capability_description(self, bot_label: str, capabilities: list[Any]) -> str:
        lines = [
            f"这是 {bot_label} 的【说明】",
            "",
            "当前 Bot：",
            f"- {bot_label}",
            f"- OpenClaw 模式：{GUIDE_MODEL} / {GUIDE_THINKING}",
            "",
            "基础规则：",
            "- `【说明】` 是所有 Bot 的唯一能力说明入口。",
            "- `【说明】` 只返回当前 Bot 的标签能力说明。",
            "- 发送格式固定为 `【标签】正文内容`。",
        ]
        route_facts = (*COMMON_ROUTING_FACTS, *BOT_ROUTING_FACTS.get(bot_label, ()))
        lines.extend(f"- {fact}" for fact in route_facts)
        lines.extend(self._bot_capability_overview(bot_label))
        lines.append("")
        lines.append("能力标签：")
        for capability in capabilities:
            lines.append(f"- `【{capability.label}】`")
            lines.append(f"  - 能实现什么：{capability.purpose}；{'；'.join(self._single_fact_parts(capability.result))}")
            lines.append(f"  - 输入格式：{self._format_capability_usage(capability.label)}")
            lines.extend(self._bot_capability_details(bot_label, capability.label))
        return "\n".join(lines)

    def _bot_capability_overview(self, bot_label: str) -> list[str]:
        overviews: dict[str, list[str]] = {
            "Media bot": [
                "- Media bot 的核心目标是把自媒体素材、活动、拆解、创作、复盘串成 Content OS 工作流。",
                "- 主要处理：`【内容素材】`、`【拆解】`、`【创作】`、`【创作-灵感】`、`【素材创作】`、`【数据复盘】`、`【自媒体-认知】`。",
                "- 长期沉淀优先写入 `/home/ubuntu/obsidian-media/`，结构化记录写入对应飞书多维表格或飞书文档。",
                "- 带上传素材的 `【素材创作】`、`【灵感-vlog】` 会直接处理附件；空正文业务标签先返回填写模板。",
                "- `【归档】`、`【补全】`、`【学习】`、`【学习-整理】` 可以发给 Media bot，但执行者是 Knowledge bot。",
            ],
            "Daily bot": [
                "- Daily bot 的核心目标是管理待办、日程、开发任务和今日执行清单。",
                "- 主要处理：`【待办】`、`【日程】`、`【开发】`、`【今日】`、`【完成】`、`【延期】`、`【取消】`、`【开发-完成】`、`【开发-验证】`。",
                "- 到点提醒写入提醒链路；明确时间事件写入飞书日历；开发事项写入本地开发需求卡。",
                "- `【今日】` 只查询和汇总，不改写任务；状态更新类标签按 ID 或关键词更新本地归档。",
                "- `【自媒体知识】`、`【转写】`、知识类标签可以发给 Daily bot，但不会进入日程或待办链路。",
            ],
            "Knowledge bot": [
                "- Knowledge bot 的核心目标是把知识沉淀成可复用资产，不是只做一次性聊天摘要。",
                "- 原生处理：`【归档】`、`【补全】`、`【学习】`、`【学习-整理】`。",
                "- 通过标签分流处理：`【自媒体知识】`、`【转写】`、`【补充】`、`【灵感】`、`【复盘】`、`【整理】`、`【规则】`、`【最近】`、`【状态】`、`【同步】`。",
                "- `【转写】` 处理上传录音并生成会议纪要；`【补全】` 只整理用户已经提供的转写文字。",
                "- `【学习】` 会自动判断解释类或整理类；`【学习-整理】` 固定按整理类沉淀。",
                "- Obsidian 周记固定写入 `/home/ubuntu/obsidian-diary/Archieve/YYYYMMDD-YYYYMMDD.md`。",
                "- 学习文件固定写入 `/home/ubuntu/obsidian-diary/学习/每日学习/YYMMDD-主题.md`。",
            ],
            "Social bot": [
                "- Social bot 的核心目标是沉淀人物交互、关系状态、人脉合作和社交复盘。",
                "- 主要处理：`【社交】` 和 `【人脉】`；社交理论标签必须写在 `【社交】` 正文里。",
                "- `【社交】` 面向有持续交互和关系判断的对象；`【人脉】` 面向合作、资源、职业连接等非亲密关系。",
                "- 社交档案优先保留事实、交互证据、判断依据、风险点、下一步动作。",
                "- `【自媒体知识】`、`【转写】`、知识类标签可以发给 Social bot，但不会写入社交档案。",
            ],
            "OpenClaw bot": [
                "- OpenClaw bot 是统一入口说明，不是某个业务域的私有 Bot。",
                "- 它展示所有标签的入口、边界和分流方向，明显属于专用 Bot 的任务应交给对应 Bot。",
                "- 想查看某个 Bot 的专属说明，发送 `【说明】media`、`【说明】daily`、`【说明】knowledge`、`【说明】social` 或 `【说明】main`。",
                "- OpenClaw bot 不读取其他 Bot 的私有记忆，只说明可用入口和调用方式。",
            ],
        }
        return overviews.get(bot_label, [])

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
                "  - 产出位置：生成 Obsidian 会议纪要 `/home/ubuntu/obsidian-diary/会议纪要/yyyy-mm-dd-总结主题.md`。",
                "  - 注意：这是从音频生成文本；已有文字稿整理请用 `【补全】`。",
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
                "  - 产出位置：本地归档并同步飞书灵感记录。",
                "  - 注意：如果是 vlog 素材类灵感，优先用 Media bot 的 `【灵感-vlog】`。",
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
            "规则": [
                "  - 适合场景：更新标签使用规则、默认标签或处理偏好。",
                "  - 注意：只记录明确规则，不把临时闲聊当长期规则。",
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
                    "  - 产出位置：写入内容素材链路，长期素材沉淀到 `/home/ubuntu/obsidian-media/05_素材与爆款库/`。",
                    "  - 注意：只想刷新字段或下载素材时用 selfmedia `ingest`，不是这个标签。",
                ],
                "拆解": [
                    "  - 适合场景：需要逐镜头看开头、转场、节奏、结构、文案和可复刻点。",
                    "  - 产出位置：生成飞书拆解文档、记录表摘要，长期同款拆解写入 `/home/ubuntu/obsidian-media/05_素材与爆款库/同款拆解/`。",
                    "  - 注意：必须给真实素材链接；如果只是记一个改编方向，用 `【创作-再创】`。",
                ],
                "创作": [
                    "  - 适合场景：已有主题、平台、账号或发布时间，需要生成可执行初稿。",
                    "  - 产出位置：创建创作文档，长期稿件进入 `/home/ubuntu/obsidian-media/03_脚本生产/` 或内容项目目录。",
                    "  - 注意：正文越明确账号、类型、主体和发布时间，生成越稳定。",
                ],
                "创作-小红书": [
                    "  - 适合场景：小红书图文或视频选题、标题、封面方向、正文结构生成。",
                    "  - 注意：不写类型时默认偏图文；需要视频请明确 `类型：视频`。",
                ],
                "创作-抖音": [
                    "  - 适合场景：抖音短视频脚本、分镜、口播、转场和拍摄清单生成。",
                    "  - 注意：不写类型时默认偏视频。",
                ],
                "创作咨询": [
                    "  - 适合场景：还没决定做什么，需要基于账号记忆、爆款表、活动表和复盘给建议。",
                    "  - 产出位置：只返回建议，不新建创作文档。",
                ],
                "创作-灵感": [
                    "  - 适合场景：把照片、视频、截图、文字想法整理成创作灵感卡和再创作方向。",
                    "  - 产出位置：写入创作灵感表；正文带项目时创建 Content OS 项目包。",
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
                    "  - 适合场景：需要未来某个时间提醒你处理，但不一定占用日历。",
                    "  - 产出位置：写入提醒与日程多维表格，到点私聊提醒。",
                    "  - 注意：必须有可解析事项；最好写清时间或提醒规则。",
                ],
                "日程": [
                    "  - 适合场景：会议、约定、课程、出行等明确占用时间的事件。",
                    "  - 产出位置：创建飞书日历事件，同时写入提醒与日程多维表格。",
                    "  - 注意：最好提供标题、开始时间、地点或参与人。",
                ],
                "开发": [
                    "  - 适合场景：bug、feature、脚本任务、自动化、运维、重构和验收项。",
                    "  - 产出位置：生成本地开发需求卡，可后续用 `【开发-验证】` 和 `【开发-完成】` 推进。",
                    "  - 注意：写清背景、模块、验收标准，比只写一句需求更可执行。",
                ],
                "今日": [
                    "  - 适合场景：查看今天该做什么、有什么提醒、日程和开发任务。",
                    "  - 产出位置：返回轻量执行清单，不打开或改写多维表格。",
                ],
                "完成": [
                    "  - 适合场景：普通待办或本地任务已经完成。",
                    "  - 注意：优先提供任务 ID；没有 ID 时用关键词匹配。",
                ],
                "延期": [
                    "  - 适合场景：任务要推迟到新的时间。",
                    "  - 注意：最好写清新时间和延期原因。",
                ],
                "取消": [
                    "  - 适合场景：任务不再需要执行。",
                    "  - 注意：优先提供任务 ID；没有 ID 时用关键词匹配。",
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
                    "  - 产出位置：生成或更新社交对象档案，可按需要写入对应飞书表。",
                    "  - 注意：必须给对象名或可识别身份；理论标签要放在正文里，不单独裸发。",
                ],
                "人脉": [
                    "  - 适合场景：合作对象、资源方、商务联系人、同学同事等非亲密关系档案。",
                    "  - 产出位置：生成或更新人脉档案，默认本地与 Obsidian 沉淀。",
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
            unsynced_entries = [entry for entry in self.archive_service.list_archives(limit=50) if not entry.frontmatter.get("feishu_synced")]
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
        for candidate in ["灵感", "待办", "日程", "活动", "内容素材", "自媒体知识", "转写", "知识", "社交", "复盘", "整理", "规则"]:
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
