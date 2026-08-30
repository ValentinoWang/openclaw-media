#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.maintenance.reminder_runtime import (  # noqa: E402
    activity_config_path,
    load_reminder_module,
    reminder_script_path,
)

REMINDER_PATH = reminder_script_path()
ACTIVITY_CONFIG_PATH = activity_config_path()
DEFAULT_STATUS = "进行中"


def load_reminder() -> Any:
    return load_reminder_module(REMINDER_PATH, "openclaw_feishu_reminder_status_backfill")


def load_activity_config() -> dict[str, str]:
    if not ACTIVITY_CONFIG_PATH.is_file():
        raise SystemExit(
            f"missing required JSON config: {ACTIVITY_CONFIG_PATH}; "
            "set OPENCLAW_ACTIVITY_CONFIG_PATH"
        )
    data = json.loads(ACTIVITY_CONFIG_PATH.read_text(encoding="utf-8"))
    app_token = str(data.get("obj_token") or data.get("app_token") or "").strip()
    table_id = str(data.get("table_id") or "").strip()
    if not app_token or not table_id:
        raise RuntimeError(f"activity config missing obj_token/table_id: {ACTIVITY_CONFIG_PATH}")
    return {
        "app_token": app_token,
        "table_id": table_id,
        "url": str(data.get("url") or "").strip(),
    }


def backfill(*, dry_run: bool) -> dict[str, Any]:
    cfg = load_activity_config()
    reminder = load_reminder()
    token = reminder._tenant_token()
    reminder._ensure_fields(token, cfg["app_token"], cfg["table_id"], "活动")
    reminder._ensure_single_select_options(token, cfg["app_token"], cfg["table_id"], {"主状态": DEFAULT_STATUS})
    field_defs = reminder._field_definitions(token, cfg["app_token"], cfg["table_id"])
    records = reminder._iter_records(token, cfg["app_token"], cfg["table_id"])
    updates: list[dict[str, str]] = []
    for record in records:
        record_id = str(record.get("record_id") or "").strip()
        if not record_id:
            continue
        fields = reminder._decode_fields_for_read(dict(record.get("fields") or {}), field_defs)
        if str(fields.get("主状态") or "").strip():
            continue
        update = {"主状态": DEFAULT_STATUS}
        updates.append({"record_id": record_id, "title": str(fields.get("标题") or ""), "主状态": DEFAULT_STATUS})
        if dry_run:
            continue
        payload = reminder._coerce_fields_for_write(update, field_defs)
        reminder._expect_ok(
            reminder._request(
                "PUT",
                f"/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records/{record_id}",
                {"fields": payload},
                token=token,
            ),
            "backfill_activity_missing_main_status",
        )
    return {
        "ok": True,
        "dry_run": dry_run,
        "table_url": cfg["url"],
        "record_count": len(records),
        "updated_count": len(updates),
        "updated_records": updates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill missing 01_近期活动 主状态.")
    parser.add_argument("--apply", action="store_true", help="write updates to Feishu; default is dry-run")
    args = parser.parse_args()
    print(json.dumps(backfill(dry_run=not args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
