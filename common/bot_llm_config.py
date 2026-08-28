from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
# README and docs/architecture.md make `config/openclaw_bots.json` the single
# editable configuration source of truth, so resolve it from the repository the
# code was loaded from instead of one host's absolute checkout path.
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "config/openclaw_bots.json"
BASE_URL_ENV_PREFIX = "env:"
DEFAULT_OPENCLAW_MODEL_PROVIDER = "codex"
OPENCLAW_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high"}
OPENCLAW_THINKING_ALIASES = {"xhigh": "high", "max": "high", "adaptive": "high"}
RUNTIME_TEMPLATE_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
RUNTIME_TEMPLATE_DEFAULTS = {
    "OPENCLAW_AGENTS_ROOT": lambda: str(Path.home() / ".openclaw" / "agents"),
    "OPENCLAW_CODEX_HOME": lambda: str(Path.home() / ".codex"),
}


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


class BotLLMConfigError(RuntimeError):
    """Raised when the repository-owned OpenClaw configuration is invalid."""


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


def resolve_runtime_template(value: object) -> str:
    """Expand the small, audited template vocabulary used by the runtime SSOT."""
    text = str(value or "").strip()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        configured = str(os.getenv(name) or "").strip()
        if configured:
            return configured
        default = RUNTIME_TEMPLATE_DEFAULTS.get(name)
        if default is None:
            raise RuntimeError(f"OpenClaw Bot LLM 配置使用了未定义的运行时模板：{name}")
        return default()

    return RUNTIME_TEMPLATE_RE.sub(replace, text)


