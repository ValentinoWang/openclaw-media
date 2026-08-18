from __future__ import annotations

import copy
import hashlib
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, ContextManager, Iterator, Literal, Mapping, NoReturn, Protocol, Sequence
from uuid import UUID, uuid4

from .errors import AccountAuthError, AccountContractError


IdentityLinkIntentStatus = Literal["active", "consumed", "revoked", "expired"]
IdentityLinkStatus = Literal["active", "revoked"]
IdentityLinkAuditAction = Literal["linked", "unlinked", "intent_revoked"]

IDENTITY_LINK_TTL_SECONDS = 10 * 60
IDENTITY_LINK_TOKEN_BYTES = 32


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return an aware datetime")
    return value.astimezone(timezone.utc)


def _token_digest(token: str) -> bytes:
    if not isinstance(token, str):
        return b""
    try:
        raw = token.encode("ascii")
    except UnicodeEncodeError:
        return b""
    if not 40 <= len(token) <= 256:
        return b""
    return hashlib.sha256(raw).digest()


def _new_token() -> str:
    return secrets.token_urlsafe(IDENTITY_LINK_TOKEN_BYTES)


def _invalid_request(code: str, detail: str, *, status: int = 400) -> NoReturn:
    raise AccountAuthError(code, detail, status=status)


def _require_user_id(user_id: UUID | None) -> UUID:
    if not isinstance(user_id, UUID):
        _invalid_request("authentication_required", "需要有效的平台登录会话。", status=401)
    return user_id


def _require_tenant_id(tenant_id: UUID | None) -> UUID:
    if not isinstance(tenant_id, UUID):
        _invalid_request("identity_link_tenant_invalid", "组织工作区无效。")
    return tenant_id


def _normalize_identity_value(value: object, code: str = "identity_link_identity_invalid") -> str:
    if not isinstance(value, str):
        _invalid_request(code, "飞书稳定身份无效。")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 512 or any(ord(character) < 32 for character in normalized):
        _invalid_request(code, "飞书稳定身份无效。")
    return normalized


def _normalize_reason(reason: str) -> str:
    if not isinstance(reason, str):
        _invalid_request("identity_link_invalid_request", "操作原因无效。")
    normalized = reason.strip()
    if not normalized or len(normalized) > 500:
        _invalid_request("identity_link_invalid_request", "操作原因无效。")
    return normalized


@dataclass(frozen=True)
class FeishuOAuthResult:
    """Untrusted broker output; only a verified stable pair may be consumed."""

    status: str
    tenant_key: str | None = None
    open_id: str | None = None
    email: str | None = None
    display_name: str | None = None

    @classmethod
    def verified(
        cls,
        tenant_key: str,
        open_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
    ) -> "FeishuOAuthResult":
        return cls("VERIFIED", tenant_key, open_id, email, display_name)


@dataclass(frozen=True)
class VerifiedFeishuOAuthResult:
    """Explicitly verified broker output used by the link completion boundary."""

    tenant_key: str
    open_id: str
    email: str | None = None
    display_name: str | None = None

    @property
    def status(self) -> str:
        return "VERIFIED"


@dataclass(frozen=True)
class IdentityLinkTenant:
    tenant_id: UUID
    status: str
    tenant_type: str
    workspace_mode: str
    body_authority: str


@dataclass(frozen=True)
class IdentityLinkBinding:
    tenant_id: UUID
    tenant_key: str
    status: str


@dataclass(frozen=True)
class IdentityLinkMembership:
    tenant_id: UUID
    user_id: UUID
    status: str
    role: str


@dataclass(frozen=True)
class IdentityLinkIntentRecord:
    intent_id: UUID
    state_digest: bytes
    user_id: UUID
    tenant_id: UUID
    callback_destination: str
    created_at: datetime
    expires_at: datetime
    status: IdentityLinkIntentStatus = "active"
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class IdentityLinkRecord:
    link_id: UUID
    user_id: UUID
    tenant_id: UUID
    tenant_key: str
    open_id: str
    intent_id: UUID
    created_at: datetime
    status: IdentityLinkStatus = "active"
    revoked_at: datetime | None = None
    revocation_reason: str | None = None


@dataclass(frozen=True)
class IdentityLinkAuditRecord:
    audit_id: UUID
    action: IdentityLinkAuditAction
    actor_user_id: UUID
    tenant_id: UUID
    intent_id: UUID | None
    link_id: UUID | None
    tenant_key: str | None
    open_id: str | None
    reason: str
    created_at: datetime


@dataclass(frozen=True)
class IdentityLinkIntentStart:
    intent_id: UUID
    state: str
    callback_destination: str
    expires_at: datetime

    @property
    def intent_token(self) -> str:
        return self.state


