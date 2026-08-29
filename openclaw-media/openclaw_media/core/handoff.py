from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .refs import _IDENTITY, is_relative_ref as _ref, issue_ref as _issue_ref
from .storyboard import EDLEntry, StoryboardEntry


@dataclass(frozen=True)
class HandoffClipDescriptor:
    clip_id: str
    identity_ref: str
    material_ref: str
    kind: str
    duration_seconds: float


@dataclass(frozen=True)
class SubtitleCue:
    cue_id: str
    sequence: int
    timeline_in_seconds: float
    timeline_out_seconds: float
    text: str
    format: str = "srt"


@dataclass(frozen=True)
class HandoffClip:
    edit_id: str
    shot_id: str
    sequence: int
    clip_id: str
    identity_ref: str
    material_ref: str
    timeline_in_seconds: float
    timeline_out_seconds: float
    source_in_seconds: float
    source_out_seconds: float


@dataclass(frozen=True)
class HandoffIssue:
    scope: str
    ref: str | None
    error_code: str


@dataclass(frozen=True)
class HandoffManifest:
    contract: str
    clip_table: tuple[HandoffClip, ...]
    subtitles: tuple[SubtitleCue, ...]
    storyboard: tuple[StoryboardEntry, ...]


@dataclass(frozen=True)
class HandoffReadme:
    contract: str
    editor_action: str
    clip_count: int
    subtitle_count: int
    timeline_duration_seconds: float


@dataclass(frozen=True)
class ValidationReceipt:
    status: str
    error_codes: tuple[str, ...]
    checked_clip_count: int
    checked_edit_count: int
    checked_subtitle_count: int


