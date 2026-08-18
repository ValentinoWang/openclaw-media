import copy
import json
import xml.etree.ElementTree as ET

import opentimelineio as otio

from openclaw_media.core import (
    EDLEntry,
    KdenliveEnvironment,
    TimelineMediaDescriptor,
    build_timeline,
)

IDENTITY_A = "sha256:" + "a" * 64
IDENTITY_B = "sha256:" + "b" * 64


def _media(identity: str, ref: str, duration: float = 10.0) -> TimelineMediaDescriptor:
    return TimelineMediaDescriptor(identity, ref, "video", duration)


def _edit(
    edit_id: str,
    sequence: int,
    timeline_in: float,
    timeline_out: float,
    identity: str,
    ref: str,
    source_in: float = 0.0,
) -> EDLEntry:
    return EDLEntry(
        edit_id,
        f"shot-{sequence}",
        sequence,
        timeline_in,
        timeline_out,
        source_in,
        source_in + timeline_out - timeline_in,
        ref,
        identity,
    )


def test_otio_golden_is_deterministic_round_trippable_and_relink_ordered() -> None:
    media = [
        _media(IDENTITY_B, "media/镜头-b.mp4"),
        _media(IDENTITY_A, "media/a-new.mp4"),
    ]
    edl = [
        _edit("edit-b", 2, 3.0, 5.0, IDENTITY_B, "offline/b.mp4", 1.0),
        _edit("edit-a", 1, 0.0, 2.0, IDENTITY_A, "offline/a.mp4"),
    ]

    plan = build_timeline(edl, media)

    assert plan.status == "ok"
    assert plan.validation.otio_round_trip_valid is True
    assert plan.validation.kdenlive_status == "not_requested"
    assert [entry.edit_id for entry in plan.relink_manifest] == ["edit-a", "edit-b"]
    assert [entry.status for entry in plan.relink_manifest] == ["relinked", "relinked"]
    assert plan.handoff.canonical_timeline_ref == "project.otio"
    assert plan.handoff.optional_editor_ref is None
    assert plan.project_otio is not None
    timeline = otio.adapters.read_from_string(plan.project_otio, adapter_name="otio_json")
    assert isinstance(timeline, otio.schema.Timeline)
    assert timeline.metadata["openclaw_media"]["timeline_fact"] == "project.otio"
    assert [item.name for item in timeline.tracks[0]] == ["edit-a", "gap", "edit-b"]
    assert timeline.tracks[0][0].media_reference.target_url == "media/a-new.mp4"
    assert timeline.tracks[0][2].media_reference.target_url == "media/镜头-b.mp4"
    assert build_timeline(reversed(edl), reversed(media)).project_otio == plan.project_otio


def test_kdenlive_available_exports_and_validates_otio_derived_project() -> None:
    plan = build_timeline(
        [_edit("edit-a", 1, 0.0, 2.0, IDENTITY_A, "media/a.mp4")],
        [_media(IDENTITY_A, "media/a.mp4")],
        kdenlive=KdenliveEnvironment(True, "24.02.1"),
    )

    assert plan.status == "ok"
    assert plan.kdenlive.status == "exported"
    assert plan.kdenlive.artifact_ref == "project.kdenlive"
    assert plan.validation.kdenlive_valid is True
    assert plan.handoff.optional_editor_ref == "project.kdenlive"
    root = ET.fromstring(plan.kdenlive.content or "")
    assert root.tag == "mlt"
    assert root.find("./producer/property[@name='resource']").text == "media/a.mp4"
    assert root.find("./tractor/track").attrib["producer"] == "playlist0"


