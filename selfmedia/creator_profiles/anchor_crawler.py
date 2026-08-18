#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

SELFMEDIA_ROOT = Path(__file__).resolve().parents[2]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import (  # noqa: E402
    feishu_ensure_fields,
    feishu_headers,
    feishu_list_records,
    feishu_plain_text,
    feishu_tenant_access_token,
)
from common.resource_ownership import canonical_tenant_owned_resources, require_tenant_id  # noqa: E402

from selfmedia.business.id_business import FEISHU_BASE, load_playwright_cookies  # noqa: E402
from selfmedia.creator_profiles.docs_builder import DEFAULT_CREATOR_REGISTRY_URL  # noqa: E402
from selfmedia.creator_profiles.registry_sync import normalize_platform, normalize_platform_id  # noqa: E402


OUTPUT_DIR = Path("/home/ubuntu/openclaw-agents/media/generated/creator-anchor-crawl")
CHROMIUM_EXECUTABLE_CANDIDATES = (
    os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", ""),
    "/home/ubuntu/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome",
)
DOUYIN_BLOCKED_PROFILE_PATHS = {"/user/self"}
DOUYIN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def parse_chinese_count(text: str) -> int | None:
    raw = str(text or "").strip().replace(",", "")
    if not raw:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([万wWkK千]?)", raw)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).lower()
    multiplier = 1
    if unit in {"万", "w"}:
        multiplier = 10_000
    elif unit in {"k", "千"}:
        multiplier = 1_000
    return int(round(number * multiplier))


def first_int_match(text: str, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        match = re.search(rf'(?:\\?")?{re.escape(key)}(?:\\?")?\s*:\s*(\d+)', text)
        if match:
            return int(match.group(1))
    return None


def first_string_match(text: str, keys: tuple[str, ...]) -> str:
    for key in keys:
        match = re.search(rf'(?:\\?")?{re.escape(key)}(?:\\?")?\s*:\s*(?:\\?")([^"\\]+)', text)
        if match:
            value = match.group(1).replace(r"\n", "\n").replace(r"\/", "/").strip()
            if value and value != "$undefined":
                return value
    return ""


def text_variants(text: str) -> list[str]:
    raw = str(text or "")
    variants = [raw, urllib.parse.unquote(raw)]
    variants.extend(html_unescape for html_unescape in [raw.replace("&quot;", '"'), urllib.parse.unquote(raw).replace("&quot;", '"')])
    deduped: list[str] = []
    for item in variants:
        if item not in deduped:
            deduped.append(item)
    return deduped


def non_empty(value: Any) -> bool:
    return value not in (None, "", [], {})


def xhs_search_url(keyword: str) -> str:
    return "https://www.xiaohongshu.com/search_result/?keyword=" + urllib.parse.quote(keyword) + "&type=51"


def launch_chromium(playwright, *, headless: bool = True):
    for candidate in CHROMIUM_EXECUTABLE_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return playwright.chromium.launch(headless=headless, executable_path=str(path))
    return playwright.chromium.launch(headless=headless)


def candidate_profile_links(page) -> list[dict[str, str]]:
    return page.eval_on_selector_all(
        "a",
        """
        els => els
          .map(a => ({text: (a.innerText || "").trim(), href: a.href || ""}))
          .filter(item => item.href.includes("/user/profile/") && item.text)
        """,
    )


def choose_xhs_candidate(
    candidates: list[dict[str, str]],
    *,
    creator_name: str,
    platform_id: str,
) -> dict[str, str] | None:
    creator_name = creator_name.strip()
    platform_id = platform_id.strip()
    exact_id = f"小红书号：{platform_id}" if platform_id else ""
    for item in candidates:
        text = str(item.get("text") or "").strip()
        if exact_id and exact_id in text and creator_name and creator_name in text:
            return item
    for item in candidates:
        text = str(item.get("text") or "").strip()
        if exact_id and exact_id in text:
            return item
    for item in candidates:
        text = str(item.get("text") or "").strip()
        if creator_name and creator_name in text:
            return item
    return None


def parse_xhs_candidate(text: str, href: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    payload: dict[str, Any] = {"homepage_link": href.strip(), "visible_text": clean}
    if lines:
        payload["account_name"] = lines[0]
    xhs_id_match = re.search(r"小红书号[:：]\s*([0-9A-Za-z_-]+)", clean)
    if xhs_id_match:
        payload["author_id"] = xhs_id_match.group(1)
    fans_match = re.search(r"粉丝[・:：]?\s*([0-9.]+[万wWkK千]?)", clean)
    if fans_match:
        payload["fans_count"] = parse_chinese_count(fans_match.group(1))
    notes_match = re.search(r"(?:笔记|作品)[・:：]?\s*([0-9.]+[万wWkK千]?)", clean)
    if notes_match:
        payload["post_count"] = parse_chinese_count(notes_match.group(1))
    return payload


def save_screenshot(page, platform: str, creator_name: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{platform}-{creator_name[:40]}.png"
    try:
        page.screenshot(path=str(path), full_page=False, timeout=20_000, animations="disabled")
        return str(path)
    except Exception:
        return ""


def crawl_xhs_anchor(creator_name: str, platform_id: str) -> dict[str, Any]:
    cookies = load_playwright_cookies("小红书")
    if not cookies:
        return {"ok": False, "platform": "小红书", "status": "missing_cookies"}
    with sync_playwright() as playwright:
        browser = launch_chromium(playwright, headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1800},
            locale="zh-CN",
            user_agent=(
                DOUYIN_USER_AGENT
            ),
        )
        context.add_cookies(cookies)
        page = context.new_page()
        try:
            queries = [creator_name.strip()]
            if platform_id and platform_id not in queries:
                queries.append(platform_id)
            last_result: dict[str, Any] | None = None
            for query in queries:
                if not query:
                    continue
                page.goto(xhs_search_url(query), wait_until="domcontentloaded", timeout=20_000)
                page.wait_for_timeout(6_000)
                screenshot = save_screenshot(page, "xhs", query)
                candidates = candidate_profile_links(page)
                picked = choose_xhs_candidate(candidates, creator_name=creator_name, platform_id=platform_id)
                if picked:
                    parsed = parse_xhs_candidate(str(picked.get("text") or ""), str(picked.get("href") or ""))
                    parsed.update(
                        {
                            "ok": True,
                            "platform": "小红书",
                            "status": "matched",
                            "search_url": page.url,
                            "screenshot": screenshot,
                            "candidate_count": len(candidates),
                            "matched_query": query,
                        }
                    )
                    return parsed
                last_result = {
                    "ok": False,
                    "platform": "小红书",
                    "status": "candidate_not_found",
                    "search_url": page.url,
                    "screenshot": screenshot,
                    "candidate_count": len(candidates),
                    "matched_query": query,
                }
            return last_result or {"ok": False, "platform": "小红书", "status": "candidate_not_found"}
        except PlaywrightTimeoutError as exc:
            return {"ok": False, "platform": "小红书", "status": "timeout", "error": str(exc)}
        finally:
            browser.close()


def douyin_search_url(keyword: str) -> str:
    return f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}?type=user"


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
        response = requests.get(
            raw,
            allow_redirects=True,
            headers={"User-Agent": DOUYIN_USER_AGENT},
            timeout=20,
        )
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


def choose_douyin_candidate(
    candidates: list[dict[str, str]],
    *,
    creator_name: str,
    platform_id: str,
) -> dict[str, str] | None:
    creator_name = creator_name.strip()
    platform_id = platform_id.strip()
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


def parse_douyin_profile_text(text: str, url: str = "", *, title: str = "") -> dict[str, Any]:
    clean = str(text or "").strip()
    payload: dict[str, Any] = {"homepage_link": url.strip(), "visible_text": clean}
    title_match = re.search(r"^(?P<name>.+?)的抖音\s*-\s*抖音$", str(title or "").strip())
    if title_match:
        payload["account_name"] = title_match.group("name").strip()
    id_match = re.search(r"抖音号[:：]\s*([0-9A-Za-z_.-]+)", clean)
    if id_match:
        payload["author_id"] = id_match.group(1)
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    if not payload.get("account_name") and payload.get("author_id"):
        id_index = next((idx for idx, line in enumerate(lines) if "抖音号" in line), -1)
        if id_index > 0:
            for candidate in reversed(lines[:id_index]):
                if candidate not in {"关注", "粉丝", "获赞", "作品", "喜欢", "收藏"} and not re.fullmatch(r"\d+(?:\.\d+)?[万wWkK千]?", candidate):
                    payload["account_name"] = candidate
                    break
    for idx, line in enumerate(lines[:-1]):
        value = parse_chinese_count(lines[idx + 1])
        if value is None:
            continue
        if line == "关注" and "following_count" not in payload:
            payload["following_count"] = value
        elif line == "粉丝" and "fans_count" not in payload:
            payload["fans_count"] = value
        elif line == "获赞" and "total_favorited" not in payload:
            payload["total_favorited"] = value
        elif line == "作品" and "post_count" not in payload:
            payload["post_count"] = value
    joined = "\n".join(lines)
    if "post_count" not in payload:
        post_match = re.search(r"作品\s*\n\s*([0-9.]+[万wWkK千]?)", joined)
        if post_match:
            payload["post_count"] = parse_chinese_count(post_match.group(1))
    return payload


def parse_douyin_embedded_profile_data(html: str, platform_id: str) -> dict[str, Any]:
    platform_id = str(platform_id or "").strip()
    if not html or not platform_id:
        return {}

    for blob in text_variants(html):
        positions = [match.start() for match in re.finditer(re.escape(platform_id), blob)]
        for position in positions:
            window_start = max(0, position - 5000)
            window = blob[window_start : position + 5000]
            relative_position = position - window_start
            profile_start = max(
                window.rfind(r'\"nickname\"', 0, relative_position),
                window.rfind('"nickname"', 0, relative_position),
                window.rfind(r'\"realName\"', 0, relative_position),
                window.rfind('"realName"', 0, relative_position),
            )
            if profile_start >= 0:
                window = window[profile_start:]
            if "uniqueId" not in window and "shortId" not in window and "抖音号" not in window:
                continue
            unique_id = first_string_match(window, ("uniqueId", "shortId"))
            if unique_id and unique_id != platform_id:
                continue
            payload: dict[str, Any] = {
                "author_id": platform_id,
                "metric_source": "embedded_profile_data",
            }
            account_name = first_string_match(window, ("nickname", "realName"))
            if account_name:
                payload["account_name"] = account_name
            bio = first_string_match(window, ("desc", "signature"))
            if bio:
                payload["bio"] = bio
            fans_count = first_int_match(window, ("mplatformFollowersCount", "followerCount"))
            if fans_count is not None:
                payload["fans_count"] = fans_count
            post_count = first_int_match(window, ("awemeCount",))
            if post_count is not None:
                payload["post_count"] = post_count
            following_count = first_int_match(window, ("followingCount",))
            if following_count is not None:
                payload["following_count"] = following_count
            total_favorited = first_int_match(window, ("totalFavorited",))
            if total_favorited is not None:
                payload["total_favorited"] = total_favorited
            return payload
    return {}


def open_douyin_profile_candidate(page, url: str, *, platform_id: str, creator_name: str, source: str) -> dict[str, Any]:
    if not url:
        return {"ok": False, "platform": "抖音", "status": "missing_profile_url", "source": source}
    if is_douyin_self_profile_url(url):
        return {
            "ok": False,
            "platform": "抖音",
            "status": "blocked_self_profile",
            "homepage_link": url,
            "source": source,
            "platform_id": platform_id,
        }
    goto_error = ""
    try:
        page.goto(url, wait_until="commit", timeout=30_000)
    except PlaywrightTimeoutError as exc:
        goto_error = str(exc)
    page.wait_for_timeout(8_000)
    screenshot = save_screenshot(page, "douyin", creator_name or platform_id)
    final_url = page.url
    if is_douyin_self_profile_url(final_url):
        return {
            "ok": False,
            "platform": "抖音",
            "status": "blocked_self_profile",
            "homepage_link": final_url,
            "source": source,
            "screenshot": screenshot,
            "platform_id": platform_id,
        }
    title = page.title()
    try:
        body = page.locator("body").inner_text(timeout=5_000)
    except Exception:
        body = ""
    try:
        html = page.content()
    except Exception:
        html = ""
    parsed = parse_douyin_profile_text(body, final_url, title=title)
    embedded = parse_douyin_embedded_profile_data(html, platform_id)
    for key, value in embedded.items():
        if non_empty(value) and not non_empty(parsed.get(key)):
            parsed[key] = value
    if not body and goto_error:
        return {"ok": False, "platform": "抖音", "status": "timeout", "error": goto_error, "homepage_link": url, "source": source, "platform_id": platform_id}
    if str(parsed.get("author_id") or "") != platform_id:
        return {
            "ok": False,
            "platform": "抖音",
            "status": "blocked_no_exact_id_match",
            "homepage_link": final_url,
            "title": title,
            "visible_text": body[:2000],
            "screenshot": screenshot,
            "platform_id": platform_id,
            "source": source,
            "parsed_author_id": parsed.get("author_id", ""),
        }
    parsed.update(
        {
            "ok": True,
            "platform": "抖音",
            "status": "matched",
            "homepage_link": final_url,
            "title": title,
            "screenshot": screenshot,
            "platform_id": platform_id,
            "source": source,
        }
    )
    return parsed


def crawl_douyin_anchor(creator_name: str, platform_id: str, homepage_hint: str = "") -> dict[str, Any]:
    cookies = load_playwright_cookies("抖音")
    if not cookies:
        return {"ok": False, "platform": "抖音", "status": "missing_cookies"}
    with sync_playwright() as playwright:
        browser = launch_chromium(playwright, headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 1800},
            locale="zh-CN",
            user_agent=DOUYIN_USER_AGENT,
        )
        context.add_cookies(cookies)
        page = context.new_page()
        try:
            direct_url = resolve_douyin_share_url(homepage_hint)
            if direct_url:
                direct_result = open_douyin_profile_candidate(
                    page,
                    direct_url,
                    platform_id=platform_id,
                    creator_name=creator_name,
                    source="homepage_hint",
                )
                if direct_result.get("ok"):
                    return direct_result

            search_url = douyin_search_url(platform_id)
            page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(8_000)
            screenshot = save_screenshot(page, "douyin", platform_id)
            title = page.title()
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=5_000)
            except Exception:
                body = ""
            candidates = douyin_profile_links(page)
            picked = choose_douyin_candidate(candidates, creator_name=creator_name, platform_id=platform_id)
            if picked:
                picked_result = open_douyin_profile_candidate(
                    page,
                    str(picked.get("href") or ""),
                    platform_id=platform_id,
                    creator_name=creator_name,
                    source="display_id_search",
                )
                if picked_result.get("ok"):
                    picked_result["search_url"] = search_url
                    picked_result["candidate_count"] = len(candidates)
                    return picked_result
                picked_result["search_url"] = search_url
                picked_result["candidate_count"] = len(candidates)
                return picked_result
            status = "captcha_blocked" if "验证码" in title or "验证码" in body else "unresolved"
            if any(is_douyin_self_profile_url(str(item.get("href") or "")) for item in candidates):
                status = "blocked_self_profile"
            return {
                "ok": False,
                "platform": "抖音",
                "status": status,
                "search_url": page.url,
                "title": title,
                "visible_text": body[:2000],
                "screenshot": screenshot,
                "platform_id": platform_id,
                "candidate_count": len(candidates),
            }
        except PlaywrightTimeoutError as exc:
            return {"ok": False, "platform": "抖音", "status": "timeout", "error": str(exc), "platform_id": platform_id}
        finally:
            browser.close()


