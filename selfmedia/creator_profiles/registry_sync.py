#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SELFMEDIA_ROOT = Path(__file__).resolve().parents[2]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.platform_labels import normalize_platform_zh  # noqa: E402
from common.social_runtime import feishu_plain_text  # noqa: E402


def normalize_text(value: Any) -> str:
    return feishu_plain_text(value).strip()


def normalize_platform(value: Any) -> str:
    # Consolidated into common/platform_labels.py (H8). This used to be a
    # narrower inline alias set (xiaohongshu/xhs/rednote -> 小红书,
    # douyin/tiktok -> 抖音) that silently disagreed with
    # creator_profiles/schemas.py's own normalize_platform -- both now read
    # from the same merged alias table.
    return normalize_platform_zh(normalize_text(value))


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
