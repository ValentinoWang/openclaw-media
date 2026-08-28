from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .tag_router_common import Message, TaskResult
from media_vault import require_tenant_id


COMMERCIAL_DELIVERY_URL_ENV = "MEDIA_OS_COMMERCIAL_DELIVERY_URL"
COMMERCIAL_DELIVERY_DOC_PARENT_NODE_TOKEN_ENV = "MEDIA_OS_COMMERCIAL_DELIVERY_PARENT_NODE_TOKEN"
COMMERCIAL_DELIVERY_TABLE_NAME = "COM01_CommercialDelivery_商单交付"
MEDIA_ENV_PATH = Path("/home/ubuntu/openclaw-agents/media/.env.local")
MEDIA_REGISTRY_PATH = Path("/home/ubuntu/openclaw-feishu-reminder/media-bitable-registry.json")
BITABLE_OPTION_ID_RE = re.compile(r"^opt[A-Za-z0-9]{6,}$")
COMMERCIAL_DELIVERY_DEFAULT_TEXT = "无特殊要求"
COMMERCIAL_DELIVERY_DEFAULTABLE_MISSING_FIELDS = {"PR备注", "平台要求", "平台要求 / 禁区", "禁区"}

COMMERCIAL_DELIVERY_FIELD_SPECS: dict[str, int] = {
    "名称": 1,
    "商单交付ID": 1,
    "作品初稿链接": 15,
    "文档ID": 1,
    "权限状态": 3,
    "初稿时间": 1,
    "发布时间": 1,
    "平台": 3,
    "内容形式": 3,
    "内容规格": 1,
    "脚本类型": 3,
    "博主名称": 1,
    "账号定位": 1,
    "品牌": 1,
    "产品": 1,
    "标题": 1,
    "一句话总结": 1,
    "PR备注": 1,
    "状态": 3,
    "来源输入摘要": 1,
    "创建时间": 5,
    "运行ID": 1,
    "租户ID": 1,
}

COMMERCIAL_DELIVERY_SELECT_OPTIONS: dict[str, list[str]] = {
    "权限状态": ["互联网所有人可编辑", "权限读回失败", "未设置"],
    "平台": ["小红书", "抖音", "B站", "视频号", "微博", "公众号", "Instagram", "TikTok", "其他", "未知"],
    "内容形式": ["图文", "视频", "图文+视频", "直播", "其他", "未知"],
    "脚本类型": ["图片脚本", "分镜脚本"],
    "状态": ["初稿待审", "需补充", "需返修", "待发布", "已发布", "写入失败"],
}

COMMERCIAL_DELIVERY_PROMPT = """
你是 OpenClaw Media bot 的商业内容交付助手。请把用户给出的品牌信息、产品卖点、Tags、创作方向、可用博主档案、平台要求、初稿/发布时间整理成一份可直接写入飞书云文档的商单交付初稿。

硬性规则：
1. 只根据用户输入与明确附件文字事实生成，不要补造品牌、价格、身份、时间、数据。
2. 如果缺少品牌/产品/博主名称/平台/内容形式/内容规格/初稿时间/发布时间/产品卖点/创作方向/Tags 中的关键项，返回 status=pending_manual，并在 missing_fields 写清楚，不要输出 done。
3. 文档名称字段 document_name_summary 必须是一句话总结，22 个中文字符以内，不要叫“广告内容交付卡”。
4. content_form 为图文时，script_type 必须是“图片脚本”；为视频时，script_type 必须是“分镜脚本”。
5. shooting_script 必须是数组，每行给语言描述和拍摄指导，不生成图片。
6. content.title 只输出 1 个可发布标题：如果用户输入里明确写了标题/题目，必须沿用该标题，不要另起；如果用户没写标题，才生成 1 个可发布标题。不要输出“标题1/标题2/多集标题/备选标题”，也不要把多个标题混进正文或 Tags。
7. content.publish_copy 必须是一段完整可直接发布的正文：包含开头钩子、真实体验过程、产品卖点、个人感受和自然转化句；不要拆成提纲，不要写“CTA/轻 CTA”小标题，不要写成品牌说明书。转化句要像博主自己的自然分享，例如“更适合...的人试试”，不能像硬广命令。
8. Tags 只放 hashtag 列表，不要混入标题、正文句子、分集标题、CTA 或没有 # 的普通词。
9. 文案语气要像博主本人分享；用户未填写博主人设 / 语气时，优先参考【可用博主档案上下文】里的身份定位、创作者角色、可创作身份卖点和公开表达边界。
10. 平台要求 / 禁区（选填）；用户没给时不要编造，输出“无特殊要求”。
11. 博主人设 / 语气（选填）；没有用户输入且没有博主档案上下文时，不要因为该项返回 pending_manual。
12. PR备注（选填）；用户没给时输出“无特殊要求”，不要因为缺少 PR备注 返回 pending_manual。

只返回 JSON，不要 Markdown。结构：
{
  "status": "done | pending_manual",
  "reason": "",
  "missing_fields": [],
  "document_name_summary": "",
  "brand": "",
  "product": "",
  "work_info": {
    "draft_due": "",
    "publish_time": "",
    "blogger_name": "",
    "account_positioning": "",
    "platform": "",
    "content_form": "",
    "content_spec": ""
  },
  "content": {
    "creative_direction": "",
    "title": "",
    "publish_copy": "",
    "opening_hook": "",
    "experience_process": "",
    "product_selling_points": "",
    "personal_feeling": "",
    "soft_conversion_sentence": "",
    "tags": [],
    "platform_requirements": "",
    "poll": ""
  },
  "script_type": "图片脚本 | 分镜脚本",
  "shooting_script": [
    {
      "index": "1",
      "scene": "",
      "timing": "",
      "shooting_guidance": "",
      "copy_or_voiceover": "",
      "product_exposure": "",
      "props_notes": ""
    }
  ],
  "pr_notes": "",
  "source_summary": ""
}
""".strip()