@dataclass(frozen=True)
class HandoffPlan:
    status: str
    manifest: HandoffManifest
    readme: HandoffReadme
    validation: ValidationReceipt
    issues: tuple[HandoffIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _time(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def plan_handoff(clips: Iterable[HandoffClipDescriptor], storyboard: Iterable[StoryboardEntry], edl: Iterable[EDLEntry], subtitles: Iterable[SubtitleCue] = ()) -> HandoffPlan:
    """Build a deterministic, path-safe human-edit handoff package manifest."""
    try:
        clip_items, board_items, edit_items, cue_items = map(list, (clips, storyboard, edl, subtitles))
    except Exception:
        clip_items, board_items, edit_items, cue_items = [], [], [], []
        issues = [HandoffIssue("handoff", None, "invalid_input")]
    else:
        issues = []
    valid: list[HandoffClipDescriptor] = []
    for item in clip_items:
        if not isinstance(item, HandoffClipDescriptor) or not _ref(item.clip_id) or not _IDENTITY.fullmatch(item.identity_ref) or not _ref(item.material_ref) or item.kind not in {"audio", "image", "video"} or not _time(item.duration_seconds) or item.duration_seconds <= 0:
            issues.append(HandoffIssue("clip", _issue_ref(getattr(item, "clip_id", None)), "invalid_input"))
        else:
            valid.append(item)
    duplicate_ids = {x.identity_ref for x in valid if sum(y.identity_ref == x.identity_ref for y in valid) > 1}
    for identity in sorted(duplicate_ids):
        issues.append(HandoffIssue("clip", identity, "duplicate_clip_identity"))
    by_identity = {x.identity_ref: x for x in valid if x.identity_ref not in duplicate_ids}
    rows: list[HandoffClip] = []
    previous_out = 0.0
    for item in sorted(edit_items, key=lambda x: (getattr(x, "sequence", -1), getattr(x, "edit_id", ""))):
        if not isinstance(item, EDLEntry):
            issues.append(HandoffIssue("edl", None, "invalid_input"))
            continue
        edit_ref = _issue_ref(item.edit_id)
        if not _ref(item.edit_id) or not _ref(item.shot_id) or not _IDENTITY.fullmatch(item.identity_ref):
            issues.append(HandoffIssue("edl", edit_ref, "invalid_input"))
            continue
        times_valid = all(_time(x) for x in (item.timeline_in_seconds, item.timeline_out_seconds, item.source_in_seconds, item.source_out_seconds))
        timeline_valid = times_valid and item.timeline_in_seconds >= 0 and item.timeline_out_seconds > item.timeline_in_seconds
        overlaps = timeline_valid and item.timeline_in_seconds < previous_out
        if timeline_valid:
            previous_out = max(previous_out, item.timeline_out_seconds)
        if not times_valid or not timeline_valid or overlaps or item.source_in_seconds < 0 or item.source_out_seconds <= item.source_in_seconds:
            issues.append(HandoffIssue("edl", edit_ref, "timing_conflict"))
            continue
        clip = by_identity.get(item.identity_ref)
        if clip is None or not _ref(item.material_ref) or clip.material_ref != item.material_ref or item.source_out_seconds > clip.duration_seconds:
            issues.append(HandoffIssue("edl", edit_ref, "missing_material"))
            continue
        rows.append(HandoffClip(item.edit_id, item.shot_id, item.sequence, clip.clip_id, clip.identity_ref, clip.material_ref, item.timeline_in_seconds, item.timeline_out_seconds, item.source_in_seconds, item.source_out_seconds))
    valid_board: list[StoryboardEntry] = []
    for item in sorted(board_items, key=lambda x: (getattr(x, "sequence", -1), getattr(x, "shot_id", ""))):
        if not isinstance(item, StoryboardEntry):
            issues.append(HandoffIssue("storyboard", None, "invalid_input"))
            continue
        paired_refs = (item.material_ref is None) == (item.identity_ref is None)
        refs_valid = paired_refs and (item.material_ref is None or (_ref(item.material_ref) and isinstance(item.identity_ref, str) and _IDENTITY.fullmatch(item.identity_ref)))
        timing_valid = all(_time(x) for x in (item.timeline_in_seconds, item.timeline_out_seconds, item.duration_seconds)) and item.timeline_in_seconds >= 0 and item.timeline_out_seconds > item.timeline_in_seconds and item.duration_seconds > 0 and math.isclose(item.timeline_out_seconds - item.timeline_in_seconds, item.duration_seconds)
        metadata_valid = _ref(item.shot_id) and isinstance(item.sequence, int) and not isinstance(item.sequence, bool) and item.sequence >= 0 and _ref(item.match_status) and (item.error_code is None or _ref(item.error_code))
        if not refs_valid or not timing_valid or not metadata_valid:
            issues.append(HandoffIssue("storyboard", _issue_ref(item.shot_id), "invalid_input"))
            continue
        valid_board.append(item)
    valid_cues: list[SubtitleCue] = []
    for cue in sorted(cue_items, key=lambda x: (getattr(x, "sequence", -1), getattr(x, "cue_id", ""))):
        if not isinstance(cue, SubtitleCue) or cue.format not in {"srt", "vtt"}:
            issues.append(HandoffIssue("subtitle", _issue_ref(getattr(cue, "cue_id", None)), "unsupported_subtitle"))
        elif not _ref(cue.cue_id) or not isinstance(cue.sequence, int) or isinstance(cue.sequence, bool) or cue.sequence < 0 or not isinstance(cue.text, str) or not cue.text.strip() or not _time(cue.timeline_in_seconds) or not _time(cue.timeline_out_seconds) or cue.timeline_in_seconds < 0 or cue.timeline_out_seconds <= cue.timeline_in_seconds:
            issues.append(HandoffIssue("subtitle", _issue_ref(cue.cue_id), "invalid_input"))
        else:
            valid_cues.append(cue)
    codes = tuple(sorted({x.error_code for x in issues}))
    status = "ok" if not issues else ("partial" if rows else "failed")
    manifest = HandoffManifest("media.edit.handoff.v1", tuple(rows), tuple(valid_cues), tuple(valid_board))
    duration = max((x.timeline_out_seconds for x in rows), default=0.0)
    readme = HandoffReadme(manifest.contract, "open the relative media refs and apply the ordered clip table", len(rows), len(valid_cues), duration)
    receipt = ValidationReceipt(status, codes, len(valid), len(edit_items), len(cue_items))
    return HandoffPlan(status, manifest, readme, receipt, tuple(issues))
