from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest

from openclaw_app.services.media_business.admin_overview import (
    AdminOverviewError,
    AdminOverviewService,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
AUDIT_ID = UUID("91000000-0000-4000-8000-000000000001")
BOUNDARY_AUDIT_ID = UUID("91000000-0000-4000-8000-000000000002")
HEALTH_TABLES = {
    "openclaw_account.users",
    "media_product.creation_runs",
    "openclaw_account.model_operations",
    "openclaw_account.admin_audit",
}


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)


class _Connection:
    def __init__(self, health_tables: set[str] | None = None) -> None:
        self.health_tables = health_tables or HEALTH_TABLES
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        self.calls.append((sql, params))
        if "GREATEST(" in sql:
            return _Result([(12, 48, 3, 2, 4, "controlled", 1_800_000_000)])
        if "FILTER" in sql:
            return _Result([(5, 1)])
        if "FROM openclaw_account.admin_audit" in sql and "LIMIT" in sql:
            return _Result(
                [
                    (
                        AUDIT_ID,
                        "billing.admin_grant",
                        True,
                        {"status": "failed", "targetType": "billing", "username": "private"},
                        NOW,
                    ),
                    (
                        BOUNDARY_AUDIT_ID,
                        "registration_policy_update",
                        False,
                        {"mode": "controlled"},
                        NOW - timedelta(hours=24),
                    ),
                ]
            )
        if "to_regclass" in sql:
            table = str(params[0])
            return _Result([(table if table in self.health_tables else None,)])
        raise AssertionError(f"unexpected SQL: {sql}")


class _Database:
    def __init__(self, connection: _Connection | None = None) -> None:
        self.connection = connection or _Connection()

    def connect(self) -> _Connection:
        return self.connection


class _UnavailableDatabase:
    def connect(self) -> Any:
        raise RuntimeError("database unavailable")


def test_dashboard_projects_only_redacted_admin_aggregates() -> None:
    database = _Database()
    service = AdminOverviewService(database, clock=lambda: NOW)

    response = service.dashboard()
    summary = response["summary"]

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["revision"] == 1_800_000_000
    assert summary["counts"] == {
        "tenants": 12,
        "users": 48,
        "pendingAdmission": 3,
        "abnormalRuns": 2,
    }
    assert summary["governanceTodos"] == [
        "\u9080\u8bf7\u5230\u671f\uff1a4",
        "\u51c6\u5165\u5e93\u5b58\uff1a3",
        "\u6ce8\u518c\u7b56\u7565\u590d\u6838\uff1acontrolled",
        "\u79df\u6237\u8fd0\u884c\u5f02\u5e38\uff1a2",
    ]
    assert summary["auditSummary24h"] == {
        "actionCount": 5,
        "failedCount": 1,
        "from": "2026-08-04T12:00:00+00:00",
        "to": "2026-08-05T12:00:00+00:00",
    }
    assert summary["recentActions"][0] == {
        "publicActionId": service.public_action_id(AUDIT_ID),
        "action": "billing.admin_grant",
        "targetType": "billing",
        "reasonSummary": "\u7ba1\u7406\u5458\u64cd\u4f5c\u539f\u56e0\u5df2\u7559\u75d5\u3002",
        "status": "failed",
        "createdAt": "2026-08-05T12:00:00+00:00",
    }
    assert summary["recentActions"][1]["createdAt"] == "2026-08-04T12:00:00+00:00"
    assert all(item["status"] == "healthy" for item in summary["serviceHealth"])

    serialized = json.dumps(response, ensure_ascii=False)
    assert "private" not in serialized
    assert str(AUDIT_ID) not in serialized
    assert "tenantId" not in serialized
    assert "username" not in serialized
    assert "credential" not in serialized


def test_dashboard_uses_inclusive_24_hour_cutoff() -> None:
    database = _Database()
    service = AdminOverviewService(database, clock=lambda: NOW)

    service.dashboard()

    cutoff = NOW - timedelta(hours=24)
    audit_queries = [
        params
        for sql, params in database.connection.calls
        if "FROM openclaw_account.admin_audit" in sql and "created_at >= %s" in sql
    ]
    assert audit_queries
    assert all(params[0] == cutoff for params in audit_queries)


def test_service_failure_is_explicit_and_never_becomes_zero() -> None:
    service = AdminOverviewService(_UnavailableDatabase(), clock=lambda: NOW)

    with pytest.raises(AdminOverviewError) as caught:
        service.dashboard()

    assert caught.value.code == "admin_overview_unavailable"
    assert caught.value.status == 503


def test_individual_service_failure_is_reported_as_unavailable() -> None:
    database = _Database()

    def fail_probe() -> str:
        raise RuntimeError("task probe unavailable")

    probes = {"\u4efb\u52a1\u670d\u52a1": fail_probe}
    service = AdminOverviewService(database, clock=lambda: NOW, health_probes=probes)

    health = service.dashboard()["summary"]["serviceHealth"]

    assert {item["service"]: item["status"] for item in health} == {
        "\u8eab\u4efd\u670d\u52a1": "healthy",
        "\u4efb\u52a1\u670d\u52a1": "unavailable",
        "\u8ba1\u8d39\u670d\u52a1": "healthy",
        "\u5ba1\u8ba1\u670d\u52a1": "healthy",
    }


