from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from openclaw_app.services.media_business.admin_upstreams import (
    AdminUpstreamsContext,
    AdminUpstreamsForbidden,
    AdminUpstreamsIdempotencyConflict,
    AdminUpstreamsInvalidRequest,
    AdminUpstreamsRevisionConflict,
    AdminUpstreamsService,
    AdminUpstreamsUnavailable,
)


UTC = timezone.utc
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000001")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000002")
OPERATION_ID = UUID("10000000-0000-4000-8000-000000000001")
TENANT_ID = "20000000-0000-4000-8000-000000000001"
SYNCED_AT = "2026-08-05T04:00:00Z"


class FakeConnection:
    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False


class FakeStorage:
    def __init__(self) -> None:
        self.idempotency: dict[tuple[UUID, str, str], dict[str, object]] = {}
        self.audits: list[dict[str, object]] = []
        self.authorize_calls = 0

    def require_admin(self, connection: FakeConnection, context: AdminUpstreamsContext, now: datetime) -> None:
        self.authorize_calls += 1
        if context.actor_user_id != ADMIN_ID or context.actor_session_id != SESSION_ID:
            raise AdminUpstreamsForbidden()

    def find_idempotency(
        self,
        connection: FakeConnection,
        actor_user_id: UUID,
        operation: str,
        key: str,
    ) -> dict[str, object] | None:
        return self.idempotency.get((actor_user_id, operation, key))

    def save_audit(self, connection: FakeConnection, **record: object) -> None:
        self.audits.append(record)
        metadata = record["metadata"]
        assert isinstance(metadata, dict)
        self.idempotency[(record["actorUserId"], record["operation"], metadata["idempotencyKey"])] = metadata


class FakeGateway:
    def __init__(self) -> None:
        self.health: dict[str, object] = {
            "provider": "sub2api",
            "status": "active",
            "version": 4,
            "token": "secret-token-must-not-escape",
            "username": "upstream-private-user",
            "availableAccountCount": 3,
            "unhealthyAccountCount": 1,
            "lastSyncedAt": SYNCED_AT,
        }
        self.queue: list[dict[str, object]] = [
            {
                "operationId": str(OPERATION_ID),
                "tenantId": TENANT_ID,
                "correlationKey": "private-correlation-key",
                "createdAt": SYNCED_AT,
            },
            {
                "operationId": "30000000-0000-4000-8000-000000000002",
                "tenantId": "40000000-0000-4000-8000-000000000002",
                "correlationKey": "private-correlation-key-two",
                "createdAt": SYNCED_AT,
            },
        ]
        self.reconcile_calls = 0
        self.rotate_calls = 0
        self.revoke_calls = 0
        self.health_unavailable = False

    def credential_health(self) -> dict[str, object]:
        if self.health_unavailable:
            raise RuntimeError("credential source down")
        return dict(self.health)

    def reconciliation_queue(self, *, limit: int) -> list[dict[str, object]]:
        return list(self.queue[:limit])

    def reconcile_operation(self, operation_id: str) -> dict[str, object]:
        assert operation_id == str(OPERATION_ID)
        self.reconcile_calls += 1
        self.queue.pop(0)
        return {"operationId": operation_id, "charge": "12.34", "status": "succeeded"}

    def rotate_credential(self) -> dict[str, object]:
        self.rotate_calls += 1
        self.health.update({"status": "active", "version": 5, "lastSyncedAt": "2026-08-05T04:05:00Z"})
        return {"provider": "sub2api", "status": "active", "version": 5}

    def revoke_credential(self) -> dict[str, object]:
        self.revoke_calls += 1
        self.health.update({"status": "retired", "version": 5, "lastSyncedAt": "2026-08-05T04:06:00Z"})
        return {"provider": "sub2api", "status": "retired", "version": 5}


def make_service() -> tuple[AdminUpstreamsService, FakeGateway, FakeStorage]:
    gateway = FakeGateway()
    storage = FakeStorage()
    service = AdminUpstreamsService(
        lambda: FakeConnection(),
        upstream_gateway=gateway,
        storage=storage,
        now=lambda: datetime(2026, 8, 5, 4, 0, tzinfo=UTC),
    )
    return service, gateway, storage


def admin_context(*, maintainer: bool = True) -> AdminUpstreamsContext:
    return AdminUpstreamsContext(ADMIN_ID, SESSION_ID, maintainer=maintainer)


def test_get_projects_complete_redacted_aggregate() -> None:
    service, _gateway, _storage = make_service()

    response = service.get_admin_upstreams(admin_context())

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    summary = response["summary"]
    assert summary["availableAccountCount"] == 3
    assert summary["unhealthyAccountCount"] == 1
    assert summary["credentialHealth"] == "healthy"
    assert summary["pendingReconciliationCount"] == 2
    assert summary["lastSyncedAt"] == SYNCED_AT
    assert isinstance(response["revision"], int)
    assert set(summary) == {
        "availableAccountCount",
        "unhealthyAccountCount",
        "credentialHealth",
        "pendingReconciliationCount",
        "lastSyncedAt",
        "revision",
    }

    serialized = json.dumps(response, ensure_ascii=False)
    for forbidden in (
        "secret-token-must-not-escape",
        "upstream-private-user",
        "private-correlation-key",
        TENANT_ID,
        str(OPERATION_ID),
        "tenantId",
        "operationId",
        "provider",
        "secretRef",
        "accessToken",
    ):
        assert forbidden not in serialized


