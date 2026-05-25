#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


MEDIA_ROOT = Path(__file__).resolve().parents[1]
SELFMEDIA_ROOT = Path("/home/ubuntu/selfmedia-tools")
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import (  # noqa: E402
    FEISHU_BASE,
    detect_platform,
    extract_urls,
    feishu_bool,
    feishu_bitable_refs,
    feishu_coerce_value,
    feishu_ensure_fields,
    feishu_field_types,
    feishu_headers,
    feishu_list_records,
    feishu_plain_text,
    feishu_table_url_from_env,
    feishu_tenant_access_token,
    load_default_env_files,
    load_env_file,
)
from common.standard_fields import normalize_standard_fields, standard_field_specs
from common.standard_fields import select_fields_for_write


OUTPUT_DIR = MEDIA_ROOT / "generated" / "id-business"
RECORD_DIR = OUTPUT_DIR / "records"
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
URL_ENV_NAMES = (
    "MEDIA_OS_BUSINESS_URL",
)
NOTIFY_TARGET_ENV_NAMES = (
    "ID_BUSINESS_SOCIAL_TARGET",
    "OPENCLAW_DELIVERY_TO",
    "OPENCLAW_LAST_TO",
    "OPENCLAW_TARGET",
)
LOCAL_TZ = timezone(timedelta(hours=8))


LEGACY_FIELD_SPECS: dict[str, int] = {
    "作者ID": 1,
    "账号名称": 1,
    "平台": 1,
    "主页链接": 15,
    "分享链接": 15,
    "分享原文": 1,
    "启用": 7,
    "更新时间": 5,
    "最近状态": 1,
    "最近错误": 1,
    "主页截图路径": 1,
    "截图状态": 1,
    "主页可见文本": 1,
    "账号数据摘要": 1,
    "给品牌方信息": 1,
    "赞藏总数": 2,
    "获赞数": 2,
    "粉丝数": 2,
    "关注数": 2,
    "作品数": 2,
    "商务原文": 1,
    "沟通开场": 1,
    "项目": 1,
    "品牌": 1,
    "产品": 1,
    "Brief链接": 1,
    "Brief附件路径": 1,
    "Brief关键入库信息": 1,
    "Brief告知类信息": 1,
    "Brief原文": 1,
    "Brief收集状态": 1,
    "档期": 1,
    "合作流程": 1,
    "图文报价": 1,
    "视频报价": 1,
    "非报备图文/视频单品报价": 1,
    "报备视频、图文/单品报价": 1,
    "4月报备图文价格": 1,
    "5月报备图文价格": 1,
    "报备返点": 1,
    "本月下单是否保价次月执行": 1,
    "是否可保价5月": 1,
    "排竞时长": 1,
    "是否有免费分发平台": 1,
    "全渠道授权及时长": 1,
    "笔记默认保留时长": 1,
    "评论区置顶": 1,
    "素材收集要求": 1,
    "需反问博主字段": 1,
    "反问博主话术": 1,
    "反问博主状态": 1,
    "反问博主时间": 5,
    "反问博主通知结果": 1,
    "具体档期": 1,
    "非商用授权": 1,
    "作品保留": 1,
    "所在地区是否可以正常收发快递": 1,
    "商用授权": 1,
    "可同步平台": 1,
    "尺码": 1,
    "报价更新时间": 5,
    "报价提醒月份": 1,
    "报价提醒状态": 1,
    "待补充字段": 1,
    "详情JSON": 1,
}
FIELD_SPECS: dict[str, int] = standard_field_specs(LEGACY_FIELD_SPECS)


LABEL_ALIASES = {
    "作者ID": "作者ID",
    "作者Id": "作者ID",
    "作者id": "作者ID",
    "ID": "作者ID",
    "Id": "作者ID",
    "id": "作者ID",
    "简称": "作者ID",
    "作者简称": "作者ID",
    "内部称呼": "作者ID",
    "称呼": "作者ID",
    "备注名": "作者ID",
    "平台": "平台",
    "项目": "项目",
    "品牌": "品牌",
    "产品": "产品",
    "brief链接": "Brief链接",
    "Brief链接": "Brief链接",
    "brief": "Brief链接",
    "Brief": "Brief链接",
    "附件": "Brief附件路径",
    "Brief附件": "Brief附件路径",
    "Brief附件路径": "Brief附件路径",
    "档期": "档期",
    "具体档期": "具体档期",
    "合作流程": "合作流程",
    "图文报价": "图文报价",
    "图文单品报价": "图文报价",
    "图文/单品报价": "图文报价",
    "非报备图文报价": "图文报价",
    "报备图文报价": "图文报价",
    "视频报价": "视频报价",
    "视频单品报价": "视频报价",
    "视频/单品报价": "视频报价",
    "非报备视频报价": "视频报价",
    "报备视频报价": "视频报价",
    "非报备图文/视频单品报价": "非报备图文/视频单品报价",
    "非报备图文": "非报备图文/视频单品报价",
    "非报备图文报价": "非报备图文/视频单品报价",
    "非报备视频": "非报备图文/视频单品报价",
    "非报备视频报价": "非报备图文/视频单品报价",
    "报备视频、图文/单品报价": "报备视频、图文/单品报价",
    "报备视频图文/单品报价": "报备视频、图文/单品报价",
    "报备视频": "报备视频、图文/单品报价",
    "报备图文": "报备视频、图文/单品报价",
    "4月份报备图文价格": "4月报备图文价格",
    "4月报备图文价格": "4月报备图文价格",
    "5月份报备图文价格": "5月报备图文价格",
    "5月报备图文价格": "5月报备图文价格",
    "返点": "报备返点",
    "报备返点": "报备返点",
    "是否可保价5月": "是否可保价5月",
    "可保价5月": "是否可保价5月",
    "排竞时长": "排竞时长",
    "排竞时长是否可前15后15": "排竞时长",
    "是否有免费分发平台": "是否有免费分发平台",
    "免费分发平台": "是否有免费分发平台",
    "是否可以全渠道授权及时长": "全渠道授权及时长",
    "全渠道授权及时长": "全渠道授权及时长",
    "笔记是否默认一年以上": "笔记默认保留时长",
    "笔记默认一年以上": "笔记默认保留时长",
    "发布后第二天是否能配合评论区置顶": "评论区置顶",
    "评论区置顶": "评论区置顶",
    "素材需要收集纯净版和发布版": "素材收集要求",
    "素材收集要求": "素材收集要求",
    "本月下单是否保价次月执行（如不能辛苦给到次月价格）": "本月下单是否保价次月执行",
    "本月下单是否保价次月执行": "本月下单是否保价次月执行",
    "非商用授权": "非商用授权",
    "作品保留": "作品保留",
    "所在地区是否可以正常收发快递": "所在地区是否可以正常收发快递",
    "快递": "所在地区是否可以正常收发快递",
    "商用授权": "商用授权",
    "可同步平台": "可同步平台",
    "尺码": "尺码",
    "账号名称": "账号名称",
    "账号": "账号名称",
    "博主": "账号名称",
    "昵称": "账号名称",
}


