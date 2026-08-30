from __future__ import annotations

import hashlib
import ipaddress
from typing import Any
from urllib.parse import urlparse

from common.social_runtime import feishu_plain_text as _shared_feishu_plain_text

from .capability_registry import MEDIA_GROWTH_LABEL_CAPABILITIES, get_capability_spec
from .contracts import (
    VISIBLE_QUALITY_STATUSES,
    VISIBLE_STATUSES,
    VISIBLE_VISIBILITIES,
    utc_now_iso,
)


def is_projection_eligible(payload: dict[str, Any], *, maintainer: bool = False) -> bool:
    if maintainer:
        return bool(payload.get("display_title") and payload.get("display_summary"))
    return (
        payload.get("front_end_eligible") is True
        and payload.get("visibility") in VISIBLE_VISIBILITIES
        and payload.get("status") in VISIBLE_STATUSES
        and payload.get("quality_status") in VISIBLE_QUALITY_STATUSES
        and bool(payload.get("display_title"))
        and bool(payload.get("display_summary"))
    )


def _text(value: Any) -> str:
    # bool and list/tuple/set are handled here, ahead of the shared
    # renderer, and recurse through _text (not feishu_plain_text) so a
    # bool anywhere inside a nested list/tuple/set keeps this
    # projection's own wording at every depth: feishu_plain_text formats
    # a bool as "True"/"False" (Python's str()) and only recurses into
    # list, not tuple/set -- both differ from this projection's
    # established "true"/"false" and tuple/set-join wording, which is
    # kept unchanged rather than folded into the shared default.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return " / ".join(item for item in (_text(entry) for entry in value) if item)
    return _shared_feishu_plain_text(value, list_separator=" / ", unknown_dict="empty")


def _number(value: Any) -> float | int | None:
    if value in (None, "", []):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _safe_url(value: Any) -> str:
    text = _text(value)
    if not text.startswith(("https://", "http://")):
        return ""
    parsed = urlparse(text)
    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname == "localhost" or hostname.endswith(".local"):
        return ""
    try:
        if ipaddress.ip_address(hostname).is_private:
            return ""
    except ValueError:
        pass
    return text


