from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from ..account.database import AccountDatabase
from ..account.errors import AccountError


MONEY_QUANTUM = Decimal("0.00000001")
MAX_ADMIN_GRANT = Decimal("100000.00000000")


class RetailAdminError(AccountError):
    def __init__(self, code: str, detail: str) -> None:
        status = {
            "admin_grant_invalid": 400,
            "product_mapping_invalid": 400,
            "plan_not_found": 404,
            "tenant_not_found": 404,
            "idempotency_conflict": 409,
            "product_mapping_conflict": 409,
        }.get(code, 503)
        super().__init__(code, detail, status=status)


class RetailAdminService:
    def __init__(self, database: AccountDatabase) -> None:
        self.database = database

    @staticmethod
    def _uuid(value: str | UUID, code: str) -> UUID:
        try:
            return value if isinstance(value, UUID) else UUID(value)
        except (TypeError, ValueError) as exc:
            raise RetailAdminError(code, "身份格式无效。") from exc

    @staticmethod
    def _reason(value: str, code: str) -> str:
        if value != value.strip() or not 1 <= len(value) <= 500:
            raise RetailAdminError(code, "审计原因无效。")
        return value

    @staticmethod
    def _amount(value: str) -> Decimal:
        try:
            amount = Decimal(value)
        except (InvalidOperation, TypeError) as exc:
            raise RetailAdminError("admin_grant_invalid", "赠款金额无效。") from exc
        if not amount.is_finite() or amount <= 0 or amount > MAX_ADMIN_GRANT or amount.quantize(MONEY_QUANTUM) != amount:
            raise RetailAdminError("admin_grant_invalid", "赠款金额无效。")
        return amount.quantize(MONEY_QUANTUM)

    @staticmethod
    def _purchase_url(value: str) -> str:
        if value != value.strip() or not 20 <= len(value) <= 2048 or any(character.isspace() for character in value):
            raise RetailAdminError("product_mapping_invalid", "购买链接无效。")
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.fragment
            or not (host == "ldxp.cn" or host.endswith(".ldxp.cn"))
        ):
            raise RetailAdminError("product_mapping_invalid", "购买链接必须使用链动 HTTPS 地址。")
        return value

    @staticmethod
    def _require_admin(connection: Any, actor: UUID, session: UUID) -> None:
        row = connection.execute(
            """
            SELECT 1
            FROM openclaw_account.sessions s
            JOIN openclaw_account.users u ON u.id=s.user_id
            WHERE s.id=%s AND s.user_id=%s AND s.status='active'
              AND s.expires_at>now() AND u.role='admin' AND u.status='active'
            """,
            (session, actor),
        ).fetchone()
        if row is None:
            raise RetailAdminError("admin_grant_invalid", "管理员会话不可用。")

    def plans(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT p.code,p.name,p.price_cny,p.credit_amount,m.purchase_url
                FROM openclaw_account.plans p
                LEFT JOIN openclaw_account.product_mappings m
                  ON m.plan_id=p.id AND m.status='active'
                WHERE p.status='active'
                ORDER BY p.price_cny
                """
            ).fetchall()
        return [
            {
                "code": str(row[0]),
                "name": f"MediaClaw ¥{row[2]} 额度",
                "priceCny": str(row[2]),
                "creditAmount": str(row[3]),
                "purchaseAvailable": row[4] is not None,
                "purchaseUrl": None if row[4] is None else str(row[4]),
            }
            for row in rows
        ]

    def create_mapping(
        self,
        *,
        actor_user_id: str | UUID,
        actor_session_id: str | UUID,
        plan_code: str,
        external_product_id: str,
        purchase_url: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        actor = self._uuid(actor_user_id, "product_mapping_invalid")
        session = self._uuid(actor_session_id, "product_mapping_invalid")
        url = self._purchase_url(purchase_url)
        audit_reason = self._reason(reason, "product_mapping_invalid")
        if plan_code != plan_code.strip() or not 1 <= len(plan_code) <= 64:
            raise RetailAdminError("product_mapping_invalid", "套餐代码无效。")
        if external_product_id != external_product_id.strip() or not 1 <= len(external_product_id) <= 128:
            raise RetailAdminError("product_mapping_invalid", "链动商品编号无效。")
        if not 1 <= len(idempotency_key) <= 128:
            raise RetailAdminError("product_mapping_invalid", "幂等键无效。")
        with self.database.connect() as connection:
            self._require_admin(connection, actor, session)
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"mapping:{idempotency_key}",))
            existing = connection.execute(
                """
                SELECT m.id,p.code,m.external_product_id,m.purchase_url,m.created_by_user_id
                FROM openclaw_account.product_mappings m
                JOIN openclaw_account.plans p ON p.id=m.plan_id
                WHERE m.idempotency_key=%s
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (existing[1], existing[2], existing[3], existing[4]) != (plan_code, external_product_id, url, actor):
                    raise RetailAdminError("idempotency_conflict", "幂等键已用于其他商品映射。")
                return self._mapping_payload(existing[0], plan_code, external_product_id, url)
            plan = connection.execute(
                "SELECT id FROM openclaw_account.plans WHERE code=%s AND status='active' FOR UPDATE",
                (plan_code,),
            ).fetchone()
            if plan is None:
                raise RetailAdminError("plan_not_found", "充值方案不可用。")
            mapping_id = uuid4()
            try:
                connection.execute(
                    """
                    INSERT INTO openclaw_account.product_mappings(
                        id,external_provider,external_product_id,plan_id,purchase_url,idempotency_key,created_by_user_id
                    ) VALUES (%s,'liandong',%s,%s,%s,%s,%s)
                    """,
                    (mapping_id, external_product_id, plan[0], url, idempotency_key, actor),
                )
            except Exception as exc:
                if getattr(exc, "sqlstate", None) == "23505":
                    raise RetailAdminError("product_mapping_conflict", "商品或套餐已存在活动映射。") from exc
                raise
            connection.execute(
                """
                INSERT INTO openclaw_account.admin_audit(
                    id,actor_user_id,actor_session_id,action,reason,metadata
                ) VALUES (%s,%s,%s,'billing.product_mapping.create',%s,%s::jsonb)
                """,
                (
                    uuid4(), actor, session, audit_reason,
                    json.dumps({"mappingId": str(mapping_id), "planCode": plan_code, "externalProductId": external_product_id}),
                ),
            )
            return self._mapping_payload(mapping_id, plan_code, external_product_id, url)

    def grant(
        self,
        *,
        actor_user_id: str | UUID,
        actor_session_id: str | UUID,
        target_tenant_id: str | UUID,
        amount: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, str]:
        actor = self._uuid(actor_user_id, "admin_grant_invalid")
        session = self._uuid(actor_session_id, "admin_grant_invalid")
        tenant = self._uuid(target_tenant_id, "tenant_not_found")
        grant_amount = self._amount(amount)
        audit_reason = self._reason(reason, "admin_grant_invalid")
        if not 1 <= len(idempotency_key) <= 128:
            raise RetailAdminError("admin_grant_invalid", "幂等键无效。")
        with self.database.connect() as connection:
            self._require_admin(connection, actor, session)
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"admin-grant:{tenant}:{idempotency_key}",))
            existing = connection.execute(
                """
                SELECT l.id,l.entry_type,l.source_type,l.available_delta,l.available_after,a.actor_user_id
                FROM openclaw_account.ledger_entries l
                LEFT JOIN openclaw_account.admin_audit a ON a.id=l.source_id
                WHERE l.tenant_id=%s AND l.idempotency_key=%s
                """,
                (tenant, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing[1] != "admin_grant" or existing[2] != "admin_grant" or existing[3] != grant_amount or existing[5] != actor:
                    raise RetailAdminError("idempotency_conflict", "幂等键已用于其他管理员赠款。")
                return self._grant_payload(existing[0], tenant, grant_amount, existing[4])
            target = connection.execute(
                """
                SELECT t.primary_user_id,w.id,w.available,w.reserved
                FROM openclaw_account.tenants t
                JOIN openclaw_account.users u ON u.id=t.primary_user_id AND u.status='active'
                JOIN openclaw_account.wallet_accounts w ON w.tenant_id=t.id
                WHERE t.id=%s AND t.status='active'
                FOR UPDATE OF w
                """,
                (tenant,),
            ).fetchone()
            if target is None:
                raise RetailAdminError("tenant_not_found", "目标租户不存在。")
            ledger_id = uuid4()
            audit_id = uuid4()
            available_after = Decimal(target[2]) + grant_amount
            connection.execute(
                "UPDATE openclaw_account.wallet_accounts SET available=%s,version=version+1,updated_at=now() WHERE id=%s",
                (available_after, target[1]),
            )
            connection.execute(
                """
                INSERT INTO openclaw_account.admin_audit(
                    id,actor_user_id,actor_session_id,action,target_user_id,reason,metadata
                ) VALUES (%s,%s,%s,'billing.admin_grant',%s,%s,%s::jsonb)
                """,
                (
                    audit_id, actor, session, target[0], audit_reason,
                    json.dumps({"targetTenantId": str(tenant), "amount": str(grant_amount), "ledgerEntryId": str(ledger_id)}),
                ),
            )
            connection.execute(
                """
                INSERT INTO openclaw_account.ledger_entries(
                    id,tenant_id,wallet_account_id,entry_type,available_delta,reserved_delta,
                    available_after,reserved_after,source_type,source_id,idempotency_key
                ) VALUES (%s,%s,%s,'admin_grant',%s,0,%s,%s,'admin_grant',%s,%s)
                """,
                (ledger_id, tenant, target[1], grant_amount, available_after, target[3], audit_id, idempotency_key),
            )
            return self._grant_payload(ledger_id, tenant, grant_amount, available_after)

    def admin_summary(self, *, limit: int = 100) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise RetailAdminError("admin_grant_invalid", "读取数量无效。")
        with self.database.connect() as connection:
            mappings = connection.execute(
                """
                SELECT m.id,p.code,m.external_product_id,m.purchase_url,m.status,m.created_at
                FROM openclaw_account.product_mappings m
                JOIN openclaw_account.plans p ON p.id=m.plan_id
                ORDER BY m.created_at DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
            batches = connection.execute(
                """
                SELECT b.id,p.code,b.code_count,b.status,b.created_at,
                       count(*) FILTER (WHERE c.status='available'),
                       count(*) FILTER (WHERE c.status='redeeming'),
                       count(*) FILTER (WHERE c.status='redeemed'),
                       count(*) FILTER (WHERE c.status='revoked')
                FROM openclaw_account.redemption_batches b
                JOIN openclaw_account.product_mappings m ON m.id=b.product_mapping_id
                JOIN openclaw_account.plans p ON p.id=m.plan_id
                JOIN openclaw_account.redemption_codes c ON c.batch_id=b.id
                GROUP BY b.id,p.code ORDER BY b.created_at DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
            fulfillments = connection.execute(
                """
                SELECT f.id,f.tenant_id,p.code,f.credited_amount,f.status,f.created_at,f.completed_at,f.refunded_at
                FROM openclaw_account.fulfillments f
                JOIN openclaw_account.plans p ON p.id=f.plan_id
                ORDER BY f.created_at DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
            grants = connection.execute(
                """
                SELECT l.id,l.tenant_id,u.username,l.available_delta,a.reason,l.created_at
                FROM openclaw_account.ledger_entries l
                JOIN openclaw_account.admin_audit a ON a.id=l.source_id
                JOIN openclaw_account.tenants t ON t.id=l.tenant_id
                JOIN openclaw_account.users u ON u.id=t.primary_user_id
                WHERE l.entry_type='admin_grant' AND l.source_type='admin_grant'
                ORDER BY l.created_at DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return {
            "plans": self.plans(),
            "mappings": [
                {"mappingId": str(row[0]), "planCode": row[1], "externalProductId": row[2], "purchaseUrl": row[3], "status": row[4], "createdAt": row[5].isoformat()}
                for row in mappings
            ],
            "batches": [
                {"batchId": str(row[0]), "planCode": row[1], "codeCount": row[2], "status": row[3], "createdAt": row[4].isoformat(), "availableCount": row[5], "redeemingCount": row[6], "redeemedCount": row[7], "revokedCount": row[8]}
                for row in batches
            ],
            "fulfillments": [
                {"fulfillmentId": str(row[0]), "tenantId": str(row[1]), "planCode": row[2], "creditedAmount": str(row[3]), "status": row[4], "createdAt": row[5].isoformat(), "completedAt": None if row[6] is None else row[6].isoformat(), "refundedAt": None if row[7] is None else row[7].isoformat()}
                for row in fulfillments
            ],
            "grants": [
                {"ledgerEntryId": str(row[0]), "tenantId": str(row[1]), "username": row[2], "amount": str(row[3]), "reason": row[4], "createdAt": row[5].isoformat()}
                for row in grants
            ],
        }

    @staticmethod
    def _mapping_payload(mapping_id: UUID, plan_code: str, external_product_id: str, purchase_url: str) -> dict[str, Any]:
        return {"mappingId": str(mapping_id), "planCode": plan_code, "externalProductId": external_product_id, "purchaseUrl": purchase_url, "status": "active"}

    @staticmethod
    def _grant_payload(ledger_id: UUID, tenant_id: UUID, amount: Decimal, available_after: Decimal) -> dict[str, str]:
        return {"ledgerEntryId": str(ledger_id), "targetTenantId": str(tenant_id), "amount": str(amount), "availableAfter": str(available_after)}