COUNT_RE = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>[kKmMwW万千]?)")
CONFIRMATION_FIELDS = {
    "具体档期",
    "图文报价",
    "视频报价",
    "非报备图文/视频单品报价",
    "报备视频、图文/单品报价",
    "4月报备图文价格",
    "5月报备图文价格",
    "报备返点",
    "本月下单是否保价次月执行",
    "是否可保价5月",
    "排竞时长",
    "是否有免费分发平台",
    "全渠道授权及时长",
    "笔记默认保留时长",
    "评论区置顶",
    "素材收集要求",
    "所在地区是否可以正常收发快递",
    "可同步平台",
    "尺码",
}
CONFIRMATION_CANONICAL = {
    "档期": "具体档期",
    "返点": "报备返点",
}
AMBIGUOUS_VALUE_RE = re.compile(r"待补充|待确认|不确定|看情况|尽快|最快|可沟通|都行|\\?|？")
QUESTION_TEMPLATES = {
    "具体档期": "最快可执行/可发布的具体档期是什么？请具体到日期或日期区间，不要只写“尽快”。",
    "图文报价": "本月图文报价是多少？请注明报备/非报备。",
    "视频报价": "本月视频报价是多少？请注明报备/非报备。",
    "非报备图文/视频单品报价": "非报备图文/视频单品报价分别是多少？",
    "报备视频、图文/单品报价": "报备图文、报备视频单品报价分别是多少？",
    "4月报备图文价格": "4月份报备图文价格是多少？",
    "5月报备图文价格": "5月份报备图文价格是多少？",
    "报备返点": "返点是否接受？如果不是 40%，请给可接受返点。",
    "本月下单是否保价次月执行": "本月下单是否可以保价到次月执行？如果不行，请给次月价格。",
    "是否可保价5月": "是否可以保价到 5 月执行？如果不行，请给 5 月价格。",
    "排竞时长": "是否可接受前 15 天后 15 天排竞？如果不能，可接受的排竞时长是多少？",
    "是否有免费分发平台": "是否有可免费同步/分发的平台？具体哪些平台？",
    "全渠道授权及时长": "是否可以全渠道授权？可授权哪些渠道，授权时长多久？",
    "笔记默认保留时长": "笔记是否默认保留一年以上？",
    "评论区置顶": "发布后第二天是否能配合评论区置顶？",
    "素材收集要求": "是否能提供纯净版和发布版素材？",
    "所在地区是否可以正常收发快递": "所在地区是否可以正常收发快递？",
    "可同步平台": "可同步哪些平台？",
    "尺码": "尺码是多少？",
}


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def business_now_iso() -> str:
    return datetime.now(LOCAL_TZ).replace(microsecond=0).isoformat()


def load_id_business_env_files() -> None:
    load_default_env_files()
    for path in (MEDIA_ROOT / ".env", MEDIA_ROOT / ".env.local"):
        load_env_file(path)


def normalize_label(label: str) -> str:
    cleaned = re.sub(r"\s+", "", label.strip().strip("：:"))
    cleaned = cleaned.strip("【】[]")
    cleaned_base = re.sub(r"[（(].*?(?:[）)]|$)", "", cleaned)
    mapped = LABEL_ALIASES.get(cleaned) or LABEL_ALIASES.get(cleaned_base)
    if mapped:
        return mapped
    if re.match(r"^\d{1,2}月份?报备图文价格$", cleaned_base):
        month = re.match(r"^(\d{1,2})月份?报备图文价格$", cleaned_base).group(1)
        return f"{month}月报备图文价格"
    if cleaned_base.endswith("图文报价") or cleaned_base.endswith("图文单品报价"):
        return "图文报价"
    if cleaned_base.endswith("视频报价") or cleaned_base.endswith("视频单品报价"):
        return "视频报价"
    return cleaned_base


def parse_count(value: str) -> int | None:
    match = COUNT_RE.search(value.replace(",", ""))
    if not match:
        return None
    number = float(match.group("number"))
    unit = match.group("unit").lower()
    multiplier = 1
    if unit == "k" or unit == "千":
        multiplier = 1_000
    elif unit == "m":
        multiplier = 1_000_000
    elif unit in {"w", "万"}:
        multiplier = 10_000
    return int(number * multiplier)


def extract_labeled_fields(text: str) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, str] = {}
    pending: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*\d+\s*[、.．]\s*", "", line)
        match = re.match(r"^【(?P<label>[^】]+)】\s*[：:]\s*(?P<value>.*)$", line)
        if not match:
            match = re.match(r"^(?P<label>[^：:]{1,120})[：:]\s*(?P<value>.*)$", line)
        if match:
            label = normalize_label(match.group("label"))
            value = match.group("value").strip()
            if label in FIELD_SPECS:
                if value:
                    fields[label] = value
                elif not fields.get(label):
                    pending.append(label)
            continue
        compact = re.sub(r"\s+", "", line)
        matched_compact_label = False
        for label in ("非商用授权", "商用授权", "作品保留"):
            if compact.startswith(label) and len(compact) > len(label):
                fields[label] = line[len(label) :].strip(" ：:，,")
                matched_compact_label = True
                break
        if matched_compact_label:
            continue
        if re.search(r"女码|男码|尺码|码数|最小\d+|最大\d+", line):
            fields.setdefault("尺码", line)
    if fields.get("档期") and not fields.get("具体档期"):
        fields["具体档期"] = fields["档期"]
    pending = [label for label in pending if not fields.get(label)]
    return fields, sorted(set(pending))


def enrich_brief_structured_fields(text: str, fields: dict[str, str], pending: list[str]) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    for index, raw_line in enumerate(lines):
        if not raw_line:
            continue
        line = re.sub(r"^\s*\d+\s*[、.．]\s*", "", raw_line)
        match = re.match(r"^【?(?P<label>[^】：:]{1,140})】?\s*[：:]\s*(?P<value>.*)$", line)
        if not match:
            continue
        normalized = normalize_label(match.group("label"))
        value = match.group("value").strip()
        if normalized == "全渠道授权及时长" and not value:
            bullets: list[str] = []
            for next_line in lines[index + 1 :]:
                if not next_line:
                    continue
                if re.match(r"^\s*\d+\s*[、.．]\s*", next_line):
                    break
                if re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", next_line):
                    bullets.append(next_line)
            if bullets:
                hint_match = re.search(r"[（(]([^）)]+)[）)]", match.group("label"))
                hint = hint_match.group(1).strip() if hint_match else ""
                fields["全渠道授权及时长"] = "\n".join(([hint] if hint else []) + bullets)
        elif normalized == "素材收集要求" and not value:
            fields["素材收集要求"] = "纯净版和发布版"
    return sorted({label for label in pending if not fields.get(label)})


