from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import Settings
from .downloader import clean_douyin_url, extract_audio_mp3, resolve_media
from .storage import ensure_media_paths, media_exists


class MusicDownloadError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MusicResult:
    url: str
    audio_path: str
    media_dir: str


@dataclass(frozen=True)
class VideoResult:
    url: str
    video_path: str
    media_dir: str


def _is_mp3(path: Optional[str]) -> bool:
    return bool(path) and path.lower().endswith(".mp3")


def download_music(url: str, settings: Settings, progress=None) -> MusicResult:
    cleaned_url = clean_douyin_url(url)
    media = resolve_media(cleaned_url, settings, progress=progress)

    if media.media_type != "video" or not media.video_path:
        raise MusicDownloadError("unsupported_media")

    paths = ensure_media_paths(cleaned_url)
    if _is_mp3(media.audio_path) and media_exists(media.audio_path):
        return MusicResult(cleaned_url, media.audio_path, paths.item_dir)

    if media.video_path and media_exists(media.video_path):
        extracted = extract_audio_mp3(media.video_path, paths.audio_path)
        if extracted and media_exists(extracted):
            return MusicResult(cleaned_url, extracted, paths.item_dir)

    raise MusicDownloadError("audio_extract_failed")


def download_video(url: str, settings: Settings, progress=None) -> VideoResult:
    cleaned_url = clean_douyin_url(url)
    media = resolve_media(cleaned_url, settings, progress=progress)

    if media.media_type != "video" or not media.video_path:
        raise MusicDownloadError("unsupported_media")

    if not media_exists(media.video_path):
        raise MusicDownloadError("video_download_failed")

    paths = ensure_media_paths(cleaned_url)
    return VideoResult(cleaned_url, media.video_path, paths.item_dir)
