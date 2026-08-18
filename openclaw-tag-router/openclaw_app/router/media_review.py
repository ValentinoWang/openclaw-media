from __future__ import annotations

from .tag_router_common import *
from media_vault import MediaVaultError, require_tenant_id


class MediaReviewMixin:
    def handle_数据复盘(self, message: Message) -> TaskResult:
        metadata = message.metadata or {}
        try:
            tenant_id = require_tenant_id(metadata.get("tenant_id"))
        except MediaVaultError as exc:
            return TaskResult(ok=False, status="tenant_context_required", reply=str(exc), task_id="")
        downloaded_paths = metadata.get("downloaded_paths") or []
        if not isinstance(downloaded_paths, list):
            downloaded_paths = []
        from selfmedia.review import handle_data_review_command

        parsed = handle_data_review_command(
            message.raw_text,
            tenant_id=tenant_id,
            attachment_paths=[str(path).strip() for path in downloaded_paths if str(path).strip()],
            conversation_context=self._conversation_context(message),
        )
        reply = str(parsed.get("reply") or "").strip()
        content_os_review = self._maybe_write_content_os_data_review(message, parsed, reply)
        if content_os_review.get("reply"):
            reply = f"{reply}\n{content_os_review['reply']}" if reply else content_os_review["reply"]
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status=str(parsed.get("status") or "data_review_done"),
            reply=reply or "【数据复盘】处理完成",
            task_id=str(parsed.get("record_id") or ""),
            feishu_doc=str(parsed.get("doc_link") or ""),
            extra={**parsed, "content_os_review": content_os_review},
        )

    def _looks_like_media_review(self, body: str) -> bool:
        text = body or ""
        if re.search(r"(平台|账号|作者ID|博主|发布链接|作品链接|创作记录ID|作品档案)\s*[=:：]", text):
            return True
        keyword_hits = sum(1 for keyword in MEDIA_REVIEW_KEYWORDS if keyword in text)
        metric_hits = len(MEDIA_REVIEW_METRIC_RE.findall(text))
        return keyword_hits >= 2 or metric_hits >= 2

    def _record_media_review_memory(self, message: Message) -> dict[str, Any]:
        try:
            tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        except MediaVaultError as exc:
            return {"ok": False, "status": "tenant_context_required", "reply": str(exc)}

        from selfmedia.context import record_review_memory

        parsed = record_review_memory(
            message.raw_text,
            tenant_id=tenant_id,
            source=message.source,
        )
        return {**parsed, "ok": True}
