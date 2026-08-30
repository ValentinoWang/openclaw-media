"""Deterministic, zero-write assembly of the Stage-2 release candidate."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from common.canonical_digest import normalize_prefixed_digest

from .stage2_artifact_state import ORGANIZATION_MODE, PERSONAL_MODE
from .stage2_release_gate import (
    GateProjection,
    ReleaseGateError,
    ReleaseGateResult,
    Stage2ReleaseGate,
    UpstreamReceipt,
    UPSTREAM_PROJECTIONS,
    SCHEMA_VERSION as RELEASE_GATE_SCHEMA_VERSION,
)

SCHEMA_VERSION = "stage2.candidate_assembly.v1"
PROJECTION_ORDER = ("F1", "F2", "F3")
ALLOWED_AUTHORITY_MODES = frozenset({PERSONAL_MODE, ORGANIZATION_MODE})
_MISSING = object()


class CandidateAssemblyError(ValueError):
    """A fail-closed candidate assembly error with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


Stage2CandidateAssemblyError = CandidateAssemblyError


def _get(value: Mapping[str, Any], *names: str, default: Any = _MISSING) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return default


def _text(value: Any, label: str, code: str, limit: int = 512) -> str:
    if not isinstance(value, str):
        raise CandidateAssemblyError(code, f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > limit or any(ord(char) < 32 for char in normalized):
        raise CandidateAssemblyError(code, f"{label} is invalid")
    return normalized


def _digest(value: Any, label: str, code: str) -> str:
    normalized = _text(value, label, code, 80)
    if normalize_prefixed_digest(normalized) is None:
        raise CandidateAssemblyError(code, f"{label} must be a sha256 digest")
    return normalized


def _hash_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, GateProjection):
        return value.as_dict()
    return value if isinstance(value, Mapping) else None


