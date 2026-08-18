"""Single canonical FFmpeg execution path for an accepted render manifest."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import os
import subprocess
import tempfile
from typing import Any, Callable, Mapping
from pathlib import PurePosixPath

from .render import RenderManifest


CommandRunner = Callable[[tuple[str, ...]], Any]
ProbeRunner = Callable[[Path], Mapping[str, Any]]


@dataclass(frozen=True)
class RenderExecutionReceipt:
    contract: str
    status: str
    manifest_identity_ref: str
    output_ref: str | None
    video_frames: int | None
    duration: tuple[int, int] | None
    audio_tracks: int | None
    cloud_bytes: int
    receipt_identity_ref: str


@dataclass(frozen=True)
class RenderExecutionResult:
    status: str
    output_ref: str | None
    receipt: RenderExecutionReceipt | None
    error_codes: tuple[str, ...] = ()

    @property
    def cloud_bytes(self) -> int:
        return 0 if self.receipt is None else self.receipt.cloud_bytes

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _failed(manifest: RenderManifest, code: str) -> RenderExecutionResult:
    return RenderExecutionResult("rejected", None, None, (code,))


def _default_runner(command: tuple[str, ...]) -> None:
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _default_probe(path: Path) -> Mapping[str, Any]:
    proc = subprocess.run(
        ("ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return json.loads(proc.stdout)


def _stream_frames(stream: Mapping[str, Any]) -> int | None:
    value = stream.get("nb_read_frames", stream.get("nb_frames"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _duration(probe: Mapping[str, Any]) -> tuple[int, int] | None:
    raw = probe.get("format", {}).get("duration")
    try:
        return Fraction(str(raw)).limit_denominator(1_000_000).numerator, Fraction(str(raw)).limit_denominator(1_000_000).denominator
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def execute_render(
    manifest: RenderManifest,
    sources: Mapping[str, Path],
    workspace: Path,
    *,
    runner: CommandRunner | None = None,
    probe_runner: ProbeRunner | None = None,
    ffmpeg: str = "ffmpeg",
) -> RenderExecutionResult:
    """Execute FFmpeg, validate ffprobe facts, and atomically publish one relative Final."""
    if (
        not isinstance(manifest, RenderManifest)
        or manifest.output.cloud_bytes != 0
        or not isinstance(manifest.output.ref, str)
        or not manifest.output.ref
        or PurePosixPath(manifest.output.ref).is_absolute()
        or "\\" in manifest.output.ref
        or ".." in PurePosixPath(manifest.output.ref).parts
    ):
        return _failed(manifest, "invalid_manifest")
    source_paths: list[Path] = []
    for item in manifest.inputs:
        path = sources.get(item.material_ref)
        if not isinstance(path, Path) or not path.is_file():
            return _failed(manifest, "missing_source")
        source_paths.append(path)
    run = runner or _default_runner
    probe = probe_runner or _default_probe
    workspace = Path(workspace)
    target = workspace / manifest.output.ref
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="render-", dir=workspace) as staging:
            staged = Path(staging) / "final.mp4"
            # U8a carries validated media descriptors; execution consumes those sources in order.
            command = (ffmpeg, "-y", "-i", *[str(path) for path in source_paths], "-c", "copy", str(staged))
            run(command)
            if not staged.is_file() or staged.stat().st_size <= 0:
                return _failed(manifest, "ffmpeg_failed")
            facts = probe(staged)
            if not isinstance(facts, Mapping):
                return _failed(manifest, "output_mismatch")
            streams = tuple(item for item in facts.get("streams", ()) if isinstance(item, Mapping))
            video = tuple(item for item in streams if item.get("codec_type") == "video")
            audio = tuple(item for item in streams if item.get("codec_type") == "audio")
            frames = _stream_frames(video[0]) if video else None
            duration = _duration(facts)
            if (
                frames != manifest.expected_video_frames
                or duration != manifest.duration
                or len(audio) != manifest.expected_audio_tracks
            ):
                return _failed(manifest, "output_mismatch")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            receipt_data = {
                "contract": "media.render.execution.receipt.v1",
                "status": "ok",
                "manifest_identity_ref": manifest.identity_ref,
                "output_ref": manifest.output.ref,
                "video_frames": frames,
                "duration": duration,
                "audio_tracks": len(audio),
                "cloud_bytes": 0,
            }
            receipt = RenderExecutionReceipt(**receipt_data, receipt_identity_ref=_digest(receipt_data))
            return RenderExecutionResult("ok", manifest.output.ref, receipt)
    except Exception:
        return _failed(manifest, "ffmpeg_failed")
