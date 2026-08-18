from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

import opentimelineio as otio

from .storyboard import EDLEntry

_IDENTITY = re.compile(r"sha256:[0-9a-f]{64}")
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*")
_WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")
_KINDS = {"audio", "image", "video"}
_TIME_RATE = 1_000_000.0


@dataclass(frozen=True)
class TimelineMediaDescriptor:
    identity_ref: str
    material_ref: str
    kind: str
    duration_seconds: float


@dataclass(frozen=True)
class KdenliveEnvironment:
    available: bool
    version: str | None = None


@dataclass(frozen=True)
class TimelineRelink:
    edit_id: str
    identity_ref: str
    source_ref: str
    resolved_ref: str | None
    status: str
    candidate_refs: tuple[str, ...]


@dataclass(frozen=True)
class TimelineIssue:
    scope: str
    ref: str | None
    error_code: str


@dataclass(frozen=True)
class KdenliveExport:
    status: str
    artifact_ref: str | None
    mime_type: str | None
    content: str | None
    version: str | None
    error_code: str | None


@dataclass(frozen=True)
class TimelineHandoff:
    contract: str
    canonical_timeline_ref: str | None
    optional_editor_ref: str | None
    relink_manifest_ref: str
    validation_ref: str
    editor_action: str


@dataclass(frozen=True)
class TimelineValidation:
    status: str
    error_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    otio_round_trip_valid: bool
    kdenlive_status: str
    kdenlive_valid: bool | None
    checked_edit_count: int
    checked_media_count: int


@dataclass(frozen=True)
class TimelinePlan:
    status: str
    project_otio: str | None
    relink_manifest: tuple[TimelineRelink, ...]
    kdenlive: KdenliveExport
    handoff: TimelineHandoff
    validation: TimelineValidation
    issues: tuple[TimelineIssue, ...]

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


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _seconds(value: float) -> otio.opentime.RationalTime:
    return otio.opentime.RationalTime(round(value * _TIME_RATE), _TIME_RATE)


def _canonical_otio(timeline: otio.schema.Timeline) -> str:
    serialized = otio.adapters.write_to_string(timeline, adapter_name="otio_json")
    parsed = json.loads(serialized)
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _build_otio(
    edits: tuple[EDLEntry, ...],
    resolved: dict[str, TimelineMediaDescriptor],
) -> str:
    timeline = otio.schema.Timeline(name="project")
    timeline.metadata["openclaw_media"] = {
        "contract": "media.edit.timeline.v1",
        "timeline_fact": "project.otio",
    }
    track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    timeline.tracks.append(track)
    cursor = 0.0
    for edit in edits:
        if edit.timeline_in_seconds > cursor:
            track.append(
                otio.schema.Gap(
                    name="gap",
                    source_range=otio.opentime.TimeRange(
                        start_time=_seconds(0.0),
                        duration=_seconds(edit.timeline_in_seconds - cursor),
                    ),
                )
            )
        media = resolved[edit.edit_id]
        reference = otio.schema.ExternalReference(
            target_url=media.material_ref,
            available_range=otio.opentime.TimeRange(
                start_time=_seconds(0.0),
                duration=_seconds(media.duration_seconds),
            ),
        )
        reference.metadata["openclaw_media"] = {
            "identity_ref": media.identity_ref,
            "kind": media.kind,
        }
        clip = otio.schema.Clip(
            name=edit.edit_id,
            media_reference=reference,
            source_range=otio.opentime.TimeRange(
                start_time=_seconds(edit.source_in_seconds),
                duration=_seconds(edit.source_out_seconds - edit.source_in_seconds),
            ),
        )
        clip.metadata["openclaw_media"] = {
            "edit_id": edit.edit_id,
            "sequence": edit.sequence,
            "shot_id": edit.shot_id,
            "timeline_in_seconds": edit.timeline_in_seconds,
            "timeline_out_seconds": edit.timeline_out_seconds,
        }
        track.append(clip)
        cursor = edit.timeline_out_seconds
    return _canonical_otio(timeline)


