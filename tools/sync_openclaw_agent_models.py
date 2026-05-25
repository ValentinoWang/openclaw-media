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
TARGET_AGENT_NAMES = (
    "main",
    "feishu-main",
    "feishu-daily",
    "feishu-knowledge",
    "feishu-media",
    "feishu-social",
)


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
    if value.startswith("openai-codex/"):
        return value[len("openai-codex/") :]
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


def _canonical_model_ref(provider_name: str, model_id: str) -> str:
    runtime_provider = "openai-codex" if provider_name == "openclaw_codex" else provider_name
    normalized = _normalized_model(model_id)
    return f"{runtime_provider}/{normalized}" if runtime_provider and normalized else ""


def build_models_payload(payload: dict[str, Any]) -> dict[str, Any]:
    providers = payload.get("providers") or {}

    codex_models = _collect_models_for_provider(payload, "openclaw_codex")
    main_models = _collect_models_for_provider(payload, "main_llm")
    qwen_models = _collect_models_for_provider(payload, "qwen")

    built: dict[str, Any] = {"providers": {}}
    built["providers"]["openai-codex"] = {
        "baseUrl": "https://chatgpt.com/backend-api",
        "api": "openai-codex-responses",
        "models": _build_model_entries(
            codex_models,
            reasoning=True,
            with_image=True,
            api="openai-codex-responses",
            context_window=1050000,
            max_tokens=128000,
        ),
    }

    main_provider = providers.get("main_llm") or {}
    built["providers"]["main_llm"] = {
        "baseUrl": str(main_provider.get("base_url") or "").strip(),
        "apiKey": str(main_provider.get("api_key") or "").strip(),
        "api": "openai-completions",
        "models": _build_model_entries(
            main_models,
            reasoning=bool(str(main_provider.get("thinking") or "").strip()),
            with_image=True,
            api="openai-completions",
            context_window=262144,
            max_tokens=65536,
        ),
    }

    qwen_provider = providers.get("qwen") or {}
    built["providers"]["qwen"] = {
        "baseUrl": str(qwen_provider.get("base_url") or "").strip(),
        "apiKey": str(qwen_provider.get("api_key") or "").strip(),
        "api": "openai-completions",
        "models": _build_model_entries(
            qwen_models,
            reasoning=bool(str(qwen_provider.get("thinking") or "").strip()),
            with_image=True,
            api="openai-completions",
            context_window=1000000,
            max_tokens=65536,
        ),
    }
    return built


def build_allowed_model_refs(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for provider_name in ("openclaw_codex", "main_llm", "qwen"):
        for model_id in _collect_models_for_provider(payload, provider_name):
            ref = _canonical_model_ref(provider_name, model_id)
            if ref and ref not in refs:
                refs.append(ref)
    return refs


def sync_openclaw_gateway_config(payload: dict[str, Any], *, dry_run: bool) -> str:
    parsed = json.loads(OPENCLAW_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise SystemExit(f"invalid openclaw config json: {OPENCLAW_CONFIG}")

    built_models = build_models_payload(payload)
    allowed_refs = build_allowed_model_refs(payload)
    codex_refs = [_canonical_model_ref("openclaw_codex", item) for item in _collect_models_for_provider(payload, "openclaw_codex")]
    codex_refs = [item for item in codex_refs if item]

    agents = parsed.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    openclaw_provider = (payload.get("providers") or {}).get("openclaw_codex") or {}
    defaults["thinkingDefault"] = str(openclaw_provider.get("thinking") or "high").strip().lower()
    defaults["timeoutSeconds"] = max(30, int(float(openclaw_provider.get("timeout") or 1800)))
    defaults["model"] = {
        "primary": codex_refs[0] if codex_refs else (allowed_refs[0] if allowed_refs else "openai-codex/gpt-5.5"),
        "fallbacks": codex_refs[1:],
    }
    defaults["models"] = {ref: {} for ref in allowed_refs}

    for agent in agents.get("list", []):
        if isinstance(agent, dict):
            agent.pop("model", None)

    parsed["models"] = {"providers": built_models["providers"]}
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
