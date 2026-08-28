from __future__ import annotations

import json
import os
from typing import Any

from . import deconstruction_artifact
from .adapters import ActivityAdapter, BusinessAdapter, CreationInspirationAdapter, ViralContentAdapter
from .deconstruction_artifact import DeconstructionArtifactUnavailable, attach_deconstruction_artifact_brief
from .field_contract import CanonicalMediaRecord, normalize_key
from .insight_cards import load_approved_human_insight_aggregation_records, load_insight_card_records
from .llm_generator import creation_candidate_context_limits, generate_creation_draft, normalize_comment_evidence_for_prompt
from .matcher import RankedRecord, content_type_allowed, rank_activities, rank_businesses, rank_inspirations, rank_virals, request_has_business_context
from .media_model_v2_writeback import write_creation_model_v2
from .platform_fit import (
    SemanticPersistenceRequiredError,
    fallback_platform_mechanism_fit,
    generate_platform_mechanism_fit,
)
from .platform_validator import validate_platform_draft
from .request_inference import parse_creation_request_with_llm
from .request_parser import CreationRequest, parse_creation_request
from .retrieval import load_business_rows_for_creation, load_inspiration_rows_for_creation, load_rows_for_creation, read_reference_docs
from .schema import ensure_creation_source_schema
from .writer import create_creation_doc
from selfmedia.context import build_media_context_for_request, merge_conversation_context, record_creation_memory
from media_vault import MediaVault, require_tenant_id
from selfmedia.deconstruct.viral_content.src.human_insight_writeback import project_id_for_human_insight_scope


