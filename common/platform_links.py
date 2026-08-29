"""Canonical classification for user-supplied social-platform links.

This module deliberately performs no network requests. Short links remain
unexpanded so the polling adapter can resolve them with the correct identity.

``platform_for_url``/``classify_post_link`` cover the two platforms that need
post/profile/short-link kind detection (douyin, xiaohongshu) with the anti-
forgery hostname matching that ``test_hard_guards.py`` and
``test_creator_profile_enrichment.py`` lock down. ``platform_display_zh`` and
``platform_from_text`` extend host recognition to the remaining platforms
(公众号/TikTok/快手/B站/YouTube) purely for display-label purposes — those
platforms have no post/profile classification here because nothing in this
repo currently needs it; add to ``_DISPLAY_ONLY_HOSTS`` if that changes.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from selfmedia.ingest.content_flow.src.utils import extract_douyin_id


_PLATFORM_HOSTS = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com", "xhslink.cn"),
}
_SHORT_HOSTS = {"v.douyin.com": "douyin", "xhslink.com": "xiaohongshu"}
_POST_PATHS = {
    "douyin": ("/video/", "/note/"),
    "xiaohongshu": ("/explore/", "/discovery/item/"),
}
_PROFILE_PATHS = ("/user/profile/", "/user/")
_ID_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")

# Display-only platforms: recognized for Chinese-label purposes (content
# ingest classification, knowledge-base tagging) but not for post/profile
# kind detection. Consolidated from content_flow_client.py:299 and
# media_knowledge_fields.py:244, which were byte-identical seven-branch
# implementations.
_DISPLAY_ONLY_HOSTS = {
    "wechat_mp": ("mp.weixin.qq.com",),
    "tiktok": ("tiktok.com",),
    "kuaishou": ("kuaishou.com", "gifshow.com"),
    "bilibili": ("bilibili.com", "b23.tv"),
    "youtube": ("youtube.com", "youtu.be"),
}
PLATFORM_DISPLAY_ZH = {
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "wechat_mp": "公众号",
    "tiktok": "TikTok",
    "kuaishou": "快手",
    "bilibili": "B站",
    "youtube": "YouTube",
}
_URL_RE = re.compile(r"https?://[^\s，。；;、)）>]+")


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _platform_for_host(host: str) -> str:
    for platform, domains in _PLATFORM_HOSTS.items():
        if any(_host_matches(host, domain) for domain in domains):
            return platform
    return "unknown"


def platform_for_url(url: str) -> str:
    """Return the canonical platform key using the URL hostname only."""
    if not isinstance(url, str) or not url.strip():
        return "unknown"
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return "unknown"
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return "unknown"
    return _platform_for_host(parsed.hostname.lower().rstrip("."))


def _canonical(parsed: Any, *, platform: str, kind: str, content_id: str | None) -> str | None:
    if platform == "douyin" and kind == "post" and content_id:
        prefix = "/note/" if "/note/" in parsed.path else "/video/"
        return urlunsplit(("https", "www.douyin.com", f"{prefix}{content_id}", "", ""))
    if platform == "xiaohongshu" and kind == "post" and content_id:
        prefix = "/discovery/item/" if "/discovery/item/" in parsed.path else "/explore/"
        return urlunsplit(("https", "www.xiaohongshu.com", f"{prefix}{content_id}", "", ""))
    if parsed.scheme and parsed.netloc:
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))
    return None


def classify_post_link(url: str) -> dict[str, str | None]:
    """Classify a social link without resolving or fetching it.

    The returned platform is the existing internal key (``douyin`` or
    ``xiaohongshu``). ``kind`` is one of ``post``, ``profile``, ``short`` or
    ``unknown``. Unknown and short links never receive a guessed content ID.
    """

    result: dict[str, str | None] = {
        "platform": "unknown",
        "kind": "unknown",
        "content_id": None,
        "canonical_url": None,
    }
    if not isinstance(url, str) or not url.strip():
        return result
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return result
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return result

    host = parsed.hostname.lower().rstrip(".")
    platform = platform_for_url(url)
    if platform == "unknown":
        return result
    result["platform"] = platform

    short_platform = _SHORT_HOSTS.get(host)
    if short_platform:
        result["kind"] = "short"
        result["canonical_url"] = _canonical(parsed, platform=platform, kind="short", content_id=None)
        return result

    path = parsed.path if parsed.path.startswith("/") else f"/{parsed.path}"
    if any(path.startswith(prefix) for prefix in _PROFILE_PATHS):
        result["kind"] = "profile"
        result["canonical_url"] = _canonical(parsed, platform=platform, kind="profile", content_id=None)
        return result

    post_prefix = next((prefix for prefix in _POST_PATHS[platform] if path.startswith(prefix)), None)
    if post_prefix:
        raw_id = path[len(post_prefix) :].split("/", 1)[0]
        if not raw_id or not _ID_SEGMENT.fullmatch(raw_id):
            return result
        # Douyin's existing extractor also understands share/query forms;
        # preserve that source of truth when a normal post path is supplied.
        if platform == "douyin":
            extracted_kind, extracted_id = extract_douyin_id(url)
            content_id = extracted_id or raw_id
            if extracted_kind and extracted_kind not in {"video", "note"}:
                return result
        else:
            content_id = raw_id
        result["kind"] = "post"
        result["content_id"] = content_id
        result["canonical_url"] = _canonical(parsed, platform=platform, kind="post", content_id=content_id)
        return result

    result["canonical_url"] = _canonical(parsed, platform=platform, kind="unknown", content_id=None)
    return result


def platform_display_zh(url: str) -> str:
    """Return the Chinese display name for any recognized platform host.

    Covers douyin/xiaohongshu (via ``platform_for_url``) plus the five
    display-only platforms. Returns "" for an unrecognized or malformed URL —
    callers that need a different empty-value contract (e.g. "未知") should
    wrap this call, not reimplement host matching.
    """
    key = platform_for_url(url)
    if key != "unknown":
        return PLATFORM_DISPLAY_ZH[key]
    if not isinstance(url, str) or not url.strip():
        return ""
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower().rstrip(".")
    for platform, domains in _DISPLAY_ONLY_HOSTS.items():
        if any(_host_matches(host, domain) for domain in domains):
            return PLATFORM_DISPLAY_ZH[platform]
    return ""


def platform_from_text(text: str, *, wechat_keyword: bool = True) -> str:
    """Scan free text for a recognizable platform link or keyword.

    Extracts URLs from ``text`` and returns the Chinese display name of the
    first recognized platform host. When ``wechat_keyword`` is set (the
    default, matching the two callers this was consolidated from), the
    literal substring "公众号" is also treated as a 公众号 signal even without
    a matching URL — this preserves the original ``_knowledge_platform_from_text``
    behaviour; ``platform_for_url``-only callers should pass ``wechat_keyword=False``.
    """
    haystack = str(text or "")
    if wechat_keyword and "公众号" in haystack:
        return "公众号"
    for match in _URL_RE.findall(haystack):
        url = match.rstrip("，。；、.）)]】")
        display = platform_display_zh(url)
        if display:
            return display
    return ""


__all__ = [
    "PLATFORM_DISPLAY_ZH",
    "classify_post_link",
    "platform_display_zh",
    "platform_for_url",
    "platform_from_text",
]
