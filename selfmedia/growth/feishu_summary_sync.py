from __future__ import annotations

import os
from typing import Any, Mapping

from media_model.contract import MediaModelContract, MediaModelContractError


ENTITY_NAME = "GrowthSummary"
PRIMARY_KEY = "artifact_id"
ENV_KEY = "MEDIA_OS_GROWTH_SUMMARY_URL"

SUMMARY_FIELDS: tuple[str, ...] = (
    "artifact_id",
    "artifact_type",
    "source_capability_id",
    "display_title",
    "display_summary",
    "platform",
    "account_id",
    "track_id",
    "status",
    "quality_status",
    "visibility",
    "front_end_eligible",
    "artifact_uri",
    "created_at",
    "updated_at",
    "reviewed_at",
    "reviewed_by",
)


def resolve_growth_summary_table_url(env: Mapping[str, str] | None = None) -> str:
    values = env if env is not None else os.environ
    return str(values.get(ENV_KEY) or "").strip()


def artifact_to_growth_summary_record(artifact: Any) -> dict[str, Any]:
    source = _artifact_mapping(artifact)
    record: dict[str, Any] = {}
    for field_name in SUMMARY_FIELDS:
        if field_name not in source:
            continue
        value = source[field_name]
        if _is_empty(value):
            continue
        record[field_name] = value
    return record


def sync_growth_summary_artifact(
    artifact: Any,
    *,
    tenant_id: str,
    table_url: str | None = None,
    client: Any | None = None,
    contract: MediaModelContract | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    actual_contract = contract or MediaModelContract()
    payload = artifact_to_growth_summary_record(artifact)
    try:
        actual_contract.validate_payload(ENTITY_NAME, payload)
    except MediaModelContractError as exc:
        return {
            "ok": False,
            "status": "pending_manual",
            "entity": ENTITY_NAME,
            "reason": str(exc),
            "payload": payload,
        }

    resolved_url = str(table_url if table_url is not None else resolve_growth_summary_table_url()).strip()
    if dry_run:
        return {
            "ok": True,
            "status": "dry_run",
            "mode": "dry_run",
            "entity": ENTITY_NAME,
            "table_url_configured": bool(resolved_url),
            "payload": payload,
        }
    if not resolved_url:
        return {
            "ok": False,
            "status": "disabled",
            "entity": ENTITY_NAME,
            "reason": f"{ENV_KEY} is not configured; GrowthSummary Feishu sync is disabled.",
            "payload": payload,
        }

    try:
        result = _upsert_with_client(
            client,
            tenant_id=tenant_id,
            table_url=resolved_url,
            payload=payload,
            contract=actual_contract,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "execution_failed",
            "entity": ENTITY_NAME,
            "reason": str(exc),
            "payload": payload,
        }
    return {
        "ok": True,
        "status": "synced",
        "entity": ENTITY_NAME,
        "mode": str(result.get("mode") or "upsert") if isinstance(result, dict) else "upsert",
        "record_id": str(result.get("record_id") or "") if isinstance(result, dict) else "",
        "client_result": result,
    }


def _artifact_mapping(artifact: Any) -> Mapping[str, Any]:
    if isinstance(artifact, Mapping):
        return artifact
    to_dict = getattr(artifact, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, Mapping):
            return value
    raw = getattr(artifact, "__dict__", {})
    if isinstance(raw, Mapping):
        return raw
    return {}


def _upsert_with_client(
    client: Any | None,
    *,
    tenant_id: str,
    table_url: str,
    payload: dict[str, Any],
    contract: MediaModelContract,
) -> Any:
    actual_client = client
    if actual_client is None:
        from integrations.feishu.media_writer import upsert_entity_record

        actual_client = upsert_entity_record
    if hasattr(actual_client, "upsert_growth_summary"):
        return actual_client.upsert_growth_summary(
            payload=payload,
            table_url=table_url,
            contract=contract,
            session_tenant_id=tenant_id,
        )
    if hasattr(actual_client, "upsert_entity_record"):
        return actual_client.upsert_entity_record(
            ENTITY_NAME,
            table_url,
            payload,
            key_field=PRIMARY_KEY,
            contract=contract,
            session_tenant_id=tenant_id,
        )
    if callable(actual_client):
        return actual_client(
            ENTITY_NAME,
            table_url,
            payload,
            key_field=PRIMARY_KEY,
            contract=contract,
            session_tenant_id=tenant_id,
        )
    raise TypeError("GrowthSummary sync client must be callable or expose upsert_entity_record")


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []
