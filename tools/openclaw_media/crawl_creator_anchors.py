#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

SELFMEDIA_ROOT = Path("/home/ubuntu/selfmedia-tools")
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import (  # noqa: E402
    feishu_ensure_fields,
    feishu_headers,
    feishu_list_records,
    feishu_plain_text,
    feishu_tenant_access_token,
    feishu_update_record,
)
from common.standard_fields import standard_field_specs  # noqa: E402

from build_creator_docs import DEFAULT_CREATOR_REGISTRY_URL  # noqa: E402
from id_business import FEISHU_BASE, load_playwright_cookies  # noqa: E402
from sync_creator_registry import normalize_platform, normalize_platform_id  # noqa: E402


OUTPUT_DIR = Path("/home/ubuntu/openclaw-agents/media/generated/creator-anchor-crawl")


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


def non_empty(value: Any) -> bool:
    return value not in (None, "", [], {})


def xhs_search_url(keyword: str) -> str:
    return "https://www.xiaohongshu.com/search_result/?keyword=" + urllib.parse.quote(keyword) + "&type=51"


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
    page.screenshot(path=str(path), full_page=False, timeout=20_000, animations="disabled")
    return str(path)


def crawl_xhs_anchor(creator_name: str, platform_id: str) -> dict[str, Any]:
    cookies = load_playwright_cookies("小红书")
    if not cookies:
        return {"ok": False, "platform": "小红书", "status": "missing_cookies"}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1800},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
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


def crawl_douyin_anchor(creator_name: str, platform_id: str) -> dict[str, Any]:
    cookies = load_playwright_cookies("抖音")
    if not cookies:
        return {"ok": False, "platform": "抖音", "status": "missing_cookies"}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 1800},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        context.add_cookies(cookies)
        page = context.new_page()
        search_url = f"https://www.douyin.com/search/{urllib.parse.quote(creator_name)}?type=user"
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=10_000)
            page.wait_for_timeout(2_000)
            screenshot = save_screenshot(page, "douyin", creator_name)
            title = page.title()
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=3_000)
            except Exception:
                body = ""
            status = "captcha_blocked" if "验证码" in title or "验证码" in body else "unresolved"
            return {
                "ok": False,
                "platform": "抖音",
                "status": status,
                "search_url": page.url,
                "title": title,
                "visible_text": body[:2000],
                "screenshot": screenshot,
                "platform_id": platform_id,
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


def registry_anchor_specs() -> dict[str, int]:
    return {
        "主页链接": standard_field_specs()["主页链接"],
        "账号名称": standard_field_specs()["账号名称"],
        "作者ID": standard_field_specs()["作者ID"],
        "粉丝数(k)": standard_field_specs()["粉丝数(k)"],
        "作品数": standard_field_specs()["作品数"],
    }


def crawl_registry(
    creator_url: str,
    *,
    limit: int = 0,
    write: bool = False,
    record_ids: set[str] | None = None,
) -> dict[str, Any]:
    token = feishu_tenant_access_token()
    ensure_registry_fields(creator_url, token)
    records = feishu_list_records(creator_url, token=token, page_size=500)
    if record_ids:
        records = [row for row in records if str(row.get("record_id") or "") in record_ids]
    if limit > 0:
        records = records[:limit]

    results: list[dict[str, Any]] = []
    updated = 0
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
            crawl = crawl_douyin_anchor(creator_name, platform_id)
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
            if payload and write:
                feishu_update_record(
                    creator_url,
                    record_id,
                    payload,
                    specs=registry_anchor_specs(),
                    token=token,
                )
                updated += 1
            elif payload:
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
        "write": write,
        "scanned": len(records),
        "updated": updated,
        "items": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use Playwright to enrich creator anchor fields.")
    parser.add_argument("--creator-url", default=DEFAULT_CREATOR_REGISTRY_URL, help="Creator registry table URL.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max record count.")
    parser.add_argument("--record-id", action="append", default=[], help="Optional record ids.")
    parser.add_argument("--write", action="store_true", help="Actually write to Feishu.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = crawl_registry(
        args.creator_url,
        limit=max(0, int(args.limit or 0)),
        write=args.write,
        record_ids={item for item in args.record_id if item},
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
