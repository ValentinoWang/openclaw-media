"""Fail-closed document writing boundary for the Phase-2 Media paths.

The router deliberately owns only the boundary and its in-process receipt
store. Feishu, database, and document implementations remain injected
adapters so focused tests cannot create external side effects.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import threading
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Protocol


SCHEMA_VERSION = "stage2.writer.result.v1"
PERSONAL_ROUTE = ("personal_web", "internal")
ORGANIZATION_ROUTE = ("organization_lark", "lark")
_SUPPORTED_ROUTES = frozenset((PERSONAL_ROUTE, ORGANIZATION_ROUTE))
_MISSING = object()

_SUCCESS_STATES = frozenset(
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
_FAILURE_STATES = frozenset(
    {
        "error",
        "failed",
        "failure",
        "invalid",
        "rejected",
        "conflict",
        "unavailable",
        "needs_attention",
    }
)
_READ_EFFECTS = frozenset({"read", "read_only", "readonly", "consultation", "none", "no_op"})
_WRITE_EFFECTS = frozenset({"write", "document", "persist", "destructive"})
_DISABLED_STATES = frozenset({"disabled", "retired", "not_implemented", "unavailable"})


class WriterRouterError(RuntimeError):
    """A fail-closed input or idempotency error raised before/around routing."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class IdempotencyConflict(WriterRouterError):
    def __init__(self, message: str = "idempotency key was already used for another request") -> None:
        super().__init__("idempotency_conflict", message)


@dataclass(frozen=True)
class Binding:
    """Minimal server-owned Binding shape useful for adapters and focused tests."""

    tenant_id: str
    binding_id: str
    generation: str
    status: str = "active"


@dataclass(frozen=True)
class AIExecutionContext:
    """Trusted server-built context consumed by the writer boundary."""

    authority: str
    workspace: str
    tenant_id: str
    active_binding: Any | None = None
    principal_id: str | None = None
    session_id: str | None = None


TrustedAIContext = AIExecutionContext


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    effect: str
    writes_to: tuple[str, ...] = ()
    requires_readback: bool = True


class CapabilityEffectRegistry:
    """Small injectable registry facade for the router's side-effect gate."""

    def __init__(self, definitions: Mapping[str, Any] | None = None) -> None:
        self._definitions = dict(definitions or {})

    def get(self, capability_id: str) -> Any:
        return self._definitions.get(capability_id)


@dataclass(frozen=True)
class WriterRequest:
    context: Any
    content: Any
    capability_id: str
    idempotency_key: str
    active_binding: Any | None
    context_receipt: Any | None
    authority: str
    workspace: str


@dataclass(frozen=True)
class ReceiptRecord:
    request_fingerprint: str
    response: dict[str, Any]


class WriterAdapter(Protocol):
    def write(self, request: WriterRequest) -> Any: ...


class ArtifactRegistrar(Protocol):
    def register(self, request: WriterRequest, writer_result: Mapping[str, Any]) -> Any: ...


class ReadbackVerifier(Protocol):
    def readback(self, request: WriterRequest, writer_result: Mapping[str, Any]) -> Any: ...


class ReceiptStore(Protocol):
    def get(self, key: str) -> ReceiptRecord | Mapping[str, Any] | None: ...

    def put(self, key: str, request_fingerprint: str, response: Mapping[str, Any]) -> None: ...


class InMemoryReceiptStore:
    """Thread-safe receipt storage with no filesystem, database, or network effects."""

    def __init__(self) -> None:
        self._records: dict[str, ReceiptRecord] = {}
        self._lock = threading.RLock()

    @property
    def records(self) -> dict[str, ReceiptRecord]:
        with self._lock:
            return dict(self._records)

    def get(self, key: str) -> ReceiptRecord | None:
        with self._lock:
            record = self._records.get(key)
            return copy.deepcopy(record) if record is not None else None

    def put(self, key: str, request_fingerprint: str, response: Mapping[str, Any]) -> None:
        with self._lock:
            existing = self._records.get(key)
            if existing is not None and existing.request_fingerprint != request_fingerprint:
                raise IdempotencyConflict()
            if existing is None:
                self._records[key] = ReceiptRecord(
                    request_fingerprint=request_fingerprint,
                    response=copy.deepcopy(dict(response)),
                )


