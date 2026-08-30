from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..services.markdown_frontmatter import read_frontmatter_tolerant


TARGET_ID_RE = re.compile(
    r"https?://[^\s`，。；;,]+|"
    r"\bper_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b|"
    r"\basset_[A-Za-z0-9_-]{2,154}\b|"
    r"\breview_[a-f0-9]{16}\b|"
    r"\brun_[A-Za-z0-9_:-]+\b|"
    r"\btask_\d{8}_\d{3}\b|"
    r"\brec[A-Za-z0-9_-]+\b|"
    r"\bVLOG-\d{8}-\d{6}-[A-Za-z0-9_-]+\b|"
    r"\b\d{8}_[^\s`，。；;,]+|"
    r"\b\d{8}-\d{6}-[A-Za-z0-9_-]+-[^\s`，。；;,]+"
)
RUN_ID_RE = re.compile(r"^run_[A-Za-z0-9_:-]+$")
PERSON_ID_RE = re.compile(r"^per_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
ARCHIVE_PREFIX_RE = re.compile(r"^(\d{8}-\d{6}-[A-Za-z0-9_-]+-.+?)(?:-[A-Za-z0-9]{4})?$")
APPLY_KEYWORDS = ("确认删除",)


@dataclass
class ArchiveCandidate:
    path: Path
    frontmatter: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    body: str = ""


@dataclass
class DiscoveryResult:
    target_id: str
    workspace_root: Path
    archive_candidates: list[ArchiveCandidate] = field(default_factory=list)
    inbox_paths: list[Path] = field(default_factory=list)
    matched_by: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def entry_tags(self) -> set[str]:
        result: set[str] = set()
        for candidate in self.archive_candidates:
            tag = str(candidate.frontmatter.get("entry_tag") or "").strip()
            if tag:
                result.add(tag)
        for path in self.inbox_paths:
            tag = tag_from_record_id(path.stem)
            if tag:
                result.add(tag)
        return result


def strip_apply_keywords(body: str) -> str:
    text = body or ""
    for keyword in APPLY_KEYWORDS:
        text = text.replace(keyword, " ")
    return text


def extract_target_ids(body: str) -> list[str]:
    text = strip_apply_keywords(body)
    seen: set[str] = set()
    result: list[str] = []
    for match in TARGET_ID_RE.findall(text):
        value = match.strip().strip("`").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def archive_prefix(value: str) -> str:
    match = ARCHIVE_PREFIX_RE.match(value.strip())
    return match.group(1) if match else value.strip()


def tag_from_record_id(value: str) -> str:
    prefix = archive_prefix(value)
    parts = prefix.split("-")
    if len(parts) < 4:
        return ""
    return "-".join(parts[3:])


def load_archive_candidate(path: Path) -> ArchiveCandidate:
    text = path.read_text(encoding="utf-8", errors="ignore")
    frontmatter, body = read_frontmatter_tolerant(text)
    title = ""
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return ArchiveCandidate(path=path, frontmatter=frontmatter, title=title, body=body)


def discover_target(workspace_root: Path, target_id: str) -> DiscoveryResult:
    root = Path(workspace_root)
    result = DiscoveryResult(target_id=target_id, workspace_root=root)
    exact_archive = root / "archive"
    exact_inbox = root / "inbox" / f"{target_id}.json"
    if exact_inbox.exists():
        result.inbox_paths.append(exact_inbox)
        result.matched_by.append("inbox_path")

    prefix = archive_prefix(target_id)
    if (root / "inbox").exists():
        for path in sorted((root / "inbox").glob(f"{prefix}-*.json")):
            if path not in result.inbox_paths:
                result.inbox_paths.append(path)
                result.matched_by.append("inbox_prefix")
    if exact_archive.exists():
        for path in sorted(exact_archive.glob("**/*.md")):
            if path.stem == target_id or path.stem.startswith(f"{prefix}-"):
                result.archive_candidates.append(load_archive_candidate(path))
                result.matched_by.append("archive_path")
    if exact_archive.exists():
        for path in sorted(exact_archive.glob("**/*.md")):
            if any(candidate.path == path for candidate in result.archive_candidates):
                continue
            try:
                candidate = load_archive_candidate(path)
            except OSError:
                continue
            fm_id = str(candidate.frontmatter.get("id") or "")
            if fm_id == target_id or fm_id.startswith(f"{prefix}-") or path.stem.startswith(f"{prefix}-"):
                result.archive_candidates.append(candidate)
                result.matched_by.append("archive_frontmatter")
    result.matched_by = sorted(set(result.matched_by))
    return result
