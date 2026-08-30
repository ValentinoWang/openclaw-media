from __future__ import annotations

from typing import Any

from common.social_runtime import now_iso as _now_iso
from media_model.payloads import account_metric_snapshot_idempotency_key
from media_model.payloads import build_account_metric_snapshot_payload


METRIC_MAP = {
    "fans_count": ("followers", "粉丝数", "people"),
    "total_favorited": ("likes_total", "获赞数", "count"),
    "post_count": ("works_count", "作品数", "count"),
    "note_count": ("works_count", "笔记数", "count"),
}


def build_account_metric_snapshots(
    *,
    account_name: str,
    creator_profile_id: str,
    platform: str,
    extracted_profile: dict[str, Any],
    evidence_uri: str,
    collected_at: str | None = None,
) -> list[dict[str, Any]]:
    collected = collected_at or _now_iso()
    payloads: list[dict[str, Any]] = []
    for source_key, (metric_key, raw_metric_name, unit) in METRIC_MAP.items():
        value = extracted_profile.get(source_key)
        if not isinstance(value, (int, float)):
            continue
        snapshot_id = account_metric_snapshot_idempotency_key(
            creator_profile_id=creator_profile_id,
            platform=platform,
            metric_key=metric_key,
            collected_at=collected,
        )
        payloads.append(
            build_account_metric_snapshot_payload(
                account_name=account_name,
                snapshot_id=snapshot_id,
                creator_profile_id=creator_profile_id,
                platform=platform,
                metric_key=metric_key,
                raw_metric_name=raw_metric_name,
                metric_value=float(value),
                unit=unit,
                evidence_uri=evidence_uri,
                data_quality="complete",
            )
        )
    return payloads
