from __future__ import annotations

from typing import Any


class LLMIOContractError(RuntimeError):
    pass


CREATOR_BRIEF_REPORT_MODE = "creator_brief_report_v1"

LLM_INPUT_SCHEMA = {
    "required": ["run_id", "request", "candidates", "constraints", "evidence_refs"],
    "candidate_required": ["id", "candidate_type", "evidence_uri"],
    "evidence_scheme": "media://",
}

LLM_OUTPUT_SCHEMA = {
    "required": [
        "platform",
        "content_type",
        "title",
        "tags",
        "topic",
        "script_options",
        "recommended_option_id",
        "candidate_match_assessments",
        "report_mode",
        "creator_report",
    ],
    "report_mode": CREATOR_BRIEF_REPORT_MODE,
}


def build_llm_input_payload(
    *,
    run_id: str,
    request: dict[str, Any],
    candidates: dict[str, list[dict[str, Any]]],
    constraints: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "run_id": run_id,
        "request": request,
        "candidates": candidates,
        "constraints": constraints or {},
        "evidence_refs": evidence_refs or [],
        "schema": LLM_INPUT_SCHEMA,
    }
    validate_llm_input_payload(payload)
    return payload


def validate_llm_input_payload(payload: dict[str, Any]) -> None:
    missing = [key for key in LLM_INPUT_SCHEMA["required"] if key not in payload]
    if missing:
        raise LLMIOContractError(f"LLM input missing keys: {missing}")
    if not str(payload.get("run_id") or "").startswith("run_"):
        raise LLMIOContractError("LLM input run_id must start with run_")
    candidates = payload.get("candidates")
    if not isinstance(candidates, dict):
        raise LLMIOContractError("LLM input candidates must be object")
    for group_name, rows in candidates.items():
        if not isinstance(rows, list):
            raise LLMIOContractError(f"LLM input candidate group {group_name} must be list")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise LLMIOContractError(f"LLM input candidate {group_name}[{index}] must be object")
            missing = [key for key in LLM_INPUT_SCHEMA["candidate_required"] if not row.get(key)]
            if missing:
                raise LLMIOContractError(f"LLM input candidate {group_name}[{index}] missing {missing}")
            if not str(row.get("evidence_uri") or "").startswith("media://"):
                raise LLMIOContractError(f"LLM input candidate {group_name}[{index}] evidence_uri must use media://")
    for uri in payload.get("evidence_refs") or []:
        if not str(uri).startswith("media://"):
            raise LLMIOContractError(f"LLM input evidence_ref must use media://: {uri}")


def validate_llm_output_payload(payload: dict[str, Any], request: Any, **_: Any) -> dict[str, Any]:
    missing = [key for key in LLM_OUTPUT_SCHEMA["required"] if key not in payload]
    if missing:
        raise LLMIOContractError(f"LLM output missing keys: {missing}")
    if payload.get("report_mode") != LLM_OUTPUT_SCHEMA["report_mode"]:
        raise LLMIOContractError(f"LLM output report_mode must be {LLM_OUTPUT_SCHEMA['report_mode']}")
    if str(payload.get("platform") or "").strip() != str(getattr(request, "platform", payload.get("platform")) or "").strip():
        raise LLMIOContractError("LLM output platform does not match request")
    return payload


# Platform-draft field validation (title/tags/platform-specific required
# fields) used to have a second, weaker implementation here
# (platform_validation_report: title-non-empty + tags-non-empty + a single
# xiaohongshu image_script check, no tag-count ranges, no title length cap,
# no per-platform video-element checks, unknown platforms silently passed).
# It had zero production callers (media_model/__init__.py only re-exported
# it, and the sole consumer was a test) while
# selfmedia.creation.platform_validator.validate_platform_draft is the real
# authority: 4 production call sites, 5 test files, per-platform tag-count
# ranges, title length caps, and hook/storyboard/voiceover/subtitle rules.
# Removed here (dedup audit cluster SV-09) rather than turned into a thin
# adapter, because media_model has no dependency on selfmedia anywhere in
# the codebase (selfmedia depends on media_model, never the other way) and
# importing selfmedia.creation from here would be a layering violation.
# assert_generation_write_policy below does not consume this function's
# output -- it takes a plain validation_ok bool -- so callers that need a
# platform-draft ok/issues verdict should call
# selfmedia.creation.platform_validator.validate_platform_draft directly
# and pass its .ok into assert_generation_write_policy.
