from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from openclaw_app.services.media_business.foundation import TenantContext
from openclaw_app.services.media_business.reviews import (
    ReviewsInternalError,
    ReviewsConflict,
    ReviewsInvalidRequest,
    ReviewsNotFound,
    ReviewsService,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 5, 3, 0, tzinfo=UTC)
CONTEXT = TenantContext("tenant-a", "user-a")


class Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class ScriptedConnection:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        self.calls.append((query, params))
        return self.handler(query, params)

    def commit(self):
        self.commits += 1


def factory(connection):
    def make():
        return connection

    return make


def review_row(public_id="review_abc", revision=2, post_title=None, document_url=None):
    return (
        public_id,
        revision,
        {
            "public_post_id": "post_abc",
            "platform": "douyin",
            "snapshot_24h": "metric_24h",
            "snapshot_7d": "metric_7d",
            "evidence_quality": "verified",
            "model_suggestion": "保留开头冲突并继续观察",
            "human_decision": None,
            "status": "pending",
            "document_url": document_url,
        },
        NOW,
        post_title,
    )


def metric_row(public_id="metric_abc", subject_type="content"):
    return (
        public_id,
        1,
        {
            "subject_type": subject_type,
            "public_subject_id": "post_abc" if subject_type == "content" else "account_abc",
            "review_window": "7d",
            "metric_key": "views",
            "metric_value": 1200,
            "unit": "count",
            "evidence_quality": "verified",
            "collected_at": NOW.isoformat(),
        },
        NOW,
    )


def test_list_reviews_returns_if2_projection_and_opaque_cursor() -> None:
    connection = ScriptedConnection(
        lambda query, params: Cursor([review_row()])
        if "FROM media_product.review_records" in query
        else Cursor()
    )
    service = ReviewsService(
        factory(connection),
        cursor_secret=b"cursor-secret-0123456789",
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )

    response = service.list_reviews(CONTEXT, page_size=30)

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["revision"] == 2
    assert response["items"] == [
        {
            "publicReviewId": "review_abc",
            "publicPostId": "post_abc",
            "postTitle": None,
            "documentUrl": None,
            "platform": "douyin",
            "snapshot24h": "metric_24h",
            "snapshot7d": "metric_7d",
            "evidenceQuality": "verified",
            "modelSuggestion": "保留开头冲突并继续观察",
            "humanDecision": None,
            "status": "pending",
            "revision": 2,
        }
    ]
    assert response["nextCursor"] is None
    assert "tenant-a" not in json.dumps(response, ensure_ascii=False)
    assert all("tenant-a" not in query for query, _ in connection.calls)


def test_list_reviews_projects_linked_post_title() -> None:
    connection = ScriptedConnection(
        lambda query, params: Cursor([review_row(post_title="训练日记")])
        if "FROM media_product.review_records" in query
        else Cursor()
    )
    service = ReviewsService(
        factory(connection),
        cursor_secret=b"cursor-secret-0123456789",
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )

    response = service.list_reviews(CONTEXT, page_size=30)

    assert response["items"][0]["postTitle"] == "训练日记"
    review_query = next(
        query for query, _ in connection.calls if "FROM media_product.review_records" in query
    )
    assert "media_product.published_posts" in review_query
    assert "media_product.publishing_packages" in review_query


def test_list_reviews_projects_nullable_document_url_with_tenant_scope() -> None:
    connection = ScriptedConnection(
        lambda query, params: Cursor(
            [review_row(document_url="https://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e")]
        )
        if "FROM media_product.review_records" in query
        else Cursor()
    )
    service = ReviewsService(
        factory(connection),
        cursor_secret=b"cursor-secret-0123456789",
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )

    response = service.list_reviews(CONTEXT, page_size=30)

    assert response["items"][0]["documentUrl"] == "https://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e"
    review_query, review_params = next(
        (query, params) for query, params in connection.calls if "FROM media_product.review_records" in query
    )
    assert "WHERE r.tenant_id = %s" in review_query
    assert review_params[0] == CONTEXT.tenant_id


