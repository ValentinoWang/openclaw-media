from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openclaw_app.services.media_business.foundation import TenantContext, error_status
from openclaw_app.services.media_business.publishing import (
    PublishingConflict,
    PublishingFieldUnavailable,
    PublishingInvalidRequest,
    PublishingNotFound,
    PublishingService,
    PublishingUnprocessable,
)
from media_vault import MediaVault


NOW = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
CONTEXT = TenantContext("tenant-a", "user-a")
PACKAGE_ID = "pkg_123456"
RUN_ID = "run_123456"
PROJECT_ID = "project_123456"
ARTIFACT_ID = "artifact_123456"


class Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


def ready_checks():
    return [
        {"key": "content", "checked": True},
        {"key": "publication", "checked": True},
    ]


def package_row(revision=2, status="checking", public_id=PACKAGE_ID):
    canonical_data = {
        "public_run_id": RUN_ID,
        "platform": "douyin",
        "content_fields": {
            "title": "训练日记",
            "body": "真实发布内容",
            "hashtags": ["训练"],
        },
        "rule_checks": [
            {
                "key": "content",
                "status": "pass",
                "source": "publish_readiness_gate",
            }
        ],
        "public_artifact_id": ARTIFACT_ID,
        "status": status,
    }
    return (
        public_id,
        revision,
        canonical_data,
        NOW,
        ARTIFACT_ID,
        PROJECT_ID,
        "publishing_package",
        "internal",
        4,
        NOW,
    )


class FakeConnection:
    def __init__(self, status="checking", revision=2, human_checks=None):
        self.calls = []
        self.commits = 0
        self.package = list(package_row(revision, status))
        self.list_rows = [tuple(self.package)]
        self.check_rows = []
        self.posts = {}
        if human_checks is not None:
            self.check_rows.append(
                (
                    "check_existing",
                    revision,
                    {
                        "public_package_id": PACKAGE_ID,
                        "checks": human_checks,
                    },
                    NOW,
                )
            )
        self.artifacts = {
            ARTIFACT_ID: (
                ARTIFACT_ID,
                PROJECT_ID,
                "publishing_package",
                "internal",
                4,
                "https://docs.example.test/artifact_123456.docx",
                NOW + timedelta(hours=1),
                NOW,
            )
        }
        self.idempotency = {}
        self.next_id = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.commits += 1

    def rollback(self):
        return None

    def new_id(self, prefix):
        self.next_id += 1
        return f"{prefix}_{self.next_id:06d}"

    def execute(self, query, params=()):
        self.calls.append((query, tuple(params)))
        sql = " ".join(query.split())
        if "FROM media_product.b06_idempotency_keys" in sql:
            _tenant, operation, key = params
            record = self.idempotency.get((operation, key))
            return Cursor([] if record is None else [record])
        if "INSERT INTO media_product.b06_idempotency_keys" in sql:
            _tenant, operation, key, checksum, response_json = params
            self.idempotency[(operation, key)] = (checksum, json.loads(response_json))
            return Cursor()
        if "FROM media_product.publishing_checks" in sql:
            package_id = params[-1]
            rows = [
                row
                for row in self.check_rows
                if row[2]["public_package_id"] == package_id
            ]
            rows.sort(key=lambda row: row[1], reverse=True)
            return Cursor(rows[:1])
        if "INSERT INTO media_product.publishing_checks" in sql:
            _tenant, public_id, _source, revision, body = params
            self.check_rows.append((public_id, revision, json.loads(body), NOW))
            return Cursor()
        if "UPDATE media_product.publishing_packages" in sql:
            revision, body, updated_at, _tenant, _public_id, expected = params
            if self.package[1] != expected:
                return Cursor()
            self.package[1] = revision
            self.package[2] = json.loads(body)
            self.package[3] = updated_at
            self.list_rows = [tuple(self.package)]
            return Cursor([tuple(self.package)])
        if "FROM media_product.publishing_packages" in sql:
            return Cursor([tuple(self.package)] if "p.public_id = %s" in sql else self.list_rows)
        if "FROM media_product.published_posts" in sql:
            if "public_id = %s" in sql:
                post_id = params[-1]
                return Cursor([self.posts[post_id]] if post_id in self.posts else [])
            if "canonical_data->>'published_url' = %s" in sql:
                _tenant, package_id, platform, url = params
                rows = [
                    row
                    for row in self.posts.values()
                    if row[2]["public_package_id"] == package_id
                    and row[2]["platform"] == platform
                    and row[2]["published_url"] == url
                ]
                return Cursor(rows[:1])
            package_id = params[-1]
            rows = [
                row
                for row in self.posts.values()
                if row[2]["public_package_id"] == package_id
            ]
            return Cursor(rows)
        if "INSERT INTO media_product.published_posts" in sql:
            _tenant, public_id, _source, revision, body = params
            row = (public_id, revision, json.loads(body), NOW)
            self.posts[public_id] = row
            return Cursor([row])
        if "FROM media_product.document_artifacts" in sql:
            artifact_id = params[-1]
            return Cursor([self.artifacts[artifact_id]] if artifact_id in self.artifacts else [])
        raise AssertionError(f"unhandled SQL: {sql}")


