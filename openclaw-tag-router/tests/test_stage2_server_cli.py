from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import pytest

import openclaw_app.server_cli as server_cli
from openclaw_app.services.stage2_contract_validator import (
    Stage2ContractValidationError,
    contract_digest,
    validate_contract_file,
)
from openclaw_app.services.stage2_context import DOCUMENT_WRITER_FIXTURE_ID
from openclaw_app.services.stage2_gateway import Stage2Gateway
from openclaw_app.services.stage2_production import Stage2ProductionAssemblyError
from openclaw_app.services.stage2_runtime import Stage2Runtime


CONTRACT_PATH = Path(__file__).parents[1] / "openclaw_app" / "contracts" / "stage2_writer_contract.json"


def test_startup_contract_path_validates_the_checked_in_contract() -> None:
    receipt = validate_contract_file(CONTRACT_PATH)

    assert receipt["valid"] is True
    assert receipt["contractDigest"].startswith("sha256:")


def test_startup_contract_path_fails_closed_for_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "stage2-writer-contract.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(Stage2ContractValidationError) as caught:
        validate_contract_file(path)

    assert caught.value.receipt["valid"] is False
    assert caught.value.receipt["findings"][0]["code"] == "contract_input_invalid"


def test_startup_contract_path_fails_closed_for_schema_violation(tmp_path: Path) -> None:
    path = tmp_path / "stage2-writer-contract.json"
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["contractVersion"] = "unsupported"
    path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(Stage2ContractValidationError) as caught:
        validate_contract_file(path)

    assert caught.value.receipt["valid"] is False
    assert any(
        finding["code"] == "contract_version_unsupported"
        for finding in caught.value.receipt["findings"]
    )


def test_server_cli_stops_before_application_import_on_invalid_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "stage2-writer-contract.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["server_cli", "--stage2-contract", str(path)])

    with pytest.raises(Stage2ContractValidationError):
        server_cli.main()


def test_provisional_contract_cannot_enable_production_runtime() -> None:
    with pytest.raises(Stage2ProductionAssemblyError) as caught:
        server_cli._load_production_gateway(
            "missing:factory",
            settings_path="settings.yaml",
            contract_path=str(CONTRACT_PATH),
            contract_digest="sha256:" + "0" * 64,
        )

    assert caught.value.code == "production_contract_not_accepted"


def test_cli_reports_production_contract_block_without_importing_application(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "server_cli",
            "--stage2-contract",
            str(CONTRACT_PATH),
            "--stage2-runtime",
            "production",
            "--stage2-factory",
            "missing:factory",
        ],
    )

    assert server_cli.main() == 2
    assert "production_contract_not_accepted" in capsys.readouterr().err


def test_accepted_contract_requires_and_loads_one_explicit_gateway_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract.update(
        {
            "status": "accepted",
            "runtimeIntegration": True,
            "endpoints": ["/stage2/personal", {"path": "/stage2/organization"}],
        }
    )
    contract_path = tmp_path / "accepted.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    accepted_digest = contract_digest(contract)

    with pytest.raises(Stage2ProductionAssemblyError) as missing:
        server_cli._load_production_gateway(
            None,
            settings_path="settings.yaml",
            contract_path=str(contract_path),
            contract_digest=accepted_digest,
        )
    assert missing.value.code == "production_factory_required"

    calls: list[dict[str, str]] = []
    module = types.ModuleType("stage2_test_factory")

    def factory(**kwargs):
        calls.append(kwargs)
        return Stage2Gateway(
            Stage2Runtime(),
            capability_id=DOCUMENT_WRITER_FIXTURE_ID,
            personal_session_provider=lambda: None,
            organization_context_provider=lambda: None,
        )

    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    gateway = server_cli._load_production_gateway(
        "stage2_test_factory:factory",
        settings_path="settings.yaml",
        contract_path=str(contract_path),
        contract_digest=accepted_digest,
    )

    assert isinstance(gateway, Stage2Gateway)
    assert calls == [
        {
            "settings_path": "settings.yaml",
            "contract_path": str(contract_path),
            "contract_digest": accepted_digest,
        }
    ]


def test_production_factory_failure_is_reported_as_stable_assembly_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract.update(
        {
            "status": "accepted",
            "runtimeIntegration": True,
            "endpoints": ["/stage2/personal", "/stage2/organization"],
        }
    )
    contract_path = tmp_path / "accepted.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    module = types.ModuleType("stage2_failing_factory")

    def factory(**kwargs):
        raise RuntimeError("dependency unavailable")

    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)

    with pytest.raises(Stage2ProductionAssemblyError) as caught:
        server_cli._load_production_gateway(
            "stage2_failing_factory:factory",
            settings_path="settings.yaml",
            contract_path=str(contract_path),
            contract_digest=contract_digest(contract),
        )

    assert caught.value.code == "production_factory_failed"


def test_production_loader_rejects_contract_changed_after_validation(
    tmp_path: Path,
) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract.update(
        {
            "status": "accepted",
            "runtimeIntegration": True,
            "endpoints": ["/stage2/personal", "/stage2/organization"],
        }
    )
    contract_path = tmp_path / "accepted.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    validated_digest = contract_digest(contract)
    contract["description"] = "changed after validation"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(Stage2ProductionAssemblyError) as caught:
        server_cli._load_production_gateway(
            "missing:factory",
            settings_path="settings.yaml",
            contract_path=str(contract_path),
            contract_digest=validated_digest,
        )

    assert caught.value.code == "production_contract_changed"
