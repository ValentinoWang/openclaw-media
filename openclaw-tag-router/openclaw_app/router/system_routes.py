from __future__ import annotations

import json
from pathlib import Path

from .tag_router_common import *
from ..services.capability_input_contracts import get_input_contract
from ..services.capability_matcher import CapabilityMatcher, CapabilityMatcherError
from ..services.capability_registry import CAPABILITY_REGISTRY
from ..services.guidance_plan import GuidancePlanError, GuidancePlanService


CAPABILITY_DOCS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "capability_docs.json"
DEEPMATH_BOT_LABEL = "DeepMath bot"


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
        body = str(message.body or "").strip()
        if not body or self._normalize_capability_bot(body):
            return TaskResult(
                ok=True,
                status="bot_capability_documents",
                reply=self._format_capability_document_reply(bot_label, doc_links),
                task_id="",
                extra={"bot": bot_label, "capability_docs": doc_links},
            )
        try:
            match = self._capability_matcher().match(
                {"query": body, "currentBot": self._capability_bot_id(bot_label)}
            )
            if match["pathStatus"] == "matched":
                match = self._guidance_plan_service().register_match(
                    match,
                    query=body,
                    current_bot=self._capability_bot_id(bot_label),
                )
        except (CapabilityMatcherError, GuidancePlanError) as exc:
            return TaskResult(
                ok=False,
                status=exc.code,
                reply=self._format_capability_error_reply(exc, doc_links, bot_label=bot_label),
                task_id="",
                extra={
                    "bot": bot_label,
                    "capability_docs": doc_links,
                    "matcher_error": exc.code,
                    "matcher_error_detail": exc.message,
                },
            )
        status = {
            "matched": "capability_match",
            "ambiguous": "capability_path_ambiguous",
            "needs_clarification": "capability_needs_clarification",
        }[match["pathStatus"]]
        return TaskResult(
            ok=True,
            status=status,
            reply=self._format_capability_match_reply(match),
            task_id="",
            extra={
                "bot": bot_label,
                "capability_docs": doc_links,
                "capability_match": match,
            },
        )

    def _current_capability_bot(self, message: Message) -> str:
        metadata = message.metadata or {}
        if any(self._is_deepmath_account(metadata.get(key)) for key in BOT_CAPABILITY_IDENTITY_KEYS):
            return DEEPMATH_BOT_LABEL
        body_label = self._normalize_capability_bot(message.body)
        if body_label:
            return body_label
        for key in BOT_CAPABILITY_IDENTITY_KEYS:
            label = self._normalize_capability_bot(metadata.get(key))
            if label:
                return label
        return ""

    @staticmethod
    def _is_deepmath_account(value: Any) -> bool:
        normalized = str(value or "").strip().lower().replace("_", "-")
        if normalized.startswith("feishu-"):
            normalized = normalized[len("feishu-"):]
        return normalized == "deepmath"

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
        allowed_bots = {bot_label} if bot_label == DEEPMATH_BOT_LABEL else {"任意 Bot", bot_label}
        for capability in TAG_CAPABILITIES:
            if capability.bot in allowed_bots or capability.label in extra_labels:
                result.append(capability)
        return result

    def _capability_matcher(self) -> CapabilityMatcher:
        return CapabilityMatcher()

    def _guidance_plan_service(self) -> GuidancePlanService:
        service = getattr(self, "guidance_plan_service", None)
        if isinstance(service, GuidancePlanService):
            return service
        # Isolated route harnesses may not construct the full application.
        service = GuidancePlanService()
        self.guidance_plan_service = service
        return service

    def _capability_bot_id(self, bot_label: str) -> str:
        for bot_id, label in BOT_CAPABILITY_IDENTITIES.items():
            if label == bot_label and bot_id in {"media", "daily", "knowledge", "social", "deepmath"}:
                return bot_id
        return ""

    def _total_doc_reply_line(self, doc_links: dict[str, dict[str, Any]]) -> str:
        total_doc = doc_links["总文档"]
        return f"{total_doc.get('title') or 'OpenClaw 全部 Bot 能力说明'}：{total_doc['url']}"

    def _capability_doc_reply_lines(
        self,
        bot_label: str,
        doc_links: dict[str, dict[str, Any]],
    ) -> list[str]:
        bot_doc = doc_links["当前 Bot 文档"]
        bot_line = f"{bot_doc.get('title') or f'{bot_label} 能力说明'}：{bot_doc['url']}"
        if bot_label == DEEPMATH_BOT_LABEL:
            return [bot_line]
        return [self._total_doc_reply_line(doc_links), bot_line]

    def _format_capability_error_reply(
        self,
        exc: CapabilityMatcherError | GuidancePlanError,
        doc_links: dict[str, dict[str, Any]],
        *,
        bot_label: str = "",
    ) -> str:
        reason, action = {
            "invalid_model_response": (
                "能力匹配模型已返回结果，但结果未通过可执行指令契约校验。",
                "请直接重试原请求；若再次出现，请携带错误代码和详情排查模型输出契约。",
            ),
            "provider_unavailable": (
                "能力匹配模型调用未完成，未取得可供校验的结果。",
                "请稍后重试；若持续出现，请根据错误代码检查 system_guide 模型调用链路。",
            ),
            "invalid_request": (
                "能力匹配请求未通过输入契约校验。",
                "请根据详情修正输入后重试。",
            ),
        }.get(
            exc.code,
            (
                "能力引导计划未通过执行契约校验。",
                "请根据错误代码和详情修正输入；若无法修正，请重新使用【说明】生成路径。",
            ),
        )
        detail = str(exc.message or "").strip() or "底层错误未提供详情。"
        return "\n".join(
            (
                *self._capability_doc_reply_lines(bot_label, doc_links),
                "",
                f"错误代码：{exc.code}",
                f"原因：{reason}",
                f"详情：{detail}",
                f"建议：{action}",
            )
        )

    def _format_capability_document_reply(self, bot_label: str, doc_links: dict[str, dict[str, Any]]) -> str:
        return "\n".join(self._capability_doc_reply_lines(bot_label, doc_links))

    def _format_capability_match_reply(self, match: dict[str, Any]) -> str:
        lines = [f"需求理解：{match['needSummary']}"]
        if match["pathStatus"] == "ambiguous":
            lines.extend(("", "可能对应以下能力："))
            for index, candidate in enumerate(match["candidates"], 1):
                definition = CAPABILITY_REGISTRY.get(str(candidate["capabilityId"]))
                if definition is not None:
                    lines.append(f"{index}. {' / '.join(definition.hierarchy.path_names)}：{candidate['reason']}")
            lines.append("请选择一个候选后继续补充。")
            return "\n".join(lines)
        if match["pathStatus"] == "needs_clarification":
            lines.extend(
                (
                    "",
                    f"需要你补充：{match['clarificationQuestion']}",
                )
            )
            return "\n".join(lines)
        lines.extend(("", f"为什么是这些能力：{match['routeExplanation']}"))
        for item in match["steps"]:
            definition = CAPABILITY_REGISTRY.get(str(item["capabilityId"]))
            label = definition.label if definition is not None else "未知能力"
            lines.extend(
                (
                    "",
                    f"{item['order']}. 【{label}】",
                )
            )
            if item.get("issues"):
                lines.extend(f"- {issue['message']}" for issue in item["issues"])
            if item.get("dependsOn"):
                dependency = item["dependsOn"]
                lines.extend(self._format_waiting_capability_call(item, dependency))
                lines.append(
                    f"等待上一步完成：需要第 {dependency['stepOrder']} 步的 "
                    + "、".join(str(value) for value in dependency["requiredOutputs"])
                    + "；绑定真实结果后会自动给出下一段可复制指令。"
                )
        lines.extend(("", "直接复制填写：", "```text", str(match["copyProjection"]), "```"))
        return "\n".join(lines)

    def _format_waiting_capability_call(
        self,
        item: dict[str, Any],
        dependency: dict[str, Any],
    ) -> list[str]:
        definition = CAPABILITY_REGISTRY.get(str(item["capabilityId"]))
        label = definition.label if definition is not None else "未知能力"
        contract = get_input_contract(label) or {}
        required_fields = [str(value) for value in contract.get("requiredFields") or [] if str(value).strip()]
        required_groups = [
            " / ".join(str(value) for value in group if str(value).strip())
            for group in contract.get("requiredAnyOf") or []
            if isinstance(group, list)
        ]
        lines = ["后续调用说明：", f"- 调用标签：`【{label}】`"]
        if required_fields:
            lines.append("- 必填字段：" + "、".join(required_fields))
        lines.extend(f"- 至少填写一项：{group}" for group in required_groups if group)
        required_outputs = [str(value) for value in dependency.get("requiredOutputs") or [] if str(value).strip()]
        if required_outputs:
            lines.append(
                "- 依赖字段："
                + "、".join(required_outputs)
                + f"（由第 {dependency['stepOrder']} 步真实结果自动绑定）"
            )
        return lines

    def _format_capability_usage(self, label: str) -> str:
        contract = get_input_contract(label)
        if contract is None:
            return f"`【{label}】正文内容`"
        usage_formats = [str(item).strip().rstrip("。") for item in contract.get("usageFormats", ()) if str(item).strip()]
        return "；".join(usage_formats) or f"`【{label}】`"

    def _format_capability_index_entry(self, capability: Any, *, compact: bool = False) -> str:
        label = str(capability.label)
        if compact:
            usage = self._format_capability_usage(label).split("；", 1)[0]
            result = str(capability.result)
            if len(result) > 72:
                result = result[:69].rstrip() + "..."
            return f"`【{label}】`：{capability.purpose}，输入：{usage}，输出：{result}"
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

    def _format_capability_label_list(self, capabilities: list[Any], *, compact: bool = False) -> list[str]:
        lines: list[str] = []
        for _, group in self._group_capabilities(capabilities):
            entries = "；".join(self._format_capability_index_entry(capability, compact=compact) for capability in group)
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
        bots = config.get("bots") if isinstance(config.get("bots"), dict) else {}
        bot_doc = bots.get(bot_label) if isinstance(bots.get(bot_label), dict) else {}
        if bot_label == DEEPMATH_BOT_LABEL:
            return {"当前 Bot 文档": dict(bot_doc)}
        total = config.get("total") if isinstance(config.get("total"), dict) else {}
        return {"当前 Bot 文档": dict(bot_doc), "总文档": dict(total)}

    def _bot_capability_details(self, bot_label: str, label: str) -> list[str]:
        capability = TAG_CAPABILITY_MAP.get(label)
        if capability is None:
            return []
        contract = get_input_contract(label) or {}
        lines = [f"  - 输入模式：`{contract.get('inputMode') or 'unknown'}`。"]
        required = [
            str(item).rstrip("：:").strip()
            for item in contract.get("requiredFields", ())
            if str(item).strip()
        ]
        copy_fields = [str(item).strip() for item in contract.get("copyFields", ()) if str(item).strip()]
        pre_actions = [
            str(item).strip().rstrip("。")
            for item in (
                *contract.get("preActions", ()),
                *(
                    action
                    for variant in contract.get("variants", ())
                    for action in variant.get("preActions", ())
                ),
            )
            if str(item).strip()
        ]
        if pre_actions:
            lines.append("  - 前置动作：" + "；".join(dict.fromkeys(pre_actions)) + "。")
        if required:
            lines.append("  - 必填字段：" + "、".join(f"`{item}`" for item in required) + "。")
        if copy_fields:
            lines.append("  - 可用字段：" + "、".join(f"`{item}`" for item in copy_fields) + "。")
        return lines

    def handle_最近(self, message: Message) -> TaskResult:
        query = self._parse_archive_query(message.body, default_limit=10)
        entries = self.archive_service.list_archives(limit=query["limit"], tag=query["tag"], created_on=query["created_on"])
        content = self._format_archive_list(entries) if entries else "暂无记录"
        return TaskResult(ok=True, status="recent_records_listed", reply=content, task_id="")

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
                ]
            )
        return TaskResult(ok=True, status="task_status_returned", reply=content, task_id="")

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
        for candidate in ["灵感", "待办", "日程", "日记", "周记", "活动", "素材", "自媒体知识", "转写-文字", "转写", "社交", "复盘", "整理"]:
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
