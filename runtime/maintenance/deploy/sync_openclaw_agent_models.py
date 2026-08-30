#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.env import parse_env_file  # noqa: E402


# The editable configuration SSOT lives in this repository; the env override
# keeps the deployed host's split layout working.
REPO_CONFIG = Path(
    os.getenv("OPENCLAW_BOTS_CONFIG")
    or Path(__file__).resolve().parents[3] / "config/openclaw_bots.json"
)
OPENCLAW_RUNTIME_HOME = Path(os.getenv("OPENCLAW_RUNTIME_HOME") or Path.home() / ".openclaw")
OPENAI_ENV = Path(os.getenv("OPENCLAW_OPENAI_ENV") or Path.home() / ".config/codex/openai.env")
AGENTS_ROOT = Path(os.getenv("OPENCLAW_AGENTS_ROOT") or OPENCLAW_RUNTIME_HOME / "agents")
OPENCLAW_CONFIG = Path(os.getenv("OPENCLAW_CONFIG_PATH") or OPENCLAW_RUNTIME_HOME / "openclaw.json")
CODEX_MODEL_PROVIDER = "codex"
OPENCLAW_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high"}
OPENCLAW_THINKING_ALIASES = {
    "xhigh": "high",
    "max": "high",
    "adaptive": "high",
}
CODEX_APP_SERVER_ARGS = ["app-server", "--listen", "stdio://"]
CODEX_APP_SERVER_SERVICE_TIER = "priority"
RUNTIME_HEARTBEAT_EVERY = "0m"
RUNTIME_SESSION_MAINTENANCE = {
    "mode": "enforce",
    "pruneAfter": "14d",
    "resetArchiveRetention": "14d",
}


def canonical_openai_base_url() -> str:
    if not OPENAI_ENV.is_file():
        raise SystemExit(f"missing required OpenAI environment file: {OPENAI_ENV}; set OPENCLAW_OPENAI_ENV")
    values = parse_env_file(OPENAI_ENV)
    base_url = values.get("OPENAI_BASE_URL", "").rstrip("/")
    if not base_url.startswith(("https://", "http://")):
        raise SystemExit(f"OPENAI_BASE_URL must be an absolute URL in {OPENAI_ENV}")
    return base_url


