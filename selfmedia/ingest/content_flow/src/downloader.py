from __future__ import annotations

from dataclasses import dataclass
import json
import os
import random
import re
import subprocess
import time
from html import unescape
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
import requests

from .config import Settings
from .storage import (
    MediaPaths,
    ensure_media_paths,
    list_image_files,
    load_json,
    load_text,
    media_exists,
    save_text,
)
from .utils import extract_douyin_id, is_direct_video_url, normalize_video_url, summarize_url


ProgressFn = Callable[[str, int, str], None]
os.environ.setdefault("PW_TEST_SCREENSHOT_NO_FONTS_READY", "1")

MOBILE_SAFARI_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

INTERACTION_COUNT_KEYS = ("like_count", "collect_count", "comment_count", "share_count")
DOUYIN_TRUSTED_STAT_SOURCES = {
    "like_count": "aweme_detail.statistics.digg_count",
    "collect_count": "aweme_detail.statistics.collect_count",
    "comment_count": "aweme_detail.statistics.comment_count",
    "share_count": "aweme_detail.statistics.share_count",
}
DOUYIN_VISIBLE_TEXT_STAT_SOURCES = {
    "like_count": "douyin_webpage_visible_text.like_count",
    "comment_count": "douyin_webpage_visible_text.comment_count",
    "collect_count": "douyin_webpage_visible_text.collect_count",
    "share_count": "douyin_webpage_visible_text.share_count",
}
DOUYIN_TRUSTED_STAT_SOURCE_PREFIXES = (
    "aweme_detail.statistics.",
    "aweme_post.statistics.",
    "iesdouyin_iteminfo.statistics.",
    "douyin_share_html.statistics.",
)
DOUYIN_STAT_KEY_ALIASES = {
    "like_count": ("digg_count", "diggCount", "like_count", "likeCount", "liked_count", "likedCount"),
    "collect_count": (
        "collect_count",
        "collectCount",
        "collected_count",
        "collectedCount",
        "favorite_count",
        "favoriteCount",
    ),
    "comment_count": ("comment_count", "commentCount", "comments_count", "commentsCount"),
    "share_count": ("share_count", "shareCount", "forward_count", "forwardCount"),
}
XHS_STAT_KEY_ALIASES = {
    "like_count": ("likedCount", "likeCount", "liked_count", "like_count", "likes"),
    "collect_count": (
        "collectedCount",
        "collectCount",
        "collected_count",
        "collect_count",
        "favoriteCount",
        "favorite_count",
    ),
    "comment_count": ("commentCount", "comment_count", "commentsCount", "comments_count"),
    "share_count": ("shareCount", "share_count", "sharedCount", "shared_count"),
}
DOUYIN_STATS_NOTICE = (
    "作品级互动数据未完整取到；仅写入 aweme_detail.statistics 中明确命中的字段，"
    "缺失字段请使用作品截图 OCR 复核，或更新 cookie/抖音接口。"
)


class _SkipPlaywright(Exception):
    pass


PLATFORM_COOKIE_DOMAINS = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhscdn.com"),
}


def _report_progress(progress: Optional[ProgressFn], percent: int, message: str) -> None:
    if not progress:
        return
    try:
        progress("downloader", percent, message)
    except Exception:
        return


def _scale_percent(local_ratio: float, start: int, end: int) -> int:
    bounded = max(0.0, min(1.0, local_ratio))
    return start + int((end - start) * bounded)


def _platform_cookie_path(platform_key: str, settings: Settings) -> str:
    if platform_key == "douyin":
        return settings.douyin_cookies_json_path
    if platform_key == "xiaohongshu":
        return settings.xiaohongshu_cookies_json_path
    return ""


def _domain_matches(cookie_domain: str, expected_domains: tuple[str, ...]) -> bool:
    normalized = cookie_domain.lstrip(".").lower()
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in expected_domains)


def _resolve_cookie_json_path(cookie_path: str) -> str:
    """Resolve cookie json path from env.

    Absolute paths are used as-is. Relative paths are resolved against the
    current working directory first, then against the content-flow project root
    so service runs from another cwd still read content-flow/private/*.json.
    """
    expanded_path = os.path.expanduser(cookie_path)
    if os.path.isabs(expanded_path):
        return expanded_path

    cwd_path = os.path.abspath(expanded_path)
    if os.path.isfile(cwd_path):
        return cwd_path

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(project_root, expanded_path)


def load_platform_cookie_items(platform_key: str, settings: Settings) -> list[dict]:
    cookie_path = _platform_cookie_path(platform_key, settings)
    if not cookie_path:
        return []
    resolved_path = _resolve_cookie_json_path(cookie_path)
    if not os.path.isfile(resolved_path):
        return []
    try:
        with open(resolved_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return []

    if isinstance(data, dict):
        raw_items = data.get("cookies") or []
    elif isinstance(data, list):
        raw_items = data
    else:
        raw_items = []

    expected_domains = PLATFORM_COOKIE_DOMAINS.get(platform_key, ())
    items: list[dict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        domain = str(item.get("domain") or item.get("host") or "").strip()
        if not name or not domain or not _domain_matches(domain, expected_domains):
            continue
        normalized = dict(item)
        normalized["name"] = name
        normalized["value"] = value
        normalized["domain"] = domain
        items.append(normalized)
    return items


def load_platform_cookie_dict(platform_key: str, settings: Settings) -> dict:
    return {
        str(item["name"]): str(item.get("value") or "")
        for item in load_platform_cookie_items(platform_key, settings)
        if item.get("name")
    }


def add_platform_cookies_to_context(context, platform_key: str, settings: Settings) -> None:
    cookies = []
    for item in load_platform_cookie_items(platform_key, settings):
        cookie = {
            "name": str(item["name"]),
            "value": str(item.get("value") or ""),
            "domain": str(item["domain"]),
            "path": str(item.get("path") or "/"),
            "httpOnly": bool(item.get("httpOnly", False)),
            "secure": bool(item.get("secure", True)),
        }
        expires = item.get("expirationDate", item.get("expires"))
        if isinstance(expires, (int, float)) and expires > 0:
            cookie["expires"] = float(expires)
        same_site = str(item.get("sameSite") or "").lower()
        if same_site in ("strict",):
            cookie["sameSite"] = "Strict"
        elif same_site in ("lax",):
            cookie["sameSite"] = "Lax"
        elif same_site in ("none", "no_restriction", "no-restriction"):
            cookie["sameSite"] = "None"
        cookies.append(cookie)
    if cookies:
        try:
            context.add_cookies(cookies)
        except Exception:
            return


def playwright_proxy(settings: Settings) -> Optional[dict]:
    server = (settings.playwright_proxy_server or "").strip()
    if not server:
        return None
    return {"server": server}


@dataclass(frozen=True)
class MediaResult:
    media_type: str
    video_path: Optional[str]
    audio_path: Optional[str]
    image_paths: list[str]
    caption: str
    stats: dict


def clean_douyin_url(url: str) -> str:
    if not url:
        return url
    url = url.strip()
    url = re.sub(r"(https?://)\s+", r"\1", url)
    match = re.search(r"https?://[^\s]+", url)
    if match:
        url = match.group(0).strip(")>.，,。")

    lowered = url.lower()
    if "xhslink.com" in lowered:
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": MOBILE_SAFARI_USER_AGENT,
                },
                allow_redirects=True,
                timeout=10,
            )
            if response.url:
                return response.url
        except requests.RequestException:
            return url

    if "xiaohongshu.com" in lowered:
        return url

    if "douyin.com" not in lowered and "iesdouyin.com" not in lowered:
        return url

    final_url = url
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": MOBILE_SAFARI_USER_AGENT,
            },
            allow_redirects=True,
            timeout=10,
        )
        if response.url:
            final_url = response.url
    except requests.RequestException:
        return url

    canonicalize = os.getenv("DOUYIN_CANONICALIZE", "0").lower() in ("1", "true", "yes")
    if not canonicalize:
        return final_url

    kind, item_id = extract_douyin_id(final_url)
    if not item_id:
        kind, item_id = extract_douyin_id(url)
    if not item_id:
        return final_url

    if kind == "note":
        return f"https://www.douyin.com/note/{item_id}"

    return f"https://www.douyin.com/video/{item_id}"


def _is_xhs_url(url: str) -> bool:
    lowered = url.lower()
    return "xiaohongshu.com" in lowered or "xhslink.com" in lowered


def _extract_xhs_initial_state_blob(html: str) -> Optional[str]:
    marker = "window.__INITIAL_STATE__"
    start = html.find(marker)
    if start == -1:
        return None
    eq = html.find("=", start + len(marker))
    if eq == -1:
        return None
    start = eq + 1
    while start < len(html) and html[start] in " \t\r\n":
        start += 1
    end = html.find("</script>", start)
    if end == -1:
        return None
    blob = html[start:end].strip()
    if blob.endswith(";"):
        blob = blob[:-1]
    return blob.strip() if blob else None