def strip_trigger(text: str) -> str:
    return re.sub(r"^\s*【ID\+商务】\s*", "", text.strip(), flags=re.IGNORECASE)


def is_profile_url(url: str) -> bool:
    lower = (url or "").lower()
    return any(domain in lower for domain in ("xhslink.com", "xiaohongshu.com", "douyin.com", "iesdouyin.com"))


def split_business_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    profile_urls: list[str] = []
    brief_urls: list[str] = []
    for url in urls:
        if is_profile_url(url):
            profile_urls.append(url)
        else:
            brief_urls.append(url)
    return profile_urls, brief_urls


def infer_author_id(body: str, fields: dict[str, str]) -> str:
    if fields.get("作者ID"):
        return fields["作者ID"].strip()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line_without_urls = re.sub(r"https?://\S+", "", line).strip()
        if not line_without_urls:
            continue
        if re.match(r"^【[^】]+】\s*[：:]", line_without_urls) or re.match(r"^[^：:]{1,40}[：:]", line_without_urls):
            continue
        match = re.match(r"^(?P<id>[A-Za-z0-9_\-\u4e00-\u9fff]{1,12})\s+(.+)$", line_without_urls)
        if match and any(keyword in line_without_urls for keyword in ("小红书", "抖音", "平台", "品牌", "主页", "商务")):
            return match.group("id")
        if any(keyword in line_without_urls for keyword in ("我在小红书", "打开抖音", "长按复制", "哈喽", "补充以下", "合作信息")):
            continue
        if re.search(r"[，。；;：:、,]", line_without_urls):
            continue
        if len(line_without_urls) <= 12:
            return line_without_urls
    return ""


def detect_platform_cn(text: str, urls: list[str], fields: dict[str, str]) -> str:
    explicit = fields.get("平台", "").strip()
    if explicit:
        if explicit.lower() in {"xhs", "rednote", "xiaohongshu"} or "小红书" in explicit:
            return "小红书"
        if explicit.lower() in {"douyin", "tiktok"} or "抖音" in explicit:
            return "抖音"
        return explicit
    combined = "\n".join([text, *urls]).lower()
    if "xhslink.com" in combined or "xiaohongshu.com" in combined or "小红书" in text:
        return "小红书"
    if "douyin.com" in combined or "iesdouyin.com" in combined or "抖音" in text:
        return "抖音"
    platform = detect_platform(urls[0]) if urls else "unknown"
    return {"xiaohongshu": "小红书", "douyin": "抖音"}.get(platform, "未识别")


def metrics_from_text(text: str) -> dict[str, int]:
    metrics: dict[str, int] = {}
    patterns = [
        ("赞藏总数", r"收获了\s*([\d.,]+(?:\s*[kKmMwW万千])?)\s*次赞与收藏"),
        ("获赞数", r"(?:获赞|点赞)\s*(?:约)?\s*([\d.,]+(?:\s*[kKmMwW万千])?)"),
        ("粉丝数", r"粉丝\s*(?:数)?\s*(?:约)?\s*([\d.,]+(?:\s*[kKmMwW万千])?)"),
        ("关注数", r"关注\s*(?:数)?\s*(?:约)?\s*([\d.,]+(?:\s*[kKmMwW万千])?)"),
        ("作品数", r"作品\s*(?:数)?\s*(?:约)?\s*([\d.,]+(?:\s*[kKmMwW万千])?)"),
    ]
    for field, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        parsed = parse_count(match.group(1))
        if parsed is not None:
            metrics[field] = parsed
    return metrics


def sanitize_stem(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value.strip(), flags=re.UNICODE).strip("-._")
    return cleaned[:80] or "creator"


def load_cookie_candidates(platform: str) -> list[Path]:
    if platform == "小红书":
        return [
            SELFMEDIA_ROOT / "04-manage-platform-cookies" / "private" / "xiaohongshu-cookies.json",
            SELFMEDIA_ROOT / "01-ingest-content-flow" / "private" / "xiaohongshu-cookies.json",
            Path(os.getenv("XIAOHONGSHU_COOKIES_JSON_PATH", "")),
        ]
    if platform == "抖音":
        return [
            SELFMEDIA_ROOT / "04-manage-platform-cookies" / "private" / "douyin-cookies.json",
            SELFMEDIA_ROOT / "01-ingest-content-flow" / "private" / "douyin-cookies.json",
            Path(os.getenv("DOUYIN_COOKIES_JSON_PATH", "")),
        ]
    return []


def load_playwright_cookies(platform: str) -> list[dict[str, Any]]:
    for path in load_cookie_candidates(platform):
        if not str(path) or not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cookies = data if isinstance(data, list) else data.get("cookies") if isinstance(data, dict) else []
        if not isinstance(cookies, list):
            continue
        normalized = []
        for cookie in cookies:
            if not isinstance(cookie, dict) or not cookie.get("name") or not cookie.get("value"):
                continue
            item = {
                "name": str(cookie["name"]),
                "value": str(cookie["value"]),
                "domain": str(cookie.get("domain") or ""),
                "path": str(cookie.get("path") or "/"),
            }
            if cookie.get("expires") not in (None, "", -1):
                try:
                    item["expires"] = int(float(cookie["expires"]))
                except (TypeError, ValueError):
                    pass
            if item["domain"]:
                normalized.append(item)
        if normalized:
            return normalized
    return []


def capture_profile(url: str, platform: str, account_name: str = "") -> dict[str, Any]:
    if not url:
        return {"ok": False, "status": "missing_url", "error": "缺少主页链接"}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"ok": False, "status": "playwright_unavailable", "error": str(exc)}

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SCREENSHOT_DIR / f"{stamp}-{sanitize_stem(platform)}-{sanitize_stem(account_name or url[:30])}.png"
    body_text = ""
    final_url = url
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 1800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            cookies = load_playwright_cookies(platform)
            if cookies:
                context.add_cookies(cookies)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(5_000)
            final_url = page.url
            try:
                body_text = page.locator("body").inner_text(timeout=5_000)
            except Exception:
                body_text = ""
            page.screenshot(path=str(path), full_page=False, timeout=20_000, animations="disabled")
            browser.close()
    except Exception as exc:
        return {"ok": False, "status": "capture_failed", "error": str(exc), "path": str(path)}
    if not path.exists() or path.stat().st_size <= 0:
        return {"ok": False, "status": "empty_screenshot", "error": "截图文件为空", "path": str(path)}
    return {
        "ok": True,
        "status": "captured",
        "path": str(path),
        "final_url": final_url,
        "visible_text": body_text[:6000],
        "metrics": metrics_from_text(body_text),
    }


