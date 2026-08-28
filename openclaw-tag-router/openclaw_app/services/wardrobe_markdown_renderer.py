from __future__ import annotations

import re
import os
from datetime import datetime
from pathlib import Path
from typing import Any


WARDROBE_ITEMS_ROOT_ENV = "OPENCLAW_WARDROBE_ITEMS_ROOT"


def resolve_wardrobe_items_root() -> Path:
    configured = os.getenv(WARDROBE_ITEMS_ROOT_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "obsidian-日记" / "物品"


DEFAULT_WARDROBE_ITEMS_ROOT = resolve_wardrobe_items_root()


def _safe_filename(value: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", value).strip(" .")
    text = re.sub(r"\s+", " ", text)
    return text[:80] or "wardrobe"


def _line_text(item: dict[str, Any]) -> str:
    color = str(item.get("color") or "").strip()
    brand = str(item.get("brand") or "").strip()
    occasion = item.get("occasion") or item.get("purpose") or ""
    if isinstance(occasion, list):
        occasion_text = "/".join(str(part).strip() for part in occasion if str(part).strip())
    else:
        occasion_text = str(occasion or "").strip()
    name = str(item.get("display_name") or item.get("name") or "").strip()
    note = str(item.get("note") or item.get("reason") or "").strip()
    prefix = "/".join(part for part in (color, brand) if part)
    body = " ".join(part for part in (prefix, occasion_text, name) if part)
    if note:
        body = f"{body} ({note})" if body else f"({note})"
    return body or name or "未命名单品"


def render_wardrobe_markdown_artifact(artifact: dict[str, Any], *, root: Path | None = None) -> Path:
    target_root = Path(root).expanduser() if root is not None else resolve_wardrobe_items_root()
    target_root.mkdir(parents=True, exist_ok=True)
    title = str(artifact.get("title") or "今日穿搭").strip()
    date_prefix = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"📝 {date_prefix} {_safe_filename(title)}.md"
    path = target_root / filename

    lines: list[str] = [f"# {title}", ""]
    source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
    table_url = str(source.get("wardrobe_table_url") or "").strip()
    record_ids = [str(item).strip() for item in source.get("item_record_ids") or [] if str(item).strip()]
    if table_url or record_ids:
        lines.append("## 来源")
        if table_url:
            lines.append(f"- 衣橱表：{table_url}")
        if record_ids:
            lines.append("- 单品记录：" + "、".join(record_ids))
        lines.append("")

    summary = str(artifact.get("summary") or "").strip()
    if summary:
        lines.extend(["## 建议", summary, ""])

    sections = artifact.get("sections") if isinstance(artifact.get("sections"), list) else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading") or "清单").strip()
        lines.append(f"## {heading}")
        items = section.get("items") if isinstance(section.get("items"), list) else []
        if not items:
            lines.append("- [ ] 待补充")
        for item in items:
            if isinstance(item, dict):
                lines.append(f"- [ ] {_line_text(item)}")
            else:
                text = str(item).strip()
                if text:
                    lines.append(f"- [ ] {text}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
