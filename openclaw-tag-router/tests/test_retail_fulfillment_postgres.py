from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from openclaw_app.account.database import AccountDatabase, AccountDatabaseSettings
from openclaw_app.services.retail_fulfillment import RetailFulfillmentError, RetailFulfillmentService


DATABASE_URL = os.getenv("OPENCLAW_U7_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="OPENCLAW_U7_TEST_DATABASE_URL is required")
ADMIN = "10000000-0000-4000-8000-000000000001"
USERS = {
    "A": ("10000000-0000-4000-8000-00000000000a", "20000000-0000-4000-8000-00000000000a", "30000000-0000-4000-8000-00000000000a"),
    "B": ("10000000-0000-4000-8000-00000000000b", "20000000-0000-4000-8000-00000000000b", "30000000-0000-4000-8000-00000000000b"),
    "C": ("10000000-0000-4000-8000-00000000000c", "20000000-0000-4000-8000-00000000000c", "30000000-0000-4000-8000-00000000000c"),
}


@pytest.fixture()
def service(tmp_path) -> RetailFulfillmentService:
    export_root = tmp_path / "redemption-exports"
    export_root.mkdir(mode=0o700)
    database = AccountDatabase(AccountDatabaseSettings(DATABASE_URL))
    with database.connect() as connection:
        connection.execute(
            "TRUNCATE openclaw_account.refund_adjustments,openclaw_account.affiliate_ledger,openclaw_account.fulfillments,"
            "openclaw_account.redemption_codes,openclaw_account.redemption_batches,openclaw_account.product_mappings,"
            "openclaw_account.admin_audit,openclaw_account.sessions,openclaw_account.ledger_entries,openclaw_account.wallet_accounts,"
            "openclaw_account.affiliate_edges,openclaw_account.affiliate_profiles,openclaw_account.tenants,openclaw_account.users CASCADE"
        )
        connection.execute(
            "INSERT INTO openclaw_account.users(id,username,password_hash,role,display_name) VALUES (%s,%s,%s,'admin',%s)",
            (ADMIN, "u7-admin", "x" * 60, "U7 Admin"),
        )
        for label, (user, tenant, wallet) in USERS.items():
            connection.execute(
                "INSERT INTO openclaw_account.users(id,username,password_hash,role,display_name) VALUES (%s,%s,%s,'user',%s)",
                (user, f"u7-{label.lower()}", "x" * 60, f"U7 {label}"),
            )
            connection.execute("INSERT INTO openclaw_account.tenants(id,primary_user_id) VALUES (%s,%s)", (tenant, user))
            connection.execute(
                "INSERT INTO openclaw_account.tenant_members(tenant_id,user_id,role,status) "
                "VALUES (%s,%s,'owner','active')",
                (tenant, user),
            )
            connection.execute("INSERT INTO openclaw_account.wallet_accounts(id,tenant_id) VALUES (%s,%s)", (wallet, tenant))
        connection.execute(
            "INSERT INTO openclaw_account.product_mappings("
            "id,external_provider,external_product_id,plan_id,purchase_url,idempotency_key,created_by_user_id"
            ") VALUES ("
            "'71000000-0000-4000-8000-000000000010','liandong','product-1',"
            "'80000000-0000-4000-8000-000000000100','https://www.ldxp.cn/goods/test-100','u7-test-mapping',%s)",
            (ADMIN,),
        )
        connection.execute(
            "INSERT INTO openclaw_account.affiliate_edges(id,inviter_user_id,invitee_user_id) VALUES ('71000000-0000-4000-8000-000000000001',%s,%s),('71000000-0000-4000-8000-000000000002',%s,%s)",
            (USERS["A"][0], USERS["B"][0], USERS["B"][0], USERS["C"][0]),
        )
    return RetailFulfillmentService(
        database,
        code_secret=b"u7-test-secret-32-bytes-minimum-value",
        export_root=export_root,
    )


def issue(service: RetailFulfillmentService, key: str, count: int = 1):
    return service.create_batch(actor_user_id=ADMIN, plan_code="mediaclaw-cny-100", count=count, idempotency_key=key)


def first_code(batch) -> str:
    assert batch.export_path.stat().st_mode & 0o777 == 0o600
    codes = batch.export_path.read_text(encoding="ascii").splitlines()
    assert len(codes) == batch.code_count
    return codes[0]


def test_same_code_concurrency_twenty_times_credits_once(service: RetailFulfillmentService) -> None:
    code = first_code(issue(service, "batch-concurrency"))
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: service.redeem(tenant_id=USERS["B"][1], user_id=USERS["B"][0], code=code), range(20)))
    assert len({item.fulfillment_id for item in results}) == 1
    with service.database.connect() as connection:
        assert connection.execute("SELECT available FROM openclaw_account.wallet_accounts WHERE tenant_id=%s", (USERS["B"][1],)).fetchone()[0] == Decimal("100.00000000")
        assert connection.execute("SELECT available FROM openclaw_account.wallet_accounts WHERE tenant_id=%s", (USERS["A"][1],)).fetchone()[0] == Decimal("10.00000000")
        assert connection.execute("SELECT count(*) FROM openclaw_account.fulfillments").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM openclaw_account.ledger_entries").fetchone()[0] == 2


