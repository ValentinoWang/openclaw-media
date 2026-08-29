"""IF2 adapter for the B13 administrator billing page.

The adapter owns the typed page contract and its audit/readback boundary. The
retail services remain the canonical writers for mappings, grants, batches,
fulfillments, wallets, and ledger entries.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from ...account.admin_audit import write_admin_audit
from .foundation import IF2_KEY, idempotency_key


SCHEMA_VERSION = "media_web_business_pages_v2"
MAX_SUMMARY_ROWS = 200
MAX_REASON_LENGTH = 500
MONEY_QUANTUM = Decimal("0.00000001")
MAX_ADMIN_GRANT = Decimal("100000.00000000")
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_UTC = timezone.utc


class AdminBillingError(RuntimeError):
    status = 500
    field: str | None = None

    def __init__(self, code: str, message: str, *, status: int, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.field = field


class AdminBillingUnauthorized(AdminBillingError):
    def __init__(self, message: str = "administrator authentication is required") -> None:
        super().__init__("authentication_required", message, status=401)


class AdminBillingForbidden(AdminBillingError):
    def __init__(self, message: str = "administrator permission is required") -> None:
        super().__init__("admin_required", message, status=403)


class AdminBillingInvalidRequest(AdminBillingError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__("invalid_request", message, status=400, field=field)


class AdminBillingNotFound(AdminBillingError):
    def __init__(self, message: str = "resource was not found") -> None:
        super().__init__("resource_not_found", message, status=404)


class AdminBillingRevisionConflict(AdminBillingError):
    def __init__(self, message: str = "billing revision has changed") -> None:
        super().__init__("revision_conflict", message, status=409)


class AdminBillingIdempotencyConflict(AdminBillingError):
    def __init__(self, message: str = "idempotency key is bound to another request") -> None:
        super().__init__("idempotency_conflict", message, status=409)


class AdminBillingInternalError(AdminBillingError):
    def __init__(self, message: str = "administrator billing data is unavailable") -> None:
        super().__init__("internal_error", message, status=500)


@dataclass(frozen=True)
class AdminBillingContext:
    actor_user_id: UUID | str
    actor_session_id: UUID | str
    role: str = "admin"
    maintainer: bool = True


AdminBillingSessionContext = AdminBillingContext


class Connection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


ConnectionFactory = Callable[[], AbstractContextManager[Connection]]


class AdminBillingStorage(Protocol):
    def require_admin(self, connection: Any, context: AdminBillingContext, now: datetime) -> None: ...

    def find_idempotency(
        self,
        connection: Any,
        actor_user_id: UUID,
        operation: str,
        key: str,
    ) -> dict[str, Any] | None: ...

    def save_audit(self, connection: Any, **record: Any) -> None: ...


def _as_utc(value: Any, *, allow_none: bool = False) -> datetime | None:
    if value is None and allow_none:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AdminBillingInternalError("billing timestamp is invalid") from exc
    else:
        raise AdminBillingInternalError("billing timestamp is invalid")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_UTC)
    return parsed.astimezone(_UTC)


def _timestamp(value: Any, *, allow_none: bool = False) -> str | None:
    parsed = _as_utc(value, allow_none=allow_none)
    return None if parsed is None else parsed.isoformat().replace("+00:00", "Z")


def _uuid(value: Any, *, not_found: bool = False) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        if not_found:
            raise AdminBillingNotFound() from exc
        raise AdminBillingInternalError("billing identifier is invalid") from exc


def _secret(secret: bytes, label: str) -> bytes:
    if not isinstance(secret, bytes) or len(secret) < 16:
        raise ValueError(f"B13 {label} must be at least 16 bytes")
    return hashlib.sha256(label.encode("ascii") + b":" + secret).digest()


def _encode_signed(value: Mapping[str, Any], secret: bytes) -> str:
    body = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret, body, hashlib.sha256).digest()[:18]
    return base64.urlsafe_b64encode(body + b"." + signature).decode("ascii").rstrip("=")


def _decode_signed(value: Any, secret: bytes) -> dict[str, Any]:
    if not isinstance(value, str) or _PUBLIC_ID.fullmatch(value) is None:
        raise AdminBillingNotFound()
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        body, signature = raw.rsplit(b".", 1)
        expected = hmac.new(secret, body, hashlib.sha256).digest()[:18]
        if not hmac.compare_digest(signature, expected):
            raise AdminBillingNotFound()
        decoded = json.loads(body.decode("utf-8"))
    except AdminBillingNotFound:
        raise
    except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdminBillingNotFound() from exc
    if not isinstance(decoded, dict):
        raise AdminBillingNotFound()
    return decoded


def _encode_public_id(namespace: str, object_id: UUID, secret: bytes) -> str:
    return _encode_signed({"namespace": namespace, "id": str(object_id)}, secret)


def _decode_public_id(namespace: str, value: str, secret: bytes) -> UUID:
    decoded = _decode_signed(value, secret)
    if decoded.get("namespace") != namespace:
        raise AdminBillingNotFound()
    return _uuid(decoded.get("id"), not_found=True)


def _encode_tenant_id(tenant_id: UUID, secret: bytes) -> str:
    return _encode_signed({"namespace": "b12-tenant", "tenantId": str(tenant_id)}, secret)


def _decode_tenant_id(value: str, secret: bytes) -> UUID:
    decoded = _decode_signed(value, secret)
    if decoded.get("namespace") != "b12-tenant":
        raise AdminBillingNotFound()
    return _uuid(decoded.get("tenantId"), not_found=True)


def _revision(*parts: Any) -> int:
    encoded: list[str] = []
    for part in parts:
        if isinstance(part, datetime):
            encoded.append(_timestamp(part) or "")
        elif isinstance(part, UUID):
            encoded.append(str(part))
        else:
            encoded.append(json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    digest = hashlib.sha256("|".join(encoded).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _decimal(value: Any, message: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AdminBillingInternalError(message) from exc
    if not result.is_finite():
        raise AdminBillingInternalError(message)
    return result


def _decimal_text(value: Any, message: str = "billing amount is invalid") -> str:
    return format(_decimal(value, message), "f")


def _nonnegative_int(value: Any, message: str) -> int:
    if isinstance(value, bool):
        raise AdminBillingInternalError(message)
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AdminBillingInternalError(message) from exc
    if result < 0:
        raise AdminBillingInternalError(message)
    return result


def _text(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= maximum:
        raise AdminBillingInvalidRequest(f"{field} is invalid", field=field)
    return value


def _reason(value: Any) -> str:
    return _text(value, field="reason", maximum=MAX_REASON_LENGTH)


def _idempotency_key(value: Any) -> str:
    return idempotency_key(
        value,
        error=lambda: AdminBillingInvalidRequest("Idempotency-Key is invalid", field="Idempotency-Key"),
        policy=IF2_KEY,
    )


def _expected_revision(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise AdminBillingInvalidRequest("expectedRevision is invalid", field="expectedRevision")
    return value


def _amount(value: Any) -> str:
    if not isinstance(value, str):
        raise AdminBillingInvalidRequest("amount is invalid", field="amount")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise AdminBillingInvalidRequest("amount is invalid", field="amount") from exc
    if (
        not amount.is_finite()
        or amount <= 0
        or amount > MAX_ADMIN_GRANT
        or amount.quantize(MONEY_QUANTUM) != amount
    ):
        raise AdminBillingInvalidRequest("amount is invalid", field="amount")
    return format(amount.quantize(MONEY_QUANTUM), "f")


def _purchase_url(value: Any) -> str:
    if not isinstance(value, str) or value != value.strip() or not 20 <= len(value) <= 2048:
        raise AdminBillingInvalidRequest("purchaseUrl is invalid", field="purchaseUrl")
    if any(character.isspace() for character in value):
        raise AdminBillingInvalidRequest("purchaseUrl is invalid", field="purchaseUrl")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise AdminBillingInvalidRequest("purchaseUrl must be a Liandong HTTPS URL", field="purchaseUrl") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
        or not (host == "ldxp.cn" or host.endswith(".ldxp.cn"))
    ):
        raise AdminBillingInvalidRequest("purchaseUrl must be a Liandong HTTPS URL", field="purchaseUrl")
    return value


def _assert_public_value(value: Any, *, field: str | None = None) -> None:
    """Reject internal identifiers before an injected/read model reaches IF2 output."""
    if isinstance(value, (UUID, bytes, bytearray)):
        raise AdminBillingInternalError("billing summary contains an internal value")
    if isinstance(value, str) and field in {"tenantId", "tenant_id", "userId", "user_id"}:
        try:
            UUID(value)
        except ValueError:
            return
        raise AdminBillingInternalError("billing summary contains an internal identifier")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_public_value(child, field=str(key))
    elif isinstance(value, list):
        for child in value:
            _assert_public_value(child)


class PostgresAdminBillingStorage:
    """Uses only the canonical session and immutable admin audit tables."""

    def require_admin(self, connection: Any, context: AdminBillingContext, now: datetime) -> None:
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
        if row is None or row[2] != "active" or (_as_utc(row[3]) or now) <= now:
            raise AdminBillingUnauthorized()
        if row[0] != "admin" or row[1] != "active":
            raise AdminBillingForbidden()

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
                raise AdminBillingInternalError("administrator audit metadata is invalid") from exc
        if not isinstance(metadata, dict):
            raise AdminBillingInternalError("administrator audit metadata is invalid")
        return metadata

    def save_audit(self, connection: Any, **record: Any) -> None:
        write_admin_audit(
            connection,
            audit_id=record["auditId"],
            actor_user_id=record["actorUserId"],
            actor_session_id=record["actorSessionId"],
            action=record["operation"],
            target_user_id=record.get("targetUserId"),
            reason=record["reason"],
            metadata=record["metadata"],
        )


_PLAN_QUERY = """
    SELECT p.code,p.name,p.status,p.text_quota,p.image_quota,p.price_cny,p.currency,p.revision
    FROM openclaw_account.plans AS p
    WHERE p.status IN ('active','draft')
    ORDER BY p.price_cny ASC,p.code ASC
    LIMIT %s
