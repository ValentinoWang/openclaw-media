from __future__ import annotations

from types import SimpleNamespace

import pytest

from selfmedia.deconstruct.viral_content.src.config import ViralDeconstructConfig
from selfmedia.deconstruct.viral_content.src import llm_client


def _config(**overrides):
    values = {
        "model": "gpt-5.5",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "api_key": "codex_auth_file",
        "timeout": 60.0,
        "source_assets_url": "",
        "material_deconstructions_url": "",
        "feishu_doc_folder_token": "",
        "feishu_wiki_parent_node_token": "",
        "feishu_deconstruct_parent_node_token": "",
        "feishu_recreate_parent_node_token": "",
        "part1_path": "/tmp",
        "llm_api_type": "openai_codex_responses",
        "thinking": "",
        "bin": "",
        "agent": "",
        "cwd": "",
        "codex_home": "",
    }
    values.update(overrides)
    return ViralDeconstructConfig(**values)


def test_text_llm_can_route_to_openclaw_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    runtime = SimpleNamespace(
        bin="/bin/openclaw",
        agent="feishu-media",
        cwd="/tmp",
        codex_home="/tmp/codex-home",
        thinking="low",
        timeout=60,
    )

    def fake_run(command, cwd=None, env=None, text=None, capture_output=None, timeout=None, check=None):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        return SimpleNamespace(
            returncode=0,
            stdout='{"result":{"payloads":[{"text":"{\\"ok\\":true}"}]}}',
            stderr="",
        )

    monkeypatch.setenv("OPENCLAW_DECONSTRUCT_TEXT_LLM_VIA_AGENT", "1")
    monkeypatch.setattr(llm_client, "bot_runtime", lambda name: runtime)
    monkeypatch.setattr(llm_client, "openclaw_subprocess_env", lambda codex_home: {"CODEX_HOME": codex_home})
    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)

    result = llm_client._generate_json_once([{"text": "return json"}], _config())

    assert result == {"ok": True}
    assert captured["command"][:4] == ["/bin/openclaw", "agent", "--agent", "feishu-media"]
    assert "--model" not in captured["command"]
    assert captured["cwd"] == "/tmp"


def test_text_agent_env_does_not_capture_image_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setenv("OPENCLAW_DECONSTRUCT_TEXT_LLM_VIA_AGENT", "1")
    monkeypatch.setattr(llm_client, "common_generate_json_once", lambda parts, settings: calls.append("direct") or {"ok": True})

    result = llm_client._generate_json_once(
        [{"text": "return json"}, {"image_data": {"data": "xxx", "mime_type": "image/jpeg"}}],
        _config(),
    )

    assert result == {"ok": True}
    assert calls == ["direct"]
