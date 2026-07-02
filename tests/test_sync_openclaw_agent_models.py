from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path("/home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/sync_openclaw_agent_models.py")
SPEC = importlib.util.spec_from_file_location("sync_openclaw_agent_models", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_build_models_payload_uses_unified_config() -> None:
    payload = MODULE.load_payload()
    built = MODULE.build_models_payload(payload)
    assert built == {"providers": {}}


def test_allowed_model_refs_cover_runtime_catalog() -> None:
    payload = MODULE.load_payload()
    refs = MODULE.build_allowed_model_refs(payload)
    default_provider = payload["policy"]["openclaw_runtime_provider"]
    assert refs == [payload["providers"][default_provider]["model"]]


def test_repo_config_has_no_secondary_model_key() -> None:
    payload = MODULE.load_payload()
    assert "fallback_models" not in payload["providers"]["openclaw_codex"]


def test_openclaw_thinking_default_normalizes_codex_aliases() -> None:
    assert MODULE._openclaw_thinking("xhigh") == "high"
    assert MODULE._openclaw_thinking("max") == "high"
    assert MODULE._openclaw_thinking("high") == "high"
    assert MODULE._openclaw_thinking("invalid") == "high"
