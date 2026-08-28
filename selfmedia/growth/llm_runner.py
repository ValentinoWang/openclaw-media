from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from common.llm_settings import load_profile_llm_settings

from .knowledge_evidence_contract import (
    KnowledgeEvidenceBundle,
    KnowledgeEvidenceContractError,
    coerce_knowledge_evidence_bundle,
)


DEFAULT_GROWTH_LLM_PROFILE = "media_analysis"
GROWTH_LLM_SUCCESS_STATUSES = frozenset(
    {"done", "complete", "completed", "structured", "ready", "success", "succeeded"}
)
GROWTH_JSON_INSTRUCTIONS = (
    "你是一名中文内容增长与运营编辑。你的输出为创作者提供基于已验证证据的增长判断、可执行策略和人工复核所需的风险提示。\n\n"
    "输出协议：\n"
    "只输出一个合法 JSON object，不要输出 Markdown 或解释。不得将 Knowledge bot 的自然语言回复作为证据；"
    "只能使用提供的已类型化 KnowledgeEvidenceBundle evidence_items。收到账号长期上下文时，必须继承其中已验证的账号定位和复盘结论；"
    "上下文缺少时只能在风险字段说明待补材料，不得补造账号事实、实时指标或已经发布的结果。"
)

GrowthJsonProvider = Callable[..., dict[str, Any]]
SettingsLoader = Callable[[str], Any]


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
        "recommended_next_capability_id",
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
    "publishing_pack_build": ("hashtags", "publish_checklist", "risk_notes"),
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


