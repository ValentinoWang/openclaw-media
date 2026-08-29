"""Shared helpers for normalizing and classifying activity Brief links.

Consolidated from two near-duplicate implementations (activity_daily.py's
``ActivityDailyMixin._activity_*`` methods and
runtime/maintenance/backfills/backfill_activity_boost_date.py's free
functions of the same shape) -- see the url-12 dedup audit.

``link_field_name``'s keyword set uses the anchored form from
backfill_activity_boost_date.py ("wiki/", "docx/", "sheets/", "forms.",
"wjx.cn") rather than activity_daily.py's bare-word form ("wiki", "docx",
"sheets", "forms", "wjx"). The bare-word form can misfire on ordinary
label text that happens to contain one of those words without it being an
actual link of that kind (e.g. a label mentioning "forms" or "sheets" in
prose); the anchored form only matches the URL-shaped fragment.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

_TRAILING_PUNCTUATION = "，。；、.）)]】"


def canonical_link_url(url: str) -> str:
    """Unwrap a link-shortener "text=" redirect fragment down to its real target URL."""
    cleaned = str(url or "").strip().rstrip(_TRAILING_PUNCTUATION)
    text_fragment = re.search(r"(?:[#?&](?::~:)?text=)([^\s]+)", cleaned)
    if text_fragment:
        decoded = unquote(text_fragment.group(1)).strip().rstrip(_TRAILING_PUNCTUATION)
        nested = re.search(r"https?://\S+", decoded)
        if nested:
            cleaned = nested.group(0).rstrip(_TRAILING_PUNCTUATION)
    return cleaned


def normalize_link_items(links: Any) -> list[dict[str, str]]:
    """Normalize a links value (free text, or a list of dicts/strings) into
    a deduped ``[{"label": ..., "url": ...}]`` list, in first-seen order."""
    raw_items: list[Any]
    if isinstance(links, str):
        raw_items = []
        for line in links.splitlines():
            line = line.strip(" -\t")
            if not line:
                continue
            match = re.search(r"(https?://\S+)", line)
            if not match:
                continue
            raw_items.append(
                {
                    "label": line[: match.start()].rstrip("：: -\t") or "来源链接",
                    "url": canonical_link_url(match.group(1)),
                }
            )
    elif isinstance(links, list):
        raw_items = links
    else:
        raw_items = []
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_items:
        if isinstance(item, dict):
            label = str(item.get("label") or "来源链接").strip() or "来源链接"
            url = canonical_link_url(str(item.get("url") or ""))
        else:
            text = str(item or "").strip()
            match = re.search(r"(https?://\S+)", text)
            if not match:
                continue
            label = text[: match.start()].rstrip("：: -\t") or "来源链接"
            url = canonical_link_url(match.group(1))
        if url and url not in seen:
            seen.add(url)
            normalized.append({"label": label, "url": url})
    return normalized


def link_field_name(label: str, url: str) -> str:
    """Classify a (label, url) pair into a Feishu Brief link field name, or "" if none fits."""
    text = f"{label} {url}".lower()
    if any(marker in text for marker in ("爆款", "示范", "范式", "参考", "douyin.com/note")):
        return "爆款示范链接"
    if any(marker in text for marker in ("返稿", "报名", "表单", "报名表", "sheets/", "forms.", "wjx.cn")):
        return "返稿链接"
    if any(marker in text for marker in ("活动文档", "文档", "详情", "规则", "brief", "wiki/", "docx/")):
        return "活动文档链接"
    return ""


def split_link_fields(links: Any) -> dict[str, str]:
    """Group normalized links by their classified field name into "label：url" blocks."""
    grouped: dict[str, list[str]] = {}
    for item in normalize_link_items(links):
        field_name = link_field_name(item["label"], item["url"])
        if not field_name:
            continue
        grouped.setdefault(field_name, []).append(f"{item['label']}：{item['url']}")
    return {name: "\n".join(values) for name, values in grouped.items() if values}