def load_payload() -> dict[str, Any]:
    if not REPO_CONFIG.is_file():
        raise SystemExit(f"missing required repository config: {REPO_CONFIG}; set OPENCLAW_BOTS_CONFIG")
    payload = json.loads(REPO_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid config json: {REPO_CONFIG}")
    return payload


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(tmp_name).replace(path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def _normalized_model(model: str) -> str:
    value = str(model or "").strip()
    for prefix in (f"{CODEX_MODEL_PROVIDER}/",):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def _collect_models_for_provider(payload: dict[str, Any], provider_name: str) -> list[str]:
    providers = payload.get("providers") or {}
    bots = payload.get("bots") or {}
    profiles = payload.get("profiles") or {}
    model_tiers = payload.get("model_tiers") or {}
    models: list[str] = []

    provider = providers.get(provider_name) or {}
    if not isinstance(provider, dict):
        return models

    def add_model(scope: dict[str, Any], bot: dict[str, Any] | None = None) -> None:
        tier_name = str(
            scope.get("model_tier")
            or (bot or {}).get("model_tier")
            or provider.get("default_model_tier")
            or ""
        ).strip()
        tier = model_tiers.get(tier_name) if tier_name else None
        model = _normalized_model(tier.get("model") if isinstance(tier, dict) else "")
        if model:
            models.append(model)

    add_model(provider)
    for bot in bots.values():
        if not isinstance(bot, dict):
            continue
        if str(bot.get("provider") or "").strip() != provider_name:
            continue
        add_model(bot)

    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        bot_name = str(profile.get("bot") or "").strip()
        bot = bots.get(bot_name) if bot_name else {}
        resolved_provider = str(profile.get("provider") or (bot or {}).get("provider") or "").strip()
        if resolved_provider != provider_name:
            continue
        add_model(profile, bot if isinstance(bot, dict) else None)

    for override in (payload.get("agent_overrides") or {}).values():
        if isinstance(override, dict):
            add_model(override)

    # The gateway catalog is the allowlist for every approved tier, including a
    # tier that is intentionally not bound to a current Bot/profile yet.
    for tier in model_tiers.values():
        if isinstance(tier, dict):
            model = _normalized_model(str(tier.get("model") or ""))
            if model:
                models.append(model)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in models:
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _agent_tier_assignments(payload: dict[str, Any]) -> dict[str, str]:
    providers = payload.get("providers") or {}
    default_provider = _runtime_provider_name(payload)
    assignments: dict[str, str] = {}

    for bot in (payload.get("bots") or {}).values():
        if not isinstance(bot, dict) or str(bot.get("provider") or "").strip() != default_provider:
            continue
        agent_name = str(bot.get("agent") or "").strip()
        provider = providers.get(default_provider) or {}
        tier_name = str(bot.get("model_tier") or provider.get("default_model_tier") or "").strip()
        if agent_name and tier_name:
            assignments[agent_name] = tier_name

    for agent_name, override in (payload.get("agent_overrides") or {}).items():
        if not isinstance(override, dict):
            continue
        tier_name = str(override.get("model_tier") or "").strip()
        if str(agent_name).strip() and tier_name:
            assignments[str(agent_name).strip()] = tier_name
    return assignments


def _tier(payload: dict[str, Any], tier_name: str) -> dict[str, Any]:
    tier = (payload.get("model_tiers") or {}).get(tier_name)
    if not isinstance(tier, dict) or not tier.get("model") or not tier.get("reasoning"):
        raise SystemExit(f"invalid model tier: {tier_name!r}")
    return tier


def _build_model_entries(models: list[str], *, reasoning: bool, with_image: bool, api: str, context_window: int, max_tokens: int) -> list[dict[str, Any]]:
    inputs = ["text", "image"] if with_image else ["text"]
    return [
        {
            "id": model,
            "name": model,
            "reasoning": reasoning,
            "input": inputs,
            "contextWindow": context_window,
            "maxTokens": max_tokens,
            "api": api,
        }
        for model in models
    ]


def _provider_timeout_seconds(provider: dict[str, Any], *, default: float) -> int:
    raw_timeout = provider.get("timeoutSeconds")
    if raw_timeout is None:
        raw_timeout = provider.get("timeout")
    try:
        return max(30, int(float(raw_timeout if raw_timeout is not None else default)))
    except (TypeError, ValueError):
        return max(30, int(float(default)))


def _openclaw_thinking(value: Any, *, default: str = "high") -> str:
    normalized = str(value or default).strip().lower()
    normalized = OPENCLAW_THINKING_ALIASES.get(normalized, normalized)
    if normalized not in OPENCLAW_THINKING_LEVELS:
        return default
    return normalized


def _canonical_model_ref(provider_name: str, model_id: str) -> str:
    if "/" in str(model_id or ""):
        return str(model_id).strip()
    runtime_provider = CODEX_MODEL_PROVIDER if provider_name == "openclaw_codex" else provider_name
    normalized = _normalized_model(model_id)
    return f"{runtime_provider}/{normalized}" if runtime_provider and normalized else ""


def _runtime_provider_name(payload: dict[str, Any]) -> str:
    policy = payload.get("policy") or {}
    provider_name = str(policy.get("openclaw_runtime_provider") or policy.get("default_provider") or "").strip()
    if not provider_name:
        raise SystemExit("policy.openclaw_runtime_provider must be configured")
    return provider_name


def _resolve_executable(command: str) -> str:
    candidate = Path(command).expanduser()
    if candidate.is_absolute() or "/" in command:
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else ""
    return shutil.which(command) or ""


def _codex_app_server(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = payload.get("openclaw_runtime") if isinstance(payload.get("openclaw_runtime"), dict) else {}
    app_server = runtime.get("codex_app_server") if isinstance(runtime.get("codex_app_server"), dict) else {}
    command = str(app_server.get("command") or "").strip()
    turn_completion_idle_timeout_ms = app_server.get("turn_completion_idle_timeout_ms")
    version = str(app_server.get("version") or "").strip()
    executable = _resolve_executable(command) if command else ""
    if not executable:
        raise SystemExit("openclaw_runtime.codex_app_server.command must resolve to an executable file or PATH command")
    if not isinstance(turn_completion_idle_timeout_ms, int) or turn_completion_idle_timeout_ms < 60000:
        raise SystemExit(
            "openclaw_runtime.codex_app_server.turn_completion_idle_timeout_ms must be an integer >= 60000"
        )
    if not version:
        raise SystemExit("openclaw_runtime.codex_app_server.version must be configured")
    try:
        actual_version = subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip().split()[-1]
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError) as exc:
        raise SystemExit("unable to verify openclaw_runtime.codex_app_server.command version") from exc
    if actual_version != version:
        raise SystemExit(
            "openclaw_runtime.codex_app_server.version drifted: "
            f"expected {version!r}, got {actual_version!r}"
        )
    return {
        "command": command,
        "args": list(CODEX_APP_SERVER_ARGS),
        "serviceTier": CODEX_APP_SERVER_SERVICE_TIER,
        "turnCompletionIdleTimeoutMs": turn_completion_idle_timeout_ms,
    }


def build_models_payload(payload: dict[str, Any]) -> dict[str, Any]:
    provider_name = _runtime_provider_name(payload)
    runtime_provider = CODEX_MODEL_PROVIDER if provider_name == "openclaw_codex" else provider_name
    models = _collect_models_for_provider(payload, provider_name)
    if not runtime_provider or not models:
        raise SystemExit("no runtime provider model catalog resolved from model_tiers")
    return {
        "providers": {
            runtime_provider: {
                "agentRuntime": {"id": "codex"},
                "baseUrl": canonical_openai_base_url(),
                "models": [{"id": model, "name": model} for model in models],
            }
        }
    }


def build_allowed_model_refs(payload: dict[str, Any]) -> list[str]:
    default_provider = _runtime_provider_name(payload)
    refs: list[str] = []
    for model_id in _collect_models_for_provider(payload, default_provider):
        ref = _canonical_model_ref(default_provider, model_id)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def sync_openclaw_gateway_config(payload: dict[str, Any], *, dry_run: bool) -> str:
    parsed = json.loads(OPENCLAW_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise SystemExit(f"invalid openclaw config json: {OPENCLAW_CONFIG}")

    allowed_refs = build_allowed_model_refs(payload)
    if not allowed_refs:
        raise SystemExit("no model refs resolved from policy.openclaw_runtime_provider")
    default_provider = _runtime_provider_name(payload)

    agents = parsed.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    provider_config = (payload.get("providers") or {}).get(default_provider) or {}
    tier_name = str(provider_config.get("default_model_tier") or "").strip()
    tier = _tier(payload, tier_name)
    defaults["thinkingDefault"] = _openclaw_thinking(tier["reasoning"])
    defaults["timeoutSeconds"] = max(30, int(float(provider_config.get("timeout") or 1800)))
    defaults["model"] = {"primary": allowed_refs[0]}
    defaults["models"] = {ref: {} for ref in allowed_refs}
    defaults["heartbeat"] = {"every": RUNTIME_HEARTBEAT_EVERY}
    session = parsed.setdefault("session", {})
    session["maintenance"] = dict(RUNTIME_SESSION_MAINTENANCE)
    plugins = parsed.setdefault("plugins", {})
    allow = plugins.get("allow")
    if isinstance(allow, list):
        plugins["allow"] = [item for item in allow if item != "openai"]
    entries = plugins.setdefault("entries", {})
    entries.pop("openai", None)
    codex = entries.setdefault("codex", {})
    codex["enabled"] = True
    codex["config"] = {"appServer": _codex_app_server(payload)}

    agent_tiers = _agent_tier_assignments(payload)
    for agent in agents.get("list", []):
        if isinstance(agent, dict):
            agent_name = str(agent.get("id") or agent.get("name") or "").strip()
            tier_name = agent_tiers.get(agent_name)
            if not tier_name:
                continue
            agent_tier = _tier(payload, tier_name)
            model_ref = _canonical_model_ref(default_provider, str(agent_tier["model"]))
            if not model_ref:
                raise SystemExit(f"invalid model for agent {agent_name}: {tier_name!r}")
            agent["model"] = {"primary": model_ref}
            agent["thinkingDefault"] = _openclaw_thinking(agent_tier["reasoning"])

    secret_providers = parsed.get("secrets", {}).get("providers") if isinstance(parsed.get("secrets"), dict) else None
    if isinstance(secret_providers, dict):
        secret_providers.pop("codex-auth-json", None)
    parsed["models"] = build_models_payload(payload)
    text = json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
    if not dry_run:
        atomic_write(OPENCLAW_CONFIG, text)
    return str(OPENCLAW_CONFIG)


def remove_empty_agent_model_catalogs(payload: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Remove former empty per-agent catalogs; the global generated catalog is canonical."""
    removed: list[str] = []
    agent_names = {"main", *_agent_tier_assignments(payload)}
    for agent_name in sorted(agent_names):
        target = AGENTS_ROOT / agent_name / "agent" / "models.json"
        if not target.exists():
            continue
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid former per-agent model catalog: {target}") from exc
        if existing != {"providers": {}}:
            raise SystemExit(f"refusing to remove non-empty per-agent model catalog: {target}")
        if not dry_run:
            target.unlink()
        removed.append(str(target))
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OpenClaw agent models.json from selfmedia openclaw_bots.json.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = load_payload()
    removed = remove_empty_agent_model_catalogs(payload, dry_run=args.dry_run)
    gateway_config = sync_openclaw_gateway_config(payload, dry_run=args.dry_run)
    print(json.dumps({"ok": True, "removed_empty_agent_catalogs": removed, "gateway_config": gateway_config, "dry_run": args.dry_run}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