class CommercialDeliveryMixin:
    def handle_商单交付(self, message: Message) -> TaskResult:
        try:
            payload = self._commercial_delivery_generate_payload(message)
            self._commercial_delivery_apply_input_defaults(payload)
            pending = self._commercial_delivery_pending_reason(payload)
            if pending:
                return TaskResult(
                    ok=False,
                    status="commercial_delivery_pending_manual",
                    reply="【商单交付】缺少必要信息，未创建飞书文档、未写入多维表格。\n" + pending,
                    task_id="",
                    extra={"persisted": False, "payload": payload},
                )

            doc_name = self._commercial_delivery_doc_name(message, payload)
            blocks = self._commercial_delivery_doc_blocks(payload)
            doc_result = self._commercial_delivery_write_doc(doc_name, blocks)
            document_id = str(doc_result.get("document_id") or "")
            if not document_id:
                raise RuntimeError("创建飞书云文档后未读到 document_id")
            permission = self.feishu_service.set_docx_public_editable(document_id)
            if not self.feishu_service.document_has_native_table(document_id):
                raise RuntimeError("飞书文档读回未发现原生表格 block_type=31")

            delivery_id = self._commercial_delivery_id(message, doc_name)
            record_result = self._commercial_delivery_write_record(
                message=message,
                payload=payload,
                delivery_id=delivery_id,
                doc_name=doc_name,
                doc_url=str(doc_result.get("doc") or ""),
                document_id=document_id,
            )
            self._commercial_delivery_register_docx(
                message=message,
                delivery_id=delivery_id,
                document_id=document_id,
            )
            reminder_result = self._commercial_delivery_create_deadline_reminders(
                message=message,
                payload=payload,
                delivery_id=delivery_id,
            )
            reply = self._commercial_delivery_success_reply(
                str(doc_result.get("doc") or ""),
                reminder_result["warnings"],
            )
            return TaskResult(
                ok=True,
                status="commercial_delivery_created",
                reply=reply,
                task_id=delivery_id,
                feishu_doc=str(doc_result.get("doc") or ""),
                extra={
                    "delivery_id": delivery_id,
                    "doc": doc_result,
                    "record": record_result,
                    "permission": permission,
                    "deadline_reminders": reminder_result["created"],
                    "deadline_reminder_warnings": reminder_result["warnings"],
                    "persisted": True,
                },
            )
        except Exception as exc:
            return TaskResult(
                ok=False,
                status="commercial_delivery_failed",
                reply=self._commercial_delivery_failure_reply("commercial_delivery_failed", str(exc)),
                task_id="",
                extra={"persisted": False, "error": str(exc)},
            )

    def _commercial_delivery_create_deadline_reminders(
        self,
        *,
        message: Message,
        payload: dict[str, Any],
        delivery_id: str,
    ) -> dict[str, list[Any]]:
        """Create reminders only after the delivery record is durably written."""
        service = getattr(self, "reminder_service", None)
        if service is None or not callable(getattr(service, "add", None)):
            return {"created": [], "warnings": []}
        work_info = self._commercial_delivery_dict(payload.get("work_info"))
        title = str(payload.get("document_name_summary") or payload.get("brand") or "商单交付").strip()
        created: list[dict[str, Any]] = []
        warnings: list[str] = []
        for field_name, key, suffix in (
            ("初稿时间", "draft_due", "draft"),
            ("发布时间", "publish_time", "publish"),
        ):
            raw_due = str(work_info.get(key) or "").strip()
            due_at = self._commercial_delivery_parse_deadline(raw_due, message.created_at)
            if due_at is None:
                warnings.append(f"{field_name}“{raw_due or '未提供'}”无法解析，未建立提醒；请手动【日程】确认。")
                continue
            try:
                reminder = service.add(
                    kind="待办",
                    title=f"商单{field_name}：{title}",
                    text=f"商单交付ID：{delivery_id}\n{field_name}：{raw_due}",
                    due_at=due_at,
                    remind_at=due_at - timedelta(minutes=30),
                    source=message.source,
                    ref_id=f"{delivery_id}-{suffix}",
                    local_path="",
                )
                created.append(reminder if isinstance(reminder, dict) else {"ref_id": f"{delivery_id}-{suffix}"})
            except Exception:
                warnings.append(f"{field_name}提醒未建立；请手动【日程】确认。")
        return {"created": created, "warnings": warnings}

    def _commercial_delivery_parse_deadline(self, value: str, created_at: datetime) -> datetime | None:
        text = str(value or "").strip().replace("/", "-")
        if not text:
            return None
        tz = ZoneInfo(self.timezone)
        iso_match = re.search(r"\d{4}-\d{1,2}-\d{1,2}(?:[T\s]\d{1,2}:\d{2})?", text)
        if iso_match:
            try:
                parsed = datetime.fromisoformat(iso_match.group(0).replace("T", " "))
                return (parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)).replace(second=0, microsecond=0)
            except ValueError:
                return None
        chinese_match = re.search(
            r"(?:(?P<year>\d{4})年)?(?P<month>\d{1,2})月(?P<day>\d{1,2})日(?:\s*(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?)?",
            text,
        )
        if not chinese_match:
            return None
        try:
            created = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=tz)
            return datetime(
                int(chinese_match.group("year") or created.astimezone(tz).year),
                int(chinese_match.group("month")),
                int(chinese_match.group("day")),
                int(chinese_match.group("hour") or 9),
                int(chinese_match.group("minute") or 0),
                tzinfo=tz,
            )
        except ValueError:
            return None

    def _commercial_delivery_generate_payload(self, message: Message) -> dict[str, Any]:
        if not getattr(self, "content_flow_client", None) or not hasattr(self.content_flow_client, "_call_profile_provider_json"):
            return {"status": "pending_manual", "reason": "media_creation JSON provider 未配置"}
        creator_context = self._commercial_delivery_creator_profile_context(message.raw_text)
        user_content = message.raw_text
        if creator_context.get("prompt_context"):
            user_content = user_content + "\n\n【可用博主档案上下文】\n" + str(creator_context["prompt_context"])
        payload = self.content_flow_client._call_profile_provider_json(
            "media_creation",
            COMMERCIAL_DELIVERY_PROMPT,
            user_content,
            "商单交付初稿",
        )
        if isinstance(payload, dict) and creator_context:
            self._commercial_delivery_apply_creator_context(payload, creator_context)
        if isinstance(payload, dict):
            self._commercial_delivery_apply_input_defaults(payload)
        return payload

    def _commercial_delivery_creator_profile_context(self, raw_text: str) -> dict[str, Any]:
        lookup = self._commercial_delivery_creator_lookup_fields(raw_text)
        blogger_name = lookup.get("blogger_name")
        if not blogger_name:
            return {}
        records_loader = getattr(self, "_creator_profile_records", None)
        record_filter = getattr(self, "_filter_creator_profile_records", None)
        if not callable(records_loader) or not callable(record_filter):
            return {}
        filters: dict[str, Any] = {}
        if lookup.get("platform"):
            filters["platform"] = lookup["platform"]
        try:
            matched = record_filter(records_loader(), {"text": blogger_name, "filters": filters})
        except Exception:
            return {}
        if not matched:
            return {}
        fields = (matched[0].get("fields") or {}) if isinstance(matched[0], dict) else {}
        if not isinstance(fields, dict):
            return {}
        context = self._commercial_delivery_creator_context_from_fields(fields)
        if not context.get("prompt_context"):
            return {}
        context["record_id"] = str(matched[0].get("record_id") or "")
        return context

    def _commercial_delivery_creator_lookup_fields(self, raw_text: str) -> dict[str, str]:
        blogger_line = self._commercial_delivery_labeled_line(raw_text, ("博主名称", "博主", "账号名称"))
        platform = self._commercial_delivery_labeled_line(raw_text, ("平台",))
        blogger_name = re.split(r"[|｜]", blogger_line, maxsplit=1)[0].strip()
        platform = re.split(r"[/／,，;；\s]", platform, maxsplit=1)[0].strip()
        return {"blogger_name": blogger_name, "platform": platform}

    @staticmethod
    def _commercial_delivery_labeled_line(raw_text: str, labels: tuple[str, ...]) -> str:
        label_pattern = "|".join(re.escape(label) for label in labels)
        for line in str(raw_text or "").replace("\r\n", "\n").splitlines():
            match = re.match(rf"\s*(?:{label_pattern})\s*[：:=]\s*(.+?)\s*$", line)
            if match:
                return match.group(1).strip()
        return ""

    def _commercial_delivery_creator_context_from_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        identity_summary = self._commercial_delivery_creator_field(fields, "identity_summary", "身份定位")
        identity_tags = self._commercial_delivery_creator_field(fields, "identity_tags", "身份标签", "关键词标签")
        education = self._commercial_delivery_creator_field(fields, "education_background", "教育背景", "院校背景")
        expertise = self._commercial_delivery_creator_field(fields, "expertise_domains", "专业能力领域")
        creator_role = self._commercial_delivery_creator_field(fields, "creator_role", "创作者角色")
        boundaries = self._commercial_delivery_creator_field(fields, "public_persona_boundaries", "公开表达边界")
        story_points = self._commercial_delivery_creator_field(fields, "story_usable_identity_points", "可创作身份卖点")
        account_name = self._commercial_delivery_creator_field(fields, "account_name", "账号名称", "博主IP")
        platform = self._commercial_delivery_creator_field(fields, "platform", "平台")
        lines = [
            f"来源：06_CreatorProfiles_达人账号档案 / MEDIA_OS_CREATOR_PROFILES_V2_URL",
            f"平台：{platform}" if platform else "",
            f"账号名称：{account_name}" if account_name else "",
            f"身份定位：{identity_summary}" if identity_summary else "",
            f"身份标签：{identity_tags}" if identity_tags else "",
            f"教育背景：{education}" if education else "",
            f"专业能力领域：{expertise}" if expertise else "",
            f"创作者角色：{creator_role}" if creator_role else "",
            f"公开表达边界：{boundaries}" if boundaries else "",
            f"可创作身份卖点：{story_points}" if story_points else "",
        ]
        prompt_context = "\n".join(line for line in lines if line)
        account_positioning = "；".join(part for part in (identity_summary, creator_role, story_points) if part)
        return {
            "source": "06_CreatorProfiles_达人账号档案 / MEDIA_OS_CREATOR_PROFILES_V2_URL",
            "account_positioning": account_positioning,
            "prompt_context": prompt_context,
        }

    def _commercial_delivery_creator_field(self, fields: dict[str, Any], canonical: str, *display_names: str) -> str:
        reader = getattr(self, "_creator_field_text", None)
        if callable(reader):
            value = str(reader(fields, canonical) or "").strip()
            if value:
                return value
        for name in (canonical, *display_names):
            value = self._commercial_delivery_plain_text(fields.get(name))
            if value:
                return value
        return ""

    @staticmethod
    def _commercial_delivery_plain_text(value: Any) -> str:
        if value in (None, "", []):
            return ""
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("name") or item.get("value") or "").strip())
                else:
                    parts.append(str(item).strip())
            return "、".join(part for part in parts if part)
        if isinstance(value, dict):
            return str(value.get("text") or value.get("name") or value.get("value") or "").strip()
        return str(value).strip()

    def _commercial_delivery_apply_creator_context(self, payload: dict[str, Any], context: dict[str, Any]) -> None:
        work_info = self._commercial_delivery_dict(payload.get("work_info"))
        if payload.get("work_info") is not work_info:
            payload["work_info"] = work_info
        if not str(work_info.get("account_positioning") or "").strip() and context.get("account_positioning"):
            work_info["account_positioning"] = context["account_positioning"]
        payload["_creator_profile_context"] = {
            "source": context.get("source"),
            "record_id": context.get("record_id"),
        }

    def _commercial_delivery_pending_reason(self, payload: dict[str, Any]) -> str:
        self._commercial_delivery_apply_input_defaults(payload)
        status = str(payload.get("status") or "").strip()
        if status != "done":
            missing_items = self._commercial_delivery_missing_items(payload.get("missing_fields"))
            blocking_missing = [item for item in missing_items if item not in COMMERCIAL_DELIVERY_DEFAULTABLE_MISSING_FIELDS]
            if missing_items and not blocking_missing:
                payload["status"] = "done"
            else:
                if blocking_missing:
                    return "原因：关键信息不足，需补充后才能形成完整商单交付稿。\n缺少：" + "、".join(blocking_missing)
                reason = str(payload.get("reason") or "LLM 未返回可写入的商单交付结构").strip()
                return f"原因：{reason}"
        missing = []
        work_info = self._commercial_delivery_dict(payload.get("work_info"))
        content = self._commercial_delivery_dict(payload.get("content"))
        required = {
            "品牌": payload.get("brand"),
            "产品": payload.get("product"),
            "平台": work_info.get("platform"),
            "内容形式": work_info.get("content_form"),
            "内容规格": work_info.get("content_spec"),
            "初稿时间": work_info.get("draft_due"),
            "发布时间": work_info.get("publish_time"),
            "博主名称": work_info.get("blogger_name"),
            "产品卖点": content.get("product_selling_points"),
            "创作方向": content.get("creative_direction"),
            "一句话总结": payload.get("document_name_summary"),
            "标题": content.get("title"),
            "完整发布文案": self._commercial_delivery_publish_copy(content),
            "脚本类型": payload.get("script_type"),
        }
        for label, value in required.items():
            if not str(value or "").strip():
                missing.append(label)
        tags = content.get("tags")
        if not isinstance(tags, list) or not any(str(tag or "").strip() for tag in tags):
            missing.append("Tags")
        script = payload.get("shooting_script")
        if not isinstance(script, list) or not script:
            missing.append("图片脚本/分镜脚本表格")
        if missing:
            return "缺少：" + "、".join(missing)
        script_type = str(payload.get("script_type") or "").strip()
        content_form = str(work_info.get("content_form") or "").strip()
        if "图文" in content_form and script_type != "图片脚本":
            return "缺少：图文内容必须输出“图片脚本”"
        if "视频" in content_form and "图文" not in content_form and script_type != "分镜脚本":
            return "缺少：视频内容必须输出“分镜脚本”"
        return ""

    def _commercial_delivery_doc_name(self, message: Message, payload: dict[str, Any]) -> str:
        summary = str(payload.get("document_name_summary") or "").strip()
        summary = re.sub(r"[\\/:*?\"<>|#\n\r\t]+", "", summary)
        summary = summary[:30] or "商单交付初稿"
        return f"{message.created_at.strftime('%Y-%m-%d')}｜{summary}"

    def _commercial_delivery_doc_blocks(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        markdown = self._commercial_delivery_markdown(payload)
        renderer = getattr(self.feishu_service, "render_docx_blocks_from_markdown", None)
        if renderer:
            return renderer(markdown)
        return self.feishu_service._content_to_docx_blocks(markdown)

    def _commercial_delivery_markdown(self, payload: dict[str, Any]) -> str:
        work_info = self._commercial_delivery_dict(payload.get("work_info"))
        content = self._commercial_delivery_dict(payload.get("content"))
        tags = content.get("tags") if isinstance(content.get("tags"), list) else []
        script_type = str(payload.get("script_type") or "").strip()
        script_heading = "图片脚本" if script_type == "图片脚本" else "分镜脚本"
        rows = self._commercial_delivery_script_rows(payload)
        table = self._commercial_delivery_script_table(script_type, rows)
        publish_copy = self._commercial_delivery_publish_copy(content)
        return "\n".join(
            [
                f"# {payload.get('document_name_summary')}",
                "",
                "## 1. 作品信息",
                f"### 初稿时间\n{work_info.get('draft_due')}",
                f"### 发布时间\n{work_info.get('publish_time')}",
                f"### 博主名称\n{work_info.get('blogger_name')}｜{work_info.get('account_positioning')}",
                f"### 平台及内容形式\n平台：{work_info.get('platform')}\n内容形式：{work_info.get('content_form')}\n规格：{work_info.get('content_spec')}",
                "",
                "## 2. 作品内容",
                f"### 创作方向\n{content.get('creative_direction')}",
                f"### 标题\n{content.get('title')}",
                "### 文案及 Tags",
                f"#### 正文（可直接发布）\n{publish_copy}",
                f"#### Tags\n{' '.join(str(tag).strip() for tag in tags if str(tag).strip())}",
                f"#### 平台要求 / 禁区（选填）\n{content.get('platform_requirements') or COMMERCIAL_DELIVERY_DEFAULT_TEXT}",
                f"### 投票（如需）\n{content.get('poll') or '无'}",
                f"### {script_heading}",
                table,
                "",
                "## 3. PR备注",
                str(payload.get("pr_notes") or COMMERCIAL_DELIVERY_DEFAULT_TEXT).strip() or COMMERCIAL_DELIVERY_DEFAULT_TEXT,
            ]
        )

    @staticmethod
    def _commercial_delivery_publish_copy(content: dict[str, Any]) -> str:
        direct = str(content.get("publish_copy") or "").strip()
        if direct:
            return direct
        parts = [
            content.get("opening_hook"),
            content.get("experience_process"),
            content.get("product_selling_points"),
            content.get("personal_feeling"),
            content.get("soft_conversion_sentence") or content.get("light_cta"),
        ]
        return "\n\n".join(str(part).strip() for part in parts if str(part or "").strip())

    def _commercial_delivery_script_rows(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for index, item in enumerate(payload.get("shooting_script") or [], 1):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "index": str(item.get("index") or index),
                    "scene": str(item.get("scene") or "").strip(),
                    "timing": str(item.get("timing") or "").strip(),
                    "shooting_guidance": str(item.get("shooting_guidance") or "").strip(),
                    "copy_or_voiceover": str(item.get("copy_or_voiceover") or "").strip(),
                    "product_exposure": str(item.get("product_exposure") or "").strip(),
                    "props_notes": str(item.get("props_notes") or "").strip(),
                }
            )
        return rows

    def _commercial_delivery_script_table(self, script_type: str, rows: list[dict[str, str]]) -> str:
        if script_type == "图片脚本":
            header = ["序号", "图片内容/画面", "拍摄指导", "画面文案", "产品露出", "道具/备注"]
            body = [
                [
                    row["index"],
                    row["scene"],
                    row["shooting_guidance"],
                    row["copy_or_voiceover"],
                    row["product_exposure"],
                    row["props_notes"],
                ]
                for row in rows
            ]
        else:
            header = ["镜号", "场景/画面", "时长/节奏", "拍摄指导", "口播/字幕", "产品露出", "道具/备注"]
            body = [
                [
                    row["index"],
                    row["scene"],
                    row["timing"],
                    row["shooting_guidance"],
                    row["copy_or_voiceover"],
                    row["product_exposure"],
                    row["props_notes"],
                ]
                for row in rows
            ]
        table_rows = [header, *body]
        return "\n".join("| " + " | ".join(self._commercial_delivery_table_cell(cell) for cell in row) + " |" for row in table_rows[:1]) + "\n" + "| " + " | ".join("---" for _ in header) + " |\n" + "\n".join(
            "| " + " | ".join(self._commercial_delivery_table_cell(cell) for cell in row) + " |" for row in table_rows[1:]
        )

    @staticmethod
    def _commercial_delivery_table_cell(value: Any) -> str:
        return str(value or "").replace("\n", " ").replace("|", "｜").strip()

    def _commercial_delivery_write_doc(self, doc_name: str, blocks: list[dict[str, Any]]) -> dict[str, str]:
        parent_node_token = self._commercial_delivery_parent_node_token()
        if parent_node_token and hasattr(self.feishu_service, "replace_child_entry_under_node_blocks"):
            return self.feishu_service.replace_child_entry_under_node_blocks(parent_node_token, doc_name, blocks)
        return self.feishu_service.create_docx_with_blocks(doc_name, blocks)

    def _commercial_delivery_register_docx(
        self,
        *,
        message: Message,
        delivery_id: str,
        document_id: str,
    ) -> None:
        owner_service = getattr(self, "tenant_owned_resources", None)
        if owner_service is None:
            raise RuntimeError("canonical resource owner service is unavailable")
        tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        owner_service.register_docx_link(
            "media.commercial_delivery",
            delivery_id,
            session_tenant_id=tenant_id,
            document_url=f"https://tcnwueberajc.feishu.cn/docx/{document_id}",
            policy="anyone_editable",
        )

    def _commercial_delivery_parent_node_token(self) -> str:
        direct = os.environ.get(COMMERCIAL_DELIVERY_DOC_PARENT_NODE_TOKEN_ENV, "").strip()
        if direct:
            return direct
        table_url = self._commercial_delivery_table_url()
        parsed = urllib.parse.urlparse(table_url)
        match = re.search(r"/wiki/([A-Za-z0-9]+)", parsed.path)
        return match.group(1) if match else ""

    def _commercial_delivery_write_record(
        self,
        *,
        message: Message,
        payload: dict[str, Any],
        delivery_id: str,
        doc_name: str,
        doc_url: str,
        document_id: str,
    ) -> dict[str, str]:
        tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        owner_service = getattr(self, "tenant_owned_resources", None)
        if owner_service is None:
            raise RuntimeError("canonical resource owner service is unavailable")
        table_url = self._commercial_delivery_table_url()
        app_token, table_id, resolved_url = self._commercial_delivery_bitable_refs(table_url)
        self._ensure_commercial_delivery_fields(app_token, table_id)
        raw_fields = self._commercial_delivery_record_fields(message, payload, delivery_id, doc_name, doc_url, document_id)
        raw_fields = owner_service.create_projection(
            "media.commercial_delivery",
            delivery_id,
            session_tenant_id=tenant_id,
            fields=raw_fields,
            writer=lambda projected: projected,
        )
        self._ensure_commercial_delivery_select_options(app_token, table_id, raw_fields)
        field_types = self._commercial_delivery_field_types(app_token, table_id)
        payload_fields = {
            name: self._commercial_delivery_coerce_value(value, field_types.get(name))
            for name, value in raw_fields.items()
            if name in field_types and value not in (None, "", [])
        }
        payload_fields = {name: value for name, value in payload_fields.items() if value not in (None, "", [])}
        if not payload_fields:
            raise RuntimeError("商单交付多维表没有可写字段")
        response = self.feishu_service._request(
            "POST",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            json_body={"fields": payload_fields},
        )
        record = response.get("data", {}).get("record") or {}
        record_id = str(record.get("record_id") or "")
        if not record_id:
            raise RuntimeError(f"商单交付多维表写入后缺少 record_id: {response}")
        readback = self.feishu_service.read_bitable_record(app_token, table_id, record_id)
        if not readback.get("fields"):
            raise RuntimeError(f"商单交付多维表记录读回失败: record_id={record_id}")
        owner_service.assert_projection_read(
            "media.commercial_delivery",
            delivery_id,
            session_tenant_id=tenant_id,
            fields=readback["fields"],
            projection_source=f"feishu:{table_id}/{record_id}",
        )
        return {
            "record_id": record_id,
            "table_url": resolved_url,
            "record_url": self._commercial_delivery_record_url(resolved_url, record_id),
            "written_fields": ",".join(sorted(payload_fields)),
        }

    def _commercial_delivery_record_fields(
        self,
        message: Message,
        payload: dict[str, Any],
        delivery_id: str,
        doc_name: str,
        doc_url: str,
        document_id: str,
    ) -> dict[str, Any]:
        work_info = self._commercial_delivery_dict(payload.get("work_info"))
        content = self._commercial_delivery_dict(payload.get("content"))
        return {
            "名称": doc_name,
            "商单交付ID": delivery_id,
            "作品初稿链接": doc_url,
            "文档ID": document_id,
            "权限状态": "互联网所有人可编辑",
            "初稿时间": work_info.get("draft_due"),
            "发布时间": work_info.get("publish_time"),
            "平台": work_info.get("platform"),
            "内容形式": work_info.get("content_form"),
            "内容规格": work_info.get("content_spec"),
            "脚本类型": payload.get("script_type"),
            "博主名称": work_info.get("blogger_name"),
            "账号定位": work_info.get("account_positioning"),
            "品牌": payload.get("brand"),
            "产品": payload.get("product"),
            "标题": content.get("title"),
            "一句话总结": payload.get("document_name_summary"),
            "PR备注": payload.get("pr_notes") or COMMERCIAL_DELIVERY_DEFAULT_TEXT,
            "状态": "初稿待审",
            "来源输入摘要": payload.get("source_summary") or message.body[:500],
            "创建时间": message.created_at,
            "运行ID": delivery_id,
        }

    def _commercial_delivery_table_url(self) -> str:
        value = os.environ.get(COMMERCIAL_DELIVERY_URL_ENV, "").strip()
        if value:
            return value
        value = self._commercial_delivery_url_from_env_file()
        if value:
            os.environ[COMMERCIAL_DELIVERY_URL_ENV] = value
            return value
        value = self._commercial_delivery_url_from_registry()
        if value:
            os.environ[COMMERCIAL_DELIVERY_URL_ENV] = value
            return value
        raise RuntimeError(f"缺少 {COMMERCIAL_DELIVERY_URL_ENV}，无法写入商单交付多维表")

    def _commercial_delivery_url_from_env_file(self) -> str:
        try:
            for raw_line in MEDIA_ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == COMMERCIAL_DELIVERY_URL_ENV:
                    return value.strip().strip("'").strip('"')
        except OSError:
            return ""
        return ""

    def _commercial_delivery_url_from_registry(self) -> str:
        try:
            registry = json.loads(MEDIA_REGISTRY_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return ""
        table = ((registry.get("tables") or {}).get("commercial_delivery") or {})
        env = table.get("env") if isinstance(table, dict) else {}
        if isinstance(env, dict):
            value = str(env.get(COMMERCIAL_DELIVERY_URL_ENV) or "").strip()
            if value:
                return value
        physical = table.get("table") if isinstance(table, dict) else {}
        if isinstance(physical, dict):
            return str(physical.get("url") or "").strip()
        return ""

    def _commercial_delivery_bitable_refs(self, table_url: str) -> tuple[str, str, str]:
        parsed = urllib.parse.urlparse(table_url)
        query = urllib.parse.parse_qs(parsed.query)
        table_id = (query.get("table") or [""])[0]
        app_token = ""
        wiki_match = re.search(r"/wiki/([A-Za-z0-9]+)", parsed.path)
        if wiki_match:
            payload = self.feishu_service._request("GET", "/wiki/v2/spaces/get_node", params={"token": wiki_match.group(1)})
            node = payload.get("data", {}).get("node") or {}
            if node.get("obj_type") != "bitable":
                raise RuntimeError(f"商单交付目标 wiki 节点不是多维表格：{node.get('obj_type')}")
            app_token = str(node.get("obj_token") or "")
        base_match = re.search(r"/base/([A-Za-z0-9]+)", parsed.path)
        if base_match:
            app_token = base_match.group(1)
        if not app_token:
            raise RuntimeError("商单交付表链接必须包含 /wiki/<token> 或 /base/<app_token>")
        if not table_id:
            table_id = self._commercial_delivery_find_or_create_table(app_token)
        resolved_url = self._commercial_delivery_resolved_table_url(table_url, table_id)
        return app_token, table_id, resolved_url

    def _commercial_delivery_find_or_create_table(self, app_token: str) -> str:
        items = self._commercial_delivery_table_items(app_token)
        for item in items:
            if str(item.get("name") or "").strip() == COMMERCIAL_DELIVERY_TABLE_NAME:
                return str(item.get("table_id") or "")
        payload = self.feishu_service._request(
            "POST",
            f"/bitable/v1/apps/{app_token}/tables",
            json_body={"table": {"name": COMMERCIAL_DELIVERY_TABLE_NAME}},
        )
        table = payload.get("data", {}).get("table") or {}
        table_id = str(table.get("table_id") or payload.get("data", {}).get("table_id") or "")
        if not table_id:
            raise RuntimeError(f"创建商单交付多维表失败：{payload}")
        return table_id

    def _commercial_delivery_table_items(self, app_token: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            payload = self.feishu_service._request("GET", f"/bitable/v1/apps/{app_token}/tables", params=params)
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            batch = data.get("items") if isinstance(data, dict) else []
            if isinstance(batch, list):
                items.extend(item for item in batch if isinstance(item, dict))
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break
        return items

    def _commercial_delivery_field_types(self, app_token: str, table_id: str) -> dict[str, Any]:
        return {
            name: item.get("type")
            for name, item in self._commercial_delivery_field_items(app_token, table_id).items()
        }

    def _commercial_delivery_field_items(self, app_token: str, table_id: str) -> dict[str, dict[str, Any]]:
        payload = self.feishu_service._request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields")
        return {
            str(item.get("field_name")): item
            for item in payload.get("data", {}).get("items", [])
            if item.get("field_name")
        }

    def _ensure_commercial_delivery_fields(self, app_token: str, table_id: str) -> None:
        existing = set(self._commercial_delivery_field_types(app_token, table_id))
        for name, field_type in COMMERCIAL_DELIVERY_FIELD_SPECS.items():
            if name in existing:
                continue
            self.feishu_service._request(
                "POST",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                json_body={"field_name": name, "type": field_type},
            )
            existing.add(name)

    def _ensure_commercial_delivery_select_options(self, app_token: str, table_id: str, raw_fields: dict[str, Any]) -> None:
        items = self._commercial_delivery_field_items(app_token, table_id)
        for name, base_options in COMMERCIAL_DELIVERY_SELECT_OPTIONS.items():
            item = items.get(name)
            if not item:
                continue
            target_type = COMMERCIAL_DELIVERY_FIELD_SPECS.get(name)
            options = [str(option).strip() for option in base_options if str(option).strip()]
            value = raw_fields.get(name)
            if str(value or "").strip() and str(value).strip() not in options:
                options.append(str(value).strip())
            existing = [
                str(option.get("name") or "").strip()
                for option in ((item.get("property") or {}).get("options") or [])
                if str(option.get("name") or "").strip()
            ]
            if item.get("type") == target_type and all(option in existing for option in options):
                continue
            merged = list(options)
            for option in existing:
                if option not in merged:
                    merged.append(option)
            self.feishu_service._request(
                "PUT",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{item.get('field_id')}",
                json_body={
                    "field_name": name,
                    "type": target_type,
                    "property": {"options": [{"name": option} for option in merged]},
                },
            )

    def _commercial_delivery_coerce_value(self, value: Any, field_type: Any) -> Any:
        if field_type == 3:
            text = str(value or "").strip()
            if BITABLE_OPTION_ID_RE.fullmatch(text):
                return None
            return text or None
        if field_type == 5:
            if isinstance(value, datetime):
                return int(value.timestamp() * 1000)
            return value
        if field_type == 15:
            text = self._commercial_delivery_first_url(value)
            if not text:
                return None
            return {"text": text[:120], "link": text}
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value or "").strip()

    @staticmethod
    def _commercial_delivery_first_url(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("link") or value.get("url") or "").strip()
        text = str(value or "")
        match = re.search(r"https?://\S+", text)
        return match.group(0).rstrip(")，。；;") if match else text.strip()

    @staticmethod
    def _commercial_delivery_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _commercial_delivery_missing_items(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        return [item.strip() for item in re.split(r"[、,，;；\n]+", text) if item.strip()] if text else []

    @staticmethod
    def _commercial_delivery_missing_text(value: Any) -> str:
        if isinstance(value, list):
            return "、".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    @staticmethod
    def _commercial_delivery_apply_input_defaults(payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        if not str(payload.get("pr_notes") or "").strip():
            payload["pr_notes"] = COMMERCIAL_DELIVERY_DEFAULT_TEXT
        content = payload.get("content")
        if isinstance(content, dict) and not str(content.get("platform_requirements") or "").strip():
            content["platform_requirements"] = COMMERCIAL_DELIVERY_DEFAULT_TEXT

    @staticmethod
    def _commercial_delivery_id(message: Message, doc_name: str) -> str:
        seed = f"{message.created_at.isoformat()}|{message.source}|{doc_name}|{message.body}"
        return "commercial_delivery_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _commercial_delivery_record_url(table_url: str, record_id: str) -> str:
        if not table_url:
            return ""
        joiner = "&" if urllib.parse.urlparse(table_url).query else "?"
        return f"{table_url}{joiner}record={record_id}"

    @staticmethod
    def _commercial_delivery_resolved_table_url(table_url: str, table_id: str) -> str:
        parsed = urllib.parse.urlparse(table_url)
        query = urllib.parse.parse_qs(parsed.query)
        query["table"] = [table_id]
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))

    @staticmethod
    def _commercial_delivery_success_reply(doc_url: str, warnings: list[str]) -> str:
        return "\n".join(
            [
                "商单交付初稿已生成。",
                f"初稿链接：{doc_url}",
                "下一步：请打开初稿核对内容；确认后提交给 PR 审核。",
                *warnings,
            ]
        )

    @staticmethod
    def _commercial_delivery_failure_reply(_code: str, _detail: str) -> str:
        return "\n".join(
            [
                "商单交付未完成。",
                "请稍后重试原始需求；若仍无法完成，请联系管理员检查交付配置与文档权限。",
            ]
        )
