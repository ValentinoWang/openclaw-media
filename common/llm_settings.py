from __future__ import annotations

from dataclasses import dataclass
import os

from .bot_llm_config import (
    normalize_openclaw_model,
    load_bot_llm_config,
    profile_runtime,
    provider_runtime,
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
    timeout: float = 120.0
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
    provider = provider_runtime("main_llm")
    return LLMProviderSettings(
        model=provider.model,
        base_url=provider.base_url,
        api_key=provider.api_key,
        api_type=provider.api_type,
        timeout=provider.timeout,
        thinking=provider.thinking,
    )


def load_qwen_settings() -> QwenProviderSettings:
    provider = provider_runtime("qwen")
    return QwenProviderSettings(
        model=provider.model,
        base_url=provider.base_url,
        api_key=provider.api_key,
        timeout=provider.timeout,
        fps=provider.fps or 2.0,
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
    config = load_bot_llm_config()
    cleaner = config["content_cleaner"]
    provider = provider_runtime(str(cleaner.get("provider") or "main_llm"))
    provider_settings = LLMProviderSettings(
        model=provider.model,
        base_url=provider.base_url,
        api_key=provider.api_key,
        api_type=provider.api_type,
        timeout=provider.timeout,
        thinking=provider.thinking,
    )
    return ContentCleanerLLMSettings(
        enabled=bool(cleaner.get("enabled", True)),
        provider=provider_settings,
        max_chars=max(1000, int(float(cleaner.get("max_chars") or 20000))),
        max_tokens=max(1000, int(float(cleaner.get("max_tokens") or 8192))),
    )
