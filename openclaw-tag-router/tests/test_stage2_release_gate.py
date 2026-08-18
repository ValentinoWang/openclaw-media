from __future__ import annotations

import copy

import pytest

from openclaw_app.services.stage2_release_gate import (
    ReleaseGateError,
    Stage2ReleaseGate,
)


DIGEST = "sha256:" + "a" * 64
CANDIDATE = "stage1-candidate-1"


def receipt(node_id: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "nodeId": node_id,
        "state": "ACCEPTED",
        "candidateId": CANDIDATE,
        "sourceDigest": DIGEST,
        "acceptanceReceipt": DIGEST,
    }
    value.update(overrides)
    return value


def test_missing_upstream_receipts_stay_blocked_and_are_zero_write() -> None:
    source = {"F1": receipt("C1")}
    before = copy.deepcopy(source)

    result = Stage2ReleaseGate().project(CANDIDATE, source)

    assert result.ready_frontier == ("F1",)
    assert {item.gate_id: item.blocker_code for item in result.projections} == {
        "F1": None,
        "F2": "upstream_receipt_missing",
        "F3": "upstream_receipt_missing",
    }
    assert source == before


def test_non_accepted_upstream_does_not_unlock_a_stage2_gate() -> None:
    result = Stage2ReleaseGate().project(
        CANDIDATE,
        {"F1": receipt("C1", state="VERIFIED"), "F2": receipt("C3"), "F3": receipt("DC2")},
    )

    assert result.ready_frontier == ("F2", "F3")
    assert result.projections[0].blocker_code == "upstream_not_accepted"


@pytest.mark.parametrize(
    ("key", "payload", "error"),
    [
        ("F1", receipt("C3"), "receipt_key_mismatch"),
        ("F2", receipt("C3", candidateId="another"), "candidate_identity_mismatch"),
        ("F3", receipt("DC2", acceptanceReceipt=None), "acceptance_receipt_missing"),
    ],
)
def test_projection_rejects_or_blocks_invalid_identity(key: str, payload: dict[str, object], error: str) -> None:
    if error == "receipt_key_mismatch":
        with pytest.raises(ReleaseGateError) as raised:
            Stage2ReleaseGate().project(CANDIDATE, {key: payload})
        assert raised.value.code == error
        return

    result = Stage2ReleaseGate().project(CANDIDATE, {key: payload})
    projection = next(item for item in result.projections if item.gate_id == key)
    assert projection.state == "BLOCKED"
    assert projection.blocker_code == error


def test_receipt_digest_is_deterministic() -> None:
    gate = Stage2ReleaseGate()
    first = gate.project(CANDIDATE, {"F1": receipt("C1"), "F2": receipt("C3"), "F3": receipt("DC2")})
    second = gate.project(CANDIDATE, {"F3": receipt("DC2"), "F1": receipt("C1"), "F2": receipt("C3")})

    assert first.as_dict() == second.as_dict()
