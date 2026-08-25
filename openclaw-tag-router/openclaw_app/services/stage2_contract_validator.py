"""Dependency-light, fail-closed validation for the Stage-2 writer contract.

The validator consumes an already loaded JSON-shaped mapping. It does not read
the contract file, import runtime adapters, or mutate the supplied mapping.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any


VALIDATOR_SCHEMA_VERSION = "stage2.contract_validator.v1"
CONTRACT_VERSION = "stage2_writer_contract.v1"
CONTRACT_SCHEMA_VERSION = 1

PERSONAL_ROUTE = ("personal_web", "internal")
ORGANIZATION_ROUTE = ("organization_lark", "lark")
SUPPORTED_ROUTES = frozenset((PERSONAL_ROUTE, ORGANIZATION_ROUTE))

_MISSING = object()
_CONTRACT_STATUSES = frozenset(
    {"draft", "provisional", "active", "accepted", "deprecated", "retired"}
)
_WRITE_STATUSES = frozenset({"written", "needs_attention", "rejected"})
_REGISTRATION_STATUSES = frozenset({"not_required", "registered", "pending", "failed"})
_READBACK_STATUSES = frozenset({"not_required", "confirmed", "pending", "failed"})
_OUTCOMES = frozenset({"reject", "needs_attention"})
_READ_EFFECTS = frozenset(
    {"read", "read_only", "readonly", "consultation", "none", "no_op"}
)
_WRITE_EFFECTS = frozenset(
    {"write", "document", "persist", "destructive", "document_write", "remote_write"}
)
_DISABLED_STATUSES = frozenset({"disabled", "retired", "not_implemented", "unavailable"})
_SUCCESS_STATUSES = frozenset(
    {
        "ok",
        "success",
        "succeeded",
        "complete",
        "completed",
        "created",
        "written",
        "registered",
        "verified",
        "ready",
        "replayed",
    }
)
_KNOWN_ERROR_CODES = frozenset(
    {
        "invalid_request",
        "contract_version_unsupported",
        "authority_override_forbidden",
        "authority_pair_invalid",
        "context_invalid",
        "context_receipt_invalid",
        "workspace_mismatch",
        "capability_not_registered",
        "capability_write_not_allowed",
        "idempotency_conflict",
        "write_failed",
        "registration_failed",
        "readback_incomplete",
        "external_write_needs_attention",
        "publish_blocked",
    }
)


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = _MISSING) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _safe_canonical(value: Any) -> Any:
    """Return a deterministic JSON-compatible representation for a digest."""

    if isinstance(value, Mapping):
        pairs = [
            (str(key), _safe_canonical(child))
            for key, child in value.items()
        ]
        pairs.sort(key=lambda item: item[0])
        result: dict[str, Any] = {}
        for key, child in pairs:
            result[key] = child
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_canonical(child) for child in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_safe_canonical(child) for child in value]
        return sorted(normalized, key=lambda child: json.dumps(child, sort_keys=True, ensure_ascii=False))
    if isinstance(value, float) and not math.isfinite(value):
        return {"__float__": repr(value)}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return {"__type__": type(value).__name__}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _safe_canonical(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def contract_digest(contract: Any) -> str:
    """Return the stable SHA-256 digest used by validation receipts."""

    return "sha256:" + hashlib.sha256(_canonical_json(contract).encode("utf-8")).hexdigest()


digest_contract = contract_digest


def _finding(findings: list[dict[str, Any]], code: str, path: str, message: str) -> None:
    findings.append({"code": code, "path": path, "message": message})


def _route_token(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower().replace(":", "/")
    aliases = {
        "personal": PERSONAL_ROUTE,
        "personal_web": PERSONAL_ROUTE,
        "internal": PERSONAL_ROUTE,
        "personal_web/internal": PERSONAL_ROUTE,
        "organization": ORGANIZATION_ROUTE,
        "organization_lark": ORGANIZATION_ROUTE,
        "lark": ORGANIZATION_ROUTE,
        "feishu": ORGANIZATION_ROUTE,
        "organization_lark/lark": ORGANIZATION_ROUTE,
    }
    if token in aliases:
        return aliases[token]
    if "/" not in token:
        return None
    authority, body = token.split("/", 1)
    route = (authority, body)
    return route if route in SUPPORTED_ROUTES else route


def _route_pair(value: Any) -> tuple[str, str] | None:
    if isinstance(value, str):
        return _route_token(value)
    if not isinstance(value, Mapping):
        return None

    for key in ("authorityMode", "authority_mode", "mode", "route"):
        candidate = value.get(key, _MISSING)
        if candidate is not _MISSING:
            route = _route_token(candidate)
            if route is not None:
                return route

    workspace = _first(value, "workspace", "workspaceMode", "workspace_mode", default=_MISSING)
    body = _first(
        value,
        "bodyAuthority",
        "body_authority",
        "body",
        default=_MISSING,
    )
    authority = _first(value, "authority", default=_MISSING)
    if isinstance(authority, str) and "/" in authority:
        route = _route_token(authority)
        if route is not None:
            return route
    if workspace is not _MISSING and body is not _MISSING:
        if isinstance(workspace, str) and isinstance(body, str):
            workspace_value = workspace.strip().lower()
            body_value = body.strip().lower()
            if workspace_value in {"internal", "lark"} and authority in {
                "personal_web",
                "organization_lark",
            }:
                workspace_value, body_value = authority, workspace_value
            return (workspace_value, body_value)
    if isinstance(authority, str) and isinstance(workspace, str):
        return (authority.strip().lower(), workspace.strip().lower())
    return None


def _entries(value: Any, *, kind: str) -> list[tuple[str, Any]]:
    if isinstance(value, (list, tuple)):
        return [(f"[{index}]", item) for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        route_keys = {
            "workspace",
            "workspaceMode",
            "workspace_mode",
            "bodyAuthority",
            "body_authority",
            "authorityMode",
            "authority_mode",
            "mode",
            "route",
        }
        capability_keys = {
            "id",
            "capabilityId",
            "capability_id",
            "effect",
            "sideEffect",
            "side_effect",
            "documentSideEffect",
            "document_side_effect",
        }
        marker_keys = route_keys if kind == "route" else capability_keys
        if set(value).intersection(marker_keys):
            return [("", value)]
        return [
            (f"[{key!s}]", {**item, "id": key} if isinstance(item, Mapping) else item)
            for key, item in value.items()
        ]
    return [("[0]", value)]


def _route_source(contract: Mapping[str, Any]) -> tuple[Any, str] | None:
    for key in ("routes", "routeModes", "route_modes", "routeDefinitions", "route_definitions"):
        if key in contract:
            return contract[key], f"$.{key}"
    policy = contract.get("authorityPolicy")
    if isinstance(policy, Mapping) and "workspaceBodyPairs" in policy:
        return policy["workspaceBodyPairs"], "$.authorityPolicy.workspaceBodyPairs"
    return None


def _binding_required_in_entry(entry: Mapping[str, Any]) -> bool:
    for key in (
        "bindingRequired",
        "requiresBinding",
        "requires_binding",
        "bindingIdentityRequired",
        "binding_identity_required",
    ):
        if entry.get(key) is True:
            return True
    nested = _first(entry, "binding", "bindingIdentity", "binding_identity", default=_MISSING)
    if isinstance(nested, Mapping):
        if nested.get("required") is True or nested.get("present") is True:
            return True
    required = _first(entry, "required", "requiredFields", "required_fields", default=())
    if isinstance(required, str):
        required = (required,)
    if isinstance(required, (list, tuple, set, frozenset)):
        normalized = {str(item).replace("_", "").lower() for item in required}
        if normalized.intersection(
            {"organizationbindingref", "bindingid", "bindingidentity", "bindinggeneration"}
        ):
            return True
    return False


def _global_binding_required(contract: Mapping[str, Any]) -> bool:
    policy = contract.get("authorityPolicy")
    if isinstance(policy, Mapping):
        fields = policy.get("serverDerivedFields", ())
        if isinstance(fields, (list, tuple, set, frozenset)):
            if "organizationBindingRef" in fields or "bindingIdentity" in fields:
                return True
    definitions = contract.get("$defs")
    context = definitions.get("trustedContext") if isinstance(definitions, Mapping) else None
    if not isinstance(context, Mapping):
        return False
    required = context.get("required", ())
    if "organizationBindingRef" not in required:
        return False
    for item in context.get("allOf", ()):
        if not isinstance(item, Mapping):
            continue
        workspace = (
            item.get("if", {})
            .get("properties", {})
            .get("workspace", {})
            .get("const")
            if isinstance(item.get("if"), Mapping)
            else None
        )
        if workspace == "organization_lark":
            return True
    return True


def _validate_routes(
    contract: Mapping[str, Any], findings: list[dict[str, Any]]
) -> set[tuple[str, str]]:
    source = _route_source(contract)
    if source is None:
        _finding(findings, "routes_missing", "$.routes", "route definitions are required")
        return set()

    seen: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()
    entries = _entries(source[0], kind="route")
    for suffix, raw in entries:
        path = source[1] + suffix
        if not isinstance(raw, Mapping):
            _finding(findings, "unknown_route", path, "route definition is not an object")
            continue
        route = _route_pair(raw)
        if route is None or route not in SUPPORTED_ROUTES:
            _finding(findings, "unknown_route", path, "route mode is not supported")
            continue
        route_id = _first(raw, "id", "routeId", "route_id", "name", default=_MISSING)
        if route_id is not _MISSING:
            normalized_id = str(route_id).strip()
            if normalized_id in seen_ids:
                _finding(findings, "duplicate_route_id", path, "route identifier is declared more than once")
            seen_ids.add(normalized_id)
        if route in seen:
            _finding(findings, "duplicate_route", path, "route mode is declared more than once")
        seen.add(route)

        remote_ref = _first(raw, "remoteRef", "remote_ref", default=_MISSING)
        if route == PERSONAL_ROUTE and remote_ref is not _MISSING and remote_ref != "forbidden":
            _finding(findings, "personal_remote_ref_invalid", path, "personal route forbids a remote reference")
        if route == ORGANIZATION_ROUTE and remote_ref is not _MISSING and remote_ref != "required":
            _finding(findings, "organization_remote_ref_invalid", path, "organization route requires a remote reference")
        if route == ORGANIZATION_ROUTE and not (
            _binding_required_in_entry(raw) or _global_binding_required(contract)
        ):
            _finding(
                findings,
                "organization_binding_required",
                path,
                "organization route must declare a required Binding identity",
            )

        for key in ("success", "successPath", "successResponse", "publishable", "publishability"):
            candidate = raw.get(key, _MISSING)
            if candidate is _MISSING or candidate is False or candidate is None:
                continue
            if isinstance(candidate, Mapping):
                _validate_success_shape(findings, candidate, f"{path}.{key}")
            elif candidate is True:
                _validate_success_shape(findings, raw, path)
    for required in SUPPORTED_ROUTES:
        if required not in seen:
            _finding(
                findings,
                "route_missing",
                source[1],
                f"required route {required[0]}/{required[1]} is missing",
            )
    return seen


def _capability_source(contract: Mapping[str, Any]) -> tuple[Any, str] | None:
    for key in (
        "capabilities",
        "capabilityEffects",
        "capability_effects",
        "capabilityRegistry",
        "capability_registry",
        "effects",
    ):
        if key in contract:
            return contract[key], f"$.{key}"
    return None


def _iter_values(value: Any) -> tuple[Any, ...]:
    if isinstance(value, str) or isinstance(value, Mapping):
        return (value,)
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    if value is _MISSING or value is None:
        return ()
    return (value,)


def _normalize_effect(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "_")


def _validate_capabilities(
    contract: Mapping[str, Any],
    route_pairs: set[tuple[str, str]],
    findings: list[dict[str, Any]],
) -> None:
    source = _capability_source(contract)
    if source is None:
        return
    seen_ids: set[str] = set()
    for suffix, raw in _entries(source[0], kind="capability"):
        path = source[1] + suffix
        if not isinstance(raw, Mapping):
            _finding(findings, "capability_invalid", path, "capability definition is not an object")
            continue
        capability_id = _first(raw, "id", "capabilityId", "capability_id", default=_MISSING)
        if not isinstance(capability_id, str) or not capability_id.strip():
            _finding(findings, "capability_id_missing", path, "capability id is required")
            continue
        capability_id = capability_id.strip()
        if capability_id in seen_ids:
            _finding(findings, "duplicate_capability_id", path, "capability id is declared more than once")
        seen_ids.add(capability_id)

        status = _first(raw, "status", "state", default=_MISSING)
        if status is not _MISSING:
            if not isinstance(status, str) or status.strip().lower() not in (
                _CONTRACT_STATUSES | _DISABLED_STATUSES
            ):
                _finding(findings, "invalid_status_vocabulary", f"{path}.status", "capability status is unsupported")
        registered = raw.get("registered", _MISSING)
        enabled = raw.get("enabled", _MISSING)
        status_value = status.strip().lower() if isinstance(status, str) else ""
        if registered is False or enabled is False or status_value in _DISABLED_STATUSES:
            _finding(findings, "capability_unregistered", path, "capability is not registered for execution")

        effect_value = _first(
            raw,
            "effect",
            "sideEffect",
            "side_effect",
            "writeEffect",
            "write_effect",
            default=_MISSING,
        )
        document_side_effect = _first(raw, "documentSideEffect", "document_side_effect", default=_MISSING)
        read_only = _first(raw, "readOnly", "read_only", default=False)
        remote_write = _first(raw, "remoteWrite", "remote_write", default=False)
        writes_to = _first(raw, "writesTo", "writes_to", default=_MISSING)
        write_targets = _iter_values(writes_to)
        normalized_effect = _normalize_effect(effect_value)
        if normalized_effect in _READ_EFFECTS:
            effect_kind = "read"
        elif normalized_effect in _WRITE_EFFECTS:
            effect_kind = "write"
        elif effect_value is _MISSING:
            if document_side_effect is True or remote_write is True or write_targets:
                effect_kind = "write"
            elif read_only is True:
                effect_kind = "read"
            else:
                effect_kind = ""
        else:
            effect_kind = ""

        has_write_effect = (
            effect_kind == "write"
            or document_side_effect is True
            or remote_write is True
            or bool(write_targets)
        )
        if not effect_kind:
            _finding(findings, "capability_effect_unregistered", path, "capability effect is unsupported or missing")
        if not isinstance(read_only, bool):
            _finding(findings, "capability_effect_contradictory", f"{path}.readOnly", "readOnly must be boolean")
        if read_only is True and has_write_effect:
            _finding(
                findings,
                "capability_effect_contradictory",
                path,
                "read-only capability cannot declare document or remote write effects",
            )
        if effect_kind == "read" and document_side_effect is True:
            _finding(findings, "capability_effect_contradictory", path, "read capability declares a document write effect")
        if effect_kind == "read" and remote_write is True:
            _finding(findings, "capability_effect_contradictory", path, "read capability declares a remote write effect")

        modes_value = _first(
            raw,
            "allowedAuthorityModes",
            "allowed_authority_modes",
            "allowedRoutes",
            "allowed_routes",
            default=_MISSING,
        )
        if modes_value is _MISSING:
            modes_value = writes_to
        modes = _iter_values(modes_value)
        normalized_modes: set[tuple[str, str]] = set()
        for index, mode in enumerate(modes):
            route = _route_pair(mode)
            if route is None or route not in SUPPORTED_ROUTES:
                _finding(
                    findings,
                    "capability_route_unknown",
                    f"{path}.allowedAuthorityModes[{index}]",
                    "capability authority mode is not supported",
                )
            else:
                normalized_modes.add(route)
                if route_pairs and route not in route_pairs:
                    _finding(
                        findings,
                        "capability_route_unregistered",
                        f"{path}.allowedAuthorityModes[{index}]",
                        "capability authority mode is not declared by the contract",
                    )
        if effect_kind == "write" and not normalized_modes:
            _finding(
                findings,
                "capability_authority_modes_missing",
                path,
                "document-writing capability must declare an allowed authority mode",
            )

        readback_value = _first(raw, "requiresReadback", "requires_readback", default=_MISSING)
        if effect_kind == "write":
            if readback_value is _MISSING:
                _finding(
                    findings,
                    "capability_readback_missing",
                    path,
                    "document-writing capability must declare required readback",
                )
            elif readback_value is not True:
                _finding(
                    findings,
                    "capability_readback_required",
                    path,
                    "document-writing capability must require readback",
                )
        elif effect_kind == "read" and readback_value is True:
            _finding(
                findings,
                "capability_effect_contradictory",
                path,
                "read-only capability cannot require document readback",
            )


def _enum_from(value: Any) -> set[Any] | None:
    if isinstance(value, Mapping) and isinstance(value.get("enum"), list):
        return set(value["enum"])
    return None


def _nested_enum(value: Any) -> set[Any] | None:
    direct = _enum_from(value)
    if direct is not None:
        return direct
    if isinstance(value, Mapping):
        for child in value.values():
            found = _nested_enum(child)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _nested_enum(child)
            if found is not None:
                return found
    return None


def _required_fields(value: Mapping[str, Any]) -> set[str]:
    required = value.get("required", ())
    if isinstance(required, str):
        return {required}
    if isinstance(required, (list, tuple, set, frozenset)):
        return {str(item) for item in required}
    return set()


def _validate_success_shape(
    findings: list[dict[str, Any]], value: Mapping[str, Any], path: str
) -> None:
    required = _required_fields(value)
    normalized = {item.replace("_", "").lower() for item in required}
    required_names = {
        "artifact",
        "registration",
        "readback",
    }
    missing = sorted(required_names - normalized)
    for field in missing:
        _finding(
            findings,
            "publishability_invariant_missing",
            path,
            f"success or publishable path must require {field}",
        )


def _validate_schema_and_status(
    contract: Mapping[str, Any], findings: list[dict[str, Any]]
) -> None:
    if contract.get("contractVersion") != CONTRACT_VERSION:
        _finding(findings, "contract_version_unsupported", "$.contractVersion", "unsupported contract version")
    schema_version = contract.get("schemaVersion", _MISSING)
    if schema_version is _MISSING or schema_version != CONTRACT_SCHEMA_VERSION:
        _finding(findings, "schema_version_unsupported", "$.schemaVersion", "unsupported schema version")
    status = contract.get("status", _MISSING)
    if status is not _MISSING and (
        not isinstance(status, str) or status.strip().lower() not in _CONTRACT_STATUSES
    ):
        _finding(findings, "invalid_status_vocabulary", "$.status", "contract status is unsupported")

    definitions = contract.get("$defs")
    if not isinstance(definitions, Mapping):
        _finding(findings, "schema_definitions_missing", "$.$defs", "contract schema definitions are required")
        return
    versioned_definitions = {
        "trustedContext",
        "contextReceipt",
        "writerRequest",
        "writeResult",
        "failClosedError",
    }
    for name in (
        "trustedContext",
        "contextReceipt",
        "writerRequest",
        "writeResult",
        "registrationState",
        "readbackState",
        "failClosedError",
    ):
        definition = definitions.get(name)
        if not isinstance(definition, Mapping):
            _finding(findings, "schema_definition_missing", f"$.$defs.{name}", "required schema definition is missing")
            continue
        properties = definition.get("properties")
        schema_property = properties.get("schemaVersion") if isinstance(properties, Mapping) else None
        if name in versioned_definitions and schema_property != {"const": CONTRACT_VERSION}:
            _finding(
                findings,
                "schema_version_unsupported",
                f"$.$defs.{name}.properties.schemaVersion",
                "schema definition must use the Stage-2 contract version",
            )

    write_result = definitions.get("writeResult")
    if not isinstance(write_result, Mapping):
        return
    properties = write_result.get("properties")
    if not isinstance(properties, Mapping):
        _finding(findings, "schema_invalid", "$.$defs.writeResult.properties", "write result properties are required")
        return
    required = _required_fields(write_result)
    for field in ("artifact", "registration", "readback"):
        if field not in required:
            _finding(
                findings,
                "publishability_invariant_missing",
                "$.$defs.writeResult.required",
                f"write result must require {field} before success or publishability",
            )

    status_enum = _enum_from(properties.get("status"))
    if status_enum is None or not status_enum or not status_enum.issubset(_WRITE_STATUSES):
        _finding(findings, "invalid_status_vocabulary", "$.$defs.writeResult.properties.status", "write result status vocabulary is invalid")

    publishable = properties.get("publishable")
    if isinstance(publishable, Mapping) and publishable.get("const") is True:
        _validate_success_shape(findings, write_result, "$.$defs.writeResult")
    elif publishable is None:
        _finding(findings, "publishability_invariant_missing", "$.$defs.writeResult.properties.publishable", "publishability must be explicit")

    registration = definitions.get("registrationState")
    if isinstance(registration, Mapping):
        registration_properties = registration.get("properties", {})
        registration_enum = _enum_from(registration_properties.get("status")) if isinstance(registration_properties, Mapping) else None
        if _required_fields(registration) != {"status"} or registration_enum is None or not registration_enum.issubset(_REGISTRATION_STATUSES):
            _finding(findings, "invalid_status_vocabulary", "$.$defs.registrationState", "registration status vocabulary is invalid")

    readback = definitions.get("readbackState")
    if isinstance(readback, Mapping):
        readback_properties = readback.get("properties", {})
        readback_enum = _enum_from(readback_properties.get("status")) if isinstance(readback_properties, Mapping) else None
        if _required_fields(readback) != {"status"} or readback_enum is None or not readback_enum.issubset(_READBACK_STATUSES):
            _finding(findings, "invalid_status_vocabulary", "$.$defs.readbackState", "readback status vocabulary is invalid")

    error_codes = contract.get("errorCodes")
    if not isinstance(error_codes, list) or not error_codes:
        _finding(findings, "error_vocabulary_missing", "$.errorCodes", "error code vocabulary is required")
        return
    codes: list[str] = []
    for index, item in enumerate(error_codes):
        path = f"$.errorCodes[{index}]"
        if not isinstance(item, Mapping):
            _finding(findings, "error_vocabulary_invalid", path, "error code entry is not an object")
            continue
        code = item.get("code")
        if not isinstance(code, str) or not code.strip():
            _finding(findings, "error_code_missing", f"{path}.code", "error code is required")
            continue
        code = code.strip()
        if code in codes:
            _finding(findings, "duplicate_error_code", f"{path}.code", "error code is declared more than once")
        codes.append(code)
        if code not in _KNOWN_ERROR_CODES:
            _finding(findings, "unknown_error_code", f"{path}.code", "error code is outside the Stage-2 vocabulary")
        if item.get("failClosed") is not True:
            _finding(findings, "error_not_fail_closed", path, "every error code must be fail-closed")
        if item.get("outcome") not in _OUTCOMES:
            _finding(findings, "invalid_status_vocabulary", f"{path}.outcome", "error outcome is unsupported")
    expected_codes = set(codes)
    fail_closed = definitions.get("failClosedError")
    if isinstance(fail_closed, Mapping):
        envelope_codes = _nested_enum(
            fail_closed.get("properties", {}).get("error", {})
            if isinstance(fail_closed.get("properties"), Mapping)
            else None
        )
        if envelope_codes != expected_codes:
            _finding(findings, "error_vocabulary_mismatch", "$.$defs.failClosedError", "error envelope vocabulary does not match errorCodes")
    result_codes = _nested_enum(properties.get("errorCode"))
    if result_codes is not None and result_codes != expected_codes:
        _finding(findings, "error_vocabulary_mismatch", "$.$defs.writeResult.properties.errorCode", "write result error vocabulary does not match errorCodes")


def _validate_extra_publishability(
    contract: Mapping[str, Any], findings: list[dict[str, Any]]
) -> None:
    for key in (
        "success",
        "successPath",
        "successResponse",
        "publishable",
        "publishability",
        "successResult",
        "publishableResult",
    ):
        value = contract.get(key, _MISSING)
        if value is _MISSING or value is False or value is None:
            continue
        if isinstance(value, Mapping):
            _validate_success_shape(findings, value, f"$.{key}")
        elif value is True:
            _finding(findings, "publishability_invariant_missing", f"$.{key}", "publishable path must declare artifact, registration, and readback")


def _sorted_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {
        (item["code"], item["path"], item["message"]): item
        for item in findings
    }
    return [
        unique[key]
        for key in sorted(unique, key=lambda item: (item[0], item[1], item[2]))
    ]


def load_contract(
    source: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Accept a mapping or an explicitly injected loader without doing I/O."""

    loaded = source() if callable(source) else source
    if not isinstance(loaded, Mapping):
        raise TypeError("injected contract source must return a mapping")
    return loaded


