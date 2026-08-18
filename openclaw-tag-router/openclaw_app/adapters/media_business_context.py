from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal, Mapping, Union
from uuid import UUID


Permission = Literal[
    "ordinary-session",
    "shared-session",
    "admin-session",
    "admin-cross-tenant-read",
    "admin-maintainer",
]
FrozenJson = Union[None, bool, int, float, str, tuple["FrozenJson", ...], Mapping[str, "FrozenJson"]]


class RequestContextError(ValueError):
    pass


class RequestAuthenticationError(RequestContextError):
    pass


class RequestAuthorizationError(RequestContextError):
    pass


def freeze_json(value: Any) -> FrozenJson:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, FrozenJson] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RequestContextError("JSON object keys must be strings")
            frozen[key] = freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise RequestContextError(f"unsupported JSON value type: {type(value).__name__}")


@dataclass(frozen=True)
class If2Route:
    operation_id: str
    method: Literal["GET", "POST", "PUT"]
    route_template: str
    permission: Permission
    mutation: bool
    body_limit_bytes: int | None
    request_schema: str | None
    allowed_statuses: frozenset[int]

    def __post_init__(self) -> None:
        if not self.operation_id or not self.route_template.startswith("/"):
            raise RequestContextError("IF2 route identity is invalid")
        if self.mutation != (self.method != "GET"):
            raise RequestContextError("IF2 mutation flag must match the HTTP method")
        if self.body_limit_bytes is not None and self.body_limit_bytes < 1:
            raise RequestContextError("IF2 body limit must be positive")
        if not self.allowed_statuses:
            raise RequestContextError("IF2 route must declare response statuses")


@dataclass(frozen=True)
class SessionPrincipal:
    session_id: UUID
    user_id: UUID
    tenant_id: UUID
    user_public_id: str
    role: Literal["user", "admin"]
    is_maintainer: bool
    expires_at: datetime
    session_token_hash: bytes

    def __post_init__(self) -> None:
        if not self.user_public_id:
            raise RequestContextError("session principal requires a public user ID")
        if len(self.session_token_hash) != 32:
            raise RequestContextError("session token identity must be SHA-256")
        if self.is_maintainer and self.role != "admin":
            raise RequestContextError("only an admin can hold maintainer authority")

    @property
    def actor_user_id(self) -> UUID:
        return self.user_id

    @property
    def actor_session_id(self) -> UUID:
        return self.session_id

    @property
    def maintainer(self) -> bool:
        return self.is_maintainer


@dataclass(frozen=True)
class ExternalRequestAuthority:
    peer_ip: str
    client_ip: str
    scheme: Literal["http", "https"]
    host: str
    port: int
    trusted_proxy: bool

    def __post_init__(self) -> None:
        if not self.peer_ip or not self.client_ip or not self.host:
            raise RequestContextError("external request authority is incomplete")
        if self.port < 1 or self.port > 65535:
            raise RequestContextError("external request port is invalid")


@dataclass(frozen=True)
class CsrfAssessment:
    required: bool
    origin: tuple[str, str, int] | None
    same_origin: bool
    token_valid: bool
    response_token: str

    def __post_init__(self) -> None:
        if self.required and (self.origin is None or not self.same_origin or not self.token_valid):
            raise RequestAuthorizationError("required CSRF assessment did not pass")
        if not self.response_token:
            raise RequestContextError("CSRF response token is required")


@dataclass(frozen=True)
class IdempotencyInput:
    key: str
    scope_kind: Literal["tenant", "admin_actor"]
    scope_id: UUID
    path_fingerprint: bytes
    request_fingerprint: bytes

    def __post_init__(self) -> None:
        if len(self.key) < 8 or len(self.key) > 128:
            raise RequestContextError("idempotency key length is invalid")
        if any(not (character.isascii() and (character.isalnum() or character in "_-")) for character in self.key):
            raise RequestContextError("idempotency key syntax is invalid")
        if len(self.path_fingerprint) != 32 or len(self.request_fingerprint) != 32:
            raise RequestContextError("idempotency fingerprints must be SHA-256")


@dataclass(frozen=True)
class AdminAuditInput:
    reason: str
    target_public_tenant_id: str
    target_tenant_id: UUID | None

    def __post_init__(self) -> None:
        if len(self.reason) < 8 or len(self.reason.encode("utf-8")) > 1024:
            raise RequestContextError("admin audit reason is invalid")
        if not self.target_public_tenant_id:
            raise RequestContextError("admin audit target is required")


@dataclass(frozen=True)
class If2RequestContext:
    request_id: UUID
    received_at: datetime
    route: If2Route
    canonical_path: str
    path_parameters: tuple[tuple[str, str], ...]
    query_parameters: tuple[tuple[str, tuple[str, ...]], ...]
    headers: tuple[tuple[str, str], ...]
    authority: ExternalRequestAuthority
    principal: SessionPrincipal
    csrf: CsrfAssessment
    idempotency: IdempotencyInput | None
    expected_revision: int | None
    body: FrozenJson | None
    admin_audit: AdminAuditInput | None

    def __post_init__(self) -> None:
        if not self.canonical_path.startswith("/openclaw/media/api/"):
            raise RequestContextError("request context path is not canonical IF2")
        if self.route.permission == "ordinary-session" and self.principal.role != "user":
            raise RequestAuthorizationError("ordinary route requires an ordinary-user principal")
        if self.route.permission.startswith("admin-") and self.principal.role != "admin":
            raise RequestAuthorizationError("admin route requires an admin principal")
        if self.route.permission == "admin-maintainer" and not self.principal.is_maintainer:
            raise RequestAuthorizationError("maintainer route requires explicit maintainer authority")
        if self.route.mutation != (self.idempotency is not None):
            raise RequestContextError("mutation context must carry exactly one idempotency input")
        if self.route.permission == "admin-cross-tenant-read" and self.admin_audit is None:
            raise RequestContextError("cross-tenant read requires immutable audit input")
        if self.route.permission != "admin-cross-tenant-read" and self.admin_audit is not None:
            raise RequestContextError("audit target input is only valid for cross-tenant reads")
        if self.expected_revision is not None and self.expected_revision < 1:
            raise RequestContextError("expected revision must be positive")

    @classmethod
    def build(cls, *, body: Any = None, **values: Any) -> "If2RequestContext":
        return cls(body=freeze_json(body), **values)