"""
_MAPPING_QUERY = """
    SELECT m.id,p.code,m.external_product_id,m.purchase_url,m.status,m.created_at
    FROM openclaw_account.product_mappings AS m
    JOIN openclaw_account.plans AS p ON p.id=m.plan_id
    ORDER BY m.created_at DESC,m.id DESC
    LIMIT %s
"""
_BATCH_QUERY = """
    SELECT b.id,p.code,b.status,b.code_count,
           COUNT(c.id) FILTER (WHERE c.status='redeemed'),b.created_at
    FROM openclaw_account.redemption_batches AS b
    JOIN openclaw_account.product_mappings AS m ON m.id=b.product_mapping_id
    JOIN openclaw_account.plans AS p ON p.id=m.plan_id
    LEFT JOIN openclaw_account.redemption_codes AS c ON c.batch_id=b.id
    GROUP BY b.id,p.code
    ORDER BY b.created_at DESC,b.id DESC
    LIMIT %s
"""
_FULFILLMENT_QUERY = """
    SELECT f.id,f.tenant_id,p.code,f.credited_amount,f.status,f.created_at,
           f.completed_at,f.refunded_at,COALESCE(affiliate.amount,0)
    FROM openclaw_account.fulfillments AS f
    JOIN openclaw_account.plans AS p ON p.id=f.plan_id
    LEFT JOIN (
        SELECT fulfillment_id,SUM(amount) AS amount
        FROM openclaw_account.affiliate_ledger
        GROUP BY fulfillment_id
    ) AS affiliate ON affiliate.fulfillment_id=f.id
    ORDER BY f.created_at DESC,f.id DESC
    LIMIT %s
