from __future__ import annotations

import json
import sys
from pathlib import Path

from _support import load_script_module


MODULE_PATH = Path(__file__).resolve().parents[1] / "runtime/maintenance/deploy/sync_openclaw_bot_config.py"
MODULE = load_script_module("sync_openclaw_bot_config", MODULE_PATH)


def _payload() -> dict[str, object]:
    return {
        "defaults": {},
        "model_tiers": {"L": {"model": "gpt-5.6-luna", "reasoning": "low"}},
        "bots": {},
        "profiles": {},
        "providers": {},
    }


def test_restart_services_is_noop_when_config_is_unchanged(tmp_path, monkeypatch, capsys) -> None:
    repo_config = tmp_path / "repo/openclaw_bots.json"
    obsidian_dir = tmp_path / "obsidian"
    obsidian_config = obsidian_dir / "openclaw_bots.json"
    obsidian_note = obsidian_dir / "OpenClaw Bot LLM 配置.md"
    llm_usage_note = tmp_path / "knowledge/OpenClaw Bot LLM 使用矩阵 SSOT.md"
    sync_state = obsidian_dir / ".openclaw_bots_sync_state.json"
    payload = _payload()
    repo_config.parent.mkdir(parents=True)
    obsidian_dir.mkdir(parents=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    repo_config.write_text(text, encoding="utf-8")
    obsidian_config.write_text(text, encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> None:
        calls.append(command)

    monkeypatch.setattr(MODULE, "REPO_CONFIG", repo_config)
    monkeypatch.setattr(MODULE, "OBSIDIAN_DIR", obsidian_dir)
    monkeypatch.setattr(MODULE, "OBSIDIAN_CONFIG", obsidian_config)
    monkeypatch.setattr(MODULE, "OBSIDIAN_NOTE", obsidian_note)
    monkeypatch.setattr(MODULE, "PUBLIC_KNOWLEDGE_DIR", llm_usage_note.parent)
    monkeypatch.setattr(MODULE, "LLM_USAGE_SSOT_NOTE", llm_usage_note)
    monkeypatch.setattr(MODULE, "SYNC_STATE", sync_state)
    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["sync_openclaw_bot_config.py", "--restart-services"])

    MODULE.main()

    output = json.loads(capsys.readouterr().out)
    assert output["config_changed"] is False
    assert output["restarted_services"] is False
    assert output["llm_usage_ssot_note"] == str(llm_usage_note)
    assert calls == []
    assert llm_usage_note.is_file()
    assert "OpenClaw Bot LLM 使用矩阵 SSOT" in llm_usage_note.read_text(encoding="utf-8")


def test_render_llm_usage_ssot_includes_profile_and_non_profile_paths() -> None:
    payload = {
        "defaults": {},
        "model_tiers": {
            "L": {"model": "gpt-5.6-luna", "reasoning": "low"},
            "A": {"model": "gpt-5.6-terra", "reasoning": "medium"},
            "B": {"model": "gpt-5.6-terra", "reasoning": "high"},
            "C": {"model": "gpt-5.6-sol", "reasoning": "medium"},
        },
        "bots": {
            "media": {"provider": "openclaw_codex", "agent": "feishu-media", "cwd": "/agents/media", "model_tier": "C"},
            "social": {"provider": "openclaw_codex", "agent": "feishu-social", "cwd": "/agents/social", "model_tier": "B"},
            "main": {"provider": "openclaw_codex", "agent": "feishu-main", "cwd": "/agents/main", "model_tier": "B"},
            "daily": {"provider": "openclaw_codex", "agent": "feishu-daily", "cwd": "/agents/daily", "model_tier": "A"},
            "knowledge": {"provider": "openclaw_codex", "agent": "feishu-knowledge", "cwd": "/agents/knowledge", "model_tier": "B"},
        },
        "profiles": {
            "media_creation": {"provider": "openclaw_codex", "bot": "media", "model_tier": "C"},
            "media_analysis": {"provider": "openclaw_codex", "bot": "media", "model_tier": "B"},
            "social_vision": {"provider": "openclaw_codex", "bot": "social", "model_tier": "C"},
        },
        "providers": {
            "openclaw_codex": {
                "default_model_tier": "B",
                "base_url": "openclaw://agent",
                "api_key": "codex_auth_file",
                "api_type": "openclaw_agent",
                "timeout": 1800,
                "bin": "/bin/openclaw",
                "codex_home": "/home/ubuntu/.codex",
            },
        },
    }

    rendered = MODULE.render_llm_usage_ssot(payload, "hash")

    assert "media_creation" in rendered
    assert "03 拆解关键帧/图文图片理解" in rendered
    assert "01 ingest 原始音频转写" in rendered
    assert "gpt-5.6-sol" in rendered
    assert "已配置" in rendered


def test_sync_agent_models_uses_the_sibling_script_by_default() -> None:
    assert MODULE.SYNC_AGENT_MODELS == MODULE_PATH.with_name("sync_openclaw_agent_models.py")