def make_service(connection):
    return PublishingService(
        lambda: connection,
        cursor_secret=b"cursor-secret-0123456789",
        public_id_secret=b"public-secret-0123456789",
        id_factory=connection.new_id,
        clock=lambda: NOW,
    )


def publication_request(url="https://example.test/post/1", expected_revision=2):
    return {
        "publicPackageId": PACKAGE_ID,
        "expectedRevision": expected_revision,
        "platform": "douyin",
        "publishedUrl": url,
        "publishedAt": NOW.isoformat(),
    }


def test_list_projection_is_tenant_bound_and_has_explicit_human_checks():
    connection = FakeConnection()
    response = make_service(connection).list_publishing_packages(CONTEXT, page_size=1)
    item = response["items"][0]
    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert item["publicPackageId"] == PACKAGE_ID
    assert item["artifactDescriptor"]["publicArtifactId"] == ARTIFACT_ID
    assert item["humanChecks"] == [
        {"key": "content", "checked": False, "status": "pending"},
        {"key": "publication", "checked": False, "status": "pending"},
    ]
    assert "tenant-a" not in json.dumps(response)
    assert all("tenant-a" not in query for query, _ in connection.calls)


def test_cursor_is_opaque_and_tenant_bound():
    connection = FakeConnection()
    connection.list_rows = [
        tuple(connection.package),
        package_row(1, public_id="pkg_234567"),
    ]
    first = make_service(connection).list_publishing_packages(CONTEXT, page_size=1)
    assert first["nextCursor"]
    with pytest.raises(PublishingInvalidRequest, match="cursor"):
        make_service(connection).list_publishing_packages(
            TenantContext("tenant-b", "user-b"),
            cursor=first["nextCursor"],
        )


def test_detail_readback_keeps_rule_checks_separate_from_human_checks():
    connection = FakeConnection()
    response = make_service(connection).get_publishing_package(CONTEXT, PACKAGE_ID)
    package = response["package"]
    assert package["ruleChecks"][0]["source"] == "publish_readiness_gate"
    assert package["humanChecks"][0]["key"] == "content"
    assert "source" not in package["humanChecks"][0]


def test_checks_require_two_keys_and_read_back_as_ready():
    connection = FakeConnection()
    response = make_service(connection).update_publishing_checks(
        CONTEXT,
        PACKAGE_ID,
        {
            "expectedRevision": 2,
            "checks": ready_checks(),
            "reason": "manual review completed",
        },
        idempotency_key="checks-1234",
    )
    assert response["revision"] == 3
    assert response["package"]["status"] == "ready"
    assert response["package"]["humanChecks"][1]["status"] == "complete"
    assert any("INSERT INTO media_product.publishing_checks" in q for q, _ in connection.calls)
    assert connection.commits == 1


