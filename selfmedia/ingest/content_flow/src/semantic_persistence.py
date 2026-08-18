from __future__ import annotations

import hashlib
import json
from typing import Any


LLM_CLEANED_USER_FIELDS_VERSION = "llm_cleaned_user_fields_v1"
LLM_SEMANTIC_PERSISTENCE_METADATA_KEY = "_llm_semantic_persistence"

# These are semantic fields that must arrive at the knowledge writer exactly as
# the LLM produced them. Source URLs, attachment metadata, and local paths are
# factual transport metadata and intentionally are not included here.
LLM_CLEANED_KNOWLEDGE_FIELD_NAMES = (
    "名称",
    "一级分类",
    "二级分类",
    "目标人群",
    "核心痛点",
    "全部文案",
    "全部内容",
    "隐形信息",
    "镜头/画面线索",
    "可迁移表达",
    "摘要",
    "问题提取",
    "价值判断",
    "应用建议",
    "关键词/标签",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _value_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def analysis_user_field_contract_issue(
    analysis: dict[str, Any] | None,
    *,
    require_work_copy: bool | None = None,
) -> str:
    """Return the first reason an analysis cannot populate user-visible fields."""
    if not isinstance(analysis, dict) or not analysis:
        return "analysis_missing"
    if analysis.get("analysis_status") in {"needs_model_rerun", "source_extracted_needs_llm_semantics"}:
        return "analysis_not_complete"
    if analysis.get("incomplete_reason"):
        return "analysis_incomplete"
    if _text(analysis.get("semantic_persistence_version")) != LLM_CLEANED_USER_FIELDS_VERSION:
        return "llm_cleaning_provenance_missing"
    if not _text(analysis.get("analysis_provider")):
        return "analysis_provider_missing"
    if not _string(analysis.get("title")):
        return "llm_title_missing"
    if not _string(analysis.get("full_content")):
        return "llm_cleaned_full_content_missing"
    if require_work_copy is None:
        require_work_copy = bool(_text(analysis.get("caption")))
    if require_work_copy and not _string(analysis.get("work_copy")):
        return "llm_cleaned_work_copy_missing"
    return ""


def build_user_field_persistence_metadata(
    analysis: dict[str, Any],
    user_fields: dict[str, Any],
    *,
    raw_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Create a non-user-visible proof that a writer can validate before persistence."""
    require_work_copy = bool(_text(user_fields.get("全部文案")))
    issue = analysis_user_field_contract_issue(analysis, require_work_copy=require_work_copy)
    if issue:
        raise ValueError(f"LLM_SEMANTIC_PERSISTENCE_REQUIRED:{issue}")
    evidence = {str(key): value for key, value in raw_evidence.items() if value not in (None, "", [], {})}
    if not evidence:
        raise ValueError("LLM_SEMANTIC_PERSISTENCE_REQUIRED:raw_evidence_missing")
    field_digests = {
        field_name: _value_digest(user_fields[field_name])
        for field_name in LLM_CLEANED_KNOWLEDGE_FIELD_NAMES
        if field_name in user_fields and user_fields[field_name] not in (None, "", [], {})
    }
    if not field_digests:
        raise ValueError("LLM_SEMANTIC_PERSISTENCE_REQUIRED:llm_user_fields_missing")
    return {
        "version": LLM_CLEANED_USER_FIELDS_VERSION,
        "analysis_provider": _text(analysis.get("analysis_provider")),
        "analysis_model": _text(analysis.get("analysis_model")),
        "content_cleaning_provider": _text(analysis.get("content_cleaning_provider")) or _text(analysis.get("analysis_provider")),
        "raw_evidence": evidence,
        "field_digests": field_digests,
    }


def user_field_persistence_metadata_issue(metadata: Any, user_fields: dict[str, Any]) -> str:
    """Return the reason a knowledge writer must refuse a user-field write."""
    if not isinstance(metadata, dict):
        return "llm_persistence_metadata_missing"
    if _text(metadata.get("version")) != LLM_CLEANED_USER_FIELDS_VERSION:
        return "llm_persistence_version_missing"
    if not _text(metadata.get("analysis_provider")):
        return "llm_persistence_provider_missing"
    if not isinstance(metadata.get("raw_evidence"), dict) or not metadata["raw_evidence"]:
        return "raw_evidence_missing"
    field_digests = metadata.get("field_digests")
    if not isinstance(field_digests, dict) or not field_digests:
        return "llm_user_field_digests_missing"
    for field_name, expected_digest in field_digests.items():
        if field_name not in LLM_CLEANED_KNOWLEDGE_FIELD_NAMES:
            return "llm_user_field_digest_scope_invalid"
        if field_name not in user_fields:
            return f"llm_user_field_missing:{field_name}"
        if _value_digest(user_fields[field_name]) != _text(expected_digest):
            return f"llm_user_field_changed:{field_name}"
    return ""