def test_non_admin_is_rejected_before_database_or_source_access() -> None:
    service, gateway, storage = make_service()
    context = AdminUpstreamsContext(ADMIN_ID, SESSION_ID, role="user", maintainer=True)

    with pytest.raises(AdminUpstreamsForbidden):
        service.get_admin_upstreams(context)

    assert storage.authorize_calls == 0
    assert gateway.reconcile_calls == 0


def test_credential_mutations_require_maintainer_and_reason() -> None:
    service, gateway, storage = make_service()
    regular_admin = admin_context(maintainer=False)
    revision = service.get_admin_upstreams(regular_admin)["revision"]

    with pytest.raises(AdminUpstreamsForbidden):
        service.rotate_admin_upstream_credential(
            regular_admin,
            reason="rotate",
            expected_revision=revision,
            idempotency_key="b14-rotate-001",
        )
    with pytest.raises(AdminUpstreamsInvalidRequest):
        service.revoke_admin_upstream_credential(
            admin_context(),
            reason=" ",
            expected_revision=revision,
            idempotency_key="b14-revoke-001",
        )

    assert gateway.rotate_calls == 0
    assert gateway.revoke_calls == 0
    assert storage.audits == []


def test_reconciliation_requires_revision_reason_reads_back_and_replays() -> None:
    service, gateway, storage = make_service()
    context = admin_context()
    initial = service.get_admin_upstreams(context)

    result = service.reconcile_admin_billing_operation(
        context,
        str(OPERATION_ID),
        reason="settle pending upstream usage",
        expected_revision=initial["revision"],
        idempotency_key="b14-reconcile-001",
    )

    assert result["ok"] is True
    assert result["schemaVersion"] == "media_web_business_pages_v2"
    assert set(result) == {"schemaVersion", "revision", "ok", "updatedAt"}
    assert result["revision"] != initial["revision"]
    assert gateway.reconcile_calls == 1
    assert storage.audits[-1]["reason"] == "settle pending upstream usage"
    assert "operationId" not in json.dumps(result)
    assert "charge" not in json.dumps(result)

    replay = service.reconcile_admin_billing_operation(
        context,
        str(OPERATION_ID),
        reason="settle pending upstream usage",
        expected_revision=initial["revision"],
        idempotency_key="b14-reconcile-001",
    )
    assert replay == result
    assert gateway.reconcile_calls == 1

    with pytest.raises(AdminUpstreamsIdempotencyConflict):
        service.reconcile_admin_billing_operation(
            context,
            str(OPERATION_ID),
            reason="different reason",
            expected_revision=initial["revision"],
            idempotency_key="b14-reconcile-001",
        )


def test_rotation_and_revoke_are_idempotent_and_return_only_readback() -> None:
    service, gateway, _storage = make_service()
    context = admin_context()
    revision = service.get_admin_upstreams(context)["revision"]

    rotated = service.rotate_admin_upstream_credential(
        context,
        reason="replace staged credential",
        expected_revision=revision,
        idempotency_key="b14-rotate-001",
    )
    assert rotated["summary"]["credentialHealth"] == "healthy"
    assert "provider" not in json.dumps(rotated)
    assert "version" not in json.dumps(rotated)
    assert gateway.rotate_calls == 1

    replay = service.rotate_admin_upstream_credential(
        context,
        reason="replace staged credential",
        expected_revision=revision,
        idempotency_key="b14-rotate-001",
    )
    assert replay == rotated
    assert gateway.rotate_calls == 1

    revoke_revision = rotated["revision"]
    revoked = service.revoke_admin_upstream_credential(
        context,
        reason="close compromised upstream credential",
        expected_revision=revoke_revision,
        idempotency_key="b14-revoke-001",
    )
    assert revoked["summary"]["credentialHealth"] == "revoked"
    assert revoked["summary"]["availableAccountCount"] == 0
    assert revoked["summary"]["unhealthyAccountCount"] == 1
    assert gateway.revoke_calls == 1

    revoke_replay = service.revoke_admin_upstream_credential(
        context,
        reason="close compromised upstream credential",
        expected_revision=revoke_revision,
        idempotency_key="b14-revoke-001",
    )
    assert revoke_replay == revoked
    assert gateway.revoke_calls == 1


def test_stale_revision_does_not_call_mutation() -> None:
    service, gateway, _storage = make_service()
    context = admin_context()
    revision = service.get_admin_upstreams(context)["revision"]
    gateway.health["lastSyncedAt"] = "2026-08-05T04:01:00Z"

    with pytest.raises(AdminUpstreamsRevisionConflict):
        service.rotate_admin_upstream_credential(
            context,
            reason="stale revision",
            expected_revision=revision,
            idempotency_key="b14-rotate-002",
        )

    assert gateway.rotate_calls == 0


def test_source_failure_is_explicit_instead_of_zero_projection() -> None:
    service, gateway, _storage = make_service()

    gateway.health_unavailable = True

    with pytest.raises(AdminUpstreamsUnavailable):
        service.get_admin_upstreams(admin_context())