def test_checks_conflict_and_idempotency_replay():
    conflict = FakeConnection(revision=3)
    with pytest.raises(PublishingConflict):
        make_service(conflict).update_publishing_checks(
            CONTEXT,
            PACKAGE_ID,
            {
                "expectedRevision": 2,
                "checks": ready_checks(),
                "reason": "review",
            },
            idempotency_key="checks-5678",
        )

    connection = FakeConnection()
    service = make_service(connection)
    request = {
        "expectedRevision": 2,
        "checks": ready_checks(),
        "reason": "review",
    }
    first = service.update_publishing_checks(
        CONTEXT,
        PACKAGE_ID,
        request,
        idempotency_key="checks-9999",
    )
    calls = len(connection.calls)
    assert service.update_publishing_checks(
        CONTEXT,
        PACKAGE_ID,
        request,
        idempotency_key="checks-9999",
    ) == first
    assert len(connection.calls) == calls + 1
    with pytest.raises(PublishingConflict, match="different request"):
        service.update_publishing_checks(
            CONTEXT,
            PACKAGE_ID,
            {**request, "reason": "changed"},
            idempotency_key="checks-9999",
        )


def test_publication_needs_ready_package_and_public_url():
    connection = FakeConnection(human_checks=ready_checks())
    with pytest.raises(PublishingUnprocessable):
        make_service(connection).create_published_post(
            CONTEXT,
            publication_request(),
            idempotency_key="post-123456",
        )
    connection = FakeConnection(status="ready", human_checks=ready_checks())
    with pytest.raises(PublishingInvalidRequest, match="public"):
        make_service(connection).create_published_post(
            CONTEXT,
            publication_request("http://127.0.0.1/post/1"),
            idempotency_key="post-234567",
        )


def test_publication_writes_receipt_then_marks_package_published():
    connection = FakeConnection(status="ready", human_checks=ready_checks())
    response = make_service(connection).create_published_post(
        CONTEXT,
        publication_request(),
        idempotency_key="post-345678",
    )
    receipt = response["publishedPost"]
    assert receipt["publicPackageId"] == PACKAGE_ID
    assert receipt["recordedBy"] == "user"
    assert receipt["publishedUrl"] == "https://example.test/post/1"
    assert connection.package[1] == 3
    assert connection.package[2]["status"] == "published"
    stored = next(iter(connection.posts.values()))[2]
    assert stored["retrieval_status"] == "pending"
    assert stored["review_windows"][0]["window"] == "24h"
    assert stored["review_windows"][1]["window"] == "7d"
    assert connection.commits == 1
    readback = make_service(connection).get_published_post(CONTEXT, receipt["publicPostId"])
    assert readback["publishedPost"] == receipt


def test_duplicate_receipt_is_idempotent_and_other_url_conflicts():
    connection = FakeConnection(status="ready", human_checks=ready_checks())
    service = make_service(connection)
    first = service.create_published_post(
        CONTEXT,
        publication_request(),
        idempotency_key="post-456789",
    )
    duplicate = service.create_published_post(
        CONTEXT,
        publication_request(expected_revision=3),
        idempotency_key="post-567890",
    )
    assert duplicate == first
    assert len(connection.posts) == 1
    with pytest.raises(PublishingConflict, match="different publication"):
        service.create_published_post(
            CONTEXT,
            publication_request("https://example.test/post/2", 3),
            idempotency_key="post-678901",
        )


def test_docx_link_is_postgres_owned_and_unopened_is_distinct():
    connection = FakeConnection()
    response = make_service(connection).get_resource_docx_link(CONTEXT, ARTIFACT_ID)
    assert response["document"] == {
        "publicArtifactId": ARTIFACT_ID,
        "url": "https://docs.example.test/artifact_123456.docx",
        "expiresAt": (NOW + timedelta(hours=1)).isoformat(),
    }
    connection.artifacts[ARTIFACT_ID] = (
        *connection.artifacts[ARTIFACT_ID][:5],
        None,
        None,
        NOW,
    )
    with pytest.raises(PublishingFieldUnavailable):
        make_service(connection).get_resource_docx_link(CONTEXT, ARTIFACT_ID)


