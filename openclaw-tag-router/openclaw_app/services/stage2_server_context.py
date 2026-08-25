"""Server-owned Stage-2 authentication, Binding, and tenant readers.

The Stage-2 gateway must receive facts that were resolved by the server, not
claims copied from an operation body.  This module keeps the resolution
boundary dependency-injected so the production transport can provide its
session store and the tests can provide isolated fixtures.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Protocol

from .stage2_context import (
    ContextSourceRow,
    OrganizationBinding,
    ServerSessionFacts,
    Stage2ContextError,
)
from .stage2_gateway import OrganizationServerContext


class Stage2ServerContextError(RuntimeError):
    """A fail-closed error raised while resolving server facts."""

    def __init__(self, code: str, message: str, *, status: int = 401) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class SessionRecordLoader(Protocol):
    def __call__(self, session_token: str) -> Mapping[str, Any] | None: ...


class BindingRecordLoader(Protocol):
    def __call__(self, tenant_id: str) -> Mapping[str, Any] | None: ...


class TenantProfileLoader(Protocol):
    def __call__(self, tenant_id: str, tenant_type: str) -> Mapping[str, Any] | None: ...


class TenantSourceLoader(Protocol):
    def __call__(
        self,
        tenant_id: str,
        workspace_mode: str,
        source_kinds: tuple[str, ...],
    ) -> Any: ...


_REQUEST_CONTEXT: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "stage2_request_context",
    default=None,
)


def _value(record: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return default


def _required_text(value: Any, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise Stage2ServerContextError("server_record_invalid", f"{label} is missing", status=503)
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise Stage2ServerContextError("server_record_invalid", f"{label} is invalid", status=503)
    return normalized


def _session_token(value: Any) -> str:
    if not isinstance(value, str):
        raise Stage2ServerContextError("authentication_invalid", "session credential is invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > 4096 or any(ord(char) < 32 for char in normalized):
        raise Stage2ServerContextError("authentication_invalid", "session credential is invalid")
    return normalized


def _parse_expiry(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise Stage2ServerContextError("server_record_invalid", "session expiry is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Stage2ServerContextError("server_record_invalid", "session expiry is invalid") from exc
    return parsed


def extract_session_token(request: Mapping[str, Any]) -> str | None:
    """Extract only the transport credential from an injected request view.

    The operation JSON is intentionally not accepted here.  A transport may
    expose an ``Authorization`` header or a named session cookie, but the
    resulting opaque value is still resolved through ``SessionRecordLoader``.
    """

    if not isinstance(request, Mapping):
        raise Stage2ServerContextError("request_context_invalid", "request context must be an object")
    headers = _value(request, "headers", default={})
    cookies = _value(request, "cookies", default={})
    if headers is None:
        headers = {}
    if cookies is None:
        cookies = {}
    if not isinstance(headers, Mapping) or not isinstance(cookies, Mapping):
        raise Stage2ServerContextError("request_context_invalid", "request headers and cookies must be objects")

    authorization = _value(headers, "Authorization", "authorization")
    if authorization is not None:
        if not isinstance(authorization, str):
            raise Stage2ServerContextError("authentication_invalid", "authorization header is invalid")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer":
            raise Stage2ServerContextError("authentication_invalid", "Bearer authorization is required")
        return _session_token(token)
    cookie = _value(cookies, "openclaw_session")
    if cookie is not None:
        return _session_token(cookie)
    return None


@contextmanager
def stage2_request_context(request: Mapping[str, Any]):
    """Bind one transport-owned request view to the current execution context."""

    if not isinstance(request, Mapping):
        raise Stage2ServerContextError("request_context_invalid", "request context must be an object")
    headers = _value(request, "headers", default={})
    cookies = _value(request, "cookies", default={})
    if not isinstance(headers, Mapping) or not isinstance(cookies, Mapping):
        raise Stage2ServerContextError(
            "request_context_invalid",
            "request headers and cookies must be objects",
        )
    frozen = MappingProxyType(
        {
            "headers": MappingProxyType(dict(headers)),
            "cookies": MappingProxyType(dict(cookies)),
        }
    )
    token = _REQUEST_CONTEXT.set(frozen)
    try:
        yield
    finally:
        _REQUEST_CONTEXT.reset(token)


def current_request_session_token() -> str | None:
    """Return the opaque credential for the active HTTP request, if any."""

    request = _REQUEST_CONTEXT.get()
    if request is None:
        return None
    return extract_session_token(request)


class AuthenticatedSessionProvider:
    """Resolve an opaque request credential into ``ServerSessionFacts``."""

    def __init__(
        self,
        session_loader: SessionRecordLoader,
        token_provider: Callable[[], str | None] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(session_loader) or (
            token_provider is not None and not callable(token_provider)
        ):
            raise TypeError("session loader and token provider must be callable")
        self._session_loader = session_loader
        self._token_provider = token_provider or current_request_session_token
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def resolve(self) -> ServerSessionFacts:
        try:
            token = self._token_provider()
        except Stage2ServerContextError:
            raise
        except Exception as exc:
            raise Stage2ServerContextError("session_unavailable", "authenticated session is unavailable", status=503) from exc
        if token is None:
            raise Stage2ServerContextError("authentication_required", "an authenticated session is required")
        token = _session_token(token)
        try:
            record = self._session_loader(token)
        except Exception as exc:
            raise Stage2ServerContextError("session_unavailable", "authenticated session is unavailable", status=503) from exc
        if not isinstance(record, Mapping):
            raise Stage2ServerContextError("authentication_required", "authenticated session was not found")
        try:
            session = ServerSessionFacts(
                session_id=_value(record, "session_id", "sessionId", "id"),
                user_id=_value(record, "user_id", "userId", "actor_id", "actorId"),
                tenant_id=_value(record, "tenant_id", "tenantId"),
                tenant_type=_value(record, "tenant_type", "tenantType"),
                session_status=_value(record, "session_status", "sessionStatus", "status", default="active"),
                member_status=_value(record, "member_status", "memberStatus", default="active"),
                member_tenant_id=_value(record, "member_tenant_id", "memberTenantId", default=None),
                member_role=_value(record, "member_role", "memberRole", "role", default="member"),
                binding_generation=_value(record, "binding_generation", "bindingGeneration", default=None),
                tenant_status=_value(record, "tenant_status", "tenantStatus", default="active"),
                expires_at=_parse_expiry(_value(record, "expires_at", "expiresAt", default=None)),
            )
            session.assert_active(now=self._clock())
        except Stage2ContextError as exc:
            raise Stage2ServerContextError("session_invalid", str(exc)) from exc
        except Stage2ServerContextError:
            raise
        except Exception as exc:
            raise Stage2ServerContextError("session_invalid", "authenticated session is invalid") from exc
        return session

    __call__ = resolve


@dataclass(frozen=True, slots=True)
class ResolvedBinding:
    """A non-secret active Binding plus server-owned open metadata."""

    identity: OrganizationBinding
    credential_generation: str
    trusted_open_url: str


class CurrentBindingProvider:
    """Resolve the active Binding for the session's tenant."""

    def __init__(self, binding_loader: BindingRecordLoader) -> None:
        if not callable(binding_loader):
            raise TypeError("binding loader must be callable")
        self._binding_loader = binding_loader

    def resolve(self, session: ServerSessionFacts) -> ResolvedBinding:
        if not isinstance(session, ServerSessionFacts):
            raise Stage2ServerContextError("session_invalid", "server session facts are required")
        if session.tenant_type != "organization":
            raise Stage2ServerContextError("organization_context_required", "an organization session is required", status=403)
        try:
            record = self._binding_loader(session.tenant_id)
        except Exception as exc:
            raise Stage2ServerContextError("binding_unavailable", "current organization Binding is unavailable", status=503) from exc
        if not isinstance(record, Mapping):
            raise Stage2ServerContextError("binding_required", "current organization Binding was not found", status=403)
        try:
            identity = OrganizationBinding(
                binding_id=_value(record, "binding_id", "bindingId", "id"),
                tenant_id=_value(record, "tenant_id", "tenantId"),
                generation=_value(record, "generation", "binding_generation", "bindingGeneration"),
                status=_value(record, "status", "binding_status", "bindingStatus", default="active"),
            )
            identity.assert_matches(session)
            credential_generation = _required_text(
                _value(record, "credential_generation", "credentialGeneration"),
                "credential generation",
                maximum=160,
            )
            trusted_open_url = _required_text(
                _value(record, "trusted_open_url", "trustedOpenUrl"),
                "trusted open URL",
                maximum=2048,
            )
            if not trusted_open_url.startswith("https://") or any(char.isspace() for char in trusted_open_url):
                raise Stage2ServerContextError(
                    "binding_invalid",
                    "trusted open URL must use HTTPS",
                    status=503,
                )
        except Stage2ContextError as exc:
            raise Stage2ServerContextError("binding_invalid", str(exc), status=403) from exc
        return ResolvedBinding(identity, credential_generation, trusted_open_url)

    __call__ = resolve


