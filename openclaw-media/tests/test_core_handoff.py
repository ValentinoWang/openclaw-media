from __future__ import annotations

import copy
import json

from openclaw_media.core import (
    EDLEntry,
    HandoffClipDescriptor,
    StoryboardEntry,
    SubtitleCue,
    plan_handoff,
)


IDENTITY_A = "sha256:" + "a" * 64
IDENTITY_B = "sha256:" + "b" * 64


def _clip(clip_id: str, identity_ref: str, material_ref: str, duration: float = 8.0) -> HandoffClipDescriptor:
    return HandoffClipDescriptor(clip_id, identity_ref, material_ref, "video", duration)


def _board(shot_id: str, sequence: int, start: float, end: float, material_ref: str, identity_ref: str) -> StoryboardEntry:
    return StoryboardEntry(
        shot_id,
        sequence,
        start,
        end,
        end - start,
        "matched",
        None,
        material_ref,
        identity_ref,
    )


def _edit(edit_id: str, shot_id: str, sequence: int, start: float, end: float, material_ref: str, identity_ref: str, source_start: float = 0.0) -> EDLEntry:
    return EDLEntry(
        edit_id,
        shot_id,
        sequence,
        start,
        end,
        source_start,
        source_start + (end - start),
        material_ref,
        identity_ref,
    )


def test_handoff_golden_orders_manifest_and_builds_readme_and_receipt() -> None:
    clips = [
        _clip("clip-b", IDENTITY_B, "media/镜头-b.mp4"),
        _clip("clip-a", IDENTITY_A, "media/a.mp4"),
    ]
    storyboard = [
        _board("shot-b", 2, 2.0, 5.0, "media/镜头-b.mp4", IDENTITY_B),
        _board("shot-a", 1, 0.0, 2.0, "media/a.mp4", IDENTITY_A),
    ]
    edl = [
        _edit("edit-b", "shot-b", 2, 2.0, 5.0, "media/镜头-b.mp4", IDENTITY_B),
        _edit("edit-a", "shot-a", 1, 0.0, 2.0, "media/a.mp4", IDENTITY_A),
    ]
    subtitles = [
        SubtitleCue("cue-b", 2, 2.0, 4.0, "第二句", "vtt"),
        SubtitleCue("cue-a", 1, 0.0, 1.5, "First line", "srt"),
    ]

    plan = plan_handoff(clips, storyboard, edl, subtitles)

    assert plan.status == "ok"
    assert [row.edit_id for row in plan.manifest.clip_table] == ["edit-a", "edit-b"]
    assert [row.material_ref for row in plan.manifest.clip_table] == ["media/a.mp4", "media/镜头-b.mp4"]
    assert [entry.shot_id for entry in plan.manifest.storyboard] == ["shot-a", "shot-b"]
    assert [cue.cue_id for cue in plan.manifest.subtitles] == ["cue-a", "cue-b"]
    assert plan.readme.contract == "media.edit.handoff.v1"
    assert plan.readme.clip_count == 2
    assert plan.readme.subtitle_count == 2
    assert plan.readme.timeline_duration_seconds == 5.0
    assert "relative" in plan.readme.editor_action
    assert plan.validation.status == "ok"
    assert plan.validation.error_codes == ()
    assert plan.validation.checked_clip_count == 2
    assert plan.validation.checked_edit_count == 2
    assert plan.validation.checked_subtitle_count == 2


def test_handoff_reports_duplicate_identity_and_missing_material_without_fallback() -> None:
    clips = [
        _clip("clip-a", IDENTITY_A, "media/a.mp4"),
        _clip("clip-copy", IDENTITY_A, "media/copy.mp4"),
    ]
    edl = [_edit("edit-a", "shot-a", 1, 0.0, 2.0, "media/a.mp4", IDENTITY_A)]

    plan = plan_handoff(clips, [], edl)

    assert plan.status == "failed"
    assert plan.manifest.clip_table == ()
    assert plan.validation.error_codes == ("duplicate_clip_identity", "missing_material")
    assert [(issue.scope, issue.error_code) for issue in plan.issues] == [
        ("clip", "duplicate_clip_identity"),
        ("edl", "missing_material"),
    ]


def test_handoff_rejects_invalid_and_overlapping_edl_ranges() -> None:
    clips = [_clip("clip-a", IDENTITY_A, "media/a.mp4")]
    edl = [
        _edit("negative-source", "shot-a", 1, 0.0, 2.0, "media/a.mp4", IDENTITY_A, -1.0),
        _edit("overlap", "shot-b", 2, 1.0, 3.0, "media/a.mp4", IDENTITY_A),
    ]

    plan = plan_handoff(clips, [], edl)

    assert plan.status == "failed"
    assert plan.manifest.clip_table == ()
    assert plan.validation.error_codes == ("timing_conflict",)
    assert [issue.ref for issue in plan.issues] == ["negative-source", "overlap"]


def test_handoff_reports_corrupt_descriptors_and_unsupported_subtitles() -> None:
    plan = plan_handoff(
        [{"clip_id": "not-a-descriptor"}],
        ["not-a-storyboard-entry"],
        ["not-an-edl-entry"],
        [SubtitleCue("cue-a", 1, 0.0, 1.0, "text", "ass")],
    )

    assert plan.status == "failed"
    assert plan.validation.error_codes == ("invalid_input", "unsupported_subtitle")
    assert [(issue.scope, issue.error_code) for issue in plan.issues] == [
        ("clip", "invalid_input"),
        ("edl", "invalid_input"),
        ("storyboard", "invalid_input"),
        ("subtitle", "unsupported_subtitle"),
    ]


def test_handoff_is_idempotent_and_does_not_mutate_inputs() -> None:
    clips = [_clip("clip-a", IDENTITY_A, "media/a.mp4")]
    storyboard = [_board("shot-a", 1, 0.0, 2.0, "media/a.mp4", IDENTITY_A)]
    edl = [_edit("edit-a", "shot-a", 1, 0.0, 2.0, "media/a.mp4", IDENTITY_A)]
    subtitles = [SubtitleCue("cue-a", 1, 0.0, 1.0, "text")]
    before = copy.deepcopy((clips, storyboard, edl, subtitles))

    first = plan_handoff(clips, storyboard, edl, subtitles)
    second = plan_handoff(clips, storyboard, edl, subtitles)

    assert first == second
    assert (clips, storyboard, edl, subtitles) == before


def test_handoff_never_leaks_absolute_paths_or_iterator_exceptions() -> None:
    class BrokenInput:
        def __iter__(self):
            raise RuntimeError("/home/private/raw-secret.mp4")

    invalid_path_plan = plan_handoff(
        [_clip("/home/private/clip", IDENTITY_A, "/home/private/raw.mp4")],
        [_board("shot-a", 1, 0.0, 2.0, "/home/private/raw.mp4", IDENTITY_A)],
        [_edit("edit-a", "shot-a", 1, 0.0, 2.0, "/home/private/raw.mp4", IDENTITY_A)],
    )
    broken_input_plan = plan_handoff(BrokenInput(), [], [])

    serialized = json.dumps(
        [invalid_path_plan.to_dict(), broken_input_plan.to_dict()],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "/home/" not in serialized
    assert "RuntimeError" not in serialized
    assert invalid_path_plan.validation.error_codes == ("invalid_input", "missing_material")
    assert broken_input_plan.validation.error_codes == ("invalid_input",)
