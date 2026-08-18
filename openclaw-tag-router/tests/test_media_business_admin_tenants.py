from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from openclaw_app.services.media_business.admin_tenants import (
    AdminTenantContext,
    AdminTenantsForbidden,
    AdminTenantsInvalidRequest,
    AdminTenantsNotFound,
    AdminTenantsService,
    AdminTenantsUnauthorized,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
TENANT_A = UUID("12000000-0000-4000-8000-000000000001")
TENANT_B = UUID("12000000-0000-4000-8000-000000000002")
MISSING_TENANT = UUID("12000000-0000-4000-8000-000000000099")
USER_A = UUID("22000000-0000-4000-8000-000000000001")
USER_B = UUID("22000000-0000-4000-8000-000000000002")
ACTOR = UUID("32000000-0000-4000-8000-000000000001")
SESSION = UUID("42000000-0000-4000-8000-000000000001")
RUN_A = "run_b12_0001"
RUN_B = "run_b12_0002"


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)


def _tenant_row(
    tenant_id: UUID,
    user_id: UUID,
    *,
    updated_at: datetime = NOW,
    status: str = "active",
) -> tuple[Any, ...]:
    return (
        tenant_id,
        user_id,
        status,
        "private-user-name",
        1,
        4,
        3,
        2,
        Decimal("12.34000000"),
        updated_at,
    )


def _run_row(
    public_id: str,
    *,
    updated_at: datetime = NOW,
    title: str = "B12 fixture run",
) -> tuple[Any, ...]:
    return (
        public_id,
        {
            "title": title,
            "entrypoint": "source_asset_intake",
            "status": "succeeded",
            "availableSections": ["sources", "outputs", "ignored"],
            "publicProjectId": "project_b12_0001",
        },
        NOW - timedelta(minutes=5),
        updated_at,
        3,
    )


