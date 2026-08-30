#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.activity_links import (  # noqa: E402
    canonical_link_url,
    link_field_name,
    normalize_link_items,
    split_link_fields,
)
from runtime.maintenance.reminder_runtime import (  # noqa: E402
    activity_config_path,
    daily_config_path,
    load_json,
    load_reminder_module,
    reminder_script_path,
)


REMINDER_PATH = reminder_script_path()
ACTIVITY_CONFIG_PATH = activity_config_path()
DAILY_CONFIG_PATH = daily_config_path()
TIMEZONE = "Asia/Shanghai"


def load_reminder() -> Any:
    return load_reminder_module(REMINDER_PATH, "openclaw_feishu_reminder_backfill")


# canonical_link_url / normalize_link_items / link_field_name /
# split_link_fields now live in common/activity_links.py (imported above)
# -- consolidated from this file and activity_daily.py's near-duplicate
# ActivityDailyMixin._activity_* methods, see the url-12 dedup audit.


def normalize_date(value: Any, *, base_year: int) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value) / 1000, tz=ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return ""
    text = text.replace("/", "-")
    iso = re.search(r"(?P<year>\d{4})-(?P<month>1[0-2]|0?[1-9])-(?P<day>3[01]|[12]\d|0?[1-9])", text)
    if iso:
        year = int(iso.group("year"))
        month = int(iso.group("month"))
        day = int(iso.group("day"))
        return f"{year:04d}-{month:02d}-{day:02d}"
    cn = re.search(r"(?:(?P<year>\d{4})年)?(?P<month>1[0-2]|0?[1-9])月(?P<day>3[01]|[12]\d|0?[1-9])(?:日|号)?", text)
    if cn:
        year = int(cn.group("year") or base_year)
        month = int(cn.group("month"))
        day = int(cn.group("day"))
        return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


EXPLICIT_BOOST_DATE_RE = re.compile(
    r"(?:冲榜日期|冲榜时间|冲刺榜单日期|集中投稿日期)\s*[:：]?\s*"
    r"(?P<date>(?:\d{4}[-/年])?\s*\d{1,2}[-/月]\s*(?:3[01]|[12]\d|0?[1-9])(?:日|号)?)"
)


def record_base_year(fields: dict[str, Any]) -> int:
    for value in (fields.get("创建时间"), fields.get("活动开始时间"), fields.get("活动结束时间")):
        normalized = normalize_date(value, base_year=datetime.now(ZoneInfo(TIMEZONE)).year)
        if normalized:
            return int(normalized[:4])
    return datetime.now(ZoneInfo(TIMEZONE)).year


def explicit_boost_date(fields: dict[str, Any]) -> str:
    base_year = record_base_year(fields)
    existing = normalize_date(fields.get("冲榜日期"), base_year=base_year)
    if existing:
        return existing
    source_text = "\n".join(
        str(fields.get(name) or "")
        for name in ("内容", "活动Brief", "填写要点", "参与方式", "提交要求", "活动时间")
        if fields.get(name)
    )
    match = EXPLICIT_BOOST_DATE_RE.search(source_text)
    if not match:
        return ""
    return normalize_date(match.group("date"), base_year=base_year)


def schedule_at(boost_date: str) -> datetime:
    tz = ZoneInfo(TIMEZONE)
    due = datetime.fromisoformat(boost_date).replace(tzinfo=tz, hour=9, minute=0, second=0, microsecond=0)
    return due - timedelta(days=1)


