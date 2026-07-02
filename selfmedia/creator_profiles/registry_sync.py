#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SELFMEDIA_ROOT = Path(__file__).resolve().parents[2]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import (  # noqa: E402
    feishu_list_records,
    feishu_plain_text,
    feishu_tenant_access_token,
    feishu_update_record,
)
from common.standard_fields import standard_field_specs  # noqa: E402


DEFAULT_CREATOR_REGISTRY_URL = (
    "https://tcnwueberajc.feishu.cn/wiki/WYaCwyPxpiYM02kzclJcJPC9n9b"
    "?table=tbli9yjd7DtTjqcV&view=vewxOPQ7ei"
)
DEFAULT_BUSINESS_URL = (
    "https://tcnwueberajc.feishu.cn/base/BazubRWJ7a9SLRsLr4Bc8IvAnCg?table=tbld333H01u34g9F"
)


def normalize_text(value: Any) -> str:
    return feishu_plain_text(value).strip()


def normalize_platform(value: Any) -> str:
    text = normalize_text(value)
    lowered = text.lower()
    if lowered in {"xiaohongshu", "xhs", "rednote"}:
        return "小红书"
    if lowered in {"douyin", "tiktok"}:
        return "抖音"
    return text


def normalize_platform_id(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text


def parse_fans_k(value: Any) -> int | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        return int(round(float(text) * 1000))
    except ValueError:
        return None


def join_tags(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    return normalize_text(value)


def is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def build_creator_index(records: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    by_platform_id: dict[tuple[str, str], dict[str, Any]] = {}
    by_name: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        fields = record.get("fields") or {}
        if not isinstance(fields, dict):
            continue
        platform = normalize_platform(fields.get("平台"))
        creator_ip = normalize_text(fields.get("博主IP"))
        native_id = normalize_platform_id(fields.get("平台ID"))
        if platform and native_id:
            by_platform_id[(platform, native_id)] = record
        if platform and creator_ip:
            by_name[(platform, creator_ip)] = record
    return by_platform_id, by_name


def find_creator_record(
    business_fields: dict[str, Any],
    by_platform_id: dict[tuple[str, str], dict[str, Any]],
    by_name: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    platform = normalize_platform(business_fields.get("平台"))
    business_platform_id = normalize_platform_id(business_fields.get("平台ID") or business_fields.get("平台账号ID"))
    if platform and business_platform_id:
        match = by_platform_id.get((platform, business_platform_id))
        if match:
            return match, "platform+platform_id"
    for key_name in ("作者ID", "账号名称", "博主IP"):
        candidate_name = normalize_text(business_fields.get(key_name))
        if platform and candidate_name:
            match = by_name.get((platform, candidate_name))
            if match:
                return match, f"platform+{key_name}"
    return None, ""


def build_update_payload(business_fields: dict[str, Any], creator_fields: dict[str, Any]) -> dict[str, Any]:
    creator_ip = normalize_text(creator_fields.get("博主IP"))
    payload: dict[str, Any] = {}

    for target, source in (
        ("博主IP", creator_ip),
        ("院校背景", normalize_text(creator_fields.get("院校背景"))),
        ("关键词标签", join_tags(creator_fields.get("关键词标签") or creator_fields.get("标签"))),
        ("赛道", join_tags(creator_fields.get("赛道"))),
    ):
        if source and is_empty(business_fields.get(target)):
            payload[target] = source

    fans = parse_fans_k(creator_fields.get("粉丝数(k)"))
    if fans is not None and is_empty(business_fields.get("粉丝数")):
        payload["粉丝数"] = fans

    return payload


def sync_creator_registry(
    creator_url: str,
    business_url: str,
    *,
    limit: int = 0,
    record_ids: set[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    token = feishu_tenant_access_token()
    creator_records = feishu_list_records(creator_url, token=token, page_size=500)
    business_records = feishu_list_records(business_url, token=token, page_size=500)
    if record_ids:
        business_records = [item for item in business_records if str(item.get("record_id") or "") in record_ids]
    if limit > 0:
        business_records = business_records[:limit]

    by_platform_id, by_name = build_creator_index(creator_records)
    touched: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for record in business_records:
        record_id = str(record.get("record_id") or "")
        fields = record.get("fields") or {}
        if not isinstance(fields, dict):
            continue
        creator_record, reason = find_creator_record(fields, by_platform_id, by_name)
        if not creator_record:
            unmatched.append(record_id)
            continue
        payload = build_update_payload(fields, creator_record.get("fields") or {})
        if not payload:
            continue
        touched.append(
            {
                "record_id": record_id,
                "match_reason": reason,
                "field_count": len(payload),
                "fields": sorted(payload),
            }
        )
        if not dry_run:
            feishu_update_record(
                business_url,
                record_id,
                payload,
                specs=standard_field_specs(),
                token=token,
            )
    return {
        "ok": True,
        "dry_run": dry_run,
        "scanned": len(business_records),
        "matched": len(touched),
        "unmatched": len(unmatched),
        "items": touched,
        "unmatched_record_ids": unmatched[:50],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync creator registry fields into 商务-ID records.")
    parser.add_argument("--creator-url", default=DEFAULT_CREATOR_REGISTRY_URL, help="Creator registry table URL.")
    parser.add_argument("--business-url", default=DEFAULT_BUSINESS_URL, help="商务-ID table URL.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max record count.")
    parser.add_argument("--record-id", action="append", default=[], help="Optional record ids to sync.")
    parser.add_argument("--write", action="store_true", help="Actually write to Feishu. Default is dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = sync_creator_registry(
        args.creator_url,
        args.business_url,
        limit=max(0, int(args.limit or 0)),
        record_ids={item for item in args.record_id if item},
        dry_run=not args.write,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
