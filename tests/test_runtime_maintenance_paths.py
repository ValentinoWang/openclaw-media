from __future__ import annotations

from pathlib import Path

import pytest

from _support import load_script_module


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    return load_script_module(name, ROOT / relative_path)


def test_deploy_maintenance_paths_are_repo_relative_and_owned_scripts_are_checked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deploy = _load_module("deploy_openclaw_runtime_paths", "runtime/maintenance/deploy/deploy_openclaw_runtime.py")

    assert deploy.REPO_ROOT == ROOT
    assert deploy.BOT_CENTER_ROOT == ROOT / "openclaw-bot-center"
    assert all(path.is_file() for path in deploy.OWNED_MAINTENANCE_SCRIPTS)

    monkeypatch.setattr(deploy, "OWNED_MAINTENANCE_SCRIPTS", (tmp_path / "missing.py",))
    with pytest.raises(SystemExit, match="repository-owned maintenance scripts"):
        deploy.assert_owned_maintenance_scripts()


def test_sync_config_derives_owned_agent_models_script_and_fails_before_restart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sync = _load_module("sync_openclaw_bot_config_paths", "runtime/maintenance/deploy/sync_openclaw_bot_config.py")

    assert sync.REPO_ROOT == ROOT
    assert sync.SYNC_AGENT_MODELS == ROOT / "runtime/maintenance/deploy/sync_openclaw_agent_models.py"

    missing = tmp_path / "missing.py"
    with pytest.raises(SystemExit, match="repository-owned maintenance script"):
        sync.assert_owned_script(missing)
