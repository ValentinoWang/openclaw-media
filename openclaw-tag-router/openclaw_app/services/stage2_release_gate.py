"""Fail-closed, zero-write projection of the Stage-1 gates used by Stage 2.

The gate is intentionally transport-free: it consumes immutable receipts and
returns a deterministic projection. It never changes upstream state, selects
credentials, or treats a candidate implementation as formal acceptance.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from common.canonical_digest import normalize_prefixed_digest


SCHEMA_VERSION = "stage2.release_gate.v1"
UPSTREAM_PROJECTIONS = {"F1": "C1", "F2": "C3", "F3": "DC2"}


class ReleaseGateError(ValueError):
    """Invalid receipt input; callers must stop rather than guess."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _text(value: Any, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise ReleaseGateError("invalid_receipt", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise ReleaseGateError("invalid_receipt", f"{label} is invalid")
    return normalized


def _digest(value: Any, label: str) -> str:
    normalized = _text(value, label, 80)
    if normalize_prefixed_digest(normalized) is None:
        raise ReleaseGateError("invalid_receipt", f"{label} must be a sha256 digest")
    return normalized


def _lookup(value: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return default


@dataclass(frozen=True, slots=True)
class UpstreamReceipt:
    node_id: str
    state: str
    candidate_id: str
    source_digest: str
    acceptance_receipt: str | None = None

    def __post_init__(self) -> None:
        if self.node_id not in set(UPSTREAM_PROJECTIONS.values()):
            raise ReleaseGateError("unknown_upstream", "receipt node is not a Stage-1 projection source")
        object.__setattr__(self, "state", _text(self.state, "state", 32).upper())
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id", 256))
        object.__setattr__(self, "source_digest", _digest(self.source_digest, "source_digest"))
        if self.acceptance_receipt is not None:
            object.__setattr__(self, "acceptance_receipt", _digest(self.acceptance_receipt, "acceptance_receipt"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "UpstreamReceipt":
        if not isinstance(value, Mapping):
            raise ReleaseGateError("invalid_receipt", "upstream receipt must be an object")
        return cls(
            node_id=_lookup(value, "node_id", "nodeId"),
            state=_lookup(value, "state", "execution_state", "executionState"),
            candidate_id=_lookup(value, "candidate_id", "candidateId"),
            source_digest=_lookup(value, "source_digest", "sourceDigest", "source_hash", "sourceHash"),
            acceptance_receipt=_lookup(value, "acceptance_receipt", "acceptanceReceipt", "receiptDigest"),
        )


@dataclass(frozen=True, slots=True)
class GateProjection:
    gate_id: str
    upstream_node: str
    state: str
    blocker_code: str | None
    candidate_id: str
    source_digest: str | None
    acceptance_receipt: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReleaseGateResult:
    schema_version: str
    candidate_id: str
    projections: tuple[GateProjection, ...]
    ready_frontier: tuple[str, ...]
    receipt_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "candidateId": self.candidate_id,
            "projections": [item.as_dict() for item in self.projections],
            "readyFrontier": list(self.ready_frontier),
            "receiptDigest": self.receipt_digest,
        }


class Stage2ReleaseGate:
    """Project upstream acceptance without mutating the supplied receipts."""

    def project(
        self,
        candidate_id: str,
        receipts: Mapping[str, UpstreamReceipt | Mapping[str, Any]],
    ) -> ReleaseGateResult:
        candidate = _text(candidate_id, "candidate_id", 256)
        if not isinstance(receipts, Mapping):
            raise ReleaseGateError("invalid_receipt", "receipts must be an object")
        normalized: dict[str, UpstreamReceipt] = {}
        for key, value in receipts.items():
            gate_source = _text(key, "receipt key", 8)
            receipt = value if isinstance(value, UpstreamReceipt) else UpstreamReceipt.from_mapping(value)
            if receipt.node_id != UPSTREAM_PROJECTIONS.get(gate_source):
                raise ReleaseGateError("receipt_key_mismatch", f"{gate_source} does not project {receipt.node_id}")
            normalized[gate_source] = receipt

        projections: list[GateProjection] = []
        for gate_id, upstream_node in UPSTREAM_PROJECTIONS.items():
            receipt = normalized.get(gate_id)
            if receipt is None:
                projections.append(GateProjection(gate_id, upstream_node, "BLOCKED", "upstream_receipt_missing", candidate, None, None))
                continue
            blocker: str | None = None
            if receipt.state != "ACCEPTED":
                blocker = "upstream_not_accepted"
            elif receipt.candidate_id != candidate:
                blocker = "candidate_identity_mismatch"
            elif receipt.acceptance_receipt is None:
                blocker = "acceptance_receipt_missing"
            projections.append(
                GateProjection(
                    gate_id,
                    upstream_node,
                    "ACCEPTED" if blocker is None else "BLOCKED",
                    blocker,
                    receipt.candidate_id,
                    receipt.source_digest,
                    receipt.acceptance_receipt,
                )
            )

        ready = tuple(item.gate_id for item in projections if item.state == "ACCEPTED")
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "candidateId": candidate,
            "projections": [item.as_dict() for item in projections],
            "readyFrontier": list(ready),
        }
        digest = "sha256:" + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        return ReleaseGateResult(SCHEMA_VERSION, candidate, tuple(copy.deepcopy(projections)), ready, digest)
