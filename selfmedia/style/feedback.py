from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .contract import StyleFeedbackRecord, StylePolishResult


def build_feedback_record(result: StylePolishResult, *, selected_version: str = "", note: str = "") -> dict[str, Any]:
    selected = str(selected_version or "").strip()
    return {
        "run_id": result.run_id,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "selection_status": "selected" if selected else "unselected",
        "selected_version": selected,
        "note": str(note or "").strip(),
        "creative_pattern_promotion": "manual_only",
        "pattern_candidate_uri": "",
    }


def build_pattern_candidate(result: StylePolishResult, *, evidence_note: str) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "candidate_type": "StylePolishPatternCandidate",
        "target_entity": "CreativePattern",
        "requires_manual_confirmation": True,
        "creative_pattern_promotion": "manual_only",
        "evidence_note": str(evidence_note or "").strip(),
        "recommended_version": result.recommended_version,
        "source_artifact_uri": result.artifact_uri,
    }


def empty_feedback_record() -> StyleFeedbackRecord:
    return StyleFeedbackRecord(
        selection_status="unselected",
        selected_version="",
        pattern_candidate_uri="",
        creative_pattern_promotion="manual_only",
    )
