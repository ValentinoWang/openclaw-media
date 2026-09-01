from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from typing import Any
from uuid import UUID, uuid4

from ..account.database import AccountDatabase
from ..account.errors import AccountError
from .retail_ledger import post_ledger_entry


MONEY_QUANTUM = Decimal("0.00000001")
FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class RetailBillingError(AccountError):
    def __init__(self, code: str, detail: str) -> None:
        status = {
            "insufficient_balance": 402,
            "billing_actor_forbidden": 403,
            "idempotency_conflict": 409,
            "usage_reconciliation_pending": 409,
            "model_price_unavailable": 503,
            "billing_state_conflict": 503,
            "invalid_usage": 503,
        }.get(code, 503)
        super().__init__(code, detail, status=status)


@dataclass(frozen=True)
class OperationReservation:
    operation_id: UUID
    request_ref_id: UUID
    hold_amount: Decimal


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int


def parse_usage(payload: dict[str, Any] | None) -> Usage:
    raw = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raise RetailBillingError("invalid_usage", "上游响应缺少实际用量。")
    details = raw.get("input_tokens_details")
    cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    values = (raw.get("input_tokens"), cached, raw.get("output_tokens"))
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise RetailBillingError("invalid_usage", "上游响应的实际用量无效。")
    if cached > values[0]:
        raise RetailBillingError("invalid_usage", "上游缓存用量超过输入用量。")
    return Usage(values[0], cached, values[2])


