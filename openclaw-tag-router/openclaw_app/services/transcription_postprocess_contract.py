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
    "meeting_info",
    "conclusion_summary",
    "decision_list",
    "topic_cards",
    "pending_decisions",
    "validation_hypotheses",
    "action_items",
    "risks_and_constraints",
    "next_meeting",
    "topical_attachments",
    "speaker_notes",
    "labeled_transcript",
    "sensitive_summary",
    "archive_macro_summary",
    "archive_summary_bullets",
)

TRANSCRIPTION_FINAL_NOTE_REQUIRED_NONEMPTY_FIELDS = (
    "title",
    "meeting_info",
    "conclusion_summary",
    "topic_cards",
    "next_meeting",
    "speaker_notes",
    "labeled_transcript",
    "archive_macro_summary",
    "archive_summary_bullets",
)

TRANSCRIPTION_MEETING_INFO_FIELDS = (
    "meeting_name",
    "meeting_goal",
    "meeting_time",
    "participants",
    "facilitator",
    "minutes_owner",
    "related_project",
    "related_documents",
    "version",
)

TRANSCRIPTION_CONCLUSION_SUMMARY_FIELDS = (
    "overall_judgment",
    "key_implications",
)

TRANSCRIPTION_CONCLUSION_STATUSES = (
    "decided",
    "tentative_direction",
    "pending_validation",
    "pending_decision",
)

TRANSCRIPTION_DECISION_STATUSES = TRANSCRIPTION_CONCLUSION_STATUSES

TRANSCRIPTION_LABELED_TRANSCRIPT_ALLOWED_SHAPES = ("role_labeled_turn",)


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

    _validate_meeting_info(note.get("meeting_info"), errors)
    _validate_conclusion_summary(note.get("conclusion_summary"), errors)
    _validate_record_list(
        note.get("decision_list"),
        "decision_list",
        ("id", "topic", "decision", "status", "rationale", "scope", "review_condition"),
        errors,
        allowed_statuses=TRANSCRIPTION_DECISION_STATUSES,
    )
    _validate_topic_cards(note.get("topic_cards"), errors)
    _validate_record_list(
        note.get("pending_decisions"),
        "pending_decisions",
        ("id", "question", "options", "decision_owner", "deadline"),
        errors,
        list_fields=("options",),
    )
    _validate_record_list(
        note.get("validation_hypotheses"),
        "validation_hypotheses",
        ("id", "hypothesis", "validation_method", "metrics", "pass_criteria", "owner"),
        errors,
    )
    _validate_record_list(
        note.get("action_items"),
        "action_items",
        ("id", "action", "assignee", "deliverable", "acceptance_criteria", "deadline", "dependencies"),
        errors,
    )
    _validate_record_list(
        note.get("risks_and_constraints"),
        "risks_and_constraints",
        ("risk", "impact", "mitigation"),
        errors,
    )
    _validate_next_meeting(note.get("next_meeting"), errors)
    _validate_record_list(
        note.get("topical_attachments"),
        "topical_attachments",
        ("id", "title", "status_note", "summary", "details"),
        errors,
        list_fields=("details",),
    )

    _validate_record_list(
        note.get("speaker_notes"),
        "speaker_notes",
        ("speaker_key", "display_name", "meeting_role", "identity_evidence", "confidence"),
        errors,
    )

    for field in ("labeled_transcript", "archive_summary_bullets"):
        value = note.get(field)
        if field in note and not isinstance(value, (list, dict, str)):
            errors.append(f"field {field} must be list/object/string, got {type(value).__name__}")

    _validate_record_list(
        note.get("labeled_transcript"),
        "labeled_transcript",
        ("speaker_key", "speaker", "role", "text", "source", "confidence"),
        errors,
    )
    return errors


