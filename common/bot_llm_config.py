from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path("/home/ubuntu/selfmedia-tools/config/openclaw_bots.json")


@dataclass(frozen=True)
class BotLLMRuntime:
    bin: str
    agent: str
    model: str
    thinking: str
    timeout: float
    cwd: str
    codex_home: str


def normalize_openclaw_model(model: str) -> str:
    value = (model or "").strip()
    if value and "/" not in value:
        return f"openai-codex/{value}"
    return value


def display_openclaw_model(model: str) -> str:
    value = normalize_openclaw_model(model)
    prefix = "openai-codex/"
    return value[len(prefix) :] if value.startswith(prefix) else value


@lru_cache(maxsize=1)
def load_bot_llm_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"OpenClaw Bot LLM 配置不存在：{CONFIG_PATH}")
    parsed = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError(f"OpenClaw Bot LLM 配置格式错误：{CONFIG_PATH}")
    for key in ("defaults", "bots", "profiles"):
        if not isinstance(parsed.get(key), dict):
            raise RuntimeError(f"OpenClaw Bot LLM 配置缺少对象字段：{key}")
    return parsed


def _merged_runtime(profile_or_bot: dict[str, Any]) -> BotLLMRuntime:
    config = load_bot_llm_config()
    defaults = dict(config["defaults"])
    bot_name = str(profile_or_bot.get("bot") or "").strip()
    bot = dict(config["bots"].get(bot_name, {})) if bot_name else {}
    merged = {**defaults, **bot, **profile_or_bot}
    missing = [key for key in ("bin", "agent", "model", "thinking", "timeout", "cwd", "codex_home") if not merged.get(key)]
    if missing:
        raise RuntimeError(f"OpenClaw Bot LLM 配置不完整：{', '.join(missing)}")
    return BotLLMRuntime(
        bin=str(merged["bin"]).strip(),
        agent=str(merged["agent"]).strip(),
        model=normalize_openclaw_model(str(merged["model"])),
        thinking=str(merged["thinking"]).strip().lower(),
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
    config = load_bot_llm_config()
    profile = config["profiles"].get(profile_name)
    if not isinstance(profile, dict):
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 profile：{profile_name}")
    return _merged_runtime(profile)
