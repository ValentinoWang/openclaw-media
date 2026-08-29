from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from .foundation import IF2_KEY, idempotency_key


SCHEMA_VERSION = "media_web_business_pages_v2"
MAX_RECONCILIATION_ROWS = 1000
_UTC = timezone.utc


class AdminUpstreamsError(RuntimeError):
    status = 500

    def __init__(self, code: str, message: str, *, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class AdminUpstreamsUnauthorized(AdminUpstreamsError):
    def __init__(self) -> None:
        super().__init__("authentication_required", "administrator authentication is required", status=401)


class AdminUpstreamsForbidden(AdminUpstreamsError):
    def __init__(self, message: str = "administrator permission is required") -> None:
        super().__init__("forbidden", message, status=403)


class AdminUpstreamsNotFound(AdminUpstreamsError):
    def __init__(self) -> None:
        super().__init__("resource_not_found", "resource was not found", status=404)


class AdminUpstreamsInvalidRequest(AdminUpstreamsError):
    def __init__(self, message: str = "invalid upstream request") -> None:
        super().__init__("invalid_request", message, status=400)


class AdminUpstreamsRevisionConflict(AdminUpstreamsError):
    def __init__(self) -> None:
        super().__init__("revision_conflict", "resource revision has changed", status=409)


class AdminUpstreamsIdempotencyConflict(AdminUpstreamsError):
    def __init__(self) -> None:
        super().__init__("idempotency_conflict", "idempotency key is bound to another request", status=409)


class AdminUpstreamsUnavailable(AdminUpstreamsError):
    def __init__(self, message: str = "upstream service data is unavailable") -> None:
        super().__init__("upstream_unavailable", message, status=503)


@dataclass(frozen=True)
class AdminUpstreamsContext:
    actor_user_id: UUID
    actor_session_id: UUID
    role: str = "admin"
    maintainer: bool = False

    @property
    def is_maintainer(self) -> bool:
        return self.maintainer


AdminUpstreamContext = AdminUpstreamsContext


class ConnectionFactory(Protocol):
    def __call__(self) -> AbstractContextManager[Any]: ...


class AdminUpstreamsStorage(Protocol):
    def require_admin(self, connection: Any, context: AdminUpstreamsContext, now: datetime) -> None: ...

    def find_idempotency(
        self,
        connection: Any,
        actor_user_id: UUID,
        operation: str,
        key: str,
    ) -> dict[str, Any] | None: ...

    def save_audit(self, connection: Any, **record: Any) -> None: ...


def _as_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise AdminUpstreamsUnavailable("upstream timestamp is invalid")
    if value.tzinfo is None:
        raise AdminUpstreamsUnavailable("upstream timestamp has no timezone")
    return value.astimezone(_UTC)


def _timestamp(value: Any) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value.strip():
        raise AdminUpstreamsUnavailable("upstream sync timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdminUpstreamsUnavailable("upstream sync timestamp is invalid") from exc
    return _as_utc(parsed)


class PostgresAdminUpstreamsStorage:
    """Uses the canonical account session and immutable admin audit tables."""

    def require_admin(self, connection: Any, context: AdminUpstreamsContext, now: datetime) -> None:
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
            raise AdminUpstreamsUnauthorized()
        if row[0] != "admin" or row[1] != "active":
            raise AdminUpstreamsForbidden()

    def find_idempotency(
        self,
        connection: Any,
        actor_user_id: UUID,
        operation: str,
        key: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT metadata
            FROM openclaw_account.admin_audit
            WHERE actor_user_id = %s
              AND action = %s
              AND metadata ->> 'idempotencyKey' = %s
            ORDER BY created_at DESC, id DESC
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
                raise AdminUpstreamsUnavailable("administrator audit metadata is invalid") from exc
        if not isinstance(metadata, dict):
            raise AdminUpstreamsUnavailable("administrator audit metadata is invalid")
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


class AdminUpstreamsService:
    """Expose B14 as one redacted read model over the existing upstream services."""

    _RECONCILE_OPERATION = "media_b14_reconcile"
    _ROTATE_OPERATION = "media_b14_rotate"
    _REVOKE_OPERATION = "media_b14_revoke"

    def __init__(
        self,
        database_or_factory: Any,
        *,
        upstream_gateway: Any | None = None,
        credential_health: Callable[[], Mapping[str, Any]] | None = None,
        reconciliation_queue: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        reconcile_operation: Callable[[str], Mapping[str, Any]] | None = None,
        rotate_credential: Callable[[], Mapping[str, Any]] | None = None,
        revoke_credential: Callable[[], Mapping[str, Any]] | None = None,
        storage: AdminUpstreamsStorage | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if hasattr(database_or_factory, "connect"):
            self._connection_factory: ConnectionFactory = database_or_factory.connect
        elif callable(database_or_factory):
            self._connection_factory = database_or_factory
        else:
            raise TypeError("B14 requires an AccountDatabase or connection factory")

        source = upstream_gateway
        self._credential_health = self._callback(credential_health, source, "credential_health")
        self._reconciliation_queue = self._callback(reconciliation_queue, source, "reconciliation_queue")
        self._reconcile_operation = self._callback(reconcile_operation, source, "reconcile_operation")
        self._rotate_credential = self._callback(rotate_credential, source, "rotate_credential")
        self._revoke_credential = self._callback(revoke_credential, source, "revoke_credential")
        self._storage = storage or PostgresAdminUpstreamsStorage()
        self._now = now or (lambda: datetime.now(_UTC))

    @staticmethod
    def _callback(
        supplied: Callable[..., Any] | None,
        source: Any | None,
        name: str,
    ) -> Callable[..., Any]:
        callback = supplied if supplied is not None else getattr(source, name, None)
        if not callable(callback):
            raise TypeError(f"B14 upstream callback is required: {name}")
        return callback

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, AdminUpstreamsError):
            return {"error": {"code": error.code, "message": error.message}}
        return {"error": {"code": "internal_error", "message": "upstream service data is unavailable"}}

    @staticmethod
    def error_status(error: BaseException) -> int:
        return error.status if isinstance(error, AdminUpstreamsError) else 500

    def get_admin_upstreams(self, context: AdminUpstreamsContext | Any) -> dict[str, Any]:
        checked = self._context(context)
        with self._connection_factory() as connection:
            self._authorize(connection, checked)
        return self._read_response()

    def reconcile_admin_billing_operation(
        self,
        context: AdminUpstreamsContext | Any,
        operation_id: str,
        *,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        normalized_reason = self._reason(reason)
        expected = self._expected_revision(expected_revision)
        key = self._idempotency_key(idempotency_key)
        target = self._operation_id(operation_id)
        operation = self._RECONCILE_OPERATION
        fingerprint = self._fingerprint(operation, target, normalized_reason, expected)

        with self._connection_factory() as connection:
            replay = self._start_mutation(connection, checked, operation, key, fingerprint)
            if replay is not None:
                return replay
            before = self._read_response()
            self._check_revision(expected, before["revision"])
            try:
                self._reconcile_operation(str(target))
            except AdminUpstreamsError:
                raise
            except Exception as exc:
                raise AdminUpstreamsUnavailable("billing reconciliation is unavailable") from exc
            after = self._read_response()
            response = {
                "schemaVersion": SCHEMA_VERSION,
                "revision": after["revision"],
                "ok": True,
                "updatedAt": _timestamp(self._now()),
            }
            self._finish_mutation(
                connection,
                checked,
                operation=operation,
                key=key,
                fingerprint=fingerprint,
                reason=normalized_reason,
                response=response,
            )
            return response

    def rotate_admin_upstream_credential(
        self,
        context: AdminUpstreamsContext | Any,
        *,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._credential_mutation(
            context,
            operation=self._ROTATE_OPERATION,
            reason=reason,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            callback=self._rotate_credential,
        )

    def revoke_admin_upstream_credential(
        self,
        context: AdminUpstreamsContext | Any,
        *,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._credential_mutation(
            context,
            operation=self._REVOKE_OPERATION,
            reason=reason,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            callback=self._revoke_credential,
        )

    def _credential_mutation(
        self,
        context: AdminUpstreamsContext | Any,
        *,
        operation: str,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
        callback: Callable[[], Mapping[str, Any]],
    ) -> dict[str, Any]:
        checked = self._context(context)
        normalized_reason = self._reason(reason)
        expected = self._expected_revision(expected_revision)
        key = self._idempotency_key(idempotency_key)
        fingerprint = self._fingerprint(operation, "", normalized_reason, expected)

        with self._connection_factory() as connection:
            self._authorize(connection, checked, require_maintainer=True)
            replay = self._find_replay(connection, checked, operation, key, fingerprint)
            if replay is not None:
                return replay
            before = self._read_response()
            self._check_revision(expected, before["revision"])
            try:
                readback = callback()
            except AdminUpstreamsError:
                raise
            except Exception as exc:
                raise AdminUpstreamsUnavailable("upstream credential operation is unavailable") from exc
            if not isinstance(readback, Mapping):
                raise AdminUpstreamsUnavailable("upstream credential readback is invalid")
            try:
                live_health = self._credential_health()
            except Exception:
                live_health = readback
            after = self._read_response(health_override=live_health, fallback_summary=before["summary"])
            self._finish_mutation(
                connection,
                checked,
                operation=operation,
                key=key,
                fingerprint=fingerprint,
                reason=normalized_reason,
                response=after,
            )
            return after

    def _read_response(
        self,
        *,
        health_override: Mapping[str, Any] | None = None,
        fallback_summary: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            health = health_override if health_override is not None else self._credential_health()
            if health_override is not None and fallback_summary is not None:
                health = self._merge_mutation_health(health, fallback_summary)
            queue = self._reconciliation_queue(limit=MAX_RECONCILIATION_ROWS)
            summary = self._project_summary(health, queue)
        except AdminUpstreamsError:
            raise
        except Exception as exc:
            raise AdminUpstreamsUnavailable() from exc
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": summary["revision"],
            "summary": summary,
        }

    @classmethod
    def _merge_mutation_health(
        cls,
        health_value: Mapping[str, Any],
        fallback_summary: Mapping[str, Any],
    ) -> dict[str, Any]:
        health = cls._mapping(health_value, "credential readback")
        status = cls._health_status(health.get("status", health.get("credentialHealth")))
        has_available = "availableAccountCount" in health or "available_accounts" in health
        has_unhealthy = "unhealthyAccountCount" in health or "unhealthy_accounts" in health
        if status == "revoked":
            health.update({"availableAccountCount": 0, "unhealthyAccountCount": 1})
        elif not has_available and not has_unhealthy:
            if status == "revoked":
                health.update({"availableAccountCount": 0, "unhealthyAccountCount": 1})
            else:
                health.update(
                    {
                        "availableAccountCount": fallback_summary["availableAccountCount"],
                        "unhealthyAccountCount": fallback_summary["unhealthyAccountCount"],
                    }
                )
        if not any(name in health for name in ("lastSyncedAt", "last_synced_at", "syncedAt", "synced_at")):
            if fallback_summary.get("lastSyncedAt") is not None:
                health["lastSyncedAt"] = fallback_summary["lastSyncedAt"]
        return health
    @classmethod
    def _project_summary(
        cls,
        health_value: Mapping[str, Any],
        queue_value: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    ) -> dict[str, Any]:
        health = cls._mapping(health_value, "credential health")
        nested_health = health.get("credential")
        if isinstance(nested_health, Mapping):
            health = dict(nested_health)
        status = cls._health_status(health.get("status", health.get("credentialHealth")))
        available, unhealthy = cls._account_counts(health, status)
        rows = cls._queue_rows(queue_value)
        last_synced = cls._last_synced_at(health, rows)
        summary: dict[str, Any] = {
            "availableAccountCount": available,
            "unhealthyAccountCount": unhealthy,
            "credentialHealth": status,
            "pendingReconciliationCount": len(rows),
            "lastSyncedAt": last_synced,
        }
        summary["revision"] = cls._revision(summary)
        return summary

    @staticmethod
    def _mapping(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise AdminUpstreamsUnavailable(f"{label} is invalid")
        return dict(value)

    @staticmethod
    def _health_status(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise AdminUpstreamsUnavailable("credential health status is missing")
        status = value.strip().lower()
        mapped = {
            "active": "healthy",
            "healthy": "healthy",
            "degraded": "degraded",
            "unavailable": "unavailable",
            "inactive": "unavailable",
            "revoked": "revoked",
            "retired": "revoked",
            "unknown": "unknown",
        }.get(status)
        return mapped if mapped is not None else "unknown"

    @classmethod
    def _account_counts(cls, health: Mapping[str, Any], status: str) -> tuple[int, int]:
        accounts = health.get("accounts")
        source = accounts if isinstance(accounts, Mapping) else health
        available_value = cls._first_present(source, "availableAccountCount", "available_accounts")
        unhealthy_value = cls._first_present(source, "unhealthyAccountCount", "unhealthy_accounts")
        if available_value is not None or unhealthy_value is not None:
            if available_value is None or unhealthy_value is None:
                raise AdminUpstreamsUnavailable("credential account aggregate is incomplete")
            return cls._count(available_value), cls._count(unhealthy_value)
        if status == "healthy":
            return 1, 0
        if status in {"degraded", "unavailable", "revoked"}:
            return 0, 1
        raise AdminUpstreamsUnavailable("credential account aggregate is unavailable")

    @staticmethod
    def _first_present(source: Mapping[str, Any], *names: str) -> Any:
        for name in names:
            if name in source:
                return source[name]
        return None

    @staticmethod
    def _count(value: Any) -> int:
        if type(value) is not int or value < 0:
            raise AdminUpstreamsUnavailable("credential account aggregate is invalid")
        return value

    @classmethod
    def _queue_rows(cls, value: Any) -> list[Mapping[str, Any]]:
        if isinstance(value, Mapping):
            value = value.get("items")
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise AdminUpstreamsUnavailable("reconciliation queue is invalid")
        rows: list[Mapping[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise AdminUpstreamsUnavailable("reconciliation queue row is invalid")
            rows.append(item)
        return rows

    @classmethod
    def _last_synced_at(
        cls,
        health: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
    ) -> str | None:
        candidates: list[datetime] = []
        for source in (health, *rows):
            for name in ("lastSyncedAt", "last_synced_at", "syncedAt", "synced_at"):
                if name in source and source[name] is not None:
                    candidates.append(_parse_timestamp(source[name]))
        if not candidates:
            return None
        return _timestamp(max(candidates))

    @staticmethod
    def _revision(summary: Mapping[str, Any]) -> int:
        encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")

    def _context(self, value: AdminUpstreamsContext | Any) -> AdminUpstreamsContext:
        if value is None:
            raise AdminUpstreamsUnauthorized()
        if isinstance(value, AdminUpstreamsContext):
            context = value
        else:
            try:
                actor_user_id_value = getattr(value, "actor_user_id", None) or getattr(value, "user_id")
                actor_session_id_value = getattr(value, "actor_session_id", None) or getattr(value, "session_id")
                actor_user_id = UUID(str(actor_user_id_value))
                actor_session_id = UUID(str(actor_session_id_value))
                role = str(getattr(value, "role"))
                maintainer = bool(getattr(value, "maintainer", getattr(value, "is_maintainer", False)))
            except (AttributeError, TypeError, ValueError) as exc:
                raise AdminUpstreamsUnauthorized() from exc
            context = AdminUpstreamsContext(actor_user_id, actor_session_id, role, maintainer)
        if context.role != "admin":
            raise AdminUpstreamsForbidden()
        return context

    def _authorize(
        self,
        connection: Any,
        context: AdminUpstreamsContext,
        *,
        require_maintainer: bool = False,
    ) -> None:
        self._storage.require_admin(connection, context, _as_utc(self._now()))
        if require_maintainer and not context.maintainer:
            raise AdminUpstreamsForbidden("maintainer permission is required")

    def _start_mutation(
        self,
        connection: Any,
        context: AdminUpstreamsContext,
        operation: str,
        key: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        self._authorize(connection, context)
        return self._find_replay(connection, context, operation, key, fingerprint)

    def _find_replay(
        self,
        connection: Any,
        context: AdminUpstreamsContext,
        operation: str,
        key: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        existing = self._storage.find_idempotency(connection, context.actor_user_id, operation, key)
        if existing is None:
            return None
        if existing.get("requestFingerprint") != fingerprint:
            raise AdminUpstreamsIdempotencyConflict()
        response = existing.get("response")
        if not isinstance(response, dict):
            raise AdminUpstreamsUnavailable("idempotent response is missing")
        return response

    def _finish_mutation(
        self,
        connection: Any,
        context: AdminUpstreamsContext,
        *,
        operation: str,
        key: str,
        fingerprint: str,
        reason: str,
        response: dict[str, Any],
    ) -> None:
        self._storage.save_audit(
            connection,
            actorUserId=context.actor_user_id,
            actorSessionId=context.actor_session_id,
            operation=operation,
            targetUserId=None,
            reason=reason,
            metadata={
                "idempotencyKey": key,
                "requestFingerprint": fingerprint,
                "response": response,
                "status": "succeeded",
                "targetType": "platform",
            },
        )

    @staticmethod
    def _reason(value: str) -> str:
        if not isinstance(value, str):
            raise AdminUpstreamsInvalidRequest("reason is required")
        normalized = value.strip()
        if not 1 <= len(normalized) <= 500:
            raise AdminUpstreamsInvalidRequest("reason is required")
        return normalized

    @staticmethod
    def _expected_revision(value: int) -> int:
        if type(value) is not int or value < 0:
            raise AdminUpstreamsInvalidRequest("expectedRevision is invalid")
        return value

    @staticmethod
    def _idempotency_key(value: str) -> str:
        return idempotency_key(
            value,
            error=lambda: AdminUpstreamsInvalidRequest("Idempotency-Key is invalid"),
            policy=IF2_KEY,
        )

    @staticmethod
    def _operation_id(value: str) -> UUID:
        try:
            return UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise AdminUpstreamsNotFound() from exc

    @staticmethod
    def _fingerprint(operation: str, target: UUID | str, reason: str, expected: int) -> str:
        encoded = json.dumps(
            {"operation": operation, "target": str(target), "reason": reason, "expectedRevision": expected},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _check_revision(expected: int, actual: int) -> None:
        if expected != actual:
            raise AdminUpstreamsRevisionConflict()

