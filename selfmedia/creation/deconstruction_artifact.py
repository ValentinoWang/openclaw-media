from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from selfmedia.deconstruct.viral_content.src.artifact_v2 import normalize_deconstruction_artifact_for_read

from .field_contract import CanonicalMediaRecord
from media_vault.vault import MediaVault


DECONSTRUCTION_SCHEMA_VERSION = "deconstruction.v2"
SUPPORTED_REUSE_LABELS = {"strong_reuse_candidate", "weak_reuse_candidate", "reject"}


class DeconstructionArtifactUnavailable(RuntimeError):
    pass


def attach_deconstruction_artifact_brief(record: CanonicalMediaRecord, *, tenant_id: str) -> CanonicalMediaRecord:
    evidence_uri = str((record.detail_json or {}).get("evidence_uri") or record.doc_links.get("evidence") or "").strip()
    artifact = load_deconstruction_artifact(evidence_uri, tenant_id=tenant_id)
    brief = distilled_usable_material_brief(artifact)
    enriched = deepcopy(record)
    enriched.detail_json = dict(enriched.detail_json or {})
    enriched.detail_json["deconstruction_artifact_schema"] = artifact.get("schema_version")
    enriched.detail_json["deconstruction_artifact_uri"] = evidence_uri
    enriched.detail_json["usable_material_brief"] = brief
    enriched.detail_json["reuse_guardrails"] = _guardrails_for_prompt(artifact.get("reuse_guardrails") or {})
    enriched.detail_json["viral_reuse_assessment"] = _assessment_for_prompt(artifact.get("viral_reuse_assessment") or {})
    enriched.detail_json["pacing_notes"] = _pacing_notes_for_prompt(artifact.get("pacing_profile") or {})
    enriched.detail_json["reference_shots"] = _reference_shots_for_prompt(artifact.get("reference_shots") or [])
    enriched.detail_json["reference_production_summary"] = artifact.get("reference_production_summary") or {}
    enriched.core_value = brief.get("why_it_may_work") or enriched.core_value
    return enriched


def load_deconstruction_artifact(evidence_uri: str, *, tenant_id: str) -> dict[str, Any]:
    if not evidence_uri:
        raise DeconstructionArtifactUnavailable("missing_evidence_uri")
    try:
        path = MediaVault(tenant_id=tenant_id).resolve_uri(evidence_uri, require_exists=True)
    except Exception as exc:
        raise DeconstructionArtifactUnavailable(f"invalid_evidence_uri: {evidence_uri}") from exc
    if not path.is_file() or path.stat().st_size <= 0:
        raise DeconstructionArtifactUnavailable(f"deconstruction_artifact_not_found: {evidence_uri}")
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeconstructionArtifactUnavailable(f"deconstruction_artifact_unreadable: {evidence_uri}") from exc
    normalized = normalize_deconstruction_artifact_for_read(artifact)
    validate_deconstruction_artifact(normalized)
    return normalized


def validate_deconstruction_artifact(artifact: dict[str, Any]) -> None:
    if artifact.get("schema_version") != DECONSTRUCTION_SCHEMA_VERSION:
        raise DeconstructionArtifactUnavailable("unsupported_deconstruction_schema")
    for key in ("evidence_manifest", "viral_reuse_assessment", "pacing_profile", "reuse_guardrails"):
        if artifact.get(key) in (None, "", [], {}):
            raise DeconstructionArtifactUnavailable(f"deconstruction_artifact_missing_{key}")
    final_label = str((artifact.get("viral_reuse_assessment") or {}).get("final_label") or "").strip()
    if final_label not in SUPPORTED_REUSE_LABELS:
        raise DeconstructionArtifactUnavailable("invalid_viral_reuse_final_label")
    guardrails = artifact.get("reuse_guardrails") or {}
    for key in ("allowed_reuse", "required_transformations", "prohibited_reuse", "similarity_risk", "originality_requirements"):
        if guardrails.get(key) in (None, "", [], {}):
            raise DeconstructionArtifactUnavailable(f"reuse_guardrails_missing_{key}")


