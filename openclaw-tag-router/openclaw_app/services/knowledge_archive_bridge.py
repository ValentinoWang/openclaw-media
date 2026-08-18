from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


DEFAULT_KNOWLEDGE_ARCHIVE_SCRIPT = Path("/home/ubuntu/openclaw-agents/knowledge/scripts/archive_to_obsidian.py")
DEFAULT_OBSIDIAN_ROOT = Path(os.environ.get("OBSIDIAN_ROOT", "/home/ubuntu/obsidian-日记"))
ARCHIVE_SECTION = "知识"
DEFAULT_KNOWLEDGE_ARCHIVE_SCRIPT_TIMEOUT_SECONDS = 180
def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


KNOWLEDGE_ARCHIVE_SCRIPT_TIMEOUT_SECONDS = _env_int(
    "OPENCLAW_KNOWLEDGE_ARCHIVE_SCRIPT_TIMEOUT_SECONDS",
    DEFAULT_KNOWLEDGE_ARCHIVE_SCRIPT_TIMEOUT_SECONDS,
)


def _subprocess_timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


@dataclass(frozen=True)
class KnowledgeArchiveBridgeResult:
    ok: bool
    status: str
    path: str = ""
    section: str = ARCHIVE_SECTION
    title: str = ""
    error: str = ""
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "path": self.path,
            "section": self.section,
            "title": self.title,
            "error": self.error,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def extract_markdown_heading_section(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"(?m)^##[ \t]+{re.escape(heading)}[ \t]*$")
    match = pattern.search(markdown)
    if not match:
        return ""
    body_start = match.end()
    body_end = len(markdown)
    next_h2 = re.search(r"(?m)^##[ \t]+.+?\s*$", markdown[body_start:])
    if next_h2:
        body_end = body_start + next_h2.start()
    return markdown[body_start:body_end].strip()


def _meeting_note_date(path: Path, markdown: str) -> date:
    filename_match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", path.name)
    if filename_match:
        return date(*(int(part) for part in filename_match.groups()))
    frontmatter_match = re.search(r"(?m)^created_at:[ \t]*['\"]?(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", markdown)
    if frontmatter_match:
        year, month, day = (int(part) for part in frontmatter_match.groups())
        return date(year, month, day)
    return datetime.now().date()


def _meeting_note_title(path: Path, markdown: str) -> str:
    match = re.search(r"(?m)^# [ \t]*(.+?)\s*$", markdown)
    title = match.group(1).strip() if match else path.stem
    title = re.sub(r"^20\d{2}-\d{2}-\d{2}[ \t]+", "", title).strip()
    title = re.sub(r"\s+", " ", title).strip()
    return title[:80] or "会议纪要"


def _week_note_path(obsidian_root: Path, target_date: date) -> Path:
    start = target_date - timedelta(days=target_date.weekday())
    end = start + timedelta(days=6)
    return obsidian_root / "Archieve" / f"{start:%Y%m%d}-{end:%Y%m%d}.md"


def _demote_content_headings(markdown: str) -> str:
    lines: list[str] = []
    for line in markdown.strip().splitlines():
        if line.startswith("### "):
            lines.append("##### " + line[4:].strip())
        elif line.startswith("## "):
            lines.append("#### " + line[3:].strip())
        elif line.startswith("# "):
            lines.append("#### " + line[2:].strip())
        else:
            lines.append(line.rstrip())
    rendered = "\n".join(lines).strip()
    if not re.search(r"(?m)^####[ \t]+", rendered):
        rendered = "#### 核心整理\n\n" + rendered
    return rendered