def test_kdenlive_unavailable_is_explicit_and_never_replaces_otio() -> None:
    plan = build_timeline(
        [_edit("edit-a", 1, 0.0, 2.0, IDENTITY_A, "media/a.mp4")],
        [_media(IDENTITY_A, "media/a.mp4")],
        kdenlive=KdenliveEnvironment(False),
    )

    assert plan.status == "ok"
    assert plan.project_otio is not None
    assert plan.kdenlive.status == "unavailable"
    assert plan.kdenlive.content is None
    assert plan.kdenlive.error_code == "kdenlive_unavailable"
    assert plan.validation.warning_codes == ("kdenlive_unavailable",)
    assert plan.handoff.optional_editor_ref is None


def test_missing_media_and_relink_ambiguity_fail_closed_in_stable_order() -> None:
    plan = build_timeline(
        [
            _edit("edit-missing", 2, 2.0, 4.0, IDENTITY_B, "offline/b.mp4"),
            _edit("edit-ambiguous", 1, 0.0, 2.0, IDENTITY_A, "offline/a.mp4"),
        ],
        [
            _media(IDENTITY_A, "media/a-2.mp4"),
            _media(IDENTITY_A, "media/a-1.mp4"),
        ],
        kdenlive=KdenliveEnvironment(True, "24.02"),
    )

    assert plan.status == "failed"
    assert plan.project_otio is None
    assert plan.kdenlive.status == "not_generated"
    assert [entry.status for entry in plan.relink_manifest] == ["ambiguous", "missing"]
    assert plan.relink_manifest[0].candidate_refs == (
        "media/a-1.mp4",
        "media/a-2.mp4",
    )
    assert plan.validation.error_codes == ("missing_media", "relink_ambiguous")


def test_invalid_overlapping_and_corrupt_edl_have_explicit_outcomes() -> None:
    media = [_media(IDENTITY_A, "media/a.mp4")]
    invalid = _edit("invalid", 1, 0.0, 2.0, IDENTITY_A, "media/a.mp4")
    invalid = EDLEntry(
        invalid.edit_id,
        invalid.shot_id,
        invalid.sequence,
        invalid.timeline_in_seconds,
        invalid.timeline_out_seconds,
        invalid.source_in_seconds,
        3.0,
        invalid.material_ref,
        invalid.identity_ref,
    )
    overlap = _edit("overlap", 2, 1.0, 3.0, IDENTITY_A, "media/a.mp4")

    plan = build_timeline([invalid, overlap, {"bad": "descriptor"}], media)

    assert plan.status == "failed"
    assert plan.validation.error_codes == ("invalid_input", "invalid_timing")
    assert [(issue.ref, issue.error_code) for issue in plan.issues] == [
        (None, "invalid_input"),
        ("invalid", "invalid_timing"),
        ("overlap", "invalid_timing"),
    ]


def test_timeline_is_idempotent_and_does_not_mutate_inputs() -> None:
    edl = [_edit("edit-a", 1, 0.0, 2.0, IDENTITY_A, "media/a.mp4")]
    media = [_media(IDENTITY_A, "media/a.mp4")]
    environment = KdenliveEnvironment(True, "24.02")
    before = copy.deepcopy((edl, media, environment))

    first = build_timeline(edl, media, kdenlive=environment)
    second = build_timeline(edl, media, kdenlive=environment)

    assert first == second
    assert (edl, media, environment) == before


def test_absolute_refs_and_iterator_exceptions_never_leak() -> None:
    class BrokenInput:
        def __iter__(self):
            raise RuntimeError("/home/private/raw-secret.mp4")

    invalid_path = build_timeline(
        [_edit("edit-a", 1, 0.0, 2.0, IDENTITY_A, "/home/private/raw.mp4")],
        [_media(IDENTITY_A, "/home/private/raw.mp4")],
    )
    broken = build_timeline(BrokenInput(), [])
    serialized = json.dumps(
        [invalid_path.to_dict(), broken.to_dict()],
        ensure_ascii=False,
        sort_keys=True,
    )

    assert "/home/" not in serialized
    assert "RuntimeError" not in serialized
    assert invalid_path.validation.error_codes == ("invalid_input",)
    assert broken.validation.error_codes == ("invalid_input",)
