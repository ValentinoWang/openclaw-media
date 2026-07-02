"""Canonical schema contract for chunked transcription postprocess final notes.

Owner: openclaw-tag-router transcription workflow.
Exception policy: changing required fields or accepted labeled_transcript shapes
requires updating this module, source/active tests, and
scripts/quality/check_feishu_tag_router_contract.py in the same change.
"""

from __future__ import annotations

from typing import Any


TRANSCRIPTION_FINAL_NOTE_REQUIRED_FIELDS = (
    "title",
    "summary",
    "theme_sections",
    "decisions",
    "action_items",
    "pending_questions",
    "speaker_notes",
    "labeled_transcript",
    "sensitive_summary",
    "archive_macro_summary",
    "archive_summary_bullets",
)

TRANSCRIPTION_FINAL_NOTE_REQUIRED_NONEMPTY_FIELDS = (
    "title",
    "summary",
    "speaker_notes",
    "labeled_transcript",
    "archive_macro_summary",
    "archive_summary_bullets",
)

TRANSCRIPTION_LABELED_TRANSCRIPT_ALLOWED_SHAPES = (
    "speaker_text",
    "source_key_flow",
    "role_key_thread",
)


def transcription_final_note_value_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def validate_transcription_final_note_contract(note: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(note, dict):
        return ["final_note must be an object"]

    for field in TRANSCRIPTION_FINAL_NOTE_REQUIRED_FIELDS:
        if field not in note:
            errors.append(f"missing required field: {field}")
            continue
        if field in TRANSCRIPTION_FINAL_NOTE_REQUIRED_NONEMPTY_FIELDS and transcription_final_note_value_missing(note.get(field)):
            errors.append(f"empty required field: {field}")

    for field in (
        "theme_sections",
        "decisions",
        "action_items",
        "pending_questions",
        "speaker_notes",
        "labeled_transcript",
        "archive_summary_bullets",
    ):
        value = note.get(field)
        if field in note and not isinstance(value, (list, dict, str)):
            errors.append(f"field {field} must be list/object/string, got {type(value).__name__}")

    labeled_transcript = note.get("labeled_transcript")
    if not _labeled_transcript_has_allowed_shape(labeled_transcript):
        errors.append(
            "labeled_transcript must contain at least one speaker/text, source/key_flow/full_transcript, or role/key_thread object"
        )
    return errors


def _labeled_transcript_has_allowed_shape(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return any(_labeled_transcript_item_has_allowed_shape(item) for item in value)


def _labeled_transcript_item_has_allowed_shape(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    speaker = str(item.get("speaker") or item.get("role") or "").strip()
    text = str(item.get("text") or item.get("content") or "").strip()
    if speaker and text:
        return True
    role = str(item.get("role") or item.get("speaker") or "").strip()
    key_thread = str(item.get("key_thread") or "").strip()
    if role and key_thread:
        return True
    source = str(item.get("source") or item.get("source_audio") or "").strip()
    key_flow = item.get("key_flow")
    has_flow = isinstance(key_flow, list) and any(str(flow or "").strip() for flow in key_flow)
    full_transcript = str(item.get("full_transcript") or "").strip()
    return bool(source and (has_flow or full_transcript))
