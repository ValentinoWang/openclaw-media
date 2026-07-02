from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from common.social_runtime import load_default_env_files
from integrations.feishu.media_writer import upsert_entity_record
from media_model.payloads import (
    build_creation_run_payload,
    build_decision_trace_payloads,
    build_material_usage_payloads,
)
from media_vault.vault import MediaVault, make_timestamp_id

from .matcher import RankedRecord
from .request_parser import CreationRequest


V2_TRACE_LIMIT_ENV = "SELFMEDIA_CREATION_V2_TRACE_LIMIT_PER_TYPE"


def write_creation_model_v2(
    *,
    request: CreationRequest,
    entrypoint: str,
    all_activity_candidates: list[RankedRecord],
    all_viral_candidates: list[RankedRecord],
    all_inspiration_candidates: list[RankedRecord],
    all_business_candidates: list[RankedRecord],
    selected_activities: list[RankedRecord],
    selected_virals: list[RankedRecord],
    selected_inspirations: list[RankedRecord],
    selected_businesses: list[RankedRecord],
    doc_link: str,
    creation_record_id: str,
    draft: dict[str, Any],
    validation: dict[str, Any],
    media_context: dict[str, Any] | None = None,
    platform_fit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    load_default_env_files()
    urls = _v2_urls()
    run_id = _run_id(creation_record_id)
    vault = MediaVault()
    vault.ensure_manifest()
    retrieval_candidates = {
        "activities": [_ranked_record_payload(item) for item in all_activity_candidates],
        "virals": [_ranked_record_payload(item) for item in all_viral_candidates],
        "inspirations": [_ranked_record_payload(item) for item in all_inspiration_candidates],
        "businesses": [_ranked_record_payload(item) for item in all_business_candidates],
    }
    selected_keys = {
        "activity": {_record_id(item) for item in selected_activities},
        "material": {_record_id(item) for item in [*selected_virals, *selected_inspirations]},
        "business": {_record_id(item) for item in selected_businesses},
    }
    run_artifacts = vault.write_creation_run_artifacts(
        run_id,
        request={
            "entrypoint": entrypoint,
            "creation_record_id": creation_record_id,
            "doc_link": doc_link,
            "request": request.to_dict(),
        },
        input_payload={"raw_text": request.raw_text, "media_context": media_context or {}},
        retrieval_candidates=retrieval_candidates,
        draft_output=draft,
        validation_report=validation,
    )
    evidence_uri = run_artifacts["request"]["uri"]
    retrieval_uri = run_artifacts["retrieval_candidates"]["uri"]
    decision_payloads = build_decision_trace_payloads(
        run_id=run_id,
        candidates=[
            *_decision_candidates("activity", all_activity_candidates, selected_keys["activity"], retrieval_uri),
            *_decision_candidates("material", all_viral_candidates, selected_keys["material"], retrieval_uri),
            *_decision_candidates("material", all_inspiration_candidates, selected_keys["material"], retrieval_uri),
            *_decision_candidates("business", all_business_candidates, selected_keys["business"], retrieval_uri),
        ],
        decision_version=str((platform_fit or {}).get("platform_mechanism_version") or "creation_v2"),
    )
    usage_payloads = build_material_usage_payloads(
        run_id=run_id,
        usages=[
            *_usage_candidates(selected_virals, "选题参考"),
            *_usage_candidates(selected_inspirations, "选题参考"),
        ],
    )
    if decision_payloads:
        vault.write_json_artifact(
            vault.creation_run_dir(run_id),
            "decision_trace.json",
            decision_payloads,
            owner_type="CreationRun",
            owner_id=run_id,
            artifact_type="decision_trace",
        )
    if usage_payloads:
        vault.write_json_artifact(
            vault.creation_run_dir(run_id),
            "material_usage.json",
            usage_payloads,
            owner_type="CreationRun",
            owner_id=run_id,
            artifact_type="material_usage",
        )
    creation_payload = build_creation_run_payload(
        run_id=run_id,
        entrypoint=entrypoint,
        input_summary=_input_summary(request),
        status="success" if validation.get("ok") else "failed",
        generation_source="llm",
        run_artifact_uri=evidence_uri,
        render_id="",
        render_spec_uri="",
        feishu_doc_link=doc_link,
    )
    writes: list[dict[str, Any]] = []
    writes.append(_write("CreationRun", urls["CreationRun"], creation_payload))
    for payload in decision_payloads:
        writes.append(_write("DecisionTrace", urls["DecisionTrace"], payload))
    for payload in usage_payloads:
        writes.append(_write("MaterialUsage", urls["MaterialUsage"], payload))
    report = {
        "run_id": run_id,
        "run_artifact_uri": evidence_uri,
        "retrieval_artifact_uri": retrieval_uri,
        "decision_trace_count": len(decision_payloads),
        "material_usage_count": len(usage_payloads),
        "writes": writes,
    }
    vault.write_json_artifact(
        vault.creation_run_dir(run_id),
        "writeback_report.json",
        report,
        owner_type="CreationRun",
        owner_id=run_id,
        artifact_type="writeback_report",
    )
    return report


def _v2_urls() -> dict[str, str]:
    mapping = {
        "CreationRun": "MEDIA_OS_CREATION_RUNS_URL",
        "DecisionTrace": "MEDIA_OS_DECISION_TRACE_URL",
        "MaterialUsage": "MEDIA_OS_MATERIAL_USAGE_URL",
    }
    urls = {entity: os.getenv(env_key, "").strip() for entity, env_key in mapping.items()}
    missing = [entity for entity, url in urls.items() if not url]
    if missing:
        raise RuntimeError(f"missing Media Model v2 table URLs for {missing}")
    return urls


def _run_id(creation_record_id: str) -> str:
    if creation_record_id:
        return f"run_{creation_record_id}"
    return make_timestamp_id("run", token_bytes=2)


def _input_summary(request: CreationRequest) -> str:
    return " / ".join(item for item in (request.platform, request.content_type, request.track, request.topic) if item)


def _trace_limit() -> int:
    try:
        return max(1, int(os.getenv(V2_TRACE_LIMIT_ENV, "20")))
    except ValueError:
        return 20


def _decision_candidates(candidate_type: str, items: list[RankedRecord], selected_ids: set[str], evidence_uri: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for rank, item in enumerate(items[: _trace_limit()], 1):
        candidate_id = _record_id(item)
        selected = candidate_id in selected_ids
        result.append(
            {
                "candidate_type": candidate_type,
                "candidate_id": candidate_id,
                "rank": rank,
                "score": item.score,
                "selected": selected,
                "reason_summary": _reason_summary(item),
                "rejection_reason": "" if selected else "未进入最终选择",
                "score_breakdown_uri": evidence_uri,
            }
        )
    return result


def _usage_candidates(items: list[RankedRecord], usage_type: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        result.append(
            {
                "asset_id": _record_id(item),
                "deconstruction_id": item.record.doc_links.get("decomposition") or "",
                "pattern_id": "",
                "usage_type": usage_type,
                "score": item.score,
                "selected_for_final": True,
                "performance_feedback_summary": "pending_post_review",
            }
        )
    return result


def _record_id(item: RankedRecord) -> str:
    record = item.record
    return str(record.relation_id or record.source_record_id or record.source_link or record.title or "unknown").strip()


def _ranked_record_payload(item: RankedRecord) -> dict[str, Any]:
    return {
        "record": asdict(item.record),
        "score": item.score,
        "reasons": item.reasons,
        "raw_score": item.raw_score,
        "score_scale": item.score_scale,
    }


def _reason_summary(item: RankedRecord) -> str:
    if not item.reasons:
        return f"score={item.score}"
    text = json.dumps(item.reasons, ensure_ascii=False, sort_keys=True)
    return text[:1500]


def _write(entity: str, table_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    key_fields = {
        "CreationRun": "run_id",
        "DecisionTrace": "trace_id",
        "MaterialUsage": "usage_id",
    }
    key_field = key_fields.get(entity)
    if not key_field:
        raise RuntimeError(f"missing Media Model v2 idempotency key for {entity}")
    result = upsert_entity_record(entity, table_url, payload, key_field=key_field)
    return {
        "entity": entity,
        "record_id": result.get("record_id", ""),
        "mode": result.get("mode", ""),
        "key_field": key_field,
        "key_value": str(payload.get(key_field) or ""),
        "field_count": len(result.get("fields") or {}),
    }
