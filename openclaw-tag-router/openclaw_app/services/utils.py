from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from zoneinfo import ZoneInfo

TAG_PATTERN = re.compile(r"^【(?P<tag>[^】]+)】\s*(?P<body>[\s\S]*)$")
LINK_PATTERN = re.compile(r"https?://\S+|xhslink\.com/\S+|douyin\.com/\S+")
THINKING_SUFFIX_RE = re.compile(r"^(?P<tag>.+)\^(?P<thinking>xhigh|high|medium|low|minimal|off)$", re.IGNORECASE)
THINKING_SUFFIX_ALIASES = {
    "xhigh": "high",
}
TAG_ALIASES = {
    "帮助": "说明",
    "自媒体": "自媒体知识",
}
BUSINESS_AUTHOR_TAG_RE = re.compile(r"^商务>(?P<author>(?!ID$)[^】>\s]{1,32})$")


def now_in_tz(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def cleanup_generated_file_duplicates(path: str | Path) -> list[Path]:
    p = Path(path)
    if not p.suffix or not p.parent.exists():
        return []
    removed: list[Path] = []
    for pattern in (f"{p.stem} [0-9]*{p.suffix}", f"{p.stem}.sync-conflict-*{p.suffix}"):
        for candidate in p.parent.glob(pattern):
            if candidate == p or not candidate.is_file():
                continue
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue
            removed.append(candidate)
    return sorted(removed)


def load_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def dump_yaml(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def parse_tag_message_with_metadata(text: str) -> tuple[str, str, dict[str, Any]]:
    normalized = text.strip()
    match = TAG_PATTERN.match(normalized)
    if not match:
        raise ValueError("消息不符合【标签】正文协议")
    tag = match.group("tag").strip()
    body = match.group("body").strip()
    metadata: dict[str, Any] = {}
    thinking_match = THINKING_SUFFIX_RE.match(tag)
    if thinking_match:
        raw_tag = tag
        raw_thinking = thinking_match.group("thinking").strip().lower()
        tag = thinking_match.group("tag").strip()
        metadata["raw_entry_tag"] = raw_tag
        metadata["tag_thinking_suffix"] = raw_thinking
        metadata["tag_thinking"] = THINKING_SUFFIX_ALIASES.get(raw_thinking, raw_thinking)
    alias = TAG_ALIASES.get(tag)
    if alias:
        return alias, body, metadata
    business_author = BUSINESS_AUTHOR_TAG_RE.match(tag)
    if business_author and tag != "商务>ID":
        author_id = business_author.group("author").strip()
        body = f"作者ID：{author_id}\n{body}" if body else f"作者ID：{author_id}"
        return "商务>ID", body, metadata
    return tag, body, metadata


def parse_tag_message(text: str) -> tuple[str, str]:
    tag, body, _metadata = parse_tag_message_with_metadata(text)
    return tag, body


def short_id() -> str:
    return uuid.uuid4().hex[:4]


def make_record_id(created_at: datetime, source: str, tag: str) -> str:
    return f"{created_at.strftime('%Y%m%d-%H%M%S')}-{source}-{tag}-{short_id()}"


def format_display_time(dt: datetime) -> str:
    return dt.strftime("%y%m%d %H:%M")


def dump_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def contains_link(text: str) -> bool:
    return bool(LINK_PATTERN.search(text))


def safe_slug(text: str, max_len: int = 24) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text, flags=re.UNICODE).strip("-")
    return cleaned[:max_len] or "entry"
