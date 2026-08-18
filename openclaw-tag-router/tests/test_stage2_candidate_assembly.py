from __future__ import annotations

import copy
import json

import pytest

from openclaw_app.services.stage2_candidate_assembly import (
    ALLOWED_AUTHORITY_MODES,
    CandidateAssemblyError,
    Stage2CandidateAssembler,
    assemble_candidate,
)
from openclaw_app.services.stage2_artifact_state import ORGANIZATION_MODE, PERSONAL_MODE
from openclaw_app.services.stage2_release_gate import Stage2ReleaseGate


CANDIDATE = "stage1-candidate-1"
OTHER_CANDIDATE = "stage1-candidate-2"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
WRITER_ROUTE = "stage2_writer_router"


def upstream_receipt(node_id: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "nodeId": node_id,
        "state": "ACCEPTED",
        "candidateId": CANDIDATE,
        "sourceDigest": DIGEST_A,
        "acceptanceReceipt": DIGEST_A,
    }
    value.update(overrides)
    return value


def all_upstream() -> dict[str, dict[str, object]]:
    return {
        "F1": upstream_receipt("C1"),
        "F2": upstream_receipt("C3"),
        "F3": upstream_receipt("DC2"),
    }


def component_inventory() -> dict[str, object]:
    return {
        "authorityModes": sorted(ALLOWED_AUTHORITY_MODES),
        "writerRoutes": [WRITER_ROUTE],
        "components": [
            {
                "componentId": "personal-content",
                "digest": DIGEST_B,
                "authorityMode": PERSONAL_MODE,
            },
            {
                "componentId": "organization-content",
                "digest": DIGEST_C,
                "authorityMode": ORGANIZATION_MODE,
            },
        ],
    }


def gate_result() -> dict[str, object]:
    return Stage2ReleaseGate().project(CANDIDATE, all_upstream()).as_dict()


def assert_code(error: pytest.ExceptionInfo[CandidateAssemblyError], code: str) -> None:
    assert error.value.code == code


def test_blocked_upstream_fails_closed() -> None:
    receipts = all_upstream()
    receipts["F2"]["state"] = "BLOCKED"

    with pytest.raises(CandidateAssemblyError) as raised:
        assemble_candidate(receipts, component_inventory())

    assert_code(raised, "upstream_projection_blocked")


def test_all_accepted_projections_assemble_a_json_shaped_candidate() -> None:
    result = assemble_candidate(gate_result(), component_inventory())

    assert result["candidateId"] == CANDIDATE
    assert result["projectionDigest"].startswith("sha256:")
    assert result["componentDigests"] == sorted([DIGEST_B, DIGEST_C])
    assert result["releasePolicy"]["authorityModes"] == sorted(ALLOWED_AUTHORITY_MODES)
    assert result["releasePolicy"]["writerRoute"] == WRITER_ROUTE
    assert result["ready"] is True
    assert result["receiptDigest"].startswith("sha256:")
    json.dumps(result, sort_keys=True)


def test_raw_receipts_and_gate_result_are_both_accepted() -> None:
    assembler = Stage2CandidateAssembler()

    from_raw = assembler.assemble(all_upstream(), component_inventory())
    gate = Stage2ReleaseGate().project(CANDIDATE, all_upstream())
    from_gate_object = assembler.assemble(gate, component_inventory())
    from_gate_mapping = assembler.assemble(gate.as_dict(), component_inventory())

    assert from_raw == from_gate_object
    assert from_gate_object == from_gate_mapping


def test_candidate_identity_mismatch_is_rejected() -> None:
    receipts = all_upstream()
    receipts["F3"]["candidateId"] = OTHER_CANDIDATE

    with pytest.raises(CandidateAssemblyError) as raised:
        assemble_candidate(receipts, component_inventory())

    assert_code(raised, "candidate_identity_mismatch")


def test_missing_acceptance_receipt_is_rejected() -> None:
    receipts = all_upstream()
    receipts["F1"]["acceptanceReceipt"] = None

    with pytest.raises(CandidateAssemblyError) as raised:
        assemble_candidate(receipts, component_inventory())

    assert_code(raised, "acceptance_receipt_missing")


def test_gate_receipt_digest_mismatch_is_rejected() -> None:
    payload = gate_result()
    payload["receiptDigest"] = DIGEST_C

    with pytest.raises(CandidateAssemblyError) as raised:
        assemble_candidate(payload, component_inventory())

    assert_code(raised, "receipt_digest_mismatch")


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("legacyWriter", True, "legacy_writer_forbidden"),
        ("credentialFallback", True, "global_credential_fallback_forbidden"),
    ],
)
def test_legacy_and_global_credential_policy_violations_are_rejected(
    field: str,
    value: object,
    expected_code: str,
) -> None:
    inventory = component_inventory()
    inventory["components"][0][field] = value

    with pytest.raises(CandidateAssemblyError) as raised:
        assemble_candidate(gate_result(), inventory)

    assert_code(raised, expected_code)


def test_dual_body_authority_is_rejected() -> None:
    inventory = component_inventory()
    inventory["components"][0]["authorityModes"] = [PERSONAL_MODE, ORGANIZATION_MODE]

    with pytest.raises(CandidateAssemblyError) as raised:
        assemble_candidate(gate_result(), inventory)

    assert_code(raised, "dual_body_authority_forbidden")


def test_duplicate_and_unknown_projection_keys_are_rejected() -> None:
    duplicate = gate_result()
    duplicate["projections"].append(copy.deepcopy(duplicate["projections"][0]))
    with pytest.raises(CandidateAssemblyError) as duplicate_error:
        assemble_candidate(duplicate, component_inventory())
    assert_code(duplicate_error, "duplicate_projection_key")

    unknown = gate_result()
    unknown["projections"][0]["gate_id"] = "F9"
    with pytest.raises(CandidateAssemblyError) as unknown_error:
        assemble_candidate(unknown, component_inventory())
    assert_code(unknown_error, "unknown_projection_key")


def test_component_digest_and_receipt_are_order_deterministic() -> None:
    receipts = all_upstream()
    reversed_receipts = dict(reversed(tuple(receipts.items())))
    inventory = component_inventory()
    reversed_inventory = {
        **inventory,
        "components": list(reversed(inventory["components"])),
    }

    first = assemble_candidate(reversed_receipts, inventory)
    second = assemble_candidate(receipts, reversed_inventory)

    assert first["componentDigests"] == [DIGEST_B, DIGEST_C]
    assert first == second


def test_input_receipts_and_inventory_are_not_mutated() -> None:
    receipts = all_upstream()
    inventory = component_inventory()
    receipts_before = copy.deepcopy(receipts)
    inventory_before = copy.deepcopy(inventory)

    assemble_candidate(receipts, inventory)

    assert receipts == receipts_before
    assert inventory == inventory_before


def test_receipt_digest_is_stable_for_repeated_assembly() -> None:
    assembler = Stage2CandidateAssembler()

    first = assembler.assemble(gate_result(), component_inventory())
    second = assembler.assemble(gate_result(), component_inventory())

    assert first["receiptDigest"] == second["receiptDigest"]
    assert first == second