def build_brand_brief(fields: dict[str, Any], pending: list[str]) -> str:
    def get(name: str, default: str = "待补充") -> str:
        value = fields.get(name)
        text = str(value).strip() if value not in (None, "") else ""
        return text or default

    lines = [
        f"平台：{get('平台')}",
        f"作者ID：{get('作者ID')}",
        f"账号：{get('账号名称')}",
        f"账号数据：{get('账号数据摘要')}",
        f"项目：{get('项目')}",
        f"Brief：{get('Brief链接')}",
        f"品牌/产品：{get('品牌')} / {get('产品')}",
        f"合作流程：{get('合作流程')}",
        f"档期：{get('具体档期', get('档期'))}",
        f"4月报备图文价格：{get('4月报备图文价格')}",
        f"5月报备图文价格：{get('5月报备图文价格')}",
        f"图文报价：{get('图文报价')}",
        f"视频报价：{get('视频报价')}",
        f"非报备图文/视频单品报价：{get('非报备图文/视频单品报价')}",
        f"报备视频、图文/单品报价：{get('报备视频、图文/单品报价')}",
        f"报备返点：{get('报备返点')}",
        f"保价次月执行：{get('本月下单是否保价次月执行')}",
        f"是否可保价5月：{get('是否可保价5月')}",
        f"排竞时长：{get('排竞时长')}",
        f"非商用授权：{get('非商用授权', '3个月')}",
        f"商用授权：{get('商用授权', '3个月')}",
        f"全渠道授权及时长：{get('全渠道授权及时长')}",
        f"作品保留：{get('作品保留', '2年')}",
        f"笔记默认保留时长：{get('笔记默认保留时长')}",
        f"可同步平台：{get('可同步平台')}",
        f"是否有免费分发平台：{get('是否有免费分发平台')}",
        f"尺码：{get('尺码')}",
        f"收发快递：{get('所在地区是否可以正常收发快递')}",
        f"评论区置顶：{get('评论区置顶')}",
        f"素材收集要求：{get('素材收集要求')}",
    ]
    if pending:
        lines.append("待补充字段：" + "、".join(pending))
    if fields.get("需反问博主字段"):
        lines.append("不要直接回复品牌方：以下字段需先反问博主确认：" + str(fields["需反问博主字段"]))
    return "\n".join(lines)


def account_data_summary(fields: dict[str, Any]) -> str:
    parts = []
    for name in ("赞藏总数", "获赞数", "粉丝数", "关注数", "作品数"):
        value = fields.get(name)
        if value not in (None, ""):
            parts.append(f"{name}：{int(value) if isinstance(value, float) and value.is_integer() else value}")
    return "；".join(parts)


def display_creator_name(fields: dict[str, Any], record_id: str = "") -> str:
    return (
        feishu_plain_text(fields.get("作者ID"))
        or feishu_plain_text(fields.get("账号名称"))
        or record_id
        or "未命名账号"
    )


def canonical_confirmation_field(name: str) -> str:
    return CONFIRMATION_CANONICAL.get(name, name)


def uncertain_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    return bool(AMBIGUOUS_VALUE_RE.search(text))


def blank_confirmation_labels(body: str) -> set[str]:
    labels: set[str] = set()
    for raw_line in body.splitlines():
        line = re.sub(r"^\s*\d+\s*[、.．]\s*", "", raw_line.strip())
        if not line:
            continue
        match = re.match(r"^【?(?P<label>[^】：:]{1,140})】?\s*[：:]\s*(?P<value>.*)$", line)
        if not match:
            continue
        label = canonical_confirmation_field(normalize_label(match.group("label")))
        value = match.group("value").strip()
        if label in CONFIRMATION_FIELDS and not value:
            labels.add(label)
    return labels


def confirmation_required_fields(body: str, fields: dict[str, Any], pending: list[str]) -> list[str]:
    required: set[str] = {canonical_confirmation_field(label) for label in pending}
    required.update(blank_confirmation_labels(body))
    for label in list(CONFIRMATION_FIELDS):
        if label in required:
            continue
        if label in fields and uncertain_value(fields.get(label)):
            required.add(label)
    if (fields.get("具体档期") or fields.get("档期")) and "具体档期" in required and not uncertain_value(fields.get("具体档期") or fields.get("档期")):
        required.discard("具体档期")
    return [label for label in sorted(required) if label in CONFIRMATION_FIELDS]


def build_creator_question_text(fields: dict[str, Any], confirmation_fields: list[str]) -> str:
    if not confirmation_fields:
        return ""
    creator = display_creator_name(fields)
    project = feishu_plain_text(fields.get("项目") or fields.get("品牌") or fields.get("产品"))
    lines = [
        "【商务-ID】需要先反问博主确认",
        f"作者ID：{creator}",
    ]
    if project:
        lines.append(f"项目：{project}")
    lines.append("以下信息不确定，不能直接粘贴给品牌方；请先向博主确认：")
    for index, field in enumerate(confirmation_fields, start=1):
        question = QUESTION_TEMPLATES.get(field, f"{field} 请确认。")
        lines.append(f"{index}. {field}：{question}")
    return "\n".join(lines)


def add_creator_confirmation_fields(body: str, fields: dict[str, Any], pending: list[str]) -> list[str]:
    confirmation_fields = confirmation_required_fields(body, fields, pending)
    if confirmation_fields:
        fields["需反问博主字段"] = "、".join(confirmation_fields)
        fields["反问博主话术"] = build_creator_question_text(fields, confirmation_fields)
        fields["反问博主状态"] = "pending"
    return confirmation_fields


def extract_project_short_name(project: str) -> str:
    return re.split(r"[（(]", project.strip(), maxsplit=1)[0].strip()