"""
_GRANT_QUERY = """
    SELECT l.id,l.tenant_id,u.username,l.available_delta,a.reason,l.created_at
    FROM openclaw_account.ledger_entries AS l
    JOIN openclaw_account.admin_audit AS a ON a.id=l.source_id
    JOIN openclaw_account.tenants AS t ON t.id=l.tenant_id
    JOIN openclaw_account.users AS u ON u.id=t.primary_user_id
    WHERE l.entry_type='admin_grant' AND l.source_type='admin_grant'
    ORDER BY l.created_at DESC,l.id DESC
    LIMIT %s
"""
_LEDGER_REVISION_QUERY = "SELECT COUNT(*) FROM openclaw_account.ledger_entries"


class AdminBillingService:
    """Expose B13 over existing retail writers and canonical account tables."""

    _PRODUCT_MAPPING_OPERATION = "media_b13_product_mapping"
    _GRANT_OPERATION = "media_b13_grant"
    _BATCH_OPERATION = "media_b13_redemption_batch"
    _RECOVER_OPERATION = "media_b13_fulfillment_recover"
    _REFUND_OPERATION = "media_b13_fulfillment_refund"

    def __init__(
        self,
        database_or_factory: Any,
        *,
        public_id_secret: bytes,
        retail_admin: Any | None = None,
        retail_fulfillment: Any | None = None,
        product_mapping_writer: Callable[..., Any] | None = None,
        grant_writer: Callable[..., Any] | None = None,
        batch_writer: Callable[..., Any] | None = None,
        recover_writer: Callable[..., Any] | None = None,
        refund_writer: Callable[..., Any] | None = None,
        summary_reader: Callable[[], Mapping[str, Any]] | None = None,
        storage: AdminBillingStorage | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if hasattr(database_or_factory, "connect"):
            self._connection_factory: ConnectionFactory = database_or_factory.connect
        elif callable(database_or_factory):
            self._connection_factory = database_or_factory
        else:
            raise TypeError("B13 requires an AccountDatabase or connection factory")
        self._public_id_secret = _secret(public_id_secret, "public-id-secret")
        self._storage = storage or PostgresAdminBillingStorage()
        self._now = now or (lambda: datetime.now(_UTC))
        self._summary_reader = summary_reader

        self._product_mapping_writer = product_mapping_writer or (
            getattr(retail_admin, "create_mapping", None) if retail_admin is not None else None
        )
        self._grant_writer = grant_writer or (
            getattr(retail_admin, "grant", None) if retail_admin is not None else None
        )
        self._batch_writer = batch_writer or (
            getattr(retail_fulfillment, "create_batch", None) if retail_fulfillment is not None else None
        )
        self._recover_writer = recover_writer or (
            getattr(retail_fulfillment, "recover", None) if retail_fulfillment is not None else None
        )
        self._refund_writer = refund_writer or (
            getattr(retail_fulfillment, "refund", None) if retail_fulfillment is not None else None
        )

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, AdminBillingError):
            return {"error": {"code": error.code, "message": error.message, "field": error.field}}
        return {"error": {"code": "internal_error", "message": "administrator billing data is unavailable", "field": None}}

    @staticmethod
    def error_status(error: BaseException) -> int:
        return error.status if isinstance(error, AdminBillingError) else 500

    def public_tenant_id(self, tenant_id: UUID | str) -> str:
        return _encode_tenant_id(_uuid(tenant_id), self._public_id_secret)

    def public_mapping_id(self, mapping_id: UUID | str) -> str:
        return _encode_public_id("b13-mapping", _uuid(mapping_id), self._public_id_secret)

    def public_batch_id(self, batch_id: UUID | str) -> str:
        return _encode_public_id("b13-batch", _uuid(batch_id), self._public_id_secret)

    def public_fulfillment_id(self, fulfillment_id: UUID | str) -> str:
        return _encode_public_id("b13-fulfillment", _uuid(fulfillment_id), self._public_id_secret)

    def get_admin_billing_summary(self, context: AdminBillingContext | Any) -> dict[str, Any]:
        checked = self._context(context)
        with self._connection_factory() as connection:
            self._authorize(connection, checked)
            response = self._read_response(connection)
            self._commit(connection)
            return response

    def create_admin_product_mapping(
        self,
        context: AdminBillingContext | Any,
        *,
        plan_code: str,
        external_product_id: str,
        purchase_url: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        plan = _text(plan_code, field="planCode", maximum=64)
        product = _text(external_product_id, field="externalProductId", maximum=128)
        url = _purchase_url(purchase_url)
        audit_reason = _reason(reason)
        key = _idempotency_key(idempotency_key)
        payload = {
            "planCode": plan,
            "externalProductId": product,
            "purchaseUrl": url,
            "reason": audit_reason,
        }

        def write() -> Any:
            return self._call_writer(
                self._product_mapping_writer,
                actor_user_id=checked.actor_user_id,
                actor_session_id=checked.actor_session_id,
                plan_code=plan,
                external_product_id=product,
                purchase_url=url,
                reason=audit_reason,
                idempotency_key=key,
            )

        return self._mutate(
            checked,
            operation=self._PRODUCT_MAPPING_OPERATION,
            key=key,
            payload=payload,
            reason=audit_reason,
            lock_scope=f"plan:{plan}",
            callback=write,
        )

    def create_admin_billing_grant(
        self,
        context: AdminBillingContext | Any,
        *,
        public_tenant_id: str,
        amount: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        tenant_id = _decode_tenant_id(public_tenant_id, self._public_id_secret)
        grant_amount = _amount(amount)
        audit_reason = _reason(reason)
        key = _idempotency_key(idempotency_key)
        payload = {
            "publicTenantId": public_tenant_id,
            "amount": grant_amount,
            "reason": audit_reason,
        }

        def write() -> Any:
            return self._call_writer(
                self._grant_writer,
                actor_user_id=checked.actor_user_id,
                actor_session_id=checked.actor_session_id,
                target_tenant_id=tenant_id,
                amount=grant_amount,
                reason=audit_reason,
                idempotency_key=key,
            )

        return self._mutate(
            checked,
            operation=self._GRANT_OPERATION,
            key=key,
            payload=payload,
            reason=audit_reason,
            lock_scope=f"tenant:{tenant_id}",
            callback=write,
        )

    def create_admin_redemption_batch(
        self,
        context: AdminBillingContext | Any,
        *,
        plan_code: str,
        count: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        plan = _text(plan_code, field="planCode", maximum=64)
        if type(count) is not int or not 1 <= count <= 1000:
            raise AdminBillingInvalidRequest("count is invalid", field="count")
        audit_reason = _reason(reason)
        key = _idempotency_key(idempotency_key)
        payload = {"planCode": plan, "count": count, "reason": audit_reason}

        def write() -> Any:
            return self._call_writer(
                self._batch_writer,
                actor_user_id=checked.actor_user_id,
                plan_code=plan,
                count=count,
                idempotency_key=key,
            )

        return self._mutate(
            checked,
            operation=self._BATCH_OPERATION,
            key=key,
            payload=payload,
            reason=audit_reason,
            lock_scope=f"plan:{plan}",
            callback=write,
        )

    def recover_admin_fulfillment(
        self,
        context: AdminBillingContext | Any,
        fulfillment_id: str,
        *,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        target = _decode_public_id("b13-fulfillment", fulfillment_id, self._public_id_secret)
        audit_reason = _reason(reason)
        expected = _expected_revision(expected_revision)
        key = _idempotency_key(idempotency_key)
        payload = {
            "fulfillmentId": fulfillment_id,
            "reason": audit_reason,
            "expectedRevision": expected,
        }

        def write() -> Any:
            return self._call_writer(self._recover_writer, fulfillment_id=target)

        return self._mutate(
            checked,
            operation=self._RECOVER_OPERATION,
            key=key,
            payload=payload,
            reason=audit_reason,
            expected_revision=expected,
            lock_scope=f"fulfillment:{target}",
            callback=write,
        )

    def refund_admin_fulfillment(
        self,
        context: AdminBillingContext | Any,
        fulfillment_id: str,
        *,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        checked = self._context(context)
        target = _decode_public_id("b13-fulfillment", fulfillment_id, self._public_id_secret)
        audit_reason = _reason(reason)
        expected = _expected_revision(expected_revision)
        key = _idempotency_key(idempotency_key)
        payload = {
            "fulfillmentId": fulfillment_id,
            "reason": audit_reason,
            "expectedRevision": expected,
        }

        def write() -> Any:
            return self._call_writer(
                self._refund_writer,
                actor_user_id=checked.actor_user_id,
                fulfillment_id=target,
                reason=audit_reason,
            )

        return self._mutate(
            checked,
            operation=self._REFUND_OPERATION,
            key=key,
            payload=payload,
            reason=audit_reason,
            expected_revision=expected,
            lock_scope=f"fulfillment:{target}",
            callback=write,
        )

    def _mutate(
        self,
        context: AdminBillingContext,
        *,
        operation: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
        lock_scope: str,
        callback: Callable[[], Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        fingerprint = self._fingerprint(operation, payload)
        lock_key = f"media-b13:{operation}:{lock_scope}"
        with self._connection_factory() as connection:
            locked = False
            try:
                self._authorize(connection, context)
                self._lock(connection, lock_key)
                locked = True
                replay = self._find_replay(connection, context, operation, key, fingerprint)
                if replay is not None:
                    self._commit(connection)
                    return replay
                before = self._read_response(connection)
                if expected_revision is not None and expected_revision != before["revision"]:
                    raise AdminBillingRevisionConflict()
                self._commit(connection)
                try:
                    callback()
                except AdminBillingError:
                    raise
                except Exception as exc:
                    raise self._translate_writer_error(exc) from exc
                after = self._read_response(connection)
                response = {
                    "schemaVersion": SCHEMA_VERSION,
                    "revision": after["revision"],
                    "ok": True,
                    "updatedAt": _timestamp(self._now()),
                }
                self._storage.save_audit(
                    connection,
                    auditId=uuid4(),
                    actorUserId=context.actor_user_id,
                    actorSessionId=context.actor_session_id,
                    operation=operation,
                    targetUserId=None,
                    reason=reason,
                    metadata={
                        "idempotencyKey": key,
                        "requestFingerprint": fingerprint,
                        "request": dict(payload),
                        "response": response,
                        "beforeRevision": before["revision"],
                        "readbackRevision": after["revision"],
                        "status": "succeeded",
                        "targetType": "billing",
                    },
                )
                self._commit(connection)
                return response
            finally:
                if locked:
                    self._rollback(connection)
                    try:
                        self._unlock(connection, lock_key)
                    finally:
                        self._commit(connection)

    def _read_response(self, connection: Any) -> dict[str, Any]:
        try:
            if self._summary_reader is not None:
                raw = self._summary_reader()
                summary = raw.get("summary") if isinstance(raw, Mapping) and "summary" in raw else raw
                return self._wrap_summary(summary)
            return self._wrap_summary(self._read_summary_from_connection(connection))
        except AdminBillingError:
            raise
        except Exception as exc:
            raise AdminBillingInternalError() from exc

    def _read_summary_from_connection(self, connection: Any) -> dict[str, Any]:
        try:
            plan_rows = connection.execute(_PLAN_QUERY, (MAX_SUMMARY_ROWS,)).fetchall()
            mapping_rows = connection.execute(_MAPPING_QUERY, (MAX_SUMMARY_ROWS,)).fetchall()
            batch_rows = connection.execute(_BATCH_QUERY, (MAX_SUMMARY_ROWS,)).fetchall()
            fulfillment_rows = connection.execute(_FULFILLMENT_QUERY, (MAX_SUMMARY_ROWS,)).fetchall()
            grant_rows = connection.execute(_GRANT_QUERY, (MAX_SUMMARY_ROWS,)).fetchall()
            ledger_row = connection.execute(_LEDGER_REVISION_QUERY).fetchone()
        except AdminBillingError:
            raise
        except Exception as exc:
            raise AdminBillingInternalError() from exc

        plans: list[dict[str, Any]] = []
        for row in plan_rows:
            if not isinstance(row, (tuple, list)) or len(row) < 8:
                raise AdminBillingInternalError("billing plan row is incomplete")
            plans.append(
                {
                    "planCode": _text(row[0], field="planCode", maximum=64),
                    "name": _text(row[1], field="name", maximum=254),
                    "status": _text(row[2], field="status", maximum=32),
                    "textQuota": float(_decimal(row[3], "text quota is invalid")),
                    "imageQuota": float(_decimal(row[4], "image quota is invalid")),
                    "price": _decimal_text(row[5], "plan price is invalid"),
                    "currency": _text(row[6], field="currency", maximum=32),
                }
            )
        product_mappings = [
            {
                "mappingId": self.public_mapping_id(_uuid(row[0], not_found=True)),
                "planCode": _text(row[1], field="planCode", maximum=64),
                "externalProductId": _text(row[2], field="externalProductId", maximum=128),
                "purchaseUrl": _purchase_url(row[3]),
                "status": _text(row[4], field="status", maximum=32),
                "createdAt": _timestamp(row[5]),
            }
            for row in mapping_rows
        ]
        redemption_batches = [
            {
                "batchId": self.public_batch_id(_uuid(row[0], not_found=True)),
                "planCode": _text(row[1], field="planCode", maximum=64),
                "status": _text(row[2], field="status", maximum=32),
                "codeCount": _nonnegative_int(row[3], "batch code count is invalid"),
                "redeemedCount": _nonnegative_int(row[4], "batch redeemed count is invalid"),
                "createdAt": _timestamp(row[5]),
            }
            for row in batch_rows
        ]
        fulfillments = [
            {
                "fulfillmentId": self.public_fulfillment_id(_uuid(row[0], not_found=True)),
                "publicTenantId": self.public_tenant_id(_uuid(row[1], not_found=True)),
                "planCode": _text(row[2], field="planCode", maximum=64),
                "creditedAmount": _decimal_text(row[3]),
                "affiliateAmount": _decimal_text(row[8]),
                "status": _text(row[4], field="status", maximum=32),
                "createdAt": _timestamp(row[5]),
                "completedAt": _timestamp(row[6], allow_none=True),
                "refundedAt": _timestamp(row[7], allow_none=True),
            }
            for row in fulfillment_rows
        ]
        grants = [
            {
                "ledgerEntryId": _encode_public_id("b13-ledger", _uuid(row[0], not_found=True), self._public_id_secret),
                "publicTenantId": self.public_tenant_id(_uuid(row[1], not_found=True)),
                "username": _text(row[2], field="username", maximum=254),
                "amount": _decimal_text(row[3]),
                "reason": _text(row[4], field="reason", maximum=MAX_REASON_LENGTH),
                "createdAt": _timestamp(row[5]),
            }
            for row in grant_rows
        ]
        ledger_revision = _nonnegative_int(ledger_row[0] if ledger_row else 0, "ledger revision is invalid")
        return {
            "plans": plans,
            "productMappings": product_mappings,
            "redemptionBatches": redemption_batches,
            "fulfillments": fulfillments,
            "grants": grants,
            "ledgerRevision": ledger_revision,
        }

    @staticmethod
    def _wrap_summary(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise AdminBillingInternalError("billing summary is invalid")
        required = {"plans", "productMappings", "redemptionBatches", "fulfillments", "grants", "ledgerRevision"}
        if set(value) != required:
            raise AdminBillingInternalError("billing summary fields are invalid")
        collection_keys = required - {"ledgerRevision"}
        if any(not isinstance(value[key], list) for key in collection_keys):
            raise AdminBillingInternalError("billing summary collections are invalid")
        for key in collection_keys:
            for item in value[key]:
                if not isinstance(item, Mapping):
                    raise AdminBillingInternalError("billing summary rows are invalid")
                _assert_public_value(item)
        ledger_revision = _nonnegative_int(value["ledgerRevision"], "ledger revision is invalid")
        summary = {
            "plans": list(value["plans"]),
            "productMappings": list(value["productMappings"]),
            "redemptionBatches": list(value["redemptionBatches"]),
            "fulfillments": list(value["fulfillments"]),
            "grants": list(value["grants"]),
            "ledgerRevision": ledger_revision,
        }
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": _revision("admin-billing", summary),
            "summary": summary,
        }

    def _context(self, value: AdminBillingContext | Any) -> AdminBillingContext:
        if value is None:
            raise AdminBillingUnauthorized()
        role = getattr(value, "role", None)
        if role != "admin" or getattr(value, "maintainer", True) is False:
            raise AdminBillingForbidden()
        actor_user_id = getattr(value, "actor_user_id", getattr(value, "user_id", None))
        actor_session_id = getattr(value, "actor_session_id", getattr(value, "session_id", None))
        if actor_user_id is None or actor_session_id is None:
            raise AdminBillingUnauthorized()
        try:
            user_id = _uuid(actor_user_id)
            session_id = _uuid(actor_session_id)
        except AdminBillingError as exc:
            raise AdminBillingUnauthorized() from exc
        return AdminBillingContext(user_id, session_id, role="admin", maintainer=True)

    def _authorize(self, connection: Any, context: AdminBillingContext) -> None:
        self._storage.require_admin(connection, context, _as_utc(self._now()) or datetime.now(_UTC))

    def _find_replay(
        self,
        connection: Any,
        context: AdminBillingContext,
        operation: str,
        key: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        existing = self._storage.find_idempotency(connection, context.actor_user_id, operation, key)
        if existing is None:
            return None
        if existing.get("requestFingerprint") != fingerprint:
            raise AdminBillingIdempotencyConflict()
        response = existing.get("response")
        if (
            not isinstance(response, dict)
            or set(response) != {"schemaVersion", "revision", "ok", "updatedAt"}
            or response.get("schemaVersion") != SCHEMA_VERSION
            or response.get("ok") is not True
            or type(response.get("revision")) is not int
            or not isinstance(response.get("updatedAt"), str)
        ):
            raise AdminBillingInternalError("idempotent billing response is missing")
        return response

    @staticmethod
    def _fingerprint(operation: str, payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(
            {"operation": operation, "payload": dict(payload)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _call_writer(writer: Callable[..., Any] | None, **kwargs: Any) -> Any:
        if not callable(writer):
            raise AdminBillingInternalError("canonical billing writer is unavailable")
        return writer(**kwargs)

    @staticmethod
    def _translate_writer_error(error: BaseException) -> AdminBillingError:
        code = getattr(error, "code", None)
        raw_message = getattr(error, "detail", None) or getattr(error, "message", None)
        message = raw_message if isinstance(raw_message, str) and raw_message else "administrator billing operation failed"
        if code == "idempotency_conflict":
            return AdminBillingIdempotencyConflict()
        if code in {"plan_not_found", "tenant_not_found", "fulfillment_not_found"}:
            return AdminBillingNotFound()
        if code in {"product_mapping_invalid", "admin_grant_invalid"}:
            return AdminBillingError(str(code), message, status=400)
        if code in {
            "product_mapping_conflict",
            "fulfillment_conflict",
            "redemption_unavailable",
            "redemption_processing",
        }:
            return AdminBillingError(str(code), message, status=409)
        if code in {"account_database_unavailable", "account_schema_outdated"}:
            return AdminBillingError(str(code), "administrator billing data is unavailable", status=503)
        return AdminBillingInternalError()

    @staticmethod
    def _lock(connection: Any, key: str) -> None:
        connection.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (key,))

    @staticmethod
    def _unlock(connection: Any, key: str) -> None:
        connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))

    @staticmethod
    def _commit(connection: Any) -> None:
        commit = getattr(connection, "commit", None)
        if callable(commit):
            commit()

    @staticmethod
    def _rollback(connection: Any) -> None:
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            rollback()