def openclaw_subprocess_env(codex_home: str = "", *, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env.setdefault("HOME", str(Path.home()))
    if codex_home:
        env["CODEX_HOME"] = codex_home
    env["PATH"] = os.pathsep.join(_dedupe_path_parts([*_openclaw_path_prefixes(env), env.get("PATH", "")]))
    return env


def _openclaw_path_prefixes(env: Mapping[str, str]) -> list[str]:
    home = Path(str(env.get("HOME") or Path.home())).expanduser()
    prefixes = [str(env.get("OPENCLAW_NODE_BIN_DIR") or "")]
    nvm_root = Path(str(env.get("NVM_DIR") or home / ".nvm")).expanduser() / "versions" / "node"
    if nvm_root.is_dir():
        for path in sorted(nvm_root.glob("*/bin"), reverse=True):
            if (path / "node").is_file():
                prefixes.append(str(path))
    prefixes.extend((str(home / "bin"), str(home / ".local" / "bin"), "/usr/local/bin", "/usr/bin", "/bin"))
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


def resolve_bot_llm_config_path() -> Path:
    override = os.getenv("OPENCLAW_BOTS_CONFIG", "").strip()
    return Path(override).expanduser() if override else DEFAULT_CONFIG_PATH


def clear_bot_llm_config_cache() -> None:
    _load_bot_llm_config.cache_clear()


def _require_mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BotLLMConfigError(f"OpenClaw Bot LLM 配置字段必须是对象：{location}")
    return value


def _require_text(value: object, location: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BotLLMConfigError(f"OpenClaw Bot LLM 配置字段不能为空：{location}")
    return text


def _require_positive_number(value: object, location: str) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BotLLMConfigError(f"OpenClaw Bot LLM 配置字段必须是正数：{location}") from exc
    if not math.isfinite(number) or number <= 0:
        raise BotLLMConfigError(f"OpenClaw Bot LLM 配置字段必须是正数：{location}")


def _validate_tier_name(model_tiers: Mapping[str, Any], tier_name: object, location: str) -> None:
    name = _require_text(tier_name, location)
    tier = _require_mapping(model_tiers.get(name), f"model_tiers.{name}")
    _require_text(tier.get("model"), f"model_tiers.{name}.model")
    thinking = normalize_openclaw_thinking(_require_text(tier.get("reasoning"), f"model_tiers.{name}.reasoning"))
    if not thinking:
        raise BotLLMConfigError(f"OpenClaw Bot LLM model tier 推理档位不受支持：model_tiers.{name}.reasoning")


def _resolved_tier_name(scope: Mapping[str, Any], fallback: Mapping[str, Any]) -> str:
    return str(scope.get("model_tier") or fallback.get("model_tier") or fallback.get("default_model_tier") or "").strip()


def _validate_bot_llm_config(parsed: Mapping[str, Any]) -> None:
    required = ("defaults", "policy", "openclaw_runtime", "model_tiers", "bots", "profiles", "providers")
    fields = {name: _require_mapping(parsed.get(name), name) for name in required}
    model_tiers = fields["model_tiers"]
    providers = fields["providers"]
    bots = fields["bots"]
    profiles = fields["profiles"]

    if not model_tiers or not providers or not bots or not profiles:
        raise BotLLMConfigError("OpenClaw Bot LLM 配置的 model_tiers/providers/bots/profiles 不能为空")

    for tier_name, tier_value in model_tiers.items():
        _validate_tier_name(model_tiers, tier_name, f"model_tiers.{tier_name}")

    for provider_name, provider_value in providers.items():
        provider = _require_mapping(provider_value, f"providers.{provider_name}")
        for key in ("base_url", "api_key", "api_type", "timeout", "bin", "codex_home"):
            _require_text(provider.get(key), f"providers.{provider_name}.{key}")
        _require_positive_number(provider.get("timeout"), f"providers.{provider_name}.timeout")
        _validate_tier_name(model_tiers, provider.get("default_model_tier"), f"providers.{provider_name}.default_model_tier")

    for bot_name, bot_value in bots.items():
        bot = _require_mapping(bot_value, f"bots.{bot_name}")
        provider_name = _require_text(bot.get("provider"), f"bots.{bot_name}.provider")
        provider = _require_mapping(providers.get(provider_name), f"providers.{provider_name}")
        _require_text(bot.get("agent"), f"bots.{bot_name}.agent")
        _require_text(bot.get("cwd"), f"bots.{bot_name}.cwd")
        _validate_tier_name(model_tiers, _resolved_tier_name(bot, provider), f"bots.{bot_name}.model_tier")

    for profile_name, profile_value in profiles.items():
        profile = _require_mapping(profile_value, f"profiles.{profile_name}")
        bot_name = _require_text(profile.get("bot"), f"profiles.{profile_name}.bot")
        bot = _require_mapping(bots.get(bot_name), f"bots.{bot_name}")
        provider_name = _require_text(profile.get("provider") or bot.get("provider"), f"profiles.{profile_name}.provider")
        provider = _require_mapping(providers.get(provider_name), f"providers.{provider_name}")
        _validate_tier_name(
            model_tiers,
            str(profile.get("model_tier") or bot.get("model_tier") or provider.get("default_model_tier") or ""),
            f"profiles.{profile_name}.model_tier",
        )

    policy = fields["policy"]
    for key in ("default_provider", "openclaw_runtime_provider"):
        provider_name = _require_text(policy.get(key), f"policy.{key}")
        _require_mapping(providers.get(provider_name), f"providers.{provider_name}")

    overrides = parsed.get("agent_overrides", {})
    for override_name, override_value in _require_mapping(overrides, "agent_overrides").items():
        override = _require_mapping(override_value, f"agent_overrides.{override_name}")
        _validate_tier_name(model_tiers, override.get("model_tier"), f"agent_overrides.{override_name}.model_tier")

    runtime = fields["openclaw_runtime"]
    for forbidden in ("heartbeat_every", "session_maintenance"):
        if forbidden in runtime:
            raise BotLLMConfigError(f"OpenClaw Bot LLM 配置不接受部署常量：openclaw_runtime.{forbidden}")
    app_server = _require_mapping(runtime.get("codex_app_server"), "openclaw_runtime.codex_app_server")
    for forbidden in ("args", "service_tier"):
        if forbidden in app_server:
            raise BotLLMConfigError(f"OpenClaw Bot LLM 配置不接受部署常量：openclaw_runtime.codex_app_server.{forbidden}")
    _require_text(app_server.get("command"), "openclaw_runtime.codex_app_server.command")
    _require_text(app_server.get("version"), "openclaw_runtime.codex_app_server.version")
    timeout = app_server.get("turn_completion_idle_timeout_ms")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 60000:
        raise BotLLMConfigError(
            "OpenClaw Bot LLM 配置字段必须是不小于 60000 的整数："
            "openclaw_runtime.codex_app_server.turn_completion_idle_timeout_ms"
        )


@lru_cache(maxsize=8)
def _load_bot_llm_config(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    if not path.is_file():
        raise BotLLMConfigError(f"OpenClaw Bot LLM 配置不存在：{path}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BotLLMConfigError(f"无法读取 OpenClaw Bot LLM 配置：{path}") from exc
    except json.JSONDecodeError as exc:
        raise BotLLMConfigError(f"OpenClaw Bot LLM 配置 JSON 无效：{path}") from exc
    if not isinstance(parsed, dict):
        raise BotLLMConfigError(f"OpenClaw Bot LLM 配置格式错误：{path}")
    _validate_bot_llm_config(parsed)
    return parsed


def load_bot_llm_config() -> dict[str, Any]:
    """Return an isolated copy of the validated configuration source of truth."""
    return copy.deepcopy(_load_bot_llm_config(str(resolve_bot_llm_config_path())))


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
    return provider_runtime(provider_name, model_tier=_resolved_model_tier_name(config, profile, bot, provider_name))


def _resolved_model_tier_name(
    config: Mapping[str, Any],
    profile_or_bot: Mapping[str, Any],
    bot: Mapping[str, Any],
    provider_name: str,
) -> str:
    provider = config["providers"].get(provider_name)
    if not isinstance(provider, Mapping):
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 provider：{provider_name}")
    tier_name = str(
        profile_or_bot.get("model_tier")
        or bot.get("model_tier")
        or provider.get("default_model_tier")
        or ""
    ).strip()
    if not tier_name:
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 model tier：{provider_name}")
    tier = config["model_tiers"].get(tier_name)
    if not isinstance(tier, Mapping):
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 model tier：{tier_name}")
    missing = [key for key in ("model", "reasoning") if not tier.get(key)]
    if missing:
        raise RuntimeError(f"OpenClaw Bot LLM model tier 配置不完整：{tier_name}.{', '.join(missing)}")
    return tier_name


def _model_tier(config: Mapping[str, Any], tier_name: str) -> Mapping[str, Any]:
    tier = config["model_tiers"].get(tier_name)
    if not isinstance(tier, Mapping):
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 model tier：{tier_name}")
    return tier


def _merged_runtime(profile_or_bot: dict[str, Any]) -> BotLLMRuntime:
    config = load_bot_llm_config()
    defaults = dict(config["defaults"])
    bot_name = str(profile_or_bot.get("bot") or "").strip()
    bot = dict(config["bots"].get(bot_name, {})) if bot_name else {}
    provider_name = str(profile_or_bot.get("provider") or bot.get("provider") or "").strip()
    provider = dict(config["providers"].get(provider_name, {})) if provider_name else {}
    merged = {**provider, **defaults, **bot, **profile_or_bot}
    tier_name = _resolved_model_tier_name(config, profile_or_bot, bot, provider_name)
    tier = _model_tier(config, tier_name)
    missing = [key for key in ("bin", "agent", "timeout", "cwd", "codex_home") if not merged.get(key)]
    if missing:
        raise RuntimeError(f"OpenClaw Bot LLM 配置不完整：{', '.join(missing)}")
    return BotLLMRuntime(
        provider=provider_name,
        bin=resolve_runtime_template(merged["bin"]),
        agent=resolve_runtime_template(merged["agent"]),
        model=normalize_openclaw_model(str(tier["model"])),
        thinking=normalize_openclaw_thinking(str(tier["reasoning"])),
        timeout=float(merged["timeout"]),
        cwd=resolve_runtime_template(merged["cwd"]),
        codex_home=resolve_runtime_template(merged["codex_home"]),
    )


def bot_runtime(bot_name: str) -> BotLLMRuntime:
    config = load_bot_llm_config()
    bot = config["bots"].get(bot_name)
    if not isinstance(bot, dict):
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 bot：{bot_name}")
    return _merged_runtime(bot)


def profile_runtime(profile_name: str) -> BotLLMRuntime:
    return _merged_runtime(profile_config(profile_name))


def provider_runtime(provider_name: str, *, model_tier: str = "") -> LLMProviderRuntime:
    config = load_bot_llm_config()
    provider = config["providers"].get(provider_name)
    if not isinstance(provider, dict):
        raise RuntimeError(f"OpenClaw Bot LLM 配置缺少 provider：{provider_name}")
    missing = [key for key in ("base_url", "api_key", "api_type", "timeout") if not provider.get(key)]
    if missing:
        raise RuntimeError(f"OpenClaw Bot LLM provider 配置不完整：{provider_name}.{', '.join(missing)}")
    tier_name = model_tier or _resolved_model_tier_name(config, provider, {}, provider_name)
    tier = _model_tier(config, tier_name)
    return LLMProviderRuntime(
        model=str(tier["model"]).strip(),
        base_url=resolve_provider_base_url(str(provider["base_url"])),
        api_key=str(provider["api_key"]).strip(),
        api_type=str(provider["api_type"]).strip(),
        timeout=float(provider["timeout"]),
        thinking=normalize_openclaw_thinking(str(tier["reasoning"])),
        fps=float(provider.get("fps") or 0),
    )


def resolve_provider_base_url(value: str) -> str:
    configured = str(value or "").strip()
    if not configured.startswith(BASE_URL_ENV_PREFIX):
        return configured.rstrip("/")
    expression = configured.removeprefix(BASE_URL_ENV_PREFIX)
    env_name, separator, suffix = expression.partition("/")
    base_url = str(os.getenv(env_name) or "").strip().rstrip("/")
    if not env_name or not base_url:
        raise RuntimeError(f"OpenClaw Bot LLM provider endpoint environment variable is unavailable: {env_name}")
    if not separator:
        return base_url
    return f"{base_url}/{suffix.lstrip('/')}"
