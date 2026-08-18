from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import stat
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ..account.database import AccountDatabase
from ..account.errors import AccountError


MONEY_QUANTUM = Decimal("0.00000001")
REWARD_RATE = Decimal("0.1000")


def load_redemption_secret(path: str | Path) -> bytes:
    secret_path = Path(path)
    try:
        metadata = secret_path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("redemption HMAC secret is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError("redemption HMAC secret is unavailable")
    value = secret_path.read_bytes()
    if len(value) < 32 or value != value.strip() or b"\n" in value or b"\r" in value:
        raise RuntimeError("redemption HMAC secret is invalid")
    return value


class RetailFulfillmentError(AccountError):
    def __init__(self, code: str, detail: str) -> None:
        status = {
            "redemption_unavailable": 409,
            "redemption_processing": 409,
            "fulfillment_not_found": 404,
            "fulfillment_conflict": 409,
            "plan_not_found": 404,
            "product_mapping_conflict": 409,
            "idempotency_conflict": 409,
            "invalid_redemption_code": 400,
        }.get(code, 503)
        super().__init__(code, detail, status=status)


@dataclass(frozen=True)
class RedemptionResult:
    fulfillment_id: UUID
    plan_code: str
    credited_amount: Decimal
    affiliate_amount: Decimal
    status: str


@dataclass(frozen=True)
class BatchIssue:
    batch_id: UUID
    code_count: int
    export_path: Path


class RetailFulfillmentService:
    def __init__(self, database: AccountDatabase, *, code_secret: bytes, export_root: str | Path) -> None:
        if len(code_secret) < 32:
            raise ValueError("redemption code secret must be at least 32 bytes")
        self.database = database
        self._code_secret = code_secret
        self._export_root = Path(export_root)
        if not self._export_root.is_absolute():
            raise ValueError("redemption export root must be absolute")
        try:
            metadata = self._export_root.lstat()
        except FileNotFoundError as exc:
            raise RuntimeError("redemption export root is unavailable") from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            raise RuntimeError("redemption export root is not private")

    @staticmethod
    def _uuid(value: str | UUID, code: str) -> UUID:
        try:
            parsed = value if isinstance(value, UUID) else UUID(value)
        except (ValueError, TypeError) as exc:
            raise RetailFulfillmentError(code, "身份格式无效。") from exc
        return parsed

    def _digest(self, code: str) -> bytes:
        if not 16 <= len(code) <= 128 or code != code.strip() or "\n" in code or "\r" in code:
            raise RetailFulfillmentError("invalid_redemption_code", "卡密格式无效。")
        return hmac.new(self._code_secret, code.encode("utf-8"), hashlib.sha256).digest()

    def _write_export(self, batch_id: UUID, codes: tuple[str, ...]) -> Path:
        export_path = self._export_root / f"{batch_id}.txt"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(export_path, flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise RuntimeError("redemption export file is not private")
            with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
                descriptor = -1
                for code in codes:
                    stream.write(code)
                    stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            export_path.unlink(missing_ok=True)
            raise
        return export_path

    def create_batch(
        self,
        *,
        actor_user_id: str | UUID,
        plan_code: str,
        count: int,
        idempotency_key: str,
    ) -> BatchIssue:
        actor = self._uuid(actor_user_id, "fulfillment_conflict")
        if not 1 <= count <= 1000 or not 1 <= len(idempotency_key) <= 128:
            raise RetailFulfillmentError("fulfillment_conflict", "批次参数无效。")
        batch_id = uuid4()
        export_path: Path | None = None
        try:
            with self.database.connect() as connection:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (f"batch:{idempotency_key}:{plan_code}",),
                )
                existing = connection.execute(
                    "SELECT id FROM openclaw_account.redemption_batches WHERE idempotency_key=%s",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    raise RetailFulfillmentError("idempotency_conflict", "批次幂等键已使用。")
                admin = connection.execute(
                    "SELECT 1 FROM openclaw_account.users WHERE id=%s AND role='admin' AND status='active'",
                    (actor,),
                ).fetchone()
                if admin is None:
                    raise RetailFulfillmentError("fulfillment_conflict", "管理员身份不可用。")
                mapping = connection.execute(
                    """
                    SELECT m.id
                    FROM openclaw_account.product_mappings m
                    JOIN openclaw_account.plans p ON p.id=m.plan_id AND p.status='active'
                    WHERE p.code=%s AND m.status='active'
                    FOR UPDATE OF m
                    """,
                    (plan_code,),
                ).fetchone()
                if mapping is None:
                    raise RetailFulfillmentError("plan_not_found", "充值方案不可用。")
                codes = tuple("OC-" + secrets.token_urlsafe(24) for _ in range(count))
                digests = tuple(self._digest(code) for code in codes)
                export_path = self._write_export(batch_id, codes)
                connection.execute(
                    "INSERT INTO openclaw_account.redemption_batches(id,product_mapping_id,code_count,idempotency_key,created_by_user_id) VALUES (%s,%s,%s,%s,%s)",
                    (batch_id, mapping[0], count, idempotency_key, actor),
                )
                with connection.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO openclaw_account.redemption_codes(id,batch_id,code_hmac) VALUES (%s,%s,%s)",
                        [(uuid4(), batch_id, digest) for digest in digests],
                    )
        except BaseException:
            if export_path is not None:
                export_path.unlink(missing_ok=True)
            raise
        if export_path is None:
            raise RuntimeError("redemption export was not created")
        return BatchIssue(batch_id, count, export_path)

    def redeem(self, *, tenant_id: str, user_id: str, code: str) -> RedemptionResult:
        tenant = self._uuid(tenant_id, "redemption_unavailable")
        user = self._uuid(user_id, "redemption_unavailable")
        digest = self._digest(code)
        fulfillment_id: UUID
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT c.id,c.status,p.id,p.code,p.credit_amount,w.id
                FROM openclaw_account.redemption_codes c
                JOIN openclaw_account.redemption_batches b ON b.id=c.batch_id AND b.status='active'
                JOIN openclaw_account.product_mappings m ON m.id=b.product_mapping_id AND m.status='active'
                JOIN openclaw_account.plans p ON p.id=m.plan_id AND p.status='active'
                JOIN openclaw_account.tenants t ON t.id=%s AND t.primary_user_id=%s AND t.status='active'
                JOIN openclaw_account.wallet_accounts w ON w.tenant_id=t.id
                WHERE c.code_hmac=%s FOR UPDATE OF c
                """,
                (tenant, user, digest),
            ).fetchone()
            if row is None or row[1] == "revoked":
                raise RetailFulfillmentError("redemption_unavailable", "卡密不可用。")
            existing = connection.execute(
                "SELECT id,tenant_id,status FROM openclaw_account.fulfillments WHERE code_id=%s",
                (row[0],),
            ).fetchone()
            if existing is not None:
                if existing[1] != tenant:
                    raise RetailFulfillmentError("redemption_unavailable", "卡密不可用。")
                fulfillment_id = existing[0]
            elif row[1] == "available":
                fulfillment_id = uuid4()
                connection.execute(
                    "UPDATE openclaw_account.redemption_codes SET status='redeeming',redeeming_at=now() WHERE id=%s",
                    (row[0],),
                )
                connection.execute(
                    "INSERT INTO openclaw_account.fulfillments(id,code_id,tenant_id,plan_id,wallet_account_id,credited_amount) VALUES (%s,%s,%s,%s,%s,%s)",
                    (fulfillment_id, row[0], tenant, row[2], row[5], row[4]),
                )
            else:
                raise RetailFulfillmentError("redemption_processing", "卡密正在处理。")
        return self.recover(fulfillment_id, expected_tenant=tenant)

    def recover(self, fulfillment_id: str | UUID, *, expected_tenant: UUID | None = None) -> RedemptionResult:
        fulfillment = self._uuid(fulfillment_id, "fulfillment_not_found")
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT f.tenant_id,f.plan_id,f.wallet_account_id,f.credited_amount,f.status,
                       c.id,p.code,t.primary_user_id
                FROM openclaw_account.fulfillments f
                JOIN openclaw_account.redemption_codes c ON c.id=f.code_id
                JOIN openclaw_account.plans p ON p.id=f.plan_id
                JOIN openclaw_account.tenants t ON t.id=f.tenant_id
                WHERE f.id=%s FOR UPDATE OF f,c
                """,
                (fulfillment,),
            ).fetchone()
            if row is None or (expected_tenant is not None and row[0] != expected_tenant):
                raise RetailFulfillmentError("fulfillment_not_found", "交付记录不存在。")
            affiliate = connection.execute(
                """
                SELECT inviter_tenant.id,inviter_wallet.id
                FROM openclaw_account.affiliate_edges edge
                JOIN openclaw_account.tenants inviter_tenant ON inviter_tenant.primary_user_id=edge.inviter_user_id
                JOIN openclaw_account.wallet_accounts inviter_wallet ON inviter_wallet.tenant_id=inviter_tenant.id
                WHERE edge.invitee_user_id=%s
                """,
                (row[7],),
            ).fetchone()
            if row[4] in {"succeeded", "refunded"}:
                reward = connection.execute(
                    "SELECT amount FROM openclaw_account.affiliate_ledger WHERE fulfillment_id=%s",
                    (fulfillment,),
                ).fetchone()
                return RedemptionResult(fulfillment, str(row[6]), Decimal(row[3]), Decimal(reward[0]) if reward else Decimal(0), str(row[4]))
            wallet_ids = sorted([row[2]] + ([affiliate[1]] if affiliate else []), key=str)
            locked = {
                item[0]: (Decimal(item[1]), Decimal(item[2]))
                for item in connection.execute(
                    "SELECT id,available,reserved FROM openclaw_account.wallet_accounts WHERE id=ANY(%s) ORDER BY id FOR UPDATE",
                    (wallet_ids,),
                ).fetchall()
            }
            principal_before = locked[row[2]][0]
            principal_amount = Decimal(row[3])
            principal_after = principal_before + principal_amount
            principal_ledger = uuid4()
            connection.execute(
                "UPDATE openclaw_account.wallet_accounts SET available=%s,version=version+1,updated_at=now() WHERE id=%s",
                (principal_after, row[2]),
            )
            connection.execute(
                """
                INSERT INTO openclaw_account.ledger_entries(
                    id,tenant_id,wallet_account_id,entry_type,available_delta,reserved_delta,
                    available_after,reserved_after,source_type,source_id,idempotency_key
                ) VALUES (%s,%s,%s,'credit',%s,0,%s,%s,'fulfillment',%s,%s)
                """,
                (principal_ledger, row[0], row[2], principal_amount, principal_after, locked[row[2]][1], fulfillment, f"fulfillment:{fulfillment}"),
            )
            affiliate_amount = Decimal(0)
            if affiliate is not None:
                affiliate_amount = (principal_amount * REWARD_RATE).quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)
                affiliate_before = locked[affiliate[1]][0]
                affiliate_after = affiliate_before + affiliate_amount
                affiliate_ledger_entry = uuid4()
                connection.execute(
                    "UPDATE openclaw_account.wallet_accounts SET available=%s,version=version+1,updated_at=now() WHERE id=%s",
                    (affiliate_after, affiliate[1]),
                )
                connection.execute(
                    """
                    INSERT INTO openclaw_account.ledger_entries(
                        id,tenant_id,wallet_account_id,entry_type,available_delta,reserved_delta,
                        available_after,reserved_after,source_type,source_id,idempotency_key
                    ) VALUES (%s,%s,%s,'affiliate',%s,0,%s,%s,'fulfillment',%s,%s)
                    """,
                    (affiliate_ledger_entry, affiliate[0], affiliate[1], affiliate_amount, affiliate_after, locked[affiliate[1]][1], fulfillment, f"affiliate:{fulfillment}"),
                )
                connection.execute(
                    "INSERT INTO openclaw_account.affiliate_ledger(id,fulfillment_id,inviter_tenant_id,invitee_tenant_id,wallet_account_id,ledger_entry_id,reward_rate,amount) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (uuid4(), fulfillment, affiliate[0], row[0], affiliate[1], affiliate_ledger_entry, REWARD_RATE, affiliate_amount),
                )
            connection.execute(
                "UPDATE openclaw_account.fulfillments SET status='succeeded',completed_at=now() WHERE id=%s",
                (fulfillment,),
            )
            connection.execute(
                "UPDATE openclaw_account.redemption_codes SET status='redeemed',redeemed_by_tenant_id=%s,redeemed_at=now() WHERE id=%s",
                (row[0], row[5]),
            )
            return RedemptionResult(fulfillment, str(row[6]), principal_amount, affiliate_amount, "succeeded")

    def refund(self, *, actor_user_id: str | UUID, fulfillment_id: str | UUID, reason: str) -> dict[str, str]:
        actor = self._uuid(actor_user_id, "fulfillment_conflict")
        fulfillment = self._uuid(fulfillment_id, "fulfillment_not_found")
        if not 1 <= len(reason.strip()) <= 500 or reason != reason.strip():
            raise RetailFulfillmentError("fulfillment_conflict", "退款原因无效。")
        with self.database.connect() as connection:
            if connection.execute("SELECT 1 FROM openclaw_account.users WHERE id=%s AND role='admin' AND status='active'", (actor,)).fetchone() is None:
                raise RetailFulfillmentError("fulfillment_conflict", "管理员身份不可用。")
            row = connection.execute(
                "SELECT tenant_id,wallet_account_id,credited_amount,status FROM openclaw_account.fulfillments WHERE id=%s FOR UPDATE",
                (fulfillment,),
            ).fetchone()
            if row is None:
                raise RetailFulfillmentError("fulfillment_not_found", "交付记录不存在。")
            existing = connection.execute(
                "SELECT principal_debited,principal_debt,affiliate_debited,affiliate_debt FROM openclaw_account.refund_adjustments WHERE fulfillment_id=%s",
                (fulfillment,),
            ).fetchone()
            if existing is not None:
                return self._refund_payload(existing)
            if row[3] != "succeeded":
                raise RetailFulfillmentError("fulfillment_conflict", "交付状态不能退款。")
            affiliate = connection.execute(
                "SELECT inviter_tenant_id,wallet_account_id,amount FROM openclaw_account.affiliate_ledger WHERE fulfillment_id=%s",
                (fulfillment,),
            ).fetchone()
            wallet_ids = sorted([row[1]] + ([affiliate[1]] if affiliate else []), key=str)
            wallets = {
                item[0]: (Decimal(item[1]), Decimal(item[2]))
                for item in connection.execute(
                    "SELECT id,available,reserved FROM openclaw_account.wallet_accounts WHERE id=ANY(%s) ORDER BY id FOR UPDATE",
                    (wallet_ids,),
                ).fetchall()
            }
            principal_requested = Decimal(row[2])
            principal_debited = min(wallets[row[1]][0], principal_requested)
            principal_debt = principal_requested - principal_debited
            if principal_debited:
                self._debit(connection, row[0], row[1], wallets[row[1]], principal_debited, fulfillment, "principal")
            affiliate_requested = Decimal(affiliate[2]) if affiliate else Decimal(0)
            affiliate_debited = min(wallets[affiliate[1]][0], affiliate_requested) if affiliate else Decimal(0)
            affiliate_debt = affiliate_requested - affiliate_debited
            if affiliate and affiliate_debited:
                self._debit(connection, affiliate[0], affiliate[1], wallets[affiliate[1]], affiliate_debited, fulfillment, "affiliate")
            values = (principal_debited, principal_debt, affiliate_debited, affiliate_debt)
            connection.execute(
                """
                INSERT INTO openclaw_account.refund_adjustments(
                    id,fulfillment_id,actor_user_id,principal_requested,principal_debited,principal_debt,
                    affiliate_requested,affiliate_debited,affiliate_debt,reason
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (uuid4(), fulfillment, actor, principal_requested, *values[:2], affiliate_requested, *values[2:], reason),
            )
            connection.execute(
                "UPDATE openclaw_account.fulfillments SET status='refunded',refunded_at=now() WHERE id=%s",
                (fulfillment,),
            )
            return self._refund_payload(values)

    @staticmethod
    def _debit(connection: Any, tenant: UUID, wallet: UUID, state: tuple[Decimal, Decimal], amount: Decimal, fulfillment: UUID, kind: str) -> None:
        available_after = state[0] - amount
        connection.execute(
            "UPDATE openclaw_account.wallet_accounts SET available=%s,version=version+1,updated_at=now() WHERE id=%s",
            (available_after, wallet),
        )
        connection.execute(
            """
            INSERT INTO openclaw_account.ledger_entries(
                id,tenant_id,wallet_account_id,entry_type,available_delta,reserved_delta,
                available_after,reserved_after,source_type,source_id,idempotency_key
            ) VALUES (%s,%s,%s,'refund',%s,0,%s,%s,'refund_adjustment',%s,%s)
            """,
            (uuid4(), tenant, wallet, -amount, available_after, state[1], fulfillment, f"refund:{kind}:{fulfillment}"),
        )

    @staticmethod
    def _refund_payload(values: Any) -> dict[str, str]:
        return {
            "principalDebited": str(values[0]),
            "principalDebt": str(values[1]),
            "affiliateDebited": str(values[2]),
            "affiliateDebt": str(values[3]),
        }
