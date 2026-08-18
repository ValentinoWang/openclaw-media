from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from selfmedia.growth import parse_media_growth_input
from selfmedia.growth.contracts import extract_urls
from selfmedia.growth.knowledge_evidence_contract import KnowledgeEvidenceBundle


MAX_EVIDENCE_TEXT_CHARS = 20000
EVIDENCE_PARAM_LABELS = (
    "证据",
    "evidence",
    "source_evidence",
    "资料",
    "材料",
    "引用文本",
    "草稿",
    "正文",
    "draft",
    "body",
)
ANALYSIS_PATH_PARAM_LABELS = (
    "analysis_path",
    "分析文件",
    "分析结果",
    "证据文件",
    "evidence_path",
)


class KnowledgeEvidenceExporter:
    def __init__(self, content_flow_client: Any | None = None) -> None:
        self.content_flow_client = content_flow_client

    def export(self, text: str, *, query: str = "") -> KnowledgeEvidenceBundle:
        parsed = parse_media_growth_input(text)
        evidence_items: list[dict[str, Any]] = []
        limitations: list[str] = []
        blocked_sources: list[str] = []

        pasted_evidence = _first_param_value(parsed, EVIDENCE_PARAM_LABELS)
        if pasted_evidence:
            evidence_items.append(_pasted_evidence_item(pasted_evidence))

        for analysis_path in _analysis_paths(parsed):
            item = self._evidence_from_analysis_file(analysis_path)
            if item:
                evidence_items.append(item)
            else:
                blocked_sources.append(str(analysis_path))
                limitations.append(f"analysis file is missing or has no source text: {analysis_path}")

        for url in extract_urls(text):
            item, note = self._evidence_from_url(url)
            if item:
                evidence_items.append(item)
            else:
                blocked_sources.append(url)
                if note:
                    limitations.append(note)

        deduped_items = _dedupe_evidence_items(evidence_items)
        status = "ready" if deduped_items else "pending_manual"
        if not deduped_items and not limitations:
            limitations.append("No typed Knowledge evidence source was available.")
            blocked_sources.append("knowledge_evidence_bundle")
        return KnowledgeEvidenceBundle.from_dict(
            {
                "bundle_id": _bundle_id(query or parsed.content_text or text, deduped_items),
                "query": query or parsed.content_text or text,
                "status": status,
                "source_system": "knowledge",
                "evidence_items": deduped_items,
                "limitations": _dedupe_strings(limitations),
                "blocked_sources": _dedupe_strings(blocked_sources),
            }
        )

    def _evidence_from_url(self, url: str) -> tuple[dict[str, Any] | None, str]:
        if not getattr(self.content_flow_client, "analyze", None):
            return None, "content_flow_client.analyze is required to export URL evidence."
        try:
            payload = self.content_flow_client.analyze(url)
        except Exception as exc:
            return None, f"content-flow analyze failed for URL evidence: {exc}"
        if not isinstance(payload, dict):
            return None, "content-flow analyze returned a non-object payload."
        item = _evidence_item_from_content_flow_payload(url, payload)
        if item:
            return item, ""
        reason = str(payload.get("reason") or payload.get("error") or payload.get("error_code") or "content-flow returned no extractable source text")
        return None, reason

    @staticmethod
    def _evidence_from_analysis_file(path: str | Path) -> dict[str, Any] | None:
        file_path = Path(path).expanduser()
        if not file_path.is_file():
            return None
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return _evidence_item_from_analysis_payload(payload, fallback_url=file_path.resolve().as_uri(), metadata={"analysis_path": str(file_path)})


