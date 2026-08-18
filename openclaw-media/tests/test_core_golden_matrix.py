from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable

import pytest

import openclaw_media.core as core
from openclaw_media.core import (
    EDLEntry,
    HandoffClipDescriptor,
    MaterialDescriptor,
    MediaFile,
    OutputDimension,
    OutputMetric,
    OutputVersionDescriptor,
    Revision,
    RevisionArtifact,
    RevisionChange,
    RevisionConfirmation,
    ReviewWeight,
    RhythmEvent,
    RhythmProfile,
    SemanticCriterion,
    SemanticPolicy,
    ShotRequest,
    StoryboardEntry,
    TimelineMediaDescriptor,
)


IDENTITY_A = "sha256:" + "a" * 64
IDENTITY_B = "sha256:" + "b" * 64


@dataclass(frozen=True)
class GoldenCase:
    capability: str
    public_apis: tuple[str, ...]
    boundaries: frozenset[str]
    run: Callable[[Path], object]
    expected_digest: str


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


def _scan_case(workspace: Path) -> object:
    media = workspace / "扫描素材"
    media.mkdir(parents=True)
    (media / "小片段.mp4").write_bytes(b"ok")
    (media / "大静音.mp4").write_bytes(b"silent-large")
    (media / "损坏.mp4").write_bytes(b"bad")

    def probe(path: Path) -> object:
        if path.name == "损坏.mp4":
            raise OSError(f"cannot probe {path}")
        streams = [{"index": 0, "codec_type": "video", "codec_name": "h264"}]
        if path.name != "大静音.mp4":
            streams.append({"index": 1, "codec_type": "audio", "codec_name": "aac"})
        return {"format": {"duration": "3", "bit_rate": "8000"}, "streams": streams}

    return core.scan_media(media, probe_runner=probe, large_file_bytes=5).to_dict()


def _extraction_case(workspace: Path) -> object:
    root = workspace / "提取工作区"
    source = root / "原片" / "无声 视频.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")

    def runner(command: tuple[str, ...] | list[str]) -> None:
        target = Path(command[-1])
        target.write_bytes(f"artifact:{target.name}".encode())

    return core.extract_media_evidence(
        root,
        "原片/无声 视频.mp4",
        "证据/无声",
        duration_seconds=4,
        has_audio=False,
        runner=runner,
        uniform_count=1,
        dense_interval_seconds=3,
    ).to_dict()


def _organization_case(_: Path) -> object:
    files = (
        MediaFile("素材/大成片.mp4", "video", ".mp4", 10_000, "large", "b" * 64, None),
        MediaFile("素材/封面.jpg", "image", ".jpg", 3, "small", "a" * 64, None),
    )
    return core.plan_media_organization(reversed(files)).to_dict()


def _storyboard_case(_: Path) -> object:
    materials = (
        MaterialDescriptor("素材/人物.mp4", "video", "a" * 64, 8, ("person", "close")),
        MaterialDescriptor("素材/远景.mp4", "video", "b" * 64, 8, ("outdoor", "wide")),
    )
    shots = (
        ShotRequest("wide", 2, 2, 1, ("outdoor",), ("wide",)),
        ShotRequest("close", 1, 1.5, 0, ("person",), ("close",)),
    )
    return core.plan_storyboard(reversed(materials), reversed(shots)).to_dict()


def _edit(
    edit_id: str,
    shot_id: str,
    sequence: int,
    start: float,
    end: float,
    ref: str,
    identity: str,
) -> EDLEntry:
    return EDLEntry(edit_id, shot_id, sequence, start, end, 0, end - start, ref, identity)


def _handoff_case(_: Path) -> object:
    ref = "media/镜头.mp4"
    clip = HandoffClipDescriptor("clip", IDENTITY_A, ref, "video", 4)
    board = StoryboardEntry("shot", 1, 0, 2, 2, "matched", None, ref, IDENTITY_A)
    edit = _edit("edit", "shot", 1, 0, 2, ref, IDENTITY_A)
    return core.plan_handoff((clip,), (board,), (edit,)).to_dict()


def _timeline_case(_: Path) -> object:
    ref = "media/镜头.mp4"
    edit = _edit("edit", "shot", 1, 0, 2, "offline/镜头.mp4", IDENTITY_A)
    media = TimelineMediaDescriptor(IDENTITY_A, ref, "video", 4)
    return core.build_timeline((edit,), (media,)).to_dict()


