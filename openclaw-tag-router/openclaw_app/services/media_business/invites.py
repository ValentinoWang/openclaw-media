"""Tenant-scoped PostgreSQL read model for the B09 invites page."""
from __future__ import annotations

import binascii
import hashlib
import hmac
import json
import re
import secrets
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import foundation
from .foundation import MediaBusinessError, TenantContext, public_projection, require_context


SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100
_INVITE_CODE = re.compile(r"^[A-F0-9]{20}$")
_CURSOR_AAD = b"media-web-b09-invitees-v1"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


InvitesError = MediaBusinessError


class InvitesForbidden(foundation.Forbidden):
    def __init__(self, message: str = "invite data is not available for this session") -> None:
        super().__init__(message)


class InvitesNotFound(foundation.NotFound):
    def __init__(self, message: str = "invite profile was not found") -> None:
        super().__init__(message)


class InvitesInvalidRequest(InvitesError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(foundation.INVALID_REQUEST, message, status=400, field=field)


class InvitesInternalError(foundation.InternalError):
    def __init__(self, message: str = "invite data is unavailable") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class InviteeCursor:
    """The decoded keyset position; it never crosses the public API boundary."""

    tenant_id: UUID
    inviter_user_id: UUID
    created_at: datetime
    invitee_user_id: UUID


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


class ConnectionFactory(Protocol):
    def __call__(self) -> AbstractContextManager[DatabaseConnection]: ...


@dataclass(frozen=True)
class _Scope:
    tenant_id: UUID
    user_id: UUID


class InvitesService:
    """Read the existing account tables without accepting caller-selected scope."""

    _PROFILE_QUERY = """
        SELECT profile.invite_code,
               profile.signup_enabled,
               profile.signup_quota,
               profile.signup_used,
               profile.signup_expires_at,
               profile.updated_at
        FROM openclaw_account.affiliate_profiles AS profile
        JOIN openclaw_account.users AS owner
          ON owner.id = profile.user_id
        JOIN openclaw_account.tenant_members AS member
          ON member.user_id = owner.id
        WHERE owner.id = %s
          AND member.tenant_id = %s
          AND member.status = 'active'
    """

    _INVITEES_STATE_QUERY = """
        SELECT profile.updated_at,
               COUNT(edge.invitee_user_id),
               MAX(edge.created_at)
        FROM openclaw_account.affiliate_profiles AS profile
        JOIN openclaw_account.users AS owner
          ON owner.id = profile.user_id
        JOIN openclaw_account.tenant_members AS member
          ON member.user_id = owner.id
        LEFT JOIN openclaw_account.affiliate_edges AS edge
          ON edge.inviter_user_id = owner.id
        WHERE owner.id = %s
          AND member.tenant_id = %s
          AND member.status = 'active'
        GROUP BY profile.updated_at
    """

    _INVITEES_QUERY = """
        SELECT edge.invitee_user_id,
               invitee.username,
               invitee.status,
               edge.created_at
        FROM openclaw_account.affiliate_edges AS edge
        JOIN openclaw_account.users AS invitee
          ON invitee.id = edge.invitee_user_id
        WHERE edge.inviter_user_id = %s
        ORDER BY edge.created_at DESC, edge.invitee_user_id ASC
        LIMIT %s
    """

    _INVITEES_CURSOR_QUERY = """
        SELECT edge.invitee_user_id,
               invitee.username,
               invitee.status,
               edge.created_at
        FROM openclaw_account.affiliate_edges AS edge
        JOIN openclaw_account.users AS invitee
          ON invitee.id = edge.invitee_user_id
        WHERE edge.inviter_user_id = %s
          AND (
            edge.created_at < %s
            OR (edge.created_at = %s AND edge.invitee_user_id > %s)
          )
        ORDER BY edge.created_at DESC, edge.invitee_user_id ASC
        LIMIT %s
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        public_id_secret: bytes,
        cursor_secret: bytes,
    ) -> None:
        if len(public_id_secret) < 16 or len(cursor_secret) < 16:
            raise ValueError("B09 secrets must be at least 16 bytes")
        self._connection_factory = connection_factory
        self._public_id_secret = bytes(public_id_secret)
        # c3/c5: purpose-tagged cursor key, distinct from every other
        # service's -- previously a bare sha256(cursor_secret) shared
        # byte-for-byte across services. Deliberately invalidates any
        # cursor a client is holding across the deploy; public_id_secret
        # (above) is untouched, so public ids are unaffected.
        self._cursor_key = foundation.derive_namespace_secret(cursor_secret, "invites-cursor")

    def get_affiliate_profile(self, context: TenantContext) -> dict[str, Any]:
        scope = self._scope(context)
        try:
            with self._connection_factory() as connection:
                row = connection.execute(
                    self._PROFILE_QUERY,
                    (scope.user_id, scope.tenant_id),
                ).fetchone()
        except InvitesError:
            raise
        except Exception as exc:
            raise InvitesInternalError() from exc

        if row is None:
            raise InvitesNotFound()
        code, enabled, quota, used, expires_at, updated_at = row
        self._validate_profile(code, enabled, quota, used, expires_at, updated_at)
        revision = _revision((updated_at,), 0)
        response = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": revision,
            "profile": {
                "affiliateCode": code,
                "enabled": enabled,
                "quota": quota,
                "used": used,
                "expiresAt": _timestamp_text(expires_at, allow_none=True),
                "revision": revision,
            },
        }
        return public_projection(response)

    def list_invitees(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        scope = self._scope(context)
        size = _page_size(page_size)
        position = self._decode_cursor(cursor, scope) if cursor else None
        try:
            with self._connection_factory() as connection:
                state = connection.execute(
                    self._INVITEES_STATE_QUERY,
                    (scope.user_id, scope.tenant_id),
                ).fetchone()
                if state is None:
                    raise InvitesNotFound()
                profile_updated_at, total, latest_edge_at = state
                if position is None:
                    rows = connection.execute(
                        self._INVITEES_QUERY,
                        (scope.user_id, size + 1),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        self._INVITEES_CURSOR_QUERY,
                        (
                            scope.user_id,
                            position.created_at,
                            position.created_at,
                            position.invitee_user_id,
                            size + 1,
                        ),
                    ).fetchall()
        except InvitesError:
            raise
        except Exception as exc:
            raise InvitesInternalError() from exc

        if not isinstance(total, int) or total < 0:
            raise InvitesInternalError("invite count is invalid")
        _require_timestamp(profile_updated_at)
        if latest_edge_at is not None:
            _require_timestamp(latest_edge_at)
        if not isinstance(rows, list):
            rows = list(rows)

        has_next = len(rows) > size
        visible_rows = rows[:size]
        items = [self._invitee_projection(row) for row in visible_rows]
        next_cursor = None
        if has_next:
            last = visible_rows[-1]
            next_cursor = self._encode_cursor(
                InviteeCursor(
                    tenant_id=scope.tenant_id,
                    inviter_user_id=scope.user_id,
                    created_at=_require_timestamp(last[3]),
                    invitee_user_id=_require_uuid(last[0]),
                )
            )

        response = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": _revision(
                (profile_updated_at, latest_edge_at),
                total,
            ),
            "items": items,
            "nextCursor": next_cursor,
        }
        return public_projection(response)

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, InvitesError):
            return {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "field": error.field,
                }
            }
        return {
            "error": {
                "code": "internal_error",
                "message": "invite data is unavailable",
                "field": None,
            }
        }

    def _scope(self, context: TenantContext) -> _Scope:
        try:
            checked = require_context(context)
            return _Scope(
                tenant_id=UUID(checked.tenant_id),
                user_id=UUID(checked.user_public_id),
            )
        except (MediaBusinessError, ValueError, TypeError) as exc:
            raise InvitesForbidden() from exc

    @staticmethod
    def _validate_profile(
        code: Any,
        enabled: Any,
        quota: Any,
        used: Any,
        expires_at: Any,
        updated_at: Any,
    ) -> None:
        if (
            not isinstance(code, str)
            or _INVITE_CODE.fullmatch(code) is None
            or type(enabled) is not bool
            or not isinstance(quota, int)
            or quota < 0
            or not isinstance(used, int)
            or used < 0
            or used > quota
        ):
            raise InvitesInternalError("invite profile violates its database contract")
        _require_timestamp(updated_at)
        if expires_at is not None:
            _require_timestamp(expires_at)

    def _invitee_projection(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 4:
            raise InvitesInternalError("invitee row shape is invalid")
        user_id, display_name, status, joined_at = row
        public_user_id = _public_user_id(_require_uuid(user_id), self._public_id_secret)
        if not isinstance(display_name, str) or not display_name.strip():
            raise InvitesInternalError("invitee display name is missing")
        if not isinstance(status, str) or not status.strip():
            raise InvitesInternalError("invitee status is missing")
        return {
            "publicUserId": public_user_id,
            "displayName": display_name,
            "status": status,
            "joinedAt": _timestamp_text(joined_at),
        }

    def _encode_cursor(self, cursor: InviteeCursor) -> str:
        payload = foundation.canonical_json_bytes(
            {
                "version": 1,
                "tenantId": str(cursor.tenant_id),
                "inviterUserId": str(cursor.inviter_user_id),
                "createdAt": _timestamp_text(cursor.created_at),
                "inviteeUserId": str(cursor.invitee_user_id),
            }
        )
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(self._cursor_key).encrypt(
            nonce,
            payload,
            _cursor_aad(cursor.tenant_id, cursor.inviter_user_id),
        )
        return _b64_encode(nonce + encrypted)

    def _decode_cursor(self, token: str, scope: _Scope) -> InviteeCursor:
        if not isinstance(token, str) or not token or re.fullmatch(r"[A-Za-z0-9_-]+", token) is None:
            raise InvitesInvalidRequest("cursor is invalid", field="cursor")
        try:
            raw = _b64_decode(token)
            if len(raw) <= 12 + 16:
                raise ValueError("cursor payload is too short")
            nonce, encrypted = raw[:12], raw[12:]
            payload = AESGCM(self._cursor_key).decrypt(
                nonce,
                encrypted,
                _cursor_aad(scope.tenant_id, scope.user_id),
            )
            data = json.loads(payload.decode("utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError("cursor version is invalid")
            tenant_id = UUID(data["tenantId"])
            inviter_user_id = UUID(data["inviterUserId"])
            if tenant_id != scope.tenant_id or inviter_user_id != scope.user_id:
                raise ValueError("cursor scope is invalid")
            return InviteeCursor(
                tenant_id=tenant_id,
                inviter_user_id=inviter_user_id,
                created_at=_require_timestamp(data["createdAt"]),
                invitee_user_id=UUID(data["inviteeUserId"]),
            )
        except (binascii.Error, InvalidTag, InvitesInternalError, KeyError, TypeError, ValueError) as exc:
            raise InvitesInvalidRequest("cursor is invalid", field="cursor") from exc


def _page_size(value: Any) -> int:
    return foundation.page_size(value, error=lambda m: InvitesInvalidRequest(m, field="pageSize"))


def _require_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as exc:
            raise InvitesInternalError("stored user identifier is invalid") from exc
    raise InvitesInternalError("stored user identifier is invalid")


def _public_user_id(user_id: UUID, secret: bytes) -> str:
    digest = hmac.new(secret, str(user_id).encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"user_{digest}"


def _require_timestamp_error(label: str, reason: str) -> Exception:
    if reason == "naive":
        return InvitesInternalError("stored invite timestamp must be timezone-aware")
    return InvitesInternalError("stored invite timestamp is invalid")


def _require_timestamp(value: Any) -> datetime:
    return foundation.coerce_utc(value, "stored invite timestamp", error=_require_timestamp_error, allow_naive=False)


def _timestamp_text(value: Any, *, allow_none: bool = False) -> str | None:
    if value is None:
        if allow_none:
            return None
        raise InvitesInternalError("stored invite timestamp is missing")
    return _require_timestamp(value).isoformat().replace("+00:00", "Z")


def _revision(timestamps: tuple[Any, ...], count: int) -> int:
    if type(count) is not int or count < 0:
        raise InvitesInternalError("invite revision count is invalid")
    state = "|".join(
        "" if timestamp is None else _timestamp_text(timestamp) or ""
        for timestamp in timestamps
    )
    digest = hashlib.sha256(f"{state}|{count}".encode("utf-8")).hexdigest()
    return max(1, int(digest[:12], 16))


def _cursor_aad(tenant_id: UUID, user_id: UUID) -> bytes:
    return _CURSOR_AAD + b"|" + str(tenant_id).encode("ascii") + b"|" + str(user_id).encode("ascii")


def _b64_encode(value: bytes) -> str:
    return foundation.b64url_encode(value)


def _b64_decode(value: str) -> bytes:
    return foundation.b64url_decode(value)
