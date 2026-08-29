"""IF2 adapter for the B11 administrator access page."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from .foundation import IF2_KEY, MediaBusinessError, idempotency_key


SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100
_PUBLIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_UTC = timezone.utc


class AdminAccessError(MediaBusinessError):
    status = 500
    field: str | None = None

    def __init__(self, code: str, message: str, *, status: int, field: str | None = None) -> None:
        super().__init__(code, message)
        self.status = status
        self.field = field


class AdminAccessUnauthorized(AdminAccessError):
    def __init__(self, message: str = "administrator authentication is required") -> None:
        super().__init__("authentication_required", message, status=401)


class AdminAccessForbidden(AdminAccessError):
    def __init__(self, message: str = "administrator permission is required") -> None:
        super().__init__("forbidden", message, status=403)


class AdminAccessNotFound(AdminAccessError):
    def __init__(self, message: str = "resource was not found") -> None:
        super().__init__("resource_not_found", message, status=404)


class AdminAccessInvalidRequest(AdminAccessError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__("invalid_request", message, status=400, field=field)


class AdminAccessRevisionConflict(AdminAccessError):
    def __init__(self, message: str = "resource revision has changed") -> None:
        super().__init__("revision_conflict", message, status=409)


class AdminAccessIdempotencyConflict(AdminAccessError):
    def __init__(self, message: str = "idempotency key is bound to another request") -> None:
        super().__init__("idempotency_conflict", message, status=409)


class AdminAccessInternalError(AdminAccessError):
    def __init__(self, message: str = "administrator access data is unavailable") -> None:
        super().__init__("internal_error", message, status=500)


@dataclass(frozen=True)
class AdminAccessContext:
    actor_user_id: UUID
    actor_session_id: UUID
    role: str = "admin"


AdminSessionContext = AdminAccessContext


@dataclass(frozen=True)
class _CursorPosition:
    resource: str
    search: str
    created_at: datetime
    object_id: UUID


class ConnectionFactory(Protocol):
    def __call__(self) -> AbstractContextManager[Any]: ...


class AdminAccessStorage(Protocol):
    def require_admin(self, connection: Any, context: AdminAccessContext, now: datetime) -> None: ...

    def find_idempotency(self, connection: Any, actor_user_id: UUID, operation: str, key: str) -> dict[str, Any] | None: ...

    def save_audit(self, connection: Any, **record: Any) -> None: ...

    def affiliate_users(self, connection: Any, *, search: str, position: _CursorPosition | None, limit: int) -> list[Any]: ...

    def affiliate_user(self, connection: Any, user_id: UUID, *, lock: bool) -> Any | None: ...

    def update_affiliate_user(
        self,
        connection: Any,
        *,
        user_id: UUID,
        affiliate_enabled: bool,
        invitation_quota: int,
    ) -> Any | None: ...

    def admission_batches(self, connection: Any, *, position: _CursorPosition | None, limit: int) -> list[Any]: ...

    def admission_batch(self, connection: Any, batch_id: UUID, *, lock: bool) -> Any | None: ...

    def update_admission_batch_disabled(self, connection: Any, *, batch_id: UUID) -> Any | None: ...

    def registration_policy(self, connection: Any, *, lock: bool) -> Any | None: ...

    def update_registration_policy(self, connection: Any, *, mode: str, actor_user_id: UUID, reason: str) -> Any | None: ...

    def revoke_user_sessions(self, connection: Any, *, user_id: UUID) -> int: ...


def _as_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise AdminAccessInternalError("database timestamp is invalid")
    if value.tzinfo is None:
        raise AdminAccessInternalError("database timestamp has no timezone")
    return value.astimezone(_UTC)


def _timestamp(value: Any) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    raise AdminAccessInternalError("database identifier is invalid")


def _revision(*parts: Any) -> int:
    values: list[str] = []
    for part in parts:
        if isinstance(part, datetime):
            values.append(_timestamp(part))
        elif isinstance(part, UUID):
            values.append(str(part))
        else:
            values.append(json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    digest = hashlib.sha256("|".join(values).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _request_fingerprint(operation: str, payload: Any) -> str:
    encoded = json.dumps(
        {"operation": operation, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encode_signed(value: dict[str, Any], secret: bytes) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret, body, hashlib.sha256).digest()[:18]
    return base64.urlsafe_b64encode(body + b"." + signature).decode("ascii").rstrip("=")


def _decode_signed(token: str, secret: bytes) -> dict[str, Any]:
    if not isinstance(token, str) or not _PUBLIC_ID_PATTERN.fullmatch(token):
        raise AdminAccessNotFound()
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        body, signature = raw.rsplit(b".", 1)
        expected = hmac.new(secret, body, hashlib.sha256).digest()[:18]
        if not hmac.compare_digest(signature, expected):
            raise AdminAccessNotFound()
        value = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdminAccessNotFound() from exc
    if not isinstance(value, dict):
        raise AdminAccessNotFound()
    return value


def _encode_public_id(namespace: str, object_id: UUID, secret: bytes) -> str:
    return _encode_signed({"namespace": namespace, "id": str(object_id)}, secret)


def _decode_public_id(namespace: str, token: str, secret: bytes) -> UUID:
    value = _decode_signed(token, secret)
    if value.get("namespace") != namespace:
        raise AdminAccessNotFound()
    try:
        return UUID(str(value["id"]))
    except (KeyError, ValueError) as exc:
        raise AdminAccessNotFound() from exc


class PostgresAdminAccessStorage:
    """Reads and writes only the existing canonical account tables."""

    def require_admin(self, connection: Any, context: AdminAccessContext, now: datetime) -> None:
        row = connection.execute(
            """
            SELECT actor_user.role, actor_user.status, active_session.status, active_session.expires_at
            FROM openclaw_account.users AS actor_user
            JOIN openclaw_account.sessions AS active_session
              ON active_session.user_id = actor_user.id
            WHERE actor_user.id = %s AND active_session.id = %s
            FOR UPDATE OF actor_user, active_session
            """,
            (context.actor_user_id, context.actor_session_id),
        ).fetchone()
        if row is None or row[2] != "active" or _as_utc(row[3]) <= now:
            raise AdminAccessUnauthorized()
        if row[0] != "admin" or row[1] != "active":
            raise AdminAccessForbidden()

    def find_idempotency(self, connection: Any, actor_user_id: UUID, operation: str, key: str) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT metadata
            FROM openclaw_account.admin_audit
            WHERE actor_user_id = %s
              AND action = %s
              AND metadata ->> 'idempotencyKey' = %s
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (actor_user_id, operation, key),
        ).fetchone()
        if row is None:
            return None
        metadata = row[0]
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError as exc:
                raise AdminAccessInternalError("administrator audit metadata is invalid") from exc
        if not isinstance(metadata, dict):
            raise AdminAccessInternalError("administrator audit metadata is invalid")
        return metadata

    def save_audit(self, connection: Any, **record: Any) -> None:
        connection.execute(
            """
            INSERT INTO openclaw_account.admin_audit(
                id, actor_user_id, actor_session_id, action, target_user_id, reason, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                uuid4(),
                record["actorUserId"],
                record["actorSessionId"],
                record["operation"],
                record.get("targetUserId"),
                record["reason"],
                json.dumps(record["metadata"], ensure_ascii=False, separators=(",", ":")),
            ),
        )

    def affiliate_users(self, connection: Any, *, search: str, position: _CursorPosition | None, limit: int) -> list[Any]:
        pattern = f"%{search}%"
        if position is None:
            rows = connection.execute(
                """
                SELECT profile.user_id, account_user.username, profile.signup_enabled,
                       profile.signup_quota, profile.signup_used, account_user.status,
                       profile.updated_at, account_user.created_at
                FROM openclaw_account.affiliate_profiles AS profile
                JOIN openclaw_account.users AS account_user ON account_user.id = profile.user_id
                WHERE (%s = '' OR account_user.username ILIKE %s)
                ORDER BY account_user.created_at DESC, account_user.id ASC
                LIMIT %s
                """,
                (search, pattern, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT profile.user_id, account_user.username, profile.signup_enabled,
                       profile.signup_quota, profile.signup_used, account_user.status,
                       profile.updated_at, account_user.created_at
                FROM openclaw_account.affiliate_profiles AS profile
                JOIN openclaw_account.users AS account_user ON account_user.id = profile.user_id
                WHERE (%s = '' OR account_user.username ILIKE %s)
                  AND (
                    account_user.created_at < %s
                    OR (account_user.created_at = %s AND account_user.id > %s)
                  )
                ORDER BY account_user.created_at DESC, account_user.id ASC
                LIMIT %s
                """,
                (search, pattern, position.created_at, position.created_at, position.object_id, limit),
            ).fetchall()
        return list(rows)

    def affiliate_user(self, connection: Any, user_id: UUID, *, lock: bool) -> Any | None:
        suffix = " FOR UPDATE" if lock else ""
        return connection.execute(
            f"""
            SELECT profile.user_id, account_user.username, profile.signup_enabled,
                   profile.signup_quota, profile.signup_used, account_user.status,
                   profile.updated_at, account_user.created_at
            FROM openclaw_account.affiliate_profiles AS profile
            JOIN openclaw_account.users AS account_user ON account_user.id = profile.user_id
            WHERE profile.user_id = %s
            {suffix}
            """,
            (user_id,),
        ).fetchone()

    def update_affiliate_user(
        self,
        connection: Any,
        *,
        user_id: UUID,
        affiliate_enabled: bool,
        invitation_quota: int,
    ) -> Any | None:
        connection.execute(
            """
            UPDATE openclaw_account.affiliate_profiles
            SET signup_enabled = %s, signup_quota = %s, updated_at = now()
            WHERE user_id = %s
            """,
            (affiliate_enabled, invitation_quota, user_id),
        )
        return self.affiliate_user(connection, user_id, lock=True)

    def admission_batches(self, connection: Any, *, position: _CursorPosition | None, limit: int) -> list[Any]:
        if position is None:
            rows = connection.execute(
                """
                SELECT batch.id, batch.name, batch.status, batch.code_count,
                       COUNT(code.id) FILTER (WHERE code.status = 'consumed'),
                       batch.created_at, batch.disabled_at
                FROM openclaw_account.admission_batches AS batch
                LEFT JOIN openclaw_account.admission_codes AS code ON code.batch_id = batch.id
                GROUP BY batch.id
                ORDER BY batch.created_at DESC, batch.id ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT batch.id, batch.name, batch.status, batch.code_count,
                       COUNT(code.id) FILTER (WHERE code.status = 'consumed'),
                       batch.created_at, batch.disabled_at
                FROM openclaw_account.admission_batches AS batch
                LEFT JOIN openclaw_account.admission_codes AS code ON code.batch_id = batch.id
                WHERE batch.created_at < %s
                   OR (batch.created_at = %s AND batch.id > %s)
                GROUP BY batch.id
                ORDER BY batch.created_at DESC, batch.id ASC
                LIMIT %s
                """,
                (position.created_at, position.created_at, position.object_id, limit),
            ).fetchall()
        return list(rows)

    def admission_batch(self, connection: Any, batch_id: UUID, *, lock: bool) -> Any | None:
        if lock:
            batch = connection.execute(
                """
                SELECT id, name, status, code_count, created_at, disabled_at
                FROM openclaw_account.admission_batches
                WHERE id = %s
                FOR UPDATE
                """,
                (batch_id,),
            ).fetchone()
            if batch is None:
                return None
            used_count = connection.execute(
                """
                SELECT COUNT(*) FILTER (WHERE status = 'consumed')
                FROM openclaw_account.admission_codes
                WHERE batch_id = %s
                """,
                (batch_id,),
            ).fetchone()[0]
            return (*batch[:4], int(used_count), *batch[4:])
        return connection.execute(
            """
            SELECT batch.id, batch.name, batch.status, batch.code_count,
                   COUNT(code.id) FILTER (WHERE code.status = 'consumed'),
                   batch.created_at, batch.disabled_at
            FROM openclaw_account.admission_batches AS batch
            LEFT JOIN openclaw_account.admission_codes AS code ON code.batch_id = batch.id
            WHERE batch.id = %s
            GROUP BY batch.id
            """,
            (batch_id,),
        ).fetchone()

    def update_admission_batch_disabled(self, connection: Any, *, batch_id: UUID) -> Any | None:
        connection.execute(
            """
            UPDATE openclaw_account.admission_batches
            SET status = 'disabled', disabled_at = now()
            WHERE id = %s AND status = 'active'
            """,
            (batch_id,),
        )
        return self.admission_batch(connection, batch_id, lock=True)

    def registration_policy(self, connection: Any, *, lock: bool) -> Any | None:
        suffix = " FOR UPDATE" if lock else " FOR SHARE"
        return connection.execute(
            f"SELECT mode, updated_at FROM openclaw_account.registration_policy WHERE singleton {suffix}"
        ).fetchone()

    def update_registration_policy(self, connection: Any, *, mode: str, actor_user_id: UUID, reason: str) -> Any | None:
        return connection.execute(
            """
            UPDATE openclaw_account.registration_policy
            SET mode = %s, updated_by_user_id = %s, reason = %s, updated_at = now()
            WHERE singleton
            RETURNING mode, updated_at
            """,
            (mode, actor_user_id, reason),
        ).fetchone()

    def revoke_user_sessions(self, connection: Any, *, user_id: UUID) -> int:
        cursor = connection.execute(
            """
            UPDATE openclaw_account.sessions
            SET status = 'revoked', revoked_at = now()
            WHERE user_id = %s AND status = 'active'
            """,
            (user_id,),
        )
        return int(cursor.rowcount)


class AdminAccessService:
    """Expose B11's IF2 DTOs while retaining the account schema as authority."""

    def __init__(
        self,
        database_or_factory: Any,
        *,
        public_id_secret: bytes,
        cursor_secret: bytes,
        storage: AdminAccessStorage | None = None,
        registration_service: Any | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if len(public_id_secret) < 16 or len(cursor_secret) < 16:
            raise ValueError("B11 secrets must be at least 16 bytes")
        if hasattr(database_or_factory, "connect"):
            self._connection_factory: ConnectionFactory = database_or_factory.connect
        elif callable(database_or_factory):
            self._connection_factory = database_or_factory
        else:
            raise TypeError("B11 requires an AccountDatabase or connection factory")
        self._public_id_secret = bytes(public_id_secret)
        self._cursor_secret = hashlib.sha256(bytes(cursor_secret)).digest()
        self._storage = storage or PostgresAdminAccessStorage()
        self._registration_service = registration_service
        self._now = now or (lambda: datetime.now(_UTC))

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, AdminAccessError):
            return {"error": {"code": error.code, "message": error.message, "field": error.field}}
        return {"error": {"code": "internal_error", "message": "administrator access data is unavailable", "field": None}}

    @staticmethod
    def error_status(error: BaseException) -> int:
        return error.status if isinstance(error, AdminAccessError) else 500

    def public_user_id(self, user_id: UUID) -> str:
        return _encode_public_id("admin-user", _uuid(user_id), self._public_id_secret)

    def public_batch_id(self, batch_id: UUID) -> str:
        return _encode_public_id("admin-batch", _uuid(batch_id), self._public_id_secret)

    def list_admin_affiliate_users(
        self,
        context: AdminAccessContext | Any,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        search: str | None = None,
    ) -> dict[str, Any]:
        checked = self._context(context)
        size = self._page_size(page_size)
        normalized_search = self._search(search)
        position = self._cursor(cursor, resource="affiliate-users", search=normalized_search) if cursor else None
        with self._connection_factory() as connection:
            self._storage.require_admin(connection, checked, self._now())
            rows = self._storage.affiliate_users(
                connection,
                search=normalized_search,
                position=position,
                limit=size + 1,
            )
        visible = rows[:size]
        items = [self._affiliate_projection(row) for row in visible]
        next_cursor = None
        if len(rows) > size:
            last = visible[-1]
            next_cursor = self._encode_cursor(
                resource="affiliate-users",
                search=normalized_search,
                created_at=_as_utc(last[7]),
                object_id=_uuid(last[0]),
            )
        revision = 0 if not visible else max(self._affiliate_revision(row) for row in visible)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": revision,
            "items": items,
            "nextCursor": next_cursor,
        }

    def update_admin_affiliate_user(
        self,
        context: AdminAccessContext | Any,
        user_id: str,
        *,
        affiliate_enabled: bool,
        invitation_quota: int,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        target = _decode_public_id("admin-user", user_id, self._public_id_secret)
        self._bool(affiliate_enabled, "affiliateEnabled")
        self._quota(invitation_quota)
        normalized_reason = self._reason(reason)
        expected = self._expected_revision(expected_revision)
        key = self._idempotency_key(idempotency_key)
        operation = "update_admin_affiliate_user"
        payload = {
            "userId": user_id,
            "affiliateEnabled": affiliate_enabled,
            "invitationQuota": invitation_quota,
            "reason": normalized_reason,
            "expectedRevision": expected,
        }
        fingerprint = _request_fingerprint(operation, payload)
        with self._connection_factory() as connection:
            replay = self._start_mutation(connection, checked, operation, key, fingerprint)
            if replay is not None:
                return replay
            row = self._storage.affiliate_user(connection, target, lock=True)
            if row is None:
                raise AdminAccessNotFound()
            self._check_revision(expected, self._affiliate_revision(row))
            if row[4] > invitation_quota:
                raise AdminAccessInvalidRequest("invitationQuota cannot be lower than usedQuota", field="invitationQuota")
            updated = self._storage.update_affiliate_user(
                connection,
                user_id=target,
                affiliate_enabled=affiliate_enabled,
                invitation_quota=invitation_quota,
            )
            if updated is None:
                raise AdminAccessInternalError("affiliate profile readback is missing")
            response = {
                "schemaVersion": SCHEMA_VERSION,
                "revision": self._affiliate_revision(updated),
                "user": self._affiliate_projection(updated),
            }
            self._finish_mutation(
                connection,
                checked,
                operation=operation,
                key=key,
                fingerprint=fingerprint,
                reason=normalized_reason,
                target_user_id=target,
                response=response,
            )
            return response

    def list_admin_admission_batches(
        self,
        context: AdminAccessContext | Any,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        checked = self._context(context)
        size = self._page_size(page_size)
        position = self._cursor(cursor, resource="admission-batches", search="") if cursor else None
        with self._connection_factory() as connection:
            self._storage.require_admin(connection, checked, self._now())
            rows = self._storage.admission_batches(connection, position=position, limit=size + 1)
        visible = rows[:size]
        items = [self._batch_projection(row) for row in visible]
        next_cursor = None
        if len(rows) > size:
            last = visible[-1]
            next_cursor = self._encode_cursor(
                resource="admission-batches",
                search="",
                created_at=_as_utc(last[5]),
                object_id=_uuid(last[0]),
            )
        revision = 0 if not visible else max(self._batch_revision(row) for row in visible)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": revision,
            "items": items,
            "nextCursor": next_cursor,
        }

    def create_admin_admission_batch(
        self,
        context: AdminAccessContext | Any,
        *,
        name: str,
        code_count: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        normalized_name = name.strip() if isinstance(name, str) else ""
        if not 1 <= len(normalized_name) <= 120:
            raise AdminAccessInvalidRequest("name must contain 1 to 120 characters", field="name")
        if type(code_count) is not int or not 1 <= code_count <= 1000:
            raise AdminAccessInvalidRequest("codeCount must be between 1 and 1000", field="codeCount")
        normalized_reason = self._reason(reason)
        key = self._idempotency_key(idempotency_key)
        operation = "create_admin_admission_batch"
        payload = {"name": normalized_name, "codeCount": code_count, "reason": normalized_reason}
        fingerprint = _request_fingerprint(operation, payload)
        with self._connection_factory() as connection:
            replay = self._start_mutation(connection, checked, operation, key, fingerprint)
            if replay is not None:
                return replay
        if self._registration_service is None:
            raise AdminAccessInternalError("registration service is unavailable")
        try:
            issue = self._registration_service.admin_create_admission_batch(
                actor_user_id=checked.actor_user_id,
                actor_session_id=checked.actor_session_id,
                name=normalized_name,
                code_count=code_count,
                reason=normalized_reason,
            )
            batch_id = _uuid(getattr(issue, "batch_id", None))
        except AdminAccessError:
            raise
        except Exception as exc:
            raise AdminAccessInternalError() from exc
        with self._connection_factory() as connection:
            self._storage.require_admin(connection, checked, self._now())
            row = self._storage.admission_batch(connection, batch_id, lock=False)
            if row is None:
                raise AdminAccessInternalError("admission batch readback is missing")
            response = {
                "schemaVersion": SCHEMA_VERSION,
                "revision": self._batch_revision(row),
                "batch": self._batch_projection(row),
            }
            self._finish_mutation(
                connection,
                checked,
                operation=operation,
                key=key,
                fingerprint=fingerprint,
                reason=normalized_reason,
                target_user_id=None,
                response=response,
                metadata_extra={"batchId": str(batch_id)},
            )
            return response

    def disable_admin_admission_batch(
        self,
        context: AdminAccessContext | Any,
        batch_id: str,
        *,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        target = _decode_public_id("admin-batch", batch_id, self._public_id_secret)
        normalized_reason = self._reason(reason)
        expected = self._expected_revision(expected_revision)
        key = self._idempotency_key(idempotency_key)
        operation = "disable_admin_admission_batch"
        payload = {"batchId": batch_id, "reason": normalized_reason, "expectedRevision": expected}
        fingerprint = _request_fingerprint(operation, payload)
        with self._connection_factory() as connection:
            replay = self._start_mutation(connection, checked, operation, key, fingerprint)
            if replay is not None:
                return replay
            row = self._storage.admission_batch(connection, target, lock=True)
            if row is None or row[2] != "active":
                raise AdminAccessNotFound()
            self._check_revision(expected, self._batch_revision(row))
            updated = self._storage.update_admission_batch_disabled(connection, batch_id=target)
            if updated is None:
                raise AdminAccessInternalError("admission batch readback is missing")
            now = self._now()
            response = {
                "schemaVersion": SCHEMA_VERSION,
                "revision": self._batch_revision(updated),
                "ok": True,
                "updatedAt": _timestamp(now),
            }
            self._finish_mutation(
                connection,
                checked,
                operation=operation,
                key=key,
                fingerprint=fingerprint,
                reason=normalized_reason,
                target_user_id=None,
                response=response,
                metadata_extra={"batchId": str(target)},
            )
            return response

    def get_admin_registration_policy(self, context: AdminAccessContext | Any) -> dict[str, Any]:
        checked = self._context(context)
        with self._connection_factory() as connection:
            self._storage.require_admin(connection, checked, self._now())
            row = self._storage.registration_policy(connection, lock=False)
        if row is None:
            raise AdminAccessInternalError("registration policy singleton is missing")
        mode, updated_at = self._policy_values(row)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": self._policy_revision(row),
            "policy": {"mode": self._external_mode(mode), "revision": self._policy_revision(row), "updatedAt": _timestamp(updated_at)},
        }

    def update_admin_registration_policy(
        self,
        context: AdminAccessContext | Any,
        *,
        mode: str,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        if mode not in {"open", "invite_only", "closed"}:
            raise AdminAccessInvalidRequest("mode is invalid", field="mode")
        normalized_reason = self._reason(reason)
        expected = self._expected_revision(expected_revision)
        key = self._idempotency_key(idempotency_key)
        operation = "update_admin_registration_policy"
        payload = {"mode": mode, "reason": normalized_reason, "expectedRevision": expected}
        fingerprint = _request_fingerprint(operation, payload)
        with self._connection_factory() as connection:
            replay = self._start_mutation(connection, checked, operation, key, fingerprint)
            if replay is not None:
                return replay
            row = self._storage.registration_policy(connection, lock=True)
            if row is None:
                raise AdminAccessInternalError("registration policy singleton is missing")
            self._check_revision(expected, self._policy_revision(row))
            stored_mode = "controlled" if mode == "invite_only" else mode
            updated = self._storage.update_registration_policy(
                connection,
                mode=stored_mode,
                actor_user_id=checked.actor_user_id,
                reason=normalized_reason,
            )
            if updated is None:
                raise AdminAccessInternalError("registration policy readback is missing")
            response_mode, updated_at = self._policy_values(updated)
            revision = self._policy_revision(updated)
            response = {
                "schemaVersion": SCHEMA_VERSION,
                "revision": revision,
                "policy": {"mode": self._external_mode(response_mode), "revision": revision, "updatedAt": _timestamp(updated_at)},
            }
            self._finish_mutation(
                connection,
                checked,
                operation=operation,
                key=key,
                fingerprint=fingerprint,
                reason=normalized_reason,
                target_user_id=None,
                response=response,
            )
            return response

    def revoke_admin_user_sessions(
        self,
        context: AdminAccessContext | Any,
        user_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        target = _decode_public_id("admin-user", user_id, self._public_id_secret)
        normalized_reason = self._reason(reason)
        key = self._idempotency_key(idempotency_key)
        operation = "revoke_admin_user_sessions"
        payload = {"userId": user_id, "reason": normalized_reason}
        fingerprint = _request_fingerprint(operation, payload)
        with self._connection_factory() as connection:
            replay = self._start_mutation(connection, checked, operation, key, fingerprint)
            if replay is not None:
                return replay
            if self._storage.affiliate_user(connection, target, lock=True) is None:
                raise AdminAccessNotFound()
            revoked = self._storage.revoke_user_sessions(connection, user_id=target)
            now = self._now()
            response = {
                "schemaVersion": SCHEMA_VERSION,
                "revision": _revision("sessions", target, revoked, now),
                "ok": True,
                "updatedAt": _timestamp(now),
            }
            self._finish_mutation(
                connection,
                checked,
                operation=operation,
                key=key,
                fingerprint=fingerprint,
                reason=normalized_reason,
                target_user_id=target,
                response=response,
                metadata_extra={"revokedSessions": revoked},
            )
            return response

    def _context(self, value: AdminAccessContext | Any) -> AdminAccessContext:
        if value is None:
            raise AdminAccessUnauthorized()
        if isinstance(value, AdminAccessContext):
            context = value
        else:
            try:
                context = AdminAccessContext(
                    actor_user_id=UUID(str(getattr(value, "user_id"))),
                    actor_session_id=UUID(str(getattr(value, "session_id"))),
                    role=str(getattr(value, "role")),
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise AdminAccessUnauthorized() from exc
        if context.role != "admin":
            raise AdminAccessForbidden()
        return context

    @staticmethod
    def _page_size(value: int) -> int:
        if type(value) is not int or not 1 <= value <= MAX_PAGE_SIZE:
            raise AdminAccessInvalidRequest("pageSize must be between 1 and 100", field="pageSize")
        return value

    @staticmethod
    def _search(value: str | None) -> str:
        if value is None:
            return ""
        if not isinstance(value, str) or len(value) > 200:
            raise AdminAccessInvalidRequest("search is invalid", field="search")
        return value.strip()

    @staticmethod
    def _reason(value: str) -> str:
        if not isinstance(value, str):
            raise AdminAccessInvalidRequest("reason is required", field="reason")
        normalized = value.strip()
        if not 1 <= len(normalized) <= 500:
            raise AdminAccessInvalidRequest("reason is required", field="reason")
        return normalized

    @staticmethod
    def _idempotency_key(value: str) -> str:
        return idempotency_key(
            value,
            error=lambda: AdminAccessInvalidRequest("Idempotency-Key is invalid", field="idempotencyKey"),
            policy=IF2_KEY,
        )

    @staticmethod
    def _expected_revision(value: int) -> int:
        if type(value) is not int or value < 0:
            raise AdminAccessInvalidRequest("expectedRevision is invalid", field="expectedRevision")
        return value

    @staticmethod
    def _bool(value: bool, field: str) -> None:
        if type(value) is not bool:
            raise AdminAccessInvalidRequest(f"{field} is invalid", field=field)

    @staticmethod
    def _quota(value: int) -> None:
        if type(value) is not int or not 0 <= value <= 1_000_000:
            raise AdminAccessInvalidRequest("invitationQuota is invalid", field="invitationQuota")

    def _cursor(self, token: str, *, resource: str, search: str) -> _CursorPosition:
        try:
            value = _decode_signed(token, self._cursor_secret)
        except AdminAccessNotFound as exc:
            raise AdminAccessInvalidRequest("cursor is invalid", field="cursor") from exc
        if value.get("resource") != resource or value.get("search") != search:
            raise AdminAccessInvalidRequest("cursor does not match this query", field="cursor")
        try:
            created_at = datetime.fromisoformat(str(value["createdAt"]).replace("Z", "+00:00"))
            object_id = UUID(str(value["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AdminAccessInvalidRequest("cursor is invalid", field="cursor") from exc
        return _CursorPosition(resource, search, _as_utc(created_at), object_id)

    def _encode_cursor(self, *, resource: str, search: str, created_at: datetime, object_id: UUID) -> str:
        return _encode_signed(
            {"resource": resource, "search": search, "createdAt": _timestamp(created_at), "id": str(object_id)},
            self._cursor_secret,
        )

    def _start_mutation(
        self,
        connection: Any,
        context: AdminAccessContext,
        operation: str,
        key: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        self._storage.require_admin(connection, context, self._now())
        existing = self._storage.find_idempotency(connection, context.actor_user_id, operation, key)
        if existing is None:
            return None
        if existing.get("requestFingerprint") != fingerprint:
            raise AdminAccessIdempotencyConflict()
        response = existing.get("response")
        if not isinstance(response, dict):
            raise AdminAccessInternalError("idempotent response is missing")
        return response

    def _finish_mutation(
        self,
        connection: Any,
        context: AdminAccessContext,
        *,
        operation: str,
        key: str,
        fingerprint: str,
        reason: str,
        target_user_id: UUID | None,
        response: dict[str, Any],
        metadata_extra: dict[str, Any] | None = None,
    ) -> None:
        metadata = {
            "idempotencyKey": key,
            "requestFingerprint": fingerprint,
            "response": response,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        self._storage.save_audit(
            connection,
            actorUserId=context.actor_user_id,
            actorSessionId=context.actor_session_id,
            operation=operation,
            targetUserId=target_user_id,
            reason=reason,
            metadata=metadata,
        )

    @staticmethod
    def _check_revision(expected: int, current: int) -> None:
        if expected != current:
            raise AdminAccessRevisionConflict()

    @staticmethod
    def _affiliate_revision(row: Any) -> int:
        if not isinstance(row, (tuple, list)) or len(row) != 8:
            raise AdminAccessInternalError("affiliate user row shape is invalid")
        return _revision("affiliate-user", _uuid(row[0]), _as_utc(row[6]))

    def _affiliate_projection(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 8:
            raise AdminAccessInternalError("affiliate user row shape is invalid")
        user_id, display_name, enabled, quota, used, status, updated_at, _created_at = row
        if not isinstance(display_name, str) or not display_name.strip() or type(enabled) is not bool:
            raise AdminAccessInternalError("affiliate user database contract is invalid")
        if type(quota) is not int or quota < 0 or type(used) is not int or used < 0 or used > quota:
            raise AdminAccessInternalError("affiliate quota database contract is invalid")
        if not isinstance(status, str) or not status.strip():
            raise AdminAccessInternalError("affiliate user status is invalid")
        return {
            "publicUserId": self.public_user_id(_uuid(user_id)),
            "displayName": display_name,
            "affiliateEnabled": enabled,
            "invitationQuota": quota,
            "usedQuota": used,
            "status": status,
            "updatedAt": _timestamp(updated_at),
        }

    @staticmethod
    def _batch_revision(row: Any) -> int:
        if not isinstance(row, (tuple, list)) or len(row) != 7:
            raise AdminAccessInternalError("admission batch row shape is invalid")
        return _revision("admission-batch", _uuid(row[0]), _as_utc(row[5]), row[2], row[4])

    def _batch_projection(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 7:
            raise AdminAccessInternalError("admission batch row shape is invalid")
        batch_id, name, status, code_count, used_count, created_at, _disabled_at = row
        if not isinstance(name, str) or not name.strip() or not isinstance(status, str) or not status.strip():
            raise AdminAccessInternalError("admission batch database contract is invalid")
        if type(code_count) is not int or code_count < 0 or type(used_count) is not int or not 0 <= used_count <= code_count:
            raise AdminAccessInternalError("admission batch counts are invalid")
        return {
            "batchId": self.public_batch_id(_uuid(batch_id)),
            "name": name,
            "status": status,
            "codeCount": code_count,
            "usedCount": used_count,
            "expiresAt": None,
            "createdAt": _timestamp(created_at),
        }

    @staticmethod
    def _policy_values(row: Any) -> tuple[str, datetime]:
        if not isinstance(row, (tuple, list)) or len(row) != 2 or not isinstance(row[0], str):
            raise AdminAccessInternalError("registration policy row shape is invalid")
        return row[0], _as_utc(row[1])

    def _policy_revision(self, row: Any) -> int:
        mode, updated_at = self._policy_values(row)
        return _revision("registration-policy", mode, updated_at)

    @staticmethod
    def _external_mode(mode: str) -> str:
        if mode == "controlled":
            return "invite_only"
        if mode not in {"open", "invite_only", "closed"}:
            raise AdminAccessInternalError("registration policy mode is invalid")
        return mode