def distilled_usable_material_brief(artifact: dict[str, Any]) -> dict[str, Any]:
    artifact = normalize_deconstruction_artifact_for_read(artifact)
    validate_deconstruction_artifact(artifact)
    summary = artifact.get("content_summary") or {}
    assessment = artifact.get("viral_reuse_assessment") or {}
    guardrails = artifact.get("reuse_guardrails") or {}
    pacing = artifact.get("pacing_profile") or {}
    human = artifact.get("human_readable_brief") or {}
    mechanism_strength = assessment.get("mechanism_strength") if isinstance(assessment.get("mechanism_strength"), dict) else {}
    account_fit = assessment.get("account_fit") if isinstance(assessment.get("account_fit"), dict) else {}
    llm_pacing = pacing.get("llm_interpretation") if isinstance(pacing.get("llm_interpretation"), dict) else {}
    return {
        "source_summary": summary.get("summary") or summary.get("source_summary") or "",
        "why_it_may_work": mechanism_strength.get("reason") or summary.get("viral_mechanism") or "",
        "reuse_candidate_label": assessment.get("final_label") or "reject",
        "account_fit_reason": account_fit.get("reason") or "",
        "usable_mechanisms": _items_text(guardrails.get("allowed_reuse")),
        "must_transform": _items_text(guardrails.get("required_transformations")),
        "must_not_copy": _items_text(guardrails.get("prohibited_reuse")),
        "pacing_notes": _items_text(llm_pacing.get("edit_recommendations") or llm_pacing.get("drop_points") or []),
        "reference_shot_contract": _reference_shots_for_prompt(artifact.get("reference_shots") or [])[:8],
        "reference_production_summary": artifact.get("reference_production_summary") or {},
        "recommended_script_directions": _items_text(human.get("recommended_script_directions") or human.get("usable_patterns") or []),
        "human_review_flags": ["human_review_required"] if guardrails.get("human_review_required") or assessment.get("human_review_required") else [],
    }


def _assessment_for_prompt(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_label": assessment.get("final_label") or "",
        "confidence": assessment.get("confidence"),
        "observed_virality": assessment.get("observed_virality") or {},
        "account_fit": assessment.get("account_fit") or {},
        "reuse_risk": assessment.get("reuse_risk") or {},
    }


def _guardrails_for_prompt(guardrails: dict[str, Any]) -> dict[str, Any]:
    return {
        "allowed_reuse": guardrails.get("allowed_reuse") or [],
        "required_transformations": guardrails.get("required_transformations") or [],
        "prohibited_reuse": guardrails.get("prohibited_reuse") or [],
        "similarity_risk": guardrails.get("similarity_risk") or {},
        "originality_requirements": guardrails.get("originality_requirements") or [],
    }


def _pacing_notes_for_prompt(pacing: dict[str, Any]) -> dict[str, Any]:
    llm = pacing.get("llm_interpretation") if isinstance(pacing.get("llm_interpretation"), dict) else {}
    return {
        "opening": llm.get("opening") or {},
        "drop_points": llm.get("drop_points") or [],
        "edit_recommendations": llm.get("edit_recommendations") or [],
    }


def _reference_shots_for_prompt(reference_shots: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(reference_shots, list):
        return result
    for item in reference_shots[:24]:
        if not isinstance(item, dict):
            continue
        time_range = item.get("time_range") if isinstance(item.get("time_range"), dict) else {}
        result.append(
            {
                "shot_id": item.get("shot_id") or "",
                "source_refs": item.get("source_refs") or [],
                "time_range": time_range,
                "subject": (item.get("subject") or {}).get("summary") if isinstance(item.get("subject"), dict) else item.get("subject"),
                "subject_motion": (item.get("subject_motion") or {}).get("summary") if isinstance(item.get("subject_motion"), dict) else item.get("subject_motion"),
                "scene": (item.get("scene") or {}).get("summary") if isinstance(item.get("scene"), dict) else item.get("scene"),
                "spatial_framing": (item.get("spatial_framing") or {}).get("summary") if isinstance(item.get("spatial_framing"), dict) else item.get("spatial_framing"),
                "camera": (item.get("camera") or {}).get("summary") if isinstance(item.get("camera"), dict) else item.get("camera"),
                "motion_type": item.get("motion_type") or "",
                "production_route": item.get("production_route") or "",
                "reference_keep": item.get("reference_keep") or [],
                "reference_transform": item.get("reference_transform") or [],
                "reference_avoid": item.get("reference_avoid") or [],
                "confidence": item.get("confidence"),
            }
        )
    return result


def _items_text(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                result.append(str(item.get("item") or item.get("mechanism") or item.get("source_part") or item.get("element") or item.get("reason") or item))
            else:
                result.append(str(item))
        return [item for item in result if item.strip()]
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items()]
    return [str(value)]
