#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SELFMEDIA_ROOT = Path(__file__).resolve().parents[3]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import load_default_env_files  # noqa: E402
from runtime.maintenance.reminder_runtime import (  # noqa: E402
    activity_config_path,
    load_json,
    load_reminder_module,
    reminder_script_path,
)

REMINDER_PATH = reminder_script_path()
ACTIVITY_CONFIG_PATH = activity_config_path()


def load_reminder() -> Any:
    return load_reminder_module(REMINDER_PATH, "openclaw_feishu_reminder_platform_backfill")


def text_part(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "name", "value"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    if isinstance(value, list):
        return "、".join(part for part in (text_part(item) for item in value) if part)
    return str(value).strip()


def looks_like_bitable_option_id(value: str) -> bool:
    return bool(re.fullmatch(r"opt[A-Za-z0-9]{6,}", str(value or "").strip()))


def normalize_platform_names(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    names: list[str] = []

    def add_name(raw: Any) -> None:
        text = text_part(raw)
        if not text:
            return
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                for item in parsed:
                    add_name(item)
                return
        for part in re.split(r"[、,，\n]+", text):
            part = part.strip()
            if not part:
                continue
            if part.startswith("["):
                try:
                    parsed = json.loads(part)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    for item in parsed:
                        add_name(item)
                    continue
            if looks_like_bitable_option_id(part):
                continue
            if part and part not in names:
                names.append(part)

    if isinstance(value, list):
        for item in value:
            add_name(item)
    else:
        add_name(value)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill 01_近期活动 平台名称 to Feishu multi-select option values.")
    parser.add_argument("--apply", action="store_true", help="write schema and record changes; default is dry-run")
    args = parser.parse_args()

    load_default_env_files()
    reminder = load_reminder()
    token = reminder._tenant_token()
    activity_cfg = load_json(ACTIVITY_CONFIG_PATH, env_name="OPENCLAW_ACTIVITY_CONFIG_PATH")
    app_token = activity_cfg["app_token"]
    table_id = activity_cfg["table_id"]

    old_field_defs = reminder._field_definitions(token, app_token, table_id)
    old_records = reminder._iter_records(token, app_token, table_id)
    normalized_by_record: dict[str, list[str]] = {}
    all_names: list[str] = []
    for record in old_records:
        record_id = str(record.get("record_id") or "")
        fields = reminder._decode_fields_for_read(record.get("fields") or {}, old_field_defs)
        normalized = normalize_platform_names(fields.get("平台名称"))
        if record_id and normalized:
            normalized_by_record[record_id] = normalized
            for name in normalized:
                if name not in all_names:
                    all_names.append(name)

    if args.apply:
        reminder._ensure_fields(token, app_token, table_id, "活动")
        reminder._ensure_single_select_options(token, app_token, table_id, {"平台名称": all_names})

    current_field_defs = reminder._field_definitions(token, app_token, table_id)
    current_platform_type = int((current_field_defs.get("平台名称") or {}).get("type") or 0)
    current_records = reminder._iter_records(token, app_token, table_id)
    updates: list[dict[str, Any]] = []
    for record in current_records:
        record_id = str(record.get("record_id") or "")
        target = normalized_by_record.get(record_id, [])
        if not record_id or not target:
            continue
        current_fields = reminder._decode_fields_for_read(record.get("fields") or {}, current_field_defs)
        current = normalize_platform_names(current_fields.get("平台名称"))
        if current != target:
            updates.append({"record_id": record_id, "平台名称": target})

    if args.apply:
        for item in updates:
            payload = reminder._coerce_fields_for_write({"平台名称": item["平台名称"]}, current_field_defs)
            reminder._expect_ok(
                reminder._request(
                    "PUT",
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{item['record_id']}",
                    {"fields": payload},
                    token=token,
                ),
                "backfill_activity_platform_name_multiselect",
            )

    print(
        json.dumps(
            {
                "ok": True,
                "mode": "apply" if args.apply else "dry_run",
                "activity_record_count": len(current_records),
                "records_with_platform_name": len(normalized_by_record),
                "update_count": len(updates),
                "platform_option_count": len(all_names),
                "platform_options": all_names,
                "platform_name_field_type": current_platform_type,
                "activity_table": activity_cfg.get("url", ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
