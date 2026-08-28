from __future__ import annotations

import hashlib
import re
from typing import Any

from selfmedia.request_constraints import validate_request_constraints_payload

from .evidence.schemas import validate_evidence_store
from .human_insight_cards import HumanInsightCardError, validate_human_insight_candidate
from .multi_signal_schema import validate_multi_signal_contract_payload


DECONSTRUCTION_SCHEMA_VERSION = "deconstruction.v2"
SUPPORTED_REUSE_LABELS = {"strong_reuse_candidate", "weak_reuse_candidate", "reject"}


class DeconstructionArtifactError(ValueError):
    pass


def validate_llm_deconstruction_v2_payload(payload: dict[str, Any], evidence_store: dict[str, Any]) -> dict[str, Any]:
    if "is_viral" in payload:
        raise DeconstructionArtifactError("禁止输出 is_viral；必须输出 viral_reuse_assessment.final_label")
    for key in ("viral_reuse_assessment", "pacing_profile", "reuse_guardrails", "human_readable_brief"):
        if not isinstance(payload.get(key), dict):
            raise DeconstructionArtifactError(f"缺少 deconstruction.v2 必需对象: {key}")
    assessment = payload.get("viral_reuse_assessment") or {}
    final_label = str(assessment.get("final_label") or "").strip()
    if final_label not in SUPPORTED_REUSE_LABELS:
        raise DeconstructionArtifactError(f"viral_reuse_assessment.final_label 非法: {final_label}")
    guardrails = payload.get("reuse_guardrails") or {}
    for key in ("allowed_reuse", "required_transformations", "prohibited_reuse", "similarity_risk", "originality_requirements"):
        if guardrails.get(key) in (None, "", [], {}):
            raise DeconstructionArtifactError(f"reuse_guardrails.{key} 不能为空")
    _validate_evidence_refs(payload, set((_evidence_manifest(evidence_store) or {}).keys()))
    return payload


def merge_llm_result_with_evidence(result: dict[str, Any], evidence_store: dict[str, Any]) -> dict[str, Any]:
    facts = evidence_store.get("modality_facts") if isinstance(evidence_store.get("modality_facts"), dict) else {}
    speech_fact = _fact_payload(facts, "speech")
    ocr_fact = _fact_payload(facts, "ocr")
    pacing_fact = _fact_payload(facts, "pacing")
    keyframe_fact = _fact_payload(facts, "keyframe_observations")
    visual_fact = _fact_payload(facts, "visual_assets")
    engagement_fact = _fact_payload(facts, "engagement")
    comments_fact = _fact_payload(facts, "comments")
    speech_transcript = speech_fact.get("speech_transcript") or {}
    speech_timeline = speech_fact.get("speech_timeline") or []
    visible_text_segments = ocr_fact.get("visible_text_segments") or []
    scene_segments = pacing_fact.get("scene_segments") or []
    keyframe_observations = keyframe_fact.get("keyframe_observations") or []
    pacing_python_facts = pacing_fact.get("pacing_python_facts") or {}
    merged = dict(result)
    merged["schema_version"] = DECONSTRUCTION_SCHEMA_VERSION
    merged["evidence_manifest"] = _evidence_manifest(evidence_store)
    merged["speech_transcript"] = speech_transcript
    merged["speech_timeline"] = speech_timeline
    merged["visible_text_segments"] = visible_text_segments
    merged["scene_segments"] = scene_segments
    merged["keyframe_observations"] = keyframe_observations
    merged["visual_hook"] = visual_fact.get("visual_hook") or {}
    merged["engagement"] = engagement_fact
    merged["comments"] = comments_fact
    pacing = dict(merged.get("pacing_profile") or {})
    llm_interpretation = pacing.get("llm_interpretation")
    if not isinstance(llm_interpretation, dict):
        llm_interpretation = {key: value for key, value in pacing.items() if key != "python_facts"}
    merged["pacing_profile"] = {
        "python_facts": pacing_python_facts,
        "llm_interpretation": llm_interpretation,
    }
    validation = dict(evidence_store.get("validation") or {})
    validation["evidence_reference_status"] = "validated"
    validation["schema_version"] = DECONSTRUCTION_SCHEMA_VERSION
    validation.setdefault("warnings", _evidence_warnings(speech_transcript, visible_text_segments))
    merged["validation"] = validation
    return merged