class _Connection:
    def __init__(
        self,
        *,
        directory_rows: list[tuple[Any, ...]] | None = None,
        detail_rows: dict[UUID, tuple[Any, ...]] | None = None,
        run_rows: list[tuple[Any, ...]] | None = None,
        tenant_users: dict[UUID, UUID] | None = None,
    ) -> None:
        self.directory_rows = directory_rows or []
        self.detail_rows = detail_rows or {}
        self.run_rows = run_rows or []
        self.tenant_users = tenant_users or {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        self.calls.append((sql, params))
        if "INSERT INTO openclaw_account.admin_audit" in sql:
            return _Result([])
        if "FROM tenant_rows" in sql and "WHERE tenant_id = %s" in sql:
            tenant_id = params[0]
            row = self.detail_rows.get(tenant_id)
            return _Result([row] if row is not None else [])
        if "FROM tenant_rows" in sql:
            return _Result(self.directory_rows)
        if "FROM openclaw_account.tenants AS tenant" in sql and "primary_user_id" in sql:
            tenant_id = params[0]
            user_id = self.tenant_users.get(tenant_id)
            return _Result([(user_id,)] if user_id is not None else [])
        if "FROM media_product.creation_runs AS run" in sql:
            return _Result(self.run_rows)
        raise AssertionError(f"unexpected SQL: {sql}")


class _Database:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def connect(self) -> _Connection:
        return self.connection


def _context() -> AdminTenantContext:
    return AdminTenantContext(actor_user_id=ACTOR, actor_session_id=SESSION)


def _service(connection: _Connection) -> AdminTenantsService:
    return AdminTenantsService(
        _Database(connection),
        public_id_secret=b"public-secret-for-b12-tests",
        cursor_secret=b"cursor-secret-for-b12-tests",
    )


def test_directory_returns_redacted_metrics_and_signed_public_ids() -> None:
    connection = _Connection(
        directory_rows=[
            _tenant_row(TENANT_A, USER_A),
            _tenant_row(TENANT_B, USER_B, status="suspended", updated_at=NOW - timedelta(hours=1)),
        ],
    )
    service = _service(connection)

    response = service.list_admin_tenants(_context(), search="active", page_size=2)

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["revision"] >= 0
    assert response["nextCursor"] is None
    assert response["items"][0] == {
        "publicTenantId": service.public_tenant_id(TENANT_A),
        "status": "active",
        "userCount": 1,
        "runCount": 4,
        "assetCount": 3,
        "archiveCount": 2,
        "usageCharge": "12.34",
        "lastActiveAt": "2026-08-05T12:00:00Z",
    }
    serialized = json.dumps(response, ensure_ascii=False)
    assert str(TENANT_A) not in serialized
    assert "private-user-name" not in serialized

    directory_query = next(params for sql, params in connection.calls if "FROM tenant_rows" in sql)
    assert directory_query[:3] == ("active", "%active%", "%active%")


def test_directory_cursor_is_opaque_and_bound_to_search() -> None:
    connection = _Connection(
        directory_rows=[
            _tenant_row(TENANT_A, USER_A),
            _tenant_row(TENANT_B, USER_B, updated_at=NOW - timedelta(hours=1)),
        ],
    )
    service = _service(connection)

    first_page = service.list_admin_tenants(_context(), page_size=1)
    cursor = first_page["nextCursor"]
    assert isinstance(cursor, str)
    assert str(TENANT_A) not in cursor
    assert service._decode_tenant_cursor(cursor, "").tenant_id == TENANT_A

    with pytest.raises(AdminTenantsInvalidRequest):
        service.list_admin_tenants(_context(), cursor=cursor, search="different", page_size=1)


def test_detail_and_runs_require_reason_and_write_immutable_read_audits() -> None:
    connection = _Connection(
        detail_rows={TENANT_A: _tenant_row(TENANT_A, USER_A)},
        tenant_users={TENANT_A: USER_A},
        run_rows=[_run_row(RUN_A), _run_row(RUN_B, updated_at=NOW - timedelta(minutes=1))],
    )
    service = _service(connection)
    public_tenant_id = service.public_tenant_id(TENANT_A)

    with pytest.raises(AdminTenantsInvalidRequest):
        service.get_admin_tenant(_context(), public_tenant_id, audit_reason="short")

    detail = service.get_admin_tenant(_context(), public_tenant_id, audit_reason="审计租户资源读取")
    runs = service.list_admin_tenant_runs(
        _context(),
        public_tenant_id,
        audit_reason="审计租户运行读取",
        page_size=1,
    )

    assert detail["tenant"]["publicTenantId"] == public_tenant_id
    assert runs["items"][0]["publicRunId"] == RUN_A
    assert runs["items"][0]["availableSections"] == ["sources", "outputs"]
    run_cursor = runs["nextCursor"]
    assert isinstance(run_cursor, str)
    assert service._decode_run_cursor(run_cursor, TENANT_A).public_run_id == RUN_A
    with pytest.raises(AdminTenantsInvalidRequest):
        service._decode_run_cursor(run_cursor, TENANT_B)
    audit_calls = [
        (sql, params)
        for sql, params in connection.calls
        if "INSERT INTO openclaw_account.admin_audit" in sql
    ]
    assert len(audit_calls) == 2
    assert [params[3] for _, params in audit_calls] == [
        "admin_tenant_detail_read",
        "admin_tenant_runs_read",
    ]
    assert [params[4] for _, params in audit_calls] == [USER_A, USER_A]
    assert [params[5] for _, params in audit_calls] == ["审计租户资源读取", "审计租户运行读取"]
    assert all(json.loads(params[6])["targetType"] == "tenant" for _, params in audit_calls)
    assert all(not sql.lstrip().upper().startswith(("UPDATE", "DELETE")) for sql, _ in connection.calls)


def test_unknown_and_malformed_targets_have_uniform_not_found_without_audit() -> None:
    connection = _Connection(detail_rows={}, tenant_users={})
    service = _service(connection)

    with pytest.raises(AdminTenantsNotFound) as missing:
        service.get_admin_tenant(
            _context(),
            service.public_tenant_id(MISSING_TENANT),
            audit_reason="审计不存在租户目标",
        )
    with pytest.raises(AdminTenantsNotFound) as malformed:
        service.get_admin_tenant(_context(), "invalid-public-id", audit_reason="审计无效目标读取")
    with pytest.raises(AdminTenantsNotFound):
        service.list_admin_tenant_runs(
            _context(),
            service.public_tenant_id(MISSING_TENANT),
            audit_reason="审计不存在运行目标",
        )

    assert missing.value.status == malformed.value.status == 404
    assert not any("INSERT INTO openclaw_account.admin_audit" in sql for sql, _ in connection.calls)


def test_permissions_are_rejected_before_business_reads() -> None:
    connection = _Connection()
    service = _service(connection)

    with pytest.raises(AdminTenantsUnauthorized):
        service.list_admin_tenants(None)
    with pytest.raises(AdminTenantsForbidden):
        service.list_admin_tenants(
            AdminTenantContext(
                actor_user_id=ACTOR,
                actor_session_id=SESSION,
                role="user",
            ),
        )
    assert not connection.calls


def test_invalid_cursor_and_page_size_are_explicit_errors() -> None:
    service = _service(_Connection())

    with pytest.raises(AdminTenantsInvalidRequest):
        service.list_admin_tenants(_context(), cursor="not-a-signed-cursor")
    with pytest.raises(AdminTenantsInvalidRequest):
        service.list_admin_tenants(_context(), page_size=0)
