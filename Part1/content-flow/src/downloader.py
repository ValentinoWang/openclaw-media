from __future__ import annotations

from dataclasses import dataclass
import json
import os
import random
import re
import subprocess
import time
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

MOBILE_SAFARI_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)


class _SkipPlaywright(Exception):
    pass


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

    cleaned = value.strip().replace("+", "")
    if not cleaned:
        return None

    multiplier = 1
    if "千" in cleaned:
        multiplier = 1000
        cleaned = cleaned.replace("千", "")
    elif "万" in cleaned:
        multiplier = 10000
        cleaned = cleaned.replace("万", "")
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

    interact = note.get("interactInfo") or {}
    if not isinstance(interact, dict):
        interact = {}

    return {
        "note_id": note_id,
        "note_type": note.get("type"),
        "caption": caption,
        "image_urls": _extract_xhs_image_urls(note),
        "video_url": _extract_xhs_video_url(note),
        "like_count": _parse_xhs_count(interact.get("likedCount") or interact.get("likeCount")),
        "comment_count": _parse_xhs_count(interact.get("commentCount")),
        "share_count": _parse_xhs_count(interact.get("shareCount")),
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


def find_stats_in_render_data(payload: object) -> Optional[dict]:
    if isinstance(payload, dict):
        stats = payload.get("statistics") or payload.get("statistic")
        if isinstance(stats, dict):
            return stats
        for value in payload.values():
            found = find_stats_in_render_data(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = find_stats_in_render_data(item)
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


def extract_stats_from_aweme(aweme: dict) -> dict:
    stats = aweme.get("statistics") or aweme.get("statistic") or {}
    def first_present(keys: list[str]) -> Optional[object]:
        for key in keys:
            if key in stats:
                return stats[key]
        return None

    return {
        "like_count": first_present(["digg_count", "likeCount", "like_count"]),
        "comment_count": first_present(["comment_count", "commentCount"]),
        "share_count": first_present(["share_count", "shareCount"]),
    }


def merge_stats(target: dict, incoming: dict) -> dict:
    for key, value in incoming.items():
        if value is None or target.get(key) is not None:
            continue
        try:
            target[key] = int(value)
        except (TypeError, ValueError):
            target[key] = value
    return target


def extract_top_comments(payload: dict, limit: int) -> list[dict]:
    comments = payload.get("comments") or []
    results: list[dict] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        text = comment.get("text") or ""
        user = comment.get("user") or {}
        author = user.get("nickname") or ""
        like_count = comment.get("digg_count") or comment.get("like_count") or comment.get("diggCount")
        cid = comment.get("cid") or comment.get("id")
        try:
            like_count = int(like_count)
        except (TypeError, ValueError):
            like_count = 0
        results.append(
            {
                "cid": cid,
                "text": text,
                "author": author,
                "like_count": like_count,
            }
        )
    results.sort(key=lambda item: item.get("like_count", 0), reverse=True)
    return results[: max(limit, 1)]


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


def fetch_iesdouyin_item(
    video_id: str,
    headers: dict,
    ms_token: str | None,
    prefer_low_quality: bool,
) -> Optional[str]:
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
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    items = payload.get("item_list", [])
    if not items:
        return None

    return select_play_url_prefer_low(items[0].get("video", {}), prefer_low_quality)


def fetch_iesdouyin_stats(video_id: str, headers: dict, ms_token: str | None) -> dict:
    if not video_id:
        return {}
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
        payload = response.json()
    except (requests.RequestException, ValueError):
        return {}

    items = payload.get("item_list", [])
    if not items:
        return {}
    return extract_stats_from_aweme(items[0])


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
    cookies: dict = {}
    debug_playwright = settings.playwright_debug

    _report_progress(progress, 18, "刷新互动数据")
    if is_xhs:
        headers = {
            "User-Agent": MOBILE_SAFARI_USER_AGENT,
            "Referer": "https://www.xiaohongshu.com/",
        }
        html = _fetch_html(url, headers, {})
        note = _extract_xhs_note_from_html(html) if html else None
        if note:
            for key in ("like_count", "comment_count", "share_count"):
                if note.get(key) is not None:
                    stats[key] = note[key]
            note_id = note.get("note_id")
            if isinstance(note_id, str) and note_id:
                stats["video_id"] = note_id
            image_urls = note.get("image_urls")
            if isinstance(image_urls, list) and image_urls:
                candidate = image_urls[0]
                if isinstance(candidate, str) and candidate.strip():
                    stats["cover_url"] = candidate.strip()
        return stats

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
                        **device_settings,
                    )
                except Exception:
                    context = None
            else:
                context = None

            if context is None:
                browser = p.webkit.launch(headless=settings.playwright_headless)
                context = browser.new_context(**device_settings)
            page = context.new_page()

            def handle_response(response):
                nonlocal cover_url, top_comments
                candidate = response.url.lower()
                if "aweme/v1/web/aweme/detail" in candidate:
                    try:
                        payload = response.json()
                        aweme_detail = payload.get("aweme_detail", {})
                        merge_stats(stats, extract_stats_from_aweme(aweme_detail))
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
                            merge_stats(stats, extract_stats_from_aweme(aweme_list[0]))
                            if not cover_url:
                                cover_candidate = extract_cover_url_from_aweme(aweme_list[0])
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
                for key in ("like_count", "comment_count", "share_count")
            )
            if missing_counts:
                try:
                    html = page.content()
                except Exception:
                    html = ""
                if html:
                    render_data = extract_render_data(html)
                    if render_data:
                        render_stats = find_stats_in_render_data(render_data)
                        if render_stats:
                            merge_stats(stats, extract_stats_from_aweme({"statistics": render_stats}))

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
                "Referer": page_url or "https://www.iesdouyin.com/",
            }
            cookies = {cookie["name"]: cookie["value"] for cookie in context.cookies()}
            missing_counts = any(
                stats.get(key) is None
                for key in ("like_count", "comment_count", "share_count")
            )
            if missing_counts:
                _kind, item_id = extract_douyin_id(page_url or url)
                if item_id:
                    merge_stats(stats, fetch_iesdouyin_stats(item_id, headers, ms_token))

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
    return stats


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
    stats: dict = {}
    cached_analysis = load_json(paths.analysis_path)
    if isinstance(cached_analysis, dict):
        stats = {
            "like_count": cached_analysis.get("like_count"),
            "comment_count": cached_analysis.get("comment_count"),
            "share_count": cached_analysis.get("share_count"),
            "top_comments": cached_analysis.get("top_comments"),
            "video_id": cached_analysis.get("video_id"),
            "cover_url": cached_analysis.get("cover_url"),
        }
    if "video_id" not in stats or not stats.get("video_id"):
        stats["video_id"] = paths.video_id
    caption = load_text(paths.caption_path) or ""

    if media_exists(paths.video_path):
        print(f"检测到已下载视频: {paths.video_path}，跳过下载。", flush=True)
        _report_progress(progress, 40, "已存在视频，跳过下载")
        cover_paths = list_image_files(paths)
        if not cover_paths:
            cover = extract_video_cover(paths.video_path, paths.image_dir)
            if cover:
                cover_paths = [cover]
        if media_exists(paths.audio_path):
            print(f"检测到已下载音频: {paths.audio_path}，跳过提取。", flush=True)
            _report_progress(progress, 45, "已存在音频")
            missing_counts = any(
                stats.get(key) is None
                for key in ("like_count", "comment_count", "share_count")
            )
            missing_comments = settings.top_comments_limit > 0 and not stats.get("top_comments")
            if missing_counts or missing_comments:
                refreshed = refresh_stats_only(url, settings, progress=progress)
                merge_stats(stats, refreshed)
                if refreshed.get("top_comments"):
                    stats["top_comments"] = refreshed.get("top_comments")
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
            missing_counts = any(
                stats.get(key) is None
                for key in ("like_count", "comment_count", "share_count")
            )
            missing_comments = settings.top_comments_limit > 0 and not stats.get("top_comments")
            if missing_counts or missing_comments:
                refreshed = refresh_stats_only(url, settings, progress=progress)
                merge_stats(stats, refreshed)
                if refreshed.get("top_comments"):
                    stats["top_comments"] = refreshed.get("top_comments")
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
    stats: dict = {"like_count": None, "comment_count": None, "share_count": None}
    stats["video_id"] = paths.video_id
    top_comments: list[dict] = []
    image_urls: list[str] = []
    cover_url: str = ""
    caption = ""
    headers: dict = {}
    cookies: dict = {}
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
        direct_html = _fetch_html(url, xhs_headers, {})
        xhs_note = _extract_xhs_note_from_html(direct_html) if direct_html else None
        if xhs_note:
            if xhs_note.get("caption"):
                caption = xhs_note["caption"]
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
            for key in ("like_count", "comment_count", "share_count"):
                if xhs_note.get(key) is not None:
                    stats[key] = xhs_note[key]
            note_id = xhs_note.get("note_id")
            if isinstance(note_id, str) and note_id:
                stats["video_id"] = note_id
            headers = xhs_headers

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
                        **device_settings,
                    )
                except Exception:
                    context = None
            else:
                context = None

            if context is None:
                browser = p.webkit.launch(headless=headless)
                context = browser.new_context(**device_settings)
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
            seen_urls: set[str] = set()

            def handle_response(response):
                nonlocal video_url, video_kind, aweme_post_url, top_comments, caption, image_urls, playwm_url
                nonlocal cover_url
                content_type = response.headers.get("content-type", "")
                candidate = response.url
                candidate_lower = candidate.lower()
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
                        merge_stats(stats, extract_stats_from_aweme(aweme_detail))
                        if not cover_url:
                            cover_candidate = extract_cover_url_from_aweme(aweme_detail)
                            if cover_candidate:
                                cover_url = cover_candidate
                        detail_caption = extract_caption_from_aweme(aweme_detail)
                        if detail_caption and not caption:
                            caption = detail_caption
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
                            merge_stats(stats, extract_stats_from_aweme(aweme_list[0]))
                            if not cover_url:
                                cover_candidate = extract_cover_url_from_aweme(aweme_list[0])
                                if cover_candidate:
                                    cover_url = cover_candidate
                            list_caption = extract_caption_from_aweme(aweme_list[0])
                            if list_caption and not caption:
                                caption = list_caption
                            if not image_urls:
                                image_urls = extract_image_urls_from_aweme(aweme_list[0])
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
                    cookies = {cookie["name"]: cookie["value"] for cookie in context.cookies()}
                except Exception:
                    cookies = {}

            xhs_note = _extract_xhs_note_from_html(html) if html and is_current_xhs else None
            if is_current_xhs and (not xhs_note or not xhs_note.get("video_url")):
                fallback_html = _fetch_html(
                    xhs_base_url,
                    headers={
                        "User-Agent": user_agent,
                        "Referer": "https://www.xiaohongshu.com/",
                    },
                    cookies=cookies,
                )
                fallback_note = _extract_xhs_note_from_html(fallback_html) if fallback_html else None
                if fallback_note:
                    if not xhs_note:
                        xhs_note = fallback_note
                    else:
                        for key in ("note_id", "caption", "video_url"):
                            if not xhs_note.get(key) and fallback_note.get(key):
                                xhs_note[key] = fallback_note[key]
                        if (not xhs_note.get("image_urls")) and fallback_note.get("image_urls"):
                            xhs_note["image_urls"] = fallback_note["image_urls"]
                        for key in ("like_count", "comment_count", "share_count"):
                            if xhs_note.get(key) is None and fallback_note.get(key) is not None:
                                xhs_note[key] = fallback_note[key]
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
                for key in ("like_count", "comment_count", "share_count"):
                    if xhs_note.get(key) is not None:
                        stats[key] = xhs_note[key]
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
                            if not image_urls:
                                image_urls = find_images_in_render_data(render_data)

            if not video_url:
                _kind, item_id = extract_douyin_id(page_url or url)
                if item_id:
                    item_url = fetch_iesdouyin_item(
                        item_id,
                        {
                            "User-Agent": user_agent,
                            "Referer": "https://www.iesdouyin.com/",
                        },
                        ms_token,
                        settings.prefer_low_quality,
                    )
                    if item_url:
                        video_url = item_url

            if is_xhs and video_url:
                video_lower = video_url.lower()
                if ".m3u8" in video_lower:
                    video_kind = "m3u8"
                elif ".mp4" in video_lower:
                    video_kind = "mp4"

            default_referer = "https://www.xiaohongshu.com/" if _is_xhs_url(page_url or url) else "https://www.iesdouyin.com/"
            headers = {
                "User-Agent": user_agent,
                "Referer": page_url or default_referer,
            }
            cookies = {cookie["name"]: cookie["value"] for cookie in context.cookies()}
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
            if settings.prefer_low_quality and not video_url and playwm_url:
                video_url = adjust_playwm_ratio(playwm_url, settings.video_ratio)
            video_url = normalize_video_url(video_url, base_url=page_url or url)
            if video_url:
                print(f"视频地址: {summarize_url(video_url)}", flush=True)
            if debug_playwright:
                print(f"[playwright] final video_url: {video_url}")
            context.close()
            if browser:
                browser.close()
    except _SkipPlaywright:
        pass
    except Exception as exc:
        print(f"下载失败: {exc}")
        print("可尝试设置 PLAYWRIGHT_HEADLESS=0 观察页面状态")
        stats["top_comments"] = top_comments
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

    if caption:
        save_text(paths.caption_path, caption)
    stats["top_comments"] = top_comments
    if not stats.get("video_id"):
        stats["video_id"] = paths.video_id

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
            print("ffmpeg 下载失败，尝试使用 requests 兜底...", flush=True)
            if not download_stream(
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
    elif not download_stream(
        video_url,
        video_path,
        headers,
        cookies,
        settings,
        progress=progress,
        progress_range=(12, 40),
    ):
        print("请求下载失败，尝试使用 ffmpeg 兜底...", flush=True)
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
