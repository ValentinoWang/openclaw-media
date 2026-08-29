from __future__ import annotations

import pytest

from selfmedia.deconstruct.viral_content.src.config import ViralDeconstructConfig
from selfmedia.deconstruct.viral_content.src import llm_client


def _config(**overrides):
    values = {
        "model": "gpt-5.5",
        "base_url": "https://example.com/v1",
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


def test_deconstruction_uses_common_openclaw_json_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_generate(parts, settings, **kwargs):
        captured["parts"] = parts
        captured["settings"] = settings
        return {"ok": True}

    monkeypatch.setattr(llm_client, "common_generate_json_from_parts", fake_generate)

    result = llm_client.generate_json(
        [{"text": "return json"}],
        _config(
            llm_api_type="openclaw_agent",
            base_url="openclaw://agent",
            bin="/bin/openclaw",
            agent="feishu-media",
            cwd="/tmp",
            codex_home="/tmp/codex-home",
        ),
    )

    assert result == {"ok": True}
    assert captured["parts"] == [{"text": "return json"}]
    settings = captured["settings"]
    assert settings.api_type == "openclaw_agent"
    assert settings.agent == "feishu-media"


def test_openclaw_agent_images_use_the_same_common_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[dict], str]] = []

    def fake_generate(parts, settings, **kwargs):
        calls.append((parts, settings.api_type))
        return {"ok": True}

    monkeypatch.setattr(llm_client, "common_generate_json_from_parts", fake_generate)

    result = llm_client.generate_json(
        [{"text": "return json"}, {"image_data": {"data": "xxx", "mime_type": "image/jpeg"}}],
        _config(
            llm_api_type="openclaw_agent",
            base_url="openclaw://agent",
            bin="/bin/openclaw",
            agent="feishu-media",
            cwd="/tmp",
            codex_home="/tmp/codex-home",
        ),
    )

    assert result == {"ok": True}
    assert calls[0][1] == "openclaw_agent"
    assert "image_data" in calls[0][0][1]