@dataclass(frozen=True)
class _ContextInfo:
    context: Any
    authority: str
    workspace: str
    tenant_scope: str
    principal_scope: str
    binding: Any | None
    binding_identity: str | None

    @property
    def route(self) -> tuple[str, str]:
        return self.authority, self.workspace


@dataclass(frozen=True)
class _CapabilityInfo:
    capability_id: str
    effect: str
    allowed_routes: frozenset[tuple[str, str]]
    requires_readback: bool


@dataclass(frozen=True)
class _NormalizedResult:
    raw: Mapping[str, Any]
    write: dict[str, Any]
    registration: dict[str, Any] | None
    readback: dict[str, Any] | None
    remote_ref: str | None
    artifact_ref: str | None


def _lookup(value: Any, *names: str, default: Any = _MISSING) -> Any:
    if value is None:
        return default
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    to_mapping = getattr(value, "to_mapping", None)
    if callable(to_mapping):
        converted = to_mapping()
        if isinstance(converted, Mapping):
            return dict(converted)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    try:
        converted = vars(value)
    except TypeError:
        return None
    return dict(converted) if isinstance(converted, Mapping) else None


def _canonical(value: Any) -> Any:
    if is_dataclass(value):
        return _canonical(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(item) for item in value), key=lambda item: repr(item))
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return {"type": type(value).__name__}


def _canonical_json(value: Any) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required_text(value: Any, field_name: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str):
        raise WriterRouterError("invalid_request", f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length or any(ord(char) < 32 for char in normalized):
        raise WriterRouterError("invalid_request", f"{field_name} is invalid")
    return normalized


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, Mapping):
        return bool(value)
    return True


def _binding_descriptor(binding: Any) -> tuple[str, str, str]:
    binding_tenant = _lookup(binding, "tenant_id", "tenantId", "organization_id", default="")
    binding_id = _lookup(
        binding,
        "binding_id",
        "bindingId",
        "public_binding_id",
        "publicBindingId",
        "id",
        default="",
    )
    generation = _lookup(
        binding,
        "generation",
        "binding_generation",
        "bindingGeneration",
        "credential_generation",
        "credentialGeneration",
        "generation_id",
        "generationId",
        default="",
    )
    tenant = str(binding_tenant).strip() if binding_tenant not in (None, "") else ""
    identifier = str(binding_id).strip() if binding_id not in (None, "") else ""
    version = str(generation).strip() if generation not in (None, "") else ""
    if not (tenant or identifier or version):
        raise WriterRouterError("invalid_context", "active Binding has no stable server identity")
    return tenant, identifier, version


