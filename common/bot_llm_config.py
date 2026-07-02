from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any, Mapping


CONFIG_PATH = Path("/home/ubuntu/selfmedia-tools/config/openclaw_bots.json")
DEFAULT_OPENCLAW_MODEL_PROVIDER = "openai-codex"
OPENCLAW_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high"}
OPENCLAW_THINKING_ALIASES = {"xhigh": "high", "max": "high", "adaptive": "high"}
OPENCLAW_NODE_BIN_DIR = "/home/ubuntu/.nvm/versions/node/v22.22.2/bin"
OPENCLAW_BASE_PATH_DIRS = (
    "/home/ubuntu/bin",
    "/home/ubuntu/.local/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
)


@dataclass(frozen=True)
class BotLLMRuntime:
    provider: str
    bin: str
    agent: str
    model: str
    thinking: str
    timeout: float
    cwd: str
    codex_home: str


@dataclass(frozen=True)
class LLMProviderRuntime:
    model: str
    base_url: str
    api_key: str
    api_type: str
    timeout: float
    thinking: str = ""
    fps: float = 0.0


def normalize_openclaw_model(model: str) -> str:
    value = (model or "").strip()
    if value and "/" not in value:
        return f"{DEFAULT_OPENCLAW_MODEL_PROVIDER}/{value}"
    return value


def display_openclaw_model(model: str) -> str:
    value = normalize_openclaw_model(model)
    return value.split("/", 1)[1] if "/" in value else value


def normalize_openclaw_thinking(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = OPENCLAW_THINKING_ALIASES.get(normalized, normalized)
    return normalized if normalized in OPENCLAW_THINKING_LEVELS else ""


def openclaw_subprocess_env(codex_home: str = "", *, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env.setdefault("HOME", "/home/ubuntu")
    if codex_home:
        env["CODEX_HOME"] = codex_home
    env["PATH"] = os.pathsep.join(_dedupe_path_parts([*_openclaw_path_prefixes(), env.get("PATH", "")]))
    return env


def _openclaw_path_prefixes() -> list[str]:
    prefixes = [OPENCLAW_NODE_BIN_DIR]
    nvm_root = Path("/home/ubuntu/.nvm/versions/node")
    if nvm_root.is_dir():
        for path in sorted(nvm_root.glob("*/bin"), reverse=True):
            if (path / "node").is_file():
                prefixes.append(str(path))
    prefixes.extend(OPENCLAW_BASE_PATH_DIRS)
    return _dedupe_path_parts(prefixes)


def _dedupe_path_parts(values: list[str]) -> list[str]:
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in str(value or "").split(os.pathsep):
            item = part.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            parts.append(item)
    return parts


@lru_cache(maxsize=1)
def load_bot_llm_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"OpenClaw Bot LLM 配置不存在：{CONFIG_PATH}")
    parsed = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError(f"OpenClaw Bot LLM 配置格式错误：{CONFIG_PATH}")
    for key in ("defaults", "bots", "profiles", "providers"):
        if not isinstance(parsed.get(key), dict):
            raise RuntimeError(f"OpenClaw Bot LLM 配置缺少对象字段：{key}")
    return parsed


def profile_config(profile_name: str) -> dict[str, Any]:
    config = load_bot_llm_config()
    profile = config["profiles"].get(profile_name)
    if not isinstance(profile, dict):
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 profile：{profile_name}")
    return dict(profile)


def profile_provider_runtime(profile_name: str) -> LLMProviderRuntime:
    config = load_bot_llm_config()
    profile = profile_config(profile_name)
    bot_name = str(profile.get("bot") or "").strip()
    bot = dict(config["bots"].get(bot_name, {})) if bot_name else {}
    provider_name = str(profile.get("provider") or bot.get("provider") or "").strip()
    if not provider_name:
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 profile provider：{profile_name}")
    return provider_runtime(provider_name)


def _merged_runtime(profile_or_bot: dict[str, Any]) -> BotLLMRuntime:
    config = load_bot_llm_config()
    defaults = dict(config["defaults"])
    bot_name = str(profile_or_bot.get("bot") or "").strip()
    bot = dict(config["bots"].get(bot_name, {})) if bot_name else {}
    provider_name = str(profile_or_bot.get("provider") or bot.get("provider") or "").strip()
    provider = dict(config["providers"].get(provider_name, {})) if provider_name else {}
    merged = {**provider, **defaults, **bot, **profile_or_bot}
    missing = [key for key in ("bin", "agent", "model", "thinking", "timeout", "cwd", "codex_home") if not merged.get(key)]
    if missing:
        raise RuntimeError(f"OpenClaw Bot LLM 配置不完整：{', '.join(missing)}")
    return BotLLMRuntime(
        provider=provider_name,
        bin=str(merged["bin"]).strip(),
        agent=str(merged["agent"]).strip(),
        model=normalize_openclaw_model(str(merged["model"])),
        thinking=normalize_openclaw_thinking(str(merged["thinking"])),
        timeout=float(merged["timeout"]),
        cwd=str(merged["cwd"]).strip(),
        codex_home=str(merged["codex_home"]).strip(),
    )


def bot_runtime(bot_name: str) -> BotLLMRuntime:
    config = load_bot_llm_config()
    bot = config["bots"].get(bot_name)
    if not isinstance(bot, dict):
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 bot：{bot_name}")
    return _merged_runtime(bot)


def profile_runtime(profile_name: str) -> BotLLMRuntime:
    return _merged_runtime(profile_config(profile_name))


def provider_runtime(provider_name: str) -> LLMProviderRuntime:
    config = load_bot_llm_config()
    provider = config["providers"].get(provider_name)
    if not isinstance(provider, dict):
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 provider：{provider_name}")
    missing = [key for key in ("model", "base_url", "api_key", "api_type", "timeout") if not provider.get(key)]
    if missing:
        raise RuntimeError(f"OpenClaw Bot LLM provider 配置不完整：{provider_name}.{', '.join(missing)}")
    return LLMProviderRuntime(
        model=str(provider["model"]).strip(),
        base_url=str(provider["base_url"]).strip().rstrip("/"),
        api_key=str(provider["api_key"]).strip(),
        api_type=str(provider["api_type"]).strip(),
        timeout=float(provider["timeout"]),
        thinking=str(provider.get("thinking") or "").strip().lower(),
        fps=float(provider.get("fps") or 0),
    )
