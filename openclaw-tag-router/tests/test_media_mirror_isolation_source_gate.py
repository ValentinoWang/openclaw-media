from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LEGACY_ENTRYPOINTS = (
    ROOT / "openclaw_app/services/media_business/lark_sync.py",
    ROOT / "scripts/sync_media_lark_tenant.py",
    ROOT / "scripts/hydrate_lark_resource_mirrors.py",
)
CANONICAL_HYDRATION = ROOT / "openclaw_app/services/lark_resource_hydration.py"


def _load_exact_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retired_lark_entrypoints_cannot_write_internal_revision_bodies() -> None:
    for path in LEGACY_ENTRYPOINTS:
        source = path.read_text(encoding="utf-8")
        assert "media_document.revision_bodies" not in source, path
        assert "PostgresLarkProjectionStore" not in source, path


def test_canonical_lark_hydration_is_mirror_only() -> None:
    source = CANONICAL_HYDRATION.read_text(encoding="utf-8")
    assert "media_document.lark_read_mirrors" in source
    assert "media_document.revision_bodies" not in source


def test_legacy_scripts_fail_closed_with_canonical_replacement() -> None:
    for path in LEGACY_ENTRYPOINTS[1:]:
        source = path.read_text(encoding="utf-8")
        assert "scripts/sync_lark_resources.py" in source or "scripts/hydrate_lark_resources.py" in source, path


def test_retired_entrypoints_fail_before_storage_initialization() -> None:
    hydrate_module = _load_exact_script(
        ROOT / "scripts/hydrate_lark_resource_mirrors.py",
        "a1_retired_hydrate_lark_resource_mirrors",
    )
    sync_module = _load_exact_script(
        ROOT / "scripts/sync_media_lark_tenant.py",
        "a1_retired_sync_media_lark_tenant",
    )

    assert sync_module.main() == 2
    assert hydrate_module.main() == 2
    with pytest.raises(RuntimeError, match="retired"):
        hydrate_module.hydrate(
            database=None,
            feishu=None,
            tenant_id="tenant",
            parent_node_token="root",
            web_base_url="https://example.feishu.cn",
        )