@dataclass(frozen=True)
class IdentityLinkReceipt:
    action: Literal["linked", "unlinked"]
    link_id: UUID
    intent_id: UUID
    user_id: UUID
    tenant_id: UUID
    tenant_key: str
    open_id: str
    status: IdentityLinkStatus
    audit_id: UUID


@dataclass(frozen=True)
class IdentityLinkIntentReceipt:
    action: Literal["intent_revoked"]
    intent_id: UUID
    user_id: UUID
    tenant_id: UUID
    status: Literal["revoked"]
    audit_id: UUID


class IdentityLinkStoreConflict(RuntimeError):
    """A database uniqueness guard rejected a concurrent or duplicate bind."""


class IdentityLinkStore(Protocol):
    def intent_for_update(self, state_digest: bytes) -> IdentityLinkIntentRecord | None: ...

    def create_intent(self, record: IdentityLinkIntentRecord) -> None: ...

    def consume_intent(self, intent_id: UUID, now: datetime) -> bool: ...

    def revoke_intent(self, intent_id: UUID, now: datetime) -> bool: ...

    def tenants_for_id(self, tenant_id: UUID) -> tuple[IdentityLinkTenant, ...]: ...

    def bindings_for_tenant(self, tenant_id: UUID) -> tuple[IdentityLinkBinding, ...]: ...

    def bindings_for_key(self, tenant_key: str) -> tuple[IdentityLinkBinding, ...]: ...

    def memberships_for_user(self, tenant_id: UUID, user_id: UUID) -> tuple[IdentityLinkMembership, ...]: ...

    def identity_links_for_pair(self, tenant_key: str, open_id: str) -> tuple[IdentityLinkRecord, ...]: ...

    def identity_links_for_user_tenant(self, user_id: UUID, tenant_id: UUID) -> tuple[IdentityLinkRecord, ...]: ...

    def create_link(self, record: IdentityLinkRecord) -> None: ...

    def revoke_link(
        self,
        link_id: UUID,
        *,
        user_id: UUID,
        tenant_id: UUID,
        tenant_key: str,
        open_id: str,
        now: datetime,
        reason: str,
    ) -> IdentityLinkRecord | None: ...

    def write_audit(self, record: IdentityLinkAuditRecord) -> None: ...


class IdentityLinkRepository(Protocol):
    def transaction(self) -> ContextManager[IdentityLinkStore]: ...


