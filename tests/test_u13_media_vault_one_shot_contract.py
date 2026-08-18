from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.migrate_media_vault_v2_tenants import MigrationError, migrate, require_explicit_seed_tenant


def test_unknown_vault_file_is_never_assigned_without_explicit_mapping(tmp_path: Path) -> None:
    vault_root = tmp_path / "media_vault"
    unknown = vault_root / "creation_runs" / "unknown" / "result.json"
    unknown.parent.mkdir(parents=True)
    unknown.write_text("{}", encoding="utf-8")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"assignments": [
        {"relative_path": "source_assets/proven", "tenant_id": "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"},
    ]}), encoding="utf-8")

    report = migrate(
        vault_root=vault_root,
        mapping_path=mapping,
        offline_archive=tmp_path / "offline",
        evidence_path=tmp_path / "evidence.json",
        resource_owner_db=tmp_path / "resource_owners.sqlite3",
        maintenance_window_id="window-unknown-owner",
        plan_only=True,
    )

    assert report["mapped_count"] == 0
    assert report["orphan_count"] == 1
    assert report["files"][0]["tenant_id"] is None
    assert report["files"][0]["orphan_reason"] == "no_explicit_tenant_assignment"
    assert report["status"] == "dry_run_verified"
    assert report["pre_count"] == report["mapped_count"] + report["orphan_count"]
    assert report["pre_hash"]
    assert "pre_relation_count" in report


def test_vault_mapping_cannot_assign_any_path_to_another_tenant(tmp_path: Path) -> None:
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"assignments": [
        {"relative_path": "creation_runs/proven", "tenant_id": "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"},
    ]}), encoding="utf-8")

    with pytest.raises(MigrationError, match="explicit seed tenant"):
        require_explicit_seed_tenant(mapping, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