def _evidence_item_from_content_flow_payload(url: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    metadata = {
        "content_flow_status": str(payload.get("status") or ""),
        "media_type": str(payload.get("media_type") or analysis.get("media_type") or ""),
        "analysis_path": str(payload.get("analysis_path") or ""),
        "structure_path": str(payload.get("structure_path") or analysis.get("article_structure_path") or ""),
        "caption_path": str(payload.get("caption_path") or ""),
        "media_dir": str(payload.get("media_dir") or ""),
    }
    item = _evidence_item_from_analysis_payload(
        {**analysis, **{key: value for key, value in payload.items() if key not in {"analysis"}}},
        fallback_url=url,
        metadata=metadata,
    )
    if item is not None:
        return item
    caption = _clean_source_text(payload.get("caption"))
    if caption:
        return _ready_evidence_item(
            source_url=url,
            source_type=_source_type_from_payload(payload, analysis),
            text_or_summary=caption,
            citations=[url],
            metadata=metadata,
            limitations=_limitations_from_payload(payload, analysis),
        )
    return None


def _evidence_item_from_analysis_payload(
    payload: dict[str, Any],
    *,
    fallback_url: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    source_text = _first_source_text(
        payload.get("full_content"),
        payload.get("work_copy"),
        payload.get("caption"),
        payload.get("transcript"),
        payload.get("ocr_text"),
        payload.get("body_text"),
        payload.get("text"),
    )
    if not source_text:
        return None
    source_url = _first_url_value(
        payload.get("source_url"),
        payload.get("canonical_url"),
        payload.get("resolved_url"),
        payload.get("video_url"),
        payload.get("note_url"),
        payload.get("page_url"),
        fallback_url,
    )
    return _ready_evidence_item(
        source_url=source_url,
        source_type=_source_type_from_payload(payload, {}),
        text_or_summary=source_text,
        citations=[source_url],
        metadata={**(metadata or {}), "analysis_provider": str(payload.get("analysis_provider") or "")},
        limitations=_limitations_from_payload(payload, {}),
    )


def _ready_evidence_item(
    *,
    source_url: str,
    source_type: str,
    text_or_summary: str,
    citations: list[str],
    metadata: dict[str, Any] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    cleaned_text = _clean_source_text(text_or_summary)
    return {
        "source_url": source_url,
        "source_type": source_type or "source_extract",
        "text_or_summary": cleaned_text[:MAX_EVIDENCE_TEXT_CHARS],
        "citations": _dedupe_strings(citations),
        "limitations": _dedupe_strings(limitations or ()),
        "status": "ready",
        "metadata": {key: value for key, value in (metadata or {}).items() if value},
    }


def _pasted_evidence_item(text: str) -> dict[str, Any]:
    cleaned = _clean_source_text(text)
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
    source_url = f"user://pasted-evidence/{digest}"
    return _ready_evidence_item(
        source_url=source_url,
        source_type="pasted_evidence",
        text_or_summary=cleaned,
        citations=[source_url],
    )


def _analysis_paths(parsed: Any) -> tuple[str, ...]:
    paths: list[str] = []
    for label in ANALYSIS_PATH_PARAM_LABELS:
        value = parsed.value(label)
        if value and value not in paths:
            paths.append(value)
    return tuple(paths)


def _first_param_value(parsed: Any, labels: tuple[str, ...]) -> str:
    for label in labels:
        value = parsed.value(label)
        if value:
            return value
    return ""


def _first_source_text(*values: Any) -> str:
    for value in values:
        text = _clean_source_text(value)
        if text:
            return text
    return ""


def _clean_source_text(value: Any) -> str:
    if isinstance(value, list):
        value = "\n".join(str(item or "") for item in value)
    elif isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _first_url_value(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        urls = extract_urls(text)
        if urls:
            return urls[0]
        if "://" in text:
            return text
    return ""


def _source_type_from_payload(payload: dict[str, Any], analysis: dict[str, Any]) -> str:
    media_type = str(payload.get("media_type") or analysis.get("media_type") or "").strip()
    provider = str(payload.get("analysis_provider") or analysis.get("analysis_provider") or "").strip()
    if media_type == "article" or "wechat" in provider:
        return "wechat_article"
    if media_type:
        return f"content_flow_{media_type}"
    return "content_flow_analysis"


def _limitations_from_payload(payload: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for key in ("incomplete_reason", "semantic_failure_reason", "source_extraction_note", "reason", "error_code"):
        value = str(payload.get(key) or analysis.get(key) or "").strip()
        if value:
            notes.append(value)
    return _dedupe_strings(notes)


def _dedupe_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        source_url = str(item.get("source_url") or "")
        text = str(item.get("text_or_summary") or "")
        key = (source_url, hashlib.sha256(text.encode("utf-8")).hexdigest())
        if source_url and text and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _dedupe_strings(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _bundle_id(query: str, evidence_items: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        {
            "query": str(query or ""),
            "sources": [
                {
                    "source_url": item.get("source_url"),
                    "source_type": item.get("source_type"),
                    "text_or_summary": item.get("text_or_summary"),
                }
                for item in evidence_items
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "knowledge_bundle_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