def test_error_shape_and_migration_are_scoped_to_b06():
    error = PublishingInvalidRequest("bad request", field="publishedUrl")
    assert PublishingService.error_response(error) == {
        "error": {
            "code": "invalid_request",
            "message": "bad request",
            "field": "publishedUrl",
        }
    }
    assert error_status(error) == 400
    migration = (
        Path(__file__).parents[1] / "openclaw_app/migrations/014_b06_publishing.sql"
    ).read_text()
    assert "b06_idempotency_keys" in migration
    assert "docx_url_expires_at" in migration
    assert "published_posts_b06_package_idx" in migration
    assert "publication_receipts" not in migration


class CreationProjectionConnection:
    def __init__(self):
        self.calls = []
        self.commits = 0
        self.existing = None
        self.counter = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.commits += 1

    def new_id(self, prefix):
        self.counter += 1
        return f"{prefix}_projection_{self.counter:06d}"

    def execute(self, query, params=()):
        self.calls.append((query, tuple(params)))
        sql = " ".join(query.split())
        if "FROM media_product.publishing_packages" in sql:
            return Cursor([] if self.existing is None else [self.existing])
        if "INSERT INTO media_product.publishing_packages" in sql:
            self.existing = (params[1],)
        return Cursor()


def test_creation_run_projection_is_tenant_scoped_transactional_and_idempotent():
    connection = CreationProjectionConnection()
    service = PublishingService(
        lambda: connection,
        cursor_secret=b"cursor-secret-0123456789",
        public_id_secret=b"public-secret-0123456789",
        id_factory=connection.new_id,
        clock=lambda: NOW,
    )
    with tempfile.TemporaryDirectory() as temporary:
        tenant_id = "11111111-1111-4111-8111-111111111111"
        vault = MediaVault(tenant_id=tenant_id, root=temporary)
        run_dir = vault.creation_run_dir(RUN_ID)
        run_dir.mkdir(parents=True)
        (run_dir / "draft_output.json").write_text(
            json.dumps(
                {
                    "creator_report": {
                        "overview": {"platform": "douyin", "recommended_topic": "训练日记"},
                        "publishing_pack": {
                            "title_1": "训练日记",
                            "title_2": "训练前后",
                            "cover_text": "坚持训练",
                            "body_copy": "今天完成了一次训练。",
                            "hashtags": ["训练", "日常"],
                            "pinned_comment": "你今天训练了吗？",
                            "comment_prompt": "你会如何开始？",
                            "first_hour_action": "发布后回复前十条评论并置顶提问。",
                        },
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run_dir / "validation_report.json").write_text('{"ok": true}', encoding="utf-8")

        created = service.project_creation_run(tenant_id, RUN_ID, vault_root=temporary)
        replayed = service.project_creation_run(tenant_id, RUN_ID, vault_root=temporary)

    assert created["created"] is True
    assert replayed == {**created, "created": False}
    assert connection.commits == 1
    statements = [" ".join(query.split()) for query, _params in connection.calls]
    assert any("pg_advisory_xact_lock" in query for query in statements)
    for table in (
        "media_product.content_projects",
        "media_product.document_artifacts",
        "media_product.document_revisions",
        "media_document.revision_bodies",
        "media_product.publishing_packages",
    ):
        assert any(f"INSERT INTO {table}" in query for query in statements)
    package_insert = next(params for query, params in connection.calls if "INSERT INTO media_product.publishing_packages" in query)
    package = json.loads(package_insert[-1])
    assert package["public_run_id"] == RUN_ID
    assert package["content_fields"]["first_hour_action"] == "发布后回复前十条评论并置顶提问。"
    assert package["status"] == "draft"
