from __future__ import annotations

import copy
import hashlib
import json

import opentimelineio as otio

from openclaw_media import RenderMediaDescriptor, plan_render
from openclaw_media.core import (
    EDLEntry,
    Revision,
    RevisionArtifact,
    RevisionChange,
    RevisionConfirmation,
    TimelineMediaDescriptor,
    build_timeline,
    create_revision,
)


IDENTITY_A = "sha256:" + "a" * 64
IDENTITY_B = "sha256:" + "b" * 64
IDENTITY_STORYBOARD = "sha256:" + "1" * 64
IDENTITY_EDL = "sha256:" + "2" * 64
IDENTITY_OLD_TIMELINE = "sha256:" + "3" * 64


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


def _timeline() -> str:
    result = build_timeline(
        [
            _edit("edit-b", 2, 2.5, 4.0, IDENTITY_B, "media/镜头-b.mp4", 1.0),
            _edit("edit-a", 1, 0.0, 2.0, IDENTITY_A, "media/a.mp4"),
        ],
        [
            TimelineMediaDescriptor(IDENTITY_B, "media/镜头-b.mp4", "video", 8.0),
            TimelineMediaDescriptor(IDENTITY_A, "media/a.mp4", "video", 5.0),
        ],
    )
    assert result.status == "ok"
    assert result.project_otio is not None
    return result.project_otio


