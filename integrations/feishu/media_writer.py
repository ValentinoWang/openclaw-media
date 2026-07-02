from __future__ import annotations

import re
from typing import Any

import requests

from common.social_runtime import (
    FEISHU_BASE,
    feishu_bitable_refs,
    feishu_coerce_value,
    feishu_field_types,
    feishu_headers,
    feishu_list_records,
)

from media_model.contract import MediaModelContract


OPTION_ID_RE = re.compile(r"^opt[A-Za-z0-9]{6,}$")


class MediaModelFeishuWriterError(RuntimeError):
    pass


def prepare_entity_bitable_fields(
    entity_name: str,
    payload: dict[str, Any],
    field_types: dict[str, Any],
    *,
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    contract = contract or MediaModelContract()
    contract.validate_payload(entity_name, payload)
    prepared: dict[str, Any] = {}
    for canonical_key, value in payload.items():
        feishu_field_name = contract.feishu_field_name(entity_name, canonical_key)
        if feishu_field_name not in field_types:
            continue
        _reject_option_ids(value, field_label=f"{entity_name}.{canonical_key}")
        coerced = feishu_coerce_value(value, field_types.get(feishu_field_name))
        if coerced in (None, "", []):
            continue
        prepared[feishu_field_name] = coerced
    if not prepared:
        raise MediaModelFeishuWriterError(f"{entity_name} payload has no fields present in target table")
    return prepared


def write_entity_record(
    entity_name: str,
    table_url: str,
    payload: dict[str, Any],
    *,
    contract: MediaModelContract | None = None,
    dry_run: bool = False,
    field_types_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not table_url and not field_types_override:
        raise MediaModelFeishuWriterError("table_url is required unless field_types_override is provided")
    token = ""
    app_token = ""
    table_id = ""
    if field_types_override is None:
        app_token, table_id, token = feishu_bitable_refs(table_url)
        field_types = feishu_field_types(app_token, table_id, token)
    else:
        field_types = dict(field_types_override)
    fields = prepare_entity_bitable_fields(entity_name, payload, field_types, contract=contract)
    if dry_run:
        return {"mode": "dry_run", "entity": entity_name, "fields": fields}
    resp = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        headers=feishu_headers(token),
        json={"fields": fields},
        timeout=20,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise MediaModelFeishuWriterError(f"failed to write {entity_name}: {result}")
    record = result.get("data", {}).get("record", {}) or {}
    return {
        "mode": "write",
        "entity": entity_name,
        "record_id": str(record.get("record_id") or ""),
        "fields": fields,
    }


def update_entity_record(
    entity_name: str,
    table_url: str,
    record_id: str,
    payload: dict[str, Any],
    *,
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    if not table_url or not record_id:
        raise MediaModelFeishuWriterError("table_url and record_id are required for update")
    app_token, table_id, token = feishu_bitable_refs(table_url)
    field_types = feishu_field_types(app_token, table_id, token)
    fields = prepare_entity_bitable_fields(entity_name, payload, field_types, contract=contract)
    resp = requests.put(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        json={"fields": fields},
        timeout=20,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise MediaModelFeishuWriterError(f"failed to update {entity_name}: {result}")
    return {
        "mode": "update",
        "entity": entity_name,
        "record_id": record_id,
        "fields": fields,
    }


def upsert_entity_record(
    entity_name: str,
    table_url: str,
    payload: dict[str, Any],
    *,
    key_field: str,
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    if not table_url:
        raise MediaModelFeishuWriterError("table_url is required for upsert")
    contract = contract or MediaModelContract()
    expected = str(payload.get(key_field) or "").strip()
    if not expected:
        raise MediaModelFeishuWriterError(f"{entity_name} upsert missing key field: {key_field}")
    feishu_key_field = contract.feishu_field_name(entity_name, key_field)
    for record in feishu_list_records(table_url, page_size=500):
        fields = record.get("fields") or {}
        if str(fields.get(feishu_key_field) or "").strip() == expected:
            return update_entity_record(entity_name, table_url, str(record.get("record_id") or ""), payload, contract=contract)
    return write_entity_record(entity_name, table_url, payload, contract=contract)


def read_entity_record(
    table_url: str,
    record_id: str,
) -> dict[str, Any]:
    if not table_url or not record_id:
        raise MediaModelFeishuWriterError("table_url and record_id are required for readback")
    app_token, table_id, token = feishu_bitable_refs(table_url)
    resp = requests.get(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        timeout=20,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise MediaModelFeishuWriterError(f"failed to read record {record_id}: {result}")
    return result.get("data", {}).get("record", {}) or {}


def _reject_option_ids(value: Any, *, field_label: str) -> None:
    if value in (None, "", []):
        return
    if isinstance(value, str):
        if OPTION_ID_RE.match(value.strip()):
            raise MediaModelFeishuWriterError(f"{field_label} contains Feishu option id instead of display value")
        return
    if isinstance(value, list):
        for item in value:
            _reject_option_ids(item, field_label=field_label)
        return
    if isinstance(value, dict):
        for item in value.values():
            _reject_option_ids(item, field_label=field_label)
