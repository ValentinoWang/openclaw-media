from __future__ import annotations

import hashlib
import re
import secrets
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .contract import MediaModelContract, MediaModelContractError

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "spm",
    "share_from_user_hidden",
    "share_id",
    "share_channel",
    "timestamp",
    "tt_from",
    "xsec_token",
}


def make_run_id(*, now: datetime | None = None) -> str:
    return _timestamp_id("run", now=now)


def make_render_id(*, now: datetime | None = None) -> str:
    return _timestamp_id("render", now=now)


def make_asset_id(platform: str, source_url: str = "", *, now: datetime | None = None) -> str:
    platform_part = _safe_part(platform or "asset")
    digest = hashlib.sha1(normalize_source_url(source_url).encode("utf-8")).hexdigest()[:8] if source_url else secrets.token_hex(4)
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return f"asset_{platform_part}_{timestamp}_{digest}"


def _timestamp_id(prefix: str, *, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    return f"{_safe_part(prefix)}_{timestamp}_{secrets.token_hex(3)}"


def _safe_part(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "item"


def normalize_source_url(url: Any) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+$", "", parsed.path or "/")
    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_KEYS or any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items))
    return urlunparse((scheme, netloc, path, "", query, ""))


def content_fingerprint(*, platform: str, source_url: str = "", author_id: str = "", external_post_id: str = "", title: str = "", body: str = "") -> str:
    parts = [
        str(platform or "").strip().lower(),
        normalize_source_url(source_url),
        str(author_id or "").strip().lower(),
        str(external_post_id or "").strip().lower(),
        normalize_text(title),
        normalize_text(body)[:2000],
    ]
    source = "\n".join(parts)
    return f"sha256:{hashlib.sha256(source.encode('utf-8')).hexdigest()}"


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def material_usage_idempotency_key(payload: dict[str, Any]) -> str:
    parts = [
        payload.get("run_id"),
        payload.get("asset_id"),
        payload.get("deconstruction_id"),
        payload.get("pattern_id"),
        payload.get("usage_type"),
    ]
    return "usage:" + hashlib.sha1("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()


def decision_trace_idempotency_key(payload: dict[str, Any]) -> str:
    parts = [
        payload.get("run_id"),
        payload.get("candidate_type"),
        payload.get("candidate_id"),
        payload.get("rank"),
    ]
    return "trace:" + hashlib.sha1("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()


def normalize_rebate_ratio(value: Any) -> float | None:
    if value in (None, "", []):
        return None
    if isinstance(value, str):
        text = value.strip().replace("％", "%")
        if not text:
            return None
        if text.endswith("%"):
            number = float(text[:-1].strip())
            return number / 100
        number = float(text)
    else:
        number = float(value)
    if number > 1:
        number = number / 100
    if number < 0:
        raise ValueError("rebate ratio cannot be negative")
    return number

METRIC_REGISTRY = {
    "impressions": {
        "display_name": "曝光",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["曝光", "曝光量", "展现", "impression", "impressions"],
    },
    "views": {
        "display_name": "播放",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["播放", "播放量", "views", "video_view"],
    },
    "reads": {
        "display_name": "阅读",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["阅读", "阅读量", "reads"],
    },
    "likes": {
        "display_name": "点赞",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["点赞", "赞", "likes"],
    },
    "saves": {
        "display_name": "收藏",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["收藏", "收藏量", "saves"],
    },
    "comments": {
        "display_name": "评论",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["评论", "评论量", "comments"],
    },
    "shares": {
        "display_name": "转发",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["转发", "分享", "shares"],
    },
    "follows": {
        "display_name": "涨粉",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["涨粉", "新增粉丝", "follows"],
    },
    "followers": {
        "display_name": "粉丝数",
        "unit": "people",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["粉丝数", "粉丝", "followers"],
    },
    "likes_total": {
        "display_name": "获赞数",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["获赞数", "总获赞", "likes_total"],
    },
    "works_count": {
        "display_name": "作品数",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["作品数", "笔记数", "视频数", "works_count"],
    },
    "avg_views_30d": {
        "display_name": "近30天平均播放",
        "unit": "count",
        "direction": "higher_is_better",
        "value_type": "integer",
        "aliases": ["近30天平均播放", "avg_views_30d"],
    },
}


class MetricRegistryError(RuntimeError):
    pass


def normalize_metric_key(raw_name: Any) -> str:
    text = str(raw_name or "").strip().lower()
    if not text:
        raise MetricRegistryError("metric name is required")
    for key, spec in METRIC_REGISTRY.items():
        if text == key.lower():
            return key
        aliases = [str(alias).strip().lower() for alias in spec.get("aliases", [])]
        if text in aliases:
            return key
    raise MetricRegistryError(f"unknown metric name: {raw_name}")


def metric_spec(metric_key: str) -> dict[str, Any]:
    key = normalize_metric_key(metric_key)
    return dict(METRIC_REGISTRY[key])


def metric_snapshot_idempotency_key(*, post_id: str, review_node: str, metric_key: str, collected_at: str) -> str:
    normalized = normalize_metric_key(metric_key)
    return "metric:" + hashlib.sha1(f"{post_id}|{review_node}|{normalized}|{collected_at}".encode("utf-8")).hexdigest()


def account_metric_snapshot_idempotency_key(*, creator_profile_id: str, platform: str, metric_key: str, collected_at: str) -> str:
    normalized = normalize_metric_key(metric_key)
    return "account_metric:" + hashlib.sha1(f"{creator_profile_id}|{platform}|{normalized}|{collected_at}".encode("utf-8")).hexdigest()

QUOTE_SNAPSHOT_VERSION = "quote_snapshot_v1"
QUOTE_STATUSES = {"current", "historical", "discarded", "pending_confirmation"}
TAX_POLICIES = {"tax_included", "tax_excluded", "unknown"}
PLATFORM_FEE_POLICIES = {"included_in_rebate", "excluded_from_rebate", "unknown"}
SOURCE_CONFIDENCE_VALUES = {"chat_confirmed", "brief_explicit", "manual_inferred", "unknown"}


class QuoteSnapshotError(RuntimeError):
    pass


def build_quote_snapshot_payload(
    *,
    opportunity_id: str,
    platform: str,
    content_form: str,
    amount: float,
    quote_month: str = "",
    report_type: str = "",
    rebate_ratio: Any = None,
    tax_policy: str = "unknown",
    platform_fee_policy: str = "unknown",
    settlement_entity: str = "",
    authorization_duration: str = "",
    price_protection_rule: str = "",
    valid_from: str = "",
    valid_until: str = "",
    quote_status: str = "pending_confirmation",
    source_confidence: str = "unknown",
    evidence_uri: str = "",
) -> dict[str, Any]:
    payload = {
        "version": QUOTE_SNAPSHOT_VERSION,
        "opportunity_id": opportunity_id,
        "platform": platform,
        "quote_month": quote_month,
        "content_form": content_form,
        "report_type": report_type,
        "amount": amount,
        "currency": "CNY",
        "rebate_ratio": normalize_rebate_ratio(rebate_ratio),
        "tax_policy": tax_policy,
        "platform_fee_policy": platform_fee_policy,
        "settlement_entity": settlement_entity,
        "authorization_duration": authorization_duration,
        "price_protection_rule": price_protection_rule,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "quote_status": quote_status,
        "source_confidence": source_confidence,
        "evidence_uri": evidence_uri,
    }
    compact = {key: value for key, value in payload.items() if value not in (None, "", [])}
    validate_quote_snapshot_payload(compact)
    return compact


def validate_quote_snapshot_payload(payload: dict[str, Any]) -> None:
    missing = [key for key in ("version", "opportunity_id", "platform", "content_form", "amount", "quote_status") if payload.get(key) in (None, "", [])]
    if missing:
        raise QuoteSnapshotError(f"quote snapshot missing required fields: {missing}")
    if payload.get("version") != QUOTE_SNAPSHOT_VERSION:
        raise QuoteSnapshotError(f"unsupported quote snapshot version: {payload.get('version')}")
    if payload.get("quote_status") not in QUOTE_STATUSES:
        raise QuoteSnapshotError(f"invalid quote_status: {payload.get('quote_status')}")
    if payload.get("tax_policy") not in TAX_POLICIES:
        raise QuoteSnapshotError(f"invalid tax_policy: {payload.get('tax_policy')}")
    if payload.get("platform_fee_policy") not in PLATFORM_FEE_POLICIES:
        raise QuoteSnapshotError(f"invalid platform_fee_policy: {payload.get('platform_fee_policy')}")
    if payload.get("source_confidence") not in SOURCE_CONFIDENCE_VALUES:
        raise QuoteSnapshotError(f"invalid source_confidence: {payload.get('source_confidence')}")
    if float(payload.get("amount") or 0) < 0:
        raise QuoteSnapshotError("quote amount cannot be negative")
    rebate = payload.get("rebate_ratio")
    if rebate is not None and not 0 <= float(rebate) <= 1:
        raise QuoteSnapshotError("rebate_ratio must be in 0..1")
    if payload.get("evidence_uri") and not str(payload["evidence_uri"]).startswith("media://"):
        raise QuoteSnapshotError("quote evidence_uri must use media://")
    _validate_date_order(payload.get("valid_from", ""), payload.get("valid_until", ""))


def _validate_date_order(valid_from: str, valid_until: str) -> None:
    if not valid_from or not valid_until:
        return
    try:
        start = date.fromisoformat(valid_from)
        end = date.fromisoformat(valid_until)
    except ValueError as exc:
        raise QuoteSnapshotError("valid_from and valid_until must be ISO dates") from exc
    if end < start:
        raise QuoteSnapshotError("valid_until cannot be before valid_from")

class RenderSpecError(RuntimeError):
    pass


RENDER_SPEC_SCHEMA = {
    "required": [
        "render_id",
        "run_id",
        "entry_tag",
        "platform",
        "content_type",
        "template_version",
        "sections",
    ],
    "section_required": [
        "type",
        "title",
        "data_ref",
    ],
    "data_ref_scheme": "media://",
}


def build_render_spec(
    *,
    render_id: str,
    run_id: str,
    entry_tag: str,
    platform: str,
    content_type: str,
    theme: str,
    sections: list[dict[str, Any]],
    template_version: str = "hyperframe_v1",
) -> dict[str, Any]:
    render_spec = {
        "render_id": render_id,
        "run_id": run_id,
        "entry_tag": entry_tag,
        "platform": platform,
        "content_type": content_type,
        "theme": theme,
        "template_version": template_version,
        "sections": sections,
        "schema": RENDER_SPEC_SCHEMA,
    }
    validate_render_spec(render_spec)
    return render_spec


def validate_render_spec(render_spec: dict[str, Any]) -> None:
    if not isinstance(render_spec, dict):
        raise RenderSpecError("render_spec must be object")
    missing = [key for key in RENDER_SPEC_SCHEMA["required"] if not render_spec.get(key)]
    if missing:
        raise RenderSpecError(f"render_spec missing keys: {missing}")
    if not str(render_spec.get("render_id") or "").startswith("render_"):
        raise RenderSpecError("render_id must start with render_")
    if not str(render_spec.get("run_id") or "").startswith("run_"):
        raise RenderSpecError("run_id must start with run_")
    sections = render_spec.get("sections")
    if not isinstance(sections, list) or not sections:
        raise RenderSpecError("render_spec.sections must be non-empty list")
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise RenderSpecError(f"render_spec.sections[{index}] must be object")
        missing_section = [key for key in RENDER_SPEC_SCHEMA["section_required"] if not section.get(key)]
        if missing_section:
            raise RenderSpecError(f"render_spec.sections[{index}] missing keys: {missing_section}")
        data_ref = str(section.get("data_ref") or "")
        if not data_ref.startswith("media://"):
            raise RenderSpecError(f"render_spec.sections[{index}].data_ref must use media://")


def render_spec_payloads(render_spec: dict[str, Any], payload_by_uri: dict[str, Any]) -> list[tuple[dict[str, Any], Any]]:
    validate_render_spec(render_spec)
    resolved: list[tuple[dict[str, Any], Any]] = []
    for section in render_spec["sections"]:
        data_ref = section["data_ref"]
        if data_ref not in payload_by_uri:
            raise RenderSpecError(f"missing payload for render section data_ref: {data_ref}")
        resolved.append((section, payload_by_uri[data_ref]))
    return resolved


def render_spec_to_creator_draft(render_spec: dict[str, Any], payload_by_uri: dict[str, Any]) -> dict[str, Any]:
    for section, payload in render_spec_payloads(render_spec, payload_by_uri):
        if section.get("type") in {"draft_output", "xhs_carousel_script", "douyin_storyboard_doc", "creator_report"}:
            if isinstance(payload, dict) and isinstance(payload.get("creator_report"), dict):
                return payload
    raise RenderSpecError("render_spec does not contain an accepted creator_report draft_output section")


def render_spec_to_creator_doc_blocks(
    render_spec: dict[str, Any],
    payload_by_uri: dict[str, Any],
    *,
    request: Any,
    activities: list[Any] | None = None,
    virals: list[Any] | None = None,
    inspirations: list[Any] | None = None,
    businesses: list[Any] | None = None,
    validation: dict[str, Any] | None = None,
    platform_fit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    draft = render_spec_to_creator_draft(render_spec, payload_by_uri)
    title = f"{render_spec.get('content_type')} - {render_spec.get('theme') or getattr(request, 'topic', '')}".strip(" -")
    report = draft.get("creator_report") if isinstance(draft, dict) else {}
    if not isinstance(report, dict):
        report = {}
    rows = [
        ["字段", "内容"],
        ["平台", str(render_spec.get("platform") or getattr(request, "platform", ""))],
        ["内容类型", str(render_spec.get("content_type") or getattr(request, "content_type", ""))],
        ["标题", str(draft.get("title") or report.get("title") or title)],
        ["推荐版本", str(draft.get("recommended_option_id") or "")],
        ["校验状态", "通过" if (validation or {"ok": True}).get("ok") else "待人工处理"],
        ["平台适配", str((platform_fit or {}).get("summary") or "")],
        ["参考活动数", str(len(activities or []))],
        ["参考爆款数", str(len(virals or []))],
        ["参考灵感数", str(len(inspirations or []))],
        ["参考商务数", str(len(businesses or []))],
    ]
    return [
        {"heading": title},
        {"paragraph": "由 media_model render_spec 生成的结构化创作文档块。"},
        {"_openclaw_kind": "_openclaw_feishu_table", "rows": rows},
    ]


def render_spec_to_task_card_blocks(
    render_spec: dict[str, Any],
    payload_by_uri: dict[str, Any],
    *,
    writer: Any,
    doc_title: str,
    record_type: str,
) -> list[dict[str, Any]]:
    validate_render_spec(render_spec)
    if not hasattr(writer, "blocks_from_text"):
        raise RenderSpecError("task card rendering must reuse CreationFeishuDocumentWriter.blocks_from_text")
    text = _task_card_text(render_spec, payload_by_uri)
    return writer.blocks_from_text(doc_title, record_type, text)


def _task_card_text(render_spec: dict[str, Any], payload_by_uri: dict[str, Any]) -> str:
    lines = [f"# {render_spec.get('theme') or render_spec.get('entry_tag')}", ""]
    for section, payload in render_spec_payloads(render_spec, payload_by_uri):
        lines.append(f"## {section.get('title')}")
        if isinstance(payload, str):
            lines.append(payload)
        elif isinstance(payload, dict):
            summary = payload.get("summary") or payload.get("title") or payload.get("final_copy") or payload.get("body") or ""
            lines.append(str(summary or "见 media_vault artifact。"))
        else:
            lines.append("见 media_vault artifact。")
        lines.append("")
    return "\n".join(lines).strip()

class MediaModelPayloadError(RuntimeError):
    pass


def build_source_asset_payload(
    *,
    platform: str,
    title: str,
    source_url: str,
    evidence_uri: str,
    asset_id: str | None = None,
    original_title: str = "",
    author_id: str = "",
    external_post_id: str = "",
    account_name_snapshot: str = "",
    creator_profile_id: str = "",
    source_doc_link: str = "",
    body: str = "",
    status: str = "待解析",
    enabled: bool = True,
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    normalized_url = normalize_source_url(source_url)
    payload = _compact_payload(
        {
            "asset_id": asset_id or make_asset_id(platform, normalized_url),
            "content_fingerprint": content_fingerprint(
                platform=platform,
                source_url=normalized_url,
                author_id=author_id,
                external_post_id=external_post_id,
                title=title,
                body=body,
            ),
            "title": title,
            "original_title": original_title,
            "platform": platform,
            "source_url": normalized_url,
            "author_id": author_id,
            "creator_profile_id": creator_profile_id,
            "account_name_snapshot": account_name_snapshot,
            "evidence_uri": evidence_uri,
            "source_doc_link": source_doc_link,
            "status": status,
            "enabled": enabled,
        }
    )
    _validate("SourceAsset", payload, contract)
    _forbid_terms("SourceAsset", payload, ("报价", "返点", "档期", "Brief", "发布链接", "复盘", "提醒"))
    return payload


def build_material_deconstruction_payload(
    *,
    deconstruction_id: str,
    asset_id: str,
    summary: str,
    evidence_uri: str,
    prompt_bundle_version: str,
    model: str,
    confidence: float,
    hook: str = "",
    transferable_points: str = "",
    non_transferable_points: str = "",
    shot_adaptation_notes_status: str = "",
    shot_adaptation_note_count: int | float | None = None,
    recommended_production_route: str = "",
    motion_type_summary: str = "",
    shot_adaptation_notes_summary: str = "",
    cover_opening_hook: str = "",
    core_data_summary: str = "",
    top_comment_insight: str = "",
    target_audience_summary: str = "",
    pain_pleasure_summary: str = "",
    attention_elements: str = "",
    viral_breakdown: str = "",
    viral_migration: str = "",
    creative_upgrade_suggestion: str = "",
    skill_version: str = "",
    deconstruction_doc_link: str = "",
    review_status: str = "未复核",
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    payload = _compact_payload(
        {
            "deconstruction_id": deconstruction_id,
            "asset_id": asset_id,
            "summary": summary,
            "hook": hook,
            "transferable_points": transferable_points,
            "non_transferable_points": non_transferable_points,
            "shot_adaptation_notes_status": shot_adaptation_notes_status,
            "shot_adaptation_note_count": shot_adaptation_note_count,
            "recommended_production_route": recommended_production_route,
            "motion_type_summary": motion_type_summary,
            "shot_adaptation_notes_summary": shot_adaptation_notes_summary,
            "cover_opening_hook": cover_opening_hook,
            "core_data_summary": core_data_summary,
            "top_comment_insight": top_comment_insight,
            "target_audience_summary": target_audience_summary,
            "pain_pleasure_summary": pain_pleasure_summary,
            "attention_elements": attention_elements,
            "viral_breakdown": viral_breakdown,
            "viral_migration": viral_migration,
            "creative_upgrade_suggestion": creative_upgrade_suggestion,
            "prompt_bundle_version": prompt_bundle_version,
            "model": model,
            "skill_version": skill_version,
            "confidence": confidence,
            "evidence_uri": evidence_uri,
            "deconstruction_doc_link": deconstruction_doc_link,
            "review_status": review_status,
        }
    )
    if not 0 <= float(confidence) <= 1:
        raise MediaModelPayloadError("MaterialDeconstruction confidence must be in 0..1")
    _validate("MaterialDeconstruction", payload, contract)
    return payload


def build_pattern_payload(
    *,
    pattern_id: str,
    pattern_name: str,
    pattern_status: str = "candidate_pattern",
    supporting_asset_ids: list[str] | None = None,
    supporting_run_ids: list[str] | None = None,
    historical_performance_summary: str = "",
    manual_confirmed: bool = False,
    positive_metric_evidence: bool = False,
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    supporting_asset_ids = supporting_asset_ids or []
    supporting_run_ids = supporting_run_ids or []
    if pattern_status == "proven_pattern" and not (
        manual_confirmed or positive_metric_evidence or len(set(supporting_asset_ids)) >= 2
    ):
        raise MediaModelPayloadError("CreativePattern cannot become proven_pattern from a single unverified source")
    payload = _compact_payload(
        {
            "pattern_id": pattern_id,
            "pattern_name": pattern_name,
            "pattern_status": pattern_status,
            "supporting_asset_ids": supporting_asset_ids,
            "supporting_run_ids": supporting_run_ids,
            "historical_performance_summary": historical_performance_summary,
        }
    )
    _validate("CreativePattern", payload, contract)
    return payload


def build_creation_run_payload(
    *,
    run_id: str,
    entrypoint: str,
    input_summary: str,
    status: str,
    generation_source: str,
    run_artifact_uri: str,
    render_id: str = "",
    render_spec_uri: str = "",
    feishu_doc_link: str = "",
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    payload = _compact_payload(
        {
            "run_id": run_id,
            "entrypoint": entrypoint,
            "input_summary": input_summary,
            "status": status,
            "generation_source": generation_source,
            "run_artifact_uri": run_artifact_uri,
            "render_id": render_id,
            "render_spec_uri": render_spec_uri,
            "feishu_doc_link": feishu_doc_link,
        }
    )
    _validate("CreationRun", payload, contract)
    return payload


def build_decision_trace_payloads(
    *,
    run_id: str,
    candidates: list[dict[str, Any]],
    decision_version: str,
    contract: MediaModelContract | None = None,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, 1):
        payload = _compact_payload(
            {
                "run_id": run_id,
                "candidate_type": candidate.get("candidate_type") or candidate.get("type"),
                "candidate_id": candidate.get("candidate_id") or candidate.get("id"),
                "rank": candidate.get("rank") or index,
                "score": candidate.get("score"),
                "selected": bool(candidate.get("selected")),
                "reason_summary": candidate.get("reason_summary") or candidate.get("selection_reason") or candidate.get("reason"),
                "rejection_reason": candidate.get("rejection_reason"),
                "score_breakdown_uri": candidate.get("score_breakdown_uri"),
                "decision_version": decision_version,
            }
        )
        payload["trace_id"] = str(candidate.get("trace_id") or decision_trace_idempotency_key(payload))
        _validate("DecisionTrace", payload, contract)
        _require_score(payload, "DecisionTrace")
        payloads.append(payload)
    if candidates and not payloads:
        raise MediaModelPayloadError("DecisionTrace candidates were provided but no payloads were built")
    return payloads


def build_material_usage_payloads(
    *,
    run_id: str,
    usages: list[dict[str, Any]],
    contract: MediaModelContract | None = None,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for usage in usages:
        payload = _compact_payload(
            {
                "run_id": run_id,
                "asset_id": usage.get("asset_id"),
                "deconstruction_id": usage.get("deconstruction_id"),
                "pattern_id": usage.get("pattern_id"),
                "usage_type": usage.get("usage_type"),
                "score": usage.get("score"),
                "selected_for_final": bool(usage.get("selected_for_final")),
                "performance_feedback_summary": usage.get("performance_feedback_summary"),
            }
        )
        payload["usage_id"] = str(usage.get("usage_id") or material_usage_idempotency_key(payload))
        if not any(payload.get(key) for key in ("asset_id", "deconstruction_id", "pattern_id")):
            raise MediaModelPayloadError("MaterialUsage requires at least one asset/deconstruction/pattern reference")
        _validate("MaterialUsage", payload, contract)
        if "score" in payload:
            _require_score(payload, "MaterialUsage")
        payloads.append(payload)
    return payloads


def build_metric_snapshot_payload(
    *,
    snapshot_id: str,
    post_id: str,
    review_node: str,
    metric_key: str,
    metric_value: float,
    unit: str,
    evidence_uri: str,
    raw_metric_name: str = "",
    data_quality: str = "complete",
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    payload = _compact_payload(
        {
            "snapshot_id": snapshot_id,
            "post_id": post_id,
            "review_node": review_node,
            "metric_key": metric_key,
            "raw_metric_name": raw_metric_name,
            "metric_value": metric_value,
            "unit": unit,
            "evidence_uri": evidence_uri,
            "data_quality": data_quality,
        }
    )
    _validate("MetricSnapshot", payload, contract)
    return payload


def build_account_metric_snapshot_payload(
    *,
    account_name: str,
    snapshot_id: str,
    creator_profile_id: str,
    platform: str,
    metric_key: str,
    metric_value: float,
    unit: str,
    evidence_uri: str,
    raw_metric_name: str = "",
    data_quality: str = "complete",
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    payload = _compact_payload(
        {
            "account_name": account_name,
            "snapshot_id": snapshot_id,
            "creator_profile_id": creator_profile_id,
            "platform": platform,
            "metric_key": metric_key,
            "raw_metric_name": raw_metric_name,
            "metric_value": metric_value,
            "unit": unit,
            "evidence_uri": evidence_uri,
            "data_quality": data_quality,
        }
    )
    _validate("AccountMetricSnapshot", payload, contract)
    return payload


def build_business_account_payload(
    *,
    business_account_id: str,
    author_id: str,
    account_name_snapshot: str,
    platform: str,
    creator_profile_id: str = "",
    current_image_quote_amount: float | None = None,
    current_video_quote_amount: float | None = None,
    quote_snapshot_uri: str = "",
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    payload = _compact_payload(
        {
            "business_account_id": business_account_id,
            "creator_profile_id": creator_profile_id,
            "author_id": author_id,
            "account_name_snapshot": account_name_snapshot,
            "platform": platform,
            "current_image_quote_amount": current_image_quote_amount,
            "current_video_quote_amount": current_video_quote_amount,
            "quote_snapshot_uri": quote_snapshot_uri,
        }
    )
    _validate("BusinessAccount", payload, contract)
    return payload


def build_business_opportunity_payload(
    *,
    opportunity_id: str,
    brand: str,
    business_account_id: str = "",
    product: str = "",
    brief_link: str = "",
    current_quote_amount: float | None = None,
    rebate_ratio: Any = None,
    valid_from: str = "",
    valid_until: str = "",
    quote_snapshot_uri: str = "",
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    payload = _compact_payload(
        {
            "opportunity_id": opportunity_id,
            "business_account_id": business_account_id,
            "brand": brand,
            "product": product,
            "brief_link": brief_link,
            "current_quote_amount": current_quote_amount,
            "rebate_ratio": normalize_rebate_ratio(rebate_ratio),
            "valid_from": valid_from,
            "valid_until": valid_until,
            "quote_snapshot_uri": quote_snapshot_uri,
        }
    )
    _validate("BusinessOpportunity", payload, contract)
    return payload


def _validate(entity_name: str, payload: dict[str, Any], contract: MediaModelContract | None) -> None:
    try:
        (contract or MediaModelContract()).validate_payload(entity_name, payload)
    except MediaModelContractError as exc:
        raise MediaModelPayloadError(str(exc)) from exc


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def _require_score(payload: dict[str, Any], label: str) -> None:
    score = payload.get("score")
    if not isinstance(score, (int, float)):
        raise MediaModelPayloadError(f"{label} score must be numeric")
    if not 0 <= float(score) <= 100:
        raise MediaModelPayloadError(f"{label} score must be in 0..100")


def _forbid_terms(entity_name: str, payload: dict[str, Any], terms: tuple[str, ...]) -> None:
    joined_keys = "\n".join(payload)
    joined_values = "\n".join(str(value) for value in payload.values())
    for term in terms:
        if term in joined_keys:
            raise MediaModelPayloadError(f"{entity_name} payload key leaks forbidden owner term: {term}")
    if any(term in joined_values for term in ("报价", "返点", "Brief收集状态", "复盘状态")):
        digest = hashlib.sha1(joined_values.encode("utf-8")).hexdigest()[:8]
        raise MediaModelPayloadError(f"{entity_name} payload value appears to leak owner data; digest={digest}")
