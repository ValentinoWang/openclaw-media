from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from typing import Optional

from .utils import extract_douyin_id, extract_xhs_id


@dataclass(frozen=True)
class MediaPaths:
    stem: str
    base_dir: str
    item_dir: str
    video_id: str
    image_dir: str
    video_path: str
    audio_path: str
    caption_path: str
    transcript_path: str
    analysis_path: str


def _ensure_base_dir(base_dir: str) -> str:
    if os.path.isabs(base_dir):
        return base_dir
    return os.path.join(os.getcwd(), base_dir)


def _make_identity(url: str) -> tuple[str, str]:
    xhs_id = extract_xhs_id(url)
    if xhs_id:
        return f"xhs-{xhs_id}", xhs_id
    _kind, item_id = extract_douyin_id(url)
    if item_id:
        return f"douyin-{item_id}", item_id
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    return f"video-{digest}", digest


def build_media_paths(url: str, base_dir: str = "downloads") -> MediaPaths:
    base_dir = _ensure_base_dir(base_dir)
    stem, video_id = _make_identity(url)
    item_dir = os.path.join(base_dir, stem)
    return MediaPaths(
        stem=stem,
        base_dir=base_dir,
        item_dir=item_dir,
        video_id=video_id,
        image_dir=os.path.join(item_dir, "images"),
        video_path=os.path.join(item_dir, "video.mp4"),
        audio_path=os.path.join(item_dir, "audio.mp3"),
        caption_path=os.path.join(item_dir, "caption.txt"),
        transcript_path=os.path.join(item_dir, "transcript.txt"),
        analysis_path=os.path.join(item_dir, "analysis.json"),
    )


def media_exists(path: Optional[str]) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def ensure_media_paths(url: str, base_dir: str = "downloads") -> MediaPaths:
    paths = build_media_paths(url, base_dir)
    os.makedirs(paths.item_dir, exist_ok=True)
    os.makedirs(paths.image_dir, exist_ok=True)

    legacy_map = {
        f"{paths.stem}.mp4": paths.video_path,
        f"{paths.stem}.mp3": paths.audio_path,
        f"{paths.stem}.txt": paths.transcript_path,
        f"{paths.stem}.json": paths.analysis_path,
    }
    for legacy_name, target in legacy_map.items():
        legacy_path = os.path.join(paths.base_dir, legacy_name)
        if os.path.exists(legacy_path) and not os.path.exists(target):
            os.replace(legacy_path, target)

    return paths


def list_image_files(paths: MediaPaths) -> list[str]:
    if not os.path.isdir(paths.image_dir):
        return []
    frames_dir = os.path.join(paths.image_dir, "frames")
    if os.path.isdir(frames_dir):
        frames = []
        for name in os.listdir(frames_dir):
            if name.startswith("."):
                continue
            frames.append(os.path.join(frames_dir, name))
        frames.sort()
        if frames:
            return frames

    files = []
    for name in os.listdir(paths.image_dir):
        if name.startswith("."):
            continue
        path = os.path.join(paths.image_dir, name)
        if os.path.isdir(path):
            continue
        files.append(path)
    files.sort()
    return files


def load_text(path: str) -> Optional[str]:
    if not media_exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def save_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def load_json(path: str) -> Optional[dict]:
    if not media_exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def save_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
