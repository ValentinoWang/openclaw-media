from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from selfmedia.deconstruct.viral_content.src.human_insight_cards import (
    HumanInsightCardError,
    TRUSTED_CARD_EVIDENCE_PROVENANCE,
    card_library_paths,
    validate_card_markdown,
)

from .field_contract import CanonicalMediaRecord


PRIVATE_SOURCE_MARKERS = (
    "social 私密",
    "私密人物档案",
    "私密风控笔记",
    "openclaw-agents/social/person-profile-skill/theory/风控.md",
)


def load_insight_card_records(*, root: Path | None = None, limit: int = 80) -> list[CanonicalMediaRecord]:
    paths = card_library_paths(root)
    library_root = paths["root"].resolve()
    records: list[CanonicalMediaRecord] = []
    for card_type, directory in (("机制卡", paths["mechanisms"]), ("群体卡", paths["audience_groups"])):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name.startswith("_"):
                continue
            if not _is_safe_card_path(path, library_root):
                continue
            record = _card_to_record(path, card_type=card_type)
            if record:
                records.append(record)
            if len(records) >= limit:
                return records
    return records


def _card_to_record(path: Path, *, card_type: str) -> CanonicalMediaRecord | None:
    text = path.read_text(encoding="utf-8")
    if any(marker in text for marker in PRIVATE_SOURCE_MARKERS):
        return None
    try:
        validate_card_markdown(text, card_type="mechanism" if card_type == "机制卡" else "group")
    except HumanInsightCardError:
        return None
    frontmatter = _frontmatter(text)
    if (
        frontmatter.get("evidence_provenance") != TRUSTED_CARD_EVIDENCE_PROVENANCE
        or not frontmatter.get("operator_verification_id")
    ):
        return None
    status = frontmatter.get("status") or _heading_value(text, "当前状态") or "假设"
    tag = (
        frontmatter.get("mechanism_tag")
        or frontmatter.get("audience_group_tag")
        or frontmatter.get("canonical_mechanism_tag")
        or path.stem
    )
    title = f"{card_type}｜{tag}"
    content = _compact_sections(text)
    return CanonicalMediaRecord(
        source_table="Obsidian:人性洞察库",
        source_record_id=f"insight_card:{path.stem}",
        record_type=card_type,
        title=title,
        content=content,
        status=status,
        relation_id=f"insight_card:{path.stem}",
        platform="",
        content_type="",
        track=str(tag),
        topic=content,
        tags=[str(tag), card_type, "人性洞察"],
        source_link=str(path),
        doc_links={"obsidian": str(path)},
        detail_json={
            "insight_card_path": str(path),
            "insight_card_type": card_type,
            "insight_card_status": status,
            "evidence_boundary": "public_content_only",
            "evidence_provenance": frontmatter["evidence_provenance"],
            "operator_verification_id": frontmatter["operator_verification_id"],
            "risk_boundary": _heading_value(text, "平台风控风险"),
        },
    )


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(?P<body>.*?)\n---", text, flags=re.S)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def _heading_value(text: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*\n(?P<body>.*?)(?=^##\s+|\Z)", text, flags=re.M | re.S)
    if not match:
        return ""
    return _one_line(match.group("body"))


def _compact_sections(text: str) -> str:
    sections = []
    for heading in (
        "定义",
        "触发方式",
        "情绪路径",
        "适用群体标签",
        "核心欲望/恐惧",
        "身份认同叙事",
        "高频触发机制",
        "语言风格",
        "已验证开头钩子句式",
        "平台风控风险",
    ):
        value = _heading_value(text, heading)
        if value:
            sections.append(f"{heading}: {value}")
    return "\n".join(sections)[:3000]


def _one_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _is_safe_card_path(path: Path, library_root: Path) -> bool:
    try:
        path.resolve().relative_to(library_root)
    except ValueError:
        return False
    return path.resolve().is_file()