@pytest.mark.parametrize(
    "document_url",
    [
        "http://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e",
        "https://tenant.feishu.cn.evil.example/wiki/UkSMwA36fiZuBdkk63ncnm84n0e",
        "https://tenant.feishu.cn:443/wiki/UkSMwA36fiZuBdkk63ncnm84n0e",
        "https://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e?from=base",
        "https://tenant.feishu.cn/wiki/short",
    ],
)
def test_list_reviews_does_not_expose_unsafe_stored_document_urls(document_url) -> None:
    connection = ScriptedConnection(
        lambda query, params: Cursor([review_row(document_url=document_url)])
        if "FROM media_product.review_records" in query
        else Cursor()
    )
    service = ReviewsService(factory(connection), cursor_secret=b"cursor-secret-0123456789")

    response = service.list_reviews(CONTEXT, page_size=30)

    assert response["items"][0]["documentUrl"] is None


def test_metric_lists_keep_window_unit_quality_and_collection_time() -> None:
    def handle(query, params):
        if "FROM media_product.metric_snapshots" in query:
            return Cursor([metric_row(subject_type="content")])
        if "FROM media_product.account_metric_snapshots" in query:
            return Cursor([metric_row(subject_type="account")])
        return Cursor()
    connection = ScriptedConnection(handle)

    service = ReviewsService(
        factory(connection),
        cursor_secret=b"cursor-secret-0123456789",
        clock=lambda: NOW,
    )

    content = service.list_content_metrics(CONTEXT)
    account = service.list_account_metrics(CONTEXT)

    assert content["items"][0]["subjectType"] == "content"
    assert content["items"][0]["reviewWindow"] == "7d"
    assert content["items"][0]["metricValue"] == 1200
    assert content["items"][0]["unit"] == "count"
    assert content["items"][0]["evidenceQuality"] == "verified"
    assert content["items"][0]["collectedAt"] == NOW.isoformat()
    assert account["items"][0]["subjectType"] == "account"


def test_summary_distinguishes_pending_windows_and_evidence_coverage() -> None:
    connection = ScriptedConnection(
        lambda query, params: Cursor([(4, 2, 1, 1, 0.75, NOW)])
        if "COUNT(*)" in query
        else Cursor()
    )
    service = ReviewsService(factory(connection), clock=lambda: NOW)

    assert service.get_reviews_summary(CONTEXT) == {
        "schemaVersion": "media_web_business_pages_v2",
        "revision": 1,
        "summary": {
            "reviewCount": 4,
            "pending24h": 2,
            "pending7d": 1,
            "confirmedCount": 1,
            "evidenceCoverage": 0.75,
            "generatedAt": NOW.isoformat(),
        },
    }


def test_metric_import_rejects_numeric_values_without_evidence_time() -> None:
    connection = ScriptedConnection(lambda query, params: Cursor())
    service = ReviewsService(
        factory(connection),
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )

    with pytest.raises(ReviewsInvalidRequest, match="capturedAt"):
        service.create_metric_import(
            CONTEXT,
            {
                "publicPostId": "post_abc",
                "reviewWindow": "24h",
                "sourceType": "manual",
                "values": {"views": 100},
                "evidenceRefs": [
                    {
                        "kind": "screenshot",
                        "label": "平台后台",
                        "publicUrl": None,
                        "capturedAt": None,
                        "qualityStatus": "verified",
                    }
                ],
            },
            idempotency_key="import-1",
        )


def test_metric_import_writes_evidenced_snapshot_and_is_idempotent() -> None:
    inserted = []

    def handle(query, params):
        if "SELECT response_json" in query:
            return Cursor()
        if "FROM media_product.published_posts" in query:
            return Cursor(
                [
                    (
                        "post_abc",
                        1,
                        {"platform": "douyin", "public_project_id": "project_abc"},
                        NOW,
                    )
                ]
            )
        if "INSERT INTO media_product.metric_snapshots" in query:
            inserted.append((query, params))
            data = json.loads(params[3])
            return Cursor([(params[1], 1, data, NOW)])
        if "INSERT INTO media_product.b07_idempotency_keys" in query:
            return Cursor()
        return Cursor()

    connection = ScriptedConnection(handle)
    service = ReviewsService(
        factory(connection),
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )
    request = {
        "publicPostId": "post_abc",
        "reviewWindow": "24h",
        "sourceType": "manual",
        "values": {"views": 100},
        "evidenceRefs": [
            {
                "kind": "screenshot",
                "label": "平台后台",
                "publicUrl": None,
                "capturedAt": NOW.isoformat(),
                "qualityStatus": "verified",
            }
        ],
    }

    receipt = service.create_metric_import(CONTEXT, request, idempotency_key="import-1")

    assert receipt["ok"] is True
    assert receipt["schemaVersion"] == "media_web_business_pages_v2"
    assert len(inserted) == 1
    stored = json.loads(inserted[0][1][3])
    assert stored["review_window"] == "24h"
    assert stored["evidence_quality"] == "verified"
    assert stored["collected_at"] == NOW.isoformat()
    assert connection.commits == 1


