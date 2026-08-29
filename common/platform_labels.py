"""Consolidated platform enum / alias / label tables (H8 dedup cluster).

This module merges the alias -> canonical-value tables that used to be
duplicated (with small, silent divergences) across:

  - openclaw-tag-router/openclaw_app/services/media_web_tasks_core.py
    (MATERIAL_PLATFORM_ALIASES / MATERIAL_PLATFORM_LABELS, English slug as
    canonical value)
  - selfmedia/creator_profiles/schemas.py (PLATFORM_ALIASES / PLATFORM_SLUGS)
  - selfmedia/review/data_review.py (normalize_platform_tags's local mapping)
  - selfmedia/hotlist/service.py (_normalize_platform's inline branches)
  - selfmedia/creation/field_contract.py (PLATFORM_ALIASES)
  - selfmedia/creator_profiles/registry_sync.py (normalize_platform's inline
    branches)

Two DELIBERATELY separate tables are kept because they serve different
audiences with different, already-conflicting canonical spellings for the
same platform (see PLATFORM_LABELS docstring for the bilibili example):

  - PLATFORM_ALIASES / normalize_platform_zh: canonicalizes to the CHINESE
    display value used by the creator-profile / field-contract / data-review
    / hotlist business logic (schemas.py, field_contract.py, data_review.py,
    hotlist/service.py, registry_sync.py all agree on Chinese canonical
    values, so that is the consolidation line taken here).
  - PLATFORM_LABELS / normalize_platform_slug: canonicalizes to the ENGLISH
    slug used by media_web_tasks_core.py's own material-parsing logic
    (which never learned a Chinese "B站" spelling for bilibili -- it only
    knows the slug "bilibili" with a "哔哩哔哩" display label).

Known, deliberately-preserved divergences (do not "fix" these by merging
the tables further -- see H8 audit notes):

  - Canonical Chinese value for bilibili/b站/哔哩哔哩 is "B站" (matches
    field_contract.py and data_review.py, the two call sites that carry a
    Chinese canonical value for this platform); media_web_tasks_core.py's
    own display label for the "bilibili" slug independently stays
    "哔哩哔哩" (PLATFORM_LABELS is left byte-identical to the original
    MATERIAL_PLATFORM_LABELS table).
  - "视频号" (channels) and "B站" have no English slug in
    media_web_tasks_core.py's 9-slug universe (it never grew a "channels"
    or "bilibili"-as-B站 concept) -- normalize_platform_slug("视频号")
    intentionally falls back to "unknown" rather than inventing a slug.
  - "小红书" has two slug spellings in the wild: media_web_tasks_core.py
    uses "xiaohongshu"; selfmedia/creator_profiles/schemas.py uses "xhs"
    (and that spelling is baked into already-generated creator_profile_id
    values, so it is NOT changed here). PLATFORM_SLUGS below picks
    "xiaohongshu" as canonical going forward; LEGACY_SLUG_ALIASES plus
    canonicalize_slug() are the compatibility bridge back to "xhs" for
    callers that still need to recognize it.
"""

from __future__ import annotations

from typing import Any

# alias (English token or Chinese spelling, arbitrary case) -> canonical
# Chinese display value. Merged from schemas.py, data_review.py,
# hotlist/service.py, field_contract.py and registry_sync.py.
PLATFORM_ALIASES: dict[str, str] = {
    # 抖音 / Douyin / TikTok
    "douyin": "抖音",
    "抖音": "抖音",
    "dy": "抖音",
    "巨量": "抖音",
    "tiktok": "抖音",
    # 小红书 / Xiaohongshu / RedNote
    "xhs": "小红书",
    "xiaohongshu": "小红书",
    "小红书": "小红书",
    "rednote": "小红书",
    # 视频号 / WeChat Channels
    "视频号": "视频号",
    "wechat_channels": "视频号",
    "wechat channel": "视频号",
    # B站 / bilibili -- canonical spelling "B站" (matches field_contract.py
    # and data_review.py, the two Chinese-canonical call sites that know
    # this platform at all)
    "bilibili": "B站",
    "b站": "B站",
    "哔哩哔哩": "B站",
    "B站": "B站",
    # 微信
    "wechat": "微信",
    "微信": "微信",
    # 微博
    "weibo": "微博",
    "微博": "微博",
    # 知乎
    "zhihu": "知乎",
    "知乎": "知乎",
    # 快手
    "kuaishou": "快手",
    "快手": "快手",
    # web / unknown pseudo-platforms (media_web_tasks_core.py's own spelling)
    "web": "普通网页",
    "普通网页": "普通网页",
    "unknown": "其他或未知平台",
    "其他或未知平台": "其他或未知平台",
}