def classify_brief_lines(body: str) -> tuple[list[str], list[str]]:
    key_lines: list[str] = []
    notice_lines: list[str] = []
    notice_keywords = ("宝，", "宝,", "觉得你的账号", "将你提报", "有意向的话", "辛苦完善", "目前有一个项目")
    key_keywords = (
        "brief",
        "Brief",
        "PDF",
        "pdf",
        "模板",
        "必看",
        "严格按照",
        "项目",
        "报价",
        "返点",
        "保价",
        "排竞",
        "档期",
        "分发",
        "授权",
        "笔记",
        "置顶",
        "素材",
        "纯净版",
        "发布版",
    )
    for raw_line in body.splitlines():
        line = raw_line.strip().strip("=")
        if not line:
            continue
        line = re.sub(r"^\s*\d+\s*[、.．]\s*", "", line)
        if any(keyword in line for keyword in notice_keywords):
            notice_lines.append(line)
            continue
        normalized = ""
        match = re.match(r"^【?(?P<label>[^】：:]{1,140})】?\s*[：:]\s*(?P<value>.*)$", line)
        if match:
            normalized = normalize_label(match.group("label"))
        if normalized in FIELD_SPECS or re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", line) or any(keyword in line for keyword in key_keywords):
            key_lines.append(line)
            continue
        if extract_urls([line]):
            key_lines.append(line)
        else:
            notice_lines.append(line)
    return key_lines, notice_lines


def add_brief_fields(fields: dict[str, Any], body: str, brief_urls: list[str], brief_files: list[str]) -> None:
    has_brief_context = bool(
        brief_urls
        or brief_files
        or re.search(r"brief|Brief|PDF|pdf|模板|图文要求|撰写模板|严格按照|项目：|项目:", body)
    )
    if not has_brief_context:
        return
    if brief_urls:
        fields["Brief链接"] = "\n".join(brief_urls)
    if brief_files:
        fields["Brief附件路径"] = "\n".join(brief_files)
    key_lines, notice_lines = classify_brief_lines(body)
    author_id = str(fields.get("作者ID") or "").strip()
    if author_id:
        notice_lines = [line for line in notice_lines if line.strip() != author_id]
    if key_lines:
        fields["Brief关键入库信息"] = "\n".join(dict.fromkeys(key_lines))
    if notice_lines:
        fields["Brief告知类信息"] = "\n".join(dict.fromkeys(notice_lines))
    fields["Brief原文"] = body
    fields["Brief收集状态"] = "collected"


def parse_business_text(
    text: str,
    *,
    screenshot_path: str = "",
    account_name: str = "",
    profile_url: str = "",
    brief_files: list[str] | None = None,
) -> dict[str, Any]:
    raw_text = text.strip()
    body = strip_trigger(raw_text)
    urls = extract_urls([body, profile_url])
    profile_urls, brief_urls = split_business_urls(urls)
    if profile_url and profile_url not in profile_urls:
        profile_urls.insert(0, profile_url)
    labeled, pending = extract_labeled_fields(body)
    pending = enrich_brief_structured_fields(body, labeled, pending)
    platform = detect_platform_cn(body, urls, labeled)
    fields: dict[str, Any] = {}
    fields.update(labeled)
    fields["平台"] = platform
    if fields.get("项目"):
        short_project = extract_project_short_name(str(fields["项目"]))
        fields.setdefault("品牌", short_project)
        fields.setdefault("产品", short_project)
    author_id = infer_author_id(body, labeled)
    if author_id:
        fields["作者ID"] = author_id
    if account_name:
        fields["账号名称"] = account_name
    fields.setdefault("账号名称", labeled.get("账号名称") or "")
    if profile_urls:
        fields["主页链接"] = profile_urls[0]
        fields["分享链接"] = profile_urls[0]
    add_brief_fields(fields, body, brief_urls, brief_files or [])
    if screenshot_path:
        fields["主页截图路径"] = screenshot_path
        fields["截图状态"] = "manual_screenshot"
    fields["分享原文"] = body
    fields["商务原文"] = body
    fields["更新时间"] = business_now_iso()
    fields["最近状态"] = "parsed"
    fields["启用"] = True
    fields.update(metrics_from_text(body))
    if any(fields.get(name) for name in ("图文报价", "视频报价", "非报备图文/视频单品报价", "报备视频、图文/单品报价")):
        fields["报价更新时间"] = business_now_iso()
    fields["待补充字段"] = "、".join(pending)
    summary = account_data_summary(fields)
    if summary:
        fields["账号数据摘要"] = summary
    confirmation_fields = add_creator_confirmation_fields(body, fields, pending)
    fields["给品牌方信息"] = build_brand_brief(fields, pending)
    fields["详情JSON"] = {
        "urls": urls,
        "profile_urls": profile_urls,
        "brief_urls": brief_urls,
        "brief_files": brief_files or [],
        "pending_fields": pending,
        "confirmation_fields": confirmation_fields,
        "parsed_at": business_now_iso(),
    }
    return {"fields": fields, "pending_fields": pending, "urls": urls, "profile_urls": profile_urls, "brief_urls": brief_urls}


def table_url_from_args(value: str = "") -> str:
    return value.strip() or feishu_table_url_from_env(*URL_ENV_NAMES)


def field_urls(value: Any) -> list[str]:
    if isinstance(value, dict):
        return extract_urls([str(value.get("link") or ""), str(value.get("text") or "")])
    if isinstance(value, list):
        urls: list[str] = []
        for item in value:
            urls.extend(field_urls(item))
        return urls
    return extract_urls([feishu_plain_text(value)])


def same_record(fields: dict[str, Any], candidate: dict[str, Any]) -> bool:
    platform_id = str(fields.get("平台ID") or fields.get("平台账号ID") or "").strip()
    candidate_platform_id = feishu_plain_text(candidate.get("平台ID") or candidate.get("平台账号ID"))
    platform = str(fields.get("平台") or "").strip()
    candidate_platform = feishu_plain_text(candidate.get("平台"))
    if platform_id and candidate_platform_id:
        if platform and candidate_platform:
            return platform == candidate_platform and platform_id == candidate_platform_id
        return platform_id == candidate_platform_id
    urls = set()
    for name in ("主页链接", "分享链接"):
        urls.update(field_urls(fields.get(name)))
    candidate_urls = set()
    for name in ("主页链接", "分享链接"):
        candidate_urls.update(field_urls(candidate.get(name)))
    if urls and candidate_urls and urls.intersection(candidate_urls):
        return True
    author_id = str(fields.get("作者ID") or "").strip()
    account = str(fields.get("账号名称") or "").strip()
    if author_id and platform and author_id == feishu_plain_text(candidate.get("作者ID")) and platform == feishu_plain_text(candidate.get("平台")):
        return True
    return bool(account and platform and account == feishu_plain_text(candidate.get("账号名称")) and platform == feishu_plain_text(candidate.get("平台")))