def smoke_creation_command(
    raw_text: str,
    *,
    tenant_id: str,
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = parse_creation_request(raw_text)
    media_context = merge_conversation_context(build_media_context_for_request(request, tenant_id=tenant_id), conversation_context)
    loaded = media_context.get("loaded") if isinstance(media_context.get("loaded"), dict) else {}
    return {
        "ok": True,
        "mode": "smoke",
        "module": "selfmedia.creation.workflow",
        "request": request.to_dict(),
        "media_context_loaded": {
            "account_profile": bool(loaded.get("account_profile")),
            "creator_profile": bool(loaded.get("creator_profile")),
            "recent_creations": int(loaded.get("recent_creations") or 0),
            "recent_reviews": int(loaded.get("recent_reviews") or 0),
        },
        "write_policy": "no_feishu_write_no_llm_generation",
    }


def handle_creation_command(
    raw_text: str,
    *,
    tenant_id: str,
    dry_run: bool = False,
    no_write: bool = False,
    viral_url: str = "",
    activity_url: str = "",
    creation_record_url: str = "",
    business_url: str = "",
    inspiration_url: str = "",
    limit: int = 300,
    ensure_schema: bool = False,
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id)
    request = parse_creation_request_with_llm(raw_text)
    media_context = merge_conversation_context(build_media_context_for_request(request, tenant_id=tenant_id), conversation_context)
    schema_result = ensure_creation_source_schema(viral_url=viral_url, activity_url=activity_url, business_url=business_url) if ensure_schema else {}

    viral_rows, activity_rows = load_rows_for_creation(tenant_id=tenant_id, viral_url=viral_url, activity_url=activity_url, limit=limit)
    business_rows = load_business_rows_for_creation(tenant_id=tenant_id, business_url=business_url, limit=limit) if request_has_business_context(request) else []
    inspiration_rows = load_inspiration_rows_for_creation(tenant_id=tenant_id, inspiration_url=inspiration_url, limit=limit)
    activities = [ActivityAdapter().to_record(row) for row in activity_rows]
    virals = [ViralContentAdapter().to_record(row) for row in viral_rows]
    businesses = [BusinessAdapter().to_record(row) for row in business_rows]
    inspirations = [CreationInspirationAdapter().to_record(row) for row in inspiration_rows]
    inspirations.extend(load_insight_card_records(limit=_env_int("SELFMEDIA_CREATION_INSIGHT_CARD_CONTEXT_LIMIT", 30)))
    insight_project_id = project_id_for_human_insight_scope(
        project_id=request.project,
        account=request.account,
        platform=request.platform,
    )
    if request.source_asset_id and insight_project_id:
        inspirations.extend(
            load_approved_human_insight_aggregation_records(
                vault=MediaVault(tenant_id=tenant_id),
                project_id=insight_project_id,
                source_asset_id=request.source_asset_id,
                limit=_env_int("SELFMEDIA_CREATION_INSIGHT_AGGREGATION_CONTEXT_LIMIT", 30),
            )
        )
    candidate_context_limits = creation_candidate_context_limits()

    ranked_activity_candidates = rank_activities(activities, request)[: candidate_context_limits["activity"]]
    activity_candidates = [item.record for item in ranked_activity_candidates]
    activity_example_virals, activity_example_deconstructs = _deconstruct_activity_example_links(
        ranked_activity_candidates,
        tenant_id=tenant_id,
        existing_virals=virals,
        enabled=not dry_run and not no_write,
        max_items=_env_int("SELFMEDIA_CREATION_ACTIVITY_EXAMPLE_DECONSTRUCT_LIMIT", 2),
    )
    viral_context_limit = candidate_context_limits["viral"]
    viral_context_limit = candidate_context_limits["viral"]
    ranked_viral_candidates = rank_virals(virals, request)[:viral_context_limit]
    if activity_example_virals:
        ranked_example_virals = rank_virals(activity_example_virals, request)
        ranked_viral_candidates = _merge_ranked_records(ranked_example_virals, ranked_viral_candidates)[:viral_context_limit]
    if request.source_asset_id:
        ranked_viral_candidates = _merge_ranked_records(
            _explicit_source_asset_virals(virals, request.source_asset_id),
            ranked_viral_candidates,
        )[:viral_context_limit]
    ranked_viral_candidates, viral_artifact_rejections = _require_deconstruction_artifacts(
        ranked_viral_candidates,
        tenant_id=tenant_id,
        request=request,
    )
    viral_candidates = [item.record for item in ranked_viral_candidates]
    ranked_inspiration_candidates = rank_inspirations(inspirations, request)[: candidate_context_limits["inspiration"]]
    inspiration_candidates = [item.record for item in ranked_inspiration_candidates]
    business_candidates = _constraint_business_candidates(businesses, request, max_items=candidate_context_limits["business"])
    activity_payloads = [_ranked_candidate_payload(item) for item in ranked_activity_candidates]
    viral_payloads = [_ranked_candidate_payload(item) for item in ranked_viral_candidates]
    inspiration_payloads = [_ranked_candidate_payload(item) for item in ranked_inspiration_candidates]
    business_payloads = [_record_candidate_payload(item) for item in business_candidates]
    ranked_business_candidates = rank_businesses(business_candidates, request)

    reference_docs = [] if dry_run else read_reference_docs(
        _reference_doc_urls_from_records(
            [*viral_candidates, *inspiration_candidates],
            max_items=_env_int("SELFMEDIA_CREATION_REFERENCE_DOC_LIMIT", 10),
        )
    )
    try:
        platform_fit = generate_platform_mechanism_fit(
            request,
            activity_candidates=activity_payloads,
            viral_candidates=viral_payloads,
            inspiration_candidates=inspiration_payloads,
            business_candidates=business_payloads,
            reference_docs=reference_docs,
            media_context=media_context,
        )
    except SemanticPersistenceRequiredError as exc:
        platform_fit = fallback_platform_mechanism_fit(
            request,
            failure_reason=str(exc),
            activity_candidates=activity_payloads,
            viral_candidates=viral_payloads,
            inspiration_candidates=inspiration_payloads,
            business_candidates=business_payloads,
            reference_docs=reference_docs,
            media_context=media_context,
        )
    draft = generate_creation_draft(
        request,
        activity_candidates=activity_payloads,
        viral_candidates=viral_payloads,
        inspiration_candidates=inspiration_payloads,
        business_candidates=business_payloads,
        reference_docs=reference_docs,
        media_context=media_context,
        platform_fit=platform_fit,
        candidate_context_limits=candidate_context_limits,
    )
    if not draft.get("script_options") or not draft.get("recommended_option_id"):
        raise RuntimeError("missing_script_options_or_recommendation")

    candidate_assessments = draft.get("candidate_match_assessments") if isinstance(draft.get("candidate_match_assessments"), dict) else {}
    ranked_activities = _selected_from_ranked(ranked_activity_candidates, draft.get("selected_activity_ids"), "LLM选择活动")
    ranked_virals = _selected_from_ranked(
        ranked_viral_candidates,
        draft.get("selected_viral_ids"),
        "LLM选择爆款",
        assessment_lookup=_assessment_lookup(candidate_assessments.get("viral")),
    )
    ranked_inspirations = _selected_from_ranked(
        ranked_inspiration_candidates,
        draft.get("selected_inspiration_ids"),
        "LLM选择创作灵感",
        assessment_lookup=_assessment_lookup(candidate_assessments.get("inspiration")),
    )
    ranked_businesses = _selected_ranked(business_candidates, draft.get("selected_business_ids"), "LLM选择商务")

    validation_result = validate_platform_draft(request.platform, request.content_type, draft)
    validation = _validation_payload(draft, validation_result)
    doc_link = ""
    creation_record_id = ""
    memory_result: dict[str, Any] = {}
    media_model_v2_result: dict[str, Any] = {}
    if not dry_run and not no_write:
        doc_link = create_creation_doc(
            request,
            ranked_activities,
            ranked_virals,
            draft,
            validation,
            businesses=ranked_businesses,
            inspirations=ranked_inspirations,
            platform_fit=platform_fit,
        )
        media_model_v2_result = write_creation_model_v2(
            tenant_id=tenant_id,
            request=request,
            entrypoint=f"【创作>{request.platform}】" if request.platform in {"小红书", "抖音"} else "【创作】",
            all_activity_candidates=ranked_activity_candidates,
            all_viral_candidates=ranked_viral_candidates,
            all_inspiration_candidates=ranked_inspiration_candidates,
            all_business_candidates=ranked_business_candidates,
            selected_activities=ranked_activities,
            selected_virals=ranked_virals,
            selected_inspirations=ranked_inspirations,
            selected_businesses=ranked_businesses,
            doc_link=doc_link,
            creation_record_id=creation_record_id,
            draft=draft,
            validation=validation,
            media_context=media_context,
            platform_fit=platform_fit,
        )
        creation_record_id = str(media_model_v2_result.get("run_id") or "")
        memory_result = record_creation_memory(
            request,
            tenant_id=tenant_id,
            draft=draft,
            analysis=draft.get("positioning_analysis") or {},
            context=media_context,
            doc_link=doc_link,
            creation_record_id=creation_record_id,
            validation=validation,
        )
    return {
        "ok": validation_result.ok,
        "mode": "dry_run" if dry_run or no_write else "write",
        "generation_mode": "openclaw_llm_first",
        "request": request.to_dict(),
        "schema": schema_result,
        "candidate_counts": {
            "activities": len(activity_candidates),
            "virals": len(viral_candidates),
            "inspirations": len(inspiration_candidates),
            "businesses": len(business_candidates),
        },
        "activities": [_ranked_public(item) for item in ranked_activities],
        "virals": [_ranked_public(item) for item in ranked_virals],
        "inspirations": [_ranked_public(item) for item in ranked_inspirations],
        "businesses": [_ranked_public(item) for item in ranked_businesses],
        "reference_docs": reference_docs,
        "platform_fit": platform_fit,
        "media_context": media_context,
        "activity_example_deconstructs": activity_example_deconstructs,
        "viral_artifact_rejections": viral_artifact_rejections,
        "script_options": draft.get("script_options") or [],
        "recommended_option_id": draft.get("recommended_option_id") or "",
        "memory": memory_result,
        "draft": draft,
        "validation": validation,
        "doc_link": doc_link,
        "creation_record_id": creation_record_id,
        "media_model_v2": media_model_v2_result,
        "reply": format_creation_reply(
            request,
            ranked_activities,
            ranked_virals,
            ranked_inspirations,
            ranked_businesses,
            doc_link,
            validation,
            media_context=media_context,
            memory=memory_result,
            creation_record_id=creation_record_id,
            dry_run=dry_run or no_write,
            candidate_counts={"activities": len(activity_candidates), "virals": len(viral_candidates), "inspirations": len(inspiration_candidates), "businesses": len(business_candidates)},
            platform_fit=platform_fit,
            generation=draft.get("_generation") if isinstance(draft.get("_generation"), dict) else {},
        ),
    }


def format_creation_reply(
    request: CreationRequest,
    activities: list[RankedRecord],
    virals: list[RankedRecord],
    inspirations: list[RankedRecord],
    businesses: list[RankedRecord],
    doc_link: str,
    validation: dict[str, Any],
    *,
    media_context: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    creation_record_id: str = "",
    dry_run: bool = False,
    candidate_counts: dict[str, int] | None = None,
    platform_fit: dict[str, Any] | None = None,
    generation: dict[str, Any] | None = None,
) -> str:
    creator_profile_unavailable = bool((media_context or {}).get("creator_profile_error"))
    # The optional inputs remain part of the callable contract, but are
    # operational telemetry and must not be sent in a creator-facing receipt.
    del activities, virals, inspirations, businesses, media_context, memory
    del candidate_counts, platform_fit, generation
    lines = [
        "【创作】草稿已就绪" if not dry_run else "【创作】预览已就绪",
        *( [f"创作文档：{doc_link}"] if doc_link else [] ),
        f"平台：{request.platform}",
        f"内容类型：{request.content_type}",
        f"赛道：{request.track}",
        f"主体：{request.topic}",
        f"平台规则校验：{'通过' if validation.get('ok') else '未通过'}",
    ]
    if creation_record_id:
        lines.append("创作档案已关联，可在发布后发起数据复盘。")
    if creator_profile_unavailable:
        lines.append("达人档案暂未加载，不影响当前草稿。")
    return "\n".join(lines)


def _constraint_business_candidates(
    records: list[CanonicalMediaRecord],
    request: CreationRequest,
    *,
    max_items: int,
) -> list[CanonicalMediaRecord]:
    if not records or max_items <= 0:
        return []
    if not request_has_business_context(request):
        return []

    constrained: list[CanonicalMediaRecord] = []
    for record in records:
        if record.platform and request.platform and normalize_key(record.platform) != normalize_key(request.platform):
            continue
        if record.content_type_requirement:
            if not content_type_allowed(request.content_type, record.content_type_requirement):
                continue
        constrained.append(record)
    return constrained[:max_items]


def _require_deconstruction_artifacts(
    ranked: list[RankedRecord],
    *,
    tenant_id: str,
    request: CreationRequest,
) -> tuple[list[RankedRecord], list[dict[str, Any]]]:
    accepted: list[RankedRecord] = []
    rejected: list[dict[str, Any]] = []
    for item in ranked:
        try:
            evidence_uri = str((item.record.detail_json or {}).get("evidence_uri") or item.record.doc_links.get("evidence") or "").strip()
            artifact = deconstruction_artifact.load_deconstruction_artifact(evidence_uri, tenant_id=tenant_id)
            evidence_uri = str((item.record.detail_json or {}).get("evidence_uri") or item.record.doc_links.get("evidence") or "").strip()
            artifact = deconstruction_artifact.load_deconstruction_artifact(evidence_uri, tenant_id=tenant_id)
            source_asset_id = str((item.record.detail_json or {}).get("source_asset_id") or "").strip()
            materialize_deferred_contract = bool(
                request.source_asset_id
                and request.source_asset_id in {*_record_keys(item.record), source_asset_id}
            )
            record = attach_deconstruction_artifact_brief(
                item.record,
                tenant_id=tenant_id,
                require_creative_handoff=materialize_deferred_contract,
                creative_handoff_text=request.raw_text,
                materialize_deferred_contract=materialize_deferred_contract,
            )
            if "comments" in artifact:
                record.detail_json["comment_evidence"] = normalize_comment_evidence_for_prompt(artifact.get("comments"))
            if "comments" in artifact:
                record.detail_json["comment_evidence"] = normalize_comment_evidence_for_prompt(artifact.get("comments"))
        except DeconstructionArtifactUnavailable as exc:
            rejected.append(
                {
                    "id": _primary_record_id(item.record),
                    "relation_id": item.record.relation_id,
                    "reason": str(exc),
                    "evidence_uri": (item.record.detail_json or {}).get("evidence_uri") or item.record.doc_links.get("evidence", ""),
                }
            )
            continue
        if not materialize_deferred_contract:
            # Ranking may retain a legacy deconstruction for selection continuity.
            # The separately classified comment evidence remains traceable and
            # explicitly untrusted; all other uncontracted material stays out.
            # Ranking may retain a legacy deconstruction for selection continuity.
            # The separately classified comment evidence remains traceable and
            # explicitly untrusted; all other uncontracted material stays out.
            record.detail_json["creation_handoff"] = {"status": "not_requested"}
        accepted.append(
            RankedRecord(
                record=record,
                score=item.score,
                reasons=item.reasons,
                raw_score=item.raw_score,
                score_scale=item.score_scale,
            )
        )
    return accepted, rejected


def _record_candidate_payload(record: CanonicalMediaRecord) -> dict[str, Any]:
    creation_handoff = (record.detail_json or {}).get("creation_handoff")
    contract = creation_handoff.get("multi_signal_contract") if isinstance(creation_handoff, dict) else None
    if record.record_type == "素材拆解" and isinstance(creation_handoff, dict):
        if isinstance(contract, dict):
            payload = {
            payload = {
                "id": _primary_record_id(record),
                "source_record_id": record.source_record_id,
                "relation_id": record.relation_id,
                "source_table": record.source_table,
                "record_type": record.record_type,
                "multi_signal_contract": contract,
            }
        else:
            payload = {
                "id": _primary_record_id(record),
                "source_record_id": record.source_record_id,
                "relation_id": record.relation_id,
                "source_table": record.source_table,
                "record_type": record.record_type,
            }
        if "comment_evidence" in (record.detail_json or {}):
            payload["comment_evidence"] = normalize_comment_evidence_for_prompt((record.detail_json or {}).get("comment_evidence"))
        return payload
    payload = {
        "id": _primary_record_id(record),
        "source_record_id": record.source_record_id,
        "relation_id": record.relation_id,
        "source_table": record.source_table,
        "record_type": record.record_type,
        "title": record.title,
        "content": _truncate(record.content, 700),
        "status": record.status,
        "platform": record.platform,
        "content_type": record.content_type,
        "content_type_requirement": record.content_type_requirement,
        "track": record.track,
        "topic": record.topic,
        "tags": record.tags[:20],
        "audience": record.audience,
        "pain_points": record.pain_points,
        "core_value": record.core_value,
        "publish_time": record.publish_time,
        "start_time": record.start_time,
        "end_time": record.end_time,
        "deadline": record.deadline,
        "boost_date": record.boost_date,
        "source_link": record.source_link,
        "doc_links": record.doc_links,
        "metrics": _truncate_nested(record.metrics),
        "activity_level": record.activity_level,
        "activity_reward": record.activity_reward,
        "participation_requirement": record.participation_requirement,
        "direction": _truncate(record.direction, 700),
        "activity_brief": _truncate(record.activity_brief, 700),
        "activity_guidance": _truncate(record.activity_guidance, 700),
        "participation_method": record.participation_method,
        "participation_form": record.participation_form,
        "submission_requirement": _truncate(record.submission_requirement, 700),
        "brief_link": record.brief_link,
        "viral_example_link": record.viral_example_link,
        "submission_link": record.submission_link,
        "activity_doc_link": record.activity_doc_link,
        "cover_opening_hook": _truncate(str((record.detail_json or {}).get("cover_opening_hook") or ""), 420),
        "core_data_summary": _truncate(str((record.detail_json or {}).get("core_data_summary") or ""), 420),
        "top_comment_insight": _truncate(str((record.detail_json or {}).get("top_comment_insight") or ""), 900),
        "target_audience": _truncate(str((record.detail_json or {}).get("target_audience") or ""), 420),
        "pain_or_pleasure_points": _truncate(str((record.detail_json or {}).get("pain_or_pleasure_points") or ""), 420),
        "attention_elements": _truncate(str((record.detail_json or {}).get("attention_elements") or ""), 420),
        "viral_mechanism": _truncate(str((record.detail_json or {}).get("viral_mechanism") or ""), 520),
        "viral_migration": _truncate(str((record.detail_json or {}).get("viral_migration") or ""), 520),
        "creative_upgrade_suggestion": _truncate(str((record.detail_json or {}).get("creative_upgrade_suggestion") or ""), 520),
        "usable_material_brief": _truncate_nested((record.detail_json or {}).get("usable_material_brief") or {}, 900),
        "reference_shots": _truncate_nested((record.detail_json or {}).get("reference_shots") or [], 1200),
        "reference_production_summary": _truncate_nested((record.detail_json or {}).get("reference_production_summary") or {}, 500),
        "reuse_guardrails": _truncate_nested((record.detail_json or {}).get("reuse_guardrails") or {}, 900),
        "viral_reuse_assessment": _truncate_nested((record.detail_json or {}).get("viral_reuse_assessment") or {}, 700),
        "pacing_notes": _truncate_nested((record.detail_json or {}).get("pacing_notes") or {}, 500),
        "detail_json": _truncate_nested(record.detail_json),
    }
    if "comment_evidence" in (record.detail_json or {}):
        payload["comment_evidence"] = normalize_comment_evidence_for_prompt((record.detail_json or {}).get("comment_evidence"))
    return payload


def _deconstruct_activity_example_links(
    ranked_activities: list[RankedRecord],
    *,
    tenant_id: str,
    existing_virals: list[CanonicalMediaRecord] | None = None,
    enabled: bool,
    max_items: int,
) -> tuple[list[CanonicalMediaRecord], list[dict[str, Any]]]:
    if not enabled or max_items <= 0:
        return [], []
    records: list[CanonicalMediaRecord] = []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    existing_by_link = {
        record.source_link: record
        for record in (existing_virals or [])
        if record.source_link
    }
    for item in ranked_activities:
        link = item.record.viral_example_link or item.record.doc_links.get("viral_example", "")
        if not link or link in seen:
            continue
        seen.add(link)
        if len(seen) > max_items:
            break
        if link in existing_by_link:
            existing = existing_by_link[link]
            records.append(existing)
            results.append(
                {
                    "ok": True,
                    "link": link,
                    "record_id": existing.source_record_id,
                    "status": "already_indexed",
                    "deconstruct_doc_url": existing.doc_links.get("decomposition", ""),
                }
            )
            continue
        result = _run_viral_deconstruct(link, tenant_id=tenant_id)
        record = result.pop("record", None)
        results.append(result)
        if result.get("ok") and isinstance(record, CanonicalMediaRecord):
            records.append(record)
    return records, results


def _run_viral_deconstruct(link: str, *, tenant_id: str) -> dict[str, Any]:
    from selfmedia.deconstruct.viral_content.src.runner import run_workflow

    payload = run_workflow(
        f"【拆解】 {link}",
        tenant_id=require_tenant_id(tenant_id),
        write_feishu=True,
    )
    deconstruct = payload.get("deconstruct") if isinstance(payload, dict) else {}
    if not isinstance(deconstruct, dict):
        return {"ok": False, "link": link, "reason": "deconstruct_missing_payload"}
    record_id = str(payload.get("feishu_record_id") or "").strip()
    doc_url = str(deconstruct.get("deconstruct_doc_url") or "").strip()
    title = str(deconstruct.get("deconstruct_doc_title") or deconstruct.get("title") or deconstruct.get("theme") or link).strip()
    record = CanonicalMediaRecord(
        source_table="02B_MaterialDeconstructions_素材拆解",
        source_record_id=record_id or link,
        record_type="素材拆解",
        title=title,
        content=_truncate(deconstruct.get("summary") or deconstruct.get("viral_mechanism") or "", 700),
        platform=str(deconstruct.get("platform") or ""),
        content_type=str(deconstruct.get("media_type") or ""),
        source_link=link,
        doc_links={"decomposition": doc_url} if doc_url else {},
        metrics={"source": "activity_viral_example_deconstruct"},
        detail_json={"activity_viral_example": True},
    )
    return {"ok": True, "link": link, "record_id": record.source_record_id, "deconstruct_doc_url": doc_url, "record": record}


def _ranked_candidate_payload(item: RankedRecord) -> dict[str, Any]:
    payload = _record_candidate_payload(item.record)
    if item.record.record_type == "素材拆解" and isinstance((item.record.detail_json or {}).get("creation_handoff"), dict):
        return payload
    payload["score"] = item.score
    payload["reasons"] = item.reasons
    payload["score_scale"] = item.score_scale
    if item.raw_score is not None:
        payload["raw_score"] = item.raw_score
    return payload


def _selected_from_ranked(
    records: list[RankedRecord],
    selected_ids: Any,
    reason: str,
    *,
    assessment_lookup: dict[str, dict[str, Any]] | None = None,
) -> list[RankedRecord]:
    selected = _as_list(selected_ids)
    if not selected:
        return []
    assessment_lookup = assessment_lookup or {}
    lookup: dict[str, RankedRecord] = {}
    for item in records:
        for key in _record_keys(item.record):
            lookup[key] = item
    result: list[RankedRecord] = []
    seen: set[str] = set()
    for selected_id in selected:
        ranked = lookup.get(selected_id)
        if not ranked:
            continue
        primary = _primary_record_id(ranked.record)
        if primary in seen:
            continue
        seen.add(primary)
        assessment = _lookup_assessment(assessment_lookup, ranked.record, selected_id)
        score = _assessment_score(assessment, ranked.score)
        reasons = {**ranked.reasons}
        if assessment:
            breakdown = assessment.get("score_breakdown")
            if isinstance(breakdown, dict):
                reasons["LLM语义分项"] = breakdown
            selection_reason = str(assessment.get("selection_reason") or "").strip()
            if selection_reason:
                reasons["LLM选择原因"] = selection_reason
        else:
            reasons["LLM选择原因"] = reason
        result.append(
            RankedRecord(
                record=ranked.record,
                score=score,
                reasons=reasons,
                raw_score=ranked.raw_score,
                score_scale=ranked.score_scale,
            )
        )
    return result


def _selected_ranked(records: list[CanonicalMediaRecord], selected_ids: Any, reason: str) -> list[RankedRecord]:
    selected = _as_list(selected_ids)
    if not selected:
        return []
    lookup: dict[str, CanonicalMediaRecord] = {}
    for record in records:
        for key in _record_keys(record):
            lookup[key] = record
    result: list[RankedRecord] = []
    seen: set[str] = set()
    for item in selected:
        record = lookup.get(item)
        if not record:
            continue
        primary = _primary_record_id(record)
        if primary in seen:
            continue
        seen.add(primary)
        result.append(RankedRecord(record=record, score=100, reasons={reason: 100}))
    return result


def _record_keys(record: CanonicalMediaRecord) -> set[str]:
    return {item for item in (record.source_record_id, record.relation_id, _primary_record_id(record)) if item}


def _explicit_source_asset_virals(records: list[CanonicalMediaRecord], source_asset_id: str) -> list[RankedRecord]:
    target = str(source_asset_id or "").strip()
    if not target:
        return []
    return [
        RankedRecord(record=record, score=100, reasons={"显式创作交接": 100})
        for record in records
        if target in {*_record_keys(record), str((record.detail_json or {}).get("source_asset_id") or "").strip()}
    ]


def _merge_ranked_records(*groups: list[RankedRecord]) -> list[RankedRecord]:
    merged: list[RankedRecord] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            primary = _primary_record_id(item.record)
            if primary in seen:
                continue
            seen.add(primary)
            merged.append(item)
    return sorted(merged, key=lambda item: item.score, reverse=True)


def _assessment_lookup(value: Any) -> dict[str, dict[str, Any]]:
    items = value if isinstance(value, list) else []
    lookup: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "").strip()
        if item_id:
            lookup[item_id] = raw
    return lookup


def _lookup_assessment(lookup: dict[str, dict[str, Any]], record: CanonicalMediaRecord, selected_id: str) -> dict[str, Any]:
    for key in (selected_id, record.source_record_id, record.relation_id, _primary_record_id(record)):
        if key and key in lookup:
            return lookup[key]
    return {}


def _assessment_score(assessment: dict[str, Any], default: int) -> int:
    if not assessment:
        return default
    try:
        score = int(assessment.get("score"))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, score))


