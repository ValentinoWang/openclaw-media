from __future__ import annotations

import html
import re
import urllib.parse
from typing import Any


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
    variants = [raw, urllib.parse.unquote(raw), html.unescape(raw), html.unescape(urllib.parse.unquote(raw))]
    result: list[str] = []
    for item in variants:
        if item not in result:
            result.append(item)
    return result


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
    if "post_count" not in payload:
        post_match = re.search(r"作品\s*\n\s*([0-9.]+[万wWkK千]?)", "\n".join(lines))
        if post_match:
            payload["post_count"] = parse_chinese_count(post_match.group(1))
    bio = public_bio_from_lines(lines)
    if bio:
        payload["bio"] = bio
    visible_titles = visible_post_titles(lines)
    if visible_titles:
        payload["visible_post_titles"] = visible_titles
    return payload


def public_bio_from_lines(lines: list[str]) -> str:
    id_index = next((idx for idx, line in enumerate(lines) if "抖音号" in line), -1)
    if id_index < 0:
        return ""
    for line in lines[id_index + 1 : id_index + 10]:
        if line in {"更多", "分享主页", "私信", "关注", "作品", "推荐", "喜欢"}:
            continue
        if "IP属地" in line or re.fullmatch(r"\d+岁", line):
            continue
        if len(line) >= 6:
            return line.strip()
    return ""


def visible_post_titles(lines: list[str], *, limit: int = 8) -> list[str]:
    titles: list[str] = []
    for line in lines:
        if len(titles) >= limit:
            break
        if len(line) < 8:
            continue
        if any(marker in line for marker in ("#", "清华", "博士", "中长跑", "马拉松", "训练")):
            if line not in titles:
                titles.append(line[:300])
    return titles


def parse_douyin_embedded_profile_data(html_text: str, platform_id: str) -> dict[str, Any]:
    platform_id = str(platform_id or "").strip()
    if not html_text or not platform_id:
        return {}
    for blob in text_variants(html_text):
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
            payload: dict[str, Any] = {"author_id": platform_id, "metric_source": "embedded_profile_data"}
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
            useful_fields = {
                "account_name",
                "bio",
                "fans_count",
                "post_count",
                "following_count",
                "total_favorited",
            }
            if any(key in payload for key in useful_fields):
                return payload
    return {}


def merge_profile_facts(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    result = dict(primary)
    for key, value in secondary.items():
        if value not in (None, "", [], {}) and result.get(key) in (None, "", [], {}):
            result[key] = value
    return result


def current_metrics_summary(profile: dict[str, Any]) -> str:
    parts = []
    if isinstance(profile.get("fans_count"), int):
        parts.append(f"粉丝数 {profile['fans_count']} 人")
    if isinstance(profile.get("following_count"), int):
        parts.append(f"关注 {profile['following_count']}")
    if isinstance(profile.get("total_favorited"), int):
        parts.append(f"获赞 {profile['total_favorited']}")
    if isinstance(profile.get("post_count"), int):
        parts.append(f"作品 {profile['post_count']}")
    if isinstance(profile.get("note_count"), int):
        parts.append(f"笔记 {profile['note_count']}")
    return "；".join(parts)