def test_crash_recovery_finishes_pending_claim_exactly_once(service: RetailFulfillmentService) -> None:
    code = first_code(issue(service, "batch-recovery"))
    digest = service._digest(code)
    with service.database.connect() as connection:
        row = connection.execute(
            "SELECT c.id,p.id,p.credit_amount,w.id FROM openclaw_account.redemption_codes c JOIN openclaw_account.redemption_batches b ON b.id=c.batch_id JOIN openclaw_account.product_mappings m ON m.id=b.product_mapping_id JOIN openclaw_account.plans p ON p.id=m.plan_id JOIN openclaw_account.wallet_accounts w ON w.tenant_id=%s WHERE c.code_hmac=%s FOR UPDATE",
            (USERS["C"][1], digest),
        ).fetchone()
        fulfillment = "72000000-0000-4000-8000-000000000001"
        connection.execute("UPDATE openclaw_account.redemption_codes SET status='redeeming',redeeming_at=now() WHERE id=%s", (row[0],))
        connection.execute("INSERT INTO openclaw_account.fulfillments(id,code_id,tenant_id,plan_id,wallet_account_id,credited_amount) VALUES (%s,%s,%s,%s,%s,%s)", (fulfillment,row[0],USERS["C"][1],row[1],row[3],row[2]))
    first = service.recover(fulfillment)
    second = service.recover(fulfillment)
    assert first == second
    with service.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM openclaw_account.ledger_entries").fetchone()[0] == 2


def test_direct_reward_is_ten_percent_and_never_multilevel(service: RetailFulfillmentService) -> None:
    code = first_code(issue(service, "batch-direct"))
    result = service.redeem(tenant_id=USERS["C"][1], user_id=USERS["C"][0], code=code)
    assert result.affiliate_amount == Decimal("10.00000000")
    with service.database.connect() as connection:
        balances = dict(connection.execute("SELECT tenant_id::text,available FROM openclaw_account.wallet_accounts"))
    assert balances[USERS["C"][1]] == Decimal("100.00000000")
    assert balances[USERS["B"][1]] == Decimal("10.00000000")
    assert balances[USERS["A"][1]] == Decimal("0E-8")


def test_refund_records_reversal_and_debt_without_negative_balance(service: RetailFulfillmentService) -> None:
    code = first_code(issue(service, "batch-refund"))
    result = service.redeem(tenant_id=USERS["B"][1], user_id=USERS["B"][0], code=code)
    with service.database.connect() as connection:
        connection.execute("UPDATE openclaw_account.wallet_accounts SET available=25 WHERE tenant_id=%s", (USERS["B"][1],))
        connection.execute("UPDATE openclaw_account.wallet_accounts SET available=2 WHERE tenant_id=%s", (USERS["A"][1],))
    refund = service.refund(actor_user_id=ADMIN, fulfillment_id=result.fulfillment_id, reason="customer refund")
    assert refund == {"principalDebited": "25.00000000", "principalDebt": "75.00000000", "affiliateDebited": "2.00000000", "affiliateDebt": "8.00000000"}
    assert service.refund(actor_user_id=ADMIN, fulfillment_id=result.fulfillment_id, reason="customer refund") == refund
    with service.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM openclaw_account.wallet_accounts WHERE available<0").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM openclaw_account.refund_adjustments").fetchone()[0] == 1


def test_refund_before_spend_fully_reverses_principal_and_affiliate(service: RetailFulfillmentService) -> None:
    code = first_code(issue(service, "batch-full-refund"))
    result = service.redeem(tenant_id=USERS["B"][1], user_id=USERS["B"][0], code=code)
    refund = service.refund(actor_user_id=ADMIN, fulfillment_id=result.fulfillment_id, reason="full reversal")
    assert refund == {
        "principalDebited": "100.00000000",
        "principalDebt": "0E-8",
        "affiliateDebited": "10.00000000",
        "affiliateDebt": "0E-8",
    }
    with service.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM openclaw_account.wallet_accounts WHERE available<>0").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM openclaw_account.ledger_entries").fetchone()[0] == 4


def test_batch_key_cannot_create_duplicate_inventory(service: RetailFulfillmentService) -> None:
    first = issue(service, "batch-idempotency", count=3)
    with pytest.raises(RetailFulfillmentError) as raised:
        issue(service, "batch-idempotency", count=3)
    assert raised.value.code == "idempotency_conflict"
    assert list(first.export_path.parent.iterdir()) == [first.export_path]
    with service.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM openclaw_account.redemption_batches").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM openclaw_account.redemption_codes").fetchone()[0] == 3


def test_database_contains_only_hmac_not_plaintext_code(service: RetailFulfillmentService) -> None:
    code = first_code(issue(service, "batch-secret"))
    with service.database.connect() as connection:
        stored = connection.execute("SELECT code_hmac FROM openclaw_account.redemption_codes").fetchone()[0]
    assert bytes(stored) == service._digest(code)
    assert code.encode() not in bytes(stored)
