from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from openclaw_app.services.media_business.foundation import TenantContext
from openclaw_app.services.media_business.usage_billing import (
    UsageBillingConflict,
    UsageBillingInternalError,
    UsageBillingService,
)


TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER = "11111111-1111-4111-8111-111111111111"
CONTEXT = TenantContext(TENANT, USER)


class FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, usage_rows: list[tuple[object, ...]]) -> None:
        self.usage_rows = usage_rows
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.redemption: tuple[str, str] | None = None
        self.redemption_readback: tuple[str, datetime, int] | None = (
            "succeeded",
            datetime(2026, 8, 5, 2, 1, tzinfo=timezone.utc),
            5,
        )
        self.image_event: tuple[object, ...] | None = None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeCursor:
        self.queries.append((query, params))
        if "FROM openclaw_account.fulfillments" in query:
            return FakeCursor([self.redemption_readback] if self.redemption_readback else [])
        if "FROM openclaw_account.usage_events" in query:
            return FakeCursor([self.image_event] if self.image_event else [])
        if "INSERT INTO openclaw_account.usage_events" in query:
            self.image_event = (
                str(params[2]),
                "image",
                str(params[4]),
                params[3],
                "images",
                params[5],
                str(params[6]),
                datetime(2026, 8, 5, 2, 0, tzinfo=timezone.utc),
            )
            return FakeCursor([self.image_event])
        if "wallet_accounts" in query:
            return FakeCursor([(Decimal("8.50000000"), datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc), 4)])
        if "FROM openclaw_account.plans" in query:
            return FakeCursor([
                ("mediaclaw-cny-20", "Twenty credits", Decimal("20"), Decimal("20.00"), "credit", "all", "balance_pack", 3, "https://example.test/buy/20"),
                ("mediaclaw-cny-50", "Fifty credits", Decimal("50"), Decimal("50.00"), "credit", "all", "balance_pack", 2, None),
            ])
        if "pg_advisory_xact_lock" in query:
            return FakeCursor([])
        if "b08_redemption_idempotency" in query and query.lstrip().startswith("SELECT"):
            return FakeCursor([self.redemption] if self.redemption else [])
        if "b08_redemption_idempotency" in query and query.lstrip().startswith("INSERT"):
            self.redemption = (str(params[3]), str(params[4]))
            return FakeCursor([])
        if "FROM openclaw_account.billing_usage_events" in query:
            return FakeCursor(self.usage_rows)
        raise AssertionError(f"unexpected query: {query}")


class FakeFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    @contextmanager
    def __call__(self):
        yield self.connection


class FakeRedeemer:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def redeem(self, *, tenant_id: str, user_id: str, code: str):
        self.calls.append({"tenant_id": tenant_id, "user_id": user_id, "code": code})
        return SimpleNamespace(
            fulfillment_id="72000000-0000-4000-8000-000000000001",
            plan_code="mediaclaw-cny-20",
            credited_amount=Decimal("20.00000000"),
            affiliate_amount=Decimal("0E-8"),
            status="succeeded",
        )


def usage_rows() -> list[tuple[object, ...]]:
    return [
        (
            "usage_text_01",
            "text",
            "gpt-5.6-sol",
            Decimal("120"),
            "tokens",
            Decimal("0.50000000"),
            "succeeded",
            datetime(2026, 8, 4, 15, 30, tzinfo=timezone.utc),
        ),
        (
            "usage_image_01",
            "image",
            "image-1",
            Decimal("2"),
            "images",
            Decimal("1.25000000"),
            "succeeded",
            datetime(2026, 8, 4, 16, 30, tzinfo=timezone.utc),
        ),
        (
            "credit_01",
            "credit",
            "mediaclaw-cny-20",
            Decimal("20"),
            "credit",
            Decimal("0E-8"),
            "succeeded",
            datetime(2026, 8, 4, 17, 30, tzinfo=timezone.utc),
        ),
    ]


def service(connection: FakeConnection, redeemer: FakeRedeemer | None = None) -> UsageBillingService:
    return UsageBillingService(
        FakeFactory(connection),
        cursor_secret=b"b08-test-cursor-secret-32-bytes-minimum",
        redemption_service=redeemer,
        clock=lambda: datetime(2026, 8, 5, 2, 0, tzinfo=timezone.utc),
    )


def test_balance_and_packs_are_typed_and_contract_bound() -> None:
    connection = FakeConnection(usage_rows())
    billing = service(connection)

    balance = billing.get_billing_balance(CONTEXT)
    packs = billing.list_billing_balance_packs(CONTEXT)

    assert balance == {
        "schemaVersion": "media_web_business_pages_v2",
        "revision": 4,
        "balance": {
            "available": "8.50000000",
            "currency": "credit",
            "asOf": "2026-08-05T01:00:00+00:00",
            "revision": 4,
        },
    }
    assert packs["items"][0] == {
        "balancePackCode": "mediaclaw-cny-20",
        "name": "Twenty credits",
        "creditAmount": 20,
        "priceCny": "20.00",
        "currency": "credit",
        "audience": "all",
        "productKind": "balance_pack",
        "purchaseAvailable": True,
        "purchaseUrl": "https://example.test/buy/20",
    }
    assert connection.queries[:2] == [
        (billing._BALANCE_QUERY, (TENANT,)),
        (billing._BALANCE_PACKS_QUERY, ()),
    ]


