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


def platform_validation_report(platform: str, content_type: str, draft: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if not str(draft.get("title") or "").strip():
        issues.append({"field": "title", "message": "title is required"})
    tags = draft.get("tags")
    if not isinstance(tags, list) or not tags:
        issues.append({"field": "tags", "message": "at least one tag is required"})
    if str(platform).strip() == "小红书" and str(content_type).strip() == "图文" and not draft.get("image_script"):
        issues.append({"field": "image_script", "message": "xiaohongshu image_script is required"})
    ok = not issues
    return {"ok": ok, "issues": issues, "write_policy": "final_write_allowed" if ok else "pending_manual_only"}
