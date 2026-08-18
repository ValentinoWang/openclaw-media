from pathlib import Path

import pytest

from scripts.sync_lark_base_projection import _resolve_activity_url


def test_activity_url_registry_is_authoritative_over_settings_and_environment(tmp_path: Path):
    registry = tmp_path / "media-bitable-registry.json"
    registry.write_text(
        '{"tables":{"activity":{"env":{"MEDIA_OS_ACTIVITY_URL":"https://tenant.feishu.cn/wiki/registry-node?table=tblRegistry"}}}}',
        encoding="utf-8",
    )

    value, source = _resolve_activity_url(
        {"media_os": {"activity_url": "https://tenant.feishu.cn/wiki/settings-node?table=tblSettings"}},
        registry,
        {"MEDIA_OS_ACTIVITY_URL": "https://tenant.feishu.cn/wiki/env-node?table=tblEnv"},
    )

    assert source == "registry"
    assert value.endswith("table=tblRegistry")


def test_activity_url_rejects_missing_table_parameter(tmp_path: Path):
    with pytest.raises(RuntimeError, match="table query parameter"):
        _resolve_activity_url({}, tmp_path / "missing.json", {"MEDIA_OS_ACTIVITY_URL": "https://tenant.feishu.cn/wiki/not-a-base"})