# Chinese canonical value -> English slug, for callers (media_web_tasks_core
# and friends) that key their own logic off the English slug rather than the
# Chinese display value. Deliberately does NOT cover every PLATFORM_ALIASES
# value: "视频号" has no established slug (see module docstring).
PLATFORM_SLUGS: dict[str, str] = {
    "抖音": "douyin",
    "小红书": "xiaohongshu",
    "快手": "kuaishou",
    "B站": "bilibili",
    "哔哩哔哩": "bilibili",
    "微信": "wechat",
    "微博": "weibo",
    "知乎": "zhihu",
    "普通网页": "web",
    "其他或未知平台": "unknown",
}

# English slug -> Chinese display label. Byte-identical to
# media_web_tasks_core.py's original MATERIAL_PLATFORM_LABELS -- this is the
# backend display table; the frontend keeps its own independent copy in
# openclaw-bot-center/src/media/ui/platformRegistry.ts (not touched here).
PLATFORM_LABELS: dict[str, str] = {
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "kuaishou": "快手",
    "bilibili": "哔哩哔哩",
    "wechat": "微信",
    "weibo": "微博",
    "zhihu": "知乎",
    "web": "普通网页",
    "unknown": "其他或未知平台",
}

# Legacy slug spellings that must still resolve to a current canonical slug.
# "xhs" is the slug selfmedia/creator_profiles/schemas.py has already baked
# into generated creator_profile_id values -- it is NOT renamed to
# "xiaohongshu" there; this is purely a read-side compatibility bridge for
# other callers that may encounter the old spelling.
LEGACY_SLUG_ALIASES: dict[str, str] = {
    "xhs": "xiaohongshu",
}


def canonicalize_slug(slug: Any) -> str:
    """Translate a legacy platform slug (e.g. "xhs") to its current form.

    Unknown / non-legacy input is returned lowercased and stripped,
    unchanged otherwise.
    """
    text = str(slug or "").strip().lower()
    return LEGACY_SLUG_ALIASES.get(text, text)


def normalize_platform_zh(value: Any) -> str:
    """Alias / slug -> canonical Chinese platform display value.

    Mirrors the lookup pattern already used by
    selfmedia/creator_profiles/schemas.py's normalize_platform: try the
    lowercased form, then the original (stripped) form, and if neither is a
    known alias, return the original text unchanged. This matches the
    "not found" behavior of every merged call site except
    selfmedia/hotlist/service.py (which raises on an unrecognized platform)
    and openclaw-tag-router's media_web_tasks_core.py (which needs a `None`
    sentinel) -- both of those wrap this function rather than relying on its
    fallback value.
    """
    text = str(value or "").strip()
    if not text:
        return text
    compact = text.lower()
    return PLATFORM_ALIASES.get(compact, PLATFORM_ALIASES.get(text, text))


def normalize_platform_slug(value: Any) -> str:
    """Alias / Chinese canonical / legacy slug -> English platform slug.

    Returns "unknown" when the input cannot be resolved to one of
    PLATFORM_LABELS' slugs (this includes platforms such as "视频号" that
    have no slug in that table at all).
    """
    text = str(value or "").strip()
    if not text:
        return "unknown"
    compact = text.lower()
    if compact in PLATFORM_LABELS:
        return compact
    if compact in LEGACY_SLUG_ALIASES:
        return LEGACY_SLUG_ALIASES[compact]
    zh = normalize_platform_zh(text)
    return PLATFORM_SLUGS.get(zh, "unknown")
