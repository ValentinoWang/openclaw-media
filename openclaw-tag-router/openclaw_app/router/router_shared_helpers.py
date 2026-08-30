from __future__ import annotations

from common.feishu_docx_writer import docx_heading_block, docx_text_block
from common.social_runtime import feishu_first_url, feishu_first_url_or_text

from .tag_router_common import *


class RouterSharedHelpersMixin:
    def _configured_bitable_url(self, kind: str) -> str:
        config_path = getattr(self.reminder_service, "config_paths", {}).get(kind, "")
        if config_path:
            try:
                data = json.loads(Path(config_path).read_text(encoding="utf-8"))
                url = str(data.get("url") or "").strip()
                if url:
                    return url
            except Exception:
                pass
        return str(getattr(self.reminder_service, "bitable_url", "") or "").strip()

    def _first_url_from_value(self, value: Any) -> str:
        """Thin wrapper — the recursive extraction now lives in common.social_runtime
        (feishu_first_url) so _coerce_feishu_url's field_type-15 handling shares it.
        Kept as a method because callers outside the coercion path (e.g.
        _first_doc_link_from_unified_fields) still reach it via self."""
        return feishu_first_url(value)

    def _docx_heading_block(self, level: int, text: str) -> dict[str, Any]:
        """Thin wrapper — block construction now lives in
        common.feishu_docx_writer (FC-08 dedup audit). Kept as a method:
        unified_creation.py/selfmedia_cognition.py inject it as a
        (level, text) heading_factory callable via self._docx_heading_block."""
        return docx_heading_block(level, text)

    def _docx_text_block(self, text: str) -> dict[str, Any]:
        """Thin wrapper — see _docx_heading_block."""
        return docx_text_block(text)

    def _docx_text_blocks(self, text: str) -> list[dict[str, Any]]:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if not lines:
            lines = ["待明确"]
        return [self._docx_text_block(line) for line in lines]

    def _doc_friendly_list(self, value: str) -> str:
        lines = []
        for raw_line in str(value or "").splitlines():
            item = re.sub(r"^[-*+]\s*", "", raw_line).strip()
            if item:
                lines.append(f"• {item}")
        return "\n".join(lines) if lines else "待明确"

    def _extract_first_url(self, text: str) -> str:
        """Thin wrapper — url-3 dedup audit: unlike _first_url_from_value,
        this falls back to the original text (not "") on a miss, so it
        shares common.social_runtime.feishu_first_url_or_text rather than
        feishu_first_url."""
        return feishu_first_url_or_text(text)

    def _extract_labeled_text(self, body: str, label: str) -> str:
        match = re.search(rf"{re.escape(label)}[：:]\s*(.+)", body)
        return match.group(1).strip() if match else ""

    def _extract_output_path(self, output: str, prefix: str) -> str:
        for line in output.splitlines():
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        return ""