def coerce_for_feishu(fields: dict[str, Any], field_types: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in field_types or value in (None, "", []):
            continue
        if field_types[key] == 7:
            payload[key] = bool(value)
        else:
            coerced = feishu_coerce_value(value, field_types[key])
            if coerced not in (None, "", []):
                payload[key] = coerced
    return payload


def merge_standard_business_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_standard_fields(fields)
    return select_fields_for_write(fields, normalized_fields=normalized)


def create_record(bitable_url: str, fields: dict[str, Any], *, token: str | None = None) -> str:
    fields = merge_standard_business_fields(fields)
    app_token, table_id, token = feishu_bitable_refs(bitable_url, token)
    feishu_ensure_fields(app_token, table_id, token, FIELD_SPECS)
    field_types = feishu_field_types(app_token, table_id, token)
    payload_fields = coerce_for_feishu(fields, field_types)
    if not payload_fields:
        raise RuntimeError("没有可写入飞书的字段")
    resp = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        headers=feishu_headers(token),
        json={"fields": payload_fields},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"创建飞书记录失败：{payload}")
    return str(payload.get("data", {}).get("record", {}).get("record_id") or "")


def update_record(bitable_url: str, record_id: str, fields: dict[str, Any], *, token: str | None = None) -> None:
    if not record_id:
        return
    fields = merge_standard_business_fields(fields)
    app_token, table_id, token = feishu_bitable_refs(bitable_url, token)
    feishu_ensure_fields(app_token, table_id, token, FIELD_SPECS)
    field_types = feishu_field_types(app_token, table_id, token)
    payload_fields = coerce_for_feishu(fields, field_types)
    if not payload_fields:
        return
    resp = requests.put(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        json={"fields": payload_fields},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"更新飞书记录失败：{payload}")


def upsert_record(bitable_url: str, fields: dict[str, Any], *, require: bool) -> dict[str, Any]:
    if not bitable_url:
        if require:
            raise RuntimeError("缺少商务账号多维表格链接：设置 MEDIA_OS_BUSINESS_URL 或传 --feishu-url")
        return {"ok": False, "skipped": True, "reason": "missing_feishu_url"}
    fields = merge_standard_business_fields(fields)
    token = feishu_tenant_access_token()
    records = feishu_list_records(bitable_url, token=token)
    existing = next((record for record in records if same_record(fields, record.get("fields") or {})), None)
    if existing:
        update_record(bitable_url, existing["record_id"], fields, token=token)
        return {"ok": True, "action": "updated", "record_id": existing["record_id"], "table_url": bitable_url}
    record_id = create_record(bitable_url, fields, token=token)
    return {"ok": True, "action": "created", "record_id": record_id, "table_url": bitable_url}


def save_local(payload: dict[str, Any]) -> str:
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    path = RECORD_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{sanitize_stem(str(payload.get('account_name') or 'id-business'))}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def ingest(args: argparse.Namespace) -> dict[str, Any]:
    load_id_business_env_files()
    text = args.text or ""
    if args.stdin:
        text = sys.stdin.read()
    if not text.strip():
        raise SystemExit("missing text; pass --text or --stdin")
    if not text.lstrip().startswith("【商务-ID】"):
        raise SystemExit("商务-ID workflow requires explicit 【商务-ID】 trigger")

    parsed = parse_business_text(
        text,
        screenshot_path=args.screenshot,
        account_name=args.account_name,
        profile_url=args.profile_url,
        brief_files=args.brief_file,
    )
    fields = parsed["fields"]
    capture: dict[str, Any] = {}
    profile_url = str(fields.get("主页链接") or "").strip()
    if not args.no_screenshot and not args.screenshot and profile_url:
        capture = capture_profile(profile_url, str(fields.get("平台") or ""), display_creator_name(fields))
        fields["截图状态"] = capture.get("status", "")
        if capture.get("path"):
            fields["主页截图路径"] = capture["path"]
        if capture.get("final_url"):
            fields["主页链接"] = capture["final_url"]
        if capture.get("visible_text"):
            fields["主页可见文本"] = capture["visible_text"]
        if isinstance(capture.get("metrics"), dict):
            fields.update(capture["metrics"])
        if capture.get("ok"):
            fields["最近状态"] = "captured"
        else:
            fields["最近状态"] = "capture_failed"
            fields["最近错误"] = str(capture.get("error") or "")
    summary = account_data_summary(fields)
    if summary:
        fields["账号数据摘要"] = summary
    fields["给品牌方信息"] = build_brand_brief(fields, parsed["pending_fields"])
    table_url = table_url_from_args(args.feishu_url)
    if args.require_feishu and not args.dry_run and not table_url:
        raise RuntimeError("缺少商务账号多维表格链接：设置 MEDIA_OS_BUSINESS_URL 或传 --feishu-url")
    confirmation_notify: dict[str, Any] = {}
    if args.notify_confirmation and fields.get("需反问博主字段") and fields.get("反问博主话术"):
        fields["反问博主时间"] = business_now_iso()
        confirmation_notify = notify_social(str(fields["反问博主话术"]), dry_run=args.dry_run)
        fields["反问博主状态"] = "dry_run" if args.dry_run else ("sent" if confirmation_notify.get("ok") else "notify_failed")
        fields["反问博主通知结果"] = json.dumps(confirmation_notify, ensure_ascii=False)[:3000]
    fields["详情JSON"] = {
        "urls": parsed.get("urls") or [],
        "profile_urls": parsed.get("profile_urls") or [],
        "brief_urls": parsed.get("brief_urls") or [],
        "brief_files": args.brief_file or [],
        "pending_fields": parsed.get("pending_fields") or [],
        "confirmation_fields": (str(fields.get("需反问博主字段") or "").split("、") if fields.get("需反问博主字段") else []),
        "confirmation_notify": confirmation_notify,
        "capture": capture,
        "ingested_at": business_now_iso(),
    }

    feishu = upsert_record(table_url, fields, require=args.require_feishu) if not args.dry_run else {"ok": False, "skipped": True, "reason": "dry_run"}
    local_path = save_local({"fields": fields, "feishu": feishu, "capture": capture, "account_name": display_creator_name(fields)})
    return {
        "ok": bool(feishu.get("ok")) if args.require_feishu else True,
        "fields": fields,
        "feishu": feishu,
        "local_path": local_path,
        "capture": capture,
    }


def parse_update_due(value: Any) -> bool:
    text = feishu_plain_text(value)
    if not text:
        return True
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            number = int(float(text))
            dt = datetime.fromtimestamp(number / 1000 if number > 10_000_000_000 else number, timezone.utc)
        except (TypeError, ValueError):
            return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt.astimezone(timezone.utc) >= timedelta(hours=24)


def local_today(value: str = ""):
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.now(LOCAL_TZ).date()


def quote_text(fields: dict[str, Any], name: str) -> str:
    return feishu_plain_text(fields.get(name)).strip()