def _parse_xhs_initial_state(html: str) -> Optional[dict]:
    blob = _extract_xhs_initial_state_blob(html)
    if not blob:
        return None
    normalized = re.sub(r"\bundefined\b", "null", blob)
    normalized = re.sub(r"\bNaN\b", "0", normalized)
    normalized = re.sub(r"\bInfinity\b", "0", normalized)
    try:
        parsed = json.loads(normalized)
    except (ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_xhs_count(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None

    cleaned = value.strip().replace("+", "").replace(",", "")
    if not cleaned:
        return None

    multiplier = 1
    if "千" in cleaned:
        multiplier = 1000
        cleaned = cleaned.replace("千", "")
    elif cleaned.lower().endswith("k"):
        multiplier = 1000
        cleaned = cleaned[:-1]
    elif "万" in cleaned:
        multiplier = 10000
        cleaned = cleaned.replace("万", "")
    elif cleaned.lower().endswith("w"):
        multiplier = 10000
        cleaned = cleaned[:-1]
    elif "亿" in cleaned:
        multiplier = 100000000
        cleaned = cleaned.replace("亿", "")

    cleaned = cleaned.strip()
    try:
        number = float(cleaned)
    except ValueError:
        digits = re.findall(r"\d+(?:\.\d+)?", cleaned)
        if not digits:
            return None
        try:
            number = float(digits[0])
        except ValueError:
            return None
    return int(number * multiplier)


def _extract_count_fields_from_mapping(
    mapping: dict,
    aliases: dict[str, tuple[str, ...]],
    source_prefix: str,
) -> dict:
    extracted: dict = {}
    sources: dict[str, str] = {}
    if not isinstance(mapping, dict):
        return extracted
    for output_key, candidate_keys in aliases.items():
        for candidate_key in candidate_keys:
            if candidate_key not in mapping:
                continue
            parsed = _parse_xhs_count(mapping.get(candidate_key))
            if parsed is None:
                continue
            extracted[output_key] = parsed
            sources[output_key] = f"{source_prefix}.{candidate_key}"
            break
    if sources:
        extracted["stats_sources"] = sources
    return extracted


def _iter_dict_nodes(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dict_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_dict_nodes(value)


def _has_any_alias(mapping: dict, aliases: dict[str, tuple[str, ...]]) -> bool:
    if not isinstance(mapping, dict):
        return False
    keys = set(mapping)
    return any(keys & set(candidate_keys) for candidate_keys in aliases.values())


def _extract_xhs_interaction_stats(note: dict) -> dict:
    if not isinstance(note, dict):
        return {}

    stats: dict = {}
    direct_candidates = (
        ("xhs.interactInfo", note.get("interactInfo")),
        ("xhs.interact_info", note.get("interact_info")),
        ("xhs.interact", note.get("interact")),
    )
    for source_prefix, candidate in direct_candidates:
        if isinstance(candidate, dict):
            merge_stats(
                stats,
                _extract_count_fields_from_mapping(candidate, XHS_STAT_KEY_ALIASES, source_prefix),
            )

    if all(stats.get(key) is not None for key in INTERACTION_COUNT_KEYS):
        return stats

    for node in _iter_dict_nodes(note):
        if node is note or not _has_any_alias(node, XHS_STAT_KEY_ALIASES):
            continue
        merge_stats(
            stats,
            _extract_count_fields_from_mapping(node, XHS_STAT_KEY_ALIASES, "xhs.recursive"),
        )
        if all(stats.get(key) is not None for key in INTERACTION_COUNT_KEYS):
            break
    return stats


def _extract_xhs_image_urls(note: dict) -> list[str]:
    image_list = note.get("imageList") or []
    if not isinstance(image_list, list):
        return []
    urls: list[str] = []
    for item in image_list:
        if not isinstance(item, dict):
            continue
        for key in ("urlDefault", "url", "urlPre"):
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate.startswith("http") and candidate.strip():
                urls.append(candidate.strip())
                break
        else:
            info_list = item.get("infoList") or []
            if isinstance(info_list, list):
                for info in info_list:
                    if not isinstance(info, dict):
                        continue
                    candidate = info.get("url")
                    if isinstance(candidate, str) and candidate.startswith("http") and candidate.strip():
                        urls.append(candidate.strip())
                        break
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in urls:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _extract_xhs_video_url(note: dict) -> Optional[str]:
    video = note.get("video") or {}
    if not isinstance(video, dict):
        return None

    mp4_candidates: list[str] = []
    m3u8_candidates: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            if not node.startswith("http") and not node.startswith("//"):
                return
            lowered = node.lower()
            if ".mp4" in lowered:
                mp4_candidates.append(node)
            elif ".m3u8" in lowered:
                m3u8_candidates.append(node)

    walk(video)
    if mp4_candidates:
        return mp4_candidates[0]
    if m3u8_candidates:
        return m3u8_candidates[0]
    return None


def _extract_xhs_note_from_html(html: str) -> Optional[dict]:
    state = _parse_xhs_initial_state(html)
    if not state:
        return None
    note: dict | None = None
    note_id: str | None = None

    note_state = state.get("note")
    if isinstance(note_state, dict):
        note_id = note_state.get("currentNoteId")
        note_detail_map = note_state.get("noteDetailMap") or {}
        if isinstance(note_detail_map, dict) and note_detail_map:
            entry = note_detail_map.get(note_id) if isinstance(note_id, str) else None
            if not isinstance(entry, dict) or not entry.get("note"):
                for key, value in note_detail_map.items():
                    if isinstance(value, dict) and isinstance(value.get("note"), dict) and value["note"]:
                        entry = value
                        if not isinstance(note_id, str) and isinstance(key, str):
                            note_id = key
                        break
            if isinstance(entry, dict):
                candidate = entry.get("note")
                if isinstance(candidate, dict) and candidate:
                    note = candidate
                    extracted_note_id = note.get("noteId") or note_id
                    note_id = extracted_note_id if isinstance(extracted_note_id, str) else note_id

    if note is None:
        note_data_state = state.get("noteData")
        if isinstance(note_data_state, dict):
            data = note_data_state.get("data")
            candidate = None
            if isinstance(data, dict):
                candidate = data.get("noteData")
            if not isinstance(candidate, dict) or not candidate:
                candidate = note_data_state.get("normalNotePreloadData")
            if isinstance(candidate, dict) and candidate:
                note = candidate
                extracted_note_id = note.get("noteId")
                note_id = extracted_note_id if isinstance(extracted_note_id, str) else None

    if note is None:
        return None
    if not isinstance(note_id, str) or not note_id:
        note_id = note.get("noteId") if isinstance(note.get("noteId"), str) else None
    if not isinstance(note_id, str) or not note_id:
        return None

    title = note.get("title") if isinstance(note.get("title"), str) else ""
    desc = note.get("desc") if isinstance(note.get("desc"), str) else ""
    caption_parts = [part.strip() for part in (title, desc) if part and part.strip()]
    caption = "\n".join(caption_parts).strip()

    interaction_stats = _extract_xhs_interaction_stats(note)

    return {
        "note_id": note_id,
        "note_type": note.get("type"),
        "caption": caption,
        "image_urls": _extract_xhs_image_urls(note),
        "video_url": _extract_xhs_video_url(note),
        "like_count": interaction_stats.get("like_count"),
        "collect_count": interaction_stats.get("collect_count"),
        "comment_count": interaction_stats.get("comment_count"),
        "share_count": interaction_stats.get("share_count"),
        "stats_sources": interaction_stats.get("stats_sources"),
    }


def _fetch_html(url: str, headers: dict, cookies: dict) -> str:
    if not url:
        return ""
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        response.raise_for_status()
        return response.text or ""
    except requests.RequestException:
        pass

    user_agent = headers.get("User-Agent") if isinstance(headers, dict) else None
    referer = headers.get("Referer") if isinstance(headers, dict) else None
    cookie_header = ""
    if isinstance(cookies, dict) and cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items() if key and value)
    curl_cmd = ["curl", "-L", "-sS"]
    if user_agent:
        curl_cmd.extend(["-A", str(user_agent)])
    if referer:
        curl_cmd.extend(["-e", str(referer)])
    if cookie_header:
        curl_cmd.extend(["-b", cookie_header])
    curl_cmd.append(url)
    try:
        result = subprocess.run(
            curl_cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""
    return result.stdout or ""


def extract_video_url_from_html(html: str) -> Optional[str]:
    patterns = [
        r"https?://[^\"'\\s]+\\.mp4[^\"'\\s]*",
        r"https?://[^\"'\\s]+\\.m3u8[^\"'\\s]*",
        r"https?:\\\\/\\\\/[^\"'\\s]+\\.mp4[^\"'\\s]*",
        r"https?:\\\\/\\\\/[^\"'\\s]+\\.m3u8[^\"'\\s]*",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if not match:
            continue
        url = match.group(0)
        url = url.replace("\\u0026", "&").replace("\\/", "/")
        return url
    return None


def extract_douyin_stats_from_html(html: str) -> dict:
    if not html:
        return {}
    decoder = json.JSONDecoder()
    for match in re.finditer(r'"statistics"\s*:\s*', html):
        start = match.end()
        try:
            parsed, _end = decoder.raw_decode(html[start:])
        except (ValueError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, dict):
            continue
        extracted = _extract_count_fields_from_mapping(
            parsed,
            DOUYIN_STAT_KEY_ALIASES,
            "douyin_share_html.statistics",
        )
        if not extracted:
            continue
        aweme_id = parsed.get("aweme_id")
        if aweme_id:
            extracted["video_id"] = str(aweme_id)
        return extracted
    return {}


def extract_douyin_page_metadata_from_html(html: str) -> dict:
    if not html:
        return {}

    def meta_content(name: str) -> str:
        patterns = (
            rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']{re.escape(name)}["\']',
            rf'<meta[^>]+property=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']{re.escape(name)}["\']',
        )
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.I)
            if match:
                return unescape(match.group(1)).strip()
        return ""

    description = meta_content("description") or meta_content("og:description")
    title = meta_content("og:title")
    if not title:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
        if title_match:
            title = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()

    page_title = ""
    if description:
        # Douyin SEO descriptions usually look like:
        # "<作品标题> - <作者>于<日期>发布在抖音，已经收获了..."
        page_title = re.split(r"\s+-\s+.+?于\d{8}发布在抖音", description, maxsplit=1)[0].strip()
        if page_title == description:
            page_title = re.split(r"\s+-\s+", description, maxsplit=1)[0].strip()
    if not page_title and title:
        page_title = title.strip()

    metadata: dict[str, str] = {}
    if page_title:
        metadata["page_title"] = page_title
        metadata["page_title_source"] = "douyin_meta_description" if description else "douyin_html_title"
    if description:
        metadata["page_description"] = description
    if title:
        metadata["html_title"] = title
    return metadata


def _caption_compare_key(value: str) -> str:
    return re.sub(r"[\s#＃，,。.!！?？、｜|:：;；\-—_]+", "", value or "").lower()


def reconcile_caption_with_page_metadata(caption: str, stats: dict) -> str:
    page_title = str(stats.get("page_title") or "").strip()
    current = (caption or "").strip()
    current_source = str(stats.get("caption_source") or "").strip()
    trusted_caption = current_source and current_source not in {"cache", "cached_caption"}
    if not page_title:
        if trusted_caption:
            return current
        if current:
            stats["cached_caption"] = current
            stats["caption_notice"] = "cached caption was not reused because current page/API did not verify it"
        return ""

    if current and (trusted_caption or _caption_compare_key(current) == _caption_compare_key(page_title)):
        return current

    if current:
        stats["cached_caption"] = current
        stats["caption_notice"] = "cached caption differed from current Douyin page title; using current page title"
    stats["caption_source"] = "douyin_meta_description"
    stats["caption_confidence"] = "page_title"
    return page_title


def extract_render_data(html: str) -> Optional[dict]:
    match = re.search(r"RENDER_DATA\\s*=\\s*\"(.*?)\"", html)
    if not match:
        return None
    try:
        decoded = unquote(match.group(1))
        return json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None


def find_video_url_in_render_data(payload: object) -> Optional[str]:
    if isinstance(payload, dict):
        play_addr = payload.get("playAddr") or payload.get("play_addr")
        if isinstance(play_addr, dict):
            url_list = play_addr.get("urlList") or play_addr.get("url_list") or []
            if url_list:
                return url_list[0]
        for value in payload.values():
            found = find_video_url_in_render_data(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = find_video_url_in_render_data(item)
            if found:
                return found
    return None


def extract_caption_from_aweme(aweme: dict) -> Optional[str]:
    if not isinstance(aweme, dict):
        return None
    for key in ("desc", "description", "title"):
        value = aweme.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_cover_url_from_aweme(aweme: dict) -> Optional[str]:
    if not isinstance(aweme, dict):
        return None
    video = aweme.get("video") or {}
    if not isinstance(video, dict):
        return None

    def pick(candidate: object) -> Optional[str]:
        if isinstance(candidate, str):
            return candidate.strip() if candidate.strip().startswith("http") else None
        if not isinstance(candidate, dict):
            return None
        url_list = extract_url_list(candidate)
        for url in url_list:
            if isinstance(url, str) and url.strip().startswith("http"):
                return url.strip()
        return None

    for key in (
        "origin_cover",
        "cover",
        "dynamic_cover",
        "animated_cover",
        "ai_cover",
        "big_cover",
        "cover_large",
        "cover_medium",
        "cover_thumb",
    ):
        found = pick(video.get(key))
        if found:
            return found
    return None


def extract_image_urls_from_aweme(aweme: dict) -> list[str]:
    if not isinstance(aweme, dict):
        return []
    images: list[dict] = []
    if isinstance(aweme.get("images"), list):
        images.extend(aweme.get("images") or [])
    image_post = aweme.get("image_post_info") or {}
    if isinstance(image_post, dict) and isinstance(image_post.get("images"), list):
        images.extend(image_post.get("images") or [])
    image_list = aweme.get("image_list") or aweme.get("img_list")
    if isinstance(image_list, list):
        images.extend(image_list)

    urls: list[str] = []
    for item in images:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("url_list"), list) and item["url_list"]:
            urls.append(item["url_list"][0])
            continue
        display = item.get("display_image") or item.get("image") or {}
        if isinstance(display, dict) and isinstance(display.get("url_list"), list) and display["url_list"]:
            urls.append(display["url_list"][0])
    return urls


def find_caption_in_render_data(payload: object) -> Optional[str]:
    if isinstance(payload, dict):
        if "desc" in payload and isinstance(payload["desc"], str) and payload["desc"].strip():
            return payload["desc"].strip()
        if "description" in payload and isinstance(payload["description"], str) and payload["description"].strip():
            return payload["description"].strip()
        for value in payload.values():
            found = find_caption_in_render_data(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = find_caption_in_render_data(item)
            if found:
                return found
    return None


def find_images_in_render_data(payload: object) -> list[str]:
    urls: list[str] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("images"), list):
            urls.extend(extract_image_urls_from_aweme(payload))
        for value in payload.values():
            urls.extend(find_images_in_render_data(value))
    elif isinstance(payload, list):
        for item in payload:
            urls.extend(find_images_in_render_data(item))
    return urls


def is_douyin_aweme_image_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    text = url.strip()
    if not text.startswith("http"):
        return False
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    if "douyinpic.com" not in host:
        return False
    query = parse_qs(parsed.query)
    return (
        query.get("biz_tag", [""])[0] == "aweme_images"
        and query.get("s", [""])[0] == "PackSourceEnum_DOUYIN_REFLOW"
    )


def douyin_aweme_image_identity(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    path = parsed.path.split("~", 1)[0]
    return f"{parsed.netloc.lower()}{path}" if parsed.netloc and path else text


def append_unique_url(urls: list[str], url: str) -> None:
    text = str(url or "").strip()
    if text and text not in urls:
        urls.append(text)


def append_unique_douyin_aweme_image_url(urls: list[str], url: str) -> None:
    text = str(url or "").strip()
    if not text:
        return
    identity = douyin_aweme_image_identity(text)
    if identity and any(douyin_aweme_image_identity(existing) == identity for existing in urls):
        return
    urls.append(text)


def is_animated_image(url: str) -> bool:
    lower = url.lower()
    return any(ext in lower for ext in (".gif", ".webp", "format=gif", "format=webp"))


def extract_play_url_from_detail(payload: dict, prefer_low_quality: bool) -> Optional[str]:
    try:
        video = payload.get("aweme_detail", {}).get("video", {})
    except AttributeError:
        return None
    return select_play_url_prefer_low(video, prefer_low_quality)


def extract_play_url_from_aweme_list(payload: dict, prefer_low_quality: bool) -> Optional[str]:
    aweme_list = payload.get("aweme_list", [])
    if not aweme_list:
        return None

    video = aweme_list[0].get("video", {})
    return select_play_url_prefer_low(video, prefer_low_quality)


def extract_url_list(play_addr: dict) -> list[str]:
    if not isinstance(play_addr, dict):
        return []
    return play_addr.get("url_list") or play_addr.get("urlList") or []


def select_low_bitrate_url(video: dict) -> Optional[str]:
    bit_rates = video.get("bit_rate") or video.get("bitrate") or []
    best: tuple[int, str] | None = None
    for item in bit_rates:
        if not isinstance(item, dict):
            continue
        bitrate = item.get("bit_rate") or item.get("bitrate") or item.get("bitRate")
        try:
            bitrate_val = int(bitrate)
        except (TypeError, ValueError):
            continue
        url_list = extract_url_list(item.get("play_addr") or item.get("playAddr") or {})
        if not url_list:
            continue
        if best is None or bitrate_val < best[0]:
            best = (bitrate_val, url_list[0])
    if best:
        return best[1]
    return None


def select_play_url(video: dict) -> Optional[str]:
    if not isinstance(video, dict):
        return None
    url_list = extract_url_list(video.get("play_addr") or {})
    if url_list:
        return url_list[0]
    if video.get("play_addr_lowbr"):
        url_list = extract_url_list(video.get("play_addr_lowbr"))
        if url_list:
            return url_list[0]
    if video.get("play_addr_low"):
        url_list = extract_url_list(video.get("play_addr_low"))
        if url_list:
            return url_list[0]
    return None


def select_play_url_prefer_low(video: dict, prefer_low_quality: bool) -> Optional[str]:
    if not isinstance(video, dict):
        return None
    if prefer_low_quality:
        low_url = select_low_bitrate_url(video)
        if low_url:
            return low_url
        if video.get("play_addr_lowbr"):
            url_list = extract_url_list(video.get("play_addr_lowbr"))
            if url_list:
                return url_list[0]
        if video.get("play_addr_low"):
            url_list = extract_url_list(video.get("play_addr_low"))
            if url_list:
                return url_list[0]
        lowbr_url = select_play_url(video)
        if lowbr_url:
            return lowbr_url
    return select_play_url(video)


def extract_aweme_id(aweme: dict) -> Optional[str]:
    if not isinstance(aweme, dict):
        return None
    for key in ("aweme_id", "item_id", "group_id", "id"):
        value = aweme.get(key)
        if value:
            return str(value)
    return None


def remember_item_id(stats: dict, item_id: str | None) -> None:
    if not item_id:
        return
    current = str(stats.get("video_id") or "")
    item_id = str(item_id)
    if not current or (item_id.isdigit() and not current.isdigit()):
        stats["video_id"] = item_id


def extract_stats_from_aweme(aweme: dict, source_prefix: str) -> dict:
    if not isinstance(aweme, dict):
        return {}
    stats = aweme.get("statistics")
    return _extract_count_fields_from_mapping(
        stats if isinstance(stats, dict) else {},
        DOUYIN_STAT_KEY_ALIASES,
        f"{source_prefix}.statistics",
    )


def extract_stats_from_aweme_detail(aweme_detail: dict) -> dict:
    return extract_stats_from_aweme(aweme_detail, "aweme_detail")


def merge_stats(target: dict, incoming: dict) -> dict:
    incoming_sources = incoming.get("stats_sources")
    if isinstance(incoming_sources, dict):
        target_sources = target.get("stats_sources")
        if not isinstance(target_sources, dict):
            target_sources = {}
            target["stats_sources"] = target_sources
    else:
        target_sources = {}

    for key, value in incoming.items():
        if key == "stats_sources":
            continue
        if key in ("stats_notice", "interaction_status"):
            if value and not target.get(key):
                target[key] = value
            continue
        if value is None or target.get(key) is not None:
            continue
        if key in ("video_id", "aweme_id"):
            target[key] = str(value)
            if isinstance(incoming_sources, dict) and key in incoming_sources:
                target_sources[key] = str(incoming_sources[key])
            continue
        try:
            target[key] = int(value)
        except (TypeError, ValueError):
            target[key] = value
        if isinstance(incoming_sources, dict) and key in incoming_sources:
            target_sources[key] = str(incoming_sources[key])
    return target


def merge_interaction_fields(target: dict, incoming: dict) -> dict:
    if not isinstance(incoming, dict):
        return target
    payload = {
        key: incoming.get(key)
        for key in INTERACTION_COUNT_KEYS
        if incoming.get(key) is not None
    }
    incoming_sources = incoming.get("stats_sources")
    if isinstance(incoming_sources, dict):
        payload["stats_sources"] = incoming_sources
    return merge_stats(target, payload)


def _is_trusted_douyin_stat_source(key: str, source: str | None) -> bool:
    if not source:
        return False
    if source == DOUYIN_TRUSTED_STAT_SOURCES.get(key):
        return True
    if source == DOUYIN_VISIBLE_TEXT_STAT_SOURCES.get(key):
        return True
    return any(source.startswith(prefix) for prefix in DOUYIN_TRUSTED_STAT_SOURCE_PREFIXES)


def sanitize_douyin_interaction_stats(stats: dict) -> dict:
    sources = stats.get("stats_sources")
    if not isinstance(sources, dict):
        sources = {}
        stats["stats_sources"] = sources

    for key in DOUYIN_TRUSTED_STAT_SOURCES:
        if stats.get(key) is None:
            continue
        if _is_trusted_douyin_stat_source(key, sources.get(key)):
            continue
        else:
            stats[key] = None

    missing_keys = [key for key in DOUYIN_TRUSTED_STAT_SOURCES if stats.get(key) is None]
    visible_text_keys = [
        key
        for key, source in DOUYIN_VISIBLE_TEXT_STAT_SOURCES.items()
        if stats.get(key) is not None and sources.get(key) == source
    ]
    if visible_text_keys:
        stats["interaction_status"] = "douyin_webpage_visible_text_pending_review"
        stats["stats_notice"] = (
            "作品级互动接口未完整取到；已从作品页截图/可见文本读取互动数，"
            "请用截图 OCR 或人工复核。"
        )
        if missing_keys:
            stats["missing_interaction_fields"] = missing_keys
        else:
            stats.pop("missing_interaction_fields", None)
    elif missing_keys:
        stats["interaction_status"] = "partial_missing_douyin_aweme_detail_statistics"
        stats["stats_notice"] = DOUYIN_STATS_NOTICE
        stats["missing_interaction_fields"] = missing_keys
    else:
        stats["interaction_status"] = "verified_douyin_aweme_detail_statistics"
        stats.pop("stats_notice", None)
        stats.pop("missing_interaction_fields", None)
    return stats


def finalize_interaction_stats(stats: dict, is_xhs: bool) -> dict:
    for key in INTERACTION_COUNT_KEYS:
        stats.setdefault(key, None)
    if is_xhs:
        missing_keys = [key for key in INTERACTION_COUNT_KEYS if stats.get(key) is None]
        if missing_keys:
            stats["interaction_status"] = "partial_missing_xhs_interact_info"
            stats["missing_interaction_fields"] = missing_keys
        else:
            stats["interaction_status"] = "verified_xhs_interact_info"
            stats.pop("missing_interaction_fields", None)
        return stats
    return sanitize_douyin_interaction_stats(stats)


def _parse_visible_count(value: str) -> Optional[int]:
    text = str(value or "").strip().lower().replace(",", "")
    if not text:
        return None
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    elif text.endswith("w"):
        multiplier = 10000
        text = text[:-1]
    elif text.endswith("千") or text.endswith("k"):
        multiplier = 1000
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100000000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def _extract_visible_interaction_stats(text: str) -> dict:
    if not text:
        return {}
    normalized = re.sub(r"\s+", " ", text.replace("\n", " | ")).strip()
    pattern = re.compile(
        r"(?P<like>\d+(?:\.\d+)?(?:万|w)?)\s*\|\s*"
        r"(?P<comment>\d+(?:\.\d+)?(?:万|w)?)\s*\|\s*"
        r"(?P<collect>\d+(?:\.\d+)?(?:万|w)?)\s*\|\s*"
        r"(?P<share>\d+(?:\.\d+)?(?:万|w)?)\s*\|\s*举报"
    )
    match = pattern.search(normalized)
    if match:
        parsed = {
            "like_count": _parse_visible_count(match.group("like")),
            "comment_count": _parse_visible_count(match.group("comment")),
            "collect_count": _parse_visible_count(match.group("collect")),
            "share_count": _parse_visible_count(match.group("share")),
        }
    else:
        count_pattern = r"(\d[\d,]*(?:\.\d+)?(?:万|w|千|k|亿)?)"
        label_patterns = {
            "like_count": (rf"{count_pattern}\s*(?:赞|获赞|点赞)", rf"(?:赞|获赞|点赞)\D{{0,6}}{count_pattern}"),
            "comment_count": (rf"{count_pattern}\s*(?:评论|条评论)", rf"(?:评论|条评论)\D{{0,6}}{count_pattern}"),
            "collect_count": (rf"{count_pattern}\s*(?:收藏)", rf"(?:收藏)\D{{0,6}}{count_pattern}"),
            "share_count": (rf"{count_pattern}\s*(?:分享|转发)", rf"(?:分享|转发)\D{{0,6}}{count_pattern}"),
        }
        parsed = {}
        for key, patterns in label_patterns.items():
            for label_pattern in patterns:
                label_match = re.search(label_pattern, normalized)
                if not label_match:
                    continue
                parsed[key] = _parse_visible_count(label_match.group(1))
                break
    extracted = {key: value for key, value in parsed.items() if value is not None}
    if extracted:
        extracted["stats_sources"] = {
            key: DOUYIN_VISIBLE_TEXT_STAT_SOURCES[key]
            for key in extracted
            if key in DOUYIN_VISIBLE_TEXT_STAT_SOURCES
        }
        extracted["visible_interaction_text"] = match.group(0) if match else normalized[:240]
    return extracted


def capture_interaction_screenshot(page, url: str, stats: dict, video_id: str | None = None) -> Optional[str]:
    if not url:
        return None
    try:
        screenshot_url = url
        if video_id:
            screenshot_url = f"https://www.douyin.com/video/{video_id}"
        paths = ensure_media_paths(screenshot_url)
        screenshot_path = paths.interaction_screenshot_path
        screenshot_page = page
        close_context = None
        try:
            browser = page.context.browser
            if browser is not None:
                desktop_context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
                    ),
                )
                cookies = page.context.cookies()
                if cookies:
                    desktop_context.add_cookies(cookies)
                close_context = desktop_context
                screenshot_page = desktop_context.new_page()
            if screenshot_url and screenshot_url != screenshot_page.url:
                screenshot_page.goto(screenshot_url, wait_until="domcontentloaded", timeout=30000)
                screenshot_page.wait_for_timeout(7000)
            try:
                body_text = screenshot_page.locator("body").inner_text(timeout=3000)
                visible_stats = _extract_visible_interaction_stats(body_text)
                if visible_stats:
                    merge_stats(stats, visible_stats)
            except Exception:
                pass
            screenshot_page.add_style_tag(
                content=(
                    "*{font-family:Arial,Helvetica,sans-serif!important;"
                    "transition:none!important;animation:none!important}"
                )
            )
            screenshot_page.wait_for_timeout(800)
            screenshot_page.evaluate("() => window.scrollTo(0, 0)")
            screenshot_page.wait_for_timeout(300)
        except Exception:
            pass
        screenshot_page.screenshot(path=screenshot_path, full_page=False, timeout=15000, animations="disabled")
        if close_context is not None:
            close_context.close()
    except Exception as exc:
        stats.setdefault("interaction_screenshot_status", "capture_failed")
        stats.setdefault("interaction_screenshot_error", str(exc))
        return None
    if not os.path.isfile(screenshot_path) or os.path.getsize(screenshot_path) <= 0:
        stats.setdefault("interaction_screenshot_status", "capture_failed")
        stats.setdefault("interaction_screenshot_error", "empty_screenshot_file")
        return None
    stats["interaction_screenshot_path"] = screenshot_path
    stats["interaction_screenshot_status"] = "captured_for_ocr"
    return screenshot_path


def extract_top_comments(payload: dict, limit: int) -> list[dict]:
    comments = list(_iter_comment_candidates(payload))
    results: list[dict] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        text = _first_text(comment, ("text", "content", "comment_text", "desc"))
        user = comment.get("user") or comment.get("user_info") or comment.get("author") or {}
        author = _first_text(user, ("nickname", "name", "user_name", "display_name")) if isinstance(user, dict) else str(user or "")
        like_count = comment.get("digg_count") or comment.get("like_count") or comment.get("diggCount") or comment.get("liked_count") or comment.get("likeCount")
        cid = comment.get("cid") or comment.get("id") or comment.get("comment_id") or comment.get("commentId")
        try:
            like_count = int(like_count)
        except (TypeError, ValueError):
            like_count = 0
        if text:
            results.append(
                {
                    "cid": cid,
                    "text": text,
                    "author": author,
                    "like_count": like_count,
                    "source_method": "comment_list_response",
                }
            )
    results.sort(key=lambda item: item.get("like_count", 0), reverse=True)
    return results[: max(limit, 1)]


def _iter_comment_candidates(value: object):
    if isinstance(value, dict):
        for key in ("comments", "comment_list", "commentList", "items", "list"):
            child = value.get(key)
            if isinstance(child, list):
                for item in child:
                    if _looks_like_comment(item):
                        yield item
                    else:
                        yield from _iter_comment_candidates(item)
        for key in ("data", "result"):
            yield from _iter_comment_candidates(value.get(key))
    elif isinstance(value, list):
        for item in value:
            if _looks_like_comment(item):
                yield item
            else:
                yield from _iter_comment_candidates(item)


def _looks_like_comment(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if any(key in value for key in ("text", "content", "comment_text", "desc")) and any(
        key in value for key in ("cid", "id", "comment_id", "commentId", "digg_count", "like_count", "liked_count", "likeCount")
    ):
        return True
    return False


def _first_text(value: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return ""


def merge_top_comments(current: list[dict], incoming: list[dict], limit: int) -> list[dict]:
    combined = current + incoming
    deduped: dict[str, dict] = {}
    for comment in combined:
        key = comment.get("cid")
        if not key:
            key = f"{comment.get('author', '')}|{comment.get('text', '')}"
        existing = deduped.get(key)
        if not existing or comment.get("like_count", 0) > existing.get("like_count", 0):
            deduped[key] = comment
    merged = list(deduped.values())
    merged.sort(key=lambda item: item.get("like_count", 0), reverse=True)
    return merged[: max(limit, 1)]


def adjust_playwm_ratio(url: str, ratio: str) -> str:
    if "playwm" not in url:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["ratio"] = [ratio]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def fetch_iesdouyin_item_meta(
    video_id: str,
    headers: dict,
    ms_token: str | None,
    prefer_low_quality: bool,
) -> dict:
    params = {"item_ids": video_id}
    if ms_token:
        params["msToken"] = ms_token

    try:
        response = requests.get(
            "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/",
            params=params,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        return {}

    try:
        payload = response.json()
    except ValueError:
        return {}

    items = payload.get("item_list", [])
    if not items:
        return {}

    aweme = items[0] if isinstance(items[0], dict) else {}
    meta = {
        "video_url": select_play_url_prefer_low(aweme.get("video", {}), prefer_low_quality),
        "stats": extract_stats_from_aweme(aweme, "iesdouyin_iteminfo"),
        "cover_url": extract_cover_url_from_aweme(aweme),
        "caption": extract_caption_from_aweme(aweme),
        "image_urls": extract_image_urls_from_aweme(aweme),
        "aweme_id": extract_aweme_id(aweme),
    }
    return {key: value for key, value in meta.items() if value not in (None, "", [], {})}


def fetch_iesdouyin_item(
    video_id: str,
    headers: dict,
    ms_token: str | None,
    prefer_low_quality: bool,
) -> Optional[str]:
    meta = fetch_iesdouyin_item_meta(video_id, headers, ms_token, prefer_low_quality)
    video_url = meta.get("video_url")
    return str(video_url) if video_url else None


def fetch_douyin_aweme_detail_stats(
    video_id: str,
    headers: dict,
    cookies: dict,
    ms_token: str | None,
) -> dict:
    if not video_id:
        return {}
    params = {
        "aweme_id": video_id,
        "aid": "6383",
        "device_platform": "webapp",
    }
    if ms_token:
        params["msToken"] = ms_token
    try:
        response = requests.get(
            "https://www.douyin.com/aweme/v1/web/aweme/detail/",
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return {}

    aweme_detail = payload.get("aweme_detail")
    if not isinstance(aweme_detail, dict):
        return {}
    return extract_stats_from_aweme_detail(aweme_detail)


def fetch_aweme_post(url: str, headers: dict, cookies: dict, prefer_low_quality: bool) -> Optional[str]:
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    return extract_play_url_from_aweme_list(payload, prefer_low_quality)


def fetch_comment_list(
    video_id: str,
    headers: dict,
    cookies: dict,
    limit: int,
    ms_token: str | None = None,
) -> list[dict]:
    if not video_id:
        return []

    params = {
        "aweme_id": video_id,
        "item_id": video_id,
        "cursor": 0,
        "count": max(limit, 1),
    }
    if ms_token:
        params["msToken"] = ms_token

    endpoints = [
        "https://www.douyin.com/aweme/v1/web/comment/list/",
        "https://www.iesdouyin.com/web/api/v2/comment/list/",
    ]
    for endpoint in endpoints:
        try:
            response = requests.get(
                endpoint,
                params=params,
                headers=headers,
                cookies=cookies,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue
        comments = extract_top_comments(payload, limit)
        if comments:
            return comments
    return []


def refresh_stats_only(
    url: str,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
) -> dict:
    is_xhs = _is_xhs_url(url)
    stats: dict = {}
    top_comments: list[dict] = []
    cover_url: str = ""
    ms_token = ""
    page_url = ""
    headers: dict = {}
    platform_key = "xiaohongshu" if is_xhs else "douyin"
    cookies: dict = load_platform_cookie_dict(platform_key, settings)
    debug_playwright = settings.playwright_debug

    _report_progress(progress, 18, "刷新互动数据")
    if is_xhs:
        headers = {
            "User-Agent": MOBILE_SAFARI_USER_AGENT,
            "Referer": "https://www.xiaohongshu.com/",
        }
        html = _fetch_html(url, headers, cookies)
        note = _extract_xhs_note_from_html(html) if html else None
        if note:
            merge_interaction_fields(stats, note)
            note_id = note.get("note_id")
            if isinstance(note_id, str) and note_id:
                stats["video_id"] = note_id
            image_urls = note.get("image_urls")
            if isinstance(image_urls, list) and image_urls:
                candidate = image_urls[0]
                if isinstance(candidate, str) and candidate.strip():
                    stats["cover_url"] = candidate.strip()
        return finalize_interaction_stats(stats, is_xhs=True)

    direct_headers = {
        "User-Agent": MOBILE_SAFARI_USER_AGENT,
        "Referer": "https://www.iesdouyin.com/",
    }
    direct_html = _fetch_html(url, direct_headers, cookies)
    direct_stats = extract_douyin_stats_from_html(direct_html) if direct_html else {}
    page_metadata = extract_douyin_page_metadata_from_html(direct_html) if direct_html else {}
    if direct_stats:
        merge_stats(stats, direct_stats)
        remember_item_id(stats, direct_stats.get("video_id"))
    if page_metadata:
        stats.update(page_metadata)

    try:
        with sync_playwright() as p:
            device = p.devices["iPhone 13 Pro"]
            device_settings = {
                "user_agent": device.get("user_agent"),
                "viewport": device.get("viewport"),
                "device_scale_factor": device.get("device_scale_factor"),
                "is_mobile": device.get("is_mobile"),
                "has_touch": device.get("has_touch"),
            }
            user_agent = device.get("user_agent", "")
            profile_dir = None if is_xhs else chrome_profile_dir(settings)
            browser = None
            if profile_dir:
                try:
                    context = p.chromium.launch_persistent_context(
                        profile_dir,
                        headless=settings.playwright_headless,
                        channel="chrome",
                        proxy=playwright_proxy(settings),
                        **device_settings,
                    )
                except Exception:
                    context = None
            else:
                context = None

            if context is None:
                browser = p.webkit.launch(
                    headless=settings.playwright_headless,
                    proxy=playwright_proxy(settings),
                )
                context = browser.new_context(**device_settings)
            add_platform_cookies_to_context(context, platform_key, settings)
            page = context.new_page()

            def handle_response(response):
                nonlocal cover_url, top_comments
                candidate = response.url.lower()
                if "aweme/v1/web/aweme/detail" in candidate:
                    try:
                        payload = response.json()
                        aweme_detail = payload.get("aweme_detail", {})
                        merge_stats(stats, extract_stats_from_aweme_detail(aweme_detail))
                        remember_item_id(stats, extract_aweme_id(aweme_detail))
                        if not cover_url:
                            cover_candidate = extract_cover_url_from_aweme(aweme_detail)
                            if cover_candidate:
                                cover_url = cover_candidate
                    except Exception:
                        pass
                if "/aweme/post/" in candidate:
                    try:
                        payload = response.json()
                        aweme_list = payload.get("aweme_list", [])
                        if aweme_list:
                            aweme = aweme_list[0] if isinstance(aweme_list[0], dict) else {}
                            merge_stats(stats, extract_stats_from_aweme(aweme, "aweme_post"))
                            remember_item_id(stats, extract_aweme_id(aweme))
                            if not cover_url:
                                cover_candidate = extract_cover_url_from_aweme(aweme)
                                if cover_candidate:
                                    cover_url = cover_candidate
                    except Exception:
                        pass
                if "comment/list" in candidate:
                    try:
                        payload = response.json()
                        incoming = extract_top_comments(payload, settings.top_comments_limit)
                        if incoming:
                            top_comments = merge_top_comments(
                                top_comments,
                                incoming,
                                settings.top_comments_limit,
                            )
                    except Exception:
                        pass

            page.on("response", handle_response)
            try:
                page.goto(url, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                page.goto(url, wait_until="domcontentloaded")

            for _ in range(16):
                if stats and (top_comments or settings.top_comments_limit <= 0):
                    break
                page.wait_for_timeout(300)

            try:
                page_url = page.url
            except Exception:
                page_url = ""

            missing_counts = any(
                stats.get(key) is None
                for key in INTERACTION_COUNT_KEYS
            )

            try:
                ms_token = page.evaluate(
                    "() => window.msToken || window._msToken || "
                    "localStorage.getItem('msToken') || "
                    "sessionStorage.getItem('msToken') || ''"
                )
            except Exception:
                ms_token = ""

            if settings.top_comments_limit > 0 and not top_comments:
                try:
                    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(800)
                except Exception:
                    pass
                for _ in range(8):
                    if top_comments:
                        break
                    page.wait_for_timeout(400)

            headers = {
                "User-Agent": user_agent,
                "Referer": page_url or "https://www.douyin.com/",
            }
            cookies = {
                **cookies,
                **{cookie["name"]: cookie["value"] for cookie in context.cookies()},
            }
            missing_counts = any(
                stats.get(key) is None
                for key in INTERACTION_COUNT_KEYS
            )
            if missing_counts:
                _kind, item_id = extract_douyin_id(page_url or url)
                if item_id:
                    remember_item_id(stats, item_id)
                    merge_stats(
                        stats,
                        fetch_douyin_aweme_detail_stats(item_id, headers, cookies, ms_token),
                    )
                    if any(stats.get(key) is None for key in INTERACTION_COUNT_KEYS):
                        item_meta = fetch_iesdouyin_item_meta(
                            item_id,
                            {
                                "User-Agent": user_agent,
                                "Referer": "https://www.iesdouyin.com/",
                            },
                            ms_token,
                            settings.prefer_low_quality,
                        )
                        merge_stats(stats, item_meta.get("stats", {}))
                        remember_item_id(stats, item_meta.get("aweme_id") or item_id)

            if settings.top_comments_limit > 0 and not top_comments:
                _kind, item_id = extract_douyin_id(page_url or url)
                if item_id:
                    fetched = fetch_comment_list(
                        item_id,
                        headers,
                        cookies,
                        settings.top_comments_limit,
                        ms_token=ms_token,
                    )
                    if fetched:
                        top_comments = merge_top_comments(
                            top_comments,
                            fetched,
                            settings.top_comments_limit,
                        )

            if not is_xhs and any(stats.get(key) is None for key in INTERACTION_COUNT_KEYS):
                _kind, screenshot_item_id = extract_douyin_id(page_url or url)
                capture_interaction_screenshot(page, page_url or url, stats, screenshot_item_id)

            context.close()
            if browser:
                browser.close()
    except Exception as exc:
        if debug_playwright:
            print(f"刷新互动数据失败: {exc}")

    if cover_url and not stats.get("cover_url"):
        stats["cover_url"] = cover_url
    if top_comments:
        stats["top_comments"] = top_comments
    return finalize_interaction_stats(stats, is_xhs=False)


def chrome_profile_dir(settings: Settings) -> Optional[str]:
    profile = settings.cookies_profile
    path = os.path.expanduser(f"~/Library/Application Support/Google/Chrome/{profile}")
    if os.path.isdir(path):
        return path
    return None


def download_stream(
    url: str,
    dest_path: str,
    headers: dict,
    cookies: dict,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (12, 40),
) -> bool:
    start_time = time.time()
    start_percent, end_percent = progress_range
    last_emit = 0.0
    downloaded_bytes = 0
    try:
        with requests.get(
            url,
            stream=True,
            headers=headers,
            cookies=cookies,
            timeout=(10, settings.download_read_timeout),
        ) as response:
            response.raise_for_status()
            total_size = response.headers.get("content-length")
            total_size_int = int(total_size) if total_size and total_size.isdigit() else None
            if total_size_int:
                size_mb = total_size_int / (1024 * 1024)
                print(f"预计下载大小: {size_mb:.2f} MB", flush=True)
                _report_progress(progress, start_percent, f"开始下载 {size_mb:.2f} MB")
            with open(dest_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if settings.download_max_seconds > 0 and time.time() - start_time > settings.download_max_seconds:
                        raise requests.Timeout("download exceeded time limit")
                    if chunk:
                        handle.write(chunk)
                        downloaded_bytes += len(chunk)
                        now = time.time()
                        if progress and now - last_emit >= 0.4:
                            if total_size_int:
                                ratio = downloaded_bytes / total_size_int
                                percent = _scale_percent(ratio, start_percent, end_percent)
                                message = (
                                    f"下载中 {downloaded_bytes / (1024 * 1024):.1f}/"
                                    f"{total_size_int / (1024 * 1024):.1f} MB"
                                )
                            else:
                                if settings.download_max_seconds > 0:
                                    ratio = min((now - start_time) / settings.download_max_seconds, 0.95)
                                    percent = _scale_percent(ratio, start_percent, end_percent)
                                else:
                                    percent = start_percent
                                message = f"下载中 {downloaded_bytes / (1024 * 1024):.1f} MB"
                            _report_progress(progress, percent, message)
                            last_emit = now
        return True
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            print(f"视频下载异常: {response.status_code}", flush=True)
        else:
            print(f"视频下载异常: {exc}", flush=True)
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        _report_progress(progress, start_percent, "下载失败")
        return False


def download_stream_with_ffmpeg(
    url: str,
    dest_path: str,
    headers: dict,
    cookies: dict,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (12, 40),
) -> bool:
    header_lines = []
    for key, value in headers.items():
        if value:
            header_lines.append(f"{key}: {value}")
    if cookies:
        cookie_value = "; ".join(f"{key}={value}" for key, value in cookies.items())
        header_lines.append(f"Cookie: {cookie_value}")
    header_blob = "\r\n".join(header_lines) + "\r\n" if header_lines else ""

    try:
        process = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-headers",
                header_blob,
                "-i",
                url,
                "-c",
                "copy",
                dest_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        return False

    start_time = time.time()
    start_percent, end_percent = progress_range
    last_emit = 0.0
    while True:
        if process.poll() is not None:
            break
        now = time.time()
        if progress and now - last_emit >= 0.6:
            if settings.download_max_seconds > 0:
                ratio = min((now - start_time) / settings.download_max_seconds, 0.95)
                percent = _scale_percent(ratio, start_percent, end_percent)
            else:
                percent = start_percent
            _report_progress(progress, percent, "下载中 (ffmpeg)")
            last_emit = now
        time.sleep(0.4)

    if process.returncode != 0:
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        _report_progress(progress, start_percent, "下载失败")
        return False

    return os.path.exists(dest_path)


def parse_video_ratio_pixels(ratio: str) -> Optional[int]:
    match = re.search(r"(\d+)", str(ratio or ""))
    if not match:
        return None
    pixels = int(match.group(1))
    if 120 <= pixels <= 4320:
        return pixels
    return None


def probe_video_dimensions(video_path: str) -> Optional[tuple[int, int]]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                video_path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    line = (result.stdout or "").strip().splitlines()[0:1]
    if not line or "x" not in line[0]:
        return None
    width_text, height_text = line[0].split("x", 1)
    try:
        width = int(width_text)
        height = int(height_text)
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def transcode_video_to_ratio(
    video_path: str,
    ratio: str,
    progress: Optional[ProgressFn] = None,
) -> bool:
    target_pixels = parse_video_ratio_pixels(ratio)
    if not target_pixels or not media_exists(video_path):
        return False

    dimensions = probe_video_dimensions(video_path)
    if not dimensions:
        print("无法读取视频尺寸，跳过 480p 转码。", flush=True)
        return False
    width, height = dimensions
    if width > height:
        if height <= target_pixels:
            return False
        scale_filter = f"-2:{target_pixels}"
    else:
        if width <= target_pixels:
            return False
        scale_filter = f"{target_pixels}:-2"

    root, _ext = os.path.splitext(video_path)
    tmp_path = f"{root}.{target_pixels}p.tmp.mp4"
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    old_size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
    print(f"正在转为 {target_pixels}p: {width}x{height}", flush=True)
    _report_progress(progress, 40, f"转为 {target_pixels}p")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vf",
                f"scale={scale_filter}",
                "-c:v",
                "libx264",
                "-preset",
                os.getenv("CONTENT_FLOW_VIDEO_TRANSCODE_PRESET", "veryfast"),
                "-crf",
                os.getenv("CONTENT_FLOW_VIDEO_TRANSCODE_CRF", "28"),
                "-c:a",
                "aac",
                "-b:a",
                os.getenv("CONTENT_FLOW_VIDEO_TRANSCODE_AUDIO_BITRATE", "96k"),
                "-movflags",
                "+faststart",
                tmp_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=int(os.getenv("CONTENT_FLOW_FFMPEG_TIMEOUT_SECONDS", "1800")),
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        print(f"{target_pixels}p 转码失败，保留原视频。", flush=True)
        return False

    if not media_exists(tmp_path):
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

    new_dimensions = probe_video_dimensions(tmp_path) or dimensions
    new_size = os.path.getsize(tmp_path)
    os.replace(tmp_path, video_path)
    print(
        "视频已转为 "
        f"{target_pixels}p: {width}x{height}/{old_size / (1024 * 1024):.2f} MB"
        f" -> {new_dimensions[0]}x{new_dimensions[1]}/{new_size / (1024 * 1024):.2f} MB",
        flush=True,
    )
    _report_progress(progress, 40, f"已转为 {target_pixels}p")
    return True


def download_images(
    image_urls: list[str],
    dest_dir: str,
    headers: dict,
    cookies: dict,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (12, 40),
) -> list[str]:
    if not image_urls:
        return []
    os.makedirs(dest_dir, exist_ok=True)
    downloaded: list[str] = []
    total = len(image_urls)
    start_percent, end_percent = progress_range
    for idx, url in enumerate(image_urls, start=1):
        try:
            response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            continue
        ext = ".jpg"
        lower = url.lower()
        if ".png" in lower:
            ext = ".png"
        elif ".webp" in lower:
            ext = ".webp"
        elif ".gif" in lower:
            ext = ".gif"
        filename = f"image-{idx:02d}{ext}"
        path = os.path.join(dest_dir, filename)
        try:
            with open(path, "wb") as handle:
                handle.write(response.content)
            downloaded.append(path)
        except OSError:
            continue
        if progress:
            ratio = idx / total
            percent = _scale_percent(ratio, start_percent, end_percent)
            _report_progress(progress, percent, f"图片下载 {idx}/{total}")
    return downloaded


def extract_animated_frames(image_path: str, dest_dir: str) -> list[str]:
    if not image_path or not os.path.exists(image_path):
        return []
    os.makedirs(dest_dir, exist_ok=True)
    frame_pattern = os.path.join(dest_dir, "frame-%02d.jpg")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                image_path,
                "-vf",
                "fps=1",
                "-frames:v",
                "3",
                frame_pattern,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=int(os.getenv("CONTENT_FLOW_FFMPEG_TIMEOUT_SECONDS", "1800")),
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    frames = []
    for name in sorted(os.listdir(dest_dir)):
        if name.startswith("frame-") and name.endswith(".jpg"):
            frames.append(os.path.join(dest_dir, name))
    return frames


def extract_audio_mp3(video_path: str, audio_path: str) -> Optional[str]:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vn",
                "-acodec",
                "libmp3lame",
                "-b:a",
                "192k",
                audio_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=int(os.getenv("CONTENT_FLOW_FFMPEG_TIMEOUT_SECONDS", "1800")),
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    return audio_path if os.path.exists(audio_path) else None


def extract_video_cover(video_path: str, dest_dir: str, filename: str = "cover.jpg") -> Optional[str]:
    if not video_path or not media_exists(video_path):
        return None
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)
    if media_exists(dest_path):
        return dest_path
    tmp_path = f"{dest_path}.tmp"
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vf",
                "select=eq(n\\,0)",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                tmp_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=int(os.getenv("CONTENT_FLOW_FFMPEG_TIMEOUT_SECONDS", "1800")),
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return None

    if not media_exists(tmp_path):
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return None
    os.replace(tmp_path, dest_path)
    return dest_path if media_exists(dest_path) else None


def resolve_media(
    url: str,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
) -> MediaResult:
    paths = ensure_media_paths(url)
    is_xhs = _is_xhs_url(url)
    stats: dict = {}
    cached_analysis = load_json(paths.analysis_path)
    if isinstance(cached_analysis, dict):
        stats = {
            "like_count": cached_analysis.get("like_count"),
            "collect_count": cached_analysis.get("collect_count"),
            "comment_count": cached_analysis.get("comment_count"),
            "share_count": cached_analysis.get("share_count"),
            "top_comments": cached_analysis.get("top_comments"),
            "video_id": cached_analysis.get("video_id"),
            "cover_url": cached_analysis.get("cover_url"),
            "stats_sources": cached_analysis.get("stats_sources"),
            "interaction_status": cached_analysis.get("interaction_status"),
            "stats_notice": cached_analysis.get("stats_notice"),
            "missing_interaction_fields": cached_analysis.get("missing_interaction_fields"),
            "interaction_screenshot_path": cached_analysis.get("interaction_screenshot_path"),
            "interaction_screenshot_status": cached_analysis.get("interaction_screenshot_status"),
            "interaction_screenshot_error": cached_analysis.get("interaction_screenshot_error"),
        }
    if "video_id" not in stats or not stats.get("video_id"):
        stats["video_id"] = paths.video_id
    caption = load_text(paths.caption_path) or ""
    if caption:
        stats["cached_caption"] = caption
        stats.setdefault("caption_source", "cache")

    if media_exists(paths.video_path):
        print(f"检测到已下载视频: {paths.video_path}，跳过下载。", flush=True)
        if settings.prefer_low_quality:
            transcode_video_to_ratio(paths.video_path, settings.video_ratio, progress=progress)
        _report_progress(progress, 40, "已存在视频，跳过下载")
        cover_paths = list_image_files(paths)
        if not cover_paths:
            cover = extract_video_cover(paths.video_path, paths.image_dir)
            if cover:
                cover_paths = [cover]
        if media_exists(paths.audio_path):
            print(f"检测到已下载音频: {paths.audio_path}，跳过提取。", flush=True)
            _report_progress(progress, 45, "已存在音频")
            refreshed = refresh_stats_only(url, settings, progress=progress)
            merge_stats(stats, refreshed)
            if refreshed.get("top_comments"):
                stats["top_comments"] = refreshed.get("top_comments")
            caption = reconcile_caption_with_page_metadata(caption, stats)
            finalize_interaction_stats(stats, is_xhs=is_xhs)
            return MediaResult(
                media_type="video",
                video_path=paths.video_path,
                audio_path=paths.audio_path,
                image_paths=cover_paths,
                caption=caption,
                stats=stats,
            )
        print("已存在视频，正在提取音频...", flush=True)
        _report_progress(progress, 42, "提取音频中")
        extracted = extract_audio_mp3(paths.video_path, paths.audio_path)
        if extracted:
            print("音频提取完成。", flush=True)
            _report_progress(progress, 45, "音频提取完成")
            refreshed = refresh_stats_only(url, settings, progress=progress)
            merge_stats(stats, refreshed)
            if refreshed.get("top_comments"):
                stats["top_comments"] = refreshed.get("top_comments")
            caption = reconcile_caption_with_page_metadata(caption, stats)
            finalize_interaction_stats(stats, is_xhs=is_xhs)
            return MediaResult(
                media_type="video",
                video_path=paths.video_path,
                audio_path=extracted,
                image_paths=cover_paths,
                caption=caption,
                stats=stats,
            )
        print("音频提取失败，尝试直接用视频文件转写。", flush=True)
        _report_progress(progress, 45, "音频提取失败")
        caption = reconcile_caption_with_page_metadata(caption, stats)
        finalize_interaction_stats(stats, is_xhs=is_xhs)
        return MediaResult(
            media_type="video",
            video_path=paths.video_path,
            audio_path=paths.video_path,
            image_paths=cover_paths,
            caption=caption,
            stats=stats,
        )

    existing_images = list_image_files(paths)
    if existing_images:
        _report_progress(progress, 40, "已存在图片，跳过下载")
        refreshed = refresh_stats_only(url, settings, progress=progress)
        merge_stats(stats, refreshed)
        if refreshed.get("top_comments"):
            stats["top_comments"] = refreshed.get("top_comments")
        caption = reconcile_caption_with_page_metadata(caption, stats)
        finalize_interaction_stats(stats, is_xhs=is_xhs)
        is_frames = any(os.path.basename(os.path.dirname(path)) == "frames" for path in existing_images)
        return MediaResult(
            media_type="animated" if is_frames else "image",
            video_path=None,
            audio_path=None,
            image_paths=existing_images,
            caption=caption,
            stats=stats,
        )

    return download_video(url, settings, paths, progress=progress)


def download_video(
    url: str,
    settings: Settings,
    paths: MediaPaths,
    progress: Optional[ProgressFn] = None,
) -> MediaResult:
    video_path = paths.video_path
    audio_path = paths.audio_path
    print("解析视频地址...", flush=True)
    _report_progress(progress, 8, "解析视频地址")
    headless = settings.playwright_headless
    is_xhs = _is_xhs_url(url)
    video_url = None
    video_kind = ""
    playwm_url = None
    stats: dict = {key: None for key in INTERACTION_COUNT_KEYS}
    stats["video_id"] = paths.video_id
    top_comments: list[dict] = []
    image_urls: list[str] = []
    cover_url: str = ""
    caption = ""
    headers: dict = {}
    platform_key = "xiaohongshu" if is_xhs else "douyin"
    cookies: dict = load_platform_cookie_dict(platform_key, settings)
    page_title = ""
    page_url = ""
    ms_token = ""
    aweme_post_url = ""
    debug_playwright = settings.playwright_debug

    if is_xhs:
        xhs_headers = {
            "User-Agent": MOBILE_SAFARI_USER_AGENT,
            "Referer": "https://www.xiaohongshu.com/",
        }
        direct_html = _fetch_html(url, xhs_headers, cookies)
        xhs_note = _extract_xhs_note_from_html(direct_html) if direct_html else None
        if xhs_note:
            if xhs_note.get("caption"):
                caption = xhs_note["caption"]
                stats["caption_source"] = "xiaohongshu_html"
            if xhs_note.get("image_urls"):
                image_urls = xhs_note["image_urls"]
                if not cover_url and image_urls:
                    cover_url = str(image_urls[0])
            direct_video_url = xhs_note.get("video_url")
            if isinstance(direct_video_url, str) and direct_video_url:
                normalized_video_url = normalize_video_url(direct_video_url, base_url=url)
                if normalized_video_url and normalized_video_url.startswith("http"):
                    video_url = normalized_video_url
                    if ".m3u8" in normalized_video_url.lower():
                        video_kind = "m3u8"
                    else:
                        video_kind = "mp4"
            merge_interaction_fields(stats, xhs_note)
            note_id = xhs_note.get("note_id")
            if isinstance(note_id, str) and note_id:
                stats["video_id"] = note_id
            headers = xhs_headers

    if not is_xhs:
        douyin_headers = {
            "User-Agent": MOBILE_SAFARI_USER_AGENT,
            "Referer": "https://www.iesdouyin.com/",
        }
        direct_html = _fetch_html(url, douyin_headers, cookies)
        direct_stats = extract_douyin_stats_from_html(direct_html) if direct_html else {}
        page_metadata = extract_douyin_page_metadata_from_html(direct_html) if direct_html else {}
        if direct_stats:
            merge_stats(stats, direct_stats)
            remember_item_id(stats, direct_stats.get("video_id"))
        if page_metadata:
            stats.update(page_metadata)
        headers = douyin_headers

    try:
        with sync_playwright() as p:
            device = p.devices["iPhone 13 Pro"]
            device_settings = {
                "user_agent": device.get("user_agent"),
                "viewport": device.get("viewport"),
                "device_scale_factor": device.get("device_scale_factor"),
                "is_mobile": device.get("is_mobile"),
                "has_touch": device.get("has_touch"),
            }
            user_agent = device.get("user_agent", "")
            profile_dir = chrome_profile_dir(settings)
            browser = None
            if profile_dir:
                try:
                    context = p.chromium.launch_persistent_context(
                        profile_dir,
                        headless=headless,
                        channel="chrome",
                        proxy=playwright_proxy(settings),
                        **device_settings,
                    )
                except Exception:
                    context = None
            else:
                context = None

            if context is None:
                browser = p.webkit.launch(
                    headless=headless,
                    proxy=playwright_proxy(settings),
                )
                context = browser.new_context(**device_settings)
            add_platform_cookies_to_context(context, platform_key, settings)
            page = context.new_page()
            if debug_playwright:
                def log_request(request):
                    if "aweme" in request.url or "iteminfo" in request.url:
                        print(f"[playwright] request: {request.url}")

                def log_response(response):
                    if "aweme" in response.url or "iteminfo" in response.url:
                        print(f"[playwright] response: {response.url} status={response.status}")

                page.on("request", log_request)
                page.on("response", log_response)
            captured_urls: list[str] = []
            captured_image_urls: list[str] = []
            seen_urls: set[str] = set()

            def handle_response(response):
                nonlocal video_url, video_kind, aweme_post_url, top_comments, caption, image_urls, playwm_url
                nonlocal cover_url
                content_type = response.headers.get("content-type", "")
                candidate = response.url
                candidate_lower = candidate.lower()
                if is_douyin_aweme_image_url(candidate):
                    append_unique_douyin_aweme_image_url(captured_image_urls, candidate)
                if "aweme/v1/web/aweme/detail" in candidate_lower:
                    try:
                        payload = response.json()
                        play_list = (
                            payload.get("aweme_detail", {})
                            .get("video", {})
                            .get("play_addr", {})
                            .get("url_list", [])
                        )
                        if play_list:
                            video_url = play_list[0]
                        aweme_detail = payload.get("aweme_detail", {})
                        merge_stats(stats, extract_stats_from_aweme_detail(aweme_detail))
                        remember_item_id(stats, extract_aweme_id(aweme_detail))
                        if not cover_url:
                            cover_candidate = extract_cover_url_from_aweme(aweme_detail)
                            if cover_candidate:
                                cover_url = cover_candidate
                        detail_caption = extract_caption_from_aweme(aweme_detail)
                        if detail_caption and not caption:
                            caption = detail_caption
                            stats["caption_source"] = "aweme_detail.desc"
                        if not image_urls:
                            image_urls = extract_image_urls_from_aweme(aweme_detail)
                    except Exception:
                        pass
                if "/aweme/post/" in candidate_lower:
                    aweme_post_url = candidate
                    try:
                        payload = response.json()
                        play_url = extract_play_url_from_aweme_list(payload, settings.prefer_low_quality)
                        if play_url and not video_url:
                            video_url = play_url
                        aweme_list = payload.get("aweme_list", [])
                        if aweme_list:
                            aweme = aweme_list[0] if isinstance(aweme_list[0], dict) else {}
                            merge_stats(stats, extract_stats_from_aweme(aweme, "aweme_post"))
                            remember_item_id(stats, extract_aweme_id(aweme))
                            if not cover_url:
                                cover_candidate = extract_cover_url_from_aweme(aweme)
                                if cover_candidate:
                                    cover_url = cover_candidate
                            list_caption = extract_caption_from_aweme(aweme)
                            if list_caption and not caption:
                                caption = list_caption
                                stats["caption_source"] = "aweme_post.desc"
                            if not image_urls:
                                image_urls = extract_image_urls_from_aweme(aweme)
                    except Exception:
                        pass
                if "comment/list" in candidate_lower:
                    try:
                        payload = response.json()
                        incoming = extract_top_comments(payload, settings.top_comments_limit)
                        if incoming:
                            top_comments = merge_top_comments(
                                top_comments,
                                incoming,
                                settings.top_comments_limit,
                            )
                    except Exception:
                        pass
                if "aweme/v1/playwm" in candidate_lower:
                    playwm_url = candidate
                if "aweme/v1/play" in candidate_lower and response.status in (301, 302):
                    location = response.headers.get("location")
                    if debug_playwright:
                        print(f"[playwright] play redirect: {location}")
                    if location:
                        video_url = location
                if (
                    "video" in content_type
                    or "mp4" in content_type
                    or "mpegurl" in content_type
                    or ".mp4" in candidate_lower
                    or ".m3u8" in candidate_lower
                    or "mime_type=video_mp4" in candidate_lower
                    or "douyinvod" in candidate_lower
                    or "aweme/v1/play" in candidate_lower
                    or "video_id=" in candidate_lower
                ) and candidate not in seen_urls:
                    seen_urls.add(candidate)
                    captured_urls.append(candidate)

            page.on("response", handle_response)
            if is_xhs:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=90000)
                except PlaywrightTimeoutError:
                    page.goto(url, wait_until="load", timeout=90000)
            else:
                try:
                    with page.expect_response(
                        lambda response: "aweme/v1/web/aweme/detail" in response.url,
                        timeout=15000,
                    ) as response_info:
                        page.goto(url, wait_until="domcontentloaded")
                    detail_response = response_info.value
                    detail_url = extract_play_url_from_detail(
                        detail_response.json(),
                        settings.prefer_low_quality,
                    )
                    if detail_url:
                        video_url = detail_url
                except PlaywrightTimeoutError:
                    page.goto(url, wait_until="domcontentloaded")

            for _ in range(20):
                if video_url or aweme_post_url or is_xhs:
                    break
                page.wait_for_timeout(250)

            try:
                page_url = page.url
                page_title = page.title()
            except Exception:
                pass

            html = ""
            try:
                html = page.content()
            except Exception:
                html = ""

            xhs_base_url = page_url or url
            is_current_xhs = _is_xhs_url(xhs_base_url)
            if is_current_xhs and not cookies:
                try:
                    cookies = {
                        **cookies,
                        **{cookie["name"]: cookie["value"] for cookie in context.cookies()},
                    }
                except Exception:
                    cookies = {}

            xhs_note = _extract_xhs_note_from_html(html) if html and is_current_xhs else None
            if xhs_note:
                if xhs_note.get("caption") and not caption:
                    caption = xhs_note["caption"]
                if xhs_note.get("image_urls") and not image_urls:
                    image_urls = xhs_note["image_urls"]
                    if not cover_url and image_urls:
                        cover_url = str(image_urls[0])
                if xhs_note.get("video_url") and (
                    not video_url or (isinstance(video_url, str) and video_url.startswith("blob:"))
                ):
                    video_url = xhs_note["video_url"]
                    if isinstance(video_url, str) and ".m3u8" in video_url.lower():
                        video_kind = "m3u8"
                    else:
                        video_kind = "mp4"
                merge_interaction_fields(stats, xhs_note)
                note_id = xhs_note.get("note_id")
                if isinstance(note_id, str) and note_id:
                    stats["video_id"] = note_id

            if not is_xhs and not video_url:
                try:
                    page.wait_for_selector("video", timeout=15000)
                except PlaywrightTimeoutError:
                    try:
                        page.wait_for_selector(".video-container", timeout=5000)
                    except PlaywrightTimeoutError:
                        pass

                try:
                    ms_token = page.evaluate(
                        "() => window.msToken || window._msToken || "
                        "localStorage.getItem('msToken') || "
                        "sessionStorage.getItem('msToken') || ''"
                    )
                except Exception:
                    ms_token = ""

                time.sleep(random.uniform(1.0, 3.0))

            if not is_xhs and settings.top_comments_limit > 0 and not top_comments:
                try:
                    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(800)
                except Exception:
                    pass
                for _ in range(8):
                    if top_comments:
                        break
                    page.wait_for_timeout(400)

            if not video_url and not (is_xhs and image_urls):
                video_element = page.query_selector("video")
                if video_element:
                    try:
                        video_element.click()
                    except Exception:
                        pass
                    try:
                        page.evaluate("() => document.querySelector('video')?.play?.()")
                    except Exception:
                        pass

                    page.wait_for_timeout(1000)
                    candidate_url = video_element.get_attribute("src") or ""
                    if not candidate_url:
                        source_element = page.query_selector("video source")
                        if source_element:
                            candidate_url = source_element.get_attribute("src") or ""
                    if candidate_url and not (is_xhs and candidate_url.startswith("blob:")):
                        video_url = candidate_url

            if is_xhs and not video_url:
                for _ in range(12):
                    if any(
                        ".mp4" in candidate.lower() or ".m3u8" in candidate.lower()
                        for candidate in captured_urls
                    ):
                        break
                    page.wait_for_timeout(250)

            if captured_urls and (
                not video_url
                or (not settings.prefer_low_quality and not is_direct_video_url(video_url))
            ):
                for candidate in reversed(captured_urls):
                    candidate_lower = candidate.lower()
                    if (
                        ".mp4" in candidate_lower
                        or "douyinvod" in candidate_lower
                        or "mime_type=video_mp4" in candidate_lower
                    ):
                        video_url = candidate
                        video_kind = "mp4"
                        break

            if not video_url and captured_urls:
                for candidate in reversed(captured_urls):
                    if ".m3u8" in candidate.lower():
                        video_url = candidate
                        video_kind = "m3u8"
                        break
                if not video_url and captured_urls:
                    video_url = captured_urls[-1]

            if not video_url:
                if not page_title:
                    try:
                        page_title = page.title()
                    except Exception:
                        page_title = ""
                if not page_url:
                    try:
                        page_url = page.url
                    except Exception:
                        page_url = ""
                if not html:
                    try:
                        html = page.content()
                    except Exception:
                        html = ""
                if html:
                    html_video_url = extract_video_url_from_html(html)
                    if html_video_url:
                        video_url = html_video_url
                        if ".m3u8" in video_url.lower():
                            video_kind = "m3u8"
                    if not video_url:
                        render_data = extract_render_data(html)
                        if render_data:
                            render_url = find_video_url_in_render_data(render_data)
                            if render_url:
                                video_url = render_url
                            if not caption:
                                render_caption = find_caption_in_render_data(render_data)
                                if render_caption:
                                    caption = render_caption
                                    stats["caption_source"] = "render_data.desc"
                            if not image_urls:
                                image_urls = find_images_in_render_data(render_data)

            if not video_url:
                _kind, item_id = extract_douyin_id(page_url or url)
                if item_id:
                    item_meta = fetch_iesdouyin_item_meta(
                        item_id,
                        {
                            "User-Agent": user_agent,
                            "Referer": "https://www.iesdouyin.com/",
                        },
                        ms_token,
                        settings.prefer_low_quality,
                    )
                    merge_stats(stats, item_meta.get("stats", {}))
                    remember_item_id(stats, item_meta.get("aweme_id") or item_id)
                    item_url = item_meta.get("video_url")
                    if item_url:
                        video_url = str(item_url)
                    if not cover_url and item_meta.get("cover_url"):
                        cover_url = str(item_meta["cover_url"])
                    if not caption and item_meta.get("caption"):
                        caption = str(item_meta["caption"])
                        stats["caption_source"] = "iesdouyin_iteminfo.desc"
                    if not image_urls and isinstance(item_meta.get("image_urls"), list):
                        image_urls = item_meta["image_urls"]

            if not video_url and not image_urls and captured_image_urls:
                image_urls = captured_image_urls

            if is_xhs and video_url:
                video_lower = video_url.lower()
                if ".m3u8" in video_lower:
                    video_kind = "m3u8"
                elif ".mp4" in video_lower:
                    video_kind = "mp4"

            default_referer = "https://www.xiaohongshu.com/" if _is_xhs_url(page_url or url) else "https://www.douyin.com/"
            headers = {
                "User-Agent": user_agent,
                "Referer": page_url or default_referer,
            }
            cookies = {
                **cookies,
                **{cookie["name"]: cookie["value"] for cookie in context.cookies()},
            }
            if not is_xhs and any(stats.get(key) is None for key in INTERACTION_COUNT_KEYS):
                _kind, item_id = extract_douyin_id(page_url or url)
                if item_id:
                    remember_item_id(stats, item_id)
                    merge_stats(
                        stats,
                        fetch_douyin_aweme_detail_stats(item_id, headers, cookies, ms_token),
                    )
                    if any(stats.get(key) is None for key in INTERACTION_COUNT_KEYS):
                        item_meta = fetch_iesdouyin_item_meta(
                            item_id,
                            {
                                "User-Agent": user_agent,
                                "Referer": "https://www.iesdouyin.com/",
                            },
                            ms_token,
                            settings.prefer_low_quality,
                        )
                        merge_stats(stats, item_meta.get("stats", {}))
                        remember_item_id(stats, item_meta.get("aweme_id") or item_id)
            if not is_xhs and settings.top_comments_limit > 0 and not top_comments:
                _kind, item_id = extract_douyin_id(page_url or url)
                if item_id:
                    fetched = fetch_comment_list(
                        item_id,
                        headers,
                        cookies,
                        settings.top_comments_limit,
                        ms_token=ms_token,
                    )
                    if fetched:
                        top_comments = merge_top_comments(
                            top_comments,
                            fetched,
                            settings.top_comments_limit,
                        )
            if not video_url and aweme_post_url:
                if debug_playwright:
                    print(f"[playwright] aweme_post_url: {aweme_post_url}")
                play_url = fetch_aweme_post(
                    aweme_post_url,
                    headers,
                    cookies,
                    settings.prefer_low_quality,
                )
                if debug_playwright and play_url:
                    print(f"[playwright] aweme_post_play_url: {play_url}")
                if play_url:
                    video_url = play_url
            video_url = normalize_video_url(video_url, base_url=page_url or url)
            if settings.prefer_low_quality:
                if video_url:
                    video_url = adjust_playwm_ratio(video_url, settings.video_ratio)
                elif playwm_url:
                    video_url = adjust_playwm_ratio(playwm_url, settings.video_ratio)
            if video_url:
                print(f"视频地址: {summarize_url(video_url)}", flush=True)
            if debug_playwright:
                print(f"[playwright] final video_url: {video_url}")
            if not is_xhs and any(stats.get(key) is None for key in INTERACTION_COUNT_KEYS):
                _kind, screenshot_item_id = extract_douyin_id(page_url or url)
                capture_interaction_screenshot(page, page_url or url, stats, screenshot_item_id)
            context.close()
            if browser:
                browser.close()
    except _SkipPlaywright:
        pass
    except Exception as exc:
        print(f"下载失败: {exc}")
        print("可尝试设置 PLAYWRIGHT_HEADLESS=0 观察页面状态")
        stats["top_comments"] = top_comments
        finalize_interaction_stats(stats, is_xhs=is_xhs)
        return MediaResult(
            media_type="unknown",
            video_path=None,
            audio_path=None,
            image_paths=[],
            caption=caption,
            stats=stats,
        )

    if not cover_url and image_urls:
        cover_url = str(image_urls[0])
    if cover_url and not stats.get("cover_url"):
        stats["cover_url"] = cover_url

    caption = reconcile_caption_with_page_metadata(caption, stats)
    if caption:
        save_text(paths.caption_path, caption)
    stats["top_comments"] = top_comments
    if not stats.get("video_id"):
        stats["video_id"] = paths.video_id
    finalize_interaction_stats(stats, is_xhs=is_xhs)

    if not video_url or not video_url.startswith("http"):
        if image_urls:
            print("未获取视频地址，尝试下载图文资源。", flush=True)
            downloaded = download_images(
                image_urls,
                paths.image_dir,
                headers,
                cookies,
                settings,
                progress=progress,
                progress_range=(12, 40),
            )
            if not downloaded:
                print("图文下载失败。", flush=True)
                return MediaResult(
                    media_type="image",
                    video_path=None,
                    audio_path=None,
                    image_paths=[],
                    caption=caption,
                    stats=stats,
                )
            animated = any(is_animated_image(url) for url in image_urls)
            if animated:
                frames = extract_animated_frames(downloaded[0], os.path.join(paths.image_dir, "frames"))
                if frames:
                    return MediaResult(
                        media_type="animated",
                        video_path=None,
                        audio_path=None,
                        image_paths=frames,
                        caption=caption,
                        stats=stats,
                    )
                return MediaResult(
                    media_type="animated",
                    video_path=None,
                    audio_path=None,
                    image_paths=downloaded,
                    caption=caption,
                    stats=stats,
                )
            return MediaResult(
                media_type="image",
                video_path=None,
                audio_path=None,
                image_paths=downloaded,
                caption=caption,
                stats=stats,
            )
        if page_title or page_url:
            print(f"页面标题: {page_title}")
            print(f"最终地址: {page_url}")
        print("未能从页面中获取视频地址")
        _report_progress(progress, 20, "未能获取视频地址")
        return MediaResult(
            media_type="unknown",
            video_path=None,
            audio_path=None,
            image_paths=[],
            caption=caption,
            stats=stats,
        )
    print("视频地址已获取，开始下载视频流...", flush=True)
    _report_progress(progress, 12, "开始下载视频")

    video_url_lower = video_url.lower()
    prefer_ffmpeg = "douyinvod" in video_url_lower or settings.download_prefer_ffmpeg
    if video_kind == "m3u8" or ".m3u8" in video_url_lower:
        if not download_stream_with_ffmpeg(
            video_url,
            video_path,
            headers,
            cookies,
            settings,
            progress=progress,
            progress_range=(12, 40),
        ):
            print("视频下载失败")
            return MediaResult(
                media_type="unknown",
                video_path=None,
                audio_path=None,
                image_paths=[],
                caption=caption,
                stats=stats,
            )
    elif prefer_ffmpeg:
        if not download_stream_with_ffmpeg(
            video_url,
            video_path,
            headers,
            cookies,
            settings,
            progress=progress,
            progress_range=(12, 40),
        ):
            print("ffmpeg 下载失败")
            return MediaResult(
                media_type="unknown",
                video_path=None,
                audio_path=None,
                image_paths=[],
                caption=caption,
                stats=stats,
            )
    elif not download_stream(
        video_url,
        video_path,
        headers,
        cookies,
        settings,
        progress=progress,
        progress_range=(12, 40),
    ):
        print("请求下载失败")
        return MediaResult(
            media_type="unknown",
            video_path=None,
            audio_path=None,
            image_paths=[],
            caption=caption,
            stats=stats,
        )

    if settings.prefer_low_quality:
        transcode_video_to_ratio(video_path, settings.video_ratio, progress=progress)

    print("视频流下载完成，开始提取音频...", flush=True)
    _report_progress(progress, 40, "下载完成，提取音频")
    extracted_audio = extract_audio_mp3(video_path, audio_path)
    if not extracted_audio:
        print("音频提取失败。", flush=True)
        _report_progress(progress, 45, "音频提取失败")
    else:
        print("音频提取完成。", flush=True)
        _report_progress(progress, 45, "音频提取完成")
    stats["top_comments"] = top_comments
    if not stats.get("video_id"):
        stats["video_id"] = paths.video_id
    finalize_interaction_stats(stats, is_xhs=is_xhs)
    cover_paths = list_image_files(paths)
    if not cover_paths and image_urls:
        cover_paths = download_images(
            image_urls[:1],
            paths.image_dir,
            headers,
            cookies,
            settings,
            progress=progress,
            progress_range=(40, 45),
        )
    if not cover_paths:
        cover = extract_video_cover(video_path, paths.image_dir)
        if cover:
            cover_paths = [cover]
    return MediaResult(
        media_type="video",
        video_path=video_path,
        audio_path=extracted_audio or video_path,
        image_paths=cover_paths,
        caption=caption,
        stats=stats,
    )