class InMemoryIdentityLinkRepository:
    def __init__(
        self,
        *,
        tenants: Sequence[IdentityLinkTenant] = (),
        bindings: Sequence[IdentityLinkBinding] = (),
        memberships: Sequence[IdentityLinkMembership] = (),
        links: Sequence[IdentityLinkRecord] = (),
    ) -> None:
        self._lock = threading.RLock()
        self._tenants = list(tenants)
        self._bindings = list(bindings)
        self._memberships = list(memberships)
        self._intents: dict[bytes, IdentityLinkIntentRecord] = {}
        self._links: dict[UUID, IdentityLinkRecord] = {record.link_id: record for record in links}
        self._audits: list[IdentityLinkAuditRecord] = []

    def add_tenant(self, record: IdentityLinkTenant) -> None:
        with self._lock:
            self._tenants.append(record)

    def add_binding(self, record: IdentityLinkBinding) -> None:
        with self._lock:
            self._bindings.append(record)

    def add_membership(self, record: IdentityLinkMembership) -> None:
        with self._lock:
            self._memberships.append(record)

    def add_link(self, record: IdentityLinkRecord) -> None:
        with self._lock:
            if record.link_id in self._links:
                raise IdentityLinkStoreConflict("identity link id already exists")
            self._links[record.link_id] = record

    @contextmanager
    def transaction(self) -> Iterator["InMemoryIdentityLinkRepository"]:
        with self._lock:
            snapshot = (
                copy.deepcopy(self._intents),
                copy.deepcopy(self._links),
                copy.deepcopy(self._audits),
            )
            try:
                yield self
            except BaseException:
                self._intents, self._links, self._audits = snapshot
                raise

    def intent_for_update(self, state_digest: bytes) -> IdentityLinkIntentRecord | None:
        return self._intents.get(state_digest)

    def create_intent(self, record: IdentityLinkIntentRecord) -> None:
        if record.state_digest in self._intents or any(item.intent_id == record.intent_id for item in self._intents.values()):
            raise IdentityLinkStoreConflict("identity link intent collision")
        self._intents[record.state_digest] = record

    def consume_intent(self, intent_id: UUID, now: datetime) -> bool:
        for digest, record in self._intents.items():
            if record.intent_id == intent_id:
                if record.status != "active" or record.expires_at <= now:
                    return False
                self._intents[digest] = replace(record, status="consumed", consumed_at=now)
                return True
        return False

    def revoke_intent(self, intent_id: UUID, now: datetime) -> bool:
        for digest, record in self._intents.items():
            if record.intent_id == intent_id:
                if record.status != "active" or record.expires_at <= now:
                    return False
                self._intents[digest] = replace(record, status="revoked", revoked_at=now)
                return True
        return False

    def tenants_for_id(self, tenant_id: UUID) -> tuple[IdentityLinkTenant, ...]:
        return tuple(record for record in self._tenants if record.tenant_id == tenant_id)

    def bindings_for_tenant(self, tenant_id: UUID) -> tuple[IdentityLinkBinding, ...]:
        return tuple(record for record in self._bindings if record.tenant_id == tenant_id)

    def bindings_for_key(self, tenant_key: str) -> tuple[IdentityLinkBinding, ...]:
        return tuple(record for record in self._bindings if record.tenant_key == tenant_key)

    def memberships_for_user(self, tenant_id: UUID, user_id: UUID) -> tuple[IdentityLinkMembership, ...]:
        return tuple(
            record for record in self._memberships if record.tenant_id == tenant_id and record.user_id == user_id
        )

    def identity_links_for_pair(self, tenant_key: str, open_id: str) -> tuple[IdentityLinkRecord, ...]:
        return tuple(
            record
            for record in self._links.values()
            if record.tenant_key == tenant_key and record.open_id == open_id
        )

    def identity_links_for_user_tenant(self, user_id: UUID, tenant_id: UUID) -> tuple[IdentityLinkRecord, ...]:
        return tuple(
            record
            for record in self._links.values()
            if record.user_id == user_id and record.tenant_id == tenant_id
        )

    def create_link(self, record: IdentityLinkRecord) -> None:
        if any(
            item.status == "active"
            and (item.tenant_key, item.open_id) == (record.tenant_key, record.open_id)
            for item in self._links.values()
        ):
            raise IdentityLinkStoreConflict("stable Feishu identity is already linked")
        if any(
            item.status == "active"
            and (item.tenant_id, item.user_id) == (record.tenant_id, record.user_id)
            for item in self._links.values()
        ):
            raise IdentityLinkStoreConflict("platform user already has an active organization identity")
        if record.link_id in self._links:
            raise IdentityLinkStoreConflict("identity link id already exists")
        self._links[record.link_id] = record

    def revoke_link(
        self,
        link_id: UUID,
        *,
        user_id: UUID,
        tenant_id: UUID,
        tenant_key: str,
        open_id: str,
        now: datetime,
        reason: str,
    ) -> IdentityLinkRecord | None:
        record = self._links.get(link_id)
        if (
            record is None
            or record.status != "active"
            or record.user_id != user_id
            or record.tenant_id != tenant_id
            or record.tenant_key != tenant_key
            or record.open_id != open_id
        ):
            return None
        revoked = replace(record, status="revoked", revoked_at=now, revocation_reason=reason)
        self._links[link_id] = revoked
        return revoked

    def write_audit(self, record: IdentityLinkAuditRecord) -> None:
        if any(item.audit_id == record.audit_id for item in self._audits):
            raise IdentityLinkStoreConflict("identity link audit id already exists")
        self._audits.append(record)

    def intents(self) -> tuple[IdentityLinkIntentRecord, ...]:
        return tuple(self._intents.values())

    def links(self) -> tuple[IdentityLinkRecord, ...]:
        return tuple(self._links.values())

    def audits(self) -> tuple[IdentityLinkAuditRecord, ...]:
        return tuple(self._audits)


