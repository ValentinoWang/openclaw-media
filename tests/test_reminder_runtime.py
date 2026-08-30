from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.maintenance import reminder_runtime


def test_reminder_script_path_honors_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override = tmp_path / "custom-reminder.py"
    monkeypatch.setenv("OPENCLAW_FEISHU_REMINDER_SCRIPT", str(override))
    assert reminder_runtime.reminder_script_path() == override


def test_reminder_script_path_defaults_under_reminder_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENCLAW_FEISHU_REMINDER_SCRIPT", raising=False)
    monkeypatch.setenv("OPENCLAW_FEISHU_REMINDER_ROOT", str(tmp_path))
    assert reminder_runtime.reminder_script_path() == tmp_path / "reminder.py"


def test_activity_config_path_defaults_under_reminder_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENCLAW_ACTIVITY_CONFIG_PATH", raising=False)
    monkeypatch.setenv("OPENCLAW_FEISHU_REMINDER_ROOT", str(tmp_path))
    assert reminder_runtime.activity_config_path() == tmp_path / "wiki-activity-config.json"


def test_daily_config_path_defaults_under_reminder_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENCLAW_DAILY_CONFIG_PATH", raising=False)
    monkeypatch.setenv("OPENCLAW_FEISHU_REMINDER_ROOT", str(tmp_path))
    assert reminder_runtime.daily_config_path() == tmp_path / "config.json"


def test_load_reminder_module_raises_recovery_hint_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing-reminder.py"
    with pytest.raises(SystemExit, match="OPENCLAW_FEISHU_REMINDER_SCRIPT"):
        reminder_runtime.load_reminder_module(missing, "some_module_name")


def test_load_reminder_module_imports_under_the_given_module_name(tmp_path: Path) -> None:
    script = tmp_path / "reminder.py"
    script.write_text("MARKER = 'loaded'\n", encoding="utf-8")

    module = reminder_runtime.load_reminder_module(script, "openclaw_test_reminder_marker")

    assert module.MARKER == "loaded"
    assert module.__name__ == "openclaw_test_reminder_marker"


def test_load_json_raises_recovery_hint_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing-config.json"
    with pytest.raises(SystemExit, match="OPENCLAW_TEST_CONFIG_PATH"):
        reminder_runtime.load_json(missing, env_name="OPENCLAW_TEST_CONFIG_PATH")


def test_load_json_reads_existing_file(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"app_token": "abc", "table_id": "tbl1"}), encoding="utf-8")

    assert reminder_runtime.load_json(config, env_name="OPENCLAW_TEST_CONFIG_PATH") == {
        "app_token": "abc",
        "table_id": "tbl1",
    }