def create_schedule_record(reminder: Any, token: str, cfg: dict[str, Any], *, record_id: str, fields: dict[str, Any], boost_date: str) -> str:
    reminder_time = schedule_at(boost_date)
    now_ms = int(datetime.now(ZoneInfo(TIMEZONE)).timestamp() * 1000)
    title = f"冲榜提醒：{fields.get('标题') or '未命名活动'}"
    text = "\n".join(
        item
        for item in [
            f"活动：{fields.get('标题') or '未命名活动'}",
            f"冲榜日期：{boost_date}",
            f"活动记录ID：{record_id}",
            f"主话题：{fields.get('主话题') or ''}",
            f"参与方式：{fields.get('参与方式') or ''}",
        ]
        if item and not item.endswith("：")
    )
    schedule_fields = {
        "标题": title,
        "类型": "日程",
        "内容": text,
        "主状态": "未开始",
        "关联ID": f"{record_id}-boost",
        "创建时间": now_ms,
        "截止时间": int(reminder_time.timestamp() * 1000),
        "提醒时间": int(reminder_time.timestamp() * 1000),
        "本地路径": "",
        "已提醒": False,
    }
    reminder._ensure_fields(token, cfg["app_token"], cfg["table_id"], "日程")
    reminder._ensure_single_select_options(token, cfg["app_token"], cfg["table_id"], schedule_fields)
    field_defs = reminder._field_definitions(token, cfg["app_token"], cfg["table_id"])
    payload = reminder._coerce_fields_for_write(schedule_fields, field_defs)
    res = reminder._expect_ok(
        reminder._request(
            "POST",
            f"/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records",
            {"fields": payload},
            token=token,
        ),
        "create_activity_boost_schedule",
    )
    return str(((res.get("data") or {}).get("record") or {}).get("record_id") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill activity split links, boost date, and boost reminder schedules.")
    parser.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    args = parser.parse_args()

    reminder = load_reminder()
    token = reminder._tenant_token()
    activity_cfg = load_json(ACTIVITY_CONFIG_PATH, env_name="OPENCLAW_ACTIVITY_CONFIG_PATH")
    daily_cfg = load_json(DAILY_CONFIG_PATH, env_name="OPENCLAW_DAILY_CONFIG_PATH")

    reminder._ensure_fields(token, activity_cfg["app_token"], activity_cfg["table_id"], "活动")
    activity_field_defs = reminder._field_definitions(token, activity_cfg["app_token"], activity_cfg["table_id"])
    activity_records = reminder._iter_records(token, activity_cfg["app_token"], activity_cfg["table_id"])

    daily_records = reminder._iter_records(token, daily_cfg["app_token"], daily_cfg["table_id"])
    daily_field_defs = reminder._field_definitions(token, daily_cfg["app_token"], daily_cfg["table_id"])
    existing_schedule_refs = {
        str(reminder._decode_fields_for_read(record.get("fields") or {}, daily_field_defs).get("关联ID") or "")
        for record in daily_records
    }

    updated_activity_count = 0
    created_schedule_count = 0
    schedule_candidates = 0
    skipped_no_boost = 0

    for record in activity_records:
        record_id = str(record.get("record_id") or "")
        fields = reminder._decode_fields_for_read(record.get("fields") or {}, activity_field_defs)
        updates: dict[str, Any] = {}

        for field_name, value in split_link_fields(fields.get("Brief链接")).items():
            if not str(fields.get(field_name) or "").strip():
                updates[field_name] = value

        boost_date = explicit_boost_date(fields)
        if boost_date and not normalize_date(fields.get("冲榜日期"), base_year=record_base_year(fields)):
            updates["冲榜日期"] = boost_date
        if not boost_date:
            skipped_no_boost += 1

        if updates:
            updated_activity_count += 1
            if args.apply:
                payload = reminder._coerce_fields_for_write(updates, activity_field_defs)
                reminder._expect_ok(
                    reminder._request(
                        "PUT",
                        f"/bitable/v1/apps/{activity_cfg['app_token']}/tables/{activity_cfg['table_id']}/records/{record_id}",
                        {"fields": payload},
                        token=token,
                    ),
                    "update_activity_boost_backfill",
                )
                fields.update(updates)

        if boost_date:
            schedule_candidates += 1
            ref_id = f"{record_id}-boost"
            if ref_id not in existing_schedule_refs:
                created_schedule_count += 1
                if args.apply:
                    created_id = create_schedule_record(reminder, token, daily_cfg, record_id=record_id, fields=fields, boost_date=boost_date)
                    existing_schedule_refs.add(ref_id)
                    if created_id:
                        existing_schedule_refs.add(created_id)

    print(
        json.dumps(
            {
                "ok": True,
                "mode": "apply" if args.apply else "dry_run",
                "activity_record_count": len(activity_records),
                "updated_activity_count": updated_activity_count,
                "schedule_candidate_count": schedule_candidates,
                "created_schedule_count": created_schedule_count,
                "skipped_no_explicit_boost_date": skipped_no_boost,
                "activity_table": activity_cfg.get("url", ""),
                "daily_table": daily_cfg.get("url", ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
