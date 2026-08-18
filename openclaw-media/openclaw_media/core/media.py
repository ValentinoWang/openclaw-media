from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

VIDEO_EXTENSIONS = frozenset({".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"})
AUDIO_EXTENSIONS = frozenset({".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"})
IMAGE_EXTENSIONS = frozenset({".avif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
XMP_EXTENSIONS = frozenset({".xmp"})
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS | XMP_EXTENSIONS

ProbeRunner = Callable[[Path], Any]


class MediaProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class StreamInfo:
    index: int
    kind: str
    codec: str | None
    width: int | None = None
    height: int | None = None
    sample_rate: int | None = None
    channels: int | None = None


@dataclass(frozen=True)
class ProbeResult:
    status: str
    duration_seconds: float | None
    bit_rate: int | None
    has_audio: bool
    has_video: bool
    streams: tuple[StreamInfo, ...]
    error_code: str | None = None


@dataclass(frozen=True)
class MediaFile:
    ref: str
    kind: str
    extension: str
    size_bytes: int
    size_class: str
    sha256: str
    probe: ProbeResult | None


@dataclass(frozen=True)
class MediaScanResult:
    status: str
    files: tuple[MediaFile, ...]
    counts: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any, cast: Callable[[Any], Any]) -> Any | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _default_probe_runner(path: Path) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise MediaProbeError("probe_failed") from exc
    if not isinstance(payload, Mapping):
        raise MediaProbeError("probe_failed")
    return payload


def probe_media(path: Path, *, runner: ProbeRunner | None = None) -> ProbeResult:
    try:
        payload = (runner or _default_probe_runner)(path)
        if not isinstance(payload, Mapping):
            return ProbeResult(
                status="corrupt",
                duration_seconds=None,
                bit_rate=None,
                has_audio=False,
                has_video=False,
                streams=(),
                error_code="probe_invalid",
            )
        raw_streams = payload.get("streams", [])
        if not isinstance(raw_streams, list):
            raise MediaProbeError("probe_failed")
        streams = tuple(
            StreamInfo(
                index=int(stream.get("index", index)),
                kind=str(stream.get("codec_type", "unknown")),
                codec=stream.get("codec_name"),
                width=_number(stream.get("width"), int),
                height=_number(stream.get("height"), int),
                sample_rate=_number(stream.get("sample_rate"), int),
                channels=_number(stream.get("channels"), int),
            )
            for index, stream in enumerate(raw_streams)
            if isinstance(stream, Mapping)
        )
        raw_format = payload.get("format", {})
        media_format = raw_format if isinstance(raw_format, Mapping) else {}
        return ProbeResult(
            status="ok",
            duration_seconds=_number(media_format.get("duration"), float),
            bit_rate=_number(media_format.get("bit_rate"), int),
            has_audio=any(stream.kind == "audio" for stream in streams),
            has_video=any(stream.kind == "video" for stream in streams),
            streams=streams,
        )
    except (MediaProbeError, OSError, TypeError, ValueError, KeyError):
        return ProbeResult(
            status="corrupt",
            duration_seconds=None,
            bit_rate=None,
            has_audio=False,
            has_video=False,
            streams=(),
            error_code="probe_failed",
        )


def _kind(extension: str) -> str:
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    return "xmp"


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_media(
    root: Path,
    *,
    probe_runner: ProbeRunner | None = None,
    large_file_bytes: int = 1024 * 1024 * 1024,
) -> MediaScanResult:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("media root must be a directory")
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    files: list[MediaFile] = []
    counts = {"audio": 0, "image": 0, "video": 0, "xmp": 0}
    for path in paths:
        extension = path.suffix.lower()
        kind = _kind(extension)
        counts[kind] += 1
        size_bytes = path.stat().st_size
        files.append(
            MediaFile(
                ref=path.relative_to(root).as_posix(),
                kind=kind,
                extension=extension,
                size_bytes=size_bytes,
                size_class="large" if size_bytes >= large_file_bytes else "small",
                sha256=_digest(path),
                probe=probe_media(path, runner=probe_runner) if kind in {"audio", "video"} else None,
            )
        )
    return MediaScanResult(status="ok", files=tuple(files), counts=counts)
