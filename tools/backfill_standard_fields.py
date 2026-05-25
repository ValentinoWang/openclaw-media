from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.social_runtime import (
    FEISHU_BASE,
    feishu_bitable_refs,
    feishu_coerce_value,
    feishu_ensure_fields,
    feishu_field_types,
    feishu_headers,
    feishu_list_records,
    feishu_tenant_access_token,
)
from common.standard_fields import normalize_standard_fields, standard_field_specs


def prune_empty_value(value: Any) -> Any:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            pruned = prune_empty_value(item)
            if pruned in (None, "", [], {}):
                continue
            cleaned[key] = pruned
        return cleaned or None
    if isinstance(value, list):
        cleaned = []
        for item in value:
            pruned = prune_empty_value(item)
            if pruned in (None, "", [], {}):
                continue
            cleaned.append(pruned)
        return cleaned or None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def build_backfill_payload(fields: dict[str, Any], existing_field_types: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_standard_fields(fields)
    payload: dict[str, Any] = {}
    for key, value in normalized.items():
        value = prune_empty_value(value)
        if value in (None, "", [], {}):
            continue
        # Skip writes where the record already has a non-empty standardized value.
        existing_value = prune_empty_value(fields.get(key))
        if key in fields and existing_value not in (None, "", [], {}):
            continue
        if key not in existing_field_types and key not in standard_field_specs():
            continue
        payload[key] = value
    return payload


def update_record_once(
    app_token: str,
    table_id: str,
    record_id: str,
    payload: dict[str, Any],
    field_types: dict[str, Any],
    token: str,
) -> None:
    payload_fields: dict[str, Any] = {}
    existing = set(field_types)
    for key, value in payload.items():
        if key not in existing:
            continue
        coerced = feishu_coerce_value(value, field_types.get(key))
        if coerced in (None, []):
            continue
        payload_fields[key] = coerced
    if not payload_fields:
        return
    resp = requests.put(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        json={"fields": payload_fields},
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise RuntimeError(f"更新飞书记录失败：{result}")


def backfill_records(
    bitable_url: str,
    *,
    limit: int = 0,
    view_id: str = "",
    record_ids: set[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    token = feishu_tenant_access_token()
    app_token, table_id, token = feishu_bitable_refs(bitable_url, token)
    feishu_ensure_fields(app_token, table_id, token, standard_field_specs())
    existing_field_types = feishu_field_types(app_token, table_id, token)
    records = feishu_list_records(bitable_url, view_id=view_id, token=token, page_size=500)
    if record_ids:
        records = [item for item in records if str(item.get("record_id") or "") in record_ids]
    if limit > 0:
        records = records[:limit]

    touched: list[dict[str, Any]] = []
    for record in records:
        record_id = str(record.get("record_id") or "")
        fields = record.get("fields") or {}
        if not isinstance(fields, dict):
            continue
        payload = build_backfill_payload(fields, existing_field_types)
        if not payload:
            continue
        touched.append({"record_id": record_id, "field_count": len(payload), "fields": sorted(payload)})
        if not dry_run:
            update_record_once(
                app_token,
                table_id,
                record_id,
                payload,
                existing_field_types,
                token,
            )
    return {
        "ok": True,
        "dry_run": dry_run,
        "scanned": len(records),
        "updated": len(touched),
        "items": touched,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill standardized fields into existing Feishu bitable records.")
    parser.add_argument("--feishu-url", required=True, help="Feishu bitable URL.")
    parser.add_argument("--view-id", default="", help="Optional view id.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max record count.")
    parser.add_argument("--record-id", action="append", default=[], help="Optional record ids to backfill.")
    parser.add_argument("--write", action="store_true", help="Actually write to Feishu. Default is dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = backfill_records(
        args.feishu_url,
        limit=max(0, int(args.limit or 0)),
        view_id=str(args.view_id or ""),
        record_ids={item for item in args.record_id if item},
        dry_run=not args.write,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