def _read_otio(content: str) -> otio.schema.Timeline | None:
    try:
        value = otio.adapters.read_from_string(content, adapter_name="otio_json")
    except Exception:
        return None
    if not isinstance(value, otio.schema.Timeline) or len(value.tracks) != 1:
        return None
    return value


def _clock(seconds: float) -> str:
    micros = round(seconds * _TIME_RATE)
    hours, micros = divmod(micros, 3_600_000_000)
    minutes, micros = divmod(micros, 60_000_000)
    whole, micros = divmod(micros, 1_000_000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d}.{micros:06d}"


def _export_kdenlive(timeline: otio.schema.Timeline, version: str) -> str:
    root = ET.Element(
        "mlt",
        {
            "LC_NUMERIC": "C",
            "producer": "main_bin",
            "title": "OpenClaw Media Timeline",
            "version": version,
        },
    )
    playlist = ET.SubElement(root, "playlist", {"id": "playlist0"})
    producer_index = 0
    for item in timeline.tracks[0]:
        duration = item.duration().to_seconds()
        if isinstance(item, otio.schema.Gap):
            ET.SubElement(playlist, "blank", {"length": _clock(duration)})
            continue
        if not isinstance(item, otio.schema.Clip):
            continue
        producer_id = f"producer{producer_index}"
        producer_index += 1
        producer = ET.SubElement(root, "producer", {"id": producer_id})
        resource = ET.SubElement(producer, "property", {"name": "resource"})
        resource.text = item.media_reference.target_url
        clip_name = ET.SubElement(producer, "property", {"name": "kdenlive:clipname"})
        clip_name.text = item.name
        source_range = item.source_range
        assert source_range is not None
        ET.SubElement(
            playlist,
            "entry",
            {
                "duration": _clock(duration),
                "in": _clock(source_range.start_time.to_seconds()),
                "producer": producer_id,
            },
        )
    tractor = ET.SubElement(root, "tractor", {"id": "tractor0"})
    ET.SubElement(tractor, "track", {"producer": "playlist0"})
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"


def _valid_kdenlive(content: str, expected_clips: int) -> bool:
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError):
        return False
    resources = [node.text for node in root.findall("./producer/property[@name='resource']")]
    return (
        root.tag == "mlt"
        and len(root.findall("./playlist/entry")) == expected_clips
        and len(resources) == expected_clips
        and all(_relative_ref(value) for value in resources)
        and root.find("./tractor/track[@producer='playlist0']") is not None
    )


def _empty_kdenlive(status: str, error_code: str | None = None) -> KdenliveExport:
    return KdenliveExport(status, None, None, None, None, error_code)