def _evidence_manifest(evidence: dict[str, Any]) -> dict[str, Any]:
    manifest = evidence.get("evidence_manifest")
    return manifest if isinstance(manifest, dict) else {}


def _fact_payload(modality_facts: dict[str, Any], fact_type: str) -> dict[str, Any]:
    fact = modality_facts.get(fact_type) if isinstance(modality_facts, dict) else {}
    if not isinstance(fact, dict):
        return {}
    payload = fact.get("facts")
    return payload if isinstance(payload, dict) else {}


def build_deconstruction_artifact(
    *,
    result: dict[str, Any],
    deconstruction_id: str,
    source_asset_id: str,
    source_asset_evidence_uri: str,
    source_text: str,
) -> dict[str, Any]:
    if result.get("schema_version") != DECONSTRUCTION_SCHEMA_VERSION:
        raise DeconstructionArtifactError("拆解结果不是 deconstruction.v2，禁止写入 canonical artifact")
    artifact = {
        "schema_version": DECONSTRUCTION_SCHEMA_VERSION,
        "deconstruction_id": deconstruction_id,
        "source_asset_id": source_asset_id,
        "asset_id": source_asset_id,
        "created_at": _utc_now_from_vault(),
        "model_info": {
            "deconstruction_model": str(result.get("model") or ""),
            "vision_mode": str(result.get("vision_mode") or "frames_only"),
            "asr_model": str((result.get("speech_transcript") or {}).get("provider") or ""),
            "ocr_model": str(result.get("ocr_model") or "tesseract_or_unavailable"),
        },
        "evidence_manifest": result.get("evidence_manifest") or {},
        "speech_transcript": result.get("speech_transcript") or {},
        "speech_timeline": result.get("speech_timeline") or [],
        "visible_text_segments": result.get("visible_text_segments") or [],
        "scene_segments": result.get("scene_segments") or [],
        "keyframe_observations": result.get("keyframe_observations") or [],
        "visual_hook": result.get("visual_hook") or {},
        "engagement": result.get("engagement") or {},
        "comments": result.get("comments") or {},
        "asset_manifest": result.get("asset_manifest") or {},
        "modality_facts": result.get("modality_facts") or {},
        "evidence_store": result.get("evidence_store") or {},
        "multi_signal_contract": result.get("multi_signal_contract") or {},
        "request_constraints": result.get("request_constraints") or {},
        "account_context": result.get("account_context") or {},
        "ai_blend_analysis": result.get("ai_blend_analysis") or [],
        "ai_storyboard_prompt_shots": result.get("ai_storyboard_prompt_shots") or [],
        "human_insight_candidates": result.get("human_insight_candidates") or [],
        "mechanism_card_candidates": result.get("mechanism_card_candidates") or [],
        "audience_group_card_candidates": result.get("audience_group_card_candidates") or [],
        "candidate_tags": result.get("candidate_tags") or [],
        "no_human_insight_detected": bool(result.get("no_human_insight_detected") or False),
        "content_summary": {
            "summary": result.get("content_summary") or "",
            "source_summary": result.get("source_summary") or "",
            "viral_mechanism": result.get("viral_mechanism") or "",
            "hook": result.get("hook_elements") or result.get("viral_mechanism") or "",
        },
        "viral_reuse_assessment": result.get("viral_reuse_assessment") or {},
        "pacing_profile": result.get("pacing_profile") or {},
        "reuse_guardrails": result.get("reuse_guardrails") or {},
        "human_readable_brief": result.get("human_readable_brief") or {},
        "reference_shots": result.get("reference_shots") or [],
        "reference_production_summary": result.get("reference_production_summary") or {},
        "analysis_fields": {
            "cover_opening_hook": result.get("cover_opening_hook") or "",
            "core_data_summary": result.get("core_data_summary") or "",
            "top_comment_insight": result.get("top_comment_insight") or "",
            "target_audience_summary": result.get("target_audience_summary") or "",
            "pain_pleasure_summary": result.get("pain_pleasure_summary") or "",
            "attention_elements": result.get("attention_elements") or [],
            "viral_breakdown": result.get("viral_breakdown") or "",
            "viral_migration": result.get("viral_migration") or "",
            "creative_upgrade_suggestion": result.get("creative_upgrade_suggestion") or "",
        },
        "validation": {
            **(result.get("validation") or {}),
            "source_asset_evidence_uri": source_asset_evidence_uri,
            "source_text_hash": hashlib.sha256(str(source_text or "").encode("utf-8")).hexdigest(),
        },
        "source_runtime": {
            "source_url": result.get("source_url") or "",
            "platform": result.get("platform") or "",
            "source_caption": result.get("source_caption") or "",
            "stats": result.get("stats") or {},
            "video_storyboard": result.get("video_storyboard") or [],
            "image_post_script": result.get("image_post_script") or [],
            "avoid_plagiarism_notes": result.get("avoid_plagiarism_notes") or "",
            "production_checklist": result.get("production_checklist") or [],
        },
    }
    validate_deconstruction_artifact(artifact)
    return artifact


