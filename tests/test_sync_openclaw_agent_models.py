from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path("/home/ubuntu/selfmedia-tools/tools/sync_openclaw_agent_models.py")
SPEC = importlib.util.spec_from_file_location("sync_openclaw_agent_models", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_build_models_payload_uses_unified_config() -> None:
    payload = MODULE.load_payload()
    built = MODULE.build_models_payload(payload)
    providers = built["providers"]
    assert set(providers) == {"openai-codex", "main_llm", "qwen"}

    codex_models = [item["id"] for item in providers["openai-codex"]["models"]]
    assert "gpt-5.5" in codex_models
    assert codex_models == ["gpt-5.5"]

    main_models = [item["id"] for item in providers["main_llm"]["models"]]
    assert main_models == ["deepseek-v4-pro"]
    assert providers["main_llm"]["baseUrl"] == "https://api.deepseek.com"
    assert providers["main_llm"]["api"] == "openai-completions"

    qwen_models = [item["id"] for item in providers["qwen"]["models"]]
    assert qwen_models == ["qwen3.5-plus"]


def test_allowed_model_refs_cover_runtime_catalog() -> None:
    payload = MODULE.load_payload()
    refs = MODULE.build_allowed_model_refs(payload)
    assert refs == [
        "openai-codex/gpt-5.5",
        "main_llm/deepseek-v4-pro",
        "qwen/qwen3.5-plus",
    ]
