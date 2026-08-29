from __future__ import annotations

import json
from pathlib import Path

import pytest

from media_vault import MediaVault, MediaVaultUriError


TENANT_A = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
TENANT_B = "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"
VAULT_CONTRACT = Path(__file__).resolve().parents[1] / "media_vault" / "media_vault_v2_contract.json"


def test_unknown_vault_file_is_never_assigned_without_an_explicit_v2_owner(tmp_path: Path) -> None:
    contract = json.loads(VAULT_CONTRACT.read_text(encoding="utf-8"))
    vault = MediaVault(tenant_id=TENANT_A, root=tmp_path / "media_vault")
    unknown = tmp_path / "media_vault" / "creation_runs" / "unknown" / "result.json"
    unknown.parent.mkdir(parents=True)
    unknown.write_text("{}", encoding="utf-8")

    assert contract["migration"]["ownership_input"] == "explicit tenant mapping plus canonical owner sidecar"
    assert contract["migration"]["unprovable_owner_action"] == "move_to_offline_orphan_archive"
    assert contract["migration"]["runtime_legacy_reader"] is False
    assert vault.list_artifacts() == []
    with pytest.raises(MediaVaultUriError, match="authenticated tenant"):
        vault.resolve_uri("media://creation_runs/unknown/result.json")


def test_vault_mapping_cannot_assign_an_artifact_to_another_tenant(tmp_path: Path) -> None:
    contract = json.loads(VAULT_CONTRACT.read_text(encoding="utf-8"))
    owner = MediaVault(tenant_id=TENANT_A, root=tmp_path / "media_vault")
    other = MediaVault(tenant_id=TENANT_B, root=tmp_path / "media_vault")
    artifact = owner.write_json_artifact(
        owner.creation_run_dir("proven"),
        "result.json",
        {"status": "ready"},
        owner_type="CreationRun",
        owner_id="proven",
        artifact_type="result",
    )

    assert contract["authorization"]["cross_tenant_result"] == "not_found"
    assert contract["authorization"]["uri_owner_must_match_context"] is True
    with pytest.raises(MediaVaultUriError, match="authenticated tenant"):
        other.read_json_artifact(artifact["uri"])
