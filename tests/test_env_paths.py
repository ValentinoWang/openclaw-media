from __future__ import annotations

import os
from pathlib import Path

from common import env_paths


def test_media_agent_root_defaults_to_current_user_home(monkeypatch) -> None:
    monkeypatch.delenv("OPENCLAW_MEDIA_AGENT_ROOT", raising=False)
    assert env_paths.media_agent_root() == Path.home() / ".openclaw" / "agents" / "media"


def test_media_agent_root_honors_env_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENCLAW_MEDIA_AGENT_ROOT", str(tmp_path))
    assert env_paths.media_agent_root() == tmp_path


def test_load_media_agent_env_files_loads_both_env_and_env_local(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text("MEDIA_OS_SOURCE_ASSETS_URL=https://example.feishu.cn/from-env\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL=https://example.feishu.cn/from-env-local\n", encoding="utf-8")
    monkeypatch.delenv("MEDIA_OS_SOURCE_ASSETS_URL", raising=False)
    monkeypatch.delenv("MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL", raising=False)

    env_paths.load_media_agent_env_files(tmp_path)

    assert os.environ["MEDIA_OS_SOURCE_ASSETS_URL"] == "https://example.feishu.cn/from-env"
    assert os.environ["MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL"] == "https://example.feishu.cn/from-env-local"


def test_load_media_agent_env_files_env_takes_precedence_over_env_local(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text("MEDIA_OS_SHARED_TOKEN=from-env\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("MEDIA_OS_SHARED_TOKEN=from-env-local\n", encoding="utf-8")
    monkeypatch.delenv("MEDIA_OS_SHARED_TOKEN", raising=False)

    env_paths.load_media_agent_env_files(tmp_path)

    assert os.environ["MEDIA_OS_SHARED_TOKEN"] == "from-env"


def test_load_media_agent_env_files_defaults_root_to_media_agent_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENCLAW_MEDIA_AGENT_ROOT", str(tmp_path))
    (tmp_path / ".env").write_text("MEDIA_OS_DEFAULT_ROOT_TOKEN=from-default-root\n", encoding="utf-8")
    monkeypatch.delenv("MEDIA_OS_DEFAULT_ROOT_TOKEN", raising=False)

    env_paths.load_media_agent_env_files()

    assert os.environ["MEDIA_OS_DEFAULT_ROOT_TOKEN"] == "from-default-root"
