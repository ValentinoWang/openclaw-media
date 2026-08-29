"""Canonical classification for user-supplied social-platform links.

This module deliberately performs no network requests. Short links remain
unexpanded so the polling adapter can resolve them with the correct identity.
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


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _platform_for_host(host: str) -> str:
    for platform, domains in _PLATFORM_HOSTS.items():
        if any(_host_matches(host, domain) for domain in domains):
            return platform
    return "unknown"


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
    platform = _platform_for_host(host)
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


__all__ = ["classify_post_link"]
