from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from openclaw_app.services.stage2_contract_validator import (
    VALIDATOR_SCHEMA_VERSION,
    contract_digest,
    validate_contract,
)


CONTRACT_PATH = Path(__file__).parents[1] / "openclaw_app/contracts/stage2_writer_contract.json"
SUPPORTED_MODES = ["personal_web/internal", "organization_lark/lark"]


def current_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def capability_entries() -> list[dict]:
    return [
        {
            "id": "stage2_document_writer_fixture",
            "effect": "write",
            "allowedAuthorityModes": list(SUPPORTED_MODES),
            "writesTo": list(SUPPORTED_MODES),
            "requiresReadback": True,
        },
        {
            "id": "stage2_read_only_consultation_fixture",
            "effect": "read",
            "readOnly": True,
            "allowedAuthorityModes": list(SUPPORTED_MODES),
            "requiresReadback": False,
            "writesTo": [],
        },
    ]


def contract_with_capabilities() -> dict:
    contract = current_contract()
    contract["capabilities"] = capability_entries()
    return contract


def codes(receipt: dict) -> set[str]:
    return {finding["code"] for finding in receipt["findings"]}


def test_current_contract_fixture_is_valid() -> None:
    receipt = validate_contract(current_contract())

    assert receipt["schemaVersion"] == VALIDATOR_SCHEMA_VERSION
    assert receipt["valid"] is True
    assert receipt["findings"] == []
    assert receipt["contractDigest"].startswith("sha256:")


def test_missing_and_unknown_routes_fail_closed() -> None:
    missing = current_contract()
    missing["authorityPolicy"]["workspaceBodyPairs"].pop()
    missing_receipt = validate_contract(missing)
    assert missing_receipt["valid"] is False
    assert "route_missing" in codes(missing_receipt)

    unknown = current_contract()
    unknown["authorityPolicy"]["workspaceBodyPairs"].append(
        {"workspace": "unknown_workspace", "bodyAuthority": "unknown_authority"}
    )
    unknown_receipt = validate_contract(unknown)
    assert unknown_receipt["valid"] is False
    assert "unknown_route" in codes(unknown_receipt)


def test_duplicate_capability_ids_fail_closed() -> None:
    contract = contract_with_capabilities()
    contract["capabilities"].append(copy.deepcopy(contract["capabilities"][0]))

    receipt = validate_contract(contract)

    assert receipt["valid"] is False
    assert "duplicate_capability_id" in codes(receipt)


def test_read_only_capability_cannot_declare_write_effects() -> None:
    contract = contract_with_capabilities()
    contract["capabilities"][1]["writesTo"] = ["organization_lark/lark"]
    contract["capabilities"][1]["remoteWrite"] = True

    receipt = validate_contract(contract)

    assert receipt["valid"] is False
    assert "capability_effect_contradictory" in codes(receipt)


def test_document_writer_must_declare_required_readback() -> None:
    contract = contract_with_capabilities()
    del contract["capabilities"][0]["requiresReadback"]

    receipt = validate_contract(contract)

    assert receipt["valid"] is False
    assert "capability_readback_missing" in codes(receipt)


def test_invalid_status_vocabulary_fails_closed() -> None:
    contract = current_contract()
    contract["$defs"]["writeResult"]["properties"]["status"]["enum"] = [
        "written",
        "success",
    ]

    receipt = validate_contract(contract)

    assert receipt["valid"] is False
    assert "invalid_status_vocabulary" in codes(receipt)


@pytest.mark.parametrize("field", ["registration", "readback"])
def test_success_result_cannot_omit_required_stage(field: str) -> None:
    contract = current_contract()
    contract["$defs"]["writeResult"]["required"].remove(field)

    receipt = validate_contract(contract)

    assert receipt["valid"] is False
    assert "publishability_invariant_missing" in codes(receipt)


def test_organization_route_requires_binding_identity() -> None:
    contract = current_contract()
    contract["authorityPolicy"]["serverDerivedFields"].remove("organizationBindingRef")
    contract["$defs"]["trustedContext"]["required"].remove("organizationBindingRef")

    receipt = validate_contract(contract)

    assert receipt["valid"] is False
    assert "organization_binding_required" in codes(receipt)


def test_input_is_not_mutated() -> None:
    contract = contract_with_capabilities()
    before = copy.deepcopy(contract)

    validate_contract(contract)

    assert contract == before


def test_digest_and_receipt_are_deterministic_for_mapping_order() -> None:
    contract = contract_with_capabilities()
    reordered = {key: contract[key] for key in reversed(tuple(contract))}

    first = validate_contract(contract)
    second = validate_contract(reordered)

    assert contract_digest(contract) == contract_digest(reordered)
    assert first == second


def test_findings_are_sorted_and_invalid_input_fails_closed() -> None:
    receipt = validate_contract({"contractVersion": "wrong", "schemaVersion": 99})

    assert receipt["valid"] is False
    assert receipt["findings"] == sorted(
        receipt["findings"], key=lambda finding: (finding["code"], finding["path"], finding["message"])
    )
    assert validate_contract(None)["valid"] is False


def test_default_path_does_not_read_a_file() -> None:
    receipt = validate_contract()

    assert receipt["valid"] is False
    assert "contract_input_invalid" in codes(receipt)
