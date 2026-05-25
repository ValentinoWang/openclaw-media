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


def now_in_tz(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


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


def parse_tag_message(text: str) -> tuple[str, str]:
    normalized = text.strip()
    match = TAG_PATTERN.match(normalized)
    if not match:
        raise ValueError("消息不符合【标签】正文协议")
    return match.group("tag").strip(), match.group("body").strip()


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