@dataclass(frozen=True)
class GrowthLLMJsonRunner:
    provider: GrowthJsonProvider | None = None
    settings: Any | None = None
    settings_loader: SettingsLoader = load_profile_llm_settings
    profile_name: str = DEFAULT_GROWTH_LLM_PROFILE
    max_retries: int = 1
    instructions: str = GROWTH_JSON_INSTRUCTIONS

    def run_json(
        self,
        *,
        task: str,
        prompt: str,
        evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
        parts: Iterable[dict[str, Any]] = (),
        require_evidence: bool = True,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bundle: KnowledgeEvidenceBundle | None = None
        if require_evidence or evidence_bundle is not None:
            bundle = coerce_knowledge_evidence_bundle(evidence_bundle)
        if require_evidence:
            try:
                assert bundle is not None
                bundle.require_ready()
            except KnowledgeEvidenceContractError as exc:
                return _pending_manual(
                    str(exc),
                    task=task,
                    evidence_bundle=bundle,
                )
        request_parts = _build_request_parts(
            task=task,
            prompt=prompt,
            base_parts=parts,
            evidence_bundle=bundle,
            extra_context=extra_context or {},
        )
        if self.provider is None:
            return _pending_manual(
                "Growth LLM JSON provider is unavailable; semantic artifact was not written",
                task=task,
                evidence_bundle=bundle,
                blocked_sources=("growth_llm_json_provider",),
            )
        provider = self.provider
        settings = self.settings if self.settings is not None else self.settings_loader(self.profile_name)
        provider_parts = request_parts
        for attempt in range(self.max_retries + 1):
            try:
                payload = provider(
                    provider_parts,
                    settings,
                    max_retries=self.max_retries,
                    error_prefix="Mediaclaw LLM JSON validation failed",
                    instructions=self.instructions,
                )
            except Exception as exc:
                return _pending_manual(
                    f"Growth LLM JSON provider failed: {exc}",
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=("growth_llm_json_provider",),
                )
            if not isinstance(payload, dict):
                return _pending_manual(
                    "Growth LLM JSON provider returned a non-object payload",
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=("growth_llm_json_provider",),
                )
            status = str(payload.get("status") or payload.get("runtime_status") or "").strip()
            if not status:
                return _pending_manual(
                    "Growth LLM JSON provider returned no status; manual review is required",
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=("growth_llm_json_provider",),
                )
            if status not in GROWTH_LLM_SUCCESS_STATUSES:
                return _pending_manual(
                    str(payload.get("reason") or f"Growth LLM returned status={status}"),
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=tuple(payload.get("blocked_sources") or ()),
                )
            result = dict(payload)
            result["status"] = "done"
            if "runtime_status" in result:
                result["runtime_status"] = "done"
            result = _normalize_task_payload_shapes(task, result)
            validation_error = _task_payload_validation_error(task, result)
            if not validation_error:
                if bundle is not None:
                    result.setdefault("evidence_bundle_id", bundle.bundle_id)
                    result.setdefault("evidence_status", bundle.status)
                return result
            if attempt >= self.max_retries:
                return _pending_manual(
                    validation_error,
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=("growth_llm_json_provider",),
                )
            provider_parts = [*request_parts, _semantic_repair_part(task, validation_error, result)]
        raise AssertionError("unreachable Growth LLM retry state")


def run_growth_json(
    *,
    task: str,
    prompt: str,
    evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
    provider: GrowthJsonProvider | None = None,
    settings: Any | None = None,
    require_evidence: bool = True,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runner = GrowthLLMJsonRunner(provider=provider, settings=settings)
    return runner.run_json(
        task=task,
        prompt=prompt,
        evidence_bundle=evidence_bundle,
        require_evidence=require_evidence,
        extra_context=extra_context,
    )


def _build_request_parts(
    *,
    task: str,
    prompt: str,
    base_parts: Iterable[dict[str, Any]],
    evidence_bundle: KnowledgeEvidenceBundle | None,
    extra_context: dict[str, Any],
) -> list[dict[str, Any]]:
    request_parts = [dict(part) for part in base_parts]
    request = {
        "task": str(task or "").strip(),
        "prompt": str(prompt or "").strip(),
        "extra_context": dict(extra_context),
    }
    if evidence_bundle is not None:
        request["knowledge_evidence_bundle"] = evidence_bundle.to_dict()
    request_parts.append(
        {
            "text": (
                "Mediaclaw JSON request:\n"
                + json.dumps(request, ensure_ascii=False, sort_keys=True, indent=2)
            )
        }
    )
    return request_parts


def _semantic_repair_part(task: str, validation_error: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": (
            "The previous Mediaclaw JSON is incomplete. Return one corrected JSON object only. "
            "Preserve grounded values, do not invent unsupported facts, use empty arrays/objects only for optional "
            "fields with no evidence, and include every required field.\n"
            + json.dumps(
                {
                    "task": task,
                    "validation_error": validation_error,
                    "required_fields": list(TASK_REQUIRED_FIELDS.get(task, ())),
                    "previous_payload": payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
    }


def _pending_manual(
    reason: str,
    *,
    task: str,
    evidence_bundle: KnowledgeEvidenceBundle | None,
    blocked_sources: tuple[str, ...] = (),
) -> dict[str, Any]:
    limitations = list(evidence_bundle.limitations) if evidence_bundle is not None else []
    bundle_blocked_sources = list(evidence_bundle.blocked_sources) if evidence_bundle is not None else []
    return {
        "status": "pending_manual",
        "runtime_status": "pending_manual",
        "task": str(task or "").strip(),
        "reason": reason,
        "evidence_bundle_id": evidence_bundle.bundle_id if evidence_bundle is not None else "",
        "evidence_status": evidence_bundle.status if evidence_bundle is not None else "pending_manual",
        "limitations": limitations,
        "blocked_sources": _dedupe((*bundle_blocked_sources, *blocked_sources)),
    }


def _task_payload_validation_error(task: str, payload: dict[str, Any]) -> str:
    required_fields = TASK_REQUIRED_FIELDS.get(str(task or "").strip())
    if not required_fields:
        return ""
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return f"Growth LLM output missing required semantic fields for {task}: {', '.join(missing)}"
    list_fields = TASK_LIST_FIELDS.get(task, ())
    invalid_lists = [field for field in list_fields if not isinstance(payload.get(field), list)]
    if invalid_lists:
        return f"Growth LLM output has invalid list fields for {task}: {', '.join(invalid_lists)}"
    invalid_text_fields = [field for field in TASK_TEXT_FIELDS.get(task, ()) if not isinstance(payload.get(field), str)]
    if invalid_text_fields:
        return f"Growth LLM output has invalid text fields for {task}: {', '.join(invalid_text_fields)}"
    invalid_text_lists = [
        field
        for field in TASK_TEXT_LIST_FIELDS.get(task, ())
        if any(not isinstance(item, str) for item in payload[field])
    ]
    if invalid_text_lists:
        return f"Growth LLM output has non-text list items for {task}: {', '.join(invalid_text_lists)}"
    non_empty_fields = TASK_REQUIRED_NON_EMPTY_FIELDS.get(task, ())
    empty = [field for field in non_empty_fields if not _has_semantic_value(payload.get(field))]
    if empty:
        return f"Growth LLM output has empty required semantic fields for {task}: {', '.join(empty)}"
    if task == "commercial_brief" and not isinstance(payload.get("technical_specs"), dict):
        return "Growth LLM output has invalid technical_specs for commercial_brief"
    mapping_list_fields = {
        "external_research_brief": ("source_evidence",),
        "commercial_brief": ("products", "locations", "deliverables", "source_evidence"),
    }.get(task, ())
    for field in mapping_list_fields:
        if any(not isinstance(item, dict) for item in payload[field]):
            return f"Growth LLM output field {field} for {task} must contain objects"
    if task == "creation_decision_brief":
        candidate_error = _decision_candidate_validation_error(payload.get("topic_candidates"))
        if candidate_error:
            return candidate_error
    return ""


def _normalize_task_payload_shapes(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    mapping_list_fields = {
        "external_research_brief": {"source_evidence"},
        "commercial_brief": {"products", "locations", "deliverables", "source_evidence"},
    }.get(task, set())
    for field in TASK_LIST_FIELDS.get(task, ()):
        if field not in result or isinstance(result[field], list):
            continue
        value = result[field]
        if field in mapping_list_fields and isinstance(value, dict):
            result[field] = [value]
        elif field not in mapping_list_fields and isinstance(value, (str, int, float, bool)):
            text = str(value).strip()
            result[field] = [text] if text else []
    if task == "commercial_brief" and "technical_specs" in result and not isinstance(result["technical_specs"], dict):
        value = result["technical_specs"]
        if isinstance(value, list):
            result["technical_specs"] = {"items": value}
        elif isinstance(value, (str, int, float, bool)) and str(value).strip():
            result["technical_specs"] = {"description": str(value).strip()}
    if task == "creation_decision_brief" and isinstance(result.get("topic_candidates"), list):
        normalized_candidates: list[Any] = []
        for candidate in result["topic_candidates"]:
            if not isinstance(candidate, dict):
                normalized_candidates.append(candidate)
                continue
            normalized = dict(candidate)
            pain_point = normalized.get("pain_point") or normalized.get("audience_pain")
            if pain_point is not None:
                normalized["pain_point"] = pain_point
                # Keep the released Growth key readable for existing consumers.
                normalized.setdefault("audience_pain", pain_point)
            normalized_candidates.append(normalized)
        result["topic_candidates"] = normalized_candidates
    return result


def _has_semantic_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return value is not None


def _decision_candidate_validation_error(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "Growth LLM output requires at least one topic candidate"
    for index, candidate in enumerate(value):
        if not isinstance(candidate, dict):
            return f"Growth LLM topic candidate {index} must be an object"
        text_fields = DECISION_CANDIDATE_REQUIRED_FIELDS[:-1]
        invalid_text = [
            field
            for field in text_fields
            if not isinstance(candidate.get(field), str) or not candidate[field].strip()
        ]
        if invalid_text:
            return f"Growth LLM topic candidate {index} has invalid text fields: {', '.join(invalid_text)}"
        missing = [field for field in DECISION_CANDIDATE_REQUIRED_FIELDS if not _has_semantic_value(candidate.get(field))]
        if missing:
            return f"Growth LLM topic candidate {index} missing required semantic fields: {', '.join(missing)}"
        if not isinstance(candidate.get("source_refs"), list):
            return f"Growth LLM topic candidate {index} source_refs must be a list"
        if any(not isinstance(item, str) or not item.strip() for item in candidate["source_refs"]):
            return f"Growth LLM topic candidate {index} source_refs must contain non-empty strings"
    return ""


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