class _PostgresIdentityLinkTransaction:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def intent_for_update(self, state_digest: bytes) -> IdentityLinkIntentRecord | None:
        row = self._connection.execute(
            """
            SELECT id, state_digest, user_id, tenant_id, callback_destination,
                   created_at, expires_at, status, consumed_at, revoked_at
            FROM openclaw_account.stage1_identity_link_intents
            WHERE state_digest = %s
            FOR UPDATE
            """,
            (state_digest,),
        ).fetchone()
        return None if row is None else IdentityLinkIntentRecord(*row)

    def create_intent(self, record: IdentityLinkIntentRecord) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO openclaw_account.stage1_identity_link_intents(
                    id, state_digest, user_id, tenant_id, callback_destination,
                    created_at, expires_at, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.intent_id,
                    record.state_digest,
                    record.user_id,
                    record.tenant_id,
                    record.callback_destination,
                    record.created_at,
                    record.expires_at,
                    record.status,
                ),
            )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise IdentityLinkStoreConflict("identity link intent collision") from exc
            raise

    def consume_intent(self, intent_id: UUID, now: datetime) -> bool:
        row = self._connection.execute(
            """
            UPDATE openclaw_account.stage1_identity_link_intents
            SET status = 'consumed', consumed_at = %s
            WHERE id = %s AND status = 'active' AND expires_at > %s
            RETURNING id
            """,
            (now, intent_id, now),
        ).fetchone()
        return row is not None

    def revoke_intent(self, intent_id: UUID, now: datetime) -> bool:
        row = self._connection.execute(
            """
            UPDATE openclaw_account.stage1_identity_link_intents
            SET status = 'revoked', revoked_at = %s
            WHERE id = %s AND status = 'active' AND expires_at > %s
            RETURNING id
            """,
            (now, intent_id, now),
        ).fetchone()
        return row is not None

    def tenants_for_id(self, tenant_id: UUID) -> tuple[IdentityLinkTenant, ...]:
        rows = self._connection.execute(
            """
            SELECT id, status, tenant_type, workspace_mode, body_authority
            FROM openclaw_account.tenants
            WHERE id = %s
            FOR SHARE
            """,
            (tenant_id,),
        ).fetchall()
        return tuple(IdentityLinkTenant(*row) for row in rows)

    def bindings_for_tenant(self, tenant_id: UUID) -> tuple[IdentityLinkBinding, ...]:
        rows = self._connection.execute(
            """
            SELECT tenant_id, tenant_key, status
            FROM media_product.lark_tenant_bindings
            WHERE tenant_id = %s
            FOR SHARE
            """,
            (tenant_id,),
        ).fetchall()
        return tuple(IdentityLinkBinding(*row) for row in rows)

    def bindings_for_key(self, tenant_key: str) -> tuple[IdentityLinkBinding, ...]:
        rows = self._connection.execute(
            """
            SELECT tenant_id, tenant_key, status
            FROM media_product.lark_tenant_bindings
            WHERE tenant_key = %s
            FOR SHARE
            """,
            (tenant_key,),
        ).fetchall()
        return tuple(IdentityLinkBinding(*row) for row in rows)

    def memberships_for_user(self, tenant_id: UUID, user_id: UUID) -> tuple[IdentityLinkMembership, ...]:
        rows = self._connection.execute(
            """
            SELECT tenant_id, user_id, status, role
            FROM openclaw_account.tenant_members
            WHERE tenant_id = %s AND user_id = %s
            FOR SHARE
            """,
            (tenant_id, user_id),
        ).fetchall()
        return tuple(IdentityLinkMembership(*row) for row in rows)

    @staticmethod
    def _link(row: tuple[Any, ...]) -> IdentityLinkRecord:
        return IdentityLinkRecord(*row)

    def identity_links_for_pair(self, tenant_key: str, open_id: str) -> tuple[IdentityLinkRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT id, user_id, tenant_id, tenant_key, open_id, intent_id,
                   created_at, status, revoked_at, revocation_reason
            FROM openclaw_account.stage1_identity_links
            WHERE tenant_key = %s AND open_id = %s
            FOR SHARE
            """,
            (tenant_key, open_id),
        ).fetchall()
        return tuple(self._link(row) for row in rows)

    def identity_links_for_user_tenant(self, user_id: UUID, tenant_id: UUID) -> tuple[IdentityLinkRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT id, user_id, tenant_id, tenant_key, open_id, intent_id,
                   created_at, status, revoked_at, revocation_reason
            FROM openclaw_account.stage1_identity_links
            WHERE user_id = %s AND tenant_id = %s
            FOR SHARE
            """,
            (user_id, tenant_id),
        ).fetchall()
        return tuple(self._link(row) for row in rows)

    def create_link(self, record: IdentityLinkRecord) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO openclaw_account.stage1_identity_links(
                    id, user_id, tenant_id, tenant_key, open_id, intent_id,
                    created_at, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.link_id,
                    record.user_id,
                    record.tenant_id,
                    record.tenant_key,
                    record.open_id,
                    record.intent_id,
                    record.created_at,
                    record.status,
                ),
            )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise IdentityLinkStoreConflict("stable Feishu identity is already linked") from exc
            raise

    def revoke_link(
        self,
        link_id: UUID,
        *,
        user_id: UUID,
        tenant_id: UUID,
        tenant_key: str,
        open_id: str,
        now: datetime,
        reason: str,
    ) -> IdentityLinkRecord | None:
        row = self._connection.execute(
            """
            UPDATE openclaw_account.stage1_identity_links
            SET status = 'revoked', revoked_at = %s, revocation_reason = %s
            WHERE id = %s AND user_id = %s AND tenant_id = %s
              AND tenant_key = %s AND open_id = %s AND status = 'active'
            RETURNING id, user_id, tenant_id, tenant_key, open_id, intent_id,
                      created_at, status, revoked_at, revocation_reason
            """,
            (now, reason, link_id, user_id, tenant_id, tenant_key, open_id),
        ).fetchone()
        return None if row is None else self._link(row)

    def write_audit(self, record: IdentityLinkAuditRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO openclaw_account.stage1_identity_link_audit(
                id, action, actor_user_id, tenant_id, intent_id, link_id,
                tenant_key, open_id, reason, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.audit_id,
                record.action,
                record.actor_user_id,
                record.tenant_id,
                record.intent_id,
                record.link_id,
                record.tenant_key,
                record.open_id,
                record.reason,
                record.created_at,
            ),
        )


