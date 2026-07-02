from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys

SELFMEDIA_ROOT = Path(__file__).resolve().parents[4]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.llm_settings import load_profile_llm_settings


@dataclass(frozen=True)
class Settings:
    gemini_base_url: str
    gemini_api_key: str
    gemini_model: str
    analysis_timeout: float
    max_inline_size: int
    gemini_timeout: float
    download_read_timeout: float
    download_max_seconds: float
    download_prefer_ffmpeg: bool
    prefer_low_quality: bool
    video_ratio: str
    top_comments_limit: int
    notion_token: str
    notion_database_id: str
    playwright_headless: bool
    playwright_debug: bool
    cookies_profile: str
    playwright_proxy_server: str
    douyin_cookies_json_path: str
    xiaohongshu_cookies_json_path: str


def load_settings() -> Settings:
    analysis_llm = load_profile_llm_settings("media_analysis")
    return Settings(
        gemini_base_url=os.getenv("GEMINI_BASE_URL", "https://api.zhizengzeng.com/google/"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3-pro-preview"),
        analysis_timeout=analysis_llm.timeout,
        max_inline_size=int(os.getenv("MAX_INLINE_SIZE", str(20 * 1024 * 1024))),
        gemini_timeout=float(os.getenv("GEMINI_TIMEOUT", "60")),
        download_read_timeout=float(os.getenv("DOWNLOAD_READ_TIMEOUT", "120")),
        download_max_seconds=float(os.getenv("DOWNLOAD_MAX_SECONDS", "180")),
        download_prefer_ffmpeg=os.getenv("DOWNLOAD_PREFER_FFMPEG", "0").lower()
        in ("1", "true", "yes"),
        prefer_low_quality=os.getenv("PREFER_LOW_QUALITY", "1").lower()
        in ("1", "true", "yes"),
        video_ratio=os.getenv("VIDEO_RATIO", "480p"),
        top_comments_limit=int(os.getenv("TOP_COMMENTS_LIMIT", "3")),
        notion_token=os.getenv("NOTION_TOKEN", ""),
        notion_database_id=os.getenv("NOTION_DATABASE_ID", ""),
        playwright_headless=os.getenv("PLAYWRIGHT_HEADLESS", "1").lower()
        not in ("0", "false", "no"),
        playwright_debug=os.getenv("PLAYWRIGHT_DEBUG", "0").lower() in ("1", "true", "yes"),
        cookies_profile=os.getenv("COOKIES_PROFILE", "Default"),
        playwright_proxy_server=os.getenv(
            "PLAYWRIGHT_PROXY_SERVER",
            os.getenv("ALL_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "",
        ),
        douyin_cookies_json_path=os.getenv("DOUYIN_COOKIES_JSON_PATH", ""),
        xiaohongshu_cookies_json_path=os.getenv("XIAOHONGSHU_COOKIES_JSON_PATH", ""),
    )