def validate_deconstruction_artifact(artifact: dict[str, Any]) -> None:
    if artifact.get("schema_version") != DECONSTRUCTION_SCHEMA_VERSION:
        raise DeconstructionArtifactError("unsupported deconstruction artifact schema_version")
    for key in ("deconstruction_id", "source_asset_id", "evidence_manifest", "viral_reuse_assessment", "pacing_profile", "reuse_guardrails"):
        if artifact.get(key) in (None, "", [], {}):
            raise DeconstructionArtifactError(f"deconstruction artifact 缺少必需字段: {key}")
    _validate_evidence_refs(artifact, set((artifact.get("evidence_manifest") or {}).keys()))
    if artifact.get("multi_signal_contract"):
        try:
            validate_multi_signal_contract_payload(
                artifact.get("multi_signal_contract") or {},
                set((artifact.get("evidence_manifest") or {}).keys()),
            )
        except ValueError as exc:
            raise DeconstructionArtifactError(f"multi_signal_contract 校验失败：{exc}") from exc
    if artifact.get("evidence_store"):
        try:
            validate_evidence_store(artifact.get("evidence_store") or {})
        except ValueError as exc:
            raise DeconstructionArtifactError(f"evidence_store 校验失败：{exc}") from exc
    _validate_request_constraints(artifact)
    _validate_ai_blend_contract(artifact)
    _validate_human_insight_candidates(artifact)


def distilled_usable_material_brief(artifact: dict[str, Any]) -> dict[str, Any]:
    validate_deconstruction_artifact(artifact)
    brief = artifact.get("human_readable_brief") or {}
    assessment = artifact.get("viral_reuse_assessment") or {}
    guardrails = artifact.get("reuse_guardrails") or {}
    pacing = artifact.get("pacing_profile") or {}
    source_summary = artifact.get("content_summary") or {}
    return {
        "source_summary": source_summary.get("summary") or source_summary.get("source_summary") or "",
        "why_it_may_work": ((assessment.get("mechanism_strength") or {}).get("reason") if isinstance(assessment.get("mechanism_strength"), dict) else "") or source_summary.get("viral_mechanism") or "",
        "reuse_candidate_label": assessment.get("final_label") or "reject",
        "account_fit_reason": ((assessment.get("account_fit") or {}).get("reason") if isinstance(assessment.get("account_fit"), dict) else ""),
        "usable_mechanisms": _items_text(guardrails.get("allowed_reuse")),
        "must_transform": _items_text(guardrails.get("required_transformations")),
        "must_not_copy": _items_text(guardrails.get("prohibited_reuse")),
        "pacing_notes": _items_text((pacing.get("llm_interpretation") or {}).get("edit_recommendations") if isinstance(pacing.get("llm_interpretation"), dict) else []),
        "recommended_script_directions": _items_text(brief.get("recommended_script_directions") or brief.get("usable_patterns") or []),
        "human_review_flags": _items_text([item for item in (artifact.get("validation") or {}).get("warnings", []) if item]),
    }


