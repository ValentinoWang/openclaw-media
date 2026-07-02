from __future__ import annotations

import re
from typing import Any, Callable


NATIVE_TABLE_KIND = "_openclaw_feishu_table"
INLINE_CODE_ESCAPED_NEWLINE_RE = re.compile(r"`([^`\n]*\\n[^`\n]*)`")


def expand_inline_code_literal_newlines(text: str) -> str:
    """Render tag input examples written as `【标签】\n字段：...` on real lines."""

    def replace(match: re.Match[str]) -> str:
        code = match.group(1)
        if "【" not in code:
            return match.group(0)
        return "`" + code.replace("\\n", "\n") + "`"

    return INLINE_CODE_ESCAPED_NEWLINE_RE.sub(replace, str(text or ""))


class FeishuDocxBlockRenderer:
    """Convert lightweight authoring text into native Feishu Docx blocks."""

    def __init__(
        self,
        heading_factory: Callable[[int, str], dict[str, Any]],
        text_factory: Callable[[str], dict[str, Any]],
        *,
        native_table_kind: str = NATIVE_TABLE_KIND,
    ) -> None:
        self.heading_factory = heading_factory
        self.text_factory = text_factory
        self.native_table_kind = native_table_kind

    def render(self, content: str, *, leading_blocks: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = list(leading_blocks or [])
        lines = str(content or "").splitlines()
        if not lines:
            return blocks or [self.text_factory(" ")]

        index = 0
        while index < len(lines):
            raw_line = lines[index]
            line = raw_line.strip()
            if not line:
                index += 1
                continue
            if line.startswith("```"):
                code_lines: list[str] = []
                index += 1
                while index < len(lines) and not lines[index].strip().startswith("```"):
                    code_lines.append(lines[index].rstrip())
                    index += 1
                if index < len(lines):
                    index += 1
                for code_line in code_lines:
                    if code_line.strip():
                        blocks.append(self.text_factory(code_line.strip()))
                continue
            if self._looks_like_table_line(line):
                table_lines: list[str] = []
                while index < len(lines) and self._looks_like_table_line(lines[index].strip()):
                    table_lines.append(self._strip_table_bullet(lines[index].strip()))
                    index += 1
                rows = self._pipe_table_rows(table_lines)
                if rows:
                    blocks.append({"_openclaw_kind": self.native_table_kind, "rows": rows})
                continue
            heading = re.match(r"^(#{1,9})\s+(.+)$", line)
            if heading:
                level = len(heading.group(1))
                blocks.append(self.heading_factory(level, self._clean_inline_markdown(heading.group(2))))
                index += 1
                continue
            blocks.append(self.text_factory(self._normalize_plain_line(line)))
            index += 1

        return blocks or [self.text_factory(" ")]

    @staticmethod
    def _looks_like_table_line(line: str) -> bool:
        line = FeishuDocxBlockRenderer._strip_table_bullet(line)
        return line.startswith("|") and line.endswith("|") and line.count("|") >= 3

    @staticmethod
    def _strip_table_bullet(line: str) -> str:
        return re.sub(r"^(?:[-*+]|•)\s+(?=\|)", "", str(line or "").strip())

    def _pipe_table_rows(self, lines: list[str]) -> list[list[str]]:
        rows: list[list[str]] = []
        for line in lines:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not cells:
                continue
            if all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells):
                continue
            rows.append([self._clean_inline_markdown(cell) for cell in cells])
        if not rows:
            return []
        column_count = max(len(row) for row in rows)
        return [row + [""] * (column_count - len(row)) for row in rows]

    def _normalize_plain_line(self, line: str) -> str:
        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        if bullet:
            return f"• {self._clean_inline_markdown(bullet.group(1))}"
        numbered = re.match(r"^(\d+)[.)]\s+(.+)$", line)
        if numbered:
            return f"{numbered.group(1)}. {self._clean_inline_markdown(numbered.group(2))}"
        return self._clean_inline_markdown(line)

    @staticmethod
    def _clean_inline_markdown(text: str) -> str:
        cleaned = expand_inline_code_literal_newlines(str(text or ""))
        cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1：\2", cleaned)
        cleaned = re.sub(r"(?<!\*)\*\*([^*]+)\*\*(?!\*)", r"\1", cleaned)
        cleaned = re.sub(r"(?<!_)__([^_]+)__(?!_)", r"\1", cleaned)
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        return cleaned.strip()