def build_update_payload(fields: dict[str, Any], crawl: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    homepage_link = str(crawl.get("homepage_link") or "").strip()
    account_name = str(crawl.get("account_name") or "").strip()
    author_id = str(crawl.get("author_id") or "").strip()
    fans_count = crawl.get("fans_count")
    post_count = crawl.get("post_count")

    if homepage_link and feishu_plain_text(fields.get("主页链接")) != homepage_link:
        payload["主页链接"] = homepage_link
    if account_name and not non_empty(fields.get("账号名称")):
        payload["账号名称"] = account_name
    current_author_id = feishu_plain_text(fields.get("作者ID"))
    if author_id and author_id != normalize_platform_id(fields.get("平台ID")) and not current_author_id:
        payload["作者ID"] = author_id
    if isinstance(fans_count, int) and fans_count > 0 and not non_empty(fields.get("粉丝数(k)")):
        payload["粉丝数(k)"] = round(fans_count / 1000, 1)
    if isinstance(post_count, int) and post_count > 0 and not non_empty(fields.get("作品数")):
        payload["作品数"] = post_count
    return payload


def ensure_registry_fields(url: str, token: str) -> None:
    from common.social_runtime import feishu_bitable_refs  # noqa: E402

    app_token, table_id, token = feishu_bitable_refs(url, token)
    specs = {
        "主页链接": standard_field_specs()["主页链接"],
        "账号名称": standard_field_specs()["账号名称"],
        "作者ID": standard_field_specs()["作者ID"],
        "粉丝数(k)": standard_field_specs()["粉丝数(k)"],
        "作品数": standard_field_specs()["作品数"],
    }
    feishu_ensure_fields(app_token, table_id, token, specs)


def crawl_registry(
    creator_url: str,
    *,
    tenant_id: str,
    limit: int = 0,
    record_ids: set[str] | None = None,
) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id)
    token = feishu_tenant_access_token()
    ensure_registry_fields(creator_url, token)
    owner_service = canonical_tenant_owned_resources()
    records: list[dict[str, Any]] = []
    for owner in owner_service.registry.list_all_by_tenant(
        tenant_id,
        resource_type="media.creator_profile",
    ):
        matches = feishu_list_records(
            creator_url,
            token=token,
            page_size=2,
            filter_formula=(
                f'CurrentValue.[达人档案ID] = '
                f'{json.dumps(owner.canonical_resource_id, ensure_ascii=False)}'
            ),
        )
        exact = [
            record
            for record in matches
            if feishu_plain_text((record.get("fields") or {}).get("达人档案ID")).strip()
            == owner.canonical_resource_id
        ]
        if len(exact) != 1:
            raise RuntimeError("CreatorProfile canonical projection is missing or duplicated")
        record = exact[0]
        owner_service.assert_projection_read(
            "media.creator_profile",
            owner.canonical_resource_id,
            session_tenant_id=tenant_id,
            fields=record.get("fields") or {},
            projection_source=f"feishu:creator_profiles/{record.get('record_id') or 'missing'}",
        )
        records.append(record)
    if record_ids:
        records = [row for row in records if str(row.get("record_id") or "") in record_ids]
    if limit > 0:
        records = records[:limit]

    results: list[dict[str, Any]] = []
    for row in records:
        record_id = str(row.get("record_id") or "")
        fields = row.get("fields") or {}
        if not isinstance(fields, dict):
            continue
        platform = normalize_platform(fields.get("平台"))
        creator_name = feishu_plain_text(fields.get("博主IP"))
        platform_id = normalize_platform_id(fields.get("平台ID"))
        if not creator_name or not platform or not platform_id:
            results.append({"record_id": record_id, "status": "missing_anchor_inputs"})
            continue

        if platform == "小红书":
            crawl = crawl_xhs_anchor(creator_name, platform_id)
        elif platform == "抖音":
            crawl = crawl_douyin_anchor(creator_name, platform_id, feishu_plain_text(fields.get("主页链接")))
        else:
            crawl = {"ok": False, "platform": platform, "status": "unsupported_platform"}

        item: dict[str, Any] = {
            "record_id": record_id,
            "creator": creator_name,
            "platform": platform,
            "platform_id": platform_id,
            "crawl_status": crawl.get("status"),
        }
        if crawl.get("ok"):
            payload = build_update_payload(fields, crawl)
            item["payload_fields"] = sorted(payload)
            item["homepage_link"] = crawl.get("homepage_link")
            item["account_name"] = crawl.get("account_name")
            item["fans_count"] = crawl.get("fans_count")
            item["post_count"] = crawl.get("post_count")
            if payload:
                item["would_update"] = True
            else:
                item["status"] = "already_complete"
        else:
            item["error"] = crawl.get("error", "")
            if crawl.get("search_url"):
                item["search_url"] = crawl.get("search_url")
            if crawl.get("screenshot"):
                item["screenshot"] = crawl.get("screenshot")
        results.append(item)
    return {
        "ok": True,
        "scanned": len(records),
        "items": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use Playwright to inspect creator profile anchor fields and return candidate updates.")
    parser.add_argument("--creator-url", default=DEFAULT_CREATOR_REGISTRY_URL, help="Creator registry table URL.")
    parser.add_argument("--tenant-id", required=True, help="Management tenant whose owned creator profiles may be processed.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max record count.")
    parser.add_argument("--record-id", action="append", default=[], help="Optional record ids.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = crawl_registry(
        args.creator_url,
        tenant_id=args.tenant_id,
        limit=max(0, int(args.limit or 0)),
        record_ids={item for item in args.record_id if item},
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
