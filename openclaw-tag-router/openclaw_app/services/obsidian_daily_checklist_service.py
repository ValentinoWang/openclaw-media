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
    def __init__(self, archive_root: str | Path, heading_label: str = "待办"):
        self.archive_root = Path(archive_root)
        self.heading_label = str(heading_label or "待办").strip() or "待办"

    def parse_target_date(self, text: str, now: datetime) -> date:
        body = str(text or "")
        patterns = (
            (r"\b(20\d{2})(\d{2})(\d{2})\b", False),
            (r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", False),
            (r"(?<![\dA-Za-z])(\d{1,2})月(\d{1,2})(?:日|号)?(?!\d)", True),
            (r"(?<![\dA-Za-z])(\d{1,2})[./](\d{1,2})(?:日|号)?(?![\dA-Za-z])", True),
        )
        for pattern, current_year in patterns:
            for match in re.finditer(pattern, body):
                values = [int(value) for value in match.groups()]
                year, month, day = (now.year, values[0], values[1]) if current_year else values
                try:
                    return date(year, month, day)
                except ValueError:
                    continue
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
        updated = self._append_to_daily_heading(existing, markdown_lines, target)
        path.write_text(updated, encoding="utf-8")
        return ChecklistAppendResult(
            path=str(path),
            target_date=target,
            items=self._flatten_tree(normalized_tree),
            markdown_lines=markdown_lines,
        )

    def _append_to_daily_heading(self, text: str, markdown_lines: list[str], target: date) -> str:
        heading = self._heading(target)
        if not text.strip():
            return f"{heading}\n" + "\n".join(markdown_lines).rstrip() + "\n"
        lines = text.strip().splitlines()
        for index, line in enumerate(lines):
            if line.strip() == heading:
                end = index + 1
                while end < len(lines) and not re.match(r"^#[ \t]+\S", lines[end]):
                    end += 1
                todo_body = lines[index + 1 : end]
                while todo_body and not todo_body[0].strip():
                    todo_body.pop(0)
                remaining = lines[:index] + lines[end:]
                todo_block = [heading, *markdown_lines, "", *todo_body]
                return self._join_heading_block(heading, todo_block, remaining)
        return self._join_heading_block(heading, [heading, *markdown_lines], lines)

    def _heading(self, target: date) -> str:
        return f"# {self.heading_label}"

    @staticmethod
    def _join_top_block(top_block: list[str], remaining: list[str]) -> str:
        top = "\n".join(top_block).rstrip()
        rest = "\n".join(remaining).strip()
        if rest:
            return f"{top}\n\n{rest}\n"
        return f"{top}\n"

    def _join_heading_block(self, heading: str, block: list[str], remaining: list[str]) -> str:
        if heading == "# 待办":
            return self._join_top_block(block, remaining)
        return self._join_after_primary_todo(block, remaining)

    @staticmethod
    def _join_after_primary_todo(block: list[str], remaining: list[str]) -> str:
        primary_heading = "# 待办"
        for index, line in enumerate(remaining):
            if line.strip() != primary_heading:
                continue
            end = index + 1
            while end < len(remaining) and not re.match(r"^#[ \t]+\S", remaining[end]):
                end += 1
            prefix = remaining[:end]
            suffix = remaining[end:]
            while prefix and not prefix[-1].strip():
                prefix.pop()
            while suffix and not suffix[0].strip():
                suffix.pop(0)
            secondary = [line for line in block if line.strip()]
            lines = [*prefix, "", *secondary]
            if suffix:
                lines.extend(["", *suffix])
            return "\n".join(lines).rstrip() + "\n"
        return ObsidianDailyChecklistService._join_top_block(block, remaining)

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