def build_timeline(
    edl: Iterable[EDLEntry],
    media: Iterable[TimelineMediaDescriptor],
    *,
    kdenlive: KdenliveEnvironment | None = None,
) -> TimelinePlan:
    """Build a validated OTIO timeline and an explicit optional Kdenlive export."""
    try:
        edit_items = list(edl)
        media_items = list(media)
    except Exception:
        edit_items, media_items = [], []
        issues = [TimelineIssue("timeline", None, "invalid_input")]
    else:
        issues = []

    media_by_identity: dict[str, dict[str, TimelineMediaDescriptor]] = {}
    for item in media_items:
        if (
            not isinstance(item, TimelineMediaDescriptor)
            or not _IDENTITY.fullmatch(item.identity_ref)
            or not _relative_ref(item.material_ref)
            or item.kind not in _KINDS
            or not _finite(item.duration_seconds)
            or item.duration_seconds <= 0
        ):
            issues.append(
                TimelineIssue(
                    "media",
                    _safe_ref(getattr(item, "material_ref", None)),
                    "invalid_input",
                )
            )
            continue
        media_by_identity.setdefault(item.identity_ref, {})[item.material_ref] = item

    valid_edits: list[EDLEntry] = []
    for item in edit_items:
        if (
            not isinstance(item, EDLEntry)
            or not _relative_ref(item.edit_id)
            or not _relative_ref(item.shot_id)
            or not _relative_ref(item.material_ref)
            or not _IDENTITY.fullmatch(item.identity_ref)
            or not isinstance(item.sequence, int)
            or isinstance(item.sequence, bool)
            or item.sequence < 0
        ):
            issues.append(
                TimelineIssue("edl", _safe_ref(getattr(item, "edit_id", None)), "invalid_input")
            )
            continue
        valid_edits.append(item)

    duplicate_edit_ids = {
        item.edit_id
        for item in valid_edits
        if sum(other.edit_id == item.edit_id for other in valid_edits) > 1
    }
    duplicate_sequences = {
        item.sequence
        for item in valid_edits
        if sum(other.sequence == item.sequence for other in valid_edits) > 1
    }
    for item in valid_edits:
        if item.edit_id in duplicate_edit_ids or item.sequence in duplicate_sequences:
            issues.append(TimelineIssue("edl", item.edit_id, "invalid_input"))
    valid_edits = [
        item
        for item in valid_edits
        if item.edit_id not in duplicate_edit_ids and item.sequence not in duplicate_sequences
    ]
    valid_edits.sort(key=lambda item: (item.timeline_in_seconds, item.sequence, item.edit_id))

    relinks: list[TimelineRelink] = []
    resolved: dict[str, TimelineMediaDescriptor] = {}
    previous_out = 0.0
    for item in valid_edits:
        edit_ref = item.edit_id
        values = (
            item.timeline_in_seconds,
            item.timeline_out_seconds,
            item.source_in_seconds,
            item.source_out_seconds,
        )
        if (
            not all(_finite(value) for value in values)
            or item.timeline_in_seconds < 0
            or item.timeline_out_seconds <= item.timeline_in_seconds
            or item.source_in_seconds < 0
            or item.source_out_seconds <= item.source_in_seconds
            or not math.isclose(
                item.timeline_out_seconds - item.timeline_in_seconds,
                item.source_out_seconds - item.source_in_seconds,
                abs_tol=1e-6,
            )
        ):
            issues.append(TimelineIssue("edl", edit_ref, "invalid_timing"))
            if (
                _finite(item.timeline_in_seconds)
                and _finite(item.timeline_out_seconds)
                and item.timeline_in_seconds >= 0
                and item.timeline_out_seconds > item.timeline_in_seconds
            ):
                previous_out = max(previous_out, item.timeline_out_seconds)
            continue
        if item.timeline_in_seconds < previous_out:
            issues.append(TimelineIssue("edl", edit_ref, "invalid_timing"))
            previous_out = max(previous_out, item.timeline_out_seconds)
            continue
        previous_out = item.timeline_out_seconds
        candidates = media_by_identity.get(item.identity_ref, {})
        candidate_refs = tuple(sorted(candidates))
        if not candidates:
            relinks.append(
                TimelineRelink(
                    edit_ref,
                    item.identity_ref,
                    item.material_ref,
                    None,
                    "missing",
                    (),
                )
            )
            issues.append(TimelineIssue("edl", edit_ref, "missing_media"))
            continue
        if len(candidates) > 1:
            relinks.append(
                TimelineRelink(
                    edit_ref,
                    item.identity_ref,
                    item.material_ref,
                    None,
                    "ambiguous",
                    candidate_refs,
                )
            )
            issues.append(TimelineIssue("edl", edit_ref, "relink_ambiguous"))
            continue
        selected = next(iter(candidates.values()))
        if item.source_out_seconds > selected.duration_seconds:
            relinks.append(
                TimelineRelink(
                    edit_ref,
                    item.identity_ref,
                    item.material_ref,
                    selected.material_ref,
                    "resolved",
                    candidate_refs,
                )
            )
            issues.append(TimelineIssue("edl", edit_ref, "invalid_timing"))
            continue
        resolved[item.edit_id] = selected
        relinks.append(
            TimelineRelink(
                edit_ref,
                item.identity_ref,
                item.material_ref,
                selected.material_ref,
                "unchanged" if item.material_ref == selected.material_ref else "relinked",
                candidate_refs,
            )
        )

    if kdenlive is not None and (
        not isinstance(kdenlive, KdenliveEnvironment)
        or not isinstance(kdenlive.available, bool)
        or (
            kdenlive.available
            and (not isinstance(kdenlive.version, str) or not _VERSION.fullmatch(kdenlive.version))
        )
        or (not kdenlive.available and kdenlive.version is not None)
    ):
        issues.append(TimelineIssue("kdenlive", None, "invalid_input"))

    issues = sorted(set(issues), key=lambda issue: (issue.scope, issue.ref or "", issue.error_code))
    error_codes = tuple(sorted({issue.error_code for issue in issues}))
    if issues:
        export = _empty_kdenlive("not_generated")
        validation = TimelineValidation(
            "failed",
            error_codes,
            (),
            False,
            export.status,
            None,
            len(edit_items),
            len(media_items),
        )
        handoff = TimelineHandoff(
            "media.edit.timeline.handoff.v1",
            None,
            None,
            "media-relink.json",
            "timeline-validation.json",
            "Resolve validation errors before opening an editor.",
        )
        return TimelinePlan("failed", None, tuple(relinks), export, handoff, validation, tuple(issues))

    ordered_edits = tuple(valid_edits)
    try:
        project_otio = _build_otio(ordered_edits, resolved)
        round_trip = _read_otio(project_otio)
    except Exception:
        project_otio, round_trip = None, None
    if project_otio is None or round_trip is None:
        issue = TimelineIssue("otio", None, "otio_round_trip_failed")
        export = _empty_kdenlive("not_generated")
        validation = TimelineValidation(
            "failed",
            (issue.error_code,),
            (),
            False,
            export.status,
            None,
            len(edit_items),
            len(media_items),
        )
        handoff = TimelineHandoff(
            "media.edit.timeline.handoff.v1",
            None,
            None,
            "media-relink.json",
            "timeline-validation.json",
            "Resolve validation errors before opening an editor.",
        )
        return TimelinePlan("failed", None, tuple(relinks), export, handoff, validation, (issue,))

    warnings: tuple[str, ...] = ()
    if kdenlive is None:
        export = _empty_kdenlive("not_requested")
        kdenlive_valid: bool | None = None
    elif not kdenlive.available:
        export = _empty_kdenlive("unavailable", "kdenlive_unavailable")
        warnings = ("kdenlive_unavailable",)
        kdenlive_valid = None
    else:
        assert kdenlive.version is not None
        content = _export_kdenlive(round_trip, kdenlive.version)
        kdenlive_valid = _valid_kdenlive(content, len(ordered_edits))
        if not kdenlive_valid:
            issue = TimelineIssue("kdenlive", None, "kdenlive_export_invalid")
            export = _empty_kdenlive("failed", issue.error_code)
            validation = TimelineValidation(
                "failed",
                (issue.error_code,),
                (),
                True,
                export.status,
                False,
                len(edit_items),
                len(media_items),
            )
            handoff = TimelineHandoff(
                "media.edit.timeline.handoff.v1",
                "project.otio",
                None,
                "media-relink.json",
                "timeline-validation.json",
                "Open project.otio; the optional editor export failed validation.",
            )
            return TimelinePlan(
                "partial",
                project_otio,
                tuple(relinks),
                export,
                handoff,
                validation,
                (issue,),
            )
        export = KdenliveExport(
            "exported",
            "project.kdenlive",
            "application/xml",
            content,
            kdenlive.version,
            None,
        )

    handoff = TimelineHandoff(
        "media.edit.timeline.handoff.v1",
        "project.otio",
        export.artifact_ref,
        "media-relink.json",
        "timeline-validation.json",
        "Open project.otio as the timeline fact; use project.kdenlive only when exported.",
    )
    validation = TimelineValidation(
        "ok",
        (),
        warnings,
        True,
        export.status,
        kdenlive_valid,
        len(edit_items),
        len(media_items),
    )
    return TimelinePlan(
        "ok",
        project_otio,
        tuple(relinks),
        export,
        handoff,
        validation,
        (),
    )
