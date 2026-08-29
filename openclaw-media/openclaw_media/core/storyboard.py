from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .refs import relative_ref as _relative_ref

_SHA256 = re.compile(r"[0-9a-f]{64}")
_KINDS = {"audio", "image", "video"}


@dataclass(frozen=True)
class MaterialDescriptor:
    ref: str
    kind: str
    sha256: str
    duration_seconds: float
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ShotRequest:
    shot_id: str
    sequence: int
    duration_seconds: float
    source_start_seconds: float = 0.0
    required_tags: tuple[str, ...] = ()
    preferred_tags: tuple[str, ...] = ()
    accepted_kinds: tuple[str, ...] = ("video", "image")


@dataclass(frozen=True)
class MaterialMatch:
    shot_id: str
    status: str
    error_code: str | None
    material_ref: str | None
    identity_ref: str | None
    candidate_identity_refs: tuple[str, ...]
    score: int | None


@dataclass(frozen=True)
class StoryboardEntry:
    shot_id: str
    sequence: int
    timeline_in_seconds: float
    timeline_out_seconds: float
    duration_seconds: float
    match_status: str
    error_code: str | None
    material_ref: str | None
    identity_ref: str | None


@dataclass(frozen=True)
class EDLEntry:
    edit_id: str
    shot_id: str
    sequence: int
    timeline_in_seconds: float
    timeline_out_seconds: float
    source_in_seconds: float
    source_out_seconds: float
    material_ref: str
    identity_ref: str


@dataclass(frozen=True)
class LocalAssetReference:
    identity_ref: str
    material_ref: str
    duplicate_refs: tuple[str, ...]
    kind: str
    sha256: str
    duration_seconds: float


@dataclass(frozen=True)
class StoryboardFailure:
    scope: str
    ref: str | None
    error_code: str


