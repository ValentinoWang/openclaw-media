from __future__ import annotations

import json
import os
from typing import Any

from .adapters import ActivityAdapter, BusinessAdapter, CreationInspirationAdapter, ViralContentAdapter
from .field_contract import CanonicalMediaRecord, normalize_key
from .llm_generator import generate_openclaw_creation_draft
from .matcher import RankedRecord, content_type_allowed, request_has_business_context
from .platform_fit import generate_platform_mechanism_fit
from .platform_validator import validate_platform_draft
from .request_inference import parse_creation_request_with_llm
from .request_parser import CreationRequest
from .retrieval import load_business_rows_for_creation, load_inspiration_rows_for_creation, load_rows_for_creation, read_reference_docs
from .schema import ensure_creation_source_schema
from .writer import create_creation_doc, write_creation_record
from tools.media_context import build_media_context_for_request, merge_conversation_context, record_creation_memory


def handle_creation_command(
    raw_text: str,
    *,
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
    request = parse_creation_request_with_llm(raw_text)
    media_context = merge_conversation_context(build_media_context_for_request(request), conversation_context)
    schema_result = ensure_creation_source_schema(viral_url=viral_url, activity_url=activity_url, business_url=business_url) if ensure_schema else {}

    viral_rows, activity_rows = load_rows_for_creation(viral_url=viral_url, activity_url=activity_url, limit=limit)
    business_rows = load_business_rows_for_creation(business_url=business_url, limit=limit)
    inspiration_rows = load_inspiration_rows_for_creation(inspiration_url=inspiration_url, limit=limit)
    activities = [ActivityAdapter().to_record(row) for row in activity_rows]
    virals = [ViralContentAdapter().to_record(row) for row in viral_rows]
    businesses = [BusinessAdapter().to_record(row) for row in business_rows]
    inspirations = [CreationInspirationAdapter().to_record(row) for row in inspiration_rows]

    activity_candidates = _constraint_candidates(activities, request, kind="activity", max_items=_env_int("SELFMEDIA_CREATION_ACTIVITY_CONTEXT_LIMIT", 30))
    viral_candidates = _constraint_candidates(virals, request, kind="viral", max_items=_env_int("SELFMEDIA_CREATION_VIRAL_CONTEXT_LIMIT", 40))
    inspiration_candidates = _constraint_candidates(inspirations, request, kind="inspiration", max_items=_env_int("SELFMEDIA_CREATION_INSPIRATION_CONTEXT_LIMIT", 40))
    business_candidates = _constraint_candidates(businesses, request, kind="business", max_items=_env_int("SELFMEDIA_CREATION_BUSINESS_CONTEXT_LIMIT", 20))
    activity_payloads = [_record_candidate_payload(item) for item in activity_candidates]
    viral_payloads = [_record_candidate_payload(item) for item in viral_candidates]
    inspiration_payloads = [_record_candidate_payload(item) for item in inspiration_candidates]
    business_payloads = [_record_candidate_payload(item) for item in business_candidates]

    reference_docs = [] if dry_run else read_reference_docs(
        _reference_doc_urls_from_records(
            [*viral_candidates, *inspiration_candidates],
            max_items=_env_int("SELFMEDIA_CREATION_REFERENCE_DOC_LIMIT", 10),
        )
    )
    platform_fit = generate_platform_mechanism_fit(
        request,
        activity_candidates=activity_payloads,
        viral_candidates=viral_payloads,
        inspiration_candidates=inspiration_payloads,
        business_candidates=business_payloads,
        reference_docs=reference_docs,
        media_context=media_context,
    )
    draft = generate_openclaw_creation_draft(
        request,
        activity_candidates=activity_payloads,
        viral_candidates=viral_payloads,
        inspiration_candidates=inspiration_payloads,
        business_candidates=business_payloads,
        reference_docs=reference_docs,
        media_context=media_context,
        platform_fit=platform_fit,
    )

    ranked_activities = _selected_ranked(activity_candidates, draft.get("selected_activity_ids"), "LLM选择活动")
    ranked_virals = _selected_ranked(viral_candidates, draft.get("selected_viral_ids"), "LLM选择爆款")
    ranked_inspirations = _selected_ranked(inspiration_candidates, draft.get("selected_inspiration_ids"), "LLM选择创作灵感")
    ranked_businesses = _selected_ranked(business_candidates, draft.get("selected_business_ids"), "LLM选择商务")

    validation_result = validate_platform_draft(request.platform, request.content_type, draft)
    validation = _validation_payload(draft, validation_result)
    doc_link = ""
    creation_record_id = ""
    memory_result: dict[str, Any] = {}
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
        creation_record_id = write_creation_record(
            request,
            ranked_activities,
            ranked_virals,
            doc_link,
            validation,
            businesses=ranked_businesses,
            inspirations=ranked_inspirations,
            record_table_url=creation_record_url,
            extra_details={
                "media_context": media_context,
                "topic_strategy": draft.get("topic_strategy") or {},
                "platform_fit": platform_fit,
                "platform_fit_meta": platform_fit.get("platform_fit_meta") or {},
                "platform_strategy": draft.get("platform_strategy") or {},
                "activity_strategy": draft.get("activity_strategy") or {},
                "validation_targets": draft.get("validation_targets") or {},
                "inspiration_reference": draft.get("inspiration_reference") or {},
                "positioning_analysis": draft.get("positioning_analysis") or {},
                "generation": {
                    "provider": "openclaw_llm",
                    "mode": "llm_first_no_template_fallback",
                    "candidate_counts": {
                        "activities": len(activity_candidates),
                        "virals": len(viral_candidates),
                        "inspirations": len(inspiration_candidates),
                        "businesses": len(business_candidates),
                    },
                    "selected_activity_ids": draft.get("selected_activity_ids") or [],
                    "selected_viral_ids": draft.get("selected_viral_ids") or [],
                    "selected_inspiration_ids": draft.get("selected_inspiration_ids") or [],
                    "selected_business_ids": draft.get("selected_business_ids") or [],
                },
            },
        )
        memory_result = record_creation_memory(
            request,
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
        "memory": memory_result,
        "draft": draft,
        "validation": validation,
        "doc_link": doc_link,
        "creation_record_id": creation_record_id,
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
            dry_run=dry_run or no_write,
            candidate_counts={"activities": len(activity_candidates), "virals": len(viral_candidates), "inspirations": len(inspiration_candidates), "businesses": len(business_candidates)},
            platform_fit=platform_fit,
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
    dry_run: bool = False,
    candidate_counts: dict[str, int] | None = None,
    platform_fit: dict[str, Any] | None = None,
) -> str:
    loaded = (media_context or {}).get("loaded") or {}
    profile = (media_context or {}).get("account_profile") or {}
    candidate_counts = candidate_counts or {}
    lines = [
        "【创作】已完成（OpenClaw/LLM 主导）" if not dry_run else "【创作】dry-run 已完成（OpenClaw/LLM 主导）",
        f"平台：{request.platform}",
        f"内容类型：{request.content_type}",
        f"赛道：{request.track}",
        f"主体：{request.topic}",
        f"候选记忆：活动 {candidate_counts.get('activities', 0)} 条，爆款 {candidate_counts.get('virals', 0)} 条，灵感 {candidate_counts.get('inspirations', 0)} 条，商务 {candidate_counts.get('businesses', 0)} 条",
        f"LLM选择：活动 {len(activities)} 条，爆款 {len(virals)} 条，灵感 {len(inspirations)} 条，商务 {len(businesses)} 条",
        f"上下文：账号档案 {'有' if loaded.get('account_profile') else '无'}，历史创作 {loaded.get('recent_creations', 0)} 条，历史复盘 {loaded.get('recent_reviews', 0)} 条，对话 {loaded.get('conversation_context', 0)} 条",
        f"平台机制版本：{(platform_fit or {}).get('platform_mechanism_version') or '未生成'}",
        f"平台规则校验：{'通过' if validation.get('ok') else '未通过'}",
    ]
    if doc_link:
        lines.append(f"创作文档：{doc_link}")
    if profile.get("markdown_path"):
        lines.append(f"账号 Markdown 档案：{profile['markdown_path']}")
    if memory and memory.get("profile", {}).get("markdown_path"):
        lines.append(f"账号档案已更新：{memory['profile']['markdown_path']}")
    return "\n".join(lines)


def _constraint_candidates(
    records: list[CanonicalMediaRecord],
    request: CreationRequest,
    *,
    kind: str,
    max_items: int,
) -> list[CanonicalMediaRecord]:
    if not records or max_items <= 0:
        return []
    if kind == "business" and not request_has_business_context(request):
        return []

    constrained: list[CanonicalMediaRecord] = []
    for record in records:
        if record.platform and request.platform and normalize_key(record.platform) != normalize_key(request.platform):
            continue
        if kind == "viral" and record.content_type and normalize_key(record.content_type) != normalize_key(request.content_type):
            continue
        if kind in {"activity", "business"} and record.content_type_requirement:
            if not content_type_allowed(request.content_type, record.content_type_requirement):
                continue
        constrained.append(record)
    return (constrained or records)[:max_items]


def _record_candidate_payload(record: CanonicalMediaRecord) -> dict[str, Any]:
    return {
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
        "source_link": record.source_link,
        "doc_links": record.doc_links,
        "metrics": _truncate_nested(record.metrics),
        "activity_level": record.activity_level,
        "activity_reward": record.activity_reward,
        "participation_requirement": record.participation_requirement,
        "direction": _truncate(record.direction, 700),
        "detail_json": _truncate_nested(record.detail_json),
    }


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


def _primary_record_id(record: CanonicalMediaRecord) -> str:
    return record.source_record_id or record.relation_id or f"{record.source_table}:{record.title or record.topic}"


def _reference_doc_urls_from_records(records: list[CanonicalMediaRecord], *, max_items: int) -> list[str]:
    urls: list[str] = []
    for record in records:
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
        "doc_links": record.doc_links,
        "source_link": record.source_link,
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
