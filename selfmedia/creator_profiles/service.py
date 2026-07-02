from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .candidate_builder import build_candidate
from .evidence import write_evidence_bundle
from .metric_snapshot import build_account_metric_snapshots
from .resolver import resolve_creator_profile
from .run_store import RunStore
from .schemas import CREATOR_PROFILE_FIELDS, normalize_id_type, normalize_platform, now_run_id


PROJECT_ROOT = Path(__file__).resolve().parents[2]

from integrations.feishu.media_writer import upsert_entity_record
from media_model.contract import MediaModelContract


DEFAULT_CREATOR_PROFILE_URL = (
    "https://tcnwueberajc.feishu.cn/base/OmjkbgBkwa2JEysEN8uc5PMhnTb"
    "?table=tblBrERiQnWvZFwp"
)
DEFAULT_ACCOUNT_METRIC_SNAPSHOT_URL = (
    "https://tcnwueberajc.feishu.cn/base/OmjkbgBkwa2JEysEN8uc5PMhnTb"
    "?table=tblYqbE2vkr9RGSK"
)


def generate_candidate_run(
    *,
    platform: str,
    platform_id: str,
    id_type: str = "",
    url: str = "",
    creator_name: str = "",
    use_llm: bool = True,
) -> dict[str, Any]:
    run_id = now_run_id()
    normalized_platform = normalize_platform(platform)
    normalized_id_type = normalize_id_type(id_type, platform=normalized_platform)
    resolver_result = resolve_creator_profile(
        platform=normalized_platform,
        platform_id=str(platform_id).strip(),
        id_type=normalized_id_type,
        url=url,
        creator_name=creator_name,
    )
    bundle = write_evidence_bundle(run_id=run_id, resolver_result=resolver_result)
    if not resolver_result.get("ok"):
        blocked = {
            "write_status": "blocked_not_written",
            "run_id": run_id,
            "evidence_uri": bundle["uri"],
            "resolver": {key: value for key, value in resolver_result.items() if key not in {"raw_dom", "screenshot_bytes"}},
            "candidate_payload": {},
        }
        (Path(bundle["dir"]) / "candidate_result.json").write_text(json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8")
        return blocked
    candidate = build_candidate(run_id=run_id, resolver_result=resolver_result, evidence_uri=bundle["uri"], use_llm=use_llm)
    (Path(bundle["dir"]) / "candidate_result.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    return candidate


def confirm_candidate_run(
    run_id: str,
    *,
    creator_profiles_url: str | None = None,
    account_metric_snapshot_url: str | None = None,
    user_edits: dict[str, Any] | None = None,
    write_metrics: bool = True,
) -> dict[str, Any]:
    store = RunStore()
    candidate = store.read_json(run_id, "candidate_result.json")
    if candidate.get("write_status") != "candidate_only_not_written":
        raise RuntimeError(f"candidate run is not writable: {candidate.get('write_status')}")
    payload = dict(candidate.get("candidate_payload") or {})
    if user_edits:
        payload.update({key: value for key, value in user_edits.items() if key in CREATOR_PROFILE_FIELDS})
    MediaModelContract().validate_payload("CreatorProfile", payload)
    table_url = creator_profiles_url or os.getenv("MEDIA_OS_CREATOR_PROFILES_V2_URL", "").strip() or DEFAULT_CREATOR_PROFILE_URL
    creator_result = upsert_entity_record("CreatorProfile", table_url, payload, key_field="creator_profile_id")
    metric_results: list[dict[str, Any]] = []
    metric_status = "skipped"
    if write_metrics:
        metric_url = (
            account_metric_snapshot_url
            or os.getenv("MEDIA_OS_ACCOUNT_METRIC_SNAPSHOT_URL", "").strip()
            or DEFAULT_ACCOUNT_METRIC_SNAPSHOT_URL
        )
        extracted = store.read_json(run_id, "extracted_profile.json")
        metric_payloads = build_account_metric_snapshots(
            account_name=str(payload.get("account_name") or ""),
            creator_profile_id=str(payload.get("creator_profile_id") or ""),
            platform=str(payload.get("platform") or ""),
            extracted_profile=extracted,
            evidence_uri=str(candidate.get("evidence_uri") or ""),
        )
        for item in metric_payloads:
            metric_results.append(upsert_entity_record("AccountMetricSnapshot", metric_url, item, key_field="snapshot_id"))
        metric_status = "written" if metric_results else "no_metrics"
    final = {
        "write_status": "written",
        "run_id": run_id,
        "creator_profile": creator_result,
        "metric_snapshot_status": metric_status,
        "metric_snapshots": metric_results,
        "candidate_payload": payload,
        "evidence_uri": candidate.get("evidence_uri", ""),
    }
    store.write_json(run_id, "final_payload.json", final)
    return final
