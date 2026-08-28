from __future__ import annotations

import base64
import math
import mimetypes
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .storyboard_window import parse_explicit_analysis_time_range


class NoRealMediaError(RuntimeError):
    pass


class MediaProcessingError(RuntimeError):
    pass


VIDEO_ANALYSIS_MAX_SECONDS = 60
STORYBOARD_OPENING_SECONDS = 5
STORYBOARD_POST_OPENING_STEP_SECONDS = 3


@dataclass(frozen=True)
class MediaEvidence:
    media_type: str
    parts: list[dict[str, Any]]
    evidence_paths: list[str]
    evidence_assets: list[dict[str, str]]
    cleanup_paths: list[str]
    audio_path: str
    preview_path: str


def _image_part(path: str) -> dict[str, Any]:
    p = Path(path)
    ensure_real_file(str(p), "视觉证据")
    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return {"image_data": {"mime_type": mime, "data": data, "path": str(p)}}


def _asset_id(prefix: str, index: int) -> str:
    return f"{prefix}_{index:03d}"


def _copy_asset(src: str, out_dir: str, asset_id: str) -> str:
    source = Path(ensure_real_file(src, "视觉证据"))
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{asset_id}{source.suffix.lower() or '.jpg'}"
    shutil.copyfile(source, target)
    return ensure_real_file(str(target), "视觉证据资产")


def ensure_real_file(path: str | None, label: str) -> str:
    if not path:
        raise NoRealMediaError(f"{label}不存在")
    p = Path(path)
    if not p.exists() or not p.is_file() or p.stat().st_size <= 0:
        raise NoRealMediaError(f"{label}不是有效文件：{path}")
    return str(p)


def ensure_real_files(paths: list[str] | None, label: str) -> list[str]:
    checked = [ensure_real_file(str(path), label) for path in (paths or []) if path]
    if not checked:
        raise NoRealMediaError(f"{label}为空")
    return checked


def detect_media_type(video_path: str | None, image_paths: list[str] | None) -> str:
    if video_path:
        ensure_real_file(video_path, "原视频")
        return "video"
    if image_paths:
        ensure_real_files(image_paths, "原图")
        return "image_post"
    raise NoRealMediaError("未下载到真实视频或图片，禁止仅根据链接拆解")


def _extract_frames_with_filter(video_path: str, pattern: Path, vf: str, *, timeout: int = 60, input_args: list[str] | None = None) -> list[str]:
    pattern.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        *(input_args or []),
        "-i",
        video_path,
        "-vf",
        vf,
        "-q:v",
        "3",
        str(pattern),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    except Exception:
        return []
    return sorted(str(p) for p in pattern.parent.glob(pattern.name.replace("%03d", "*")))


def _extract_frame_at(video_path: str, out_dir: Path, timestamp_sec: int) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"frame_t{timestamp_sec:06d}.jpg"
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(max(0, int(timestamp_sec))),
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-vf",
        "scale=768:-1",
        "-q:v",
        "3",
        str(target),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except Exception:
        return ""
    return str(target) if target.exists() and target.stat().st_size > 0 else ""


def storyboard_sample_timestamps(
    max_seconds: int = VIDEO_ANALYSIS_MAX_SECONDS,
    *,
    start_seconds: float = 0.0,
) -> list[int]:
    max_seconds = max(1, int(max_seconds or VIDEO_ANALYSIS_MAX_SECONDS))
    start_seconds = max(0.0, float(start_seconds or 0.0))
    if start_seconds < STORYBOARD_OPENING_SECONDS:
        timestamps = list(range(int(math.ceil(start_seconds)), min(STORYBOARD_OPENING_SECONDS, max_seconds) + 1))
        next_timestamp = STORYBOARD_OPENING_SECONDS + STORYBOARD_POST_OPENING_STEP_SECONDS
    else:
        timestamps = [int(math.ceil(start_seconds))]
        next_timestamp = int(math.ceil(start_seconds)) + STORYBOARD_POST_OPENING_STEP_SECONDS
    while next_timestamp < max_seconds:
        timestamps.append(next_timestamp)
        next_timestamp += STORYBOARD_POST_OPENING_STEP_SECONDS
    return sorted(set(timestamps))


def extract_video_frames(
    video_path: str,
    out_dir: str,
    max_frames: int = 8,
    *,
    analysis_time_range: str = "",
) -> list[str]:
    video = Path(video_path)
    ensure_real_file(str(video), "原视频")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames: list[str] = []
    requested_ranges = parse_explicit_analysis_time_range(analysis_time_range)
    if requested_ranges:
        timestamps = [
            timestamp
            for start, end in requested_ranges
            for timestamp in storyboard_sample_timestamps(int(math.ceil(end)), start_seconds=start)
            if timestamp < end
        ]
    else:
        timestamps = storyboard_sample_timestamps(VIDEO_ANALYSIS_MAX_SECONDS)
    for timestamp_sec in sorted(set(timestamps)):
        frame = _extract_frame_at(str(video), out, timestamp_sec)
        if frame:
            frames.append(frame)
    return frames


def extract_first_frame(video_path: str, out_dir: str) -> str:
    ensure_real_file(video_path, "原视频")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "first_frame.jpg"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-vf",
        "scale=768:-1",
        "-q:v",
        "3",
        str(target),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except Exception:
        return ""
    return str(target) if target.exists() and target.stat().st_size > 0 else ""


def extract_audio(
    video_path: str,
    out_dir: str,
    max_duration_sec: int = VIDEO_ANALYSIS_MAX_SECONDS,
    *,
    start_seconds: float = 0.0,
) -> str:
    ensure_real_file(video_path, "原视频")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "audio.mp3"
    cmd = ["ffmpeg", "-y"]
    if start_seconds > 0:
        cmd.extend(["-ss", str(max(0.0, float(start_seconds)))])
    cmd.extend(
        [
            "-t",
            str(max(1, int(max_duration_sec or VIDEO_ANALYSIS_MAX_SECONDS))),
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "libmp3lame",
            "-q:a",
            "4",
            str(target),
        ]
    )
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    except Exception:
        return ""
    return str(target) if target.exists() and target.stat().st_size > 0 else ""


def cleanup_temp_files(paths: list[str]) -> None:
    for path in paths:
        try:
            p = Path(path)
            p.unlink()
            try:
                p.parent.rmdir()
            except OSError:
                pass
        except OSError:
            pass