def _primary_record_id(record: CanonicalMediaRecord) -> str:
    return record.source_record_id or record.relation_id or f"{record.source_table}:{record.title or record.topic}"


def _reference_doc_urls_from_records(records: list[CanonicalMediaRecord], *, max_items: int) -> list[str]:
    urls: list[str] = []
    for record in records:
        if record.record_type == "素材拆解" and isinstance((record.detail_json or {}).get("creation_handoff"), dict):
            continue
        for url in record.doc_links.values():
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= max_items:
                return urls
    return urls


def _validation_payload(draft: dict[str, Any], validation_result: Any) -> dict[str, Any]:
    return {
        **validation_result.to_dict(),
        "title_ok": not any(issue.field == "title" for issue in validation_result.issues),
        "tags_ok": not any(issue.field == "tags" for issue in validation_result.issues),
        "title": draft.get("title", ""),
        "tag_count": len(draft.get("tags") or []),
        "generation_mode": "openclaw_llm_first",
        "fallback": "disabled",
    }


def _ranked_public(item: RankedRecord) -> dict[str, Any]:
    record = item.record
    return {
        "source_table": record.source_table,
        "source_record_id": record.source_record_id,
        "relation_id": record.relation_id,
        "title": record.title,
        "platform": record.platform,
        "track": record.track,
        "topic": record.topic,
        "score": item.score,
        "reasons": item.reasons,
        "raw_score": item.raw_score,
        "score_scale": item.score_scale,
        "doc_links": record.doc_links,
        "source_link": record.source_link,
        "submission_link": record.submission_link,
        "activity_doc_link": record.activity_doc_link,
        "brief_link": record.brief_link,
        "viral_example_link": record.viral_example_link,
    }


def _truncate(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= max_chars else text[: max_chars - 12].rstrip() + "..."


def _truncate_nested(value: Any, max_chars: int = 900) -> Any:
    if isinstance(value, dict):
        return {str(key): _truncate_nested(item, max_chars=max_chars) for key, item in value.items() if item not in (None, "", [])}
    if isinstance(value, list):
        return [_truncate_nested(item, max_chars=max_chars) for item in value[:20]]
    if isinstance(value, str):
        return _truncate(value, max_chars)
    return value


def _as_list(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
