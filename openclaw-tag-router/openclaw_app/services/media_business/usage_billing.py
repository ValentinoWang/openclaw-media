"""Tenant-scoped PostgreSQL read model for the B08 usage and billing page."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import foundation
from .foundation import MediaBusinessError, TenantContext, public_projection, require_context


SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100
DEFAULT_TIMEZONE = "Asia/Shanghai"
MONEY_QUANTUM = Decimal("0.00000001")
PRICE_QUANTUM = Decimal("0.01")
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_KINDS = {"text", "image", "credit", "compensation"}
_STATUSES = {"succeeded", "compensated", "pending_reconciliation"}
_UNITS = {"tokens", "images", "credit"}


UsageBillingError = MediaBusinessError


class UsageBillingForbidden(UsageBillingError):
    def __init__(self, message: str = "billing data is not available for this session") -> None:
        super().__init__("forbidden", message, status=403)


class UsageBillingInvalidRequest(UsageBillingError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__("invalid_request", message, status=400, field=field)


class UsageBillingConflict(UsageBillingError):
    def __init__(self, message: str = "idempotency key was reused with a different request") -> None:
        super().__init__("idempotency_conflict", message, status=409)


class UsageBillingNotFound(UsageBillingError):
    def __init__(self, message: str = "billing account was not found") -> None:
        super().__init__("resource_not_found", message, status=404)


class UsageBillingInternalError(UsageBillingError):
    def __init__(self, message: str = "billing data is unavailable") -> None:
        super().__init__("internal_error", message, status=500)


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


class ConnectionFactory(Protocol):
    def __call__(self) -> AbstractContextManager[DatabaseConnection]: ...


class RedemptionService(Protocol):
    def redeem(self, *, tenant_id: str, user_id: str, code: str) -> Any: ...


@dataclass(frozen=True)
class UsageCursor:
    tenant_id: UUID
    created_at: datetime
    public_usage_id: str


@dataclass(frozen=True)
class _UsageRow:
    public_usage_id: str
    kind: str
    model: str
    quantity: Decimal
    unit: str
    charge: Decimal
    status: str
    created_at: datetime


class UsageBillingService:
    """Read canonical billing facts without creating a second balance ledger."""

    _BALANCE_QUERY = """
        SELECT w.available, w.updated_at, w.version
        FROM openclaw_account.wallet_accounts AS w
        WHERE w.tenant_id = %s
    """

    _BALANCE_PACKS_QUERY = """
        SELECT p.code,
               p.name,
               p.credit_amount,
               p.price_cny,
               p.currency,
               p.audience,
               p.product_kind,
               p.revision,
               active_mapping.purchase_url
        FROM openclaw_account.plans AS p
        LEFT JOIN LATERAL (
            SELECT mapping.purchase_url
            FROM openclaw_account.product_mappings AS mapping
            WHERE mapping.plan_id = p.id
              AND mapping.status = 'active'
            ORDER BY mapping.created_at DESC, mapping.id DESC
            LIMIT 1
        ) AS active_mapping ON TRUE
        WHERE p.status = 'active'
          AND p.product_kind = 'balance_pack'
          AND p.audience = 'all'
        ORDER BY p.price_cny ASC, p.code ASC
    """

    _USAGE_QUERY = """
        SELECT e.public_usage_id,
               e.kind,
               e.model,
               e.quantity,
               e.unit,
               e.charge,
               e.status,
               e.created_at,
               COUNT(*) OVER () AS stream_revision
        FROM openclaw_account.billing_usage_events AS e
        LEFT JOIN openclaw_account.model_price_versions AS price_version
          ON price_version.id = e.price_version_id
        WHERE e.tenant_id = %s
          AND (
              CAST(%s AS TIMESTAMPTZ) IS NULL
              OR e.created_at < CAST(%s AS TIMESTAMPTZ)
              OR (e.created_at = CAST(%s AS TIMESTAMPTZ) AND e.public_usage_id > CAST(%s AS TEXT))
          )
        ORDER BY e.created_at DESC, e.public_usage_id ASC
        LIMIT %s
    """

    _ALL_USAGE_QUERY = """
        SELECT e.public_usage_id,
               e.kind,
               e.model,
               e.quantity,
               e.unit,
               e.charge,
               e.status,
               e.created_at
        FROM openclaw_account.billing_usage_events AS e
        LEFT JOIN openclaw_account.model_price_versions AS price_version
          ON price_version.id = e.price_version_id
        WHERE e.tenant_id = %s
        ORDER BY e.created_at ASC, e.public_usage_id ASC
    """

    _IDEMPOTENCY_LOOKUP = """
        SELECT request_checksum, response_json
        FROM media_product.b08_redemption_idempotency
        WHERE tenant_id = %s AND operation = %s AND idempotency_key = %s
        FOR UPDATE
    """

    _IDEMPOTENCY_INSERT = """
        INSERT INTO media_product.b08_redemption_idempotency(
            tenant_id, operation, idempotency_key, request_checksum, response_json
        ) VALUES (%s, %s, %s, %s, CAST(%s AS jsonb))
        ON CONFLICT (tenant_id, operation, idempotency_key) DO NOTHING
    """

    _IMAGE_USAGE_BY_SOURCE_QUERY = """
        SELECT event_public_id,
               kind,
               model,
               quantity,
               unit,
               charge,
               status,
               created_at
        FROM openclaw_account.usage_events
        WHERE tenant_id = %s
          AND source_type = %s
          AND source_id = %s
        FOR UPDATE
    """

    _IMAGE_USAGE_INSERT = """
        INSERT INTO openclaw_account.usage_events(
            tenant_id,
            event_public_id,
            kind,
            quantity,
            model,
            unit,
            charge,
            currency,
            status,
            source_type,
            source_id,
            price_version_id
        ) VALUES (%s, %s, 'image', %s, %s, 'images', %s, 'credit', %s, %s, %s, %s)
        ON CONFLICT (tenant_id, source_type, source_id) DO NOTHING
        RETURNING event_public_id,
                  kind,
                  model,
                  quantity,
                  unit,
                  charge,
                  status,
                  created_at
    """

    _REDEMPTION_READBACK_QUERY = """
        SELECT f.status, f.completed_at, w.version
        FROM openclaw_account.fulfillments AS f
        JOIN openclaw_account.wallet_accounts AS w
          ON w.id = f.wallet_account_id
         AND w.tenant_id = f.tenant_id
        WHERE f.id = %s
          AND f.tenant_id = %s
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        cursor_secret: bytes,
        redemption_service: RedemptionService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(cursor_secret) < 16:
            raise ValueError("B08 cursor secret must be at least 16 bytes")
        self._connection_factory = connection_factory
        self._cursor_key = hashlib.sha256(bytes(cursor_secret)).digest()
        self._redemption_service = redemption_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_billing_balance(self, context: TenantContext) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        try:
            with self._connection_factory() as connection:
                row = connection.execute(self._BALANCE_QUERY, (tenant_id,)).fetchone()
        except UsageBillingError:
            raise
        except Exception as exc:
            raise UsageBillingInternalError() from exc
        if row is None:
            raise UsageBillingNotFound()
        available, as_of, revision = row
        amount = _decimal(available, "balance available")
        timestamp = _timestamp(as_of, "balance asOf")
        version = _nonnegative_int(revision, "balance revision")
        return public_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": version,
                "balance": {
                    "available": _decimal_text(amount),
                    "currency": "credit",
                    "asOf": timestamp.isoformat(),
                    "revision": version,
                },
            }
        )

    def list_billing_balance_packs(self, context: TenantContext) -> dict[str, Any]:
        self._tenant_id(context)
        try:
            with self._connection_factory() as connection:
                rows = connection.execute(self._BALANCE_PACKS_QUERY).fetchall()
        except UsageBillingError:
            raise
        except Exception as exc:
            raise UsageBillingInternalError() from exc
        items: list[dict[str, Any]] = []
        revision = 0
        for row in rows:
            if len(row) < 9:
                raise UsageBillingInternalError("billing balance pack row is incomplete")
            code, name, credit_amount, price, currency, audience, product_kind, row_revision, purchase_url = row[:9]
            if not isinstance(code, str) or not code or not isinstance(name, str) or not name:
                raise UsageBillingInternalError("billing balance pack identity is invalid")
            if currency != "credit":
                raise UsageBillingInternalError("billing balance pack currency is invalid")
            if audience != "all" or product_kind != "balance_pack":
                raise UsageBillingInternalError("billing balance pack classification is invalid")
            if purchase_url is not None and (not isinstance(purchase_url, str) or not purchase_url):
                raise UsageBillingInternalError("billing balance pack purchase URL is invalid")
            revision = max(revision, _nonnegative_int(row_revision, "billing balance pack revision"))
            items.append(
                {
                    "balancePackCode": code,
                    "name": name,
                    "creditAmount": _number(_nonnegative_decimal(credit_amount, "balance pack credit amount")),
                    "priceCny": _fixed_decimal_text(_nonnegative_decimal(price, "balance pack price"), PRICE_QUANTUM),
                    "currency": "credit",
                    "audience": audience,
                    "productKind": product_kind,
                    "purchaseAvailable": purchase_url is not None,
                    "purchaseUrl": purchase_url,
                }
            )
        return public_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": revision,
                "items": items,
                "nextCursor": None,
            }
        )

    def list_billing_usage(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        size = _page_size(page_size)
        position = self._decode_cursor(cursor, tenant_id) if cursor else None
        if position is None:
            params = (tenant_id, None, None, None, None, size + 1)
        else:
            params = (
                tenant_id,
                position.created_at,
                position.created_at,
                position.created_at,
                position.public_usage_id,
                size + 1,
            )
        try:
            with self._connection_factory() as connection:
                rows = connection.execute(self._USAGE_QUERY, params).fetchall()
        except UsageBillingError:
            raise
        except Exception as exc:
            raise UsageBillingInternalError() from exc
        parsed = [self._parse_usage_row(row) for row in rows]
        stream_revision = _nonnegative_int(rows[0][8], "usage revision") if rows and len(rows[0]) > 8 else len(parsed)
        has_next = len(parsed) > size
        visible = parsed[:size]
        next_cursor = None
        if has_next:
            last = visible[-1]
            next_cursor = self._encode_cursor(
                UsageCursor(tenant_id, last.created_at, last.public_usage_id)
            )
        return public_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": stream_revision,
                "items": [self._usage_projection(row) for row in visible],
                "nextCursor": next_cursor,
            }
        )

    def get_billing_usage_summary(
        self,
        context: TenantContext,
        *,
        timezone_name: str = DEFAULT_TIMEZONE,
    ) -> dict[str, Any]:
        rows = self._load_all_usage(context)
        self._timezone(timezone_name)
        text_quantity, image_quantity, total_charge = _totals(rows)
        start, end = _range(rows, self._clock())
        return public_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": len(rows),
                "summary": {
                    "textQuantity": _number(text_quantity),
                    "imageQuantity": _number(image_quantity),
                    "totalCharge": _decimal_text(total_charge),
                    "currency": "credit",
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "revision": len(rows),
                },
            }
        )

    def daily_usage_summary(
        self,
        context: TenantContext,
        *,
        timezone_name: str = DEFAULT_TIMEZONE,
    ) -> list[dict[str, Any]]:
        zone = self._timezone(timezone_name)
        buckets: dict[str, dict[str, Decimal]] = {}
        for row in self._load_all_usage(context):
            if row.kind not in {"text", "image"} or row.status != "succeeded":
                continue
            date_key = row.created_at.astimezone(zone).date().isoformat()
            bucket = buckets.setdefault(
                date_key,
                {"text": Decimal(0), "image": Decimal(0), "charge": Decimal(0)},
            )
            bucket[row.kind] += row.quantity
            bucket["charge"] += row.charge
        return [
            {
                "date": date_key,
                "textQuantity": _number(values["text"]),
                "imageQuantity": _number(values["image"]),
                "totalCharge": _decimal_text(values["charge"]),
            }
            for date_key, values in sorted(buckets.items())
        ]

    def record_image_usage_event(
        self,
        context: TenantContext,
        *,
        public_usage_id: str,
        model: str,
        quantity: Decimal | int | float | str,
        charge: Decimal | int | float | str | None,
        source_type: str,
        source_id: str,
        status: str = "succeeded",
        price_version_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        """Append one image event and return the row read back from PostgreSQL."""
        tenant_id = self._tenant_id(context)
        if not isinstance(public_usage_id, str) or not _PUBLIC_ID.fullmatch(public_usage_id):
            raise UsageBillingInvalidRequest("publicUsageId is invalid", field="publicUsageId")
        _require_text(model, "model")
        _require_text(source_type, "sourceType", max_length=96)
        source_uuid = _uuid_text(source_id, "sourceId")
        if status not in _STATUSES:
            raise UsageBillingInvalidRequest("status is invalid", field="status")
        parsed_quantity = _decimal(quantity, "quantity")
        if parsed_quantity <= 0:
            raise UsageBillingInvalidRequest("quantity must be greater than zero", field="quantity")
        parsed_charge = None if charge is None else _decimal(charge, "charge")
        if parsed_charge is not None and parsed_charge < 0:
            raise UsageBillingInvalidRequest("charge must not be negative", field="charge")
        if status == "succeeded" and parsed_charge is None:
            raise UsageBillingInvalidRequest("charge is required for succeeded events", field="charge")
        price_uuid = _uuid_text(price_version_id, "priceVersionId") if price_version_id is not None else None
        params = (
            tenant_id,
            public_usage_id,
            parsed_quantity,
            model.strip(),
            parsed_charge,
            status,
            source_type.strip(),
            source_uuid,
            price_uuid,
        )
        try:
            with self._connection_factory() as connection:
                existing = connection.execute(
                    self._IMAGE_USAGE_BY_SOURCE_QUERY,
                    (tenant_id, source_type.strip(), source_uuid),
                ).fetchone()
                if existing is None:
                    existing = connection.execute(self._IMAGE_USAGE_INSERT, params).fetchone()
                if existing is None:
                    existing = connection.execute(
                        self._IMAGE_USAGE_BY_SOURCE_QUERY,
                        (tenant_id, source_type.strip(), source_uuid),
                    ).fetchone()
        except UsageBillingError:
            raise
        except Exception as exc:
            raise UsageBillingInternalError() from exc
        if existing is None:
            raise UsageBillingInternalError("image usage event readback is missing")
        row = self._parse_usage_row(existing)
        if row.public_usage_id != public_usage_id:
            raise UsageBillingConflict("image usage source is already bound to another event")
        if row.model != model.strip() or row.quantity != parsed_quantity or row.status != status:
            raise UsageBillingConflict("image usage event is immutable")
        return public_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": 1,
                "item": self._usage_projection(row),
            }
        )

    def redeem_billing_code(
        self,
        context: TenantContext,
        *,
        code: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        user_id = self._user_id(context)
        _require_text(code, "redemption code", max_length=128)
        _require_key(idempotency_key, "Idempotency-Key")
        if self._redemption_service is None:
            raise UsageBillingInternalError("redemption service is unavailable")
        request_checksum = hashlib.sha256(
            json.dumps({"code": code}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        operation = "redeemBillingCode"
        try:
            with self._connection_factory() as connection:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"b08:{tenant_id}:{operation}:{idempotency_key}",),
                )
                existing = connection.execute(
                    self._IDEMPOTENCY_LOOKUP,
                    (tenant_id, operation, idempotency_key),
                ).fetchone()
                if existing is not None:
                    stored_checksum, stored_response = existing[:2]
                    if stored_checksum != request_checksum:
                        raise UsageBillingConflict()
                    return public_projection(_json_object(stored_response, "idempotent redemption response"))
                result = self._redemption_service.redeem(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    code=code,
                )
                fulfillment_id = _uuid_text(_result_value(result, "fulfillment_id"), "fulfillmentId")
                readback = connection.execute(
                    self._REDEMPTION_READBACK_QUERY,
                    (fulfillment_id, tenant_id),
                ).fetchone()
                if readback is None or len(readback) < 3 or readback[0] != "succeeded":
                    raise UsageBillingInternalError("redemption readback is incomplete")
                completed_at = _timestamp(readback[1], "redemption updatedAt")
                revision = _nonnegative_int(readback[2], "redemption revision")
                response = {
                    "schemaVersion": SCHEMA_VERSION,
                    "revision": revision,
                    "ok": True,
                    "updatedAt": completed_at.isoformat(),
                }
                connection.execute(
                    self._IDEMPOTENCY_INSERT,
                    (
                        tenant_id,
                        operation,
                        idempotency_key,
                        request_checksum,
                        json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    ),
                )
                return public_projection(response)
        except UsageBillingError:
            raise
        except Exception as exc:
            raise UsageBillingInternalError() from exc

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, UsageBillingError):
            return {"error": {"code": error.code, "message": error.message, "field": error.field}}
        return {"error": {"code": "internal_error", "message": "billing data is unavailable", "field": None}}

    @staticmethod
    def error_status(error: BaseException) -> int:
        return error.status if isinstance(error, UsageBillingError) else 500

    def _tenant_id(self, context: TenantContext) -> str:
        try:
            checked = require_context(context)
            if checked.is_admin:
                raise UsageBillingForbidden()
            tenant = UUID(checked.tenant_id)
        except UsageBillingError:
            raise
        except Exception as exc:
            raise UsageBillingForbidden() from exc
        return str(tenant)

    def _user_id(self, context: TenantContext) -> str:
        try:
            checked = require_context(context)
            return str(UUID(checked.user_public_id))
        except Exception as exc:
            raise UsageBillingForbidden() from exc

    def _load_all_usage(self, context: TenantContext) -> list[_UsageRow]:
        tenant_id = self._tenant_id(context)
        try:
            with self._connection_factory() as connection:
                rows = connection.execute(self._ALL_USAGE_QUERY, (tenant_id,)).fetchall()
        except UsageBillingError:
            raise
        except Exception as exc:
            raise UsageBillingInternalError() from exc
        return [self._parse_usage_row(row) for row in rows]

    @staticmethod
    def _parse_usage_row(row: Any) -> _UsageRow:
        if not isinstance(row, (tuple, list)) or len(row) < 8:
            raise UsageBillingInternalError("billing usage row is incomplete")
        public_usage_id, kind, model, quantity, unit, charge, status, created_at = row[:8]
        if not isinstance(public_usage_id, str) or not _PUBLIC_ID.fullmatch(public_usage_id):
            raise UsageBillingInternalError("billing usage identifier is invalid")
        if kind not in _KINDS:
            raise UsageBillingInternalError("billing usage kind is invalid")
        if not isinstance(model, str) or not model.strip():
            raise UsageBillingInternalError("billing usage model is invalid")
        if unit not in _UNITS:
            raise UsageBillingInternalError("billing usage unit is invalid")
        if status not in _STATUSES:
            raise UsageBillingInternalError("billing usage status is invalid")
        parsed_charge = _decimal(charge, "billing usage charge")
        parsed_quantity = _decimal(quantity, "billing usage quantity")
        timestamp = _timestamp(created_at, "billing usage createdAt")
        if parsed_quantity < 0 and kind != "compensation":
            raise UsageBillingInternalError("billing usage quantity is negative")
        if parsed_charge < 0 and kind != "compensation":
            raise UsageBillingInternalError("billing usage charge is negative")
        return _UsageRow(
            public_usage_id,
            kind,
            model,
            parsed_quantity,
            unit,
            parsed_charge,
            status,
            timestamp,
        )

    @staticmethod
    def _usage_projection(row: _UsageRow) -> dict[str, Any]:
        return {
            "publicUsageId": row.public_usage_id,
            "kind": row.kind,
            "model": row.model,
            "quantity": _number(row.quantity),
            "unit": row.unit,
            "charge": _decimal_text(row.charge),
            "status": row.status,
            "createdAt": row.created_at.isoformat(),
        }

    def _encode_cursor(self, cursor: UsageCursor) -> str:
        payload = {
            "tenantId": str(cursor.tenant_id),
            "createdAt": cursor.created_at.isoformat(),
            "publicUsageId": cursor.public_usage_id,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self._cursor_key, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw + b"." + signature).decode().rstrip("=")

    def _decode_cursor(self, value: str, tenant_id: str) -> UsageCursor:
        if not isinstance(value, str) or not value:
            raise UsageBillingInvalidRequest("cursor is invalid", field="cursor")
        try:
            padded = value + "=" * (-len(value) % 4)
            raw, signature = base64.urlsafe_b64decode(padded.encode()).rsplit(b".", 1)
            expected = hmac.new(self._cursor_key, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("cursor signature")
            payload = json.loads(raw.decode())
            if payload.get("tenantId") != tenant_id:
                raise ValueError("cursor tenant")
            created_at = _timestamp(datetime.fromisoformat(payload["createdAt"]), "cursor createdAt")
            public_usage_id = payload["publicUsageId"]
            if not isinstance(public_usage_id, str) or not _PUBLIC_ID.fullmatch(public_usage_id):
                raise ValueError("cursor id")
            return UsageCursor(UUID(tenant_id), created_at, public_usage_id)
        except Exception as exc:
            raise UsageBillingInvalidRequest("cursor is invalid", field="cursor") from exc

    @staticmethod
    def _timezone(timezone_name: str) -> ZoneInfo:
        if not isinstance(timezone_name, str) or not timezone_name.strip():
            raise UsageBillingInvalidRequest("timezone is invalid", field="timezone")
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise UsageBillingInvalidRequest("timezone is invalid", field="timezone") from exc

    def _now(self) -> datetime:
        value = self._clock()
        return _timestamp(value, "clock")


def _page_size(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGE_SIZE:
        raise UsageBillingInvalidRequest("pageSize must be between 1 and 100", field="pageSize")
    return value


def _require_text(value: str, label: str, *, max_length: int | None = None) -> None:
    if not isinstance(value, str) or not value or value != value.strip() or (max_length is not None and len(value) > max_length):
        raise UsageBillingInvalidRequest(f"{label} is invalid", field=label)


def _require_key(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_KEY.fullmatch(value):
        raise UsageBillingInvalidRequest(f"{label} is invalid", field=label)


def _decimal(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise UsageBillingInternalError(f"{label} is unknown")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise UsageBillingInternalError(f"{label} is invalid") from exc
    if not parsed.is_finite():
        raise UsageBillingInternalError(f"{label} is invalid")
    return parsed


def _nonnegative_decimal(value: Any, label: str) -> Decimal:
    parsed = _decimal(value, label)
    if parsed < 0:
        raise UsageBillingInternalError(f"{label} is negative")
    return parsed


def _decimal_text(value: Decimal) -> str:
    return _fixed_decimal_text(value, MONEY_QUANTUM)


def _fixed_decimal_text(value: Decimal, quantum: Decimal) -> str:
    return format(value.quantize(quantum), "f")


def _number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _nonnegative_int(value: Any, label: str) -> int:
    parsed = _decimal(value, label)
    if parsed < 0 or parsed != parsed.to_integral_value():
        raise UsageBillingInternalError(f"{label} is invalid")
    return int(parsed)


def _timestamp_error(label: str, reason: str) -> Exception:
    return UsageBillingInternalError(f"{label} is invalid")


def _timestamp(value: Any, label: str) -> datetime:
    # Unlike its siblings in assets.py/tracks.py/invites.py/runs.py, this one
    # never accepted an ISO string -- only an already-parsed datetime -- so
    # that acceptance rule is kept as an explicit guard in front of
    # coerce_utc rather than folded into it.
    if not isinstance(value, datetime):
        raise _timestamp_error(label, "missing")
    return foundation.coerce_utc(value, label, error=_timestamp_error, allow_naive=False)


def _totals(rows: list[_UsageRow]) -> tuple[Decimal, Decimal, Decimal]:
    text = Decimal(0)
    image = Decimal(0)
    charge = Decimal(0)
    for row in rows:
        if row.kind == "text" and row.status == "succeeded":
            text += row.quantity
        if row.kind == "image" and row.status == "succeeded":
            image += row.quantity
        if row.kind in {"text", "image", "compensation"} and row.status in {"succeeded", "compensated"}:
            charge += row.charge
    return text, image, charge.quantize(MONEY_QUANTUM)


def _uuid_text(value: Any, label: str) -> str:
    try:
        parsed = UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise UsageBillingInvalidRequest(f"{label} is invalid", field=label) from exc
    return str(parsed)


def _result_value(result: Any, name: str) -> Any:
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)

def _range(rows: list[_UsageRow], now: datetime) -> tuple[datetime, datetime]:
    if not rows:
        current = _timestamp(now, "clock")
        return current, current
    timestamps = [row.created_at for row in rows]
    return min(timestamps), max(timestamps)


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise UsageBillingInternalError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise UsageBillingInternalError(f"{label} is invalid")
    return value