def missing_quote_fields(fields: dict[str, Any]) -> list[str]:
    combined_quote = quote_text(fields, "非报备图文/视频单品报价") or quote_text(fields, "报备视频、图文/单品报价")
    missing: list[str] = []
    if not quote_text(fields, "图文报价") and not combined_quote:
        missing.append("图文报价")
    if not quote_text(fields, "视频报价") and not combined_quote:
        missing.append("视频报价")
    return missing


def monthly_quote_reminder_due(fields: dict[str, Any], *, today=None, reminder_day: int = 1) -> tuple[bool, list[str], str]:
    today = today or local_today()
    month_key = today.strftime("%Y-%m")
    missing = missing_quote_fields(fields)
    if today.day != reminder_day or not missing:
        return False, missing, month_key
    reminded_month = quote_text(fields, "报价提醒月份")
    return reminded_month != month_key, missing, month_key


def quote_reminder_message(fields: dict[str, Any], *, record_id: str, missing: list[str], month_key: str) -> str:
    platform = quote_text(fields, "平台") or "未识别平台"
    account = display_creator_name(fields, record_id)
    platform_account = quote_text(fields, "账号名称")
    brand = quote_text(fields, "品牌")
    missing_text = "、".join(missing)
    lines = [
        "【商务-ID】每月报价更新提醒",
        f"月份：{month_key}",
        f"平台：{platform}",
        f"作者ID：{account}",
    ]
    if platform_account and platform_account != account:
        lines.append(f"平台账号：{platform_account}")
    if brand:
        lines.append(f"最近品牌：{brand}")
    lines.extend(
        [
            f"缺少报价：{missing_text}",
            "请补充本月对应平台的图文报价和视频报价。",
            f"建议回复格式：{platform} 图文报价：；{platform} 视频报价：",
        ]
    )
    if record_id:
        lines.append(f"飞书记录 ID：{record_id}")
    return "\n".join(lines)


def notify_social(message: str, *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"ok": False, "skipped": True, "reason": "dry_run", "message": message}
    target = next((os.getenv(name, "").strip() for name in NOTIFY_TARGET_ENV_NAMES if os.getenv(name, "").strip()), "")
    if target:
        cmd = [
            "openclaw",
            "message",
            "send",
            "--channel",
            "feishu",
            "--account",
            "social",
            "--target",
            target,
            "--message",
            message,
            "--json",
        ]
    else:
        cmd = [
            "openclaw",
            "agent",
            "--agent",
            os.getenv("ID_BUSINESS_NOTIFY_AGENT", "feishu-social"),
            "--message",
            message,
            "--json",
            "--timeout",
            "1800",
        ]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=1860)
    stdout_summary = summarize_openclaw_cli_output(completed.stdout)
    return {
        "ok": completed.returncode == 0,
        "command": cmd[:4],
        "stdout_summary": stdout_summary,
        "stderr": completed.stderr[-1000:],
    }


def summarize_openclaw_cli_output(stdout: str) -> str:
    text = (stdout or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
        payloads = result.get("payloads") if isinstance(result, dict) else None
        if isinstance(payloads, list):
            texts = [
                str(payload.get("text")).strip()
                for payload in payloads
                if isinstance(payload, dict) and payload.get("text")
            ]
            if texts:
                return "\n".join(texts)[:1000]
        meta = result.get("meta") if isinstance(result, dict) else None
        if isinstance(meta, dict):
            for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
                value = meta.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:1000]
        run_id = parsed.get("runId") or parsed.get("id") or ""
        status = parsed.get("status") or ""
        return f"OpenClaw structured output status={status} runId={run_id}".strip()[:1000]
    if text.startswith("{") or text.startswith("["):
        return "OpenClaw structured output without visible text"
    return text[-1000:]


def record_enabled(fields: dict[str, Any]) -> bool:
    if "启用" not in fields:
        return True
    return feishu_bool(fields.get("启用"), default=True)


def poll(args: argparse.Namespace) -> dict[str, Any]:
    load_id_business_env_files()
    table_url = table_url_from_args(args.feishu_url)
    if not table_url:
        raise RuntimeError("缺少商务账号多维表格链接：设置 MEDIA_OS_BUSINESS_URL 或传 --feishu-url")
    records = feishu_list_records(table_url, view_id=args.view_id)
    if args.limit:
        records = records[: args.limit]
    today = local_today(args.today)
    updated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    quote_reminders: list[dict[str, Any]] = []
    skipped = 0
    for record in records:
        fields = record.get("fields") or {}
        record_id = str(record.get("record_id") or "")
        if not record_enabled(fields):
            skipped += 1
            continue
        quote_due, missing_quotes, quote_month = monthly_quote_reminder_due(
            fields,
            today=today,
            reminder_day=args.quote_reminder_day,
        )
        if quote_due and not args.no_quote_reminder and args.notify:
            message = quote_reminder_message(fields, record_id=record_id, missing=missing_quotes, month_key=quote_month)
            notify_result = notify_social(message, dry_run=args.dry_run)
            reminder_fields = {
                "报价提醒状态": "dry_run" if args.dry_run else ("sent" if notify_result.get("ok") else "notify_failed"),
            }
            if args.dry_run or notify_result.get("ok"):
                reminder_fields["报价提醒月份"] = quote_month
            if not args.dry_run:
                update_record(table_url, record_id, reminder_fields)
            quote_reminders.append(
                {
                    "record_id": record_id,
                    "account": display_creator_name(fields, record_id),
                    "platform": feishu_plain_text(fields.get("平台")),
                    "missing": missing_quotes,
                    "month": quote_month,
                    "status": reminder_fields["报价提醒状态"],
                }
            )
        if not args.force and not parse_update_due(fields.get("更新时间")):
            skipped += 1
            continue
        profile_urls = field_urls(fields.get("主页链接")) or field_urls(fields.get("分享链接"))
        if not profile_urls:
            error_fields = {
                "更新时间": business_now_iso(),
                "最近状态": "missing_profile_url",
                "最近错误": "缺少主页链接/分享链接，需要补充新链接",
            }
            if not args.dry_run:
                update_record(table_url, record_id, error_fields)
            errors.append({"record_id": record_id, "account": display_creator_name(fields, record_id), "error": error_fields["最近错误"]})
            if args.notify:
                notify_social(f"【商务-ID】账号缺少主页链接，需要补充：{display_creator_name(fields, record_id)}", dry_run=args.dry_run)
            continue
        platform = feishu_plain_text(fields.get("平台")) or detect_platform_cn("", profile_urls, {})
        account_name = feishu_plain_text(fields.get("账号名称"))
        display_name = display_creator_name(fields, record_id)
        capture = capture_profile(profile_urls[0], platform, account_name or display_name) if not args.no_screenshot else {"ok": True, "status": "skipped"}
        update_fields: dict[str, Any] = {
            "更新时间": business_now_iso(),
            "截图状态": capture.get("status", ""),
            "最近状态": "captured" if capture.get("ok") else "capture_failed",
            "最近错误": "" if capture.get("ok") else str(capture.get("error") or ""),
        }
        if capture.get("path"):
            update_fields["主页截图路径"] = capture["path"]
        if capture.get("final_url"):
            update_fields["主页链接"] = capture["final_url"]
        if capture.get("visible_text"):
            update_fields["主页可见文本"] = capture["visible_text"]
        if isinstance(capture.get("metrics"), dict):
            update_fields.update(capture["metrics"])
        combined = {**{key: feishu_plain_text(value) for key, value in fields.items()}, **update_fields}
        summary = account_data_summary(combined)
        if summary:
            update_fields["账号数据摘要"] = summary
        update_fields["详情JSON"] = {"capture": capture, "polled_at": business_now_iso()}
        if not args.dry_run:
            update_record(table_url, record_id, update_fields)
        item = {"record_id": record_id, "account": display_name, "platform_account": account_name, "status": update_fields["最近状态"], "screenshot": update_fields.get("主页截图路径", "")}
        updated.append(item)
        if not capture.get("ok"):
            errors.append({**item, "error": update_fields["最近错误"]})
            if args.notify:
                notify_social(
                    "【商务-ID】账号主页更新异常，需要补充/更新链接：\n"
                    f"- 作者ID：{display_name}\n"
                    f"- 平台账号：{account_name or '未记录'}\n"
                    f"- 平台：{platform}\n"
                    f"- 当前链接：{profile_urls[0]}\n"
                    f"- 错误：{update_fields['最近错误']}",
                    dry_run=args.dry_run,
                )
    return {
        "ok": not errors,
        "updated": updated,
        "errors": errors,
        "quote_reminders": quote_reminders,
        "skipped": skipped,
        "table_url": table_url,
    }


