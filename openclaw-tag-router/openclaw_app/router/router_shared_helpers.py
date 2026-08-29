from __future__ import annotations

from common.social_runtime import feishu_first_url

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
        normalized_level = min(max(level, 1), 9)
        block_type = normalized_level + 2
        key = f"heading{normalized_level}"
        return {
            "block_type": block_type,
            key: {"elements": [{"text_run": {"content": str(text or "")[:500]}}]},
        }

    def _docx_text_block(self, text: str) -> dict[str, Any]:
        return {
            "block_type": 2,
            "text": {"elements": [{"text_run": {"content": str(text or "")[:1800]}}]},
        }

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
        match = re.search(r"https?://[^\s)\]，。；;、]+", text or "")
        return match.group(0).strip() if match else (text or "").strip()

    def _extract_labeled_text(self, body: str, label: str) -> str:
        match = re.search(rf"{re.escape(label)}[：:]\s*(.+)", body)
        return match.group(1).strip() if match else ""

    def _extract_output_path(self, output: str, prefix: str) -> str:
        for line in output.splitlines():
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        return ""
