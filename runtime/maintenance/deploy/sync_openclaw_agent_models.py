#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


REPO_CONFIG = Path("/home/ubuntu/selfmedia-tools/config/openclaw_bots.json")
AGENTS_ROOT = Path("/home/ubuntu/.openclaw/agents")
OPENCLAW_CONFIG = Path("/home/ubuntu/.openclaw/openclaw.json")
CODEX_MODEL_PROVIDER = "openai-codex"
TARGET_AGENT_NAMES = (
    "main",
    "feishu-main",
    "feishu-daily",
    "feishu-knowledge",
    "feishu-media",
    "feishu-social",
    "openclaw-maintenance",
)
OPENCLAW_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high"}
OPENCLAW_THINKING_ALIASES = {
    "xhigh": "high",
    "max": "high",
    "adaptive": "high",
}


def load_payload() -> dict[str, Any]:
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
    models: list[str] = []

    provider = providers.get(provider_name) or {}
    model = _normalized_model(provider.get("model") or "")
    if model:
        models.append(model)

    for bot in bots.values():
        if not isinstance(bot, dict):
            continue
        if str(bot.get("provider") or "").strip() != provider_name:
            continue
        model = _normalized_model(bot.get("model") or "")
        if model:
            models.append(model)

    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        bot_name = str(profile.get("bot") or "").strip()
        bot = bots.get(bot_name) if bot_name else {}
        resolved_provider = str(profile.get("provider") or (bot or {}).get("provider") or "").strip()
        if resolved_provider != provider_name:
            continue
        model = _normalized_model(profile.get("model") or "")
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


def build_models_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {"providers": {}}


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
    defaults["thinkingDefault"] = _openclaw_thinking(provider_config.get("thinking"))
    defaults["timeoutSeconds"] = max(30, int(float(provider_config.get("timeout") or 1800)))
    defaults["model"] = {"primary": allowed_refs[0]}
    defaults["models"] = {ref: {} for ref in allowed_refs}

    for agent in agents.get("list", []):
        if isinstance(agent, dict):
            agent.pop("model", None)
            if "thinkingDefault" in agent:
                agent["thinkingDefault"] = _openclaw_thinking(agent.get("thinkingDefault"), default=defaults["thinkingDefault"])

    secret_providers = parsed.get("secrets", {}).get("providers") if isinstance(parsed.get("secrets"), dict) else None
    if isinstance(secret_providers, dict):
        secret_providers.pop("codex-auth-json", None)
    parsed.pop("models", None)
    text = json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
    if not dry_run:
        atomic_write(OPENCLAW_CONFIG, text)
    return str(OPENCLAW_CONFIG)


def write_runtime_models(payload: dict[str, Any], *, dry_run: bool) -> list[str]:
    models_payload = build_models_payload(payload)
    text = json.dumps(models_payload, ensure_ascii=False, indent=2) + "\n"
    written: list[str] = []
    for agent_name in TARGET_AGENT_NAMES:
        target = AGENTS_ROOT / agent_name / "agent" / "models.json"
        if dry_run:
            written.append(str(target))
            continue
        atomic_write(target, text)
        written.append(str(target))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OpenClaw agent models.json from selfmedia openclaw_bots.json.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = load_payload()
    written = write_runtime_models(payload, dry_run=args.dry_run)
    gateway_config = sync_openclaw_gateway_config(payload, dry_run=args.dry_run)
    print(json.dumps({"ok": True, "targets": written, "gateway_config": gateway_config, "dry_run": args.dry_run}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
