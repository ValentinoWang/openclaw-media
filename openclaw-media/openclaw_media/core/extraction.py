from __future__ import annotations

import hashlib
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .refs import ref_path as _ref_path

CommandRunner = Callable[[tuple[str, ...]], None]


@dataclass(frozen=True)
class ExtractionArtifact:
    ref: str
    kind: str
    mime_type: str
    size_bytes: int
    sha256: str
    mode: str
    timestamp_seconds: float | None = None
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    source_ref: str
    artifacts: tuple[ExtractionArtifact, ...]
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _default_runner(command: tuple[str, ...]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError, OSError) as exc:
        raise RuntimeError("extraction_failed") from exc


def _relative_path(ref: str, *, field: str) -> PurePosixPath:
    path = _ref_path(ref)
    if path is None:
        raise ValueError(f"{field} must be a normalized relative reference")
    return path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_times(duration_seconds: float, count: int) -> tuple[float, ...]:
    if count <= 0:
        return ()
    return tuple(round(duration_seconds * (index + 0.5) / count, 6) for index in range(count))


def _dense_times(duration_seconds: float, interval_seconds: float) -> tuple[float, ...]:
    if interval_seconds <= 0:
        return ()
    count = max(1, int((duration_seconds - 1e-9) // interval_seconds) + 1)
    return tuple(round(index * interval_seconds, 6) for index in range(count))


def _descriptor(
    root: Path,
    path: Path,
    *,
    kind: str,
    mime_type: str,
    mode: str,
    timestamp_seconds: float | None = None,
    duration_seconds: float | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
) -> ExtractionArtifact:
    return ExtractionArtifact(
        ref=path.relative_to(root).as_posix(),
        kind=kind,
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        sha256=_digest(path),
        mode=mode,
        timestamp_seconds=timestamp_seconds,
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        channels=channels,
    )


def extract_media_evidence(
    root: Path,
    source_ref: str,
    output_ref: str,
    *,
    duration_seconds: float,
    has_audio: bool,
    runner: CommandRunner | None = None,
    uniform_count: int = 3,
    dense_interval_seconds: float = 2.0,
    audio_sample_rate: int = 16000,
    audio_channels: int = 1,
) -> ExtractionResult:
    """Extract deterministic JPEG evidence and a descriptor-only WAV artifact."""
    source_rel = _relative_path(source_ref, field="source_ref")
    output_rel = _relative_path(output_ref, field="output_ref")
    if (
        not math.isfinite(duration_seconds)
        or duration_seconds <= 0
        or uniform_count < 0
        or not math.isfinite(dense_interval_seconds)
        or dense_interval_seconds <= 0
    ):
        return ExtractionResult("failed", source_rel.as_posix(), (), "corrupt_input")
    if audio_sample_rate <= 0 or audio_channels <= 0:
        raise ValueError("audio settings must be positive")

    execute = runner or _default_runner
    artifacts: list[ExtractionArtifact] = []
    generated: list[Path] = []

    try:
        workspace = root.resolve(strict=True)
        source = workspace.joinpath(*source_rel.parts)
        if not source.is_file():
            return ExtractionResult("failed", source_rel.as_posix(), (), "corrupt_input")
        output = workspace.joinpath(*output_rel.parts)
        selections = (
            ("uniform", _frame_times(duration_seconds, uniform_count)),
            ("dense", _dense_times(duration_seconds, dense_interval_seconds)),
        )
        for mode, timestamps in selections:
            frame_dir = output / "keyframes" / mode
            frame_dir.mkdir(parents=True, exist_ok=True)
            for index, timestamp in enumerate(timestamps, start=1):
                target = frame_dir / f"frame-{index:04d}.jpg"
                generated.append(target)
                execute(
                    (
                        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", f"{timestamp:.6f}", "-i", str(source), "-frames:v", "1",
                        "-q:v", "2", str(target),
                    )
                )
                artifacts.append(
                    _descriptor(
                        workspace,
                        target,
                        kind="keyframe",
                        mime_type="image/jpeg",
                        mode=mode,
                        timestamp_seconds=timestamp,
                    )
                )

        error_code = None
        status = "ok"
        if has_audio:
            target = output / "audio" / "source.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            generated.append(target)
            execute(
                (
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(source), "-map", "0:a:0", "-vn", "-acodec", "pcm_s16le",
                    "-ar", str(audio_sample_rate), "-ac", str(audio_channels), str(target),
                )
            )
            artifacts.append(
                _descriptor(
                    workspace,
                    target,
                    kind="audio",
                    mime_type="audio/wav",
                    mode="wav",
                    duration_seconds=duration_seconds,
                    sample_rate=audio_sample_rate,
                    channels=audio_channels,
                )
            )
        else:
            status = "partial"
            error_code = "no_audio"
        return ExtractionResult(status, source_rel.as_posix(), tuple(artifacts), error_code)
    except Exception:
        for path in generated:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return ExtractionResult("failed", source_rel.as_posix(), (), "corrupt_input")