def test_confirm_review_requires_expected_revision() -> None:
    connection = ScriptedConnection(
        lambda query, params: Cursor([review_row(revision=3)])
        if "FROM media_product.review_records" in query
        else Cursor()
    )
    service = ReviewsService(factory(connection), clock=lambda: NOW)

    with pytest.raises(ReviewsConflict):
        service.confirm_review(
            CONTEXT,
            "review_abc",
            {
                "expectedRevision": 2,
                "humanDecision": "保留并继续观察",
                "reason": "7 天指标已完成，证据质量为 verified。",
            },
            idempotency_key="confirm-1",
        )
def test_cursor_is_signed_and_tenant_bound() -> None:
    connection = ScriptedConnection(
        lambda query, params: Cursor(
            [review_row("review_abc"), review_row("review_def")]
        )
        if "FROM media_product.review_records" in query
        else Cursor()
    )
    service = ReviewsService(
        factory(connection),
        cursor_secret=b"cursor-secret-0123456789",
        clock=lambda: NOW,
    )

    first = service.list_reviews(CONTEXT, page_size=1)
    assert first["nextCursor"]
    with pytest.raises(ReviewsInvalidRequest):
        service.list_reviews(
            TenantContext("tenant-b", "user-b"),
            cursor=first["nextCursor"],
            page_size=1,
        )
    with pytest.raises(ReviewsInvalidRequest):
        service.list_reviews(
            CONTEXT,
            cursor=first["nextCursor"][:-1] + ("A" if first["nextCursor"][-1] != "A" else "B"),
            page_size=1,
        )


def test_create_review_writes_artifact_and_report_revision() -> None:
    statements = []

    def handle(query, params):
        statements.append((query, params))
        if "SELECT response_json" in query:
            return Cursor()
        if "FROM media_product.published_posts" in query:
            return Cursor(
                [
                    (
                        "post_abc",
                        1,
                        {"platform": "douyin", "public_project_id": "project_abc"},
                        NOW,
                    )
                ]
            )
        if "FROM media_product.review_records" in query:
            if "public_id = %s" in query:
                return Cursor(
                    [
                        (
                            "review_generated",
                            1,
                            {"public_post_id": "post_abc"},
                            NOW,
                        )
                    ]
                )
            return Cursor()
        if "FROM media_product.document_artifacts" in query:
            return Cursor(
                [("artifact_generated", "project_abc", "review_report", "internal", 1, NOW)]
            )
        return Cursor()

    connection = ScriptedConnection(handle)
    service = ReviewsService(
        factory(connection),
        cursor_secret=b"cursor-secret-0123456789",
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )

    response = service.create_review(
        CONTEXT,
        {
            "publicPostId": "post_abc",
            "expectedRevision": 0,
            "reviewWindow": "7d",
            "reason": "7 天窗口已完成，等待人工确认。",
        },
        idempotency_key="review-create-1",
    )

    assert response["item"]["artifactType"] == "review_report"
    assert response["item"]["publicArtifactId"] == "artifact_generated"
    assert response["item"]["currentRevision"] == 1
    assert any("INSERT INTO media_product.review_records" in query for query, _ in statements)
    assert any("INSERT INTO media_product.document_artifacts" in query for query, _ in statements)
    assert connection.commits == 1