def _validate_meeting_info(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("field meeting_info must be an object")
        return
    for field in TRANSCRIPTION_MEETING_INFO_FIELDS:
        if field not in value:
            errors.append(f"meeting_info missing required field: {field}")
            continue
        field_value = value.get(field)
        if transcription_final_note_value_missing(field_value):
            errors.append(f"meeting_info.{field} must be non-empty; use 未从来源识别 when evidence is absent")
    for field in ("participants", "related_documents"):
        if field in value and not isinstance(value.get(field), (list, str)):
            errors.append(f"meeting_info.{field} must be a list or string")


def _validate_conclusion_summary(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("field conclusion_summary must be an object")
        return
    overall_judgment = value.get("overall_judgment")
    if not isinstance(overall_judgment, str) or not overall_judgment.strip():
        errors.append("conclusion_summary.overall_judgment must be a non-empty string")
    implications = value.get("key_implications")
    if not isinstance(implications, list):
        errors.append("conclusion_summary.key_implications must be a list")
        return
    for index, item in enumerate(implications):
        if not isinstance(item, dict):
            errors.append(f"conclusion_summary.key_implications[{index}] must be an object")
            continue
        _validate_required_item_fields(
            item,
            f"conclusion_summary.key_implications[{index}]",
            ("item", "rationale", "implications", "related_ids"),
            errors,
        )
        if "related_ids" in item and not isinstance(item.get("related_ids"), list):
            errors.append(f"conclusion_summary.key_implications[{index}].related_ids must be a list")


def _validate_topic_cards(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("field topic_cards must be a list")
        return
    if not value:
        errors.append("topic_cards must contain at least one important topic")
        return
    required = (
        "id",
        "topic",
        "current_facts",
        "core_question",
        "conclusion_status",
        "conclusion",
        "next_step",
    )
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"topic_cards[{index}] must be an object")
            continue
        _validate_required_item_fields(item, f"topic_cards[{index}]", required, errors)
        for field in ("current_facts", "options", "unresolved_questions"):
            if field not in item:
                errors.append(f"topic_cards[{index}] missing required field: {field}")
            elif not isinstance(item.get(field), list):
                errors.append(f"topic_cards[{index}].{field} must be a list")
        status = str(item.get("conclusion_status") or "").strip()
        if status and status not in TRANSCRIPTION_CONCLUSION_STATUSES:
            errors.append(
                f"topic_cards[{index}].conclusion_status must be one of {TRANSCRIPTION_CONCLUSION_STATUSES}, got {status}"
            )


def _validate_next_meeting(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("field next_meeting must be an object")
        return
    for field in ("trigger_conditions", "required_materials", "decisions_needed"):
        if field not in value:
            errors.append(f"next_meeting missing required field: {field}")
        elif not isinstance(value.get(field), list):
            errors.append(f"next_meeting.{field} must be a list")


def _validate_record_list(
    value: Any,
    field: str,
    required_fields: tuple[str, ...],
    errors: list[str],
    *,
    list_fields: tuple[str, ...] = (),
    allowed_statuses: tuple[str, ...] = (),
) -> None:
    if not isinstance(value, list):
        errors.append(f"field {field} must be a list")
        return
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{field}[{index}] must be an object")
            continue
        prefix = f"{field}[{index}]"
        _validate_required_item_fields(item, prefix, required_fields, errors)
        for list_field in list_fields:
            if list_field in item and not isinstance(item.get(list_field), list):
                errors.append(f"{prefix}.{list_field} must be a list")
        if allowed_statuses:
            status = str(item.get("status") or "").strip()
            if status and status not in allowed_statuses:
                errors.append(f"{prefix}.status must be one of {allowed_statuses}, got {status}")


def _validate_required_item_fields(
    item: dict[str, Any],
    prefix: str,
    required_fields: tuple[str, ...],
    errors: list[str],
) -> None:
    for field in required_fields:
        if field not in item:
            errors.append(f"{prefix} missing required field: {field}")
            continue
        if transcription_final_note_value_missing(item.get(field)):
            errors.append(f"{prefix}.{field} must be non-empty; use 未指定 when evidence is absent")
