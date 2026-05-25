from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys

SELFMEDIA_ROOT = Path(__file__).resolve().parents[3]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.llm_settings import (
    load_analysis_agent_settings,
    load_qwen_settings,
    normalize_thinking,
)


@dataclass(frozen=True)
class Settings:
    gemini_base_url: str
    gemini_api_key: str
    gemini_model: str
    qwen_base_url: str
    qwen_api_key: str
    qwen_model: str
    qwen_timeout: float
    analysis_openclaw_bin: str
    analysis_openclaw_model: str
    analysis_openclaw_allow_model_override: bool
    analysis_openclaw_timeout: float
    analysis_openclaw_thinking: str
    analysis_openclaw_cwd: str
    analysis_openclaw_codex_home: str
    analysis_openclaw_agent: str
    max_inline_size: int
    asr_provider: str
    dashscope_api_key: str
    dashscope_asr_model: str
    dashscope_asr_mode: str
    dashscope_diarization_enabled: bool
    dashscope_speaker_count: int
    dashscope_poll_interval: float
    dashscope_timeout: float
    openai_api_key: str
    openai_base_url: str
    openai_transcription_model: str
    openai_transcription_timeout: float
    openai_transcription_language: str
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


def _normalize_analysis_thinking(value: str) -> str:
    return normalize_thinking(value)


def load_settings() -> Settings:
    qwen = load_qwen_settings()
    analysis_agent = load_analysis_agent_settings()
    return Settings(
        gemini_base_url=os.getenv("GEMINI_BASE_URL", "https://api.zhizengzeng.com/google/"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3-pro-preview"),
        qwen_base_url=qwen.base_url,
        qwen_api_key=qwen.api_key,
        qwen_model=qwen.model,
        qwen_timeout=float(os.getenv("SELFMEDIA_QWEN_TIMEOUT", "120")),
        analysis_openclaw_bin=analysis_agent.bin,
        analysis_openclaw_model=analysis_agent.model,
        analysis_openclaw_allow_model_override=analysis_agent.allow_model_override,
        analysis_openclaw_timeout=analysis_agent.timeout,
        analysis_openclaw_thinking=analysis_agent.thinking,
        analysis_openclaw_cwd=analysis_agent.cwd,
        analysis_openclaw_codex_home=analysis_agent.codex_home,
        analysis_openclaw_agent=analysis_agent.agent,
        max_inline_size=int(os.getenv("MAX_INLINE_SIZE", str(20 * 1024 * 1024))),
        asr_provider=os.getenv("ASR_PROVIDER", os.getenv("TRANSCRIPTION_PROVIDER", "dashscope")).strip().lower(),
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", ""),
        dashscope_asr_model=os.getenv("DASHSCOPE_ASR_MODEL", "fun-asr-realtime"),
        dashscope_asr_mode=os.getenv("DASHSCOPE_ASR_MODE", "auto").strip().lower(),
        dashscope_diarization_enabled=os.getenv("DASHSCOPE_DIARIZATION_ENABLED", "0").lower()
        in ("1", "true", "yes", "on"),
        dashscope_speaker_count=int(os.getenv("DASHSCOPE_SPEAKER_COUNT", "0") or "0"),
        dashscope_poll_interval=float(os.getenv("DASHSCOPE_POLL_INTERVAL", "5")),
        dashscope_timeout=float(os.getenv("DASHSCOPE_TIMEOUT", "180")),
        openai_api_key=os.getenv("SELFMEDIA_TRANSCRIPTION_OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("SELFMEDIA_TRANSCRIPTION_OPENAI_BASE_URL", ""),
        openai_transcription_model=os.getenv("SELFMEDIA_TRANSCRIPTION_OPENAI_MODEL", ""),
        openai_transcription_timeout=float(os.getenv("SELFMEDIA_TRANSCRIPTION_OPENAI_TIMEOUT", "600")),
        openai_transcription_language=os.getenv("SELFMEDIA_TRANSCRIPTION_OPENAI_LANGUAGE", "zh"),
        gemini_timeout=float(os.getenv("GEMINI_TIMEOUT", "60")),
        download_read_timeout=float(os.getenv("DOWNLOAD_READ_TIMEOUT", "120")),
        download_max_seconds=float(os.getenv("DOWNLOAD_MAX_SECONDS", "180")),
        download_prefer_ffmpeg=os.getenv("DOWNLOAD_PREFER_FFMPEG", "0").lower()
        in ("1", "true", "yes"),
        prefer_low_quality=os.getenv("PREFER_LOW_QUALITY", "1").lower()
        in ("1", "true", "yes"),
        video_ratio=os.getenv("VIDEO_RATIO", "540p"),
        top_comments_limit=int(os.getenv("TOP_COMMENTS_LIMIT", "1")),
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
