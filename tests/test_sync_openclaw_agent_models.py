from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "runtime/maintenance/deploy/sync_openclaw_agent_models.py"
SPEC = importlib.util.spec_from_file_location("sync_openclaw_agent_models", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_build_models_payload_uses_unified_config() -> None:
    payload = MODULE.load_payload()
    built = MODULE.build_models_payload(payload)
    assert built == {
        "providers": {
            "codex": {
                "agentRuntime": {"id": "codex"},
                "baseUrl": MODULE.canonical_openai_base_url(),
                "models": [
                    {"id": "gpt-5.6-terra", "name": "gpt-5.6-terra"},
                    {"id": "gpt-5.6-sol", "name": "gpt-5.6-sol"},
                    {"id": "gpt-5.6-luna", "name": "gpt-5.6-luna"},
                ]
            }
        }
    }


def test_allowed_model_refs_cover_runtime_catalog() -> None:
    payload = MODULE.load_payload()
    refs = MODULE.build_allowed_model_refs(payload)
    assert refs == [
        "codex/gpt-5.6-terra",
        "codex/gpt-5.6-sol",
        "codex/gpt-5.6-luna",
    ]


def test_repo_config_has_no_secondary_model_key() -> None:
    payload = MODULE.load_payload()
    assert "fallback_models" not in payload["providers"]["openclaw_codex"]
    assert all("model" not in provider for provider in payload["providers"].values())
    assert all("thinking" not in bot for bot in payload["bots"].values())
    assert all("thinking" not in profile for profile in payload["profiles"].values())


def test_repo_config_explicitly_disables_default_heartbeat() -> None:
    payload = MODULE.load_payload()
    assert payload["openclaw_runtime"]["heartbeat_every"] == "0m"
    assert payload["openclaw_runtime"]["session_maintenance"] == {
        "mode": "enforce",
        "prune_after": "14d",
        "reset_archive_retention": "14d",
    }


def test_repo_config_allows_long_structured_codex_turns() -> None:
    payload = MODULE.load_payload()
    assert payload["openclaw_runtime"]["codex_app_server"]["turn_completion_idle_timeout_ms"] == 180000
    assert MODULE._codex_app_server(payload)["turnCompletionIdleTimeoutMs"] == 180000


def test_openclaw_thinking_default_normalizes_codex_aliases() -> None:
    assert MODULE._openclaw_thinking("xhigh") == "high"
    assert MODULE._openclaw_thinking("max") == "high"
    assert MODULE._openclaw_thinking("high") == "high"
    assert MODULE._openclaw_thinking("invalid") == "high"


def test_gateway_sync_uses_tier_resolved_primary_and_catalog(tmp_path, monkeypatch) -> None:
    gateway_config = tmp_path / "openclaw.json"
    gateway_config.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {},
                    "list": [
                        {"id": "feishu-main"},
                        {"id": "feishu-daily"},
                        {"id": "feishu-knowledge"},
                        {"id": "feishu-media"},
                        {"id": "feishu-social"},
                        {"id": "openclaw-maintenance"},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(MODULE, "OPENCLAW_CONFIG", gateway_config)

    MODULE.sync_openclaw_gateway_config(MODULE.load_payload(), dry_run=False)

    synced = json.loads(gateway_config.read_text(encoding="utf-8"))
    defaults = synced["agents"]["defaults"]
    assert defaults["model"] == {"primary": "codex/gpt-5.6-terra"}
    assert defaults["models"] == {
        "codex/gpt-5.6-luna": {},
        "codex/gpt-5.6-terra": {},
        "codex/gpt-5.6-sol": {},
    }
    assert synced["models"] == MODULE.build_models_payload(MODULE.load_payload())
    assert defaults["thinkingDefault"] == "high"
    assert synced["session"]["maintenance"] == {
        "mode": "enforce",
        "pruneAfter": "14d",
        "resetArchiveRetention": "14d",
    }
    agents = {agent["id"]: agent for agent in synced["agents"]["list"]}
    assert synced["plugins"]["entries"]["codex"] == {
        "enabled": True,
        "config": {"appServer": MODULE._codex_app_server(MODULE.load_payload())},
    }
    assert agents["feishu-knowledge"]["model"] == {"primary": "codex/gpt-5.6-terra"}
    assert agents["feishu-knowledge"]["thinkingDefault"] == "high"
    assert agents["feishu-media"]["model"] == {"primary": "codex/gpt-5.6-sol"}
    assert agents["feishu-media"]["thinkingDefault"] == "medium"
    assert agents["feishu-main"]["model"] == {"primary": "codex/gpt-5.6-terra"}
    assert agents["feishu-main"]["thinkingDefault"] == "high"
    assert agents["feishu-daily"]["model"] == {"primary": "codex/gpt-5.6-terra"}
    assert agents["feishu-daily"]["thinkingDefault"] == "medium"
    assert agents["feishu-social"]["model"] == {"primary": "codex/gpt-5.6-terra"}
    assert agents["feishu-social"]["thinkingDefault"] == "high"
    assert agents["openclaw-maintenance"]["model"] == {"primary": "codex/gpt-5.6-sol"}
    assert agents["openclaw-maintenance"]["thinkingDefault"] == "medium"