def _items(value: Any, label: str, code: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise CandidateAssemblyError(code, f"{label} must be an array")
    return tuple(value)


def _optional_digest(value: Any, label: str) -> str | None:
    return None if value is _MISSING or value is None else _digest(value, label, "invalid_gate_result")


def _raw_receipts(receipts: Mapping[str, Any], candidate_id: str | None) -> Mapping[str, Any]:
    candidates: list[str] = []
    for key, receipt in receipts.items():
        if not isinstance(key, str) or key not in UPSTREAM_PROJECTIONS:
            raise CandidateAssemblyError("unknown_projection_key", f"unknown upstream key: {key!r}")
        if isinstance(receipt, UpstreamReceipt):
            candidates.append(receipt.candidate_id)
            continue
        item = _mapping(receipt)
        if item is None:
            continue
        expected_node = UPSTREAM_PROJECTIONS[key]
        node = _get(item, "node_id", "nodeId")
        if node is not _MISSING and node is not None and node != expected_node:
            raise CandidateAssemblyError("projection_mapping_mismatch", f"{key} must project {expected_node}")
        receipt_digests: list[str | None] = []
        for name in ("acceptance_receipt", "acceptanceReceipt", "receipt_digest", "receiptDigest"):
            if name in item:
                raw = item[name]
                receipt_digests.append(None if raw is None else _digest(raw, f"{key}.{name}", "invalid_upstream_receipt"))
        if len(set(receipt_digests)) > 1:
            raise CandidateAssemblyError("receipt_digest_mismatch", f"{key} has conflicting receipt digests")
        raw_candidate = _get(item, "candidate_id", "candidateId")
        if raw_candidate is not _MISSING and raw_candidate is not None:
            candidates.append(_text(raw_candidate, f"{key}.candidate_id", "candidate_identity_mismatch", 256))

    unique = set(candidates)
    if len(unique) > 1:
        raise CandidateAssemblyError("candidate_identity_mismatch", "upstream projections have different candidates")
    if candidate_id is not None:
        candidate = _text(candidate_id, "candidate_id", "candidate_identity_mismatch", 256)
        if any(item != candidate for item in candidates):
            raise CandidateAssemblyError("candidate_identity_mismatch", "upstream projection candidate differs")
    elif unique:
        candidate = next(iter(unique))
    elif not receipts:
        raise CandidateAssemblyError("upstream_projection_missing", "all upstream projections are missing")
    else:
        raise CandidateAssemblyError("candidate_identity_missing", "upstream candidate identity is missing")

    try:
        return Stage2ReleaseGate().project(candidate, receipts).as_dict()
    except ReleaseGateError as error:
        code = {
            "receipt_key_mismatch": "projection_mapping_mismatch",
            "unknown_upstream": "unknown_projection_key",
            "invalid_receipt": "invalid_upstream_receipt",
        }.get(error.code, error.code)
        raise CandidateAssemblyError(code, error.message) from error


def _gate_entries(value: Any) -> tuple[tuple[str | None, Any], ...]:
    if isinstance(value, Mapping):
        return tuple((key if isinstance(key, str) else None, item) for key, item in value.items())
    return tuple((None, item) for item in _items(value, "projections", "invalid_gate_result"))


def _normalize_gate(value: Mapping[str, Any]) -> tuple[str, str, tuple[dict[str, Any], ...]]:
    if _get(value, "schemaVersion", "schema_version") != RELEASE_GATE_SCHEMA_VERSION:
        raise CandidateAssemblyError("gate_schema_unsupported", "unsupported Stage2ReleaseGate schema")
    candidate = _text(_get(value, "candidateId", "candidate_id"), "candidate_id", "invalid_gate_result", 256)
    raw_projections = _get(value, "projections")
    if raw_projections is _MISSING:
        raise CandidateAssemblyError("invalid_gate_result", "gate result must contain projections")

    normalized: dict[str, dict[str, Any]] = {}
    for key_hint, raw_projection in _gate_entries(raw_projections):
        item = _mapping(raw_projection)
        if item is None:
            raise CandidateAssemblyError("invalid_gate_result", "projection must be an object")
        gate_id = _get(
            item,
            "gate_id",
            "gateId",
            "projection_id",
            "projectionId",
            default=key_hint if key_hint is not None else _MISSING,
        )
        if not isinstance(gate_id, str) or gate_id not in UPSTREAM_PROJECTIONS:
            raise CandidateAssemblyError("unknown_projection_key", f"unknown projection key: {gate_id!r}")
        if key_hint is not None and key_hint != gate_id:
            raise CandidateAssemblyError("projection_mapping_mismatch", "projection key and gate id differ")
        if gate_id in normalized:
            raise CandidateAssemblyError("duplicate_projection_key", f"duplicate projection key: {gate_id}")

        expected_node = UPSTREAM_PROJECTIONS[gate_id]
        node = _get(item, "upstream_node", "upstreamNode")
        if node is _MISSING:
            raise CandidateAssemblyError("projection_mapping_missing", f"{gate_id} must map to {expected_node}")
        node = _text(node, f"{gate_id}.upstream_node", "invalid_gate_result", 32)
        if node != expected_node:
            raise CandidateAssemblyError("projection_mapping_mismatch", f"{gate_id} must map to {expected_node}")

        state = _text(
            _get(item, "state", "execution_state", "executionState"),
            f"{gate_id}.state",
            "invalid_gate_result",
            32,
        ).upper()
        if state not in {"ACCEPTED", "BLOCKED"}:
            raise CandidateAssemblyError("invalid_gate_result", f"{gate_id} has an unsupported state")
        projection_candidate = _text(
            _get(item, "candidate_id", "candidateId"),
            f"{gate_id}.candidate_id",
            "candidate_identity_mismatch",
            256,
        )
        if projection_candidate != candidate:
            raise CandidateAssemblyError("candidate_identity_mismatch", f"{gate_id} belongs to another candidate")

        blocker_raw = _get(item, "blocker_code", "blockerCode", default=None)
        blocker = None if blocker_raw is None else _text(blocker_raw, f"{gate_id}.blocker_code", "invalid_gate_result", 96)
        source_digest = _optional_digest(_get(item, "source_digest", "sourceDigest", default=None), f"{gate_id}.source_digest")

        acceptance_values: list[str | None] = []
        for name in ("acceptance_receipt", "acceptanceReceipt", "receipt_digest", "receiptDigest"):
            if name in item:
                raw = item[name]
                acceptance_values.append(None if raw is None else _digest(raw, f"{gate_id}.{name}", "invalid_gate_result"))
        if len(set(acceptance_values)) > 1:
            raise CandidateAssemblyError("receipt_digest_mismatch", f"{gate_id} has conflicting receipt digests")
        acceptance_receipt = acceptance_values[0] if acceptance_values else None
        if state == "ACCEPTED":
            if source_digest is None:
                raise CandidateAssemblyError("source_digest_missing", f"{gate_id} has no source digest")
            if acceptance_receipt is None:
                raise CandidateAssemblyError("acceptance_receipt_missing", f"{gate_id} has no acceptance receipt")
            if blocker is not None:
                raise CandidateAssemblyError("invalid_gate_result", f"{gate_id} is accepted but blocked")

        normalized[gate_id] = {
            "gate_id": gate_id,
            "upstream_node": node,
            "state": state,
            "blocker_code": blocker,
            "candidate_id": projection_candidate,
            "source_digest": source_digest,
            "acceptance_receipt": acceptance_receipt,
        }

    missing = [key for key in PROJECTION_ORDER if key not in normalized]
    if missing:
        raise CandidateAssemblyError("upstream_projection_missing", "missing projections: " + ",".join(missing))
    projections = tuple(normalized[key] for key in PROJECTION_ORDER)
    expected_ready = tuple(item["gate_id"] for item in projections if item["state"] == "ACCEPTED")
    ready = tuple(
        _text(item, "readyFrontier item", "invalid_gate_result", 8)
        for item in _items(_get(value, "readyFrontier", "ready_frontier"), "readyFrontier", "invalid_gate_result")
    )
    if len(set(ready)) != len(ready):
        raise CandidateAssemblyError("duplicate_projection_key", "readyFrontier has duplicate keys")
    if ready != expected_ready:
        raise CandidateAssemblyError("gate_state_mismatch", "readyFrontier does not match projection states")

    receipt_digest = _digest(
        _get(value, "receiptDigest", "receipt_digest"),
        "receipt_digest",
        "receipt_digest_mismatch",
    )
    canonical = {
        "schemaVersion": RELEASE_GATE_SCHEMA_VERSION,
        "candidateId": candidate,
        "projections": list(projections),
        "readyFrontier": list(expected_ready),
    }
    if receipt_digest != _hash_json(canonical):
        raise CandidateAssemblyError("receipt_digest_mismatch", "gate receipt digest does not match projections")
    return candidate, receipt_digest, projections


def _ready_gate(upstream: ReleaseGateResult | Mapping[str, Any], candidate_id: str | None) -> tuple[str, str, tuple[dict[str, Any], ...]]:
    if isinstance(upstream, ReleaseGateResult):
        payload = upstream.as_dict()
    elif isinstance(upstream, Mapping) and any(
        key in upstream
        for key in ("schemaVersion", "schema_version", "projections", "readyFrontier", "ready_frontier", "receiptDigest", "receipt_digest")
    ):
        payload = upstream
    elif isinstance(upstream, Mapping):
        payload = _raw_receipts(upstream, candidate_id)
    else:
        raise CandidateAssemblyError("invalid_upstream", "upstream must be raw receipts or a gate result")

    candidate, projection_digest, projections = _normalize_gate(payload)
    if candidate_id is not None and _text(candidate_id, "candidate_id", "candidate_identity_mismatch", 256) != candidate:
        raise CandidateAssemblyError("candidate_identity_mismatch", "requested candidate differs from gate candidate")
    for projection in projections:
        if projection["state"] == "ACCEPTED":
            continue
        code = {
            "upstream_receipt_missing": "upstream_projection_missing",
            "upstream_not_accepted": "upstream_projection_blocked",
            "candidate_identity_mismatch": "candidate_identity_mismatch",
            "acceptance_receipt_missing": "acceptance_receipt_missing",
        }.get(projection["blocker_code"], "upstream_projection_blocked")
        raise CandidateAssemblyError(
            code,
            f"{projection['gate_id']} is not accepted: {projection['blocker_code'] or 'blocked'}",
        )
    return candidate, projection_digest, projections


_COMPONENT_KEYS = frozenset({
    "componentId", "component_id", "id", "name", "digest", "componentDigest", "component_digest",
    "sourceDigest", "source_digest", "authorityMode", "authority_mode", "authorityModes", "authority_modes",
    "workspace", "workspaceMode", "workspace_mode", "bodyAuthority", "body_authority",
    "writerRoute", "writer_route", "writerRoutes", "writer_routes", "route",
})
_LEGACY_FIELDS = ("legacy", "legacyWriter", "legacy_writer", "isLegacy", "is_legacy", "legacyWriters", "legacy_writers")
_CREDENTIAL_FIELDS = (
    "credentials", "credential", "globalCredentials", "global_credentials",
    "deploymentGlobalCredentials", "deployment_global_credentials",
    "credentialFallback", "credential_fallback", "globalCredentialFallback", "global_credential_fallback",
    "deploymentGlobalCredentialFallback", "deployment_global_credential_fallback",
    "usesDeploymentGlobalCredentials", "uses_deployment_global_credentials",
)
_DOUBLE_WRITER_FIELDS = ("dualWriter", "dual_writer", "doubleWriter", "double_writer", "dualRoute", "dual_route")
_DUAL_AUTHORITY_FIELDS = ("dualBodyAuthority", "dual_body_authority", "bodyAuthorityPair", "body_authority_pair")


def _active(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str) and value.strip().lower() in {"", "false", "0", "no", "off", "none"}:
        return False
    if isinstance(value, (list, tuple, dict, set, frozenset)) and not value:
        return False
    return True


def _flag(value: Mapping[str, Any], names: Sequence[str]) -> bool:
    return any(name in value and _active(value[name]) for name in names)


def _name(value: Any, label: str) -> str:
    return _text(value, label, "invalid_component_inventory", 256).strip().lower()


def _values(value: Any, label: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_name(value, label),)
    return tuple(_name(item, f"{label} item") for item in _items(value, label, "invalid_component_inventory"))


def _mode(value: Any, label: str) -> str:
    normalized = _name(value, label).replace(":", "/")
    if normalized not in ALLOWED_AUTHORITY_MODES:
        raise CandidateAssemblyError("authority_modes_invalid", f"{label} is not an allowed authority mode")
    return normalized


def _component_mode(component: Mapping[str, Any], component_id: str) -> str:
    modes: list[str] = []
    for key in ("authorityModes", "authority_modes"):
        raw = _get(component, key)
        if raw is not _MISSING:
            values = _values(raw, f"{component_id}.authority_modes")
            if len(values) != 1:
                raise CandidateAssemblyError("dual_body_authority_forbidden", f"{component_id} declares multiple authorities")
            modes.append(_mode(values[0], f"{component_id}.authority_mode"))
            break
    direct = _get(component, "authorityMode", "authority_mode", "bodyAuthorityMode", "body_authority_mode")
    if direct is not _MISSING:
        values = _values(direct, f"{component_id}.authority_mode")
        if len(values) != 1:
            raise CandidateAssemblyError("dual_body_authority_forbidden", f"{component_id} declares multiple authorities")
        modes.append(_mode(values[0], f"{component_id}.authority_mode"))

    workspace = _get(component, "workspace", "workspaceMode", "workspace_mode")
    body = _get(component, "bodyAuthority", "body_authority")
    if workspace is not _MISSING or body is not _MISSING:
        if workspace is _MISSING or body is _MISSING or not isinstance(workspace, str) or not isinstance(body, str):
            raise CandidateAssemblyError("authority_modes_invalid", f"{component_id} has an invalid workspace/body pair")
        modes.append(_mode(f"{workspace.strip()}/{body.strip()}", f"{component_id}.authority_mode"))
    elif isinstance(body, str) and "/" in body:
        modes.append(_mode(body, f"{component_id}.body_authority"))

    if _flag(component, _DUAL_AUTHORITY_FIELDS):
        raise CandidateAssemblyError("dual_body_authority_forbidden", f"{component_id} declares dual authority")
    if not modes:
        raise CandidateAssemblyError("authority_modes_invalid", f"{component_id} does not declare an authority mode")
    if len(set(modes)) != 1:
        raise CandidateAssemblyError("dual_body_authority_forbidden", f"{component_id} declares multiple authorities")
    return modes[0]


def _component_route(component: Mapping[str, Any], component_id: str, inherited: str | None) -> str:
    routes: list[str] = []
    plural = _get(component, "writerRoutes", "writer_routes")
    if plural is not _MISSING:
        routes.extend(_values(plural, f"{component_id}.writer_routes"))
    singular = _get(component, "writerRoute", "writer_route", "route")
    if singular is not _MISSING:
        routes.extend(_values(singular, f"{component_id}.writer_route") if isinstance(singular, (list, tuple)) else (_name(singular, f"{component_id}.writer_route"),))
    if not routes:
        writer = _get(component, "writer")
        if isinstance(writer, str):
            routes.append(_name(writer, f"{component_id}.writer"))
    if not routes and inherited is not None:
        routes.append(inherited)
    if not routes:
        raise CandidateAssemblyError("writer_route_invalid", f"{component_id} has no writer route")
    if len(set(routes)) != 1:
        raise CandidateAssemblyError("double_writer_forbidden", f"{component_id} declares multiple writer routes")
    return routes[0]


def _component_entries(value: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Mapping):
        if _COMPONENT_KEYS.intersection(value):
            return (value,)
        result: list[Mapping[str, Any]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise CandidateAssemblyError("invalid_component_inventory", "component keys must be strings")
            if isinstance(item, str):
                result.append({"componentId": key, "digest": item})
            elif isinstance(item, Mapping):
                descriptor = dict(item)
                descriptor.setdefault("componentId", key)
                result.append(descriptor)
            else:
                raise CandidateAssemblyError("invalid_component_inventory", f"component {key!r} is invalid")
        return tuple(result)
    items = _items(value, "components", "invalid_component_inventory")
    if any(not isinstance(item, Mapping) for item in items):
        raise CandidateAssemblyError("invalid_component_inventory", "each component must be an object")
    return tuple(items)


def _inventory_parts(value: Any) -> tuple[tuple[Mapping[str, Any], ...], Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return _component_entries(value), {}
    raw = _get(value, "components", "componentInventory", "component_inventory", "inventory")
    if raw is not _MISSING:
        return _component_entries(raw), value
    if _COMPONENT_KEYS.intersection(value):
        return (value,), {}
    if value and all(isinstance(item, (Mapping, str)) for item in value.values()):
        return _component_entries(value), {}
    raise CandidateAssemblyError("invalid_component_inventory", "component inventory must declare components")


def _declared(metadata: Mapping[str, Any], label: str) -> tuple[str, ...]:
    result: list[str] = []
    for key in ("writerRoutes", "writer_routes", "writerRoute", "writer_route", "writer"):
        raw = _get(metadata, key)
        if raw is not _MISSING:
            result.extend(_values(raw, label))
    return tuple(result)


def _normalize_inventory(value: Any) -> tuple[list[str], str]:
    components, metadata = _inventory_parts(value)
    if _flag(metadata, _LEGACY_FIELDS):
        raise CandidateAssemblyError("legacy_writer_forbidden", "inventory contains a legacy writer")
    if _flag(metadata, _CREDENTIAL_FIELDS):
        raise CandidateAssemblyError("global_credential_fallback_forbidden", "inventory contains a credential fallback")
    if _flag(metadata, _DOUBLE_WRITER_FIELDS):
        raise CandidateAssemblyError("double_writer_forbidden", "inventory contains a dual writer")
    if _flag(metadata, _DUAL_AUTHORITY_FIELDS):
        raise CandidateAssemblyError("dual_body_authority_forbidden", "inventory contains dual body authority")

    declared_modes_raw = _get(metadata, "authorityModes", "authority_modes")
    declared_modes: set[str] | None = None
    if declared_modes_raw is not _MISSING:
        declared_modes = {_mode(item, "inventory.authority_mode") for item in _values(declared_modes_raw, "inventory.authority_modes")}
        if declared_modes != ALLOWED_AUTHORITY_MODES:
            raise CandidateAssemblyError("authority_modes_invalid", "inventory must declare exactly the two allowed modes")

    declared_routes = set(_declared(metadata, "inventory.writer_route"))
    if len(declared_routes) > 1:
        raise CandidateAssemblyError("double_writer_forbidden", "inventory declares multiple writer routes")
    inherited_route = next(iter(declared_routes), None)

    digests: list[str] = []
    modes: set[str] = set()
    routes: set[str] = set()
    component_ids: set[str] = set()
    for index, raw_component in enumerate(components):
        component = dict(raw_component)
        component_id = _text(
            _get(component, "componentId", "component_id", "id", "name"),
            f"component[{index}].component_id",
            "invalid_component_inventory",
            256,
        )
        if component_id in component_ids:
            raise CandidateAssemblyError("duplicate_component", f"duplicate component: {component_id}")
        component_ids.add(component_id)
        if _flag(component, _LEGACY_FIELDS) or "legacy" in component_id.lower():
            raise CandidateAssemblyError("legacy_writer_forbidden", f"{component_id} is a legacy writer")
        if _flag(component, _CREDENTIAL_FIELDS):
            raise CandidateAssemblyError("global_credential_fallback_forbidden", f"{component_id} uses credential fallback")
        if _flag(component, _DOUBLE_WRITER_FIELDS):
            raise CandidateAssemblyError("double_writer_forbidden", f"{component_id} declares a dual writer")

        raw_digest = _get(component, "digest", "componentDigest", "component_digest", "sourceDigest", "source_digest")
        digests.append(_digest(raw_digest, f"{component_id}.digest", "invalid_component_inventory"))
        modes.add(_component_mode(component, component_id))
        route = _component_route(component, component_id, inherited_route)
        routes.add(route)
        identity = f"{component_id} {route}".lower()
        if "legacy" in identity:
            raise CandidateAssemblyError("legacy_writer_forbidden", f"{component_id} is a legacy writer")
        if "credential" in identity and "fallback" in identity:
            raise CandidateAssemblyError("global_credential_fallback_forbidden", f"{component_id} uses credential fallback")
        if "dual" in identity or "double" in identity:
            raise CandidateAssemblyError("double_writer_forbidden", f"{component_id} declares a dual writer")

    if not components:
        raise CandidateAssemblyError("invalid_component_inventory", "component inventory cannot be empty")
    if modes != ALLOWED_AUTHORITY_MODES:
        raise CandidateAssemblyError("authority_modes_invalid", "inventory must cover exactly the two allowed modes")
    if declared_modes is not None and declared_modes != modes:
        raise CandidateAssemblyError("authority_modes_invalid", "declared and component modes differ")
    if len(routes) != 1:
        raise CandidateAssemblyError("writer_route_invalid", "inventory must use one writer route")
    writer_route = next(iter(routes))
    if inherited_route is not None and inherited_route != writer_route:
        raise CandidateAssemblyError("writer_route_invalid", "declared and component routes differ")
    if "legacy" in writer_route:
        raise CandidateAssemblyError("legacy_writer_forbidden", "inventory contains a legacy writer route")
    if "credential" in writer_route and "fallback" in writer_route:
        raise CandidateAssemblyError("global_credential_fallback_forbidden", "inventory contains a credential fallback route")
    if "dual" in writer_route or "double" in writer_route:
        raise CandidateAssemblyError("double_writer_forbidden", "inventory contains a dual writer route")
    return sorted(digests), writer_route


class Stage2CandidateAssembler:
    """Assemble one candidate after all three upstream projections pass."""

    def assemble(
        self,
        upstream: ReleaseGateResult | Mapping[str, Any],
        component_inventory: Any,
        candidate_id: str | None = None,
    ) -> dict[str, Any]:
        candidate, projection_digest, _ = _ready_gate(upstream, candidate_id)
        component_digests, writer_route = _normalize_inventory(component_inventory)
        receipt: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "candidateId": candidate,
            "projectionDigest": projection_digest,
            "componentDigests": component_digests,
            "releasePolicy": {
                "formalAcceptanceRequired": True,
                "productionRelease": False,
                "requiredProjections": list(PROJECTION_ORDER),
                "authorityModes": sorted(ALLOWED_AUTHORITY_MODES),
                "writerRoute": writer_route,
            },
            "ready": True,
        }
        receipt["receiptDigest"] = _hash_json(receipt)
        return copy.deepcopy(receipt)

    build = assemble


Stage2CandidateAssembly = Stage2CandidateAssembler


def assemble_candidate(upstream: ReleaseGateResult | Mapping[str, Any], component_inventory: Any, candidate_id: str | None = None) -> dict[str, Any]:
    return Stage2CandidateAssembler().assemble(upstream, component_inventory, candidate_id)


def assemble(upstream: ReleaseGateResult | Mapping[str, Any], component_inventory: Any, candidate_id: str | None = None) -> dict[str, Any]:
    return assemble_candidate(upstream, component_inventory, candidate_id)


__all__ = [
    "ALLOWED_AUTHORITY_MODES",
    "CandidateAssemblyError",
    "SCHEMA_VERSION",
    "Stage2CandidateAssembly",
    "Stage2CandidateAssemblyError",
    "Stage2CandidateAssembler",
    "assemble",
    "assemble_candidate",
]
