from __future__ import annotations

from collections import Counter
import json
import mimetypes
import os
import re
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse


XIAOHONGSHU_HOSTS = ("xiaohongshu.com", "xhslink.com", "xhslink.cn")


def is_xiaohongshu_url(url: str) -> bool:
    host = (urlparse((url or "").strip()).hostname or "").lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in XIAOHONGSHU_HOSTS)


def extract_douyin_id(url: str) -> tuple[str, Optional[str]]:
    if not url:
        return "", None
    local_match = re.search(r"douyin-(\d{8,})", url)
    if local_match:
        return "video", local_match.group(1)
    parsed = urlparse(url)
    patterns = [
        (r"/share/video/(\d+)", "video"),
        (r"/video/(\d+)", "video"),
        (r"/share/note/(\d+)", "note"),
        (r"/note/(\d+)", "note"),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, parsed.path)
        if match:
            return kind, match.group(1)

    query = parse_qs(parsed.query)
    query_keys = {
        "item_id": "video",
        "item_ids": "video",
        "aweme_id": "video",
        "modal_id": "video",
        "video_id": "video",
        "note_id": "note",
    }
    for key, kind in query_keys.items():
        if key in query and query[key]:
            raw_value = query[key][0]
            value = raw_value.split(",")[0]
            if value:
                return kind, value

    return "", None


def extract_xhs_id(url: str) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url)
    for pattern in (r"/discovery/item/([0-9a-fA-F]{10,})", r"/explore/([0-9a-fA-F]{10,})"):
        match = re.search(pattern, parsed.path)
        if match:
            return match.group(1)
    return None


def detect_platform(url: str) -> str:
    lower = url.lower()
    if "douyin.com" in lower or "iesdouyin.com" in lower or "aweme" in lower:
        return "抖音"
    if is_xiaohongshu_url(url):
        return "小红书"
    return "未知"


def normalize_video_url(video_url: Optional[str], base_url: str = "https://www.iesdouyin.com") -> Optional[str]:
    if not video_url:
        return None
    if not base_url:
        base_url = "https://www.iesdouyin.com"
    return urljoin(base_url, video_url)


def is_direct_video_url(video_url: Optional[str]) -> bool:
    if not video_url:
        return False
    lower = video_url.lower()
    return "douyinvod" in lower or ".mp4" in lower or "mime_type=video_mp4" in lower


def summarize_url(video_url: str, limit: int = 140) -> str:
    if len(video_url) <= limit:
        return video_url
    return f"{video_url[:limit]}..."


def parse_json_payload(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def extract_gemini_text(payload: dict) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""

    return "".join(part.get("text", "") for part in parts if isinstance(part, dict))


def guess_mime_type(file_path: str) -> str:
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type
    ext = os.path.splitext(file_path)[1].lower()
    default_mime_by_ext = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
    }
    return default_mime_by_ext.get(ext, "application/octet-stream")


def stringify_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [stringify_value(item) for item in value if item is not None]
        return "\n".join([part for part in parts if part])
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def normalize_tags(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = re.split(r"[,\n，/|、]+", value)
        return [item.strip() for item in raw if item.strip()]
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    items.append(cleaned)
            else:
                items.append(stringify_value(item))
        return [item for item in items if item]
    return [stringify_value(value)]


def extract_tags_from_text(text: str, limit: int = 6) -> list[str]:
    if not text:
        return []
    hashtags = re.findall(r"#([\w\u4e00-\u9fff]+)", text)
    hashtags = [tag.strip() for tag in hashtags if tag.strip()]

    zh_tokens = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    en_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)

    stop_zh = {
        "这个",
        "那个",
        "一个",
        "我们",
        "你们",
        "他们",
        "感觉",
        "真的",
        "就是",
        "不是",
        "比较",
        "可以",
        "应该",
        "因为",
        "所以",
        "但是",
        "然后",
        "如果",
        "需要",
        "这些",
        "那些",
        "这样",
        "什么",
        "怎么",
        "还是",
        "没有",
        "其实",
        "可能",
        "一定",
        "非常",
        "已经",
        "今天",
        "现在",
        "之后",
        "结果",
        "内容",
        "视频",
        "短视频",
        "账号",
    }
    stop_en = {
        "the",
        "and",
        "with",
        "that",
        "this",
        "from",
        "your",
        "you",
        "for",
        "are",
        "was",
        "is",
        "its",
        "not",
        "but",
        "just",
        "video",
    }

    counter: Counter[str] = Counter()
    for token in zh_tokens:
        if token in stop_zh:
            continue
        counter[token] += 1
    for token in en_tokens:
        lowered = token.lower()
        if lowered in stop_en:
            continue
        counter[token] += 1

    ranked = sorted(counter.items(), key=lambda item: (-item[1], -len(item[0])))
    tags: list[str] = []
    seen: set[str] = set()
    for tag in hashtags + [item[0] for item in ranked]:
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= limit:
            break
    return tags


def extract_tags_from_comments(comments: list[dict], limit: int = 6) -> list[str]:
    texts = []
    for comment in comments or []:
        text = comment.get("text") if isinstance(comment, dict) else ""
        if text:
            texts.append(str(text))
    if not texts:
        return []
    return extract_tags_from_text("\n".join(texts), limit=limit)


def merge_tag_lists(*tag_lists: list[str], limit: int = 8) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for tags in tag_lists:
        for tag in tags:
            if not tag:
                continue
            if tag in seen:
                continue
            seen.add(tag)
            merged.append(tag)
            if len(merged) >= limit:
                return merged
    return merged