def validate_contract(
    contract: Mapping[str, Any] | None = None,
    *,
    loader: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate a JSON-shaped mapping and return a deterministic receipt.

    A loader is invoked only when explicitly supplied. With no mapping and no
    loader the function returns an invalid receipt and performs no file I/O.
    """

    supplied: Any = contract
    findings: list[dict[str, Any]] = []
    if supplied is None and loader is not None:
        try:
            supplied = load_contract(loader)
        except Exception as exc:
            _finding(findings, "contract_input_invalid", "$", f"injected contract loader failed: {type(exc).__name__}")
    if not isinstance(supplied, Mapping):
        _finding(findings, "contract_input_invalid", "$", "contract must be a JSON object mapping")
    else:
        try:
            _validate_schema_and_status(supplied, findings)
            route_pairs = _validate_routes(supplied, findings)
            _validate_capabilities(supplied, route_pairs, findings)
            _validate_extra_publishability(supplied, findings)
        except Exception as exc:
            _finding(findings, "validator_internal_error", "$", f"validation failed closed: {type(exc).__name__}")

    return {
        "schemaVersion": VALIDATOR_SCHEMA_VERSION,
        "contractDigest": contract_digest(supplied),
        "findings": _sorted_findings(findings),
        "valid": not findings,
    }


validate_stage2_contract = validate_contract


class Stage2ContractValidator:
    """Small injectable facade for callers that prefer an object API."""

    def validate(
        self,
        contract: Mapping[str, Any] | None = None,
        *,
        loader: Callable[[], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return validate_contract(contract, loader=loader)


class Stage2ContractValidationError(ValueError):
    """Raised by a startup/release owner when the persisted contract is invalid."""

    def __init__(self, path: str | Path, receipt: Mapping[str, Any]) -> None:
        self.path = str(path)
        self.receipt = dict(receipt)
        findings = self.receipt.get("findings", ())
        summary = "; ".join(
            str(item.get("code", "contract_invalid"))
            for item in findings
            if isinstance(item, Mapping)
        ) or "contract_invalid"
        super().__init__(f"Stage-2 contract validation failed for {self.path}: {summary}")


def validate_contract_file(path: str | Path) -> dict[str, Any]:
    """Load and validate the immutable JSON contract used by a start workflow."""

    contract_path = Path(path)
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except Exception as exc:
        receipt = validate_contract(None)
        receipt["findings"] = [
            {
                "code": "contract_input_invalid",
                "path": str(contract_path),
                "message": f"contract file could not be loaded: {type(exc).__name__}",
            }
        ]
        receipt["valid"] = False
        raise Stage2ContractValidationError(contract_path, receipt) from exc

    receipt = validate_contract(contract)
    if not receipt["valid"]:
        raise Stage2ContractValidationError(contract_path, receipt)
    return receipt


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "CONTRACT_VERSION",
    "ORGANIZATION_ROUTE",
    "PERSONAL_ROUTE",
    "SUPPORTED_ROUTES",
    "Stage2ContractValidator",
    "Stage2ContractValidationError",
    "VALIDATOR_SCHEMA_VERSION",
    "contract_digest",
    "digest_contract",
    "load_contract",
    "validate_contract",
    "validate_contract_file",
    "validate_stage2_contract",
]
