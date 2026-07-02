from __future__ import annotations

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
        if value in (None, "", []):
            return ""
        if isinstance(value, dict):
            for key in ("link", "url", "doc", "document_url", "recreation_doc", "inspiration_doc", "material_doc", "creation_doc"):
                found = self._first_url_from_value(value.get(key))
                if found:
                    return found
            for item in value.values():
                found = self._first_url_from_value(item)
                if found:
                    return found
            return ""
        if isinstance(value, (list, tuple, set)):
            for item in value:
                found = self._first_url_from_value(item)
                if found:
                    return found
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if text.startswith("{") or text.startswith("["):
            try:
                return self._first_url_from_value(json.loads(text))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        match = re.search(r"https?://[^\s\"'<>]+", text)
        return match.group(0).rstrip("，。；;、)") if match else ""

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
