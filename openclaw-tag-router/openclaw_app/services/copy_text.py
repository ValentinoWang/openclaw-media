"""Canonical formatting for copy-ready capability guidance.

The matcher remains responsible for semantic content.  This module only
normalizes the transport text that carries that content: the public tag, field
line boundaries, and the opaque continuation-plan field.
"""

from __future__ import annotations

import re
from typing import Any

from .capability_input_contracts import CAPABILITY_INPUT_CONTRACTS

CONTROLLED_INPUT_MARKER = "[你要粘贴的内容]"
PATH_ID_FIELD = "路径续接ID"
FORBIDDEN_COPY_MARKER_RE = re.compile(r"<[^>]+>|\{\{[^}]+\}\}|待填写|上一步返回|自行替换")
_PATH_ID_FIELD_RE = re.compile(rf"{re.escape(PATH_ID_FIELD)}\s*[：:]\s*(?P<value>[A-Za-z0-9_-]+)")
_BASE_FIELD_NAMES = (
    "路径续接ID",
    "内容来源",
    "处理要求",
    "素材类型",
    "用途",
    "平台",
    "类型",
    "赛道",
    "主体",
    "账号",
    "素材/参考",
    "希望产出",
    "输出要求",
    "补充说明",
    "文档链接",
    "修改要求",
    "约束",
    "主题",
    "材料",
    "原文",
    "原文/笔记",
    "当前困惑",
    "希望整理成",
    "链接",
    "标题",
    "正文",
    "标签",
    "评论引导",
    "来源",
    "信息",
    "能力",
    "目标",
    "内容类型",
    "内容规格",
    "品牌",
    "产品",
    "博主名称",
    "创作方向",
    "产品卖点",
    "Tags",
    "发布时间",
    "初稿时间",
    "平台要求/禁区",
    "PR备注",
)
_CONTRACT_FIELD_NAMES = tuple(
    dict.fromkeys(
        field
        for contract in CAPABILITY_INPUT_CONTRACTS.values()
        for field in contract.get("copyFields", [])
        if field
    )
)
_KNOWN_FIELD_NAMES = tuple(dict.fromkeys((*_BASE_FIELD_NAMES, *_CONTRACT_FIELD_NAMES)))
_KNOWN_FIELD_MARKER_RE = re.compile(
    rf"(?P<name>{'|'.join(re.escape(name) for name in sorted(_KNOWN_FIELD_NAMES, key=len, reverse=True))})\s*[：:]"
)
_GENERIC_FIELD_MARKER_RE = re.compile(
    r"(?<!\S)(?P<name>(?:[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9_/>.-]{0,39}|[A-Za-z][A-Za-z0-9_/>.-]*_[A-Za-z0-9_/>.-]+))\s*[：:]"
)


class CopyTextFormatError(ValueError):
    """Raised when a copy-ready command cannot satisfy its structural contract."""


def format_copy_text(value: Any, *, label: str, guidance_plan_id: str) -> str:
    """Return one canonical, line-oriented copy command.

    Only syntactic layout is changed.  In particular, field values are never
    inferred, summarized, or filled from the request.
    """

    if not isinstance(value, str):
        raise CopyTextFormatError("copyText 必须是文本。")
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    prefix = f"【{label}】"
    if not text.startswith(prefix):
        raise CopyTextFormatError("复制文本必须以对应能力标签开头。")

    # Keep the tag on its own line even when the model appended the first field
    # directly after it.
    remainder = text[len(prefix):].lstrip(" \t：:")
    text = prefix if not remainder else f"{prefix}\n{remainder}"

    path_ids = [match.group("value") for match in _PATH_ID_FIELD_RE.finditer(text)]
    if not path_ids:
        raise CopyTextFormatError("复制文本缺少独立的路径续接 ID 字段。")
    if any(path_id != guidance_plan_id for path_id in path_ids):
        raise CopyTextFormatError("复制文本包含不匹配的路径续接 ID。")

    lines: list[str] = []
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if _PATH_ID_FIELD_RE.fullmatch(stripped):
            continue
        without_path = _PATH_ID_FIELD_RE.sub("", raw_line)
        if without_path.strip():
            lines.extend(_split_inline_fields(without_path))
    lines.append(f"{PATH_ID_FIELD}：{guidance_plan_id}")
    return "\n".join(lines).strip()


def validate_copy_text_layout(value: Any, *, label: str, guidance_plan_id: str) -> str:
    """Validate already-rendered text without changing user-visible content."""

    if not isinstance(value, str):
        raise CopyTextFormatError("copyText 必须是文本。")
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = text.split("\n")
    if not lines or lines[0].strip() != f"【{label}】":
        raise CopyTextFormatError("复制文本的能力标签必须独占第一行。")
    path_lines = [line.strip() for line in lines if line.strip().startswith(f"{PATH_ID_FIELD}：") or line.strip().startswith(f"{PATH_ID_FIELD}:")]
    if path_lines != [f"{PATH_ID_FIELD}：{guidance_plan_id}"]:
        raise CopyTextFormatError("路径续接 ID 必须匹配且独占一行，只能出现一次。")
    for field_name in ("内容来源", "处理要求"):
        marker = re.compile(rf"{re.escape(field_name)}\s*[：:]")
        for line in lines:
            matches = list(marker.finditer(line))
            if matches and (len(matches) != 1 or line[: matches[0].start()].strip(" \t-*：:") or matches[0].start() != len(line) - len(line.lstrip())):
                raise CopyTextFormatError(f"{field_name} 必须独占一行。")
    marker_line = re.compile(r"^[^\n：:]{1,80}\s*[：:]\s*" + re.escape(CONTROLLED_INPUT_MARKER) + r"\s*$")
    if any(CONTROLLED_INPUT_MARKER in line and not marker_line.fullmatch(line.strip()) for line in lines):
        raise CopyTextFormatError("后续粘贴提示必须作为字段值出现，不能单独占一行。")
    if FORBIDDEN_COPY_MARKER_RE.search(text):
        raise CopyTextFormatError("复制文本包含未绑定占位符。")
    return text


def _split_inline_fields(line: str) -> list[str]:
    """Split only unambiguous ``字段：值 字段：值`` runs.

    A single colon in prose is left untouched.  Multiple field markers on one
    line are the malformed layout this formatter is intended to repair.
    """

    if line.lstrip().startswith("```"):
        return [line]
    known_matches = list(_KNOWN_FIELD_MARKER_RE.finditer(line))
    generic_matches = [
        match
        for match in _GENERIC_FIELD_MARKER_RE.finditer(line)
        if not any(
            known.start() <= match.start() < known.end() or match.start() <= known.start() < match.end()
            for known in known_matches
        )
    ]
    matches_by_start = {match.start(): match for match in [*known_matches, *generic_matches]}
    matches = [match for _, match in sorted(matches_by_start.items()) if match.group("name").lower() not in {"http", "https"}]
    if len(matches) < 2:
        return [line]
    first = matches[0]
    prefix = line[: first.start()].strip()
    result: list[str] = []
    if prefix:
        result.append(prefix)
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        segment = line[match.start() : end].strip()
        if segment:
            result.append(segment)
    return result or [line]
