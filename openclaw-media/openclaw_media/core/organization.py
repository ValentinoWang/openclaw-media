from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

from .media import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, XMP_EXTENSIONS, MediaFile

_SHA256 = re.compile(r"[0-9a-f]{64}")
_KINDS = {"video": "video", "audio": "audio", "image": "image", "xmp": "sidecar"}
_EXTENSIONS = {
    "video": VIDEO_EXTENSIONS,
    "audio": AUDIO_EXTENSIONS,
    "image": IMAGE_EXTENSIONS,
    "xmp": XMP_EXTENSIONS,
}
_WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")


@dataclass(frozen=True)
class OrganizationMapping:
    source_ref: str
    destination_ref: str
    kind: str
    sha256: str
    identity_ref: str
    decision: str
    duplicate_of: str | None = None


@dataclass(frozen=True)
class OrganizationFailure:
    source_ref: str | None
    error_code: str


@dataclass(frozen=True)
class OrganizationPlan:
    status: str
    mappings: tuple[OrganizationMapping, ...]
    failures: tuple[OrganizationFailure, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ref(value: str) -> PurePosixPath | None:
    if not isinstance(value, str) or "\\" in value or _WINDOWS_ABSOLUTE.match(value):
        return None
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} or "\x00" in part for part in path.parts)
        or path.as_posix() != value
    ):
        return None
    return path


def _sort_key(item: object) -> tuple[str, str, str, str, int]:
    if not isinstance(item, MediaFile):
        return ("", "", "", "", -1)
    return (
        item.ref if isinstance(item.ref, str) else "",
        item.kind if isinstance(item.kind, str) else "",
        item.extension if isinstance(item.extension, str) else "",
        item.sha256 if isinstance(item.sha256, str) else "",
        item.size_bytes if isinstance(item.size_bytes, int) and not isinstance(item.size_bytes, bool) else -1,
    )


def _valid_item(item: object, source: PurePosixPath | None) -> bool:
    if not isinstance(item, MediaFile) or source is None or item.kind not in _KINDS:
        return False
    if not isinstance(item.extension, str) or item.extension != item.extension.lower():
        return False
    if source.suffix.lower() != item.extension or item.extension not in _EXTENSIONS[item.kind]:
        return False
    if not isinstance(item.size_bytes, int) or isinstance(item.size_bytes, bool) or item.size_bytes < 0:
        return False
    return isinstance(item.sha256, str) and _SHA256.fullmatch(item.sha256) is not None


def plan_media_organization(files: Iterable[MediaFile]) -> OrganizationPlan:
    """Return a deterministic, descriptor-only organization plan without filesystem writes."""
    mappings: list[OrganizationMapping] = []
    failures: list[OrganizationFailure] = []
    identities: dict[str, OrganizationMapping] = {}
    destinations: dict[str, str] = {}
    try:
        candidates = sorted(files, key=_sort_key)
    except (TypeError, ValueError, OSError):
        return OrganizationPlan("failed", (), (OrganizationFailure(None, "invalid_input"),))

    for item in candidates:
        source = _ref(item.ref) if isinstance(item, MediaFile) else None
        if not _valid_item(item, source):
            failures.append(OrganizationFailure(source.as_posix() if source else None, "invalid_input"))
            continue
        assert source is not None
        if item.probe is not None and item.probe.status != "ok":
            failures.append(OrganizationFailure(source.as_posix(), "corrupt_input"))
            continue
        duplicate = identities.get(item.sha256)
        if duplicate:
            mapping = OrganizationMapping(source.as_posix(), duplicate.destination_ref, item.kind, item.sha256, f"sha256:{item.sha256}", "duplicate", duplicate.source_ref)
        else:
            target = PurePosixPath("organized", _KINDS[item.kind], source.name)
            key = target.as_posix().casefold()
            decision = "planned"
            if key in destinations:
                target = target.with_name(f"{target.stem}--{item.sha256[:12]}{target.suffix.lower()}")
                key = target.as_posix().casefold()
                decision = "renamed_collision"
            if key in destinations:
                failures.append(OrganizationFailure(source.as_posix(), "collision_unresolved"))
                continue
            mapping = OrganizationMapping(source.as_posix(), target.as_posix(), item.kind, item.sha256, f"sha256:{item.sha256}", decision)
            identities[item.sha256] = mapping
            destinations[key] = item.sha256
        mappings.append(mapping)
    status = "ok" if not failures else ("failed" if not mappings else "partial")
    return OrganizationPlan(status, tuple(mappings), tuple(failures))
