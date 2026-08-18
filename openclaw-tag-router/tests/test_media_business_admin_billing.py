from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

import pytest

from openclaw_app.services.media_business.admin_billing import (
    AdminBillingContext,
    AdminBillingForbidden,
    AdminBillingIdempotencyConflict,
    AdminBillingInternalError,
    AdminBillingInvalidRequest,
    AdminBillingRevisionConflict,
    AdminBillingService,
    AdminBillingUnauthorized,
    _decode_signed,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
ACTOR = UUID("11111111-1111-4111-8111-111111111111")
SESSION = UUID("22222222-2222-4222-8222-222222222222")
TENANT = UUID("33333333-3333-4333-8333-333333333333")
FULFILLMENT = UUID("44444444-4444-4444-8444-444444444444")
CONTEXT = AdminBillingContext(ACTOR, SESSION)


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Result:
        self.calls.append((query, params))
        return _Result()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _Database:
    def __init__(self) -> None:
        self.connections: list[_Connection] = []

    def connect(self) -> _Connection:
        connection = _Connection()
        self.connections.append(connection)
        return connection


class _Storage:
    def __init__(self) -> None:
        self.audit: list[dict[str, Any]] = []
        self.authorization_calls: list[AdminBillingContext] = []
        self.permission_error: Exception | None = None

    def require_admin(self, connection: Any, context: AdminBillingContext, now: datetime) -> None:
        self.authorization_calls.append(context)
        if self.permission_error is not None:
            raise self.permission_error

    def find_idempotency(
        self,
        connection: Any,
        actor_user_id: UUID,
        operation: str,
        key: str,
    ) -> dict[str, Any] | None:
        for record in reversed(self.audit):
            metadata = record["metadata"]
            if (
                record["actorUserId"] == actor_user_id
                and record["operation"] == operation
                and metadata["idempotencyKey"] == key
            ):
                return metadata
        return None

    def save_audit(self, connection: Any, **record: Any) -> None:
        self.audit.append(record)


def _summary() -> dict[str, Any]:
    return {
        "plans": [{"planCode": "starter", "name": "Starter"}],
        "productMappings": [],
        "redemptionBatches": [],
        "fulfillments": [],
        "grants": [],
        "ledgerRevision": 4,
    }


def _service(
    state: dict[str, Any] | None = None,
    storage: _Storage | None = None,
    **writers: Callable[..., Any],
) -> tuple[AdminBillingService, dict[str, Any], _Storage]:
    summary = state or _summary()
    audit = storage or _Storage()
    service = AdminBillingService(
        _Database(),
        public_id_secret=b"b13-test-secret-20260805",
        summary_reader=lambda: summary,
        storage=audit,
        now=lambda: NOW,
        **writers,
    )
    return service, summary, audit


def _mapping_kwargs() -> dict[str, str]:
    return {
        "plan_code": "starter",
        "external_product_id": "sku-001",
        "purchase_url": "https://ldxp.cn/products/sku-001",
        "reason": "operator correction",
        "idempotency_key": "mapping-001",
    }


def test_summary_has_if2_shape_and_requires_administrator() -> None:
    service, state, storage = _service()

    with pytest.raises(AdminBillingUnauthorized):
        service.get_admin_billing_summary(None)

    with pytest.raises(AdminBillingForbidden):
        service.get_admin_billing_summary(
            AdminBillingContext(ACTOR, SESSION, role="user")
        )

    response = service.get_admin_billing_summary(CONTEXT)

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert isinstance(response["revision"], int)
    assert response["summary"] == state
    assert set(response["summary"]) == {
        "plans",
        "productMappings",
        "redemptionBatches",
        "fulfillments",
        "grants",
        "ledgerRevision",
    }
    assert storage.authorization_calls == [CONTEXT]


def test_storage_permission_failure_is_not_bypassed() -> None:
    storage = _Storage()
    storage.permission_error = AdminBillingForbidden("maintainer permission is required")
    service, _, _ = _service(storage=storage)

    with pytest.raises(AdminBillingForbidden, match="maintainer permission"):
        service.get_admin_billing_summary(CONTEXT)


def test_b12_tenant_public_id_uses_tenant_id_and_grant_decodes_it() -> None:
    grant_calls: list[dict[str, Any]] = []

    def grant_writer(**kwargs: Any) -> None:
        grant_calls.append(kwargs)

    service, _, _ = _service(grant_writer=grant_writer)
    public_tenant_id = service.public_tenant_id(TENANT)

    assert _decode_signed(public_tenant_id, service._public_id_secret) == {
        "namespace": "b12-tenant",
        "tenantId": str(TENANT),
    }

    response = service.create_admin_billing_grant(
        CONTEXT,
        public_tenant_id=public_tenant_id,
        amount="2.50000000",
        reason="service recovery",
        idempotency_key="grant-001",
    )

    assert grant_calls[0]["target_tenant_id"] == TENANT
    assert grant_calls[0]["amount"] == "2.50000000"
    assert response["ok"] is True


def test_reason_validation_happens_before_any_writer() -> None:
    calls: list[dict[str, Any]] = []

    def mapping_writer(**kwargs: Any) -> None:
        calls.append(kwargs)

    service, _, _ = _service(product_mapping_writer=mapping_writer)
    request = _mapping_kwargs()
    request["reason"] = "  "

    with pytest.raises(AdminBillingInvalidRequest) as caught:
        service.create_admin_product_mapping(CONTEXT, **request)

    assert caught.value.field == "reason"
    assert calls == []


def test_idempotency_replays_readback_and_rejects_changed_payload() -> None:
    state = _summary()
    calls: list[dict[str, Any]] = []

    def mapping_writer(**kwargs: Any) -> None:
        calls.append(kwargs)
        state["productMappings"].append(
            {
                "mappingId": "public-mapping-001",
                "planCode": kwargs["plan_code"],
            }
        )

    service, _, storage = _service(state, product_mapping_writer=mapping_writer)
    request = _mapping_kwargs()

    first = service.create_admin_product_mapping(CONTEXT, **request)
    replay = service.create_admin_product_mapping(CONTEXT, **request)

    assert first == replay
    assert first["ok"] is True
    assert first["schemaVersion"] == "media_web_business_pages_v2"
    assert first["revision"] == service.get_admin_billing_summary(CONTEXT)["revision"]
    assert first["updatedAt"] == "2026-08-05T12:00:00Z"
    assert len(calls) == 1
    assert len(storage.audit) == 1
    assert storage.audit[0]["metadata"]["readbackRevision"] == first["revision"]

    changed = dict(request)
    changed["external_product_id"] = "sku-002"
    with pytest.raises(AdminBillingIdempotencyConflict):
        service.create_admin_product_mapping(CONTEXT, **changed)

    assert len(calls) == 1
    assert len(storage.audit) == 1


def test_expected_revision_blocks_recovery_before_canonical_writer() -> None:
    recover_calls: list[dict[str, Any]] = []

    def recover_writer(**kwargs: Any) -> None:
        recover_calls.append(kwargs)

    service, _, storage = _service(recover_writer=recover_writer)
    current_revision = service.get_admin_billing_summary(CONTEXT)["revision"]

    with pytest.raises(AdminBillingRevisionConflict):
        service.recover_admin_fulfillment(
            CONTEXT,
            service.public_fulfillment_id(FULFILLMENT),
            reason="reconciliation retry",
            expected_revision=current_revision + 1,
            idempotency_key="recover-001",
        )

    assert recover_calls == []
    assert storage.audit == []


def test_all_mutations_call_canonical_writers_and_record_readback() -> None:
    calls: dict[str, list[dict[str, Any]]] = {
        "mapping": [],
        "grant": [],
        "batch": [],
        "recover": [],
        "refund": [],
    }

    def mapping_writer(**kwargs: Any) -> None:
        calls["mapping"].append(kwargs)

    def grant_writer(**kwargs: Any) -> None:
        calls["grant"].append(kwargs)

    def batch_writer(**kwargs: Any) -> None:
        calls["batch"].append(kwargs)

    def recover_writer(**kwargs: Any) -> None:
        calls["recover"].append(kwargs)

    def refund_writer(**kwargs: Any) -> None:
        calls["refund"].append(kwargs)

    service, _, storage = _service(
        product_mapping_writer=mapping_writer,
        grant_writer=grant_writer,
        batch_writer=batch_writer,
        recover_writer=recover_writer,
        refund_writer=refund_writer,
    )
    public_tenant_id = service.public_tenant_id(TENANT)
    public_fulfillment_id = service.public_fulfillment_id(FULFILLMENT)
    revision = service.get_admin_billing_summary(CONTEXT)["revision"]

    mapping_response = service.create_admin_product_mapping(
        CONTEXT, **_mapping_kwargs()
    )
    grant_response = service.create_admin_billing_grant(
        CONTEXT,
        public_tenant_id=public_tenant_id,
        amount="1.00000000",
        reason="grant reason",
        idempotency_key="grant-002",
    )
    batch_response = service.create_admin_redemption_batch(
        CONTEXT,
        plan_code="starter",
        count=3,
        reason="batch reason",
        idempotency_key="batch-001",
    )
    recover_response = service.recover_admin_fulfillment(
        CONTEXT,
        public_fulfillment_id,
        reason="recover reason",
        expected_revision=revision,
        idempotency_key="recover-002",
    )
    refund_response = service.refund_admin_fulfillment(
        CONTEXT,
        public_fulfillment_id,
        reason="refund reason",
        expected_revision=revision,
        idempotency_key="refund-001",
    )

    assert calls["mapping"][0]["actor_user_id"] == ACTOR
    assert calls["mapping"][0]["actor_session_id"] == SESSION
    assert calls["mapping"][0]["plan_code"] == "starter"
    assert calls["grant"][0]["target_tenant_id"] == TENANT
    assert calls["batch"][0] == {
        "actor_user_id": ACTOR,
        "plan_code": "starter",
        "count": 3,
        "idempotency_key": "batch-001",
    }
    assert calls["recover"][0] == {"fulfillment_id": FULFILLMENT}
    assert calls["refund"][0] == {
        "actor_user_id": ACTOR,
        "fulfillment_id": FULFILLMENT,
        "reason": "refund reason",
    }
    for response in (
        mapping_response,
        grant_response,
        batch_response,
        recover_response,
        refund_response,
    ):
        assert response["ok"] is True
        assert response["revision"] == revision
        assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert len(storage.audit) == 5
    assert all(
        record["metadata"]["status"] == "succeeded"
        and record["metadata"]["readbackRevision"] == revision
        for record in storage.audit
    )


def test_summary_shape_mismatch_fails_closed() -> None:
    state = _summary()
    state.pop("grants")
    service, _, _ = _service(state)

    with pytest.raises(AdminBillingInternalError):
        service.get_admin_billing_summary(CONTEXT)
