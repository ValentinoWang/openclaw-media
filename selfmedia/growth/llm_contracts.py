"""LLM output contracts for selfmedia growth tasks.

dedup(llm-wrapper-04 + SV-10): growth used to validate its four LLM JSON
task outputs (external_research_brief / commercial_brief /
creation_decision_brief / publishing_pack_build) with a hand-rolled engine
built from five parallel TASK_* field tables
(selfmedia/growth/llm_runner.py's old _task_payload_validation_error). That
duplicated the rule *shape* -- required fields, non-empty fields, list vs.
text fields -- that common/llm_validation.py's LLMValidationContract engine
already exists to express, and left growth as the one LLM JSON consumer in
the repo whose output contract was invisible to validate_llm_payload().

This module registers one LLMValidationContract per task
(selfmedia.growth.<task>.v1) so growth's validation goes through the same
common.llm_validation.validate_llm_payload() call surface as every other
prompt in the repo (see common/llm_validation.py's
LLM_PROMPT_VALIDATION_BINDINGS). Per the audit's correction, only the
*validation* layer moves here -- GrowthLLMJsonRunner keeps its own
retry/pending_manual/evidence-bundle orchestration in llm_runner.py
unchanged; this module has no opinion on retries and never raises outside
of validate_llm_payload's own call.

Each contract's validator reproduces the exact original rule set and
Chinese error text (including the "(任务 {task})" suffixes and per-field
lists) that tests/test_media_growth_v2.py asserts substrings of, verbatim --
by raising LLMPostValidationError(original_message). validate_llm_payload
re-raises a validator's own LLMPostValidationError as-is rather than
prefixing it with the contract_id, so the message growth callers see (and
feed into GrowthLLMJsonRunner's own _semantic_repair_part /
pending_manual["reason"]) is unchanged. Two of the original rules --
_has_sufficient_chinese's CJK-ratio gate and _normalize_task_payload_shapes'
shape coercion -- cannot be expressed as LLMValidationContract's declarative
required_fields/field_types (the former needs a ratio computation, the
latter must run *before* validation, not during it); the Chinese-ratio gate
lives in this module's validator, and the shape normalization stays in
llm_runner.py (called before validate_llm_payload, exactly as it was called
before the old hand-rolled check).
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from common.llm_validation import (
    LLMPostValidationError,
    LLMValidationContract,
    register_llm_validation_contract,
)


TASK_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "external_research_brief": (
        "research_question",
        "media_goal",
        "audience_relevance",
        "content_opportunity",
        "usable_angles",
        "unusable_angles",
        "risk_notes",
        "next_content_actions",
        "source_evidence",
        "display_title",
        "display_summary",
    ),
    "commercial_brief": (
        "brand",
        "project_name",
        "products",
        "platforms",
        "content_format",
        "duration_requirement",
        "locations",
        "required_brand_mentions",
        "must_cover",
        "narrative_direction",
        "interaction_design",
        "compliance_restrictions",
        "deliverables",
        "technical_specs",
        "approval_requirements",
        "cleaned_brief",
        "risk_notes",
        "next_content_actions",
        "source_evidence",
        "display_title",
        "display_summary",
    ),
    "creation_decision_brief": (
        "decision_goal",
        "topic_candidates",
        "recommended_next_capability_id",
        "risk_or_missing_info",
        "display_title",
        "display_summary",
    ),
    "publishing_pack_build": (
        "title",
        "cover_text",
        "caption",
        "hashtags",
        "comment_seed",
        "publish_checklist",
        "risk_notes",
        "display_title",
        "display_summary",
    ),
}

TASK_REQUIRED_NON_EMPTY_FIELDS: dict[str, tuple[str, ...]] = {
    "external_research_brief": (
        "research_question",
        "media_goal",
        "audience_relevance",
        "content_opportunity",
        "usable_angles",
        "risk_notes",
        "next_content_actions",
        "source_evidence",
        "display_title",
        "display_summary",
    ),
    "commercial_brief": (
        "brand",
        "cleaned_brief",
        "source_evidence",
        "display_title",
        "display_summary",
    ),
    "creation_decision_brief": (
        "decision_goal",
        "topic_candidates",
        "recommended_next_capability_id",
        "display_title",
        "display_summary",
    ),
    "publishing_pack_build": (
        "title",
        "cover_text",
        "caption",
        "comment_seed",
        "publish_checklist",
        "risk_notes",
        "display_title",
        "display_summary",
    ),
}

TASK_LIST_FIELDS: dict[str, tuple[str, ...]] = {
    "external_research_brief": (
        "usable_angles",
        "unusable_angles",
        "risk_notes",
        "next_content_actions",
        "source_evidence",
    ),
    "commercial_brief": (
        "products",
        "platforms",
        "locations",
        "required_brand_mentions",
        "must_cover",
        "narrative_direction",
        "interaction_design",
        "compliance_restrictions",
        "deliverables",
        "approval_requirements",
        "risk_notes",
        "next_content_actions",
        "source_evidence",
    ),
    "creation_decision_brief": ("topic_candidates", "risk_or_missing_info"),
    "publishing_pack_build": ("hashtags", "publish_checklist", "risk_notes"),
}

TASK_TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    "external_research_brief": (
        "research_question",
        "media_goal",
        "audience_relevance",
        "content_opportunity",
        "display_title",
        "display_summary",
    ),
    "commercial_brief": (
        "brand",
        "project_name",
        "content_format",
        "duration_requirement",
        "cleaned_brief",
        "display_title",
        "display_summary",
    ),
    "creation_decision_brief": (
        "decision_goal",
        "display_title",
        "display_summary",
    ),
    "publishing_pack_build": (
        "title",
        "cover_text",
        "caption",
        "comment_seed",
        "display_title",
        "display_summary",
    ),
}

TASK_TEXT_LIST_FIELDS: dict[str, tuple[str, ...]] = {
    "external_research_brief": ("usable_angles", "unusable_angles", "risk_notes", "next_content_actions"),
    "commercial_brief": (
        "platforms",
        "required_brand_mentions",
        "must_cover",
        "narrative_direction",
        "interaction_design",
        "compliance_restrictions",
        "approval_requirements",
        "risk_notes",
        "next_content_actions",
    ),
    "creation_decision_brief": ("risk_or_missing_info",),
    "publishing_pack_build": ("publish_checklist", "risk_notes"),
}

# Also reused by llm_runner.py's _normalize_task_payload_shapes, which must
# run (unchanged) before validate_llm_payload -- see module docstring.
MAPPING_LIST_FIELDS: dict[str, tuple[str, ...]] = {
    "external_research_brief": ("source_evidence",),
    "commercial_brief": ("products", "locations", "deliverables", "source_evidence"),
}

DECISION_CANDIDATE_REQUIRED_FIELDS = (
    "title",
    "target_audience",
    "pain_point",
    "content_angle",
    "single_problem",
    "self_check",
    "source_refs",
)
DECISION_CANDIDATE_TEXT_FIELDS = DECISION_CANDIDATE_REQUIRED_FIELDS[:-1]
CHINESE_OUTPUT_MIN_RATIO = 0.2


def _has_semantic_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return value is not None


def _has_sufficient_chinese(value: str) -> bool:
    text = re.sub(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![A-Za-z0-9_])", "", value.strip())
    text = re.sub(r"(?<![A-Za-z0-9])[A-Za-z]+[A-Z][A-Za-z0-9]*(?![A-Za-z0-9])", "", text)
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    letters = len(re.findall(r"[A-Za-z\u3400-\u9fff]", text))
    return cjk / letters >= CHINESE_OUTPUT_MIN_RATIO if letters else True


def _decision_candidate_validation_error(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "增长内容结果至少需要一个选题候选"
    for index, candidate in enumerate(value):
        if not isinstance(candidate, dict):
            return f"增长内容结果的第 {index + 1} 个选题候选必须是对象"
        invalid_text = [
            field
            for field in DECISION_CANDIDATE_TEXT_FIELDS
            if not isinstance(candidate.get(field), str) or not candidate[field].strip()
        ]
        if invalid_text:
            return f"增长内容结果的第 {index + 1} 个选题候选文本字段无效：{', '.join(invalid_text)}"
        non_chinese = [
            field
            for field in DECISION_CANDIDATE_TEXT_FIELDS
            if not _has_sufficient_chinese(candidate[field])
        ]
        if non_chinese:
            return f"增长内容结果的第 {index + 1} 个选题候选文本必须使用中文：{', '.join(non_chinese)}"
        missing = [field for field in DECISION_CANDIDATE_REQUIRED_FIELDS if not _has_semantic_value(candidate.get(field))]
        if missing:
            return f"增长内容结果的第 {index + 1} 个选题候选缺少必填字段：{', '.join(missing)}"
        if not isinstance(candidate.get("source_refs"), list):
            return f"增长内容结果的第 {index + 1} 个选题候选 source_refs 必须是数组"
        if any(not isinstance(item, str) or not item.strip() for item in candidate["source_refs"]):
            return f"增长内容结果的第 {index + 1} 个选题候选 source_refs 必须包含非空文本"
    return ""


def _task_payload_validation_message(task: str, payload: Mapping[str, Any]) -> str:
    """The exact rule set and Chinese wording of the pre-dedup hand-rolled check."""
    required_fields = TASK_REQUIRED_FIELDS.get(task)
    if not required_fields:
        return ""
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return f"增长内容结果缺少必填字段（任务 {task}）：{', '.join(missing)}"
    list_fields = TASK_LIST_FIELDS.get(task, ())
    invalid_lists = [field for field in list_fields if not isinstance(payload.get(field), list)]
    if invalid_lists:
        return f"增长内容结果的列表字段格式无效（任务 {task}）：{', '.join(invalid_lists)}"
    invalid_text_fields = [field for field in TASK_TEXT_FIELDS.get(task, ()) if not isinstance(payload.get(field), str)]
    if invalid_text_fields:
        return f"增长内容结果的文本字段格式无效（任务 {task}）：{', '.join(invalid_text_fields)}"
    invalid_text_lists = [
        field
        for field in TASK_TEXT_LIST_FIELDS.get(task, ())
        if any(not isinstance(item, str) for item in payload[field])
    ]
    if invalid_text_lists:
        return f"增长内容结果的列表项必须是文本（任务 {task}）：{', '.join(invalid_text_lists)}"
    non_chinese_fields = [
        field
        for field in TASK_TEXT_FIELDS.get(task, ())
        if not _has_sufficient_chinese(payload[field])
    ]
    if non_chinese_fields:
        return f"增长内容结果的创作者可见文本必须使用中文（任务 {task}）：{', '.join(non_chinese_fields)}"
    non_chinese_lists = [
        field
        for field in TASK_TEXT_LIST_FIELDS.get(task, ())
        if any(not _has_sufficient_chinese(item) for item in payload[field])
    ]
    if non_chinese_lists:
        return f"增长内容结果的创作者可见列表文本必须使用中文（任务 {task}）：{', '.join(non_chinese_lists)}"
    non_empty_fields = TASK_REQUIRED_NON_EMPTY_FIELDS.get(task, ())
    empty = [field for field in non_empty_fields if not _has_semantic_value(payload.get(field))]
    if empty:
        return f"增长内容结果的必填字段为空（任务 {task}）：{', '.join(empty)}"
    if task == "commercial_brief" and not isinstance(payload.get("technical_specs"), dict):
        return "增长内容结果的 technical_specs 必须是对象（任务 commercial_brief）"
    for field in MAPPING_LIST_FIELDS.get(task, ()):
        if any(not isinstance(item, dict) for item in payload[field]):
            return f"增长内容结果的 {field} 必须是对象数组（任务 {task}）"
    if task == "creation_decision_brief":
        candidate_error = _decision_candidate_validation_error(payload.get("topic_candidates"))
        if candidate_error:
            return candidate_error
    return ""


def _make_task_validator(task: str):
    def _validate(payload: dict[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
        message = _task_payload_validation_message(task, payload)
        if message:
            raise LLMPostValidationError(message)
        return payload

    return _validate


CONTRACT_ID_BY_TASK: dict[str, str] = {}
for _task_name in TASK_REQUIRED_FIELDS:
    _contract_id = f"selfmedia.growth.{_task_name}.v1"
    register_llm_validation_contract(
        LLMValidationContract(
            contract_id=_contract_id,
            profile="bounded_open",
            validator=_make_task_validator(_task_name),
        )
    )
    CONTRACT_ID_BY_TASK[_task_name] = _contract_id
del _task_name, _contract_id