class RetailBillingService:
    def __init__(self, database: AccountDatabase, *, hold_ttl_seconds: int = 900) -> None:
        if not 60 <= hold_ttl_seconds <= 86400:
            raise ValueError("hold ttl must be between 60 and 86400 seconds")
        self.database = database
        self.hold_ttl_seconds = hold_ttl_seconds

    @staticmethod
    def _tenant(value: str) -> UUID:
        try:
            tenant = UUID(value)
        except ValueError as exc:
            raise RetailBillingError("billing_state_conflict", "租户身份无效。") from exc
        if str(tenant) != value:
            raise RetailBillingError("billing_state_conflict", "租户身份无效。")
        return tenant

    @staticmethod
    def _charge(
        usage: Usage,
        input_price: Decimal,
        cached_price: Decimal,
        output_price: Decimal,
    ) -> Decimal:
        uncached = usage.input_tokens - usage.cached_input_tokens
        amount = (
            Decimal(uncached) * input_price
            + Decimal(usage.cached_input_tokens) * cached_price
            + Decimal(usage.output_tokens) * output_price
        ) / Decimal(1_000_000)
        return amount.quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)

    def reserve(
        self,
        *,
        tenant_id: str,
        actor_user_id: str,
        scope: str,
        idempotency_key: str,
        request_fingerprint: str,
        model: str,
        correlation_key: str,
        max_input_tokens: int,
        max_output_tokens: int,
    ) -> OperationReservation:
        tenant = self._tenant(tenant_id)
        actor = self._tenant(actor_user_id)
        if not FINGERPRINT.fullmatch(request_fingerprint):
            raise RetailBillingError("billing_state_conflict", "模型请求指纹无效。")
        if not 1 <= len(scope) <= 128 or not 1 <= len(idempotency_key) <= 128:
            raise RetailBillingError("billing_state_conflict", "模型幂等身份无效。")
        if not 16 <= len(correlation_key) <= 128:
            raise RetailBillingError("billing_state_conflict", "模型关联键无效。")
        if max_input_tokens <= 0 or max_output_tokens <= 0:
            raise RetailBillingError("billing_state_conflict", "模型额度上限无效。")

        operation_id = uuid4()
        hold_id = uuid4()
        request_ref_id = uuid4()
        ledger_id = uuid4()
        with self.database.connect() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{tenant}:{scope}:{idempotency_key}",),
            )
            active_actor = connection.execute(
                """
                SELECT 1
                FROM openclaw_account.tenant_members
                WHERE tenant_id = %s AND user_id = %s AND status = 'active'
                FOR SHARE
                """,
                (tenant, actor),
            ).fetchone()
            if active_actor is None:
                raise RetailBillingError(
                    "billing_actor_forbidden",
                    "模型请求发起人不属于当前租户。",
                )
            existing = connection.execute(
                """
                SELECT id, request_fingerprint, status, actor_user_id
                FROM openclaw_account.model_operations
                WHERE tenant_id = %s AND scope = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (tenant, scope, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing[3] != actor:
                    raise RetailBillingError("idempotency_conflict", "幂等键已绑定其他模型请求。")
                if str(existing[1]) != request_fingerprint:
                    raise RetailBillingError("idempotency_conflict", "幂等键已绑定其他模型请求。")
                raise RetailBillingError(
                    "usage_reconciliation_pending",
                    "模型请求已存在，禁止重复提交。",
                )
            price = connection.execute(
                """
                SELECT id, input_price_per_million, cached_input_price_per_million,
                       output_price_per_million
                FROM openclaw_account.model_price_versions
                WHERE model = %s AND effective_at <= now()
                  AND (retired_at IS NULL OR retired_at > now())
                ORDER BY effective_at DESC LIMIT 1
                """,
                (model,),
            ).fetchone()
            if price is None:
                raise RetailBillingError("model_price_unavailable", "模型零售价格不可用。")
            input_price, cached_price, output_price = (Decimal(price[1]), Decimal(price[2]), Decimal(price[3]))
            if cached_price > input_price:
                raise RetailBillingError("model_price_unavailable", "模型零售价格无效。")
            maximum = self._charge(
                Usage(max_input_tokens, 0, max_output_tokens),
                input_price,
                cached_price,
                output_price,
            )
            if maximum <= 0:
                raise RetailBillingError("model_price_unavailable", "模型零售价格无效。")
            wallet = connection.execute(
                """
                SELECT id, available, reserved
                FROM openclaw_account.wallet_accounts
                WHERE tenant_id = %s FOR UPDATE
                """,
                (tenant,),
            ).fetchone()
            if wallet is None:
                raise RetailBillingError("billing_state_conflict", "租户钱包不可用。")
            available, reserved = Decimal(wallet[1]), Decimal(wallet[2])
            if available < maximum:
                raise RetailBillingError("insufficient_balance", "余额不足，无法冻结本次模型额度。")
            available_after = available - maximum
            reserved_after = reserved + maximum
            connection.execute(
                """
                UPDATE openclaw_account.wallet_accounts
                SET available = %s, reserved = %s, version = version + 1, updated_at = now()
                WHERE id = %s
                """,
                (available_after, reserved_after, wallet[0]),
            )
            connection.execute(
                """
                INSERT INTO openclaw_account.fund_holds(
                    id, tenant_id, wallet_account_id, amount, idempotency_key, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    hold_id,
                    tenant,
                    wallet[0],
                    maximum,
                    idempotency_key,
                    datetime.now(timezone.utc) + timedelta(seconds=self.hold_ttl_seconds),
                ),
            )
            post_ledger_entry(
                connection,
                entry_id=ledger_id,
                tenant_id=tenant,
                wallet_account_id=wallet[0],
                entry_type="reserve",
                available_delta=-maximum,
                reserved_delta=maximum,
                available_after=available_after,
                reserved_after=reserved_after,
                source_type="model_hold",
                source_id=hold_id,
                idempotency_key=f"reserve:{idempotency_key}",
            )
            connection.execute(
                """
                INSERT INTO openclaw_account.model_operations(
                    id, tenant_id, actor_user_id, scope, idempotency_key, request_fingerprint,
                    fund_hold_id, price_version_id, requested_model
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    operation_id,
                    tenant,
                    actor,
                    scope,
                    idempotency_key,
                    request_fingerprint,
                    hold_id,
                    price[0],
                    model,
                ),
            )
            connection.execute(
                """
                INSERT INTO openclaw_account.upstream_request_refs(
                    id, operation_id, tenant_id, provider, correlation_key
                ) VALUES (%s,%s,%s,'sub2api',%s)
                """,
                (request_ref_id, operation_id, tenant, correlation_key),
            )
        return OperationReservation(operation_id, request_ref_id, maximum)

    def settle(
        self,
        operation_id: UUID,
        *,
        usage: Usage,
        upstream_request_id: str | None,
        upstream_model: str | None,
        actual_cost: Decimal | None = None,
    ) -> Decimal:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT o.status, o.tenant_id, o.fund_hold_id, o.price_version_id,
                       h.wallet_account_id, h.amount, h.status,
                       p.input_price_per_million, p.cached_input_price_per_million,
                       p.output_price_per_million, r.id
                FROM openclaw_account.model_operations o
                JOIN openclaw_account.fund_holds h ON h.id = o.fund_hold_id
                JOIN openclaw_account.model_price_versions p ON p.id = o.price_version_id
                JOIN openclaw_account.upstream_request_refs r ON r.operation_id = o.id
                WHERE o.id = %s
                FOR UPDATE OF o, h, r
                """,
                (operation_id,),
            ).fetchone()
            if row is None or (row[0], row[6]) not in {
                ("pending", "pending"),
                ("unknown_reconcile", "pending_manual"),
            }:
                raise RetailBillingError("billing_state_conflict", "模型结算状态冲突。")
            if actual_cost is not None and actual_cost < 0:
                raise RetailBillingError("invalid_usage", "上游实际成本无效。")
            charge = self._charge(usage, Decimal(row[7]), Decimal(row[8]), Decimal(row[9]))
            hold_amount = Decimal(row[5])
            if charge > hold_amount:
                raise RetailBillingError("usage_reconciliation_pending", "实际用量超过冻结上限，需要人工对账。")
            wallet = connection.execute(
                "SELECT available, reserved FROM openclaw_account.wallet_accounts WHERE id = %s FOR UPDATE",
                (row[4],),
            ).fetchone()
            if wallet is None or Decimal(wallet[1]) < hold_amount:
                raise RetailBillingError("billing_state_conflict", "钱包冻结余额无效。")
            available_after = Decimal(wallet[0]) + hold_amount - charge
            reserved_after = Decimal(wallet[1]) - hold_amount
            connection.execute(
                "UPDATE openclaw_account.wallet_accounts SET available=%s,reserved=%s,version=version+1,updated_at=now() WHERE id=%s",
                (available_after, reserved_after, row[4]),
            )
            post_ledger_entry(
                connection,
                entry_id=uuid4(),
                tenant_id=row[1],
                wallet_account_id=row[4],
                entry_type="settle",
                available_delta=hold_amount - charge,
                reserved_delta=-hold_amount,
                available_after=available_after,
                reserved_after=reserved_after,
                source_type="model_operation",
                source_id=operation_id,
                idempotency_key=f"settle:{operation_id}",
            )
            connection.execute(
                "UPDATE openclaw_account.fund_holds SET status='captured',updated_at=now() WHERE id=%s",
                (row[2],),
            )
            safe_result = json.dumps(
                {
                    "inputTokens": usage.input_tokens,
                    "cachedInputTokens": usage.cached_input_tokens,
                    "outputTokens": usage.output_tokens,
                    "charge": str(charge),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            connection.execute(
                """
                UPDATE openclaw_account.model_operations
                SET status='succeeded',upstream_model=%s,input_tokens=%s,cached_input_tokens=%s,
                    output_tokens=%s,actual_charge=%s,safe_result=%s::jsonb,updated_at=now(),completed_at=now()
                WHERE id=%s
                """,
                (
                    upstream_model, usage.input_tokens, usage.cached_input_tokens,
                    usage.output_tokens, charge, safe_result, operation_id,
                ),
            )
            connection.execute(
                """
                UPDATE openclaw_account.upstream_request_refs
                SET status='succeeded',upstream_request_id=%s,input_tokens=%s,cached_input_tokens=%s,
                    output_tokens=%s,actual_cost=%s,updated_at=now() WHERE id=%s
                """,
                (
                    upstream_request_id, usage.input_tokens, usage.cached_input_tokens,
                    usage.output_tokens, actual_cost, row[10],
                ),
            )
            connection.execute(
                """
                INSERT INTO openclaw_account.usage_charges(
                    id,operation_id,tenant_id,upstream_request_ref_id,price_version_id,
                    input_tokens,cached_input_tokens,output_tokens,amount
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    uuid4(), operation_id, row[1], row[10], row[3], usage.input_tokens,
                    usage.cached_input_tokens, usage.output_tokens, charge,
                ),
            )
        return charge

    def release(self, operation_id: UUID, *, error_code: str) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT o.status,o.tenant_id,o.fund_hold_id,h.wallet_account_id,h.amount,h.status,r.id
                FROM openclaw_account.model_operations o
                JOIN openclaw_account.fund_holds h ON h.id=o.fund_hold_id
                JOIN openclaw_account.upstream_request_refs r ON r.operation_id=o.id
                WHERE o.id=%s FOR UPDATE OF o,h,r
                """,
                (operation_id,),
            ).fetchone()
            if row is None or row[0] != "pending" or row[5] != "pending":
                raise RetailBillingError("billing_state_conflict", "模型释放状态冲突。")
            wallet = connection.execute(
                "SELECT available,reserved FROM openclaw_account.wallet_accounts WHERE id=%s FOR UPDATE",
                (row[3],),
            ).fetchone()
            amount = Decimal(row[4])
            if wallet is None or Decimal(wallet[1]) < amount:
                raise RetailBillingError("billing_state_conflict", "钱包冻结余额无效。")
            available_after = Decimal(wallet[0]) + amount
            reserved_after = Decimal(wallet[1]) - amount
            connection.execute(
                "UPDATE openclaw_account.wallet_accounts SET available=%s,reserved=%s,version=version+1,updated_at=now() WHERE id=%s",
                (available_after, reserved_after, row[3]),
            )
            post_ledger_entry(
                connection,
                entry_id=uuid4(),
                tenant_id=row[1],
                wallet_account_id=row[3],
                entry_type="release",
                available_delta=amount,
                reserved_delta=-amount,
                available_after=available_after,
                reserved_after=reserved_after,
                source_type="model_operation",
                source_id=operation_id,
                idempotency_key=f"release:{operation_id}",
            )
            connection.execute("UPDATE openclaw_account.fund_holds SET status='released',updated_at=now() WHERE id=%s", (row[2],))
            connection.execute(
                "UPDATE openclaw_account.model_operations SET status='failed',error_code=%s,updated_at=now(),completed_at=now() WHERE id=%s",
                (error_code[:96], operation_id),
            )
            connection.execute(
                "UPDATE openclaw_account.upstream_request_refs SET status='failed',updated_at=now() WHERE id=%s",
                (row[6],),
            )

    def mark_unknown(self, operation_id: UUID, *, upstream_request_id: str | None = None) -> None:
        with self.database.connect() as connection:
            updated = connection.execute(
                """
                UPDATE openclaw_account.model_operations
                SET status='unknown_reconcile',error_code='model_settlement_unknown',updated_at=now(),completed_at=now()
                WHERE id=%s AND status='pending'
                """,
                (operation_id,),
            )
            if updated.rowcount != 1:
                raise RetailBillingError("billing_state_conflict", "模型未知结算状态冲突。")
            connection.execute(
                "UPDATE openclaw_account.fund_holds SET status='pending_manual',updated_at=now() WHERE id=(SELECT fund_hold_id FROM openclaw_account.model_operations WHERE id=%s)",
                (operation_id,),
            )
            connection.execute(
                "UPDATE openclaw_account.upstream_request_refs SET status='unknown_reconcile',upstream_request_id=COALESCE(%s,upstream_request_id),updated_at=now() WHERE operation_id=%s",
                (upstream_request_id, operation_id),
            )

    def task_calls(self, tenant_id: str, scope: str) -> list[dict[str, Any]]:
        tenant = self._tenant(tenant_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.idempotency_key,u.id,o.status,o.updated_at
                FROM openclaw_account.model_operations o
                LEFT JOIN openclaw_account.usage_charges u ON u.operation_id=o.id
                WHERE o.tenant_id=%s AND o.scope=%s ORDER BY o.created_at
                """,
                (tenant, scope),
            ).fetchall()
        return [
            {
                "requestId": str(row[0]),
                "usageId": str(row[1]) if row[1] is not None else None,
                "status": str(row[2]),
                "updatedAt": row[3].isoformat(),
            }
            for row in rows
        ]

    def balance(self, tenant_id: str) -> dict[str, str]:
        tenant = self._tenant(tenant_id)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT available,reserved FROM openclaw_account.wallet_accounts WHERE tenant_id=%s",
                (tenant,),
            ).fetchone()
        if row is None:
            raise RetailBillingError("billing_state_conflict", "租户钱包不可用。")
        return {"available": str(row[0]), "reserved": str(row[1]), "currency": "credit"}

    def usage(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        tenant = self._tenant(tenant_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,o.requested_model,o.status,o.input_tokens,o.cached_input_tokens,
                       o.output_tokens,o.actual_charge,o.created_at
                FROM openclaw_account.model_operations o
                WHERE o.tenant_id=%s ORDER BY o.created_at DESC LIMIT %s
                """,
                (tenant, max(1, min(limit, 1000))),
            ).fetchall()
        return [
            {
                "operationId": str(row[0]), "model": str(row[1]), "status": str(row[2]),
                "inputTokens": row[3], "cachedInputTokens": row[4], "outputTokens": row[5],
                "charge": str(row[6]) if row[6] is not None else None, "createdAt": row[7].isoformat(),
            }
            for row in rows
        ]

    def reconciliation_queue(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,o.tenant_id,o.requested_model,r.correlation_key,r.upstream_request_id,o.created_at
                FROM openclaw_account.model_operations o
                JOIN openclaw_account.upstream_request_refs r ON r.operation_id=o.id
                WHERE o.status='unknown_reconcile' ORDER BY o.created_at LIMIT %s
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()
        return [
            {
                "operationId": str(row[0]), "tenantId": str(row[1]), "model": str(row[2]),
                "correlationKey": str(row[3]), "upstreamRequestId": row[4], "createdAt": row[5].isoformat(),
            }
            for row in rows
        ]

    def reconciliation_target(self, operation_id: str) -> tuple[UUID, str]:
        try:
            operation = UUID(operation_id)
        except ValueError as exc:
            raise RetailBillingError("billing_state_conflict", "对账操作身份无效。") from exc
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT r.upstream_request_id,r.correlation_key
                FROM openclaw_account.model_operations o
                JOIN openclaw_account.upstream_request_refs r ON r.operation_id=o.id
                WHERE o.id=%s AND o.status='unknown_reconcile'
                """,
                (operation,),
            ).fetchone()
        if row is None:
            raise RetailBillingError("billing_state_conflict", "对账操作不存在或状态已变化。")
        return operation, str(row[0] or row[1])
