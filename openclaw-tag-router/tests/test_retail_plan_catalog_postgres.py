from __future__ import annotations

import os

import pytest

from openclaw_app.account.database import AccountDatabase, AccountDatabaseSettings


DATABASE_URL = os.getenv("OPENCLAW_U8_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="OPENCLAW_U8_TEST_DATABASE_URL is required")


@pytest.fixture()
def database() -> AccountDatabase:
    return AccountDatabase(AccountDatabaseSettings(DATABASE_URL))


def test_catalog_is_exactly_six_equal_value_active_plans(database: AccountDatabase) -> None:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT code,price_cny,credit_amount,status FROM openclaw_account.plans ORDER BY price_cny"
        ).fetchall()
    assert [(row[0], int(row[1]), int(row[2]), row[3]) for row in rows] == [
        ("mediaclaw-cny-1", 1, 1, "active"),
        ("mediaclaw-cny-5", 5, 5, "active"),
        ("mediaclaw-cny-20", 20, 20, "active"),
        ("mediaclaw-cny-50", 50, 50, "active"),
        ("mediaclaw-cny-100", 100, 100, "active"),
        ("mediaclaw-cny-500", 500, 500, "active"),
    ]


def test_catalog_rejects_seventh_plan_and_amount_rewrite(database: AccountDatabase) -> None:
    with pytest.raises(Exception) as inserted:
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO openclaw_account.plans(id,code,name,price_cny,credit_amount,status) "
                "VALUES ('80000000-0000-4000-8000-000000000999','mediaclaw-cny-999','Invalid',999,999,'active')"
            )
    assert getattr(inserted.value, "sqlstate", None) == "55000"

    with pytest.raises(Exception) as updated:
        with database.connect() as connection:
            connection.execute(
                "UPDATE openclaw_account.plans SET credit_amount=2 WHERE code='mediaclaw-cny-1'"
            )
    assert getattr(updated.value, "sqlstate", None) == "55000"


def test_product_mapping_target_is_immutable_and_one_active_per_plan(database: AccountDatabase) -> None:
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO openclaw_account.product_mappings(id,external_provider,external_product_id,plan_id,purchase_url,idempotency_key,created_by_user_id) "
            "SELECT '81000000-0000-4000-8000-000000000001','liandong','test-product-1',id,'https://www.ldxp.cn/goods/test-1','mapping-test-1'," 
            "(SELECT id FROM openclaw_account.users WHERE role='admin' ORDER BY created_at LIMIT 1) "
            "FROM openclaw_account.plans WHERE code='mediaclaw-cny-1'"
        )

    with pytest.raises(Exception) as rewritten:
        with database.connect() as connection:
            connection.execute(
                "UPDATE openclaw_account.product_mappings SET plan_id="
                "(SELECT id FROM openclaw_account.plans WHERE code='mediaclaw-cny-5') "
                "WHERE external_product_id='test-product-1'"
            )
    assert getattr(rewritten.value, "sqlstate", None) == "55000"

    with pytest.raises(Exception) as duplicated:
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO openclaw_account.product_mappings(id,external_provider,external_product_id,plan_id,purchase_url,idempotency_key,created_by_user_id) "
                "SELECT '81000000-0000-4000-8000-000000000002','liandong','test-product-2',id,'https://www.ldxp.cn/goods/test-2','mapping-test-2'," 
                "(SELECT id FROM openclaw_account.users WHERE role='admin' ORDER BY created_at LIMIT 1) "
                "FROM openclaw_account.plans WHERE code='mediaclaw-cny-1'"
            )
    assert getattr(duplicated.value, "sqlstate", None) == "23505"
