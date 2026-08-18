from __future__ import annotations

import os
from decimal import Decimal

import pytest

from openclaw_app.account.database import AccountDatabase, AccountDatabaseSettings
from openclaw_app.services.retail_admin import RetailAdminError, RetailAdminService


DATABASE_URL = os.getenv("OPENCLAW_U12B_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="OPENCLAW_U12B_TEST_DATABASE_URL is required")
ADMIN = "91000000-0000-4000-8000-000000000001"
ADMIN_TENANT = "92000000-0000-4000-8000-000000000001"
ADMIN_WALLET = "93000000-0000-4000-8000-000000000001"
ADMIN_SESSION = "94000000-0000-4000-8000-000000000001"
TARGET = "91000000-0000-4000-8000-000000000002"
TARGET_TENANT = "92000000-0000-4000-8000-000000000002"
TARGET_WALLET = "93000000-0000-4000-8000-000000000002"


@pytest.fixture()
def service() -> RetailAdminService:
    database = AccountDatabase(AccountDatabaseSettings(DATABASE_URL))
    with database.connect() as connection:
        connection.execute(
            "TRUNCATE openclaw_account.refund_adjustments,openclaw_account.affiliate_ledger,"
            "openclaw_account.fulfillments,openclaw_account.redemption_codes,openclaw_account.redemption_batches,"
            "openclaw_account.product_mappings,openclaw_account.admin_audit,openclaw_account.ledger_entries,"
            "openclaw_account.sessions,openclaw_account.wallet_accounts,openclaw_account.tenants,openclaw_account.users CASCADE"
        )
        connection.execute(
            "INSERT INTO openclaw_account.users(id,username,password_hash,role) VALUES "
            "(%s,'u12b-admin',%s,'admin'),(%s,'u12b-target',%s,'user')",
            (ADMIN, "x" * 60, TARGET, "x" * 60),
        )
        connection.execute(
            "INSERT INTO openclaw_account.tenants(id,primary_user_id) VALUES (%s,%s),(%s,%s)",
            (ADMIN_TENANT, ADMIN, TARGET_TENANT, TARGET),
        )
        connection.execute(
            "INSERT INTO openclaw_account.wallet_accounts(id,tenant_id) VALUES (%s,%s),(%s,%s)",
            (ADMIN_WALLET, ADMIN_TENANT, TARGET_WALLET, TARGET_TENANT),
        )
        connection.execute(
            """
            INSERT INTO openclaw_account.sessions(
                id,session_token_hash,csrf_token_hash,user_id,tenant_id,expires_at
            ) VALUES (%s,%s,%s,%s,%s,now()+interval '1 hour')
            """,
            (ADMIN_SESSION, b"s" * 32, b"c" * 32, ADMIN, ADMIN_TENANT),
        )
    return RetailAdminService(database)


def test_plans_and_mapping_have_one_canonical_purchase_path(service: RetailAdminService) -> None:
    plans = service.plans()
    assert [item["code"] for item in plans] == [
        "mediaclaw-cny-1", "mediaclaw-cny-5", "mediaclaw-cny-20",
        "mediaclaw-cny-50", "mediaclaw-cny-100", "mediaclaw-cny-500",
    ]
    assert all(item["purchaseAvailable"] is False and item["purchaseUrl"] is None for item in plans)

    created = service.create_mapping(
        actor_user_id=ADMIN,
        actor_session_id=ADMIN_SESSION,
        plan_code="mediaclaw-cny-1",
        external_product_id="liandong-openclaw-1",
        purchase_url="https://www.ldxp.cn/goods/openclaw-1",
        reason="canonical product mapping",
        idempotency_key="mapping-u12b-1",
    )
    replay = service.create_mapping(
        actor_user_id=ADMIN,
        actor_session_id=ADMIN_SESSION,
        plan_code="mediaclaw-cny-1",
        external_product_id="liandong-openclaw-1",
        purchase_url="https://www.ldxp.cn/goods/openclaw-1",
        reason="canonical product mapping",
        idempotency_key="mapping-u12b-1",
    )
    assert replay == created
    assert service.plans()[0]["purchaseUrl"] == "https://www.ldxp.cn/goods/openclaw-1"
    with service.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM openclaw_account.product_mappings").fetchone()[0] == 1


def test_mapping_rejects_non_liandong_or_changed_idempotent_payload(service: RetailAdminService) -> None:
    with pytest.raises(RetailAdminError) as invalid:
        service.create_mapping(
            actor_user_id=ADMIN, actor_session_id=ADMIN_SESSION, plan_code="mediaclaw-cny-1",
            external_product_id="bad", purchase_url="https://example.com/goods/1",
            reason="invalid host", idempotency_key="mapping-invalid",
        )
    assert invalid.value.code == "product_mapping_invalid"


def test_admin_grant_is_atomic_audited_and_idempotent(service: RetailAdminService) -> None:
    first = service.grant(
        actor_user_id=ADMIN,
        actor_session_id=ADMIN_SESSION,
        target_tenant_id=TARGET_TENANT,
        amount="25.50000000",
        reason="test operations credit",
        idempotency_key="grant-u12b-1",
    )
    replay = service.grant(
        actor_user_id=ADMIN,
        actor_session_id=ADMIN_SESSION,
        target_tenant_id=TARGET_TENANT,
        amount="25.50000000",
        reason="test operations credit",
        idempotency_key="grant-u12b-1",
    )
    assert replay == first
    with service.database.connect() as connection:
        assert connection.execute(
            "SELECT available FROM openclaw_account.wallet_accounts WHERE id=%s", (TARGET_WALLET,)
        ).fetchone()[0] == Decimal("25.50000000")
        assert connection.execute(
            "SELECT count(*) FROM openclaw_account.ledger_entries WHERE entry_type='admin_grant' AND source_type='admin_grant'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM openclaw_account.admin_audit WHERE action='billing.admin_grant'"
        ).fetchone()[0] == 1

    with pytest.raises(RetailAdminError) as conflict:
        service.grant(
            actor_user_id=ADMIN, actor_session_id=ADMIN_SESSION, target_tenant_id=TARGET_TENANT,
            amount="26.00000000", reason="changed amount", idempotency_key="grant-u12b-1",
        )
    assert conflict.value.code == "idempotency_conflict"


def test_admin_adjustment_and_invalid_grants_are_rejected(service: RetailAdminService) -> None:
    with pytest.raises(RetailAdminError):
        service.grant(
            actor_user_id=ADMIN, actor_session_id=ADMIN_SESSION, target_tenant_id=TARGET_TENANT,
            amount="100000.00000001", reason="over limit", idempotency_key="grant-over-limit",
        )
    with pytest.raises(Exception) as legacy:
        with service.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO openclaw_account.ledger_entries(
                    id,tenant_id,wallet_account_id,entry_type,available_delta,reserved_delta,
                    available_after,reserved_after,source_type,idempotency_key
                ) VALUES ('95000000-0000-4000-8000-000000000001',%s,%s,'admin_adjustment',1,0,1,0,'legacy','legacy')
                """,
                (TARGET_TENANT, TARGET_WALLET),
            )
    assert getattr(legacy.value, "sqlstate", None) == "23514"
