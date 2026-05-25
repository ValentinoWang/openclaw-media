from __future__ import annotations

from dataclasses import dataclass
import os

from .bot_llm_config import (
    normalize_openclaw_model,
    profile_runtime,
)


API_TYPE_CHAT_COMPLETIONS = "openai_chat_completions"
API_TYPE_CODEX_RESPONSES = "openai_codex_responses"

@dataclass(frozen=True)
class LLMProviderSettings:
    model: str
    base_url: str
    api_key: str
    api_type: str
    timeout: float
    thinking: str = ""


@dataclass(frozen=True)
class QwenProviderSettings:
    model: str
    base_url: str
    api_key: str
    fps: float = 2.0


@dataclass(frozen=True)
class OpenClawAgentSettings:
    bin: str
    agent: str
    model: str
    allow_model_override: bool
    timeout: float
    thinking: str
    cwd: str
    codex_home: str


@dataclass(frozen=True)
class ContentCleanerLLMSettings:
    enabled: bool
    provider: LLMProviderSettings
    max_chars: int
    max_tokens: int


def normalize_thinking(value: str, *, default: str = "high") -> str:
    thinking = (value or "").strip().lower()
    if not thinking:
        return default
    return thinking


def env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: str) -> float:
    return float(os.getenv(name, default))


def env_int(name: str, default: str) -> int:
    return int(float(os.getenv(name, default)))


def load_main_llm_settings() -> LLMProviderSettings:
    return LLMProviderSettings(
        model=os.getenv("SELFMEDIA_CLEAN_LLM_MODEL", "").strip(),
        base_url=os.getenv("SELFMEDIA_CLEAN_LLM_BASE_URL", "").strip().rstrip("/"),
        api_key=os.getenv("SELFMEDIA_CLEAN_LLM_API_KEY", "").strip(),
        api_type=os.getenv("SELFMEDIA_CLEAN_LLM_API_TYPE", "").strip(),
        timeout=env_float("SELFMEDIA_CLEAN_LLM_TIMEOUT", "300"),
        thinking="",
    )


def load_qwen_settings() -> QwenProviderSettings:
    return QwenProviderSettings(
        model=os.getenv("SELFMEDIA_QWEN_MODEL", "").strip(),
        base_url=os.getenv("SELFMEDIA_QWEN_BASE_URL", "").strip().rstrip("/"),
        api_key=os.getenv("SELFMEDIA_QWEN_API_KEY", "").strip(),
        fps=env_float("SELFMEDIA_QWEN_FPS", "2.0"),
    )


def load_analysis_agent_settings() -> OpenClawAgentSettings:
    runtime = profile_runtime("media_analysis")
    return OpenClawAgentSettings(
        bin=runtime.bin,
        agent=runtime.agent,
        model=runtime.model,
        allow_model_override=True,
        timeout=runtime.timeout,
        thinking=normalize_thinking(runtime.thinking),
        cwd=runtime.cwd,
        codex_home=runtime.codex_home,
    )


def load_creation_agent_settings() -> OpenClawAgentSettings:
    runtime = profile_runtime("media_creation")
    return OpenClawAgentSettings(
        bin=runtime.bin,
        agent=runtime.agent,
        model=runtime.model,
        allow_model_override=True,
        timeout=runtime.timeout,
        thinking=normalize_thinking(runtime.thinking),
        cwd=runtime.cwd,
        codex_home=runtime.codex_home,
    )


def load_content_cleaner_llm_settings() -> ContentCleanerLLMSettings:
    provider = LLMProviderSettings(
        model=os.getenv("SELFMEDIA_CLEAN_LLM_MODEL", "").strip(),
        base_url=os.getenv("SELFMEDIA_CLEAN_LLM_BASE_URL", "").strip().rstrip("/"),
        api_key=os.getenv("SELFMEDIA_CLEAN_LLM_API_KEY", "").strip(),
        api_type=os.getenv("SELFMEDIA_CLEAN_LLM_API_TYPE", "").strip(),
        timeout=env_float("SELFMEDIA_CLEAN_LLM_TIMEOUT", "300"),
        thinking="",
    )
    return ContentCleanerLLMSettings(
        enabled=os.getenv("SELFMEDIA_CLEAN_LLM_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"},
        provider=provider,
        max_chars=max(1000, env_int("SELFMEDIA_CLEAN_LLM_MAX_CHARS", "20000")),
        max_tokens=max(1000, env_int("SELFMEDIA_CLEAN_LLM_MAX_TOKENS", "8192")),
    )