def _validate_evidence_refs(payload: Any, valid_ids: set[str]) -> None:
    if not valid_ids:
        raise DeconstructionArtifactError("缺少 evidence_manifest，无法校验证据引用")
    for path, value in _walk_refs(payload):
        refs = value if isinstance(value, list) else [value]
        for ref in refs:
            ref_text = str(ref or "").strip()
            if ref_text and ref_text not in valid_ids:
                raise DeconstructionArtifactError(f"非法 evidence 引用 {path}: {ref_text}")


def _walk_refs(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in {"evidence_ids", "evidence_asset_ids", "evidence_refs"}:
                yield child, item
            elif key in {"evidence_id", "evidence_asset_id", "source_ref", "segment_id", "text_segment_id", "asset_id", "scene_id", "observation_id"}:
                text = str(item or "").strip()
                if re.match(r"^(frame|image|sp|ocr|scene|keyobs|comment)_\d{3}$", text):
                    yield child, item
            elif key in {"source_refs", "source_frame_refs"}:
                yield child, item
            else:
                yield from _walk_refs(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_refs(item, f"{path}[{index}]")


def _validate_human_insight_candidates(artifact: dict[str, Any]) -> None:
    candidates = artifact.get("human_insight_candidates") or []
    if not isinstance(candidates, list):
        raise DeconstructionArtifactError("human_insight_candidates 必须是数组")
    for index, item in enumerate(candidates, 1):
        if not isinstance(item, dict):
            raise DeconstructionArtifactError(f"human_insight_candidates[{index}] 必须是对象")
        if not str(item.get("evidence_quote") or "").strip() and not item.get("evidence_asset_ids") and not item.get("evidence_refs"):
            raise DeconstructionArtifactError(f"human_insight_candidates[{index}] 缺少 evidence_quote/evidence_asset_ids/evidence_refs")
        for field in ("mechanism_tag", "desire_or_fear", "emotion_path", "audience_group_hypothesis", "trigger_pattern", "risk_boundary", "reasoning_summary"):
            if not str(item.get(field) or "").strip():
                raise DeconstructionArtifactError(f"human_insight_candidates[{index}] 缺少 {field}")
        confidence = item.get("confidence")
        try:
            number = float(confidence)
        except (TypeError, ValueError) as exc:
            raise DeconstructionArtifactError(f"human_insight_candidates[{index}].confidence 非法") from exc
        if not 0 <= number <= 1:
            raise DeconstructionArtifactError(f"human_insight_candidates[{index}].confidence 必须在 0..1")
        try:
            validate_human_insight_candidate(item)
        except (HumanInsightCardError, TypeError, ValueError) as exc:
            raise DeconstructionArtifactError(f"human_insight_candidates[{index}] 非法: {exc}") from exc


def _validate_request_constraints(artifact: dict[str, Any]) -> None:
    constraints = artifact.get("request_constraints")
    if not isinstance(constraints, dict) or not constraints:
        raise DeconstructionArtifactError("request_constraints 不能为空")
    try:
        artifact["request_constraints"] = validate_request_constraints_payload(constraints)
    except (TypeError, ValueError) as exc:
        raise DeconstructionArtifactError(f"request_constraints 非法: {exc}") from exc


def _validate_ai_blend_contract(artifact: dict[str, Any]) -> None:
    valid_ids = set((artifact.get("evidence_manifest") or {}).keys())
    segments = artifact.get("ai_blend_analysis") or []
    prompt_shots = artifact.get("ai_storyboard_prompt_shots") or []
    if not isinstance(segments, list):
        raise DeconstructionArtifactError("ai_blend_analysis 必须是数组")
    if not isinstance(prompt_shots, list):
        raise DeconstructionArtifactError("ai_storyboard_prompt_shots 必须是数组")
    segment_ids: set[str] = set()
    for index, item in enumerate(segments, 1):
        if not isinstance(item, dict):
            raise DeconstructionArtifactError(f"ai_blend_analysis[{index}] 必须是对象")
        segment_id = str(item.get("segment_id") or "").strip()
        segment_ids.add(segment_id)
        if str(item.get("segment_type") or "").strip() not in {"real", "ai", "hybrid", "uncertain"}:
            raise DeconstructionArtifactError(f"ai_blend_analysis[{index}].segment_type 非法")
        _validate_float_range(item.get("confidence"), f"ai_blend_analysis[{index}].confidence")
        if not str(item.get("time_range") or "").strip() or not str(item.get("reasoning_summary") or "").strip():
            raise DeconstructionArtifactError(f"ai_blend_analysis[{index}] 缺少 time_range/reasoning_summary")
        _validate_artifact_evidence_list(item.get("evidence_asset_ids"), valid_ids, f"ai_blend_analysis[{index}].evidence_asset_ids")
    for index, item in enumerate(prompt_shots, 1):
        if not isinstance(item, dict):
            raise DeconstructionArtifactError(f"ai_storyboard_prompt_shots[{index}] 必须是对象")
        for field in (
            "shot_id",
            "segment_id",
            "duration_seconds",
            "start_frame_ref",
            "end_frame_ref",
            "continuity_to_real_footage",
            "aspect_ratio",
            "target_tool",
            "prompt_language",
            "prompt",
            "negative_prompt",
        ):
            if not str(item.get(field) or "").strip():
                raise DeconstructionArtifactError(f"ai_storyboard_prompt_shots[{index}] 缺少 {field}")
        segment_id = str(item.get("segment_id") or "").strip()
        if segment_ids and segment_id not in segment_ids:
            raise DeconstructionArtifactError(f"ai_storyboard_prompt_shots[{index}].segment_id 未匹配 ai_blend_analysis")
        _validate_artifact_evidence_list(item.get("evidence_asset_ids"), valid_ids, f"ai_storyboard_prompt_shots[{index}].evidence_asset_ids")


def _validate_artifact_evidence_list(value: Any, valid_ids: set[str], path: str) -> None:
    refs = value if isinstance(value, list) else []
    if not refs:
        raise DeconstructionArtifactError(f"{path} 不能为空")
    invalid = [str(item or "").strip() for item in refs if str(item or "").strip() not in valid_ids]
    if invalid:
        raise DeconstructionArtifactError(f"{path} 非法 evidence 引用: {', '.join(invalid)}")


def _validate_float_range(value: Any, path: str) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DeconstructionArtifactError(f"{path} 非法") from exc
    if not 0 <= number <= 1:
        raise DeconstructionArtifactError(f"{path} 必须在 0..1")


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


def _evidence_warnings(speech_transcript: dict[str, Any], visible_text_segments: list[dict[str, Any]]) -> list[str]:
    warnings = []
    if speech_transcript.get("status") != "success":
        warnings.append(f"speech_status={speech_transcript.get('status') or 'unknown'}")
    if not visible_text_segments:
        warnings.append("ocr_status=no_visible_text_or_ocr_failed")
    return warnings


def _utc_now_from_vault() -> str:
    try:
        from media_vault.vault import utc_now_iso

        return utc_now_iso()
    except Exception:
        return ""