@dataclass(frozen=True, slots=True)
class TenantProfile:
    tenant_id: str
    tenant_type: str
    revision: str
    fields: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.fields, Mapping):
            raise Stage2ServerContextError("tenant_profile_invalid", "tenant profile fields must be an object", status=503)
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))


class TenantProfileReader:
    """Read a tenant profile through an injected, server-side repository."""

    def __init__(self, profile_loader: TenantProfileLoader) -> None:
        if not callable(profile_loader):
            raise TypeError("profile loader must be callable")
        self._profile_loader = profile_loader

    def read(self, session: ServerSessionFacts) -> TenantProfile:
        if not isinstance(session, ServerSessionFacts):
            raise Stage2ServerContextError("session_invalid", "server session facts are required")
        try:
            record = self._profile_loader(session.tenant_id, session.tenant_type)
        except Exception as exc:
            raise Stage2ServerContextError("tenant_profile_unavailable", "tenant profile is unavailable", status=503) from exc
        if not isinstance(record, Mapping):
            raise Stage2ServerContextError("tenant_profile_missing", "tenant profile was not found", status=403)
        tenant_id = _value(record, "tenant_id", "tenantId")
        tenant_type = _value(record, "tenant_type", "tenantType")
        if tenant_id != session.tenant_id or tenant_type != session.tenant_type:
            raise Stage2ServerContextError("tenant_profile_mismatch", "tenant profile does not match the session", status=403)
        fields = _value(record, "fields", "data", "profile", default={})
        if not isinstance(fields, Mapping):
            raise Stage2ServerContextError("tenant_profile_invalid", "tenant profile fields must be an object", status=503)
        return TenantProfile(
            tenant_id=session.tenant_id,
            tenant_type=session.tenant_type,
            revision=_required_text(_value(record, "revision", "profile_revision", default="1"), "profile revision", maximum=160),
            fields=fields,
        )

    __call__ = read


