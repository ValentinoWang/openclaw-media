"""Deterministic render planning from the confirmed OTIO timeline fact."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from typing import Any, Iterable

import opentimelineio as otio

from .core.revision import RevisionArtifact, RevisionResult


_IDENTITY = re.compile(r"sha256:[0-9a-f]{64}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")


@dataclass(frozen=True)
class RenderMediaDescriptor:
    identity_ref: str
    material_ref: str
    sha256: str
    size_bytes: int
    duration_seconds: float
    has_video: bool
    has_audio: bool
    verified: bool


@dataclass(frozen=True)
class RenderInput:
    identity_ref: str
    material_ref: str
    sha256: str
    size_bytes: int
    duration: tuple[int, int]
    has_audio: bool


@dataclass(frozen=True)
class RenderOutput:
    ref: str
    mime_type: str
    cloud_bytes: int


@dataclass(frozen=True)
class RenderManifest:
    contract: str
    manifest_ref: str
    identity_ref: str
    revision_identity_ref: str
    project_otio_ref: str
    project_otio_identity_ref: str
    inputs: tuple[RenderInput, ...]
    frame_rate: tuple[int, int]
    duration: tuple[int, int]
    expected_video_frames: int
    expected_audio_tracks: int
    audio_disposition: str
    output: RenderOutput


@dataclass(frozen=True)
class RenderIssue:
    scope: str
    ref: str | None
    error_code: str


@dataclass(frozen=True)
class RenderPlan:
    status: str
    manifest: RenderManifest | None
    issues: tuple[RenderIssue, ...]

    @property
    def error_codes(self) -> tuple[str, ...]:
        return tuple(sorted({item.error_code for item in self.issues}))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _relative_ref(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    if _WINDOWS_ABSOLUTE.match(value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.as_posix() == value


def _safe_ref(value: object) -> str | None:
    return value if _relative_ref(value) else None


def _identity(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _fraction(value: float) -> tuple[int, int]:
    fraction = Fraction(str(value)).limit_denominator(1_000_000)
    return fraction.numerator, fraction.denominator


def _failed(issues: Iterable[RenderIssue]) -> RenderPlan:
    ordered = tuple(sorted(issues, key=lambda item: (item.error_code, item.scope, item.ref or "")))
    return RenderPlan("rejected", None, ordered)


def plan_render(
    revision_result: RevisionResult,
    project_otio: str,
    media: Iterable[RenderMediaDescriptor],
    *,
    frame_rate: tuple[int, int] = (30, 1),
) -> RenderPlan:
    """Validate the confirmed timeline fact and produce a planning-only render manifest."""
    if (
        not isinstance(frame_rate, tuple)
        or len(frame_rate) != 2
        or any(not isinstance(value, int) or isinstance(value, bool) for value in frame_rate)
        or frame_rate[0] <= 0
        or frame_rate[1] <= 0
    ):
        return _failed((RenderIssue("frame_rate", None, "invalid_input"),))
    if not isinstance(revision_result, RevisionResult):
        return _failed((RenderIssue("revision", None, "invalid_input"),))
    if (
        revision_result.status != "ok"
        or revision_result.revision is None
        or revision_result.receipt.status != "applied"
        or revision_result.receipt.revision_identity_ref != revision_result.revision.identity_ref
    ):
        return _failed((RenderIssue("revision", None, "unconfirmed_revision"),))
    revision = revision_result.revision
    if not _IDENTITY.fullmatch(revision.identity_ref):
        return _failed((RenderIssue("revision", None, "invalid_input"),))
    try:
        artifacts = tuple(revision.artifacts)
    except Exception:
        return _failed((RenderIssue("revision", None, "invalid_input"),))
    editors = [item for item in artifacts if isinstance(item, RevisionArtifact) and item.kind == "editor_artifact"]
    if len(editors) != 1 or not _relative_ref(editors[0].artifact_ref) or not _IDENTITY.fullmatch(editors[0].identity_ref):
        return _failed((RenderIssue("revision", None, "invalid_input"),))
    editor = editors[0]
    if not isinstance(project_otio, str) or _identity(project_otio) != editor.identity_ref:
        return _failed((RenderIssue("revision", editor.artifact_ref, "stale_revision"),))

    try:
        media_items = list(media)
    except Exception:
        return _failed((RenderIssue("media", None, "invalid_input"),))
    issues: list[RenderIssue] = []
    valid: dict[tuple[str, str], RenderMediaDescriptor] = {}
    for item in media_items:
        if (
            not isinstance(item, RenderMediaDescriptor)
            or not _IDENTITY.fullmatch(item.identity_ref)
            or not _relative_ref(item.material_ref)
            or not _DIGEST.fullmatch(item.sha256)
            or "sha256:" + item.sha256 != item.identity_ref
            or not isinstance(item.size_bytes, int)
            or isinstance(item.size_bytes, bool)
            or item.size_bytes <= 0
            or not isinstance(item.duration_seconds, (int, float))
            or isinstance(item.duration_seconds, bool)
            or not math.isfinite(item.duration_seconds)
            or item.duration_seconds <= 0
            or not isinstance(item.has_video, bool)
            or not isinstance(item.has_audio, bool)
            or not isinstance(item.verified, bool)
        ):
            issues.append(RenderIssue("media", _safe_ref(getattr(item, "material_ref", None)), "invalid_input"))
            continue
        key = (item.identity_ref, item.material_ref)
        if key in valid:
            issues.append(RenderIssue("media", item.material_ref, "invalid_input"))
            continue
        valid[key] = item

    try:
        timeline = otio.adapters.read_from_string(project_otio, adapter_name="otio_json")
    except Exception:
        return _failed((*issues, RenderIssue("otio", None, "invalid_otio")))
    if (
        not isinstance(timeline, otio.schema.Timeline)
        or timeline.metadata.get("openclaw_media", {}).get("timeline_fact") != "project.otio"
        or len(timeline.tracks) != 1
        or timeline.tracks[0].kind != otio.schema.TrackKind.Video
    ):
        return _failed((*issues, RenderIssue("otio", None, "invalid_otio")))

    ordered_inputs: list[RenderInput] = []
    seen: set[tuple[str, str]] = set()
    for child in timeline.tracks[0]:
        if isinstance(child, otio.schema.Gap):
            continue
        if not isinstance(child, otio.schema.Clip) or not isinstance(child.media_reference, otio.schema.ExternalReference):
            issues.append(RenderIssue("otio", None, "unsupported_stream"))
            continue
        metadata = child.media_reference.metadata.get("openclaw_media", {})
        identity_ref = metadata.get("identity_ref")
        material_ref = child.media_reference.target_url
        key = (identity_ref, material_ref)
        descriptor = valid.get(key)
        if descriptor is None:
            issues.append(RenderIssue("media", _safe_ref(material_ref), "missing_media"))
            continue
        if not descriptor.verified:
            issues.append(RenderIssue("media", descriptor.material_ref, "corrupt_media"))
            continue
        if not descriptor.has_video or metadata.get("kind") != "video":
            issues.append(RenderIssue("media", descriptor.material_ref, "unsupported_stream"))
            continue
        source_range = child.source_range
        if source_range is None or source_range.end_time_exclusive().to_seconds() > descriptor.duration_seconds + 1e-9:
            issues.append(RenderIssue("media", descriptor.material_ref, "timeline_mismatch"))
            continue
        if key not in seen:
            seen.add(key)
            ordered_inputs.append(
                RenderInput(
                    descriptor.identity_ref,
                    descriptor.material_ref,
                    descriptor.sha256,
                    descriptor.size_bytes,
                    _fraction(descriptor.duration_seconds),
                    descriptor.has_audio,
                )
            )
    if issues:
        return _failed(issues)

    duration_time = timeline.duration()
    duration_fraction = Fraction(int(round(duration_time.value)), int(round(duration_time.rate)))
    duration = (duration_fraction.numerator, duration_fraction.denominator)
    frames_fraction = duration_fraction * Fraction(*frame_rate)
    expected_frames = (2 * frames_fraction.numerator + frames_fraction.denominator) // (2 * frames_fraction.denominator)
    audio_tracks = int(any(item.has_audio for item in ordered_inputs))
    identity_payload = {
        "contract": "media.render.manifest.v1",
        "revision_identity_ref": revision.identity_ref,
        "project_otio_ref": editor.artifact_ref,
        "project_otio_identity_ref": editor.identity_ref,
        "inputs": [asdict(item) for item in ordered_inputs],
        "frame_rate": frame_rate,
        "duration": duration,
        "expected_video_frames": expected_frames,
        "expected_audio_tracks": audio_tracks,
        "audio_disposition": "mix_if_present" if audio_tracks else "none",
        "output_mime_type": "video/mp4",
        "cloud_bytes": 0,
    }
    manifest_identity = _digest(identity_payload)
    suffix = manifest_identity.removeprefix("sha256:")
    manifest = RenderManifest(
        "media.render.manifest.v1",
        f"render-manifests/{suffix}.json",
        manifest_identity,
        revision.identity_ref,
        editor.artifact_ref,
        editor.identity_ref,
        tuple(ordered_inputs),
        frame_rate,
        duration,
        expected_frames,
        audio_tracks,
        "mix_if_present" if audio_tracks else "none",
        RenderOutput(f"renders/{suffix}/final.mp4", "video/mp4", 0),
    )
    return RenderPlan("ok", manifest, ())
