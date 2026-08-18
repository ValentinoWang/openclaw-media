from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from openclaw_app.services.media_business.foundation import TenantContext
from openclaw_app.services.media_business.overview import (
    OverviewConflict,
    OverviewError,
    OverviewForbidden,
    OverviewIdempotencyConflict,
    OverviewInternalError,
    OverviewInvalidRequest,
    OverviewNotFound,
    OverviewService,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 5, 3, 0, tzinfo=UTC)
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
CONTEXT_A = TenantContext(TENANT_A, "user-a")
CONTEXT_B = TenantContext(TENANT_B, "user-b")


class Cursor:
    def __init__(self, rows: Any = ()) -> None:
        self.rows = list(rows)

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return list(self.rows)


class ScriptedConnection:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> "ScriptedConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Cursor:
        self.calls.append((query, params))
        return self.handler(query, params)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def factory(connection: ScriptedConnection):
    def make() -> ScriptedConnection:
        return connection

    return make


def project_row(
    public_id: str = "project_abc",
    revision: int = 3,
    title: str = "A project",
    canonical_data: dict[str, Any] | None = None,
    updated_at: datetime = NOW,
    artifact_counts: dict[str, int] | None = None,
) -> tuple[Any, ...]:
    return (
        public_id,
        title,
        "creation",
        revision,
        canonical_data
        or {"workspace_mode": "personal_web", "status": "active"},
        updated_at,
        artifact_counts or {"creation_document": 1},
    )


def artifact_row(
    public_id: str = "artifact_abc",
    project_id: str = "project_abc",
    kind: str = "creation_document",
    authority: str = "lark",
    current_revision: int = 2,
    revision_state: str = "ready",
    remote_version: str | None = "v2",
    display_name: str | None = "图文 - Kimi K3发布与WAIC现场观察 - 未定发布时间",
    document_url: str | None = None,
    document_url_expires_at: datetime | None = None,
    updated_at: datetime = NOW,
) -> tuple[Any, ...]:
    return (
        public_id,
        project_id,
        kind,
        authority,
        current_revision,
        revision_state,
        remote_version,
        display_name,
        document_url,
        document_url_expires_at,
        updated_at,
    )


def task_reader(_tenant_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": "media_web_business_pages_v2",
        "revision": 4,
        "items": [
            {"status": "queued"},
            {"status": "generating"},
            {"status": "pending_manual"},
            {"status": "failed"},
        ],
        "nextCursor": None,
    }


def service(connection: ScriptedConnection, *, reader: Any = task_reader) -> OverviewService:
    return OverviewService(
        factory(connection),
        task_reader=reader,
        cursor_secret=b"b01-cursor-secret-0123456789",
        clock=lambda: NOW,
    )


def test_dashboard_has_exact_dto_fields_and_never_uses_legacy_zero_fallback() -> None:
    def handle(query: str, _params: tuple[Any, ...]) -> Cursor:
        if "GROUP BY project.stage" in query:
            return Cursor(
                [
                    ("research", 2),
                    ("creation", 1),
                ]
            )
        if "FROM media_product.content_projects" in query:
            return Cursor([(4, 5, 6, 7, 8, 9, 10, 1, 2, 3, 11)])
        raise AssertionError(query)

    response = service(ScriptedConnection(handle)).get_dashboard(CONTEXT_A)

    assert set(response) == {"schemaVersion", "revision", "summary"}
    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["revision"] == 11
    assert set(response["summary"]) == {
        "counts",
        "contentProjectStages",
        "pendingDecisions",
        "pendingPublishing",
        "pendingReviews",
        "taskSummary",
        "coverage",
        "generatedAt",
        "revision",
    }
    assert response["summary"]["counts"] == {
        "contentProjects": 4,
        "runs": 5,
        "assets": 6,
        "tracks": 7,
        "creators": 8,
        "publishedPosts": 9,
        "reviews": 10,
    }
    assert response["summary"]["taskSummary"] == {
        "queued": 1,
        "running": 1,
        "needsAttention": 1,
        "failed": 1,
    }
    assert response["summary"]["coverage"] == {
        "known": 49,
        "unknown": 0,
        "unavailable": 0,
    }
    assert response["summary"]["revision"] == 11