def test_usage_and_summary_conserve_text_image_quantities_and_charge() -> None:
    connection = FakeConnection(usage_rows())
    billing = service(connection)

    listing = billing.list_billing_usage(CONTEXT, page_size=10)
    summary = billing.get_billing_usage_summary(CONTEXT)
    daily = billing.daily_usage_summary(CONTEXT, timezone_name="Asia/Shanghai")

    assert [item["kind"] for item in listing["items"]] == ["text", "image", "credit"]
    assert listing["items"][0]["quantity"] == 120
    assert listing["items"][1]["quantity"] == 2
    assert summary["summary"] == {
        "textQuantity": 120,
        "imageQuantity": 2,
        "totalCharge": "1.75000000",
        "currency": "credit",
        "from": "2026-08-04T15:30:00+00:00",
        "to": "2026-08-04T17:30:00+00:00",
        "revision": 3,
    }
    assert [(item["date"], item["textQuantity"], item["imageQuantity"]) for item in daily] == [
        ("2026-08-04", 120, 0),
        ("2026-08-05", 0, 2),
    ]
    assert any("model_price_versions" in query for query, _ in connection.queries)

    usage_query, usage_params = next((query, params) for query, params in connection.queries if "COUNT(*) OVER" in query)
    assert "CAST(%s AS TIMESTAMPTZ) IS NULL" in usage_query
    assert "e.public_usage_id > CAST(%s AS TEXT)" in usage_query
    assert usage_params[1:5] == (None, None, None, None)


def test_unknown_charge_fails_closed_instead_of_rendering_zero() -> None:
    connection = FakeConnection([
        (
            "usage_unknown",
            "image",
            "image-1",
            Decimal("1"),
            "images",
            None,
            "pending_reconciliation",
            datetime(2026, 8, 5, tzinfo=timezone.utc),
        )
    ])

    with pytest.raises(UsageBillingInternalError, match="charge"):
        service(connection).list_billing_usage(CONTEXT)


def test_image_usage_event_is_immutable_and_source_idempotent() -> None:
    connection = FakeConnection(usage_rows())
    billing = service(connection)
    source_id = "22000000-0000-4000-8000-000000000001"
    first = billing.record_image_usage_event(
        CONTEXT,
        public_usage_id="usage_image_02",
        model="image-2",
        quantity=3,
        charge="2.50000000",
        source_type="image_task",
        source_id=source_id,
    )
    replay = billing.record_image_usage_event(
        CONTEXT,
        public_usage_id="usage_image_02",
        model="image-2",
        quantity=3,
        charge="2.50000000",
        source_type="image_task",
        source_id=source_id,
    )

    assert first == replay
    assert first["item"]["kind"] == "image"
    assert first["item"]["charge"] == "2.50000000"
    inserts = [item for item in connection.queries if "INSERT INTO openclaw_account.usage_events" in item[0]]
    assert len(inserts) == 1
    assert inserts[0][1][:3] == (TENANT, USER, "usage_image_02")
    with pytest.raises(UsageBillingConflict):
        billing.record_image_usage_event(
            CONTEXT,
            public_usage_id="usage_image_03",
            model="image-2",
            quantity=3,
            charge="2.50000000",
            source_type="image_task",
            source_id=source_id,
        )

def test_image_unknown_charge_readback_fails_closed() -> None:
    connection = FakeConnection(usage_rows())
    connection.image_event = (
        "usage_image_04",
        "image",
        "image-2",
        Decimal("1"),
        "images",
        None,
        "pending_reconciliation",
        datetime(2026, 8, 5, 2, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(UsageBillingInternalError, match="charge"):
        service(connection).record_image_usage_event(CONTEXT, public_usage_id="usage_image_04", model="image-2", quantity=1, charge=None, source_type="image_task", source_id="22000000-0000-4000-8000-000000000004", status="pending_reconciliation")

def test_redemption_is_postgres_idempotent_and_rejects_key_reuse() -> None:
    connection = FakeConnection(usage_rows())
    redeemer = FakeRedeemer()
    billing = service(connection, redeemer)

    first = billing.redeem_billing_code(CONTEXT, code="OC-test-code", idempotency_key="redeem-1")
    replay = billing.redeem_billing_code(CONTEXT, code="OC-test-code", idempotency_key="redeem-1")

    assert first == replay
    assert len(redeemer.calls) == 1
    with pytest.raises(UsageBillingConflict):
        billing.redeem_billing_code(CONTEXT, code="OC-other-code", idempotency_key="redeem-1")


def test_migration_declares_typed_events_active_plan_and_immutable_boundaries() -> None:
    migration = Path(__file__).parents[1] / "openclaw_app/migrations/014_b08_usage_billing.sql"
    text = migration.read_text(encoding="utf-8")

    for fragment in (
        "billing_usage_events",
        "tenant_billing_plans",
        "b08_redemption_idempotency",
        "usage_billing_events_immutable",
        "ledger_entries_immutable",
        "model_price_versions",
        "text_quota",
        "image_quota",
    ):
        assert fragment in text
    assert "BEFORE UPDATE OR DELETE" in text
    assert "UNIQUE (tenant_id, operation, idempotency_key)" in text
    service_text = (Path(__file__).parents[1] / "openclaw_app/services/media_business/usage_billing.py").read_text(encoding="utf-8")
    assert "ON CONFLICT (tenant_id, operation, idempotency_key)" in service_text


def test_service_never_projects_private_tenant_identity() -> None:
    connection = FakeConnection(usage_rows())
    payload = service(connection).list_billing_usage(CONTEXT)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert TENANT not in encoded
    assert "tenant_id" not in encoded