def _revision_case(_: Path) -> object:
    old_identity = "sha256:" + "1" * 64
    new_identity = "sha256:" + "2" * 64
    base = Revision(
        "revisions/base.json",
        "sha256:" + "0" * 64,
        None,
        (RevisionArtifact("storyboard", "storyboard", "artifacts/storyboard.json", old_identity),),
    )
    change = RevisionChange(
        "change-1",
        1,
        "storyboard",
        old_identity,
        "artifacts/分镜-v2.json",
        new_identity,
        "replace",
    )
    return core.create_revision(
        base,
        (change,),
        RevisionConfirmation("confirmations/review-1", True),
    ).to_dict()


def _review_case(_: Path) -> object:
    version = OutputVersionDescriptor(
        "发布版",
        "media/发布版.mp4",
        "review/联系表.jpg",
        "review/场景表.jpg",
        (OutputMetric("bitrate", 8, 4, 12, "compression_risk"),),
        (OutputDimension("hook", 90),),
    )
    output = core.review_output(
        (version,),
        platform="douyin",
        weights=(ReviewWeight("hook", 1),),
        required_metrics=("bitrate",),
    )
    rhythm = core.review_rhythm(
        "media/发布版.mp4",
        3,
        (RhythmEvent("beat", "audio", "beat", 1, 1),),
        (RhythmEvent("cut", "visual", "scene", 1.05, 0.9),),
        RhythmProfile("fast", 1, 1, 0.1),
    )
    semantic = core.review_semantic(
        "review/联系表.jpg",
        (SemanticCriterion("hook", 80, 90, 1),),
        SemanticPolicy("publish", 0.4, 0.6, ("hook",)),
    )
    return {
        "output": output.to_dict(),
        "rhythm": rhythm.to_dict(),
        "semantic": semantic.to_dict(),
    }


CASES = (
    GoldenCase("media_scan", ("scan_media", "probe_media"), frozenset({"small", "large", "corrupt", "no_audio", "non_ascii"}), _scan_case, "sha256:5aeb321a09d50ca88562e410e0ad6a0b4eda332776b568f905127346db4df39e"),
    GoldenCase("evidence_extraction", ("extract_media_evidence",), frozenset({"no_audio", "non_ascii"}), _extraction_case, "sha256:819970c50ff01d25ddb6e2a640af4cf30835c693efc1fea826515c222a45e100"),
    GoldenCase("organization", ("plan_media_organization",), frozenset({"small", "large", "non_ascii"}), _organization_case, "sha256:1d3a7c89e690021df991650fa3e289c5a4f36483f4c1e1c06f97c9f55485c07e"),
    GoldenCase("storyboard_edl", ("plan_storyboard",), frozenset({"non_ascii"}), _storyboard_case, "sha256:c22d5c0af602d81d38c6fd0748c5aa48e0e5c18e220600168aa0276bd1c74341"),
    GoldenCase("human_handoff", ("plan_handoff",), frozenset({"non_ascii"}), _handoff_case, "sha256:e782585d194ba506a9f888ccb865125ad55df111fcf685045a1e8cdaf4039d99"),
    GoldenCase("otio_timeline", ("build_timeline",), frozenset({"non_ascii"}), _timeline_case, "sha256:f26d8a67719bd699cbb65eb105fc04ddc498176535558b6990e4b5f9b3a5b24a"),
    GoldenCase("confirmed_revision", ("create_revision",), frozenset({"non_ascii"}), _revision_case, "sha256:b8d167419ccb25b6c6b224b5c6e4d227764e51230f1c0a573ea707d2f9c9622f"),
    GoldenCase("output_rhythm_semantic_review", ("review_output", "review_rhythm", "review_semantic"), frozenset({"non_ascii"}), _review_case, "sha256:bedc2b8b826dffa744f5923c3bb18904b50bc16c5df0ccb877e6d614b3898ef4"),
)


def test_matrix_has_exact_capabilities_boundaries_and_public_exports() -> None:
    assert [case.capability for case in CASES] == [
        "media_scan",
        "evidence_extraction",
        "organization",
        "storyboard_edl",
        "human_handoff",
        "otio_timeline",
        "confirmed_revision",
        "output_rhythm_semantic_review",
    ]
    assert frozenset().union(*(case.boundaries for case in CASES)) == {
        "small",
        "large",
        "corrupt",
        "no_audio",
        "non_ascii",
    }
    for case in CASES:
        for api in case.public_apis:
            assert api in core.__all__
            assert callable(getattr(core, api))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.capability)
def test_cross_capability_golden_matrix(case: GoldenCase, tmp_path: Path) -> None:
    payload = case.run(tmp_path / case.capability)
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert _digest(payload) == case.expected_digest
    assert str(tmp_path) not in rendered
    assert not re.search(r'(?<![A-Za-z0-9])[A-Za-z]:[\\\\/]', rendered)
    assert '"/home/' not in rendered
    assert "Traceback" not in rendered
    assert "exception" not in rendered.lower()
