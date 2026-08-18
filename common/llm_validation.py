from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Literal, Mapping


ValidationProfile = Literal["strict_structured", "bounded_open"]
ValidationState = Literal["validated", "pending_manual"]
PayloadValidator = Callable[[dict[str, Any], Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class LLMPromptValidationBinding:
    prompt_contract_id: str
    contract_id: str
    profile: ValidationProfile


def validate_llm_prompt_validation_bindings(
    bindings: Iterable[LLMPromptValidationBinding],
) -> tuple[LLMPromptValidationBinding, ...]:
    validated = tuple(bindings)
    seen_prompt_ids: set[str] = set()
    contract_profiles: dict[str, ValidationProfile] = {}
    for binding in validated:
        prompt_contract_id = binding.prompt_contract_id.strip()
        contract_id = binding.contract_id.strip()
        if not prompt_contract_id or not contract_id:
            raise ValueError("LLM prompt validation bindings require non-empty ids")
        if binding.profile not in {"strict_structured", "bounded_open"}:
            raise ValueError(f"unsupported LLM validation binding profile: {binding.profile}")
        if prompt_contract_id in seen_prompt_ids:
            raise ValueError(f"duplicate LLM prompt validation binding: {prompt_contract_id}")
        seen_prompt_ids.add(prompt_contract_id)
        existing_profile = contract_profiles.get(contract_id)
        if existing_profile is not None and existing_profile != binding.profile:
            raise ValueError(
                f"LLM validation contract {contract_id} has conflicting binding profiles: "
                f"{existing_profile} != {binding.profile}"
            )
        contract_profiles[contract_id] = binding.profile
    return validated


LLM_PROMPT_VALIDATION_BINDINGS: tuple[LLMPromptValidationBinding, ...] = validate_llm_prompt_validation_bindings((
    LLMPromptValidationBinding("inspiration-summary", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("activity-brief-cleaning", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("document-edit-stage1-target-plan", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("document-edit-stage2-patch-plan", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("selfmedia-cognition-routing", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("selfmedia-cognition-merge", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("work-acceptance-review", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("transcription-chunk-fact-extraction", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("transcription-attachment-reduce", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("transcription-group-reduce", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("transcription-global-note", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("transcription-consistency-check", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("transcription-consistency-revision", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("transcription-schema-patch", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("commercial-delivery-draft-generation", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("social-metadata-extraction", "tag_router.content_flow.direct_json.v1", "bounded_open"),
    LLMPromptValidationBinding("wardrobe-item-ingest-runtime", "tag_router.wardrobe.output.v1", "strict_structured"),
    LLMPromptValidationBinding("wardrobe-recommendation-runtime", "tag_router.wardrobe.output.v1", "strict_structured"),
    LLMPromptValidationBinding("capability-matcher-guidance", "tag_router.capability_matcher.v3", "strict_structured"),
    LLMPromptValidationBinding("capability-matcher-continuation", "tag_router.capability_continuation.v3", "strict_structured"),
    LLMPromptValidationBinding("creation-main-editor", "selfmedia.creation.draft.v1", "strict_structured"),
    LLMPromptValidationBinding("style-polish-editor", "selfmedia.style.polish.v1", "strict_structured"),
    LLMPromptValidationBinding("shooting-execution-request-parser", "selfmedia.creation.shooting_request.v1", "strict_structured"),
    LLMPromptValidationBinding("shooting-execution-director", "selfmedia.creation.shooting_plan.v1", "strict_structured"),
    LLMPromptValidationBinding("shooting-backwash-narrative-planner", "selfmedia.creation.shooting_narrative_plan.v1", "strict_structured"),
    LLMPromptValidationBinding("shooting-backwash-narrative-plan-review", "selfmedia.creation.shooting_backwash_review.v1", "strict_structured"),
    LLMPromptValidationBinding("shooting-backwash-revision", "selfmedia.creation.shooting_plan.v1", "strict_structured"),
    LLMPromptValidationBinding("shooting-backwash-coherence-review", "selfmedia.creation.shooting_backwash_review.v1", "strict_structured"),
    LLMPromptValidationBinding("creation-consultation-advisor", "selfmedia.creation.consultation.v1", "bounded_open"),
    LLMPromptValidationBinding("data-review-analysis", "selfmedia.review.data_review.v1", "bounded_open"),
    LLMPromptValidationBinding("business-id-field-extraction", "selfmedia.business.id_extraction.v1", "strict_structured"),
    LLMPromptValidationBinding("business-id-reply", "selfmedia.business.reply.v1", "bounded_open"),
    LLMPromptValidationBinding("viral-deconstruction-main", "selfmedia.deconstruction.output.v1", "strict_structured"),
    LLMPromptValidationBinding("selfmedia-knowledge-content-flow-analysis", "selfmedia.content_flow.analysis.v1", "strict_structured"),
))


class LLMPostValidationError(ValueError):
    """Raised when parsed LLM JSON fails the declared output contract."""


class LLMPostValidationPending(LLMPostValidationError):
    """Raised when the model explicitly reports that human input is required."""


@dataclass(frozen=True)
class LLMValidationContract:
    contract_id: str
    profile: ValidationProfile
    required_fields: tuple[str, ...] = ()
    non_empty_fields: tuple[str, ...] = ()
    allowed_fields: frozenset[str] | None = None
    field_types: Mapping[str, type | tuple[type, ...]] = field(default_factory=dict)
    evidence_fields: tuple[str, ...] = ()
    status_fields: tuple[str, ...] = ("status", "runtime_status")
    pending_statuses: frozenset[str] = frozenset({"pending", "manual", "pending_manual", "needs_review", "need_review"})
    prompt_contract_ids: tuple[str, ...] = ()
    validator: PayloadValidator | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        contract_id = self.contract_id.strip()
        if not contract_id:
            raise ValueError("LLM validation contract_id must not be empty")
        if self.profile not in {"strict_structured", "bounded_open"}:
            raise ValueError(f"unsupported LLM validation profile: {self.profile}")
        if not (self.required_fields or self.non_empty_fields or self.field_types or self.evidence_fields or self.validator):
            raise ValueError(f"LLM validation contract {contract_id} has no enforceable rules")
        if len(self.prompt_contract_ids) != len(set(self.prompt_contract_ids)):
            raise ValueError(f"LLM validation contract {contract_id} has duplicate prompt contract ids")


@dataclass(frozen=True)
class LLMValidationResult:
    contract_id: str
    profile: ValidationProfile
    state: ValidationState
    payload: dict[str, Any]


_CONTRACTS: dict[str, LLMValidationContract] = {}


def register_llm_validation_contract(contract: LLMValidationContract) -> str:
    bindings = tuple(item for item in LLM_PROMPT_VALIDATION_BINDINGS if item.contract_id == contract.contract_id)
    for binding in bindings:
        if binding.profile != contract.profile:
            raise ValueError(
                f"LLM prompt validation binding profile mismatch for {binding.prompt_contract_id}: "
                f"{binding.profile} != {contract.profile}"
            )
    bound_prompt_ids = tuple(item.prompt_contract_id for item in bindings)
    if contract.prompt_contract_ids and contract.prompt_contract_ids != bound_prompt_ids:
        raise ValueError(f"LLM validation contract {contract.contract_id} prompt binding mismatch")
    if bound_prompt_ids and not contract.prompt_contract_ids:
        contract = replace(contract, prompt_contract_ids=bound_prompt_ids)
    existing = _CONTRACTS.get(contract.contract_id)
    if existing is not None and existing is not contract:
        raise ValueError(f"duplicate LLM validation contract_id: {contract.contract_id}")
    _CONTRACTS[contract.contract_id] = contract
    return contract.contract_id


def registered_llm_validation_contracts() -> tuple[LLMValidationContract, ...]:
    return tuple(_CONTRACTS[key] for key in sorted(_CONTRACTS))


def llm_prompt_validation_bindings() -> tuple[LLMPromptValidationBinding, ...]:
    return LLM_PROMPT_VALIDATION_BINDINGS


def validate_llm_payload(
    payload: dict[str, Any],
    contract_id: str,
    *,
    context: Mapping[str, Any] | None = None,
) -> LLMValidationResult:
    contract = _CONTRACTS.get(contract_id)
    if contract is None:
        raise LLMPostValidationError(f"unknown LLM validation contract: {contract_id}")
    if not isinstance(payload, dict):
        raise LLMPostValidationError(f"{contract_id}: JSON top level must be an object")

    candidate = dict(payload)
    unknown = set(candidate) - contract.allowed_fields if contract.allowed_fields is not None else set()
    if unknown:
        raise LLMPostValidationError(f"{contract_id}: unknown fields: {sorted(unknown)}")

    missing = [field_name for field_name in contract.required_fields if field_name not in candidate]
    if missing:
        raise LLMPostValidationError(f"{contract_id}: missing required fields: {missing}")
    empty = [field_name for field_name in contract.non_empty_fields if _is_missing(candidate.get(field_name))]
    if empty:
        raise LLMPostValidationError(f"{contract_id}: fields must not be empty: {empty}")

    for field_name, expected_type in contract.field_types.items():
        if field_name not in candidate:
            continue
        value = candidate[field_name]
        if isinstance(value, bool) and expected_type is int:
            valid = False
        else:
            valid = isinstance(value, expected_type)
        if not valid:
            raise LLMPostValidationError(
                f"{contract_id}: field {field_name} must be {_type_name(expected_type)}, got {type(value).__name__}"
            )

    if contract.evidence_fields and not any(not _is_missing(candidate.get(field_name)) for field_name in contract.evidence_fields):
        raise LLMPostValidationError(
            f"{contract_id}: at least one evidence field is required: {list(contract.evidence_fields)}"
        )

    if contract.validator is not None:
        try:
            candidate = contract.validator(candidate, context or {})
        except LLMPostValidationError:
            raise
        except Exception as exc:
            raise LLMPostValidationError(f"{contract_id}: {exc}") from exc
        if not isinstance(candidate, dict):
            raise LLMPostValidationError(f"{contract_id}: validator must return a JSON object")

    for status_field in contract.status_fields:
        status = str(candidate.get(status_field) or "").strip().lower()
        if status and status in contract.pending_statuses:
            reason = str(candidate.get("reason") or "human input required").strip()
            raise LLMPostValidationPending(f"{contract_id}: {reason}")

    return LLMValidationResult(
        contract_id=contract.contract_id,
        profile=contract.profile,
        state="validated",
        payload=candidate,
    )


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _type_name(expected_type: type | tuple[type, ...]) -> str:
    if isinstance(expected_type, tuple):
        return " or ".join(item.__name__ for item in expected_type)
    return expected_type.__name__
