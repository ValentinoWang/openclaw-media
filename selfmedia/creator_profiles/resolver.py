from __future__ import annotations

import os
import base64
import re
import urllib.parse
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .extractor import merge_profile_facts, parse_douyin_embedded_profile_data, parse_douyin_profile_text
from .schemas import normalize_platform
from selfmedia.business.id_business import load_playwright_cookies


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


def douyin_profile_links(page) -> list[dict[str, str]]:
    try:
        return page.eval_on_selector_all(
            "a",
            """
            els => els
              .map(a => ({text: (a.innerText || "").trim(), href: a.href || ""}))
              .filter(item => item.href.includes("douyin.com/user/") && item.text)
            """,
        )
    except Exception:
        return []


def choose_douyin_candidate(candidates: list[dict[str, str]], *, creator_name: str, platform_id: str) -> dict[str, str] | None:
    creator_name = str(creator_name or "").strip()
    platform_id = str(platform_id or "").strip()
    usable = [
        item
        for item in candidates
        if not is_douyin_self_profile_url(str(item.get("href") or ""))
        and str(item.get("text") or "").strip() not in {"我的", "客户端"}
    ]
    for item in usable:
        text = str(item.get("text") or "")
        if platform_id and platform_id in text and creator_name and creator_name in text:
            return item
    for item in usable:
        text = str(item.get("text") or "")
        if platform_id and platform_id in text:
            return item
    return None


def capture_screenshot_bytes(page) -> tuple[bytes, str]:
    try:
        return page.screenshot(full_page=False, timeout=20_000, animations="disabled"), ""
    except Exception as exc:
        first_error = str(exc)
    try:
        return page.screenshot(full_page=False, timeout=20_000), ""
    except Exception as exc:
        second_error = str(exc)
    try:
        session = page.context.new_cdp_session(page)
        payload = session.send("Page.captureScreenshot", {"format": "png", "fromSurface": True, "captureBeyondViewport": False})
        data = str(payload.get("data") or "")
        if data:
            return base64.b64decode(data), ""
    except Exception as exc:
        return b"", str(exc)
    return b"", second_error or first_error


def open_douyin_profile_candidate(page, url: str, *, platform_id: str, creator_name: str, source: str) -> dict[str, Any]:
    if not url:
        return {"ok": False, "platform": "抖音", "resolve_status": "missing_profile_url", "source": source}
    if is_douyin_self_profile_url(url):
        return {
            "ok": False,
            "platform": "抖音",
            "resolve_status": "blocked_self_profile",
            "resolved_profile_url": url,
            "source": source,
            "input_platform_id": platform_id,
        }
    goto_error = ""
    try:
        page.goto(url, wait_until="commit", timeout=30_000)
    except PlaywrightTimeoutError as exc:
        goto_error = str(exc)
    page.wait_for_timeout(8_000)
    final_url = page.url
    if is_douyin_self_profile_url(final_url):
        return {
            "ok": False,
            "platform": "抖音",
            "resolve_status": "blocked_self_profile",
            "resolved_profile_url": final_url,
            "source": source,
            "input_platform_id": platform_id,
        }
    title = page.title()
    try:
        body = page.locator("body").inner_text(timeout=5_000)
    except Exception:
        body = ""
    try:
        raw_dom = page.content()
    except Exception:
        raw_dom = ""
    screenshot_bytes, screenshot_error = capture_screenshot_bytes(page)
    parsed = parse_douyin_profile_text(body, final_url, title=title)
    parsed = merge_profile_facts(parsed, parse_douyin_embedded_profile_data(raw_dom, platform_id))
    if not body and goto_error:
        return {
            "ok": False,
            "platform": "抖音",
            "resolve_status": "timeout",
            "error": goto_error,
            "resolved_profile_url": url,
            "source": source,
            "input_platform_id": platform_id,
        }
    if str(parsed.get("author_id") or "") != str(platform_id):
        return {
            "ok": False,
            "platform": "抖音",
            "resolve_status": "blocked_no_exact_id_match",
            "resolved_profile_url": final_url,
            "title": title,
            "rendered_text": body,
            "raw_dom": raw_dom,
            "input_platform_id": platform_id,
            "source": source,
            "parsed_author_id": parsed.get("author_id", ""),
            "extracted_profile": parsed,
        }
    parsed.update({"platform": "抖音", "profile_url": final_url})
    return {
        "ok": True,
        "platform": "抖音",
        "resolve_status": "exact_profile_resolved",
        "source": source,
        "input_platform_id": platform_id,
        "input_platform_id_type": "douyin_display_id",
        "resolved_author_id": platform_id,
        "resolved_author_id_type": "douyin_display_id",
        "resolved_profile_url": final_url,
        "account_name": parsed.get("account_name") or creator_name,
        "title": title,
        "rendered_text": body,
        "raw_dom": raw_dom,
        "screenshot_bytes": screenshot_bytes,
        "screenshot_error": screenshot_error,
        "extracted_profile": parsed,
        "success_evidence": [f"public rendered text includes 抖音号：{platform_id}"],
    }


def resolve_douyin_profile(*, platform_id: str, id_type: str = "douyin_display_id", url: str = "", creator_name: str = "") -> dict[str, Any]:
    cookies = load_playwright_cookies("抖音")
    if not cookies:
        return {"ok": False, "platform": "抖音", "resolve_status": "missing_cookies", "input_platform_id": platform_id, "input_platform_id_type": id_type}
    with sync_playwright() as playwright:
        browser = launch_chromium(playwright, headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 1800}, locale="zh-CN", user_agent=DOUYIN_USER_AGENT)
        context.add_cookies(cookies)
        page = context.new_page()
        try:
            direct_url = resolve_douyin_share_url(url)
            if direct_url:
                direct = open_douyin_profile_candidate(page, direct_url, platform_id=platform_id, creator_name=creator_name, source="homepage_hint")
                if direct.get("ok"):
                    return direct
                if direct.get("resolve_status") not in {"blocked_no_exact_id_match", "blocked_self_profile"}:
                    return direct
            search_url = douyin_search_url(platform_id)
            page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(8_000)
            candidates = douyin_profile_links(page)
            picked = choose_douyin_candidate(candidates, creator_name=creator_name, platform_id=platform_id)
            if picked:
                result = open_douyin_profile_candidate(page, str(picked.get("href") or ""), platform_id=platform_id, creator_name=creator_name, source="display_id_search")
                result["search_url"] = search_url
                result["candidate_count"] = len(candidates)
                return result
            try:
                body = page.locator("body").inner_text(timeout=5_000)
            except Exception:
                body = ""
            status = "blocked_self_profile" if any(is_douyin_self_profile_url(str(item.get("href") or "")) for item in candidates) else "blocked_no_exact_id_match"
            return {
                "ok": False,
                "platform": "抖音",
                "resolve_status": status,
                "search_url": page.url,
                "rendered_text": body,
                "input_platform_id": platform_id,
                "input_platform_id_type": id_type,
                "candidate_count": len(candidates),
            }
        finally:
            browser.close()


def resolve_creator_profile(*, platform: str, platform_id: str, id_type: str = "unknown", url: str = "", creator_name: str = "") -> dict[str, Any]:
    normalized = normalize_platform(platform)
    if normalized == "抖音":
        return resolve_douyin_profile(platform_id=platform_id, id_type=id_type or "douyin_display_id", url=url, creator_name=creator_name)
    return {
        "ok": False,
        "platform": normalized,
        "resolve_status": "unsupported_platform_for_new_resolver",
        "input_platform_id": platform_id,
        "input_platform_id_type": id_type,
    }