def test_invalid_boolean_aggregate_is_not_coerced_to_count() -> None:
    class InvalidConnection(_Connection):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
            if "GREATEST(" in sql:
                return _Result([(True, 48, 3, 2, 4, "controlled", 1_800_000_000)])
            return super().execute(sql, params)

    service = AdminOverviewService(
        _Database(InvalidConnection()),
        clock=lambda: NOW,
    )

    with pytest.raises(AdminOverviewError) as caught:
        service.dashboard()

    assert caught.value.code == "admin_overview_unavailable"


def test_uncontrolled_registration_mode_is_redacted_to_unknown() -> None:
    class UncontrolledConnection(_Connection):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
            if "GREATEST(" in sql:
                return _Result([(12, 48, 3, 2, 4, "<script>", 1_800_000_000)])
            return super().execute(sql, params)

    service = AdminOverviewService(
        _Database(UncontrolledConnection()),
        clock=lambda: NOW,
    )

    todos = service.dashboard()["summary"]["governanceTodos"]

    assert todos[2] == "\u6ce8\u518c\u7b56\u7565\u590d\u6838\uff1aunknown"


def test_unknown_audit_status_remains_unknown() -> None:
    class UnknownStatusConnection(_Connection):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
            if "FROM openclaw_account.admin_audit" in sql and "LIMIT" in sql:
                return _Result(
                    [
                        (
                            AUDIT_ID,
                            "platform.policy_update",
                            False,
                            {"status": "mystery", "ok": False, "targetType": "platform"},
                            NOW,
                        )
                    ]
                )
            return super().execute(sql, params)

    service = AdminOverviewService(
        _Database(UnknownStatusConnection()),
        clock=lambda: NOW,
    )

    actions = service.dashboard()["summary"]["recentActions"]

    assert actions[0]["status"] == "unknown"


def test_unknown_audit_target_type_does_not_infer_from_action() -> None:
    class UnknownTargetConnection(_Connection):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
            if "FROM openclaw_account.admin_audit" in sql and "LIMIT" in sql:
                return _Result(
                    [
                        (
                            AUDIT_ID,
                            "billing.admin_grant",
                            False,
                            {"status": "succeeded"},
                            NOW,
                        )
                    ]
                )
            return super().execute(sql, params)

    service = AdminOverviewService(
        _Database(UnknownTargetConnection()),
        clock=lambda: NOW,
    )

    actions = service.dashboard()["summary"]["recentActions"]

    assert actions[0]["targetType"] == "unknown"


def test_uncontrolled_audit_action_name_fails_closed() -> None:

    class UnsafeActionConnection(_Connection):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
            if "FROM openclaw_account.admin_audit" in sql and "LIMIT" in sql:
                return _Result(
                    [
                        (
                            AUDIT_ID,
                            "<script>",
                            False,
                            {"status": "succeeded", "targetType": "platform"},
                            NOW,
                        )
                    ]
                )
            return super().execute(sql, params)

    service = AdminOverviewService(
        _Database(UnsafeActionConnection()),
        clock=lambda: NOW,
    )

    with pytest.raises(AdminOverviewError) as caught:
        service.dashboard()

    assert caught.value.code == "admin_overview_unavailable"


def test_non_boolean_audit_target_flag_fails_closed() -> None:
    class InvalidTargetFlagConnection(_Connection):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
            if "FROM openclaw_account.admin_audit" in sql and "LIMIT" in sql:
                return _Result(
                    [
                        (
                            AUDIT_ID,
                            "platform.policy_update",
                            1,
                            {"status": "succeeded", "targetType": "platform"},
                            NOW,
                        )
                    ]
                )
            return super().execute(sql, params)

    service = AdminOverviewService(
        _Database(InvalidTargetFlagConnection()),
        clock=lambda: NOW,
    )

    with pytest.raises(AdminOverviewError) as caught:
        service.dashboard()

    assert caught.value.code == "admin_overview_unavailable"

def test_service_health_preserves_degraded_and_unknown_states() -> None:
    probes = {
        "\u8eab\u4efd\u670d\u52a1": lambda: "degraded",
        "\u4efb\u52a1\u670d\u52a1": lambda: "unknown",
        "\u8ba1\u8d39\u670d\u52a1": lambda: "healthy",
        "\u5ba1\u8ba1\u670d\u52a1": lambda: "unavailable",
    }
    service = AdminOverviewService(
        _Database(),
        clock=lambda: NOW,
        health_probes=probes,
    )

    health = service.dashboard()["summary"]["serviceHealth"]

    assert {item["service"]: item["status"] for item in health} == {
        "\u8eab\u4efd\u670d\u52a1": "degraded",
        "\u4efb\u52a1\u670d\u52a1": "unknown",
        "\u8ba1\u8d39\u670d\u52a1": "healthy",
        "\u5ba1\u8ba1\u670d\u52a1": "unavailable",
    }
