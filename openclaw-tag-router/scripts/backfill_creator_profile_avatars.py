#!/usr/bin/env python3
"""Backfill missing CreatorProfile avatars from authenticated profile pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.social_runtime import (  # noqa: E402
    feishu_list_records,
    feishu_plain_text,
    feishu_update_record,
    load_default_env_files,
)
from selfmedia.creator_profiles.extractor import normalize_public_http_url  # noqa: E402
from selfmedia.creator_profiles.resolver import (  # noqa: E402
    resolve_douyin_profile,
    resolve_xiaohongshu_profile,
)
from selfmedia.creator_profiles.schemas import normalize_platform  # noqa: E402


DEFAULT_TABLE_URL = (
    "https://tcnwueberajc.feishu.cn/base/OmjkbgBkwa2JEysEN8uc5PMhnTb"
    "?table=tblBrERiQnWvZFwp"
)
AVATAR_FIELD_SPECS = {"头像链接": 15}
SUPPORTED_PLATFORMS = {"抖音", "小红书"}
AUTH_FAILURE_STATUSES = {"missing_cookies", "capture_auth_required", "capture_access_restricted"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="write verified avatars; default is dry-run")
    parser.add_argument("--table-url", default=DEFAULT_TABLE_URL)
    parser.add_argument("--platform", choices=("douyin", "xiaohongshu", "抖音", "小红书"))
    parser.add_argument("--record-id", help="process one Feishu record id")
    parser.add_argument("--creator-profile-id", help="process one creator profile id")
    parser.add_argument("--report", type=Path, help="write the redacted JSON report to this path")
    return parser.parse_args()


def platform_filter(value: str | None) -> str:
    aliases = {"douyin": "抖音", "xiaohongshu": "小红书"}
    return aliases.get(str(value or "").strip(), str(value or "").strip())


def text_field(fields: dict[str, Any], *names: str) -> str:
    for name in names:
        value = feishu_plain_text(fields.get(name)).strip()
        if value:
            return value
    return ""


def avatar_fingerprint(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {
        "avatar_host": (parsed.hostname or "").lower(),
        "avatar_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
    }


def resolve_avatar(platform: str, author_id: str, account_name: str, profile_url: str) -> dict[str, Any]:
    if platform == "抖音":
        return resolve_douyin_profile(
            platform_id=author_id,
            id_type="douyin_display_id",
            url=profile_url,
            creator_name=account_name,
        )
    if platform == "小红书":
        return resolve_xiaohongshu_profile(
            platform_id=author_id,
            url=profile_url,
            creator_name=account_name,
        )
    raise ValueError(f"unsupported platform: {platform}")


def selected_records(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    expected_platform = platform_filter(args.platform)
    selected = []
    for record in records:
        fields = record.get("fields") or {}
        if args.record_id and record.get("record_id") != args.record_id:
            continue
        if args.creator_profile_id and text_field(fields, "达人档案ID") != args.creator_profile_id:
            continue
        if expected_platform and normalize_platform(text_field(fields, "平台")) != expected_platform:
            continue
        selected.append(record)
    if (args.record_id or args.creator_profile_id) and not selected:
        raise RuntimeError("the requested CreatorProfile record was not found")
    return selected


def readback_avatar(table_url: str, record_id: str) -> str:
    for record in feishu_list_records(table_url):
        if record.get("record_id") == record_id:
            return text_field(record.get("fields") or {}, "头像链接")
    raise RuntimeError("record disappeared during write readback")


def process_record(
    record: dict[str, Any],
    *,
    table_url: str,
    execute: bool,
    resolver: Callable[[str, str, str, str], dict[str, Any]] = resolve_avatar,
) -> dict[str, Any]:
    fields = record.get("fields") or {}
    record_id = str(record.get("record_id") or "").strip()
    creator_profile_id = text_field(fields, "达人档案ID")
    platform = normalize_platform(text_field(fields, "平台"))
    author_id = text_field(fields, "作者ID", "平台ID")
    account_name = text_field(fields, "账号名称", "博主IP")
    profile_url = text_field(fields, "主页链接")
    existing_avatar = text_field(fields, "头像链接")
    result: dict[str, Any] = {
        "record_id": record_id,
        "creator_profile_id": creator_profile_id,
        "platform": platform,
        "author_id": author_id,
    }

    if existing_avatar:
        return {**result, "status": "skipped_existing_avatar", **avatar_fingerprint(existing_avatar)}
    if not record_id or not creator_profile_id or platform not in SUPPORTED_PLATFORMS or not author_id or not account_name:
        return {**result, "status": "blocked_invalid_record_identity"}

    resolved = resolver(platform, author_id, account_name, profile_url)
    resolve_status = str(resolved.get("resolve_status") or "unknown")
    if not resolved.get("ok"):
        status = "blocked_cookie_invalid" if resolve_status in AUTH_FAILURE_STATUSES else "blocked_profile_resolution"
        return {**result, "status": status, "resolve_status": resolve_status}
    if normalize_platform(str(resolved.get("platform") or platform)) != platform:
        return {**result, "status": "blocked_platform_mismatch", "resolve_status": resolve_status}
    resolved_author_id = str(resolved.get("resolved_author_id") or "").strip()
    if not resolved_author_id or resolved_author_id != author_id:
        return {
            **result,
            "status": "blocked_author_id_mismatch",
            "resolve_status": resolve_status,
            "resolved_author_id": resolved_author_id,
        }
    extracted = resolved.get("extracted_profile") or {}
    avatar_url = normalize_public_http_url(extracted.get("avatar_url"))
    if not avatar_url:
        return {**result, "status": "blocked_avatar_missing", "resolve_status": resolve_status}

    redacted = {**result, "resolve_status": resolve_status, **avatar_fingerprint(avatar_url)}
    if not execute:
        return {**redacted, "status": "dry_run_would_write"}

    # Recheck immediately before writing so concurrent/manual population is never overwritten.
    current_avatar = readback_avatar(table_url, record_id)
    if current_avatar:
        return {**result, "status": "skipped_existing_avatar_after_resolution", **avatar_fingerprint(current_avatar)}
    feishu_update_record(
        table_url,
        record_id,
        {"头像链接": avatar_url},
        specs=AVATAR_FIELD_SPECS,
    )
    persisted = readback_avatar(table_url, record_id)
    if persisted != avatar_url:
        raise RuntimeError(f"avatar write readback mismatch for {record_id}")
    return {**redacted, "status": "written_verified"}


def main() -> int:
    args = parse_args()
    load_default_env_files()
    records = selected_records(feishu_list_records(args.table_url), args)
    outcomes: list[dict[str, Any]] = []
    for record in records:
        try:
            outcomes.append(process_record(record, table_url=args.table_url, execute=args.execute))
        except Exception as exc:
            fields = record.get("fields") or {}
            outcomes.append(
                {
                    "record_id": str(record.get("record_id") or ""),
                    "creator_profile_id": text_field(fields, "达人档案ID"),
                    "status": "failed_exception",
                    "error_type": type(exc).__name__,
                }
            )
    counts: dict[str, int] = {}
    for outcome in outcomes:
        status = str(outcome["status"])
        counts[status] = counts.get(status, 0) + 1
    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "execute" if args.execute else "dry_run",
        "selected": len(outcomes),
        "counts": counts,
        "outcomes": outcomes,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    failed = any(str(item["status"]).startswith(("blocked_", "failed_")) for item in outcomes)
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