def test_dashboard_database_failure_is_internal_not_zero() -> None:
    connection = ScriptedConnection(
        lambda _query, _params: (_ for _ in ()).throw(RuntimeError("db down"))
    )

    with pytest.raises(OverviewInternalError):
        service(connection).get_dashboard(CONTEXT_A)

def test_dashboard_task_reader_failure_is_internal_not_zero() -> None:
    connection = ScriptedConnection(
        lambda _query, _params: Cursor([(0, 0, 0, 0, 0, 0, 0, 0)])
    )

    def broken_reader(_tenant_id: str) -> dict[str, Any]:
        raise RuntimeError("task store unavailable")

    with pytest.raises(OverviewInternalError):
        service(connection, reader=broken_reader).get_dashboard(CONTEXT_A)

def test_dashboard_accepts_if2_task_items() -> None:
    def handle(query: str, _params: tuple[Any, ...]) -> Cursor:
        if "GROUP BY project.stage" in query:
            return Cursor()
        return Cursor([(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)])

    connection = ScriptedConnection(handle)

    def reader(_tenant_id: str) -> dict[str, Any]:
        return {
            "schemaVersion": "media_web_business_pages_v2",
            "revision": 4,
            "items": [
                {"status": "queued"},
                {"status": "running"},
                {"status": "awaiting_confirmation"},
                {"status": "failed"},
            ],
            "nextCursor": None,
        }

    response = service(connection, reader=reader).get_dashboard(CONTEXT_A)

    assert response["summary"]["taskSummary"] == {
        "queued": 1,
        "running": 1,
        "needsAttention": 1,
        "failed": 1,
    }


def test_dashboard_etag_is_stable_for_generated_time_and_changes_with_data() -> None:
    response = {
        "schemaVersion": "media_web_business_pages_v2",
        "revision": 4,
        "summary": {
            "counts": {"contentProjects": 1},
            "generatedAt": "2026-08-05T03:00:00+00:00",
        },
    }
    later = json.loads(json.dumps(response))
    later["summary"]["generatedAt"] = "2026-08-05T03:05:00+00:00"
    changed = json.loads(json.dumps(response))
    changed["summary"]["counts"]["contentProjects"] = 2

    etag = OverviewService.response_etag(response)
    assert etag.startswith('"') and etag.endswith('"')
    assert OverviewService.response_etag(later) == etag
    assert OverviewService.response_etag(changed) != etag


