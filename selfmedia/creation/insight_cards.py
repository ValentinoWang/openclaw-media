from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from media_vault.vault import MediaVault, MediaVaultError
from selfmedia.deconstruct.viral_content.src.human_insight_cards import (
    HumanInsightCardError,
    TRUSTED_CARD_EVIDENCE_PROVENANCE,
    card_library_paths,
    validate_human_insight_candidate,
    validate_card_markdown,
)
from selfmedia.deconstruct.viral_content.src.human_insight_writeback import (
    OPERATOR_VERIFIED_EVIDENCE_PROVENANCE,
    UNTRUSTED_EVIDENCE_STATUS,
    validate_approved_human_insight_aggregation,
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


def load_approved_human_insight_aggregation_records(
    *,
    vault: MediaVault,
    project_id: str,
    source_asset_id: str,
    limit: int = 80,
) -> list[CanonicalMediaRecord]:
    """Load only operator-verified aggregations for one tenant/project/source handoff."""
    project_id = str(project_id or "").strip()
    source_asset_id = str(source_asset_id or "").strip()
    if not project_id or not source_asset_id or limit <= 0:
        return []
    try:
        source_directory = vault.human_insight_candidate_dir(
            project_id,
            source_asset_id,
            "approval-lookup",
        ).parent
    except (MediaVaultError, ValueError):
        return []
    records: list[CanonicalMediaRecord] = []
    approval_directories = [
        path
        for path in sorted(source_directory.glob("*/approved_aggregations"))
        if _is_safe_directory_path(path, source_directory)
    ]
    for approval_directory in approval_directories:
        for path in sorted(approval_directory.glob("*.json")):
            if not _is_safe_card_path(path, approval_directory):
                continue
            try:
                artifact_uri = vault.to_uri(path)
                payload = vault.read_json_artifact(artifact_uri)
                identity = {
                    "tenant_id": vault.tenant_id,
                    "project_id": project_id,
                    "source_asset_id": source_asset_id,
                    "deconstruction_id": str((payload.get("identity") or {}).get("deconstruction_id") or "").strip(),
                }
                validate_approved_human_insight_aggregation(payload, identity=identity)
                _validate_approved_aggregation_source(vault, payload, identity)
                for aggregation in payload["aggregations"]:
                    records.append(_approved_aggregation_to_record(aggregation, payload, artifact_uri))
                    if len(records) >= limit:
                        return records
            except (MediaVaultError, OSError, ValueError, TypeError):
                continue
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


def _validate_approved_aggregation_source(
    vault: MediaVault,
    payload: dict[str, Any],
    identity: dict[str, str],
) -> None:
    library = vault.read_json_artifact(payload["candidate_library_uri"])
    if not isinstance(library, dict) or library.get("identity") != identity:
        raise ValueError("approved aggregation candidate library identity mismatch")
    candidates: dict[str, dict[str, Any]] = {}
    for candidate_record in library.get("candidates") or []:
        if not isinstance(candidate_record, dict):
            raise ValueError("approved aggregation candidate library record is invalid")
        candidate_id = str(candidate_record.get("candidate_id") or "").strip()
        candidate = candidate_record.get("candidate")
        if not candidate_id or not isinstance(candidate, dict):
            raise ValueError("approved aggregation candidate library candidate is invalid")
        validate_human_insight_candidate(candidate)
        if candidate_record.get("evidence_status") != UNTRUSTED_EVIDENCE_STATUS:
            raise ValueError("approved aggregation candidate library evidence state changed")
        candidates[candidate_id] = candidate_record
    for aggregation in payload["aggregations"]:
        candidate_record = candidates.get(aggregation["candidate_id"])
        if candidate_record is None:
            raise ValueError("approved aggregation candidate is no longer present")
        candidate = candidate_record["candidate"]
        if any(str(candidate.get(field) or "").strip() != aggregation["insight"][field] for field in aggregation["insight"]):
            raise ValueError("approved aggregation insight no longer matches reviewed candidate")
        candidate_refs = {str(item or "").strip() for item in candidate_record.get("source_refs") or []}
        if not set(aggregation["source_refs"]).issubset(candidate_refs):
            raise ValueError("approved aggregation source refs no longer match reviewed candidate")


def _approved_aggregation_to_record(
    aggregation: dict[str, Any],
    payload: dict[str, Any],
    artifact_uri: str,
) -> CanonicalMediaRecord:
    insight = aggregation["insight"]
    verification = aggregation["verification"]
    aggregation_id = aggregation["aggregation_id"]
    tag = insight["mechanism_tag"]
    content = "\n".join(
        f"{label}: {insight[field]}"
        for label, field in (
            ("核心欲望/恐惧", "desire_or_fear"),
            ("情绪路径", "emotion_path"),
            ("适用群体标签", "audience_group_hypothesis"),
            ("触发方式", "trigger_pattern"),
            ("平台风控风险", "risk_boundary"),
            ("审核摘要", "reasoning_summary"),
        )
    )
    source_record_id = f"insight_card:approved_aggregation:{aggregation_id}"
    return CanonicalMediaRecord(
        source_table="MediaVault:已审核人性洞察聚合",
        source_record_id=source_record_id,
        record_type="机制卡",
        title=f"已审核洞察聚合｜{tag}",
        content=content,
        status="已验证",
        relation_id=source_record_id,
        track=tag,
        topic=content,
        tags=[tag, "机制卡", "人性洞察", "已审核聚合"],
        source_link=artifact_uri,
        doc_links={"approved_aggregation": artifact_uri, "candidate_library": payload["candidate_library_uri"]},
        detail_json={
            "insight_aggregation_id": aggregation_id,
            "insight_card_status": "已验证",
            "evidence_boundary": "public_content_only",
            "evidence_provenance": OPERATOR_VERIFIED_EVIDENCE_PROVENANCE,
            "operator_verification_id": verification["approval_id"],
            "operator_id": verification["operator_id"],
            "approved_at": verification["approved_at"],
            "source_refs": aggregation["source_refs"],
            "reviewed_source_refs": aggregation["reviewed_source_refs"],
            "risk_boundary": insight["risk_boundary"],
            "tenant_id": payload["identity"]["tenant_id"],
            "project_id": payload["identity"]["project_id"],
            "source_asset_id": payload["identity"]["source_asset_id"],
            "deconstruction_id": payload["identity"]["deconstruction_id"],
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


def _is_safe_directory_path(path: Path, library_root: Path) -> bool:
    try:
        path.resolve().relative_to(library_root)
    except ValueError:
        return False
    return path.resolve().is_dir()