def test_confirm_review_updates_human_conclusion_and_returns_new_revision() -> None:
    update_payloads = []
    review_reads = 0

    def handle(query, params):
        if "SELECT response_json" in query:
            return Cursor()
        if "UPDATE media_product.review_records" in query:
            update_payloads.append(json.loads(params[1]))
            return Cursor()
        if "FROM media_product.review_records" in query:
            nonlocal review_reads
            review_reads += 1
            return Cursor(
                [
                    (
                        "review_abc",
                        3 if review_reads == 1 else 4,
                        {
                            "public_post_id": "post_abc",
                            "platform": "douyin",
                            "review_window": "7d",
                            "public_artifact_id": "artifact_abc",
                            "public_project_id": "project_abc",
                            "evidence_quality": "verified",
                            "status": "pending",
                        },
                        NOW,
                    )
                ]
            )
        if "FROM media_product.document_artifacts" in query:
            return Cursor(
                [("artifact_abc", "project_abc", "review_report", "internal", 4, NOW)]
            )
        return Cursor()

    connection = ScriptedConnection(handle)
    service = ReviewsService(
        factory(connection),
        cursor_secret=b"cursor-secret-0123456789",
        clock=lambda: NOW,
    )

    response = service.confirm_review(
        CONTEXT,
        "review_abc",
        {
            "expectedRevision": 3,
            "humanDecision": "保留当前结构",
            "reason": "7 天数据已完成且证据质量为 verified。",
        },
        idempotency_key="review-confirm-1",
    )

    assert response["revision"] == 4
    assert response["item"]["currentRevision"] == 4
    assert update_payloads[0]["human_decision"] == "保留当前结构"
    assert update_payloads[0]["status"] == "confirmed"
    assert connection.commits == 1
def test_metric_import_rejects_missing_tenant_published_post() -> None:
    calls = []

    def handle(query, params):
        calls.append((query, params))
        if "SELECT response_json" in query:
            return Cursor()
        if "FROM media_product.published_posts" in query:
            return Cursor()
        return Cursor()

    connection = ScriptedConnection(handle)
    service = ReviewsService(
        factory(connection),
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )

    with pytest.raises(ReviewsNotFound):
        service.create_metric_import(
            TenantContext("tenant-b", "user-b"),
            {
                "publicPostId": "post_abc",
                "reviewWindow": "24h",
                "sourceType": "manual",
                "values": {"views": 100},
                "evidenceRefs": [
                    {
                        "kind": "screenshot",
                        "label": "dashboard",
                        "publicUrl": None,
                        "capturedAt": NOW.isoformat(),
                        "qualityStatus": "verified",
                    }
                ],
            },
            idempotency_key="tenant-b-import",
        )

    post_queries = [
        params
        for query, params in calls
        if "FROM media_product.published_posts" in query
    ]
    assert post_queries == [("tenant-b", "post_abc")]
    assert not any("INSERT INTO media_product.metric_snapshots" in query for query, _ in calls)


def test_review_write_requires_artifact_readback() -> None:
    def handle(query, params):
        if "SELECT response_json" in query:
            return Cursor()
        if "FROM media_product.published_posts" in query:
            return Cursor([
                (
                    "post_abc",
                    1,
                    {"platform": "douyin", "public_project_id": "project_abc"},
                    NOW,
                )
            ])
        if "FROM media_product.metric_snapshots" in query:
            return Cursor()
        if "FROM media_product.review_records" in query:
            if "public_id = %s" in query:
                return Cursor([("review_generated", 1, {"public_post_id": "post_abc"}, NOW)])
            return Cursor()
        if "FROM media_product.document_artifacts" in query:
            return Cursor()
        return Cursor()

    connection = ScriptedConnection(handle)
    service = ReviewsService(
        factory(connection),
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )

    with pytest.raises(ReviewsInternalError, match="artifact write was not readable"):
        service.create_review(
            CONTEXT,
            {
                "publicPostId": "post_abc",
                "expectedRevision": 0,
                "reviewWindow": "24h",
                "reason": "facts are ready for review",
            },
            idempotency_key="artifact-readback-failure",
        )
    assert connection.commits == 0


def test_metric_import_reuses_same_fact_and_rejects_conflicting_fact() -> None:
    inserts = []
    evidence = {
        "kind": "screenshot",
        "label": "dashboard",
        "publicUrl": None,
        "capturedAt": NOW.isoformat(),
        "qualityStatus": "verified",
    }
    existing = (
        "metric_existing",
        1,
        {
            "subject_type": "content",
            "public_subject_id": "post_abc",
            "review_window": "24h",
            "metric_key": "views",
            "metric_value": 1200,
            "unit": "count",
            "evidence_quality": "verified",
            "collected_at": NOW.isoformat(),
            "source_type": "manual",
            "evidence_refs": [evidence],
        },
        NOW,
    )

    def handle(query, params):
        if "SELECT response_json" in query:
            return Cursor()
        if "FROM media_product.published_posts" in query:
            return Cursor([
                (
                    "post_abc",
                    1,
                    {"platform": "douyin", "public_project_id": "project_abc"},
                    NOW,
                )
            ])
        if "INSERT INTO media_product.metric_snapshots" in query:
            inserts.append(params)
            return Cursor()
        if "FROM media_product.metric_snapshots" in query:
            return Cursor([existing])
        return Cursor()

    request = {
        "publicPostId": "post_abc",
        "reviewWindow": "24h",
        "sourceType": "manual",
        "values": {"views": 1200},
        "evidenceRefs": [evidence],
    }
    connection = ScriptedConnection(handle)
    service = ReviewsService(
        factory(connection),
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )

    service.create_metric_import(CONTEXT, request, idempotency_key="same-fact-1")
    service.create_metric_import(CONTEXT, request, idempotency_key="same-fact-2")
    conflicting = dict(request)
    conflicting["values"] = {"views": 1201}
    with pytest.raises(ReviewsConflict, match="different facts"):
        service.create_metric_import(CONTEXT, conflicting, idempotency_key="conflicting-fact")

    assert len(inserts) == 3
    assert connection.commits == 2


