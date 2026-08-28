from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.migrate_media_vault_v2_tenants import MigrationError, migrate


TENANT_A = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
TENANT_B = "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"


def test_plan_only_creates_evidence_without_moving_mapped_or_orphan_files(tmp_path: Path) -> None:
    vault_root = tmp_path / "media_vault"
    mapped = vault_root / "creation_runs" / "run-1" / "result.json"
    orphan = vault_root / "renders" / "unproven" / "result.json"
    mapped.parent.mkdir(parents=True)
    orphan.parent.mkdir(parents=True)
    mapped.write_text("mapped", encoding="utf-8")
    orphan.write_text("orphan", encoding="utf-8")
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps({"assignments": [{"relative_path": "creation_runs/run-1", "tenant_id": TENANT_A}]}),
        encoding="utf-8",
    )

    report = migrate(
        vault_root=vault_root,
        mapping_path=mapping_path,
        offline_archive=tmp_path / "offline",
        evidence_path=tmp_path / "evidence.json",
        resource_owner_db=tmp_path / "resource_owners.sqlite3",
        maintenance_window_id="window-plan-only",
        plan_only=True,
    )

    assert report["status"] == "dry_run_verified"
    assert mapped.is_file()
    assert orphan.is_file()
    assert not (vault_root / "tenants").exists()
    assert not (tmp_path / "offline").exists()
    assert json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))["pre_hash"] == report["pre_hash"]


def test_overlapping_mappings_to_different_tenants_are_rejected_before_inventory(tmp_path: Path) -> None:
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "assignments": [
                    {"relative_path": "creation_runs", "tenant_id": TENANT_A},
                    {"relative_path": "creation_runs/run-1", "tenant_id": TENANT_B},
                ]
            }
        ),
        encoding="utf-8",
    )
    vault_root = tmp_path / "media_vault"
    vault_root.mkdir()

    with pytest.raises(MigrationError, match="cross-tenant"):
        migrate(
            vault_root=vault_root,
            mapping_path=mapping_path,
            offline_archive=tmp_path / "offline",
            evidence_path=tmp_path / "evidence.json",
            resource_owner_db=tmp_path / "resource_owners.sqlite3",
            maintenance_window_id="window-cross-tenant",
            plan_only=True,
        )
