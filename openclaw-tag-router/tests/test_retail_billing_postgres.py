from __future__ import annotations

import os
import hashlib
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID

import pytest

from openclaw_app.account.database import AccountDatabase, AccountDatabaseSettings
from openclaw_app.services.retail_billing import RetailBillingError, RetailBillingService, Usage


DATABASE_URL = os.getenv("OPENCLAW_U6_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="OPENCLAW_U6_TEST_DATABASE_URL is required")
TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"
WALLET_A = "30000000-0000-4000-8000-000000000001"
WALLET_B = "30000000-0000-4000-8000-000000000002"
PRICE_A = "60000000-0000-4000-8000-000000000001"


@pytest.fixture()
def billing() -> RetailBillingService:
    database = AccountDatabase(AccountDatabaseSettings(DATABASE_URL))
    with database.connect() as connection:
        connection.execute(
            "TRUNCATE openclaw_account.usage_charges,openclaw_account.upstream_request_refs,"
            "openclaw_account.model_operations,openclaw_account.fund_holds,"
            "openclaw_account.ledger_entries,openclaw_account.wallet_accounts,"
            "openclaw_account.model_price_versions,openclaw_account.tenants,"
            "openclaw_account.users CASCADE"
        )
        for user, tenant, wallet, suffix in (
            (USER_A, TENANT_A, WALLET_A, "a"),
            (USER_B, TENANT_B, WALLET_B, "b"),
        ):
            connection.execute(
                "INSERT INTO openclaw_account.users(id,username,password_hash,role) VALUES (%s,%s,%s,'user')",
                (user, f"u6-{suffix}", "x" * 60),
            )
            connection.execute(
                "INSERT INTO openclaw_account.tenants(id,primary_user_id) VALUES (%s,%s)",
                (tenant, user),
            )
            connection.execute(
                "INSERT INTO openclaw_account.wallet_accounts(id,tenant_id,available) VALUES (%s,%s,10)",
                (wallet, tenant),
            )
        connection.execute(
            """
            INSERT INTO openclaw_account.model_price_versions(
                id,model,input_price_per_million,cached_input_price_per_million,
                output_price_per_million,effective_at
            ) VALUES (%s,'gpt-5.6-sol',2,0.2,8,'2026-08-02T00:00:00+08:00')
            """,
            (PRICE_A,),
        )
    return RetailBillingService(database)


def reserve(service: RetailBillingService, tenant: str, key: str, fingerprint: str | None = None):
    return service.reserve(
        tenant_id=tenant,
        scope="media-task",
        idempotency_key=key,
        request_fingerprint=fingerprint or hashlib.sha256(key.encode("utf-8")).hexdigest(),
        model="gpt-5.6-sol",
        correlation_key=f"correlation-{key}",
        max_input_tokens=1000,
        max_output_tokens=100,
    )


def test_actual_cached_usage_settles_hold_and_append_only_ledger(billing: RetailBillingService) -> None:
    operation = reserve(billing, TENANT_A, "operation-a")
    assert billing.balance(TENANT_A) == {
        "available": "9.99720000",
        "reserved": "0.00280000",
        "currency": "credit",
    }

    charge = billing.settle(
        operation.operation_id,
        usage=Usage(100, 40, 10),
        upstream_request_id="client:request-a",
        upstream_model="gpt-5.6-sol",
    )

    assert charge == Decimal("0.00020800")
    assert billing.balance(TENANT_A) == {
        "available": "9.99979200",
        "reserved": "0E-8",
        "currency": "credit",
    }
    with billing.database.connect() as connection:
        entries = connection.execute(
            "SELECT entry_type FROM openclaw_account.ledger_entries WHERE tenant_id=%s ORDER BY created_at",
            (TENANT_A,),
        ).fetchall()
        usage = connection.execute(
            "SELECT input_tokens,cached_input_tokens,output_tokens,amount FROM openclaw_account.usage_charges"
        ).fetchone()
    assert [row[0] for row in entries] == ["reserve", "settle"]
    assert usage == (100, 40, 10, Decimal("0.00020800"))


def test_insufficient_balance_and_idempotency_fail_closed(billing: RetailBillingService) -> None:
    with billing.database.connect() as connection:
        connection.execute("UPDATE openclaw_account.wallet_accounts SET available=0 WHERE tenant_id=%s", (TENANT_A,))
    with pytest.raises(RetailBillingError) as insufficient:
        reserve(billing, TENANT_A, "no-balance")
    assert insufficient.value.code == "insufficient_balance"

    with billing.database.connect() as connection:
        connection.execute("UPDATE openclaw_account.wallet_accounts SET available=10 WHERE tenant_id=%s", (TENANT_A,))
    reserve(billing, TENANT_A, "bound-key")
    with pytest.raises(RetailBillingError) as conflict:
        reserve(billing, TENANT_A, "bound-key", "2" * 64)
    assert conflict.value.code == "idempotency_conflict"
    with pytest.raises(RetailBillingError) as replay:
        reserve(billing, TENANT_A, "bound-key")
    assert replay.value.code == "usage_reconciliation_pending"


def test_same_key_concurrency_creates_exactly_one_operation(billing: RetailBillingService) -> None:
    def claim() -> str:
        try:
            reserve(billing, TENANT_A, "same-key-concurrent")
        except RetailBillingError as exc:
            return exc.code
        return "reserved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(lambda _: claim(), range(2)))

    assert results == ["reserved", "usage_reconciliation_pending"]
    with billing.database.connect() as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM openclaw_account.model_operations),
                (SELECT count(*) FROM openclaw_account.fund_holds),
                (SELECT count(*) FROM openclaw_account.ledger_entries)
            """
        ).fetchone()
    assert counts == (1, 1, 1)


def test_failure_releases_but_timeout_keeps_hold(billing: RetailBillingService) -> None:
    failed = reserve(billing, TENANT_A, "failed-call")
    billing.release(failed.operation_id, error_code="model_request_rejected")
    assert billing.balance(TENANT_A)["available"] == "10.00000000"
    assert billing.balance(TENANT_A)["reserved"] == "0E-8"

    unknown = reserve(billing, TENANT_A, "unknown-call")
    billing.mark_unknown(unknown.operation_id, upstream_request_id="client:unknown")
    assert billing.balance(TENANT_A)["available"] == "9.99720000"
    assert billing.balance(TENANT_A)["reserved"] == "0.00280000"
    queue = billing.reconciliation_queue()
    assert [item["operationId"] for item in queue] == [str(unknown.operation_id)]
    target, request_id = billing.reconciliation_target(str(unknown.operation_id))
    assert target == unknown.operation_id
    assert request_id == "client:unknown"
    billing.settle(
        target,
        usage=Usage(100, 20, 10),
        upstream_request_id=request_id,
        upstream_model="gpt-5.6-sol",
        actual_cost=Decimal("0.00010000"),
    )
    assert billing.balance(TENANT_A)["reserved"] == "0E-8"
    with billing.database.connect() as connection:
        actual_cost = connection.execute(
            "SELECT actual_cost FROM openclaw_account.upstream_request_refs WHERE operation_id=%s",
            (target,),
        ).fetchone()[0]
    assert actual_cost == Decimal("0.00010000")


def test_two_tenant_concurrency_never_crosses_or_goes_negative(billing: RetailBillingService) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        operations = list(
            pool.map(
                lambda item: reserve(billing, item[0], item[1]),
                ((TENANT_A, "concurrent-a"), (TENANT_B, "concurrent-b")),
            )
        )
    for operation in operations:
        billing.settle(
            operation.operation_id,
            usage=Usage(50, 0, 5),
            upstream_request_id=f"client:{operation.operation_id}",
            upstream_model="gpt-5.6-sol",
        )
    assert billing.balance(TENANT_A) == billing.balance(TENANT_B)
    assert Decimal(billing.balance(TENANT_A)["available"]) >= 0
    assert billing.usage(TENANT_A)[0]["operationId"] != billing.usage(TENANT_B)[0]["operationId"]


def test_price_change_does_not_change_existing_operation_snapshot(billing: RetailBillingService) -> None:
    first = reserve(billing, TENANT_A, "old-price")
    with billing.database.connect() as connection:
        connection.execute(
            "UPDATE openclaw_account.model_price_versions SET retired_at=now() WHERE id=%s",
            (PRICE_A,),
        )
        connection.execute(
            """
            INSERT INTO openclaw_account.model_price_versions(
                id,model,input_price_per_million,cached_input_price_per_million,
                output_price_per_million,effective_at
            ) VALUES ('60000000-0000-4000-8000-000000000002','gpt-5.6-sol',4,0.4,16,now())
            """
        )
    second = reserve(billing, TENANT_A, "new-price")
    first_charge = billing.settle(
        first.operation_id, usage=Usage(100, 0, 10), upstream_request_id="client:old", upstream_model="gpt-5.6-sol"
    )
    second_charge = billing.settle(
        second.operation_id, usage=Usage(100, 0, 10), upstream_request_id="client:new", upstream_model="gpt-5.6-sol"
    )
    assert first_charge == Decimal("0.00028000")
    assert second_charge == Decimal("0.00056000")