def test_empty_project_list_is_success_and_database_failure_is_not_empty() -> None:
    empty = ScriptedConnection(lambda _query, _params: Cursor())
    response = service(empty).list_content_projects(CONTEXT_A)
    assert response["items"] == []
    assert response["nextCursor"] is None
    assert response["revision"] == 0

    failing = ScriptedConnection(
        lambda _query, _params: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    with pytest.raises(OverviewInternalError):
        service(failing).list_content_projects(CONTEXT_A)


def test_projects_are_tenant_scoped_and_projection_has_no_private_fields() -> None:
    connection = ScriptedConnection(
        lambda query, _params: Cursor(
            [
                project_row(
                    canonical_data={
                        "workspace_mode": "organization_lark",
                        "status": "active",
                        "tenant_id": TENANT_B,
                        "local_path": "/private/project",
                    }
                )
            ]
        )
        if "FROM media_product.content_projects" in query
        else Cursor()
    )

    response = service(connection).list_content_projects(CONTEXT_A)
    item = response["items"][0]
    assert item == {
        "publicProjectId": "project_abc",
        "title": "A project",
        "workspaceMode": "organization_lark",
        "stage": "creation",
        "status": "active",
        "artifactCounts": {"creation_document": 1},
        "updatedAt": NOW.isoformat(),
    }
    encoded = json.dumps(response, ensure_ascii=True)
    assert TENANT_B not in encoded
    assert "local_path" not in encoded
    assert any("tenant_id = %s" in query for query, _ in connection.calls)


def test_project_pagination_is_opaque_tenant_bound_and_capped_at_100() -> None:
    rows = [project_row("project_abc"), project_row("project_def")]
    connection = ScriptedConnection(
        lambda query, _params: Cursor(rows)
        if "FROM media_product.content_projects" in query
        else Cursor()
    )
    first = service(connection).list_content_projects(CONTEXT_A, page_size=1)
    assert first["nextCursor"]
    assert "tenant-a" not in first["nextCursor"]

    with pytest.raises(OverviewInvalidRequest):
        service(connection).list_content_projects(
            CONTEXT_B, cursor=first["nextCursor"], page_size=1
        )
    with pytest.raises(OverviewInvalidRequest):
        service(connection).list_content_projects(CONTEXT_A, page_size=101)

    tampered = first["nextCursor"][:-1] + ("A" if first["nextCursor"][-1] != "A" else "B")
    with pytest.raises(OverviewInvalidRequest):
        service(connection).list_content_projects(CONTEXT_A, cursor=tampered, page_size=1)


def test_cross_tenant_project_is_masked_as_not_found_and_context_is_required() -> None:
    connection = ScriptedConnection(lambda _query, _params: Cursor())
    with pytest.raises(OverviewNotFound):
        service(connection).list_project_artifacts(CONTEXT_A, "project_abc")
    with pytest.raises(OverviewForbidden):
        service(connection).get_dashboard(None)  # type: ignore[arg-type]


def test_artifact_mapping_uses_project_join_and_sync_projection() -> None:
    def handle(query: str, _params: tuple[Any, ...]) -> Cursor:
        if "SELECT project.revision" in query:
            return Cursor([(4, NOW)])
        if "media_product.document_artifacts AS artifact" in query:
            return Cursor([artifact_row()])
        raise AssertionError(query)

    response = service(ScriptedConnection(handle)).list_project_artifacts(
        CONTEXT_A, "project_abc"
    )
    assert response["revision"] == 4
    assert response["items"] == [
        {
            "publicArtifactId": "artifact_abc",
            "publicProjectId": "project_abc",
            "artifactType": "creation_document",
            "displayName": "图文 - Kimi K3发布与WAIC现场观察 - 未定发布时间",
            "bodyAuthority": "lark",
            "currentRevision": 2,
                "syncStatus": "synced",
                "updatedAt": NOW.isoformat(),
                "organizationDocumentUrl": None,
                "organizationDocumentUrlExpiresAt": None,
                "allowedActions": ["view", "regenerate"],
        }
    ]


def test_artifact_display_name_rejects_non_text_values() -> None:
    malformed = list(artifact_row())
    malformed[7] = 42

    with pytest.raises(OverviewInternalError, match="artifact display name is invalid"):
        service(ScriptedConnection(lambda _query, _params: Cursor()))._artifact_projection(malformed)


def test_artifact_pagination_uses_updated_at_not_organization_document_url() -> None:
    first_updated_at = NOW.replace(hour=2)
    second_updated_at = NOW.replace(hour=1)

    def handle(query: str, _params: tuple[Any, ...]) -> Cursor:
        if "SELECT project.revision" in query:
            return Cursor([(4, NOW)])
        if "media_product.document_artifacts AS artifact" in query:
            return Cursor(
                [
                    artifact_row(
                        public_id="artifact_first",
                        document_url="https://team.feishu.cn/docx/doc_000001",
                        updated_at=first_updated_at,
                    ),
                    artifact_row(
                        public_id="artifact_second",
                        document_url="https://team.feishu.cn/docx/doc_000002",
                        updated_at=second_updated_at,
                    ),
                ]
            )
        raise AssertionError(query)

    response = service(ScriptedConnection(handle)).list_project_artifacts(
        CONTEXT_A, "project_abc", page_size=1
    )

    assert response["items"][0]["organizationDocumentUrl"] == "https://team.feishu.cn/docx/doc_000001"
    assert response["nextCursor"]


def test_create_summary_requires_expected_revision_and_reason() -> None:
    connection = ScriptedConnection(
        lambda query, _params: Cursor(
            [
                (
                    "project_abc",
                    3,
                    "A project",
                    "creation",
                    {"workspace_mode": "personal_web", "status": "active"},
                    NOW,
                )
            ]
        )
        if "FROM media_product.content_projects AS project" in query
        else Cursor()
    )
    target = service(connection)
    with pytest.raises(OverviewInvalidRequest):
        target.create_project_summary(
            CONTEXT_A,
            "project_abc",
            {"expectedRevision": 3, "reason": " "},
            idempotency_key="summary-1",
        )
    with pytest.raises(OverviewConflict):
        target.create_project_summary(
            CONTEXT_A,
            "project_abc",
            {"expectedRevision": 2, "reason": "refresh"},
            idempotency_key="summary-1",
        )


def test_create_summary_replays_same_idempotency_key_and_rejects_different_payload() -> None:
    stored: dict[str, Any] = {}

    def handle(query: str, params: tuple[Any, ...]) -> Cursor:
        if "FROM media_product.project_summary_idempotency" in query:
            if not stored:
                return Cursor()
            return Cursor(
                [(stored["fingerprint"], json.dumps(stored["response"]), 200)]
            )
        if "SELECT project.revision, project.updated_at" in query:
            return Cursor([(4, NOW)])
        if "artifact.workspace_mode,\n               artifact.updated_at" in query:
            return Cursor([("project_summary_generated", 1, "internal", "personal_web", NOW)])
        if "FROM media_product.content_projects AS project" in query:
            return Cursor(
                [
                    (
                        "project_abc",
                        3,
                        "A project",
                        "creation",
                        {"workspace_mode": "personal_web", "status": "active"},
                        NOW,
                    )
                ]
            )
        if "media_product.document_artifacts AS artifact" in query:
            return Cursor()
        if "INSERT INTO media_product.project_summary_idempotency" in query:
            stored["fingerprint"] = params[3]
            stored["response"] = json.loads(params[5])
            return Cursor()
        if "UPDATE media_product.content_projects" in query:
            return Cursor()
        if "INSERT INTO media_product.document_artifacts" in query:
            return Cursor()
        if "INSERT INTO media_product.document_revisions" in query:
            return Cursor()
        raise AssertionError(query)

    connection = ScriptedConnection(handle)
    target = OverviewService(
        factory(connection),
        task_reader=task_reader,
        cursor_secret=b"b01-cursor-secret-0123456789",
        id_factory=lambda prefix: prefix + "_generated",
        clock=lambda: NOW,
    )
    request = {"expectedRevision": 3, "reason": "refresh"}
    first = target.create_project_summary(
        CONTEXT_A, "project_abc", request, idempotency_key="summary-1"
    )
    second = target.create_project_summary(
        CONTEXT_A, "project_abc", request, idempotency_key="summary-1"
    )
    assert first == second
    with pytest.raises(OverviewIdempotencyConflict):
        target.create_project_summary(
            CONTEXT_A,
            "project_abc",
            {"expectedRevision": 3, "reason": "different"},
            idempotency_key="summary-1",
        )
    assert connection.commits == 1


def test_create_summary_rejects_existing_non_internal_authority() -> None:
    def handle(query: str, _params: tuple[Any, ...]) -> Cursor:
        if "FROM media_product.project_summary_idempotency" in query:
            return Cursor()
        if "FROM media_product.content_projects AS project" in query:
            return Cursor(
                [
                    (
                        "project_abc",
                        3,
                        "A project",
                        "creation",
                        {"workspace_mode": "personal_web", "status": "active"},
                        NOW,
                    )
                ]
            )
        if "media_product.document_artifacts AS artifact" in query:
            return Cursor([("artifact_abc", 1, "lark", "personal_web")])
        if "UPDATE media_product.document_artifacts" in query:
            return Cursor()
        if "INSERT INTO media_product.document_revisions" in query:
            return Cursor()
        if "UPDATE media_product.content_projects" in query:
            return Cursor()
        if "INSERT INTO media_product.project_summary_idempotency" in query:
            return Cursor()
        raise AssertionError(query)

    with pytest.raises(OverviewInternalError):
        service(ScriptedConnection(handle)).create_project_summary(
            CONTEXT_A,
            "project_abc",
            {"expectedRevision": 3, "reason": "refresh"},
            idempotency_key="summary-1",
        )


def test_create_summary_response_uses_write_readback() -> None:
    readback_time = datetime(2026, 8, 5, 3, 7, tzinfo=UTC)

    def handle(query: str, params: tuple[Any, ...]) -> Cursor:
        if "FROM media_product.project_summary_idempotency" in query:
            return Cursor()
        if "SELECT project.revision, project.updated_at" in query:
            return Cursor([(4, readback_time)])
        if "artifact.workspace_mode,\n               artifact.updated_at" in query:
            return Cursor(
                [("project_summary_generated", 1, "internal", "personal_web", readback_time)]
            )
        if "FROM media_product.content_projects AS project" in query:
            return Cursor(
                [
                    (
                        "project_abc",
                        3,
                        "A project",
                        "creation",
                        {"workspace_mode": "personal_web", "status": "active"},
                        NOW,
                    )
                ]
            )
        if "media_product.document_artifacts AS artifact" in query:
            return Cursor()
        if "INSERT INTO media_product.document_artifacts" in query:
            return Cursor()
        if "INSERT INTO media_product.document_revisions" in query:
            return Cursor()
        if "UPDATE media_product.content_projects" in query:
            return Cursor()
        if "INSERT INTO media_product.project_summary_idempotency" in query:
            return Cursor()
        raise AssertionError(query)

    response = OverviewService(
        factory(ScriptedConnection(handle)),
        task_reader=task_reader,
        cursor_secret=b"b01-cursor-secret-0123456789",
        id_factory=lambda prefix: prefix + "_generated",
        clock=lambda: NOW,
    ).create_project_summary(
        CONTEXT_A,
        "project_abc",
        {"expectedRevision": 3, "reason": "refresh"},
        idempotency_key="summary-1",
    )

    assert response["revision"] == 4
    assert response["item"]["publicArtifactId"] == "project_summary_generated"
    assert response["item"]["currentRevision"] == 1
    assert response["item"]["bodyAuthority"] == "internal"
    assert response["item"]["updatedAt"] == readback_time.isoformat()

def test_error_response_is_stable_and_does_not_expose_exception_details() -> None:
    error = OverviewInternalError()
    assert OverviewService.error_status(error) == 500
    assert OverviewService.error_response(error) == {
        "error": {
            "code": "internal_error",
            "message": "overview data is unavailable",
            "field": None,
        }
    }
    assert OverviewService.error_status(RuntimeError("secret path")) == 500
    assert OverviewService.error_response(RuntimeError("secret path")) == {
        "error": {
            "code": "internal_error",
            "message": "overview data is unavailable",
            "field": None,
        }
    }


def test_overview_queries_match_the_migrated_document_runtime() -> None:
    artifacts_query = OverviewService._ARTIFACTS_PREFIX
    dashboard_query = OverviewService._DASHBOARD_QUERY

    assert "binding.remote_version" not in artifacts_query
    assert "binding_batch.remote_document_version" in artifacts_query
    assert "binding_batch.error_detail #>> '{larkResource,title}'" in artifacts_query
    assert "media_document.revision_bodies AS internal_body" in artifacts_query
    assert "media_document.lark_read_mirrors AS lark_mirror" in artifacts_query
    assert "heading.block ->> 'type' = 'heading_1'" in artifacts_query
    assert "media_product.sync_batches AS binding_batch" in artifacts_query
    assert "VALUES (%s::uuid)" in dashboard_query


def test_service_errors_are_typed() -> None:
    assert issubclass(OverviewInvalidRequest, OverviewError)
    assert issubclass(OverviewConflict, OverviewError)


def test_b01_migration_adds_only_indexes_and_idempotency_ledger() -> None:
    migration = (
        Path(__file__).parents[1]
        / "openclaw_app"
        / "migrations"
        / "014_b01_overview.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS media_product.project_summary_idempotency" in migration
    assert "content_projects_b01_tenant_updated_idx" in migration
    assert "document_artifacts_b01_tenant_project_updated_idx" in migration
    assert "CREATE TABLE IF NOT EXISTS media_product.content_projects" not in migration
    assert "CREATE TABLE IF NOT EXISTS media_product.document_artifacts" not in migration