@dataclass(frozen=True)
class StoryboardPlan:
    status: str
    matches: tuple[MaterialMatch, ...]
    storyboard: tuple[StoryboardEntry, ...]
    edl: tuple[EDLEntry, ...]
    local_assets: tuple[LocalAssetReference, ...]
    failures: tuple[StoryboardFailure, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _CanonicalMaterial:
    material: MaterialDescriptor
    duplicate_refs: tuple[str, ...]
    tags: frozenset[str]

    @property
    def identity_ref(self) -> str:
        return f"sha256:{self.material.sha256}"


def _label(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    if any(character.isspace() or character in "/\\\x00" for character in value):
        return None
    return value


def _seconds(value: object, *, positive: bool) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        return None
    return round(number, 6)


def _tags(value: object) -> frozenset[str] | None:
    if not isinstance(value, tuple):
        return None
    if any(not isinstance(tag, str) or not tag or "\x00" in tag or tag != tag.strip() for tag in value):
        return None
    tags = frozenset(value)
    return tags if len(tags) == len(value) else None


def _material_key(item: MaterialDescriptor) -> tuple[str, str, str, float, tuple[str, ...]]:
    return (item.sha256, item.ref, item.kind, float(item.duration_seconds), item.tags)


def _valid_material(item: object) -> tuple[MaterialDescriptor, frozenset[str]] | None:
    if not isinstance(item, MaterialDescriptor) or _relative_ref(item.ref) is None:
        return None
    duration = _seconds(item.duration_seconds, positive=True)
    tags = _tags(item.tags)
    if item.kind not in _KINDS or _SHA256.fullmatch(item.sha256) is None or duration is None or tags is None:
        return None
    return MaterialDescriptor(item.ref, item.kind, item.sha256, duration, tuple(sorted(tags))), tags


def _canonical_materials(items: list[object]) -> tuple[list[_CanonicalMaterial], list[StoryboardFailure]]:
    valid: list[tuple[MaterialDescriptor, frozenset[str]]] = []
    failures: list[StoryboardFailure] = []
    for item in items:
        checked = _valid_material(item)
        if checked is None:
            safe_ref = _relative_ref(item.ref) if isinstance(item, MaterialDescriptor) else None
            failures.append(StoryboardFailure("material", safe_ref, "invalid_input"))
        else:
            valid.append(checked)

    conflicting_refs = {
        ref
        for ref in {item.ref for item, _ in valid}
        if len({item.sha256 for item, _ in valid if item.ref == ref}) > 1
    }
    for ref in sorted(conflicting_refs):
        failures.append(StoryboardFailure("material", ref, "invalid_input"))
    valid = [(item, tags) for item, tags in valid if item.ref not in conflicting_refs]

    canonical: list[_CanonicalMaterial] = []
    for digest in sorted({item.sha256 for item, _ in valid}):
        group = sorted(((item, tags) for item, tags in valid if item.sha256 == digest), key=lambda pair: _material_key(pair[0]))
        signatures = {(item.kind, item.duration_seconds, tags) for item, tags in group}
        if len(signatures) != 1:
            failures.append(StoryboardFailure("material", f"sha256:{digest}", "invalid_input"))
            continue
        item, tags = group[0]
        refs = tuple(sorted({candidate.ref for candidate, _ in group}))
        canonical.append(_CanonicalMaterial(item, tuple(ref for ref in refs if ref != item.ref), tags))
    return canonical, failures


def _valid_shot(item: object) -> ShotRequest | None:
    if not isinstance(item, ShotRequest) or _label(item.shot_id) is None:
        return None
    if not isinstance(item.sequence, int) or isinstance(item.sequence, bool) or item.sequence < 0:
        return None
    duration = _seconds(item.duration_seconds, positive=True)
    source_start = _seconds(item.source_start_seconds, positive=False)
    required = _tags(item.required_tags)
    preferred = _tags(item.preferred_tags)
    if duration is None or source_start is None or required is None or preferred is None:
        return None
    if not isinstance(item.accepted_kinds, tuple) or not item.accepted_kinds:
        return None
    kinds = frozenset(item.accepted_kinds)
    if len(kinds) != len(item.accepted_kinds) or not kinds.issubset(_KINDS):
        return None
    return ShotRequest(
        item.shot_id,
        item.sequence,
        duration,
        source_start,
        tuple(sorted(required)),
        tuple(sorted(preferred)),
        tuple(sorted(kinds)),
    )


def _match(shot: ShotRequest, materials: list[_CanonicalMaterial]) -> MaterialMatch:
    required = frozenset(shot.required_tags)
    preferred = frozenset(shot.preferred_tags)
    eligible = [
        material
        for material in materials
        if material.material.kind in shot.accepted_kinds and required.issubset(material.tags)
    ]
    if not eligible:
        return MaterialMatch(shot.shot_id, "unmatched", "unmatched", None, None, (), None)

    timed = [
        material
        for material in eligible
        if shot.source_start_seconds + shot.duration_seconds <= material.material.duration_seconds
    ]
    if not timed:
        identities = tuple(sorted(material.identity_ref for material in eligible))
        return MaterialMatch(shot.shot_id, "invalid", "invalid_timing", None, None, identities, None)

    scored = [(len(preferred.intersection(material.tags)), material) for material in timed]
    best_score = max(score for score, _ in scored)
    best = sorted((material for score, material in scored if score == best_score), key=lambda material: material.identity_ref)
    if len(best) != 1:
        identities = tuple(material.identity_ref for material in best)
        return MaterialMatch(shot.shot_id, "ambiguous", "ambiguous", None, None, identities, best_score)
    selected = best[0]
    return MaterialMatch(
        shot.shot_id,
        "matched",
        None,
        selected.material.ref,
        selected.identity_ref,
        (selected.identity_ref,),
        best_score,
    )


def plan_storyboard(materials: Iterable[MaterialDescriptor], shots: Iterable[ShotRequest]) -> StoryboardPlan:
    """Match structured descriptors and emit deterministic Storyboard/EDL decisions."""
    try:
        material_items = list(materials)
        shot_items = list(shots)
    except Exception:
        failure = StoryboardFailure("plan", None, "invalid_input")
        return StoryboardPlan("failed", (), (), (), (), (failure,))

    canonical, failures = _canonical_materials(material_items)
    valid_shots: list[ShotRequest] = []
    for item in shot_items:
        checked = _valid_shot(item)
        if checked is None:
            safe_id = _label(item.shot_id) if isinstance(item, ShotRequest) else None
            failures.append(StoryboardFailure("shot", safe_id, "invalid_input"))
        else:
            valid_shots.append(checked)

    duplicate_ids = {
        shot_id
        for shot_id in {shot.shot_id for shot in valid_shots}
        if sum(shot.shot_id == shot_id for shot in valid_shots) > 1
    }
    for shot_id in sorted(duplicate_ids):
        failures.append(StoryboardFailure("shot", shot_id, "invalid_input"))
    valid_shots = sorted(
        (shot for shot in valid_shots if shot.shot_id not in duplicate_ids),
        key=lambda shot: (shot.sequence, shot.shot_id),
    )

    matches: list[MaterialMatch] = []
    storyboard: list[StoryboardEntry] = []
    edl: list[EDLEntry] = []
    used_identities: set[str] = set()
    timeline_in = 0.0
    for shot in valid_shots:
        match = _match(shot, canonical)
        timeline_out = round(timeline_in + shot.duration_seconds, 6)
        matches.append(match)
        storyboard.append(
            StoryboardEntry(
                shot.shot_id,
                shot.sequence,
                timeline_in,
                timeline_out,
                shot.duration_seconds,
                match.status,
                match.error_code,
                match.material_ref,
                match.identity_ref,
            )
        )
        if match.status == "matched":
            assert match.material_ref is not None and match.identity_ref is not None
            source_out = round(shot.source_start_seconds + shot.duration_seconds, 6)
            edl.append(
                EDLEntry(
                    f"edit-{len(edl) + 1:04d}",
                    shot.shot_id,
                    shot.sequence,
                    timeline_in,
                    timeline_out,
                    shot.source_start_seconds,
                    source_out,
                    match.material_ref,
                    match.identity_ref,
                )
            )
            used_identities.add(match.identity_ref)
        timeline_in = timeline_out

    local_assets = tuple(
        LocalAssetReference(
            material.identity_ref,
            material.material.ref,
            material.duplicate_refs,
            material.material.kind,
            material.material.sha256,
            material.material.duration_seconds,
        )
        for material in canonical
        if material.identity_ref in used_identities
    )
    has_errors = bool(failures) or any(match.status != "matched" for match in matches)
    matched_count = sum(match.status == "matched" for match in matches)
    status = "ok" if not has_errors else ("partial" if matched_count else "failed")
    return StoryboardPlan(status, tuple(matches), tuple(storyboard), tuple(edl), local_assets, tuple(failures))