class PostgresIdentityLinkRepository:
    def __init__(self, database: Any) -> None:
        self._database = database

    @contextmanager
    def transaction(self) -> Iterator[IdentityLinkStore]:
        with self._database.connect() as connection:
            yield _PostgresIdentityLinkTransaction(connection)


class IdentityLinkService:
    def __init__(
        self,
        repository: IdentityLinkRepository,
        *,
        allowed_callback_destinations: Sequence[str],
        now: Callable[[], datetime] | None = None,
        ttl_seconds: int = IDENTITY_LINK_TTL_SECONDS,
    ) -> None:
        if not allowed_callback_destinations:
            raise ValueError("at least one identity link callback destination is required")
        if not isinstance(ttl_seconds, int) or not 60 <= ttl_seconds <= 60 * 60:
            raise ValueError("identity link ttl must be between 60 seconds and one hour")
        normalized = tuple(dict.fromkeys(self._normalize_callback(item) for item in allowed_callback_destinations))
        self._repository = repository
        self._allowed_callbacks = frozenset(normalized)
        self._now = now or _now_utc
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _normalize_callback(callback_destination: object) -> str:
        if not isinstance(callback_destination, str):
            raise ValueError("identity link callback destination must be a string")
        normalized = callback_destination.strip()
        if not normalized:
            raise ValueError("identity link callback destination must be non-empty")
        return normalized

    def _validate_callback(self, callback_destination: str) -> str:
        if not isinstance(callback_destination, str):
            _invalid_request("identity_link_callback_mismatch", "回调地址不在允许列表中。")
        normalized = callback_destination.strip()
        if normalized not in self._allowed_callbacks:
            _invalid_request("identity_link_callback_mismatch", "回调地址不在允许列表中。")
        return normalized

    @staticmethod
    def _validate_state(state: str) -> bytes:
        digest = _token_digest(state)
        if not digest:
            _invalid_request("identity_link_intent_invalid", "身份关联意图无效或已过期。")
        return digest

    @staticmethod
    def _validate_oauth_result(
        oauth_result: FeishuOAuthResult | VerifiedFeishuOAuthResult | Mapping[str, Any],
    ) -> tuple[str, str]:
        status: object
        tenant_key: object
        open_id: object
        if isinstance(oauth_result, VerifiedFeishuOAuthResult):
            status, tenant_key, open_id = oauth_result.status, oauth_result.tenant_key, oauth_result.open_id
        elif isinstance(oauth_result, FeishuOAuthResult):
            status, tenant_key, open_id = oauth_result.status, oauth_result.tenant_key, oauth_result.open_id
        elif isinstance(oauth_result, Mapping):
            status = oauth_result.get("status")
            if status is None and oauth_result.get("verified") is True:
                status = "VERIFIED"
            tenant_key, open_id = oauth_result.get("tenant_key"), oauth_result.get("open_id")
        else:
            _invalid_request("identity_link_oauth_unverified", "飞书授权结果未完成验证。", status=403)
        if status != "VERIFIED":
            _invalid_request("identity_link_oauth_unverified", "飞书授权结果未完成验证。", status=403)
        return (
            _normalize_identity_value(tenant_key),
            _normalize_identity_value(open_id),
        )

    @staticmethod
    def _one_tenant(store: IdentityLinkStore, tenant_id: UUID) -> IdentityLinkTenant:
        tenants = store.tenants_for_id(tenant_id)
        if not tenants:
            _invalid_request("identity_link_tenant_missing", "组织工作区不存在。", status=409)
        if len(tenants) != 1:
            _invalid_request("identity_link_tenant_ambiguous", "组织工作区绑定不唯一。", status=409)
        tenant = tenants[0]
        if tenant.status != "active":
            _invalid_request("identity_link_tenant_inactive", "组织工作区当前不可用。", status=409)
        if (
            tenant.tenant_type != "organization"
            or tenant.workspace_mode != "organization_lark"
            or tenant.body_authority != "lark"
        ):
            _invalid_request("identity_link_tenant_invalid", "组织工作区授权组合无效。", status=409)
        return tenant

    @staticmethod
    def _one_membership(store: IdentityLinkStore, tenant_id: UUID, user_id: UUID) -> IdentityLinkMembership:
        memberships = store.memberships_for_user(tenant_id, user_id)
        if not memberships:
            _invalid_request("identity_link_membership_missing", "当前用户不是该组织的有效成员。", status=403)
        if len(memberships) != 1:
            _invalid_request("identity_link_membership_ambiguous", "当前用户的组织成员关系不唯一。", status=403)
        membership = memberships[0]
        if membership.status != "active":
            _invalid_request("identity_link_membership_inactive", "当前用户的组织成员关系已停用。", status=403)
        if membership.tenant_id != tenant_id or membership.user_id != user_id:
            _invalid_request("identity_link_membership_mismatch", "组织成员关系与当前用户不一致。", status=403)
        return membership

    @staticmethod
    def _one_binding_for_tenant(store: IdentityLinkStore, tenant_id: UUID) -> IdentityLinkBinding:
        bindings = store.bindings_for_tenant(tenant_id)
        if not bindings:
            _invalid_request("identity_link_binding_missing", "组织飞书绑定不存在。", status=409)
        if len(bindings) != 1:
            _invalid_request("identity_link_binding_ambiguous", "组织飞书绑定不唯一。", status=409)
        binding = bindings[0]
        if binding.status != "active":
            _invalid_request("identity_link_binding_inactive", "组织飞书绑定当前不可用。", status=409)
        if binding.tenant_id != tenant_id:
            _invalid_request("identity_link_cross_tenant", "飞书身份不属于当前组织。", status=403)
        _normalize_identity_value(binding.tenant_key, "identity_link_binding_invalid")
        return binding

    def _validate_current_organization(
        self,
        store: IdentityLinkStore,
        *,
        user_id: UUID,
        tenant_id: UUID,
    ) -> IdentityLinkBinding:
        self._one_tenant(store, tenant_id)
        self._one_membership(store, tenant_id, user_id)
        return self._one_binding_for_tenant(store, tenant_id)

    @staticmethod
    def _validate_oauth_binding(
        store: IdentityLinkStore,
        *,
        tenant_id: UUID,
        expected_binding: IdentityLinkBinding,
        tenant_key: str,
    ) -> None:
        bindings = store.bindings_for_key(tenant_key)
        if not bindings:
            _invalid_request("identity_link_binding_missing", "飞书组织绑定不存在。", status=409)
        if len(bindings) != 1:
            _invalid_request("identity_link_binding_ambiguous", "飞书组织绑定不唯一。", status=409)
        binding = bindings[0]
        if binding.status != "active":
            _invalid_request("identity_link_binding_inactive", "飞书组织绑定当前不可用。", status=409)
        if binding.tenant_id != tenant_id or binding.tenant_key != expected_binding.tenant_key:
            _invalid_request("identity_link_cross_tenant", "飞书身份不属于当前组织。", status=403)

    def start_link_intent(
        self,
        user_id: UUID | None,
        tenant_id: UUID | None,
        callback_destination: str,
    ) -> IdentityLinkIntentStart:
        current_user_id = _require_user_id(user_id)
        current_tenant_id = _require_tenant_id(tenant_id)
        callback = self._validate_callback(callback_destination)
        state = _new_token()
        now = _aware(self._now())
        record = IdentityLinkIntentRecord(
            intent_id=uuid4(),
            state_digest=_token_digest(state),
            user_id=current_user_id,
            tenant_id=current_tenant_id,
            callback_destination=callback,
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
        )
        try:
            with self._repository.transaction() as store:
                self._validate_current_organization(
                    store,
                    user_id=current_user_id,
                    tenant_id=current_tenant_id,
                )
                store.create_intent(record)
        except (AccountAuthError, AccountContractError):
            raise
        except IdentityLinkStoreConflict as exc:
            raise AccountContractError("identity_link_store_conflict", "身份关联意图无法安全创建") from exc
        except Exception as exc:
            raise AccountContractError("identity_link_store_unavailable", "身份关联存储暂时不可用") from exc
        return IdentityLinkIntentStart(record.intent_id, state, callback, record.expires_at)

    start = start_link_intent

    def complete_link(
        self,
        state: str,
        *,
        user_id: UUID | None,
        callback_destination: str,
        oauth_result: FeishuOAuthResult | VerifiedFeishuOAuthResult | Mapping[str, Any],
        confirmed: bool,
    ) -> IdentityLinkReceipt:
        current_user_id = _require_user_id(user_id)
        callback = self._validate_callback(callback_destination)
        if confirmed is not True:
            _invalid_request("identity_link_confirmation_required", "请再次明确确认要关联该飞书身份。")
        tenant_key, open_id = self._validate_oauth_result(oauth_result)
        state_digest = self._validate_state(state)
        now = _aware(self._now())
        try:
            with self._repository.transaction() as store:
                intent = store.intent_for_update(state_digest)
                if intent is None or intent.status != "active" or intent.expires_at <= now:
                    _invalid_request("identity_link_intent_invalid", "身份关联意图无效或已过期。")
                if intent.callback_destination != callback:
                    _invalid_request("identity_link_callback_mismatch", "回调地址不在该身份关联意图中。")
                if intent.user_id != current_user_id:
                    _invalid_request("identity_link_wrong_user", "身份关联意图不属于当前用户。", status=403)
                binding = self._validate_current_organization(
                    store,
                    user_id=current_user_id,
                    tenant_id=intent.tenant_id,
                )
                self._validate_oauth_binding(
                    store,
                    tenant_id=intent.tenant_id,
                    expected_binding=binding,
                    tenant_key=tenant_key,
                )
                pair_links = store.identity_links_for_pair(tenant_key, open_id)
                if len(pair_links) > 1:
                    _invalid_request("identity_link_identity_ambiguous", "飞书身份关联不唯一。", status=409)
                if pair_links:
                    existing = pair_links[0]
                    if existing.tenant_id != intent.tenant_id:
                        _invalid_request("identity_link_cross_tenant", "飞书身份不属于当前组织。", status=403)
                    if existing.user_id != current_user_id:
                        _invalid_request("identity_link_wrong_user", "飞书身份已属于其他平台用户。", status=403)
                    if existing.status != "active":
                        _invalid_request("identity_link_identity_inactive", "飞书身份关联已停用。", status=409)
                    _invalid_request("identity_link_duplicate", "该飞书身份已经关联当前平台用户。", status=409)
                active_user_links = tuple(
                    record
                    for record in store.identity_links_for_user_tenant(current_user_id, intent.tenant_id)
                    if record.status == "active"
                )
                if len(active_user_links) > 1:
                    _invalid_request("identity_link_identity_ambiguous", "当前组织的身份关联不唯一。", status=409)
                if active_user_links:
                    _invalid_request("identity_link_duplicate", "当前用户已经关联该组织身份。", status=409)
                link = IdentityLinkRecord(
                    link_id=uuid4(),
                    user_id=current_user_id,
                    tenant_id=intent.tenant_id,
                    tenant_key=tenant_key,
                    open_id=open_id,
                    intent_id=intent.intent_id,
                    created_at=now,
                )
                if not store.consume_intent(intent.intent_id, now):
                    _invalid_request("identity_link_intent_invalid", "身份关联意图无效或已过期。")
                store.create_link(link)
                audit = IdentityLinkAuditRecord(
                    audit_id=uuid4(),
                    action="linked",
                    actor_user_id=current_user_id,
                    tenant_id=intent.tenant_id,
                    intent_id=intent.intent_id,
                    link_id=link.link_id,
                    tenant_key=tenant_key,
                    open_id=open_id,
                    reason="user_confirmed_identity_link",
                    created_at=now,
                )
                store.write_audit(audit)
                return IdentityLinkReceipt(
                    action="linked",
                    link_id=link.link_id,
                    intent_id=intent.intent_id,
                    user_id=link.user_id,
                    tenant_id=link.tenant_id,
                    tenant_key=link.tenant_key,
                    open_id=link.open_id,
                    status=link.status,
                    audit_id=audit.audit_id,
                )
        except (AccountAuthError, AccountContractError):
            raise
        except IdentityLinkStoreConflict as exc:
            raise AccountAuthError("identity_link_duplicate", "该身份关联已被其他请求占用。", status=409) from exc
        except Exception as exc:
            raise AccountContractError("identity_link_store_unavailable", "身份关联存储暂时不可用") from exc

    complete = complete_link

    def revoke_intent(
        self,
        state: str,
        *,
        user_id: UUID | None,
        callback_destination: str,
        reason: str = "user_revoked_identity_link_intent",
    ) -> IdentityLinkIntentReceipt:
        current_user_id = _require_user_id(user_id)
        callback = self._validate_callback(callback_destination)
        state_digest = self._validate_state(state)
        normalized_reason = _normalize_reason(reason)
        now = _aware(self._now())
        try:
            with self._repository.transaction() as store:
                intent = store.intent_for_update(state_digest)
                if intent is None or intent.status != "active" or intent.expires_at <= now:
                    _invalid_request("identity_link_intent_invalid", "身份关联意图无效或已过期。")
                if intent.callback_destination != callback:
                    _invalid_request("identity_link_callback_mismatch", "回调地址不在该身份关联意图中。")
                if intent.user_id != current_user_id:
                    _invalid_request("identity_link_wrong_user", "身份关联意图不属于当前用户。", status=403)
                if not store.revoke_intent(intent.intent_id, now):
                    _invalid_request("identity_link_intent_invalid", "身份关联意图无效或已过期。")
                audit = IdentityLinkAuditRecord(
                    audit_id=uuid4(),
                    action="intent_revoked",
                    actor_user_id=current_user_id,
                    tenant_id=intent.tenant_id,
                    intent_id=intent.intent_id,
                    link_id=None,
                    tenant_key=None,
                    open_id=None,
                    reason=normalized_reason,
                    created_at=now,
                )
                store.write_audit(audit)
                return IdentityLinkIntentReceipt(
                    action="intent_revoked",
                    intent_id=intent.intent_id,
                    user_id=current_user_id,
                    tenant_id=intent.tenant_id,
                    status="revoked",
                    audit_id=audit.audit_id,
                )
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("identity_link_store_unavailable", "身份关联存储暂时不可用") from exc

    def unlink(
        self,
        user_id: UUID | None,
        tenant_id: UUID | None,
        tenant_key: str,
        open_id: str,
        *,
        reason: str = "user_requested_identity_unlink",
    ) -> IdentityLinkReceipt:
        current_user_id = _require_user_id(user_id)
        current_tenant_id = _require_tenant_id(tenant_id)
        normalized_tenant_key = _normalize_identity_value(tenant_key)
        normalized_open_id = _normalize_identity_value(open_id)
        normalized_reason = _normalize_reason(reason)
        now = _aware(self._now())
        try:
            with self._repository.transaction() as store:
                binding = self._validate_current_organization(
                    store,
                    user_id=current_user_id,
                    tenant_id=current_tenant_id,
                )
                if binding.tenant_key != normalized_tenant_key:
                    _invalid_request("identity_link_cross_tenant", "飞书身份不属于当前组织。", status=403)
                pair_links = store.identity_links_for_pair(normalized_tenant_key, normalized_open_id)
                if len(pair_links) > 1:
                    _invalid_request("identity_link_identity_ambiguous", "飞书身份关联不唯一。", status=409)
                if not pair_links:
                    _invalid_request("identity_link_not_found", "未找到当前组织中的身份关联。", status=404)
                existing = pair_links[0]
                if existing.tenant_id != current_tenant_id:
                    _invalid_request("identity_link_cross_tenant", "飞书身份不属于当前组织。", status=403)
                if existing.user_id != current_user_id:
                    _invalid_request("identity_link_wrong_user", "身份关联不属于当前用户。", status=403)
                if existing.status != "active":
                    _invalid_request("identity_link_identity_inactive", "飞书身份关联已停用。", status=409)
                revoked = store.revoke_link(
                    existing.link_id,
                    user_id=current_user_id,
                    tenant_id=current_tenant_id,
                    tenant_key=normalized_tenant_key,
                    open_id=normalized_open_id,
                    now=now,
                    reason=normalized_reason,
                )
                if revoked is None:
                    _invalid_request("identity_link_identity_inactive", "飞书身份关联已停用。", status=409)
                audit = IdentityLinkAuditRecord(
                    audit_id=uuid4(),
                    action="unlinked",
                    actor_user_id=current_user_id,
                    tenant_id=current_tenant_id,
                    intent_id=revoked.intent_id,
                    link_id=revoked.link_id,
                    tenant_key=revoked.tenant_key,
                    open_id=revoked.open_id,
                    reason=normalized_reason,
                    created_at=now,
                )
                store.write_audit(audit)
                return IdentityLinkReceipt(
                    action="unlinked",
                    link_id=revoked.link_id,
                    intent_id=revoked.intent_id,
                    user_id=revoked.user_id,
                    tenant_id=revoked.tenant_id,
                    tenant_key=revoked.tenant_key,
                    open_id=revoked.open_id,
                    status=revoked.status,
                    audit_id=audit.audit_id,
                )
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("identity_link_store_unavailable", "身份关联存储暂时不可用") from exc

    revoke_link = unlink


__all__ = [
    "IDENTITY_LINK_TTL_SECONDS",
    "FeishuOAuthResult",
    "IdentityLinkAuditRecord",
    "IdentityLinkBinding",
    "IdentityLinkIntentReceipt",
    "IdentityLinkIntentRecord",
    "IdentityLinkIntentStart",
    "IdentityLinkMembership",
    "IdentityLinkReceipt",
    "IdentityLinkRecord",
    "IdentityLinkRepository",
    "IdentityLinkService",
    "IdentityLinkStore",
    "IdentityLinkStoreConflict",
    "IdentityLinkTenant",
    "InMemoryIdentityLinkRepository",
    "PostgresIdentityLinkRepository",
    "VerifiedFeishuOAuthResult",
]