def _identity(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _confirmed(project_otio: str):
    base = Revision(
        "revisions/base.json",
        "sha256:" + "0" * 64,
        None,
        (
            RevisionArtifact("storyboard", "storyboard", "artifacts/storyboard.json", IDENTITY_STORYBOARD),
            RevisionArtifact("edl", "edl", "artifacts/edit-list.json", IDENTITY_EDL),
            RevisionArtifact("editor", "editor_artifact", "artifacts/old.otio", IDENTITY_OLD_TIMELINE),
        ),
    )
    return create_revision(
        base,
        [
            RevisionChange(
                "confirmed-timeline",
                1,
                "editor",
                IDENTITY_OLD_TIMELINE,
                "artifacts/project.otio",
                _identity(project_otio),
                "replace",
            )
        ],
        RevisionConfirmation("confirmations/editor-approved", True),
    )


def _media(
    identity: str,
    ref: str,
    duration: float,
    *,
    audio: bool,
    verified: bool = True,
    video: bool = True,
) -> RenderMediaDescriptor:
    return RenderMediaDescriptor(
        identity,
        ref,
        identity.removeprefix("sha256:"),
        4096,
        duration,
        video,
        audio,
        verified,
    )


def test_confirmed_otio_builds_deterministic_render_manifest_golden() -> None:
    project_otio = _timeline()
    revision = _confirmed(project_otio)
    media = [
        _media(IDENTITY_B, "media/镜头-b.mp4", 8.0, audio=False),
        _media(IDENTITY_A, "media/a.mp4", 5.0, audio=True),
    ]
    before = copy.deepcopy((revision, media, project_otio))

    result = plan_render(revision, project_otio, reversed(media), frame_rate=(30, 1))
    repeated = plan_render(revision, project_otio, media, frame_rate=(30, 1))

    assert result == repeated
    assert (revision, media, project_otio) == before
    assert result.status == "ok"
    assert result.issues == ()
    assert result.manifest is not None
    manifest = result.manifest
    assert manifest.contract == "media.render.manifest.v1"
    assert manifest.identity_ref == "sha256:e4b884dd08c865c6bb88cf3439ef471389ff03b6541d2944d9cd24c76d32c89e"
    assert manifest.revision_identity_ref == revision.revision.identity_ref
    assert manifest.project_otio_ref == "artifacts/project.otio"
    assert manifest.project_otio_identity_ref == _identity(project_otio)
    assert [(item.identity_ref, item.material_ref) for item in manifest.inputs] == [
        (IDENTITY_A, "media/a.mp4"),
        (IDENTITY_B, "media/镜头-b.mp4"),
    ]
    assert manifest.frame_rate == (30, 1)
    assert manifest.duration == (4, 1)
    assert manifest.expected_video_frames == 120
    assert manifest.expected_audio_tracks == 1
    assert manifest.audio_disposition == "mix_if_present"
    assert manifest.output.mime_type == "video/mp4"
    assert manifest.output.cloud_bytes == 0
    assert manifest.output.ref.startswith("renders/")
    assert manifest.output.ref.endswith("/final.mp4")
    assert manifest.manifest_ref.startswith("render-manifests/")
    reopened = otio.adapters.read_from_string(project_otio, adapter_name="otio_json")
    assert reopened.duration().to_seconds() == 4.0


def test_silent_timeline_and_non_ascii_refs_remain_explicit_and_relative() -> None:
    project_otio = _timeline()
    result = plan_render(
        _confirmed(project_otio),
        project_otio,
        [
            _media(IDENTITY_A, "media/a.mp4", 5.0, audio=False),
            _media(IDENTITY_B, "media/镜头-b.mp4", 8.0, audio=False),
        ],
        frame_rate=(24_000, 1_001),
    )

    assert result.manifest is not None
    assert result.manifest.expected_audio_tracks == 0
    assert result.manifest.audio_disposition == "none"
    assert result.manifest.duration == (4, 1)
    assert result.manifest.expected_video_frames == 96
    serialized = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
    assert "镜头-b.mp4" in serialized
    assert "/home/" not in serialized


def test_unconfirmed_and_stale_revision_never_create_a_manifest() -> None:
    project_otio = _timeline()
    rejected = create_revision(
        Revision(
            "revisions/base.json",
            "sha256:" + "0" * 64,
            None,
            (
                RevisionArtifact("storyboard", "storyboard", "artifacts/storyboard.json", IDENTITY_STORYBOARD),
                RevisionArtifact("edl", "edl", "artifacts/edit-list.json", IDENTITY_EDL),
                RevisionArtifact("editor", "editor_artifact", "artifacts/old.otio", IDENTITY_OLD_TIMELINE),
            ),
        ),
        [RevisionChange("edit", 1, "editor", IDENTITY_OLD_TIMELINE, "artifacts/project.otio", _identity(project_otio), "replace")],
        RevisionConfirmation("confirmations/pending", False),
    )
    media = [_media(IDENTITY_A, "media/a.mp4", 5.0, audio=True), _media(IDENTITY_B, "media/镜头-b.mp4", 8.0, audio=False)]

    unconfirmed = plan_render(rejected, project_otio, media)
    stale = plan_render(_confirmed(project_otio), project_otio + " ", media)

    assert unconfirmed.manifest is None
    assert unconfirmed.error_codes == ("unconfirmed_revision",)
    assert stale.manifest is None
    assert stale.error_codes == ("stale_revision",)


def test_missing_corrupt_and_unsupported_media_fail_closed_in_stable_order() -> None:
    project_otio = _timeline()
    revision = _confirmed(project_otio)

    missing = plan_render(revision, project_otio, [_media(IDENTITY_A, "media/a.mp4", 5.0, audio=True)])
    corrupt = plan_render(
        revision,
        project_otio,
        [
            _media(IDENTITY_A, "media/a.mp4", 5.0, audio=True, verified=False),
            _media(IDENTITY_B, "media/镜头-b.mp4", 8.0, audio=False),
        ],
    )
    unsupported = plan_render(
        revision,
        project_otio,
        [
            _media(IDENTITY_A, "media/a.mp4", 5.0, audio=True, video=False),
            _media(IDENTITY_B, "media/镜头-b.mp4", 8.0, audio=False),
        ],
    )

    assert missing.error_codes == ("missing_media",)
    assert corrupt.error_codes == ("corrupt_media",)
    assert unsupported.error_codes == ("unsupported_stream",)
    assert missing.manifest is corrupt.manifest is unsupported.manifest is None


def test_malformed_otio_absolute_refs_and_timeline_mismatch_do_not_leak() -> None:
    project_otio = _timeline()
    revision = _confirmed(project_otio)
    media = [_media(IDENTITY_A, "media/a.mp4", 5.0, audio=True), _media(IDENTITY_B, "media/镜头-b.mp4", 8.0, audio=False)]

    malformed = plan_render(revision, "{/home/private/broken.otio", media)
    absolute = plan_render(
        revision,
        project_otio,
        [_media(IDENTITY_A, "/home/private/a.mp4", 5.0, audio=True), media[1]],
    )
    wrong_duration = plan_render(
        revision,
        project_otio,
        [_media(IDENTITY_A, "media/a.mp4", 1.0, audio=True), media[1]],
    )

    assert malformed.error_codes == ("stale_revision",)
    assert absolute.error_codes == ("invalid_input", "missing_media")
    assert wrong_duration.error_codes == ("timeline_mismatch",)
    serialized = json.dumps(
        [malformed.to_dict(), absolute.to_dict(), wrong_duration.to_dict()],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "/home/" not in serialized
    assert "private" not in serialized
    assert "Traceback" not in serialized


def test_invalid_descriptors_frame_rate_and_iterator_failure_are_sanitized() -> None:
    class BrokenMedia:
        def __iter__(self):
            raise RuntimeError("/home/private/source.mp4")

    project_otio = _timeline()
    revision = _confirmed(project_otio)
    invalid_rate = plan_render(revision, project_otio, [], frame_rate=(0, 1))
    broken = plan_render(revision, project_otio, BrokenMedia())

    assert invalid_rate.error_codes == ("invalid_input",)
    assert broken.error_codes == ("invalid_input",)
    serialized = json.dumps([invalid_rate.to_dict(), broken.to_dict()], sort_keys=True)
    assert "/home/" not in serialized
    assert "RuntimeError" not in serialized
