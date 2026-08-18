"""Canonical local preprocessing for one verified workspace CAS blob."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
from typing import Callable

from .workspace import LocalWorkspace


CommandRunner = Callable[[tuple[str, ...]], None]
_RESERVED_OUTPUT_ROOTS = {"blobs", "tmp", "workspace.sqlite3"}


class _CorruptOutput(Exception):
    """Internal marker whose details never cross the public boundary."""


@dataclass(frozen=True)
class PreprocessArtifact:
    ref: str
    kind: str
    mime_type: str
    sha256: str
    size_bytes: int
    timestamp_seconds: float | None = None


@dataclass(frozen=True)
class LocalMediaManifest:
    status: str
    source_ref: str
    proxy: PreprocessArtifact | None
    keyframes: tuple[PreprocessArtifact, ...]
    audio: PreprocessArtifact | None
    error_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _manual(source_ref: object, code: str) -> LocalMediaManifest:
    safe_ref = source_ref if isinstance(source_ref, str) else ""
    return LocalMediaManifest("manual", safe_ref, None, (), None, code)


def _output_reference(value: object) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return None
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] in _RESERVED_OUTPUT_ROOTS
        or path.parts[0].endswith(":")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        return None
    return path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(
    path: Path,
    ref: str,
    kind: str,
    mime_type: str,
    timestamp_seconds: float | None = None,
) -> PreprocessArtifact:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
            raise _CorruptOutput
        digest = _digest(path)
    except OSError as exc:
        raise _CorruptOutput from exc
    return PreprocessArtifact(
        ref=ref,
        kind=kind,
        mime_type=mime_type,
        sha256=f"sha256:{digest}",
        size_bytes=metadata.st_size,
        timestamp_seconds=timestamp_seconds,
    )


def _default_runner(command: tuple[str, ...]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("preprocess_failed") from exc


def _replace_directory(staging: Path, destination: Path, temporary_root: Path) -> bool:
    backup = temporary_root / f"previous-{staging.name}"
    previous_moved = False
    new_moved = False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                return False
            os.replace(destination, backup)
            previous_moved = True
        os.replace(staging, destination)
        new_moved = True
    except OSError:
        try:
            if new_moved and destination.exists():
                shutil.rmtree(destination)
            if previous_moved and backup.exists():
                os.replace(backup, destination)
        except OSError:
            pass
        return False
    if backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError:
            pass
    return True


def preprocess_media(
    workspace: LocalWorkspace,
    source_ref: str,
    output_ref: str,
    *,
    duration_seconds: float,
    has_audio: bool,
    runner: CommandRunner | None = None,
    keyframe_count: int = 3,
) -> LocalMediaManifest:
    """Create proxy, uniform keyframes, and optional WAV from a verified CAS blob."""

    output = _output_reference(output_ref)
    if output is None:
        return _manual(source_ref, "invalid_output_ref")
    if not isinstance(workspace, LocalWorkspace):
        return _manual(source_ref, "invalid_workspace")
    verified = workspace.verify_blob(source_ref)
    if verified.status != "completed":
        return _manual(source_ref, verified.code)
    if (
        not isinstance(duration_seconds, (int, float))
        or isinstance(duration_seconds, bool)
        or not math.isfinite(duration_seconds)
        or duration_seconds <= 0
        or not isinstance(has_audio, bool)
        or not isinstance(keyframe_count, int)
        or isinstance(keyframe_count, bool)
        or keyframe_count <= 0
        or keyframe_count > 1000
    ):
        return _manual(source_ref, "invalid_descriptor")

    root = workspace.root
    source_path = root.joinpath(*PurePosixPath(source_ref).parts)
    temporary_root = root / "tmp"
    execute = runner or _default_runner
    staging: Path | None = None
    try:
        staging = Path(tempfile.mkdtemp(prefix="preprocess-", dir=temporary_root))
        proxy_path = staging / "proxy.mp4"
        proxy_path.parent.mkdir(parents=True, exist_ok=True)
        execute(
            (
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source_path), "-map", "0:v:0", "-vf", "scale=1280:-2",
                "-c:v", "libx264", "-preset", "fast", "-crf", "28", "-an",
                str(proxy_path),
            )
        )
        proxy = _artifact(proxy_path, f"{output.as_posix()}/proxy.mp4", "proxy", "video/mp4")

        keyframes: list[PreprocessArtifact] = []
        for index in range(keyframe_count):
            timestamp = round(duration_seconds * (index + 0.5) / keyframe_count, 6)
            frame_path = staging / "keyframes" / f"frame-{index + 1:04d}.jpg"
            frame_path.parent.mkdir(parents=True, exist_ok=True)
            execute(
                (
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{timestamp:.6f}", "-i", str(source_path), "-frames:v", "1",
                    str(frame_path),
                )
            )
            keyframes.append(
                _artifact(
                    frame_path,
                    f"{output.as_posix()}/keyframes/{frame_path.name}",
                    "keyframe",
                    "image/jpeg",
                    timestamp,
                )
            )

        audio: PreprocessArtifact | None = None
        status = "completed"
        error_code = None
        if has_audio:
            audio_path = staging / "audio" / "source.wav"
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            execute(
                (
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(source_path), "-map", "0:a:0", "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1", str(audio_path),
                )
            )
            audio = _artifact(
                audio_path, f"{output.as_posix()}/audio/source.wav", "audio", "audio/wav"
            )
        else:
            status = "partial"
            error_code = "no_audio"

        if not _replace_directory(staging, root.joinpath(*output.parts), temporary_root):
            return _manual(source_ref, "output_conflict")
        staging = None
        return LocalMediaManifest(
            status, source_ref, proxy, tuple(keyframes), audio, error_code
        )
    except _CorruptOutput:
        return _manual(source_ref, "corrupt_output")
    except Exception:
        return _manual(source_ref, "preprocess_failed")
    finally:
        if staging is not None and staging.exists():
            try:
                shutil.rmtree(staging)
            except OSError:
                pass
