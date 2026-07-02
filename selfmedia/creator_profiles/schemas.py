from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


CREATOR_PROFILE_FIELDS = (
    "creator_profile_id",
    "platform",
    "author_id",
    "account_name",
    "profile_url",
    "identity_summary",
    "identity_tags",
    "education_background",
    "expertise_domains",
    "creator_role",
    "public_persona_boundaries",
    "story_usable_identity_points",
    "current_metrics_summary",
)

SEMANTIC_FIELDS = (
    "identity_summary",
    "identity_tags",
    "education_background",
    "expertise_domains",
    "creator_role",
    "public_persona_boundaries",
    "story_usable_identity_points",
)

LIST_FIELDS = {"identity_tags", "expertise_domains"}

PLATFORM_ALIASES = {
    "douyin": "抖音",
    "抖音": "抖音",
    "xhs": "小红书",
    "xiaohongshu": "小红书",
    "小红书": "小红书",
}

PLATFORM_SLUGS = {
    "抖音": "douyin",
    "小红书": "xhs",
}

ID_TYPE_ALIASES = {
    "抖音号": "douyin_display_id",
    "douyin": "douyin_display_id",
    "douyin_display_id": "douyin_display_id",
    "小红书号": "xhs_display_id",
    "xhs": "xhs_display_id",
    "xhs_display_id": "xhs_display_id",
}


def now_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def normalize_platform(value: Any) -> str:
    text = str(value or "").strip()
    return PLATFORM_ALIASES.get(text.lower(), PLATFORM_ALIASES.get(text, text))


def platform_slug(value: Any) -> str:
    platform = normalize_platform(value)
    return PLATFORM_SLUGS.get(platform, str(value or "unknown").strip().lower() or "unknown")


def normalize_id_type(value: Any, *, platform: str = "") -> str:
    text = str(value or "").strip()
    if text:
        return ID_TYPE_ALIASES.get(text.lower(), ID_TYPE_ALIASES.get(text, text))
    if normalize_platform(platform) == "抖音":
        return "douyin_display_id"
    if normalize_platform(platform) == "小红书":
        return "xhs_display_id"
    return "unknown"


def creator_profile_id(platform: str, author_id: str) -> str:
    return f"creator_{platform_slug(platform)}_{safe_key_part(author_id)}"


def safe_key_part(value: Any) -> str:
    text = str(value or "").strip().lower()
    result = []
    for char in text:
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            result.append(char)
        else:
            result.append("_")
    key = "".join(result).strip("_")
    return key or "unknown"


def compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}