class TenantSourceReader:
    """Tenant-scoped source reader compatible with ``ContextBuilder``."""

    def __init__(self, source_loader: TenantSourceLoader) -> None:
        if not callable(source_loader):
            raise TypeError("source loader must be callable")
        self._source_loader = source_loader

    def list_sources(
        self,
        *,
        tenant_id: str,
        workspace_mode: str,
        source_kinds: tuple[str, ...],
    ) -> tuple[Mapping[str, Any], ...]:
        try:
            rows = self._source_loader(tenant_id, workspace_mode, tuple(source_kinds))
        except Exception as exc:
            raise Stage2ServerContextError("source_unavailable", "tenant sources are unavailable", status=503) from exc
        if rows is None:
            return ()
        if isinstance(rows, (str, bytes, Mapping)):
            raise Stage2ServerContextError("source_reader_invalid", "tenant source reader must return rows", status=503)
        normalized: list[Mapping[str, Any]] = []
        for raw in rows:
            try:
                row = ContextSourceRow.from_record(raw)
            except Exception as exc:
                raise Stage2ServerContextError("source_invalid", "tenant source row is invalid", status=503) from exc
            if row.tenant_id != tenant_id or row.workspace_mode != workspace_mode:
                raise Stage2ServerContextError("source_tenant_mismatch", "source row escaped the tenant scope", status=403)
            if row.source_kind not in source_kinds:
                raise Stage2ServerContextError("source_kind_mismatch", "source reader returned an unauthorized source kind", status=403)
            normalized.append(row.as_dict())
        normalized.sort(key=lambda item: (str(item["sourceKind"]), str(item["sourceId"])))
        return tuple(normalized)


class ServerStage2ContextProviders:
    """Compose the providers used by the HTTP gateway."""

    def __init__(
        self,
        session_provider: AuthenticatedSessionProvider,
        binding_provider: CurrentBindingProvider,
        profile_reader: TenantProfileReader,
    ) -> None:
        self.session_provider = session_provider
        self.binding_provider = binding_provider
        self.profile_reader = profile_reader

    def personal_session(self) -> ServerSessionFacts:
        session = self.session_provider.resolve()
        if session.tenant_type != "personal":
            raise Stage2ServerContextError("personal_context_required", "a personal session is required", status=403)
        self.profile_reader.read(session)
        return session

    def organization_context(self) -> OrganizationServerContext:
        session = self.session_provider.resolve()
        if session.tenant_type != "organization":
            raise Stage2ServerContextError("organization_context_required", "an organization session is required", status=403)
        self.profile_reader.read(session)
        binding = self.binding_provider.resolve(session)
        return OrganizationServerContext(
            session=session,
            binding=binding.identity,
            credential_generation=binding.credential_generation,
            trusted_open_url=binding.trusted_open_url,
        )


__all__ = [
    "AuthenticatedSessionProvider",
    "CurrentBindingProvider",
    "ResolvedBinding",
    "ServerStage2ContextProviders",
    "Stage2ServerContextError",
    "TenantProfile",
    "TenantProfileReader",
    "TenantSourceReader",
    "current_request_session_token",
    "extract_session_token",
    "stage2_request_context",
]