def update_link(args: argparse.Namespace) -> dict[str, Any]:
    load_id_business_env_files()
    table_url = table_url_from_args(args.feishu_url)
    if not table_url:
        raise RuntimeError("缺少商务账号多维表格链接：设置 MEDIA_OS_BUSINESS_URL 或传 --feishu-url")
    fields = {"主页链接": args.url, "分享链接": args.url, "更新时间": business_now_iso(), "最近状态": "link_updated", "最近错误": ""}
    update_record(table_url, args.record_id, fields)
    return {"ok": True, "record_id": args.record_id, "updated_fields": fields}


def install_cron(args: argparse.Namespace) -> dict[str, Any]:
    command = ["/home/ubuntu/selfmedia-tools/tools/openclaw_media/id_business.py", "poll", "--notify", "--require-feishu"]
    if args.feishu_url:
        command.extend(["--feishu-url", args.feishu_url])
    cron_command = [
        "openclaw",
        "cron",
        "add",
        "--name",
        args.name,
        "--agent",
        "feishu-media",
        "--cron",
        args.cron,
        "--tz",
        args.tz,
        "--session",
        "isolated",
        "--tools",
        "exec",
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--expect-final",
        "--no-deliver",
        "--message",
        "请执行这个本机 商务-ID账号 24h 轮询命令；若今天是每月 1 日且报价缺失，也要通过 social Bot 提醒我补对应平台的图文/视频报价。只返回飞书更新结果、报价提醒、异常账号和阻塞点：\n\n" + " ".join(command),
        "--json",
    ]
    if args.disabled:
        cron_command.append("--disabled")
    completed = subprocess.run(cron_command, cwd=str(MEDIA_ROOT), text=True, capture_output=True, check=False, timeout=90)
    return {
        "ok": completed.returncode == 0,
        "stdout_summary": summarize_openclaw_cli_output(completed.stdout),
        "stderr": completed.stderr[-1000:],
        "command": cron_command,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="商务-ID creator profile and brand inquiry workflow.")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_parser = sub.add_parser("ingest", help="Parse 【商务-ID】 text, capture profile screenshot, upsert Feishu record.")
    ingest_parser.add_argument("--text", default="")
    ingest_parser.add_argument("--stdin", action="store_true")
    ingest_parser.add_argument("--feishu-url", default="")
    ingest_parser.add_argument("--profile-url", default="")
    ingest_parser.add_argument("--screenshot", default="")
    ingest_parser.add_argument("--brief-file", action="append", default=[])
    ingest_parser.add_argument("--account-name", default="")
    ingest_parser.add_argument("--notify-confirmation", action="store_true")
    ingest_parser.add_argument("--require-feishu", action="store_true")
    ingest_parser.add_argument("--dry-run", action="store_true")
    ingest_parser.add_argument("--no-screenshot", action="store_true")
    ingest_parser.set_defaults(func=ingest)

    poll_parser = sub.add_parser("poll", help="Poll Feishu business creator table and refresh profile screenshots every 24h.")
    poll_parser.add_argument("--feishu-url", default="")
    poll_parser.add_argument("--view-id", default="")
    poll_parser.add_argument("--limit", type=int, default=0)
    poll_parser.add_argument("--force", action="store_true")
    poll_parser.add_argument("--notify", action="store_true")
    poll_parser.add_argument("--dry-run", action="store_true")
    poll_parser.add_argument("--no-screenshot", action="store_true")
    poll_parser.add_argument("--no-quote-reminder", action="store_true")
    poll_parser.add_argument("--quote-reminder-day", type=int, default=1)
    poll_parser.add_argument("--today", default="", help="Override local date for tests, YYYY-MM-DD.")
    poll_parser.add_argument("--require-feishu", action="store_true")
    poll_parser.set_defaults(func=poll)

    link_parser = sub.add_parser("update-link", help="Update one Feishu row with a new profile/share link.")
    link_parser.add_argument("--feishu-url", default="")
    link_parser.add_argument("--record-id", required=True)
    link_parser.add_argument("--url", required=True)
    link_parser.set_defaults(func=update_link)

    cron_parser = sub.add_parser("install-cron", help="Install 24h poll cron through OpenClaw.")
    cron_parser.add_argument("--name", default="id-business-24h-poll")
    cron_parser.add_argument("--cron", default="0 9 * * *")
    cron_parser.add_argument("--tz", default="Asia/Shanghai")
    cron_parser.add_argument("--timeout-seconds", type=int, default=1800)
    cron_parser.add_argument("--feishu-url", default="")
    cron_parser.add_argument("--disabled", action="store_true")
    cron_parser.set_defaults(func=install_cron)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print_json({"ok": False, "error": exc.code})
            return 1
        raise
    except Exception as exc:
        print_json({"ok": False, "error": str(exc), "command": args.command})
        return 1
    print_json(result)
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