def test_review_windows_share_one_report_and_revision_chain() -> None:
    metric_rows = []
    review_revision = 0
    review_data = {}
    artifact_revision = 0
    bodies = []

    def metric_snapshot(window, public_id):
        return (
            public_id,
            1,
            {
                "subject_type": "content",
                "public_subject_id": "post_abc",
                "review_window": window,
                "metric_key": "views",
                "metric_value": 1200 if window == "24h" else 2400,
                "unit": "count",
                "evidence_quality": "verified",
                "collected_at": NOW.isoformat(),
            },
            NOW,
        )

    metric_rows.append(metric_snapshot("24h", "metric_24h"))

    def handle(query, params):
        nonlocal artifact_revision, review_data, review_revision
        if "SELECT response_json" in query:
            return Cursor()
        if "FROM media_product.published_posts" in query:
            return Cursor([
                (
                    "post_abc",
                    1,
                    {"platform": "douyin", "public_project_id": "project_abc"},
                    NOW,
                )
            ])
        if "FROM media_product.metric_snapshots" in query:
            return Cursor(metric_rows)
        if "FROM media_product.review_records" in query:
            if "public_id = %s" in query:
                return Cursor([("review_generated", review_revision, review_data, NOW)])
            if "canonical_data->>'public_post_id'" in query and review_revision:
                return Cursor([("review_generated", review_revision, review_data, NOW)])
            return Cursor()
        if "INSERT INTO media_product.review_records" in query:
            review_revision = params[2]
            review_data = json.loads(params[3])
            return Cursor()
        if "UPDATE media_product.review_records" in query:
            review_revision = params[0]
            review_data = json.loads(params[1])
            return Cursor()
        if "INSERT INTO media_product.document_artifacts" in query:
            artifact_revision = params[3]
            return Cursor()
        if "UPDATE media_product.document_artifacts" in query:
            artifact_revision = params[0]
            return Cursor()
        if "FROM media_product.document_artifacts" in query:
            return Cursor([
                ("artifact_generated", "project_abc", "review_report", "internal", artifact_revision, NOW)
            ])
        if "INSERT INTO media_document.revision_bodies" in query:
            bodies.append(json.loads(params[3]))
            return Cursor()
        return Cursor()

    connection = ScriptedConnection(handle)
    service = ReviewsService(
        factory(connection),
        id_factory=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )
    response24h = service.create_review(
        CONTEXT,
        {
            "publicPostId": "post_abc",
            "expectedRevision": 0,
            "reviewWindow": "24h",
            "reason": "first facts are ready",
        },
        idempotency_key="review-24h",
    )

    metric_rows.append(metric_snapshot("7d", "metric_7d"))
    response7d = service.create_review(
        CONTEXT,
        {
            "publicPostId": "post_abc",
            "expectedRevision": 1,
            "reviewWindow": "7d",
            "reason": "longer window is ready",
        },
        idempotency_key="review-7d",
    )

    assert response24h["revision"] == 1
    assert response7d["revision"] == 2
    assert review_data["snapshot_24h"] == "metric_24h"
    assert review_data["snapshot_7d"] == "metric_7d"
    assert review_data["metric_facts"]["24h"]
    assert review_data["metric_facts"]["7d"]
    assert bodies[-1]["sourceFacts"]["windows"]["24h"]
    assert bodies[-1]["sourceFacts"]["windows"]["7d"]
    assert connection.commits == 2
