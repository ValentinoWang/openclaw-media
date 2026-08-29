"""Shared Douyin homepage/share-URL resolution helpers.

Consolidated from near-duplicate copies in resolver.py and anchor_crawler.py
(url-5 dedup audit). ``douyin_search_url`` keeps resolver.py's null-safe
guard (``str(keyword or "").strip()``); anchor_crawler.py's version would
raise ``TypeError`` on a ``None`` keyword.
"""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

import requests


DOUYIN_BLOCKED_PROFILE_PATHS = {"/user/self"}
DOUYIN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CHROMIUM_EXECUTABLE_CANDIDATES = (
    os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", ""),
    "/home/ubuntu/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome",
)


def launch_chromium(playwright, *, headless: bool = True):
    for candidate in CHROMIUM_EXECUTABLE_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return playwright.chromium.launch(headless=headless, executable_path=str(path))
    return playwright.chromium.launch(headless=headless)


def douyin_search_url(keyword: str) -> str:
    return f"https://www.douyin.com/search/{urllib.parse.quote(str(keyword or '').strip())}?type=user"


def is_douyin_self_profile_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url or ""))
    return parsed.netloc.endswith("douyin.com") and parsed.path.rstrip("/") in DOUYIN_BLOCKED_PROFILE_PATHS


def douyin_profile_url_from_redirect_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or ""))
    query = urllib.parse.parse_qs(parsed.query)
    sec_uid = ""
    if parsed.path.startswith("/share/user/"):
        sec_uid = parsed.path.rsplit("/", 1)[-1]
    if not sec_uid:
        sec_uid = str((query.get("sec_uid") or [""])[0]).strip()
    if sec_uid:
        return "https://www.douyin.com/user/" + sec_uid
    if parsed.netloc.endswith("douyin.com") and parsed.path.startswith("/user/") and not is_douyin_self_profile_url(url):
        return urllib.parse.urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path, "", "", ""))
    return ""


def resolve_douyin_share_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    direct = douyin_profile_url_from_redirect_url(raw)
    if direct:
        return direct
    if "v.douyin.com" not in raw and "iesdouyin.com/share/user" not in raw:
        return ""
    try:
        response = requests.get(raw, allow_redirects=True, headers={"User-Agent": DOUYIN_USER_AGENT}, timeout=20)
    except requests.RequestException:
        return ""
    return douyin_profile_url_from_redirect_url(response.url)
