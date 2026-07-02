from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from ..models.archive_entry import ArchiveEntry
from ..models.message import Message
from .utils import dump_json, ensure_dir, format_display_time, make_record_id, safe_slug

ARCHIVE_DIR_MAP = {
    "灵感": "inspirations",
    "待办": "todos",
    "日程": "schedules",
    "待办-开发": "development",
    "周记": "weekly_reviews",
    "今日": "task_commands",
    "开发-完成": "task_commands",
    "开发-验证": "task_commands",
    "活动": "campaigns",
    "内容素材": "selfmedia",
    "灵感>vlog": "vlog_inspirations",
    "转写": "transcripts",
    "转写-文字": "transcripts",
    "社交": "social",
    "复盘": "reviews",
    "整理": "reports",
}


class ArchiveService:
    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root)
        ensure_dir(self.root / "inbox")
        ensure_dir(self.root / "archive")

    def save_inbox(self, message: Message) -> str:
        record_id = make_record_id(message.created_at, message.source, message.entry_tag)
        inbox_path = self.root / "inbox" / f"{record_id}.json"
        dump_json(inbox_path, message.to_dict())
        return str(inbox_path)

    def save_archive(self, message: Message, title: str, sections: list[tuple[str, str]], extra_frontmatter: dict[str, Any] | None = None) -> ArchiveEntry:
        record_id = make_record_id(message.created_at, message.source, message.entry_tag)
        frontmatter = {
            "id": record_id,
            "source": message.source,
            "entry_tag": message.entry_tag,
            "created_at": format_display_time(message.created_at),
            "status": "archived",
            "tags": [],
            "feishu_synced": False,
            "feishu_doc": "",
        }
        if extra_frontmatter:
            frontmatter.update(extra_frontmatter)
        bucket = ARCHIVE_DIR_MAP.get(message.entry_tag, safe_slug(message.entry_tag))
        archive_dir = ensure_dir(self.root / "archive" / bucket)
        filename = f"{record_id}.md"
        path = archive_dir / filename
        content = self.render_markdown(frontmatter, title, sections)
        path.write_text(content, encoding="utf-8")
        return ArchiveEntry(frontmatter=frontmatter, title=title, sections=sections, local_path=str(path))

    def load_archive(self, path: str | Path) -> ArchiveEntry:
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8")
        frontmatter: dict[str, Any] = {}
        body = text
        if text.startswith("---\n"):
            _, _, remainder = text.partition("---\n")
            frontmatter_text, sep, content = remainder.partition("\n---\n")
            if sep:
                frontmatter = yaml.safe_load(frontmatter_text) or {}
                body = content

        title = ""
        sections: list[tuple[str, str]] = []
        current_heading = ""
        current_lines: list[str] = []
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                continue
            if line.startswith("## "):
                if current_heading:
                    sections.append((current_heading, "\n".join(current_lines).strip()))
                current_heading = line[3:].strip()
                current_lines = []
                continue
            if current_heading:
                current_lines.append(line)
        if current_heading:
            sections.append((current_heading, "\n".join(current_lines).strip()))

        return ArchiveEntry(frontmatter=frontmatter, title=title, sections=sections, local_path=str(file_path))

    def list_archives(
        self,
        *,
        limit: int | None = None,
        tag: str | None = None,
        status: str | None = None,
        created_on: date | None = None,
    ) -> list[ArchiveEntry]:
        paths = sorted((self.root / "archive").glob("**/*.md"), reverse=True)
        entries: list[ArchiveEntry] = []
        created_prefix = created_on.strftime("%y%m%d") if created_on else ""
        for path in paths:
            entry = self.load_archive(path)
            frontmatter = entry.frontmatter
            entry_tag = frontmatter.get("entry_tag")
            if tag and entry_tag != tag:
                continue
            if status and frontmatter.get("status") != status:
                continue
            if created_prefix and not str(frontmatter.get("created_at", "")).startswith(created_prefix):
                continue
            entries.append(entry)
            if limit is not None and len(entries) >= limit:
                break
        return entries

    def get_archive_by_id(self, record_id: str) -> ArchiveEntry | None:
        for path in sorted((self.root / "archive").glob("**/*.md"), reverse=True):
            if path.stem == record_id:
                return self.load_archive(path)
        return None

    def update_frontmatter(self, path: str | Path, updates: dict[str, Any]) -> ArchiveEntry:
        entry = self.load_archive(path)
        entry.frontmatter.update(updates)
        Path(entry.local_path).write_text(self.render_markdown(entry.frontmatter, entry.title, entry.sections), encoding="utf-8")
        return entry

    @staticmethod
    def render_markdown(frontmatter: dict[str, Any], title: str, sections: list[tuple[str, str]]) -> str:
        parts = ["---", yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip(), "---", "", f"# {title}", ""]
        for heading, body in sections:
            parts.append(f"## {heading}")
            parts.append(body.strip())
            parts.append("")
        return "\n".join(parts).strip() + "\n"
