from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class ChecklistAppendResult:
    path: str
    target_date: date
    items: list[str]
    markdown_lines: list[str]


class ObsidianDailyChecklistService:
    def __init__(self, archive_root: str | Path):
        self.archive_root = Path(archive_root)

    def parse_target_date(self, text: str, now: datetime) -> date:
        body = str(text or "")
        match = re.search(r"\b(20\d{2})(\d{2})(\d{2})\b", body)
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", body)
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        match = re.search(r"(?<![\dA-Za-z])(\d{1,2})月(\d{1,2})(?:日|号)?(?!\d)", body)
        if match:
            return date(now.year, int(match.group(1)), int(match.group(2)))
        match = re.search(r"(?<![\dA-Za-z])(\d{1,2})[./](\d{1,2})(?:日|号)?(?![\dA-Za-z])", body)
        if match:
            return date(now.year, int(match.group(1)), int(match.group(2)))
        return now.date()

    def weekly_archive_path(self, target: date) -> Path:
        start = target - timedelta(days=target.weekday())
        end = start + timedelta(days=6)
        return self.archive_root / f"{start:%Y%m%d}-{end:%Y%m%d}.md"

    def append_checklist(
        self,
        *,
        text: str,
        now: datetime,
        checklist_tree: list[dict[str, object]],
        feishu_record: str = "",
    ) -> ChecklistAppendResult:
        target = self.parse_target_date(text, now)
        normalized_tree = self._normalize_tree(checklist_tree)
        if not normalized_tree:
            raise ValueError("missing checklist_tree")
        path = self.weekly_archive_path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        markdown_lines = self._render_tree(normalized_tree, feishu_record=feishu_record)
        updated = self._append_to_todo_heading(existing, markdown_lines)
        path.write_text(updated, encoding="utf-8")
        return ChecklistAppendResult(
            path=str(path),
            target_date=target,
            items=self._flatten_tree(normalized_tree),
            markdown_lines=markdown_lines,
        )

    def _append_to_todo_heading(self, text: str, markdown_lines: list[str]) -> str:
        heading = "# 待办"
        block = "\n".join(markdown_lines)
        if not text.strip():
            return f"{heading}\n{block}\n"
        lines = text.rstrip().splitlines()
        for index, line in enumerate(lines):
            if line.strip() == heading:
                insert_at = index + 1
                while insert_at < len(lines) and not lines[insert_at].strip():
                    del lines[insert_at]
                lines[insert_at:insert_at] = [block, ""]
                return "\n".join(lines).rstrip() + "\n"
        insert_lines = [heading, block, ""]
        lines[0:0] = insert_lines
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _normalize_tree(nodes: list[dict[str, object]]) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            text = re.sub(r"\s+", " ", str(node.get("text") or "")).strip()
            if not text:
                continue
            children = node.get("children")
            child_nodes = children if isinstance(children, list) else []
            normalized.append({"text": text, "children": ObsidianDailyChecklistService._normalize_tree(child_nodes)})
        return normalized

    @staticmethod
    def _flatten_tree(nodes: list[dict[str, object]]) -> list[str]:
        flattened: list[str] = []
        for node in nodes:
            text = str(node.get("text") or "").strip()
            if text:
                flattened.append(text)
            children = node.get("children")
            if isinstance(children, list):
                flattened.extend(ObsidianDailyChecklistService._flatten_tree(children))
        return flattened

    @staticmethod
    def _render_tree(nodes: list[dict[str, object]], *, feishu_record: str = "", depth: int = 0) -> list[str]:
        lines: list[str] = []
        single_root = len(nodes) == 1 and depth == 0
        for node in nodes:
            text = str(node.get("text") or "").strip()
            if not text:
                continue
            children = node.get("children")
            child_nodes = children if isinstance(children, list) else []
            suffix = ""
            if feishu_record and single_root and not child_nodes:
                suffix = f" <!-- openclaw:feishu_record={feishu_record};sync=todo_complete_v1 -->"
            indent = "  " * depth
            lines.append(f"{indent}- [ ] {text}{suffix}")
            lines.extend(ObsidianDailyChecklistService._render_tree(child_nodes, depth=depth + 1))
        return lines
