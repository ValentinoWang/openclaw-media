"""Server-owned HTTP composition boundary for Stage-2 operations.

The gateway accepts operation data from a transport only. Session, Binding,
credential generation, and trusted document URLs are resolved by injected
server providers and never taken from browser payloads.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .stage2_context import OrganizationBinding, ServerSessionFacts
from .stage2_external_document import BindingIdentity
from .stage2_runtime import Stage2Runtime, Stage2RuntimeError


class Stage2GatewayError(ValueError):
    """Stable transport-level error for fail-closed request composition."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class OrganizationServerContext:
    """All organization authority facts resolved by the server."""

    session: ServerSessionFacts
    binding: OrganizationBinding | BindingIdentity
    credential_generation: str
    trusted_open_url: str


_FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {
        "authority", "authority_mode", "authorityMode", "binding", "binding_id", "bindingId",
        "binding_generation", "bindingGeneration", "capability", "capability_id", "capabilityId",
        "container_id", "containerId", "credential", "credentials", "credential_generation",
        "credentialGeneration", "lark_app_id", "larkAppId", "lark_space_id", "larkSpaceId",
        "organization_id", "organizationId", "parent_node_id", "parentNodeId", "role", "route", "session",
        "tenant", "tenant_id", "tenantId", "tenant_type", "tenantType", "trusted_open_url",
        "trustedOpenUrl", "workspace", "workspace_mode", "workspaceMode",
    }
)
_PERSONAL_FIELDS = frozenset(
    {
        "operation_id", "operationId", "idempotency_key", "idempotencyKey", "title", "topic", "target",
        "confirmed_by", "confirmedBy", "confirmation_ref", "confirmationRef", "sources", "source_rows",
        "sourceRows", "body", "tradeoffs", "risks", "platform_constraints", "platformConstraints",
    }
)
_ORGANIZATION_FIELDS = frozenset(
    {"operation_id", "operationId", "idempotency_key", "idempotencyKey", "title", "sources", "source_rows", "sourceRows", "body"}
)


def _require_mapping(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage2GatewayError("invalid_request", "JSON request body must be an object")
    return payload


def _reject_authority_fields(payload: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        code = "authority_override" if any(key in _FORBIDDEN_AUTHORITY_FIELDS for key in unknown) else "invalid_request"
        raise Stage2GatewayError(code, "request contains server-owned or unsupported fields")


def _pick(payload: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return default


def _server_context_error(exc: Exception, label: str) -> Stage2GatewayError:
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    message = getattr(exc, "message", None)
    if (
        isinstance(code, str)
        and bool(code.strip())
        and isinstance(status, int)
        and 400 <= status <= 599
        and isinstance(message, str)
        and bool(message.strip())
    ):
        return Stage2GatewayError(code, message, status=status)
    return Stage2GatewayError(
        "server_context_unavailable",
        f"{label} server context is unavailable",
        status=503,
    )


class Stage2Gateway:
    """Compose transport data with server-owned Stage-2 authority facts."""

    def __init__(
        self,
        runtime: Stage2Runtime,
        *,
        capability_id: str,
        personal_session_provider: Callable[[], ServerSessionFacts],
        organization_context_provider: Callable[[], OrganizationServerContext],
        allow_transport_sources: bool = False,
    ) -> None:
        if not isinstance(runtime, Stage2Runtime):
            raise TypeError("runtime must be a Stage2Runtime")
        if not capability_id or not callable(personal_session_provider) or not callable(organization_context_provider):
            raise ValueError("Stage-2 gateway requires server-owned providers")
        if not isinstance(allow_transport_sources, bool):
            raise TypeError("allow_transport_sources must be a boolean")
        self.runtime = runtime
        self.capability_id = capability_id
        self.personal_session_provider = personal_session_provider
        self.organization_context_provider = organization_context_provider
        self.allow_transport_sources = allow_transport_sources

    def _reject_transport_sources(self, request: Mapping[str, Any]) -> None:
        if not self.allow_transport_sources and any(
            field in request for field in ("sources", "source_rows", "sourceRows")
        ):
            raise Stage2GatewayError(
                "authority_override",
                "request cannot provide server-owned source rows",
            )

    def run_personal(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        request = _require_mapping(payload)
        _reject_authority_fields(request, _PERSONAL_FIELDS)
        self._reject_transport_sources(request)
        try:
            session = self.personal_session_provider()
        except Exception as exc:
            raise _server_context_error(exc, "personal") from exc
        if not isinstance(session, ServerSessionFacts):
            raise Stage2GatewayError("server_context_invalid", "personal server context is invalid", status=503)
        args = {
            "session": session, "capability_id": self.capability_id,
            "operation_id": _pick(request, "operation_id", "operationId"),
            "idempotency_key": _pick(request, "idempotency_key", "idempotencyKey"),
            "title": _pick(request, "title"), "topic": _pick(request, "topic"), "target": _pick(request, "target"),
            "confirmed_by": _pick(request, "confirmed_by", "confirmedBy"),
            "confirmation_ref": _pick(request, "confirmation_ref", "confirmationRef"),
            "sources": _pick(request, "sources"), "source_rows": _pick(request, "source_rows", "sourceRows"),
            "body": _pick(request, "body"), "tradeoffs": _pick(request, "tradeoffs", default=()),
            "risks": _pick(request, "risks", default=()),
            "platform_constraints": _pick(request, "platform_constraints", "platformConstraints", default={}),
        }
        return self._run(self.runtime.run_personal, args)

    def run_organization(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        request = _require_mapping(payload)
        _reject_authority_fields(request, _ORGANIZATION_FIELDS)
        self._reject_transport_sources(request)
        try:
            context = self.organization_context_provider()
        except Exception as exc:
            raise _server_context_error(exc, "organization") from exc
        if not isinstance(context, OrganizationServerContext):
            raise Stage2GatewayError("server_context_invalid", "organization server context is invalid", status=503)
        args = {
            "session": context.session, "binding": context.binding, "capability_id": self.capability_id,
            "operation_id": _pick(request, "operation_id", "operationId"),
            "idempotency_key": _pick(request, "idempotency_key", "idempotencyKey"),
            "title": _pick(request, "title"), "sources": _pick(request, "sources"),
            "source_rows": _pick(request, "source_rows", "sourceRows"), "body": _pick(request, "body"),
            "credential_generation": context.credential_generation, "trusted_open_url": context.trusted_open_url,
        }
        return self._run(self.runtime.run_organization, args)

    def run(self, mode: str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        if mode == "personal":
            return self.run_personal(payload)
        if mode == "organization":
            return self.run_organization(payload)
        raise Stage2GatewayError("route_mismatch", "unsupported Stage-2 operation route")

    @staticmethod
    def _run(operation: Callable[..., dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
        try:
            return operation(**args)
        except Stage2RuntimeError:
            raise
        except Exception as exc:
            raise Stage2GatewayError("stage2_runtime_failed", "Stage-2 operation failed", status=500) from exc


__all__ = ["OrganizationServerContext", "Stage2Gateway", "Stage2GatewayError"]
