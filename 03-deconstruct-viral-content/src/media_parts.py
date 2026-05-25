from __future__ import annotations

import base64
import mimetypes
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class NoRealMediaError(RuntimeError):
    pass


class MediaProcessingError(RuntimeError):
    pass


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


def extract_video_frames(video_path: str, out_dir: str, max_frames: int = 8) -> list[str]:
    video = Path(video_path)
    ensure_real_file(str(video), "原视频")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # 前 5 秒是短视频/图文视频最关键的停留区，强制 10fps 采样。
    first5_frames = _extract_frames_with_filter(
        str(video),
        out / "first5s_%03d.jpg",
        "fps=10,scale=768:-1",
        input_args=["-t", "5"],
    )
    # 5 秒之后按用户要求改为 fps=2，连续覆盖后续内容。
    post5_frames = _extract_frames_with_filter(
        str(video),
        out / "frame_%03d.jpg",
        "fps=2,scale=768:-1",
        input_args=["-ss", "5"],
    )
    return first5_frames + post5_frames


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


def extract_audio(video_path: str, out_dir: str) -> str:
    ensure_real_file(video_path, "原视频")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "audio.mp3"
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "4", str(target)]
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


def prepare_media_evidence(
    video_path: str | None,
    image_paths: list[str] | None,
    work_dir: str,
    max_frames: int = 8,
    existing_audio_path: str | None = None,
) -> MediaEvidence:
    media_type = detect_media_type(video_path, image_paths)
    parts: list[dict[str, Any]] = []
    evidence: list[str] = []
    evidence_assets: list[dict[str, str]] = []
    cleanup_paths: list[str] = []
    audio_path = ""
    preview_path = ""

    if media_type == "video":
        checked_video = ensure_real_file(video_path, "原视频")
        frames = extract_video_frames(checked_video, str(Path(work_dir) / "frames"), max_frames=max_frames)
        frames = [ensure_real_file(frame, "视频关键帧") for frame in frames]
        if not frames:
            raise MediaProcessingError(f"视频已下载但抽帧失败，不能进行假拆解：{checked_video}")
        cleanup_paths.extend(frames)
        asset_dir = str(Path(work_dir) / "doc_assets")
        for idx, frame in enumerate(frames, 1):
            asset_id = _asset_id("frame", idx)
            asset_path = _copy_asset(frame, asset_dir, asset_id)
            source_name = Path(frame).name
            is_first5 = source_name.startswith("first5s_")
            kind = "first5s_frame" if is_first5 else "keyframe"
            phase = "前5秒 10fps 高密度采样" if is_first5 else "5秒后 fps=2 采样"
            evidence.append(asset_path)
            evidence_assets.append({"asset_id": asset_id, "path": asset_path, "kind": kind, "phase": phase})
            parts.append({"text": f"视觉证据 asset_id={asset_id}；这是从已下载原视频抽取的{phase}帧。后续分镜必须在 evidence_asset_id 引用这个 ID。"})
            parts.append(_image_part(asset_path))
        preview_path = extract_first_frame(checked_video, str(Path(work_dir) / "preview"))
        if not preview_path:
            preview_path = evidence_assets[0]["path"]
        if existing_audio_path:
            try:
                audio_path = ensure_real_file(existing_audio_path, "原音频")
            except NoRealMediaError:
                audio_path = ""
        if not audio_path:
            audio_path = extract_audio(checked_video, str(Path(work_dir) / "audio"))
        if not audio_path:
            raise MediaProcessingError(f"视频音频提取失败，不能写入半成品：{checked_video}")
    else:
        checked_images = ensure_real_files(image_paths, "原图")
        selected = checked_images[:max_frames]
        for idx, path in enumerate(selected, 1):
            asset_id = _asset_id("image", idx)
            kind = "cover_image" if idx == 1 else "source_image"
            phase = "图文首图/封面重点分析" if idx == 1 else "图文后续图片"
            evidence.append(path)
            evidence_assets.append({"asset_id": asset_id, "path": path, "kind": kind, "phase": phase})
            parts.append({"text": f"视觉证据 asset_id={asset_id}；这是已下载图文原图，{phase}。后续分镜/图文脚本必须在 evidence_asset_id 引用这个 ID。"})
            parts.append(_image_part(path))
        preview_path = selected[0] if selected else ""

    return MediaEvidence(
        media_type=media_type,
        parts=parts,
        evidence_paths=evidence,
        evidence_assets=evidence_assets,
        cleanup_paths=cleanup_paths,
        audio_path=audio_path,
        preview_path=preview_path,
    )


def build_vision_media_parts(
    video_path: str | None,
    image_paths: list[str] | None,
    work_dir: str,
    max_frames: int = 8,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return model-compatible image parts and the concrete evidence paths used."""
    evidence = prepare_media_evidence(video_path, image_paths, work_dir, max_frames=max_frames)
    return evidence.parts, evidence.evidence_paths