def _binding_identity(binding: Any) -> str:
    tenant, identifier, generation = _binding_descriptor(binding)
    payload = {
        "tenant_id": tenant,
        "binding_id": identifier,
        "generation": generation,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _context_info(context: Any) -> _ContextInfo:
    if context is None:
        raise WriterRouterError("invalid_context", "trusted AI context is required")
    authority = _lookup(context, "authority", "authority_mode", "body_authority", "bodyAuthority", default="")
    workspace = _lookup(context, "workspace", "workspace_mode", "body_workspace", default="")
    authority = _required_text(authority, "authority", max_length=80).lower()
    workspace = _required_text(workspace, "workspace", max_length=80).lower()
    # The shared Stage-2 context exposes authority_mode as a combined value
    # while retaining workspace_mode as the workspace name. Normalize that
    # server-produced shape to the router's (authority, body) route tuple.
    if "/" in authority:
        combined_authority, combined_workspace = authority.split("/", 1)
        if combined_authority in {"personal_web", "organization_lark"} and combined_workspace in {"internal", "lark"}:
            authority = combined_authority
            if workspace in {"personal_web", "organization_lark"}:
                workspace = combined_workspace
    else:
        body_authority = _lookup(context, "body_authority", "bodyAuthority", default="")
        if (
            isinstance(body_authority, str)
            and body_authority.strip().lower() in {"internal", "lark"}
            and workspace in {"personal_web", "organization_lark"}
        ):
            workspace = body_authority.strip().lower()
    route = (authority, workspace)
    if route not in _SUPPORTED_ROUTES:
        raise WriterRouterError(
            "authority_mismatch",
            "trusted context authority/workspace pair is not supported",
        )

    tenant = _lookup(
        context,
        "tenant_id",
        "tenantId",
        "organization_id",
        "organizationId",
        default="",
    )
    principal = _lookup(
        context,
        "principal_id",
        "principalId",
        "user_public_id",
        "userPublicId",
        "user_id",
        "userId",
        "subject_id",
        "subjectId",
        default="",
    )
    tenant_scope = str(tenant).strip() if isinstance(tenant, str) else ""
    principal_scope = str(principal).strip() if isinstance(principal, str) else ""
    binding = _lookup(context, "active_binding", "activeBinding", "binding", default=None)
    if binding is None:
        # AIExecutionContext carries the active Binding identity as fields
        # rather than a nested object. Treat that server-owned identity as the
        # binding input without accepting any caller-selected credentials.
        context_binding_id = _lookup(context, "binding_id", "bindingId", default=None)
        context_binding_generation = _lookup(
            context,
            "binding_generation",
            "bindingGeneration",
            default=None,
        )
        if context_binding_id is not None or context_binding_generation is not None:
            binding = context

    if route == PERSONAL_ROUTE:
        if _present(binding):
            raise WriterRouterError(
                "authority_mismatch",
                "personal_web/internal context cannot carry an organization Binding",
            )
        if not (tenant_scope or principal_scope):
            raise WriterRouterError("invalid_context", "personal context lacks a server identity")
        return _ContextInfo(
            context=context,
            authority=authority,
            workspace=workspace,
            tenant_scope=tenant_scope or principal_scope,
            principal_scope=principal_scope,
            binding=None,
            binding_identity=None,
        )

    if not _present(binding):
        raise WriterRouterError(
            "authority_mismatch",
            "organization_lark/lark context requires an active Binding",
        )
    binding_tenant, _binding_id, _generation = _binding_descriptor(binding)
    if binding_tenant and tenant_scope and binding_tenant != tenant_scope:
        raise WriterRouterError(
            "authority_mismatch",
            "active Binding does not belong to the trusted context tenant",
        )
    status = _lookup(binding, "status", "state", default=_MISSING)
    active = _lookup(binding, "active", "is_active", "isActive", default=_MISSING)
    if active is False or (
        isinstance(status, str) and status.strip().lower() not in {"active", "enabled", "current"}
    ):
        raise WriterRouterError("authority_mismatch", "active Binding is not active")
    if not tenant_scope and binding_tenant:
        tenant_scope = binding_tenant
    if not (tenant_scope or principal_scope):
        raise WriterRouterError("invalid_context", "organization context lacks a server identity")
    return _ContextInfo(
        context=context,
        authority=authority,
        workspace=workspace,
        tenant_scope=tenant_scope or principal_scope,
        principal_scope=principal_scope,
        binding=binding,
        binding_identity=_binding_identity(binding),
    )


def _target_route(value: Any) -> tuple[str, str] | None:
    if isinstance(value, Mapping):
        authority = _lookup(value, "authority", "body_authority", default="")
        workspace = _lookup(value, "workspace", "workspace_mode", default="")
        if isinstance(authority, str) and isinstance(workspace, str):
            route = (authority.strip().lower(), workspace.strip().lower())
            return route if route in _SUPPORTED_ROUTES else None
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace(":", "/")
    if normalized in {"personal", "personal_web", "internal", "personal_web/internal"}:
        return PERSONAL_ROUTE
    if normalized in {"organization", "organization_lark", "lark", "feishu", "organization_lark/lark"}:
        return ORGANIZATION_ROUTE
    if "/" in normalized:
        authority, workspace = normalized.split("/", 1)
        route = (authority, workspace)
        return route if route in _SUPPORTED_ROUTES else None
    return None


def _iter_targets(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or isinstance(value, Mapping):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _capability_info(registry: Any, capability_id: str) -> _CapabilityInfo:
    definition = registry.get(capability_id) if hasattr(registry, "get") else None
    if definition is None:
        raise WriterRouterError(
            "capability_unregistered",
            f"capability {capability_id!r} has no registered side-effect contract",
        )
    if isinstance(definition, CapabilitySpec):
        raw = {
            "effect": definition.effect,
            "writes_to": definition.writes_to,
            "requires_readback": definition.requires_readback,
        }
    else:
        raw = _as_mapping(definition) or {}
    enabled = _lookup(definition, "enabled", default=_MISSING)
    status = _lookup(definition, "status", "state", default=_MISSING)
    if enabled is False or (isinstance(status, str) and status.strip().lower() in _DISABLED_STATES):
        raise WriterRouterError("capability_unregistered", f"capability {capability_id!r} is not executable")
    effect = _lookup(raw, "effect", "side_effect", "sideEffect", "write_effect", default=_MISSING)
    document_side_effect = _lookup(
        raw,
        "document_side_effect",
        "documentSideEffect",
        default=_MISSING,
    )
    if effect is _MISSING and document_side_effect is not _MISSING:
        effect = "write" if document_side_effect else "read"
    read_only = _lookup(raw, "read_only", "readOnly", default=False)
    if read_only is True or document_side_effect is False:
        normalized_effect = "read"
    elif isinstance(effect, str):
        normalized_effect = effect.strip().lower()
    else:
        normalized_effect = ""
    if normalized_effect in _READ_EFFECTS:
        return _CapabilityInfo(capability_id, "read", frozenset(), False)
    if normalized_effect not in _WRITE_EFFECTS:
        raise WriterRouterError(
            "capability_effect_unregistered",
            f"capability {capability_id!r} does not declare a supported effect",
        )

    targets = _iter_targets(
        _lookup(
            raw,
            "writes_to",
            "writesTo",
            "allowed_routes",
            "allowedRoutes",
            "allowed_authority_modes",
            "allowedAuthorityModes",
            default=(),
        )
    )
    allowed = frozenset(route for route in (_target_route(item) for item in targets) if route is not None)
    if targets and not allowed:
        raise WriterRouterError(
            "capability_effect_unregistered",
            f"capability {capability_id!r} has no supported write target",
        )
    requires_readback = _lookup(raw, "requires_readback", "requiresReadback", default=True)
    return _CapabilityInfo(capability_id, "write", allowed, bool(requires_readback))


def _status(value: Any, *, stage: str) -> str:
    if isinstance(value, bool):
        return "succeeded" if value else "failed"
    mapping = _as_mapping(value)
    if mapping is not None:
        ok = _lookup(mapping, "ok", "success", default=_MISSING)
        if isinstance(ok, bool):
            return "succeeded" if ok else "failed"
        if stage == "registration":
            registered = _lookup(mapping, "registered", "is_registered", default=_MISSING)
            if isinstance(registered, bool):
                return "succeeded" if registered else "failed"
        if stage == "readback":
            verified = _lookup(mapping, "verified", "readback_ok", "readbackOk", default=_MISSING)
            if isinstance(verified, bool):
                return "succeeded" if verified else "failed"
        value = _lookup(mapping, "status", "state", "outcome", default="")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _SUCCESS_STATES:
            return "succeeded"
        if normalized in _FAILURE_STATES:
            return "failed"
        if normalized in {"pending", "running", "reserved", "in_progress", "incomplete"}:
            return "incomplete"
    return "incomplete"


def _stage(value: Any, *, stage: str) -> dict[str, Any]:
    mapping = _as_mapping(value)
    if mapping is None:
        state = _status(value, stage=stage)
        return {"status": state, "ok": state == "succeeded"}
    state = _status(mapping, stage=stage)
    result: dict[str, Any] = {"status": state, "ok": state == "succeeded"}
    artifact_ref = _lookup(
        mapping,
        "artifact_ref",
        "artifactRef",
        "artifact_id",
        "artifactId",
        "local_ref",
        "localRef",
        default=_MISSING,
    )
    remote_ref = _lookup(
        mapping,
        "remote_ref",
        "remoteRef",
        "remote_document_ref",
        "remoteDocumentRef",
        "document_url",
        "documentUrl",
        "url",
        default=_MISSING,
    )
    if artifact_ref is not _MISSING and artifact_ref not in (None, ""):
        result["artifact_ref"] = str(artifact_ref)
    if remote_ref is not _MISSING:
        normalized_ref = _remote_ref(remote_ref)
        if normalized_ref is not None:
            result["remote_ref"] = normalized_ref
    for source, target in (
        ("revision", "revision"),
        ("version", "version"),
        ("body_checksum", "body_checksum"),
        ("bodyChecksum", "body_checksum"),
    ):
        candidate = mapping.get(source, _MISSING)
        if candidate is not _MISSING and candidate not in (None, ""):
            result[target] = str(candidate)
    error = _lookup(mapping, "error", "failure", "message", default=_MISSING)
    if error is not _MISSING and error not in (None, ""):
        if isinstance(error, Mapping):
            error_code = _lookup(error, "code", "error_code", "errorCode", default="")
            error_message = _lookup(error, "message", "detail", default="")
            result["error"] = {
                "code": str(error_code).strip() if error_code else "stage_failed",
                "message": str(error_message).strip()[:240] if error_message else "stage failed",
            }
        else:
            result["error"] = {"code": "stage_failed", "message": str(error).strip()[:240]}
    return result


def _remote_ref(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, Mapping):
        nested = _lookup(value, "id", "document_id", "documentId", "token", "url", default="")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


def _first_ref(*values: Any) -> str | None:
    for value in values:
        mapping = _as_mapping(value)
        if mapping is not None:
            candidate = _lookup(
                mapping,
                "remote_ref",
                "remoteRef",
                "remote_document_ref",
                "remoteDocumentRef",
                "document_url",
                "documentUrl",
                "url",
                default=_MISSING,
            )
            if candidate is not _MISSING:
                normalized = _remote_ref(candidate)
                if normalized is not None:
                    return normalized
        else:
            normalized = _remote_ref(value)
            if normalized is not None:
                return normalized
    return None


def _first_artifact_ref(*values: Any) -> str | None:
    for value in values:
        mapping = _as_mapping(value)
        if mapping is None:
            continue
        candidate = _lookup(
            mapping,
            "artifact_ref",
            "artifactRef",
            "artifact_id",
            "artifactId",
            "local_ref",
            "localRef",
            default=_MISSING,
        )
        if candidate is not _MISSING and candidate not in (None, ""):
            return str(candidate)
    return None


def _result_mapping(raw: Any) -> dict[str, Any] | None:
    mapping = _as_mapping(raw)
    return mapping if mapping else None


def _normalize_writer_result(raw: Any, *, requires_readback: bool) -> _NormalizedResult:
    mapping = _result_mapping(raw)
    if mapping is None:
        raise WriterRouterError("writer_result_invalid", "writer did not return an object result")
    write_found, write_value = _field(mapping, "write", "write_result", "writeResult")
    write_value = write_value if write_found else mapping
    write = _stage(write_value, stage="write")
    registration_found, registration_value = _field(
        mapping,
        "registration",
        "registration_result",
        "registrationResult",
        "registered",
    )
    registration = _stage(registration_value, stage="registration") if registration_found else None
    readback_found, readback_value = _field(
        mapping,
        "readback",
        "readback_result",
        "readbackResult",
        "readback_ok",
        "readbackOk",
    )
    readback = _stage(readback_value, stage="readback") if readback_found else None
    return _NormalizedResult(
        raw=mapping,
        write=write,
        registration=registration,
        readback=readback,
        remote_ref=_first_ref(mapping, write_value, registration_value, readback_value),
        artifact_ref=_first_artifact_ref(mapping, write_value, registration_value),
    )


def _field(mapping: Mapping[str, Any], *names: str) -> tuple[bool, Any]:
    for name in names:
        if name in mapping:
            return True, mapping[name]
    return False, None


def _error_message(exc: Exception, fallback: str) -> str:
    detail = str(exc).strip()
    if not detail:
        return fallback
    return f"{fallback}: {detail[:240]}"


def _call_component(
    component: Any,
    *,
    operation: str,
    request: WriterRequest,
    writer_result: Mapping[str, Any] | None = None,
) -> Any:
    target = getattr(component, operation, None)
    if target is None and operation == "register":
        target = getattr(component, "registration", None)
    if target is None and operation == "readback":
        target = getattr(component, "verify", None)
    if target is None and callable(component):
        target = component
    if target is None or not callable(target):
        raise TypeError(f"injected {operation} adapter is not callable")

    values = {
        "request": request,
        "writer_request": request,
        "context": request.context,
        "trusted_context": request.context,
        "content": request.content,
        "body": request.content,
        "capability_id": request.capability_id,
        "capability": request.capability_id,
        "idempotency_key": request.idempotency_key,
        "idempotencyKey": request.idempotency_key,
        "binding": request.active_binding,
        "active_binding": request.active_binding,
        "activeBinding": request.active_binding,
        "context_receipt": request.context_receipt,
        "receipt": request.context_receipt,
        "writer_result": writer_result,
        "result": writer_result,
    }
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return target(request) if writer_result is None else target(request, writer_result)

    positional: list[Any] = []
    keyword: dict[str, Any] = {}
    has_var_keyword = False
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            has_var_keyword = True
            continue
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if parameter.name in values:
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                positional.append(values[parameter.name])
            else:
                keyword[parameter.name] = values[parameter.name]
            continue
        if parameter.default is inspect.Parameter.empty:
            if len(signature.parameters) == 1:
                return target(request)
            if writer_result is not None and len(signature.parameters) == 2:
                return target(request, writer_result)
            raise TypeError(f"injected {operation} adapter has unsupported parameter {parameter.name!r}")
    if has_var_keyword:
        keyword.update(values)
    return target(*positional, **keyword)


class WriterRouter:
    """The single server-side boundary for Phase-2 document-producing effects."""

    def __init__(
        self,
        personal_writer: WriterAdapter,
        organization_writer: WriterAdapter,
        *,
        capability_registry: Any | None = None,
        receipt_store: ReceiptStore | MutableMapping[str, Any] | None = None,
        artifact_registrar: ArtifactRegistrar | Callable[..., Any] | None = None,
        readback_verifier: ReadbackVerifier | Callable[..., Any] | None = None,
    ) -> None:
        if personal_writer is None or organization_writer is None:
            raise ValueError("both personal_writer and organization_writer are required")
        self.personal_writer = personal_writer
        self.organization_writer = organization_writer
        self.capability_registry = (
            capability_registry if capability_registry is not None else CapabilityEffectRegistry()
        )
        self.receipt_store = receipt_store if receipt_store is not None else InMemoryReceiptStore()
        self.artifact_registrar = artifact_registrar
        self.readback_verifier = readback_verifier
        self._lock = threading.RLock()

    def write(
        self,
        context: Any,
        content: Any,
        capability_id: str,
        idempotency_key: str,
        context_receipt: Any | None = None,
    ) -> dict[str, Any]:
        info = _context_info(context)
        normalized_capability_id = _required_text(capability_id, "capability_id", max_length=160)
        normalized_key = _required_text(idempotency_key, "idempotency_key")
        capability = _capability_info(self.capability_registry, normalized_capability_id)

        if capability.effect == "read":
            return self._no_op(info, normalized_capability_id, normalized_key, context_receipt)
        if info.route not in capability.allowed_routes and capability.allowed_routes:
            raise WriterRouterError(
                "authority_mismatch",
                "capability is not allowed to write to the trusted context authority",
            )

        storage_key = self._storage_key(info, normalized_key)
        fingerprint = self._request_fingerprint(info, normalized_capability_id, normalized_key, content)
        with self._lock:
            cached = self._read_record(storage_key)
            if cached is not None:
                if cached.request_fingerprint != fingerprint:
                    raise IdempotencyConflict()
                replay = copy.deepcopy(cached.response)
                replay["replayed"] = True
                return replay

            request = WriterRequest(
                context=info.context,
                content=content,
                capability_id=normalized_capability_id,
                idempotency_key=normalized_key,
                active_binding=info.binding,
                context_receipt=context_receipt,
                authority=info.authority,
                workspace=info.workspace,
            )
            response = self._execute(request, info, capability, storage_key)
            self._write_record(storage_key, fingerprint, response)
            return copy.deepcopy(response)

    route = write

    @staticmethod
    def _storage_key(info: _ContextInfo, idempotency_key: str) -> str:
        scope = {
            "authority": info.authority,
            "workspace": info.workspace,
            "tenant_scope": info.tenant_scope,
            "binding_identity": info.binding_identity,
        }
        digest = hashlib.sha256(_canonical_json(scope).encode("utf-8")).hexdigest()
        return f"stage2-writer:{digest}:{idempotency_key}"

    @staticmethod
    def _request_fingerprint(
        info: _ContextInfo,
        capability_id: str,
        idempotency_key: str,
        content: Any,
    ) -> str:
        payload = {
            "authority": info.authority,
            "workspace": info.workspace,
            "tenant_scope": info.tenant_scope,
            "binding_identity": info.binding_identity,
            "capability_id": capability_id,
            "idempotency_key": idempotency_key,
            "content": content,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _adapter_result(
        normalized: _NormalizedResult,
        registration: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": normalized.write["status"],
            "write": copy.deepcopy(normalized.write),
            "remote_ref": normalized.remote_ref,
            "artifact_ref": normalized.artifact_ref,
        }
        if registration is not None:
            payload["registration"] = copy.deepcopy(dict(registration))
        return payload

    def _execute(
        self,
        request: WriterRequest,
        info: _ContextInfo,
        capability: _CapabilityInfo,
        storage_key: str,
    ) -> dict[str, Any]:
        writer = self.personal_writer if info.route == PERSONAL_ROUTE else self.organization_writer
        try:
            raw_result = _call_component(writer, operation="write", request=request)
            normalized = _normalize_writer_result(
                raw_result,
                requires_readback=capability.requires_readback,
            )
        except WriterRouterError as exc:
            return self._needs_attention(
                info,
                request,
                storage_key,
                exc.code,
                exc.message,
            )
        except Exception as exc:
            return self._needs_attention(
                info,
                request,
                storage_key,
                "writer_failed",
                _error_message(exc, "writer call failed"),
            )

        if normalized.write["status"] != "succeeded":
            code = "writer_failed" if normalized.write["status"] == "failed" else "writer_result_invalid"
            return self._needs_attention(
                info,
                request,
                storage_key,
                code,
                "writer did not complete successfully",
                normalized=normalized,
            )

        if info.route == PERSONAL_ROUTE and normalized.remote_ref is not None:
            return self._needs_attention(
                info,
                request,
                storage_key,
                "personal_remote_ref_forbidden",
                "personal_web/internal results cannot contain a remote_ref",
                normalized=normalized,
            )
        if info.route == ORGANIZATION_ROUTE and normalized.remote_ref is None:
            return self._needs_attention(
                info,
                request,
                storage_key,
                "organization_remote_ref_missing",
                "organization_lark/lark results require a remote_ref",
                normalized=normalized,
            )

        registration = normalized.registration
        if self.artifact_registrar is not None:
            try:
                registration = _stage(
                    _call_component(
                        self.artifact_registrar,
                        operation="register",
                        request=request,
                        writer_result=self._adapter_result(normalized),
                    ),
                    stage="registration",
                )
            except Exception as exc:
                return self._needs_attention(
                    info,
                    request,
                    storage_key,
                    "registration_failed",
                    _error_message(exc, "artifact registration failed"),
                    normalized=normalized,
                    registration=registration,
                )
        if registration is None:
            return self._needs_attention(
                info,
                request,
                storage_key,
                "registration_incomplete",
                "artifact registration result is missing",
                normalized=normalized,
            )
        if registration["status"] != "succeeded":
            return self._needs_attention(
                info,
                request,
                storage_key,
                "registration_failed",
                "artifact registration did not complete successfully",
                normalized=normalized,
                registration=registration,
            )

        readback = normalized.readback
        if self.readback_verifier is not None:
            try:
                readback = _stage(
                    _call_component(
                        self.readback_verifier,
                        operation="readback",
                        request=request,
                        writer_result=self._adapter_result(normalized, registration),
                    ),
                    stage="readback",
                )
            except Exception as exc:
                return self._needs_attention(
                    info,
                    request,
                    storage_key,
                    "readback_failed",
                    _error_message(exc, "artifact readback failed"),
                    normalized=normalized,
                    registration=registration,
                    readback=readback,
                )
        if capability.requires_readback and readback is None:
            return self._needs_attention(
                info,
                request,
                storage_key,
                "readback_incomplete",
                "artifact readback result is missing",
                normalized=normalized,
                registration=registration,
            )
        if capability.requires_readback and readback is not None and readback["status"] != "succeeded":
            return self._needs_attention(
                info,
                request,
                storage_key,
                "readback_failed",
                "artifact readback did not verify the written result",
                normalized=normalized,
                registration=registration,
                readback=readback,
            )

        return self._response(
            info,
            request,
            storage_key,
            status="succeeded",
            writer_called=True,
            remote_ref=normalized.remote_ref,
            artifact_ref=normalized.artifact_ref
            or (registration or {}).get("artifact_ref"),
            write=normalized.write,
            registration=registration,
            readback=readback,
            error=None,
        )

    @staticmethod
    def _response(
        info: _ContextInfo,
        request: WriterRequest,
        storage_key: str | None,
        *,
        status: str,
        writer_called: bool,
        remote_ref: str | None = None,
        artifact_ref: str | None = None,
        write: Mapping[str, Any] | None = None,
        registration: Mapping[str, Any] | None = None,
        readback: Mapping[str, Any] | None = None,
        error: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "state": status,
            "published": False,
            "publish_success": False,
            "needs_attention": status == "needs_attention",
            "replayed": False,
            "writer_called": writer_called,
            "capability_id": request.capability_id,
            "authority": info.authority,
            "workspace": info.workspace,
            "idempotency_key": request.idempotency_key,
            "receipt_storage_key": storage_key,
            "context_receipt_present": request.context_receipt is not None,
            "remote_ref": remote_ref,
            "artifact_ref": artifact_ref,
            "write": copy.deepcopy(dict(write)) if write is not None else None,
            "registration": copy.deepcopy(dict(registration)) if registration is not None else None,
            "readback": copy.deepcopy(dict(readback)) if readback is not None else None,
            "error": copy.deepcopy(dict(error)) if error is not None else None,
        }

    def _needs_attention(
        self,
        info: _ContextInfo,
        request: WriterRequest,
        storage_key: str,
        code: str,
        message: str,
        *,
        normalized: _NormalizedResult | None = None,
        registration: Mapping[str, Any] | None = None,
        readback: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if normalized is not None:
            write = normalized.write
            if registration is None:
                registration = normalized.registration
            if readback is None:
                readback = normalized.readback
            remote_ref = normalized.remote_ref
            artifact_ref = normalized.artifact_ref
        else:
            write = None
            remote_ref = None
            artifact_ref = None
        return self._response(
            info,
            request,
            storage_key,
            status="needs_attention",
            writer_called=True,
            remote_ref=remote_ref,
            artifact_ref=artifact_ref,
            write=write,
            registration=registration,
            readback=readback,
            error={"code": code, "message": message},
        )

    @staticmethod
    def _no_op(
        info: _ContextInfo,
        capability_id: str,
        idempotency_key: str,
        context_receipt: Any | None,
    ) -> dict[str, Any]:
        request = WriterRequest(
            context=info.context,
            content=None,
            capability_id=capability_id,
            idempotency_key=idempotency_key,
            active_binding=info.binding,
            context_receipt=context_receipt,
            authority=info.authority,
            workspace=info.workspace,
        )
        return WriterRouter._response(
            info,
            request,
            None,
            status="no_op",
            writer_called=False,
            error={"code": "read_only_capability", "message": "read-only capability has no writer effect"},
        )

    def _read_record(self, key: str) -> ReceiptRecord | None:
        if isinstance(self.receipt_store, MutableMapping):
            record = self.receipt_store.get(key)
        else:
            record = self.receipt_store.get(key)
        if record is None:
            return None
        if isinstance(record, ReceiptRecord):
            return copy.deepcopy(record)
        if isinstance(record, Mapping):
            fingerprint = _lookup(
                record,
                "request_fingerprint",
                "requestFingerprint",
                "fingerprint",
                default=_MISSING,
            )
            response = _lookup(record, "response", default=_MISSING)
            if isinstance(fingerprint, str) and isinstance(response, Mapping):
                return ReceiptRecord(fingerprint, copy.deepcopy(dict(response)))
        raise WriterRouterError("receipt_store_invalid", "receipt store returned an invalid record")

    def _write_record(self, key: str, fingerprint: str, response: Mapping[str, Any]) -> None:
        if isinstance(self.receipt_store, MutableMapping):
            existing = self.receipt_store.get(key)
            if existing is not None:
                cached = self._read_record(key)
                if cached is not None and cached.request_fingerprint != fingerprint:
                    raise IdempotencyConflict()
                return
            self.receipt_store[key] = ReceiptRecord(fingerprint, copy.deepcopy(dict(response)))
            return
        self.receipt_store.put(key, fingerprint, response)


__all__ = [
    "AIExecutionContext",
    "ArtifactRegistrar",
    "Binding",
    "CapabilityEffectRegistry",
    "CapabilitySpec",
    "IdempotencyConflict",
    "InMemoryReceiptStore",
    "ReadbackVerifier",
    "ReceiptRecord",
    "ReceiptStore",
    "SCHEMA_VERSION",
    "TrustedAIContext",
    "WriterAdapter",
    "WriterRequest",
    "WriterRouter",
    "WriterRouterError",
]
