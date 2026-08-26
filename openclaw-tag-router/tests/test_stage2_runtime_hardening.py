from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from openclaw_app.services.production_reconciliation_planner import (
    PlannerValidationError,
    plan_production_reconciliation,
)
from openclaw_app.services.stage2_main_composition import (
    Stage2ProductionAssemblyError,
    build_main_stage2_app,
)


def _manifest_request() -> dict[str, object]:
    source_sha = "a" * 40
    previous_sha = "b" * 40
    previous_digest = "c" * 64
    files = [
        {"path": "z.py", "sha256": "1" * 64, "mode": "100644"},
        {"path": "a.py", "sha256": "2" * 64, "mode": "100644"},
    ]
    manifest: dict[str, object] = {
        "schema_version": "production-release-manifest.v1",
        "source": {"git_sha": source_sha, "git_clean": True},
        "target": {"root": ".", "files": files},
        "previous_release_identity": {
            "git_sha": previous_sha,
            "manifest_sha256": previous_digest,
        },
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest["manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    previous = {
        "release_id": "openclaw-stage2-" + previous_sha,
        "git_sha": previous_sha,
        "root": "/srv/openclaw/releases/openclaw-stage2-" + previous_sha,
        "manifest_sha256": previous_digest,
    }
    return {
        "operation": "activate",
        "source": {"git_sha": source_sha},
        "layout": {
            "release_base": "/srv/openclaw/releases",
            "current_pointer": "/srv/openclaw/current",
        },
        "target_release": {
            "release_id": "openclaw-stage2-" + source_sha,
            "git_sha": source_sha,
            "root": "/srv/openclaw/releases/openclaw-stage2-" + source_sha,
            "manifest": manifest,
        },
        "pointer": {"expected": copy.deepcopy(previous), "observed": copy.deepcopy(previous)},
        "previous_release": {
            **previous,
            "manifest_schema": "production-release-manifest.v1",
            "rollback_compatible": True,
        },
        "known_releases": [],
        "user_systemd": {"enabled": False, "units": [], "actions": []},
        "observation": {"window_seconds": 300, "signals": ["health", "readiness"]},
    }


def test_planner_rejects_unsorted_manifest_inventory_per_locked_contract() -> None:
    with pytest.raises(PlannerValidationError) as caught:
        plan_production_reconciliation(_manifest_request())
    assert caught.value.code == "MANIFEST_INVALID"


def test_main_composition_detects_contract_replacement_during_assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "openclaw_app"
        / "contracts"
        / "stage2_writer_contract.json"
    )
    contract = json.loads(source.read_text(encoding="utf-8"))
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    class FakeGateway:
        def run(self, mode, payload):
            return {"mode": mode, "payload": payload}

    def replacing_factory(**_kwargs):
        changed = dict(contract)
        changed["description"] = str(changed.get("description") or "") + " changed"
        path.write_text(json.dumps(changed), encoding="utf-8")
        return FakeGateway()

    import openclaw_app.services.stage2_main_composition as composition

    monkeypatch.setattr(composition, "_load_factory", lambda _reference: replacing_factory)
    with pytest.raises(Stage2ProductionAssemblyError) as caught:
        build_main_stage2_app(
            settings_path=str(tmp_path / "settings.yaml"),
            contract_path=path,
            acceptance_mode=True,
        )
    assert caught.value.code == "production_contract_changed"