def _projection_id(kind: str, raw_id: Any) -> str:
    digest = hashlib.sha256(f"{kind}:{_text(raw_id)}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}_{digest}"


def source_asset_public_id(raw_id: Any) -> str:
    """Return the stable redacted reference used by the public asset projection."""
    return _projection_id("asset", raw_id)


def review_public_id(raw_id: Any) -> str:
    """Return the stable redacted reference used by the public review projection."""
    return _projection_id("review", raw_id)


def _latest_timestamp(rows: list[dict[str, Any]]) -> str:
    values = sorted(
        (_text(row.get("updated_at") or row.get("reviewed_at") or row.get("created_at")) for row in rows),
        reverse=True,
    )
    return next((value for value in values if value), "")


def _build_accounts(account_metric_snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in account_metric_snapshots:
        account_name = _text(row.get("account_name"))
        platform = _text(row.get("platform"))
        if not account_name:
            continue
        group = grouped.setdefault(
            (platform, account_name),
            {
                "id": _projection_id("account", f"{platform}:{account_name}"),
                "accountName": account_name,
                "platform": platform or "未标注平台",
                "status": "observed",
                "metrics": [],
                "dataSource": "H02_AccountMetricSnapshot_账号指标快照",
            },
        )
        metric_key = _text(row.get("metric_key"))
        metric_value = _number(row.get("metric_value"))
        if metric_key and metric_value is not None:
            group["metrics"].append(
                {
                    "label": _text(row.get("raw_metric_name")) or metric_key,
                    "value": metric_value,
                    "unit": _text(row.get("unit")),
                    "quality": _text(row.get("data_quality")) or "unknown",
                }
            )
    return sorted(grouped.values(), key=lambda item: (item["platform"], item["accountName"]))


def _eligible_growth_summaries(
    growth_summaries: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    artifacts_by_id = _artifact_lookup(artifacts)
    return [
        summary
        for summary in growth_summaries
        if is_projection_eligible(summary)
        and (artifact := artifacts_by_id.get(_text(summary.get("artifact_id")))) is not None
        and is_projection_eligible(artifact)
    ]


def _string_values(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    raw_values = value if isinstance(value, (list, tuple, set)) else str(value).replace("，", ",").split(",")
    return list(dict.fromkeys(text for text in (_text(item) for item in raw_values) if text))


def _build_tracks(
    track_registry: list[dict[str, Any]],
    growth_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    content_counts: dict[str, int] = {}
    for row in growth_summaries:
        track_id = _text(row.get("track_id"))
        if track_id:
            content_counts[track_id] = content_counts.get(track_id, 0) + 1
    tracks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in track_registry:
        track_id = _text(row.get("track_id"))
        track_name = _text(row.get("track_name"))
        status = _text(row.get("status"))
        if not track_id or not track_name or status not in {"active", "inactive"}:
            raise ValueError("TrackRegistry projection received an invalid persisted row")
        if track_id in seen_ids:
            raise ValueError(f"TrackRegistry projection received duplicate track_id: {track_id}")
        seen_ids.add(track_id)
        parent_track_id = _text(row.get("parent_track_id"))
        tracks.append(
            {
                "id": _projection_id("track", track_id),
                "trackName": track_name,
                "description": _text(row.get("description")),
                "parentId": _projection_id("track", parent_track_id) if parent_track_id else "",
                "status": status,
                "platforms": _string_values(row.get("platform_scope")),
                "aliases": _string_values(row.get("alias_names")),
                "artifactCount": content_counts.get(track_id, 0),
                "dataSource": "07_TrackRegistry_赛道注册表",
            }
        )
    projected_ids = {item["id"] for item in tracks}
    orphan_parents = [item["parentId"] for item in tracks if item["parentId"] and item["parentId"] not in projected_ids]
    if orphan_parents:
        raise ValueError("TrackRegistry projection contains orphan parent tracks")
    return sorted(tracks, key=lambda item: (item["trackName"], item["id"]))


def _build_creator_profiles(creator_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in creator_profiles:
        creator_profile_id = _text(row.get("creator_profile_id"))
        platform = _text(row.get("platform"))
        author_id = _text(row.get("author_id"))
        account_name = _text(row.get("account_name"))
        if not creator_profile_id or not platform or not author_id or not account_name:
            raise ValueError("CreatorProfile projection received a row without required owner fields")
        if creator_profile_id in seen_ids:
            raise ValueError("CreatorProfile projection received a duplicate primary identity")
        seen_ids.add(creator_profile_id)
        items.append(
            {
                "id": _projection_id("creator", creator_profile_id),
                "accountName": account_name,
                "platform": platform,
                "creatorRole": _text(row.get("creator_role")),
                "identityTags": _string_values(row.get("identity_tags")),
                "expertiseDomains": _string_values(row.get("expertise_domains")),
                "profileUrl": _safe_url(row.get("profile_url")),
                "dataSource": "06_CreatorProfiles_达人账号档案",
            }
        )
    return sorted(items, key=lambda item: (item["platform"], item["accountName"], item["id"]))


def _build_creator_memberships(
    memberships: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
    creator_profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    track_by_projection_id = {item["id"]: item for item in tracks}
    track_by_raw_id = {
        raw_id: track_by_projection_id[_projection_id("track", raw_id)]
        for raw_id in (
            _text(row.get("track_id"))
            for row in memberships
        )
        if raw_id and _projection_id("track", raw_id) in track_by_projection_id
    }
    profile_by_id = {
        _text(row.get("creator_profile_id")): row
        for row in creator_profiles
        if _text(row.get("creator_profile_id"))
    }
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for row in memberships:
        membership_id = _text(row.get("membership_id"))
        raw_track_id = _text(row.get("track_id"))
        creator_profile_id = _text(row.get("creator_profile_id"))
        status = _text(row.get("status"))
        role = _text(row.get("role"))
        score = _number(row.get("fit_score"))
        if not membership_id or not raw_track_id or not creator_profile_id:
            raise ValueError("TrackCreatorMembership projection received a row without identity fields")
        if membership_id in seen_ids or (raw_track_id, creator_profile_id) in seen_pairs:
            raise ValueError("TrackCreatorMembership projection received a duplicate relation")
        if status not in {"candidate", "active", "rejected"} or score is None or not 0 <= score <= 100:
            raise ValueError(f"TrackCreatorMembership projection received invalid status/score: {membership_id}")
        track = track_by_raw_id.get(raw_track_id)
        profile = profile_by_id.get(creator_profile_id)
        if not track or not profile:
            raise ValueError(f"TrackCreatorMembership projection contains orphan relation: {membership_id}")
        seen_ids.add(membership_id)
        seen_pairs.add((raw_track_id, creator_profile_id))
        items.append(
            {
                "id": _projection_id("membership", membership_id),
                "trackId": track["id"],
                "trackName": track["trackName"],
                "creatorId": _projection_id("creator", creator_profile_id),
                "creatorName": _text(profile.get("account_name")) or _text(row.get("account_name_snapshot")),
                "platform": _text(profile.get("platform")) or _text(row.get("platform")) or "未标注平台",
                "role": role,
                "fitScore": score,
                "fitReason": _text(row.get("fit_reason")),
                "contentUseCase": _text(row.get("content_use_case")),
                "businessUseCase": _text(row.get("business_use_case")),
                "status": status,
                "lastEvaluatedAt": _text(row.get("last_evaluated_at")),
                "dataSource": "R03_TrackCreatorMembership_赛道博主关系 + 06_CreatorProfiles_达人账号档案",
            }
        )
    return sorted(items, key=lambda item: (item["trackName"], -item["fitScore"], item["creatorName"]))


def _build_track_graph(tracks: list[dict[str, Any]], memberships: list[dict[str, Any]]) -> dict[str, Any]:
    track_nodes = [
        {
            "id": item["id"],
            "kind": "track",
            "label": item["trackName"],
            "secondary": " / ".join(item["platforms"]) or "未限定平台",
            "status": item["status"],
        }
        for item in tracks
    ]
    creator_nodes_by_id: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for item in memberships:
        creator_nodes_by_id.setdefault(
            item["creatorId"],
            {
                "id": item["creatorId"],
                "kind": "creator",
                "label": item["creatorName"],
                "secondary": item["platform"],
                "status": item["status"],
            },
        )
        edges.append(
            {
                "id": _projection_id("edge", item["id"]),
                "source": item["trackId"],
                "target": item["creatorId"],
                "role": item["role"],
                "status": item["status"],
                "fitScore": item["fitScore"],
            }
        )
    nodes = track_nodes + sorted(creator_nodes_by_id.values(), key=lambda item: (item["label"], item["id"]))
    node_ids = {item["id"] for item in nodes}
    if any(edge["source"] not in node_ids or edge["target"] not in node_ids for edge in edges):
        raise ValueError("track graph contains orphan edge")
    return {"nodes": nodes, "edges": edges}


def _build_source_assets(source_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in source_assets:
        raw_id = row.get("asset_id") or row.get("source_asset_id")
        title = _text(row.get("title") or row.get("original_title"))
        if not raw_id or not title or row.get("enabled") is False:
            continue
        items.append(
            {
                "id": source_asset_public_id(raw_id),
                "title": title,
                "platform": _text(row.get("platform")) or "未标注平台",
                "accountName": _text(row.get("account_name_snapshot")),
                "status": _text(row.get("status")) or "unknown",
                "sourceUrl": _safe_url(row.get("source_url")),
                "dataSource": "02A_SourceAssets_素材源",
            }
        )
    return items


def _build_creation_runs(creation_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in creation_runs:
        raw_id = row.get("run_id")
        summary = _text(row.get("input_summary"))
        if not raw_id or not summary:
            continue
        items.append(
            {
                "id": _projection_id("run", raw_id),
                "summary": summary,
                "entrypoint": _text(row.get("entrypoint")) or "创作",
                "status": _text(row.get("status")) or "unknown",
                "dataSource": "03_CreationRuns_创作运行",
            }
        )
    return items


def _artifact_lookup(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        _text(item.get("artifact_id")): item
        for item in artifacts
        if _text(item.get("artifact_id"))
    }


def _build_publishing_packs(
    growth_summaries: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    artifact_by_id = _artifact_lookup(artifacts)
    items: list[dict[str, Any]] = []
    for row in growth_summaries:
        if _text(row.get("artifact_type")) != "PublishingPack":
            continue
        raw_id = _text(row.get("artifact_id"))
        detail = artifact_by_id.get(raw_id, {})
        readiness = detail.get("readiness") if isinstance(detail.get("readiness"), dict) else {}
        items.append(
            {
                "id": _projection_id("pack", raw_id),
                "title": _text(row.get("display_title")),
                "summary": _text(row.get("display_summary")),
                "platform": _text(row.get("platform")) or "未标注平台",
                "status": _text(row.get("status")) or "ready",
                "qualityStatus": _text(row.get("quality_status")),
                "readiness": {
                    "ready": readiness.get("ready") is True,
                    "missing": [text for text in (_text(value) for value in readiness.get("missing", [])) if text],
                },
                "updatedAt": _text(row.get("updated_at")),
                "dataSource": "H03_GrowthSummary_增长摘要",
            }
        )
    return items


def _build_review_signals(
    post_reviews: list[dict[str, Any]],
    metric_snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metrics_by_post: dict[str, list[dict[str, Any]]] = {}
    for metric in metric_snapshots:
        post_id = _text(metric.get("post_id"))
        value = _number(metric.get("metric_value"))
        if not post_id or value is None:
            continue
        metrics_by_post.setdefault(post_id, []).append(
            {
                "label": _text(metric.get("raw_metric_name")) or _text(metric.get("metric_key")) or "指标",
                "value": value,
                "unit": _text(metric.get("unit")),
                "quality": _text(metric.get("data_quality")) or "unknown",
            }
        )
    items: list[dict[str, Any]] = []
    for row in post_reviews:
        raw_id = _text(row.get("post_id"))
        if not raw_id:
            continue
        items.append(
            {
                "id": review_public_id(raw_id),
                "platform": _text(row.get("platform")) or "未标注平台",
                "reviewNode": _text(row.get("review_node")) or "复盘",
                "rating": _text(row.get("performance_rating")) or "待判断",
                "summary": _text(row.get("key_metrics_summary")) or "暂无复盘摘要",
                "publishedUrl": _safe_url(row.get("published_url")),
                "metrics": metrics_by_post.get(raw_id, []),
                "dataSource": "04_PostReviews_发布复盘 + H01_MetricSnapshot_作品指标快照",
            }
        )
    return items


def _build_next_actions() -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for label, capability_id in MEDIA_GROWTH_LABEL_CAPABILITIES.items():
        spec = get_capability_spec(capability_id)
        if not spec:
            continue
        actions.append(
            {
                "id": _projection_id("action", capability_id),
                "label": label,
                "copyText": f"【{label}】",
                "group": spec.frontend_group,
                "lifecycleLayer": spec.lifecycle_layer,
                "availability": spec.implementation_status,
                "requiresManualCompletion": spec.implementation_status == "not_implemented",
                "dataSource": "Mediaclaw capability registry",
            }
        )
    return actions


def build_dashboard_projection(
    artifacts: list[dict[str, Any]],
    *,
    source_assets: list[dict[str, Any]] | None = None,
    creation_runs: list[dict[str, Any]] | None = None,
    post_reviews: list[dict[str, Any]] | None = None,
    creator_profiles: list[dict[str, Any]] | None = None,
    track_registry: list[dict[str, Any]] | None = None,
    track_creator_memberships: list[dict[str, Any]] | None = None,
    metric_snapshots: list[dict[str, Any]] | None = None,
    account_metric_snapshots: list[dict[str, Any]] | None = None,
    growth_summaries: list[dict[str, Any]] | None = None,
    generated_at: str = "",
    source_health: dict[str, str] | None = None,
) -> dict[str, Any]:
    source_assets = list(source_assets or [])
    creation_runs = list(creation_runs or [])
    post_reviews = list(post_reviews or [])
    creator_profiles = list(creator_profiles or [])
    track_registry = list(track_registry or [])
    track_creator_memberships = list(track_creator_memberships or [])
    metric_snapshots = list(metric_snapshots or [])
    account_metric_snapshots = list(account_metric_snapshots or [])
    growth_summaries = list(growth_summaries or [])
    visible_summaries = _eligible_growth_summaries(growth_summaries, artifacts)
    accounts = _build_accounts(account_metric_snapshots)
    tracks = _build_tracks(track_registry, visible_summaries)
    creator_profile_projection = _build_creator_profiles(creator_profiles)
    creator_memberships = _build_creator_memberships(track_creator_memberships, tracks, creator_profiles)
    track_graph = _build_track_graph(tracks, creator_memberships)
    source_asset_projection = _build_source_assets(source_assets)
    creation_run_projection = _build_creation_runs(creation_runs)
    publishing_packs = _build_publishing_packs(visible_summaries, artifacts)
    review_signals = _build_review_signals(post_reviews, metric_snapshots)
    next_actions = _build_next_actions()
    generated_at = generated_at or utc_now_iso()
    health = dict(source_health or {})
    counts = {
        "accounts": len(accounts),
        "tracks": len(tracks),
        "creatorProfiles": len(creator_profile_projection),
        "creatorMemberships": len(creator_memberships),
        "sourceAssets": len(source_asset_projection),
        "creationRuns": len(creation_run_projection),
        "publishingPacks": len(publishing_packs),
        "reviewSignals": len(review_signals),
        "nextActions": len(next_actions),
    }
    return {
        "schemaVersion": "media_growth_dashboard_v2",
        "generatedAt": generated_at,
        "source": "curated_projection",
        "provenance": {
            "businessFacts": "Feishu Media Model v2 canonical tables",
            "artifactDetails": "media_vault allowlisted fields joined through H03 GrowthSummary",
            "trackFacts": "07_TrackRegistry_赛道注册表",
            "creatorFacts": "06_CreatorProfiles_达人账号档案",
            "membershipFacts": "R03_TrackCreatorMembership_赛道博主关系",
            "capabilityActions": "Mediaclaw capability registry",
            "sourceHealth": health,
            "visibleGrowthSummaries": len(visible_summaries),
            "latestSourceUpdate": _latest_timestamp(growth_summaries),
        },
        "coverage": [
            {
                "key": "accounts",
                "status": "available" if accounts else "empty",
                "reason": "账号区只展示 H02 已持久化的账号指标快照，不把外部达人档案冒充自有账号。",
            },
            {
                "key": "tracks",
                "status": "available" if tracks else "empty",
                "reason": "赛道区只展示 07_TrackRegistry 已持久化的事实；H03 仅贡献已注册赛道的内容计数。",
            },
            {
                "key": "creatorProfiles",
                "status": "available" if creator_profile_projection else "empty",
                "reason": "博主池展示 06 表已持久化的公开账号事实；是否关联赛道只由 R03 决定。",
            },
            {
                "key": "creatorMemberships",
                "status": "available" if creator_memberships else "empty",
                "reason": (
                    f"R03 已确认 {len(creator_memberships)} 条证据式关系；关系只来自显式确认或已审阅来源事实。"
                    if creator_memberships
                    else "R03 当前没有可证明关系；达人档案、标签和简介不会被自动解释为赛道成员。"
                ),
            },
        ],
        "counts": counts,
        "accounts": accounts,
        "tracks": tracks,
        "creatorProfiles": creator_profile_projection,
        "creatorMemberships": creator_memberships,
        "trackGraph": track_graph,
        "sourceAssets": source_asset_projection,
        "creationRuns": creation_run_projection,
        "publishingPacks": publishing_packs,
        "reviewSignals": review_signals,
        "nextActions": next_actions,
    }