def _meeting_note_frontmatter(markdown: str) -> dict[str, Any]:
    if not markdown.startswith("---\n"):
        return {}
    _, _, remainder = markdown.partition("---\n")
    frontmatter_text, sep, _ = remainder.partition("\n---\n")
    if not sep:
        return {}
    try:
        loaded = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _normalize_archive_summary_bullets(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = value.splitlines()
    elif isinstance(value, list):
        candidates = [str(item) for item in value]
    else:
        candidates = []
    bullets: list[str] = []
    for item in candidates:
        text = re.sub(r"^\s*[-*•\d.、]+\s*", "", str(item or "")).strip()
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            bullets.append(text)
        if len(bullets) >= 5:
            break
    return bullets


def _raw_transcript_path_from_note(note_path: Path, frontmatter: dict[str, Any], obsidian_root: Path) -> Path:
    raw_value = str(frontmatter.get("raw_transcript_path") or "").strip().strip("'\"")
    candidates: list[Path] = []
    if raw_value:
        raw_path = Path(raw_value).expanduser()
        if not raw_path.is_absolute():
            raw_path = note_path.parent / raw_path
        candidates.append(raw_path)
    candidates.append(obsidian_root / "会议纪要" / "原字稿" / f"{note_path.stem}-原字稿.md")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _archive_entry_markdown(
    target_date: date,
    title: str,
    note_path: Path,
    content_section: str,
    obsidian_root: Path,
    *,
    macro_summary: str,
    summary_bullets: list[str],
    raw_transcript_path: Path,
) -> str:
    del content_section
    week_note = _week_note_path(obsidian_root, target_date)
    note_link = os.path.relpath(note_path, start=week_note.parent).replace(os.sep, "/")
    raw_link = os.path.relpath(raw_transcript_path, start=week_note.parent).replace(os.sep, "/")
    bullets = "\n".join(f"- {item}" for item in summary_bullets[:5])
    return (
        f"### {target_date:%y-%m-%d} {title}\n\n"
        f"宏观总结：{macro_summary}\n\n"
        f"{bullets}\n\n"
        f"详细链接：[{note_path.stem}]({note_link})\n"
        f"原字稿链接：[{raw_transcript_path.stem}]({raw_link})\n"
    )


def _remove_existing_archive_entries(markdown: str, marker: str) -> tuple[str, int]:
    starts = [match.start() for match in re.finditer(r"(?m)^#{3,4}[ \t]+.+$", markdown)]
    if not starts:
        return markdown, 0
    starts.append(len(markdown))
    chunks: list[str] = []
    cursor = 0
    removed = 0
    for index, start in enumerate(starts[:-1]):
        end = starts[index + 1]
        chunks.append(markdown[cursor:start])
        block = markdown[start:end]
        if marker in block:
            removed += 1
        else:
            chunks.append(block)
        cursor = end
    chunks.append(markdown[cursor:])
    updated = "".join(chunks)
    updated = re.sub(r"\n{4,}", "\n\n\n", updated).rstrip() + "\n"
    return updated, removed


def archive_meeting_content_section(
    meeting_note_path: str | Path,
    *,
    archive_script: str | Path = DEFAULT_KNOWLEDGE_ARCHIVE_SCRIPT,
    obsidian_root: str | Path = DEFAULT_OBSIDIAN_ROOT,
    dry_run: bool = False,
    refresh: bool = False,
) -> KnowledgeArchiveBridgeResult:
    note_path = Path(meeting_note_path)
    try:
        markdown = note_path.read_text(encoding="utf-8")
    except OSError as exc:
        return KnowledgeArchiveBridgeResult(ok=False, status="read_failed", error=str(exc))

    content_section = extract_markdown_heading_section(markdown, "1. 结论摘要")
    if not content_section:
        return KnowledgeArchiveBridgeResult(ok=False, status="missing_conclusion_summary")

    frontmatter = _meeting_note_frontmatter(markdown)
    macro_summary = str(frontmatter.get("archive_macro_summary") or "").strip()
    summary_bullets = _normalize_archive_summary_bullets(frontmatter.get("archive_summary_bullets"))
    if not macro_summary or not summary_bullets:
        return KnowledgeArchiveBridgeResult(ok=False, status="missing_weekly_archive_summary")

    target_date = _meeting_note_date(note_path, markdown)
    title = f"{_meeting_note_title(note_path, markdown)} 会议纪要"
    root = Path(obsidian_root)
    raw_transcript_path = _raw_transcript_path_from_note(note_path, frontmatter, root)
    if not raw_transcript_path.is_file():
        return KnowledgeArchiveBridgeResult(
            ok=False,
            status="missing_raw_transcript",
            title=title,
            error=str(raw_transcript_path),
        )
    week_note = _week_note_path(root, target_date)
    note_marker = note_path.name
    removed_existing = 0
    if week_note.exists():
        week_text = week_note.read_text(encoding="utf-8")
        if note_marker in week_text:
            if not refresh:
                return KnowledgeArchiveBridgeResult(ok=True, status="skipped_existing", path=str(week_note), title=title)
            updated_week_text, removed_existing = _remove_existing_archive_entries(week_text, note_marker)
            if not dry_run:
                week_note.write_text(updated_week_text, encoding="utf-8")

    payload = {
        "date": target_date.isoformat(),
        "section": ARCHIVE_SECTION,
        "subsection": "转写",
        "title": title,
        "text": f"【归档】{title}",
        "entry_markdown": _archive_entry_markdown(
            target_date,
            title,
            note_path,
            content_section,
            root,
            macro_summary=macro_summary,
            summary_bullets=summary_bullets,
            raw_transcript_path=raw_transcript_path,
        ),
        "logic_check": "来自转写会议纪要的 LLM 周记摘要字段；归档前已校验会议纪要和原字稿路径，便于回查详细纪要和原字稿。",
    }
    if dry_run:
        status = "dry_run_refresh" if refresh and removed_existing else "dry_run"
        return KnowledgeArchiveBridgeResult(ok=True, status=status, path=str(week_note), title=title)

    script_path = Path(archive_script)
    if not script_path.is_file():
        return KnowledgeArchiveBridgeResult(ok=False, status="script_missing", error=str(script_path), title=title)

    env = os.environ.copy()
    env["OBSIDIAN_ROOT"] = str(root)
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), "--json"],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            env=env,
            check=False,
            timeout=KNOWLEDGE_ARCHIVE_SCRIPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return KnowledgeArchiveBridgeResult(
            ok=False,
            status="archive_timeout",
            title=title,
            stdout=_subprocess_timeout_text(exc.stdout),
            stderr=_subprocess_timeout_text(exc.stderr),
            error=f"archive_to_obsidian timed out after {KNOWLEDGE_ARCHIVE_SCRIPT_TIMEOUT_SECONDS}s",
        )
    if proc.returncode != 0:
        return KnowledgeArchiveBridgeResult(
            ok=False,
            status="archive_failed",
            title=title,
            stdout=proc.stdout.strip(),
            stderr=proc.stderr.strip(),
            error=f"archive_to_obsidian exited {proc.returncode}",
        )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return KnowledgeArchiveBridgeResult(
            ok=False,
            status="archive_result_invalid",
            title=title,
            stdout=proc.stdout.strip(),
            stderr=proc.stderr.strip(),
            error="archive_to_obsidian did not return JSON",
        )
    return KnowledgeArchiveBridgeResult(
        ok=bool(result.get("ok")),
        status="archived" if result.get("ok") else "archive_failed",
        path=str(result.get("path") or week_note),
        section=str(result.get("section") or ARCHIVE_SECTION),
        title=title,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
    )
