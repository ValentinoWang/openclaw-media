from __future__ import annotations

from dataclasses import dataclass
import os

from .bot_llm_config import (
    normalize_openclaw_model,
    profile_config,
    profile_provider_runtime,
    profile_runtime,
    provider_runtime,
)


API_TYPE_CHAT_COMPLETIONS = "openai_chat_completions"
API_TYPE_CODEX_RESPONSES = "openai_codex_responses"
API_TYPE_OPENCLAW_AGENT = "openclaw_agent"

@dataclass(frozen=True)
class LLMProviderSettings:
    model: str
    base_url: str
    api_key: str
    api_type: str
    timeout: float
    thinking: str = ""
    bin: str = ""
    agent: str = ""
    cwd: str = ""
    codex_home: str = ""


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


def load_profile_llm_settings(profile_name: str) -> LLMProviderSettings:
    provider = profile_provider_runtime(profile_name)
    runtime = profile_runtime(profile_name) if provider.api_type == API_TYPE_OPENCLAW_AGENT else None
    return LLMProviderSettings(
        model=runtime.model if runtime else provider.model,
        base_url=provider.base_url,
        api_key=provider.api_key,
        api_type=provider.api_type,
        timeout=runtime.timeout if runtime else provider.timeout,
        thinking=runtime.thinking if runtime else provider.thinking,
        bin=runtime.bin if runtime else "",
        agent=runtime.agent if runtime else "",
        cwd=runtime.cwd if runtime else "",
        codex_home=runtime.codex_home if runtime else "",
    )


def load_analysis_agent_settings() -> OpenClawAgentSettings:
    runtime = profile_runtime("media_analysis")
    return OpenClawAgentSettings(
        bin=runtime.bin,
        agent=runtime.agent,
        model=runtime.model,
        allow_model_override=False,
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
        allow_model_override=False,
        timeout=runtime.timeout,
        thinking=normalize_thinking(runtime.thinking),
        cwd=runtime.cwd,
        codex_home=runtime.codex_home,
    )


def load_content_cleaner_llm_settings() -> ContentCleanerLLMSettings:
    cleaner = profile_config("content_cleaner")
    provider_settings = load_profile_llm_settings("content_cleaner")
    return ContentCleanerLLMSettings(
        enabled=bool(cleaner.get("enabled", True)),
        provider=provider_settings,
        max_chars=max(1000, int(float(cleaner.get("max_chars") or 20000))),
        max_tokens=max(1000, int(float(cleaner.get("max_tokens") or 8192))),
    )
