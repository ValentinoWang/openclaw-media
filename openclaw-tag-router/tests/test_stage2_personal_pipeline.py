from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from openclaw_app.services.stage2_personal_pipeline import (
    IdempotencyConflict,
    PersonalContentPipeline,
    PersonalPipelineError,
    RevisionConflict,
    SQLitePersonalContentStore,
)


TENANT = "tenant-personal"


def context(**overrides):
    value = {
        "tenant_id": TENANT,
        "workspace_mode": "personal_web",
        "body_authority": "internal",
        "capability_id": "personal_content_writer",
        "binding_id": None,
    }
    value.update(overrides)
    return value


def sources():
    return [
        {
            "sourceId": "material-1",
            "sourceKind": "personal_material",
            "tenantId": TENANT,
            "workspaceMode": "personal_web",
            "bodyAuthority": "internal",
            "revision": "2",
            "payload": {"title": "First"},
        },
        {
            "sourceId": "account-1",
            "sourceKind": "account_memory",
            "tenantId": TENANT,
            "workspaceMode": "personal_web",
            "bodyAuthority": "internal",
            "payload": {"tone": "direct"},
        },
    ]


class FakeWriter:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result or {
            "status": "succeeded",
            "artifact_ref": "artifact-1",
            "remote_ref": None,
            "readback": {"status": "confirmed"},
        }

    def write(self, context, content, capability_id, idempotency_key, context_receipt=None):
        self.calls += 1
        return self.result


def bundle(pipeline: PersonalContentPipeline):
    scope = pipeline.build_scope(context(), sources())
    research = pipeline.build_research_brief(scope)
    decision = pipeline.build_decision_brief(
        scope,
        topic="Topic",
        target="Audience",
        tradeoffs=["Speed over breadth"],
        risks=["Stale source"],
        confirmed_by="user-1",
        confirmation_ref="confirm-1",
    )
    return scope, research, decision, pipeline.build_context_bundle(
        scope, research, decision, platform_constraints={"maxLength": 500}
    )


def test_positive_personal_path_is_deterministic_and_never_publishes() -> None:
    pipeline = PersonalContentPipeline()
    scope, research, decision, context_bundle = bundle(pipeline)
    assert pipeline.build_scope(context(), reversed(sources()))["scopeDigest"] == scope["scopeDigest"]
    assert research["tenantId"] == TENANT
    assert decision["confirmedBy"] == "user-1"
    writer = FakeWriter()
    artifact = pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=writer
    )
    revision = pipeline.save_revision(
        artifact["artifactRef"], tenant_id=TENANT, title="Draft 2", body="Body 2", baseline_revision=1, idempotency_key="rev-1"
    )
    package = pipeline.build_publish_package(
        artifact["artifactRef"], tenant_id=TENANT, revision=revision["revision"], platform="douyin", platform_fields={"hook": "A"}
    )
    assert package["externalPublishStatus"] == "not_published"
    assert package["publishable"] is False


def test_sqlite_store_rejects_schema_version_with_missing_columns(tmp_path) -> None:
    database = tmp_path / "personal.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE personal_store_meta (schema_version INTEGER NOT NULL)")
        connection.execute("INSERT INTO personal_store_meta(schema_version) VALUES (1)")
        connection.execute("CREATE TABLE personal_artifacts (artifact_ref TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE personal_replays (replay_key TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE personal_operations (replay_key TEXT PRIMARY KEY)")
        connection.commit()

    with pytest.raises(RuntimeError, match="schema is missing"):
        SQLitePersonalContentStore(database)


def test_cross_tenant_organization_and_binding_sources_are_rejected() -> None:
    pipeline = PersonalContentPipeline()
    wrong = sources()[0] | {"tenantId": "tenant-other"}
    with pytest.raises(PersonalPipelineError) as mismatch:
        pipeline.build_scope(context(), [wrong])
    assert mismatch.value.code == "source_tenant_mismatch"
    org = sources()[0] | {"workspaceMode": "organization_lark", "bodyAuthority": "lark"}
    with pytest.raises(PersonalPipelineError) as organization:
        pipeline.build_scope(context(), [org])
    assert organization.value.code == "organization_source_forbidden"
    bound = sources()[0] | {"bindingId": "binding-1"}
    with pytest.raises(PersonalPipelineError) as binding:
        pipeline.build_scope(context(), [bound])
    assert binding.value.code == "personal_binding_forbidden"


def test_browser_authority_and_unconfirmed_decision_are_rejected() -> None:
    pipeline = PersonalContentPipeline()
    with pytest.raises(PersonalPipelineError) as authority:
        pipeline.build_scope(context(), sources(), browser_claims={"tenantId": "other"})
    assert authority.value.code == "authority_override_forbidden"
    scope = pipeline.build_scope(context(), sources())
    with pytest.raises(PersonalPipelineError) as decision:
        pipeline.build_decision_brief(
            scope, topic="Topic", target="Target", tradeoffs=[], risks=[], confirmed_by=None, confirmation_ref=None
        )
    assert decision.value.code == "human_confirmation_required"


def test_writer_failure_remote_ref_and_readback_failure_close_artifact() -> None:
    pipeline = PersonalContentPipeline()
    _, _, _, context_bundle = bundle(pipeline)
    with pytest.raises(PersonalPipelineError) as failed:
        pipeline.create_artifact(
            context(), context_bundle, title="Draft", body="Body", idempotency_key="w1",
            writer=FakeWriter({"status": "failed"}),
        )
    assert failed.value.code == "writer_failed"
    with pytest.raises(PersonalPipelineError) as remote:
        pipeline.create_artifact(
            context(), context_bundle, title="Draft", body="Body", idempotency_key="w2",
            writer=FakeWriter({"status": "succeeded", "artifact_ref": "a2", "remote_ref": "doc-1", "readback": {"status": "confirmed"}}),
        )
    assert remote.value.code == "personal_remote_ref_forbidden"
    with pytest.raises(PersonalPipelineError) as readback:
        pipeline.create_artifact(
            context(), context_bundle, title="Draft", body="Body", idempotency_key="w3",
            writer=FakeWriter({"status": "succeeded", "artifact_ref": "a3", "remote_ref": None, "readback": {"status": "failed"}}),
        )
    assert readback.value.code == "readback_incomplete"


def test_artifact_and_revision_replay_are_idempotent() -> None:
    pipeline = PersonalContentPipeline()
    _, _, _, context_bundle = bundle(pipeline)
    writer = FakeWriter()
    first = pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=writer
    )
    replay = pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=writer
    )
    assert replay["replayed"] is True
    assert writer.calls == 1
    with pytest.raises(IdempotencyConflict):
        pipeline.create_artifact(
            context(), context_bundle, title="Other", body="Body", idempotency_key="write-1", writer=writer
        )
    revision = pipeline.save_revision(
        first["artifactRef"], tenant_id=TENANT, title="R2", body="B2", baseline_revision=1, idempotency_key="revision-1"
    )
    replay_revision = pipeline.save_revision(
        first["artifactRef"], tenant_id=TENANT, title="R2", body="B2", baseline_revision=1, idempotency_key="revision-1"
    )
    assert revision["revision"] == 2
    assert replay_revision["replayed"] is True


def test_revision_conflict_and_stale_package_fail_closed() -> None:
    pipeline = PersonalContentPipeline()
    _, _, _, context_bundle = bundle(pipeline)
    artifact = pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=FakeWriter()
    )
    pipeline.save_revision(
        artifact["artifactRef"], tenant_id=TENANT, title="R2", body="B2", baseline_revision=1, idempotency_key="revision-1"
    )
    with pytest.raises(RevisionConflict):
        pipeline.save_revision(
            artifact["artifactRef"], tenant_id=TENANT, title="R3", body="B3", baseline_revision=1, idempotency_key="revision-2"
        )
    with pytest.raises(PersonalPipelineError) as stale:
        pipeline.build_publish_package(
            artifact["artifactRef"], tenant_id=TENANT, revision=1, platform="douyin", platform_fields={}
        )
    assert stale.value.code == "stale_revision"


def test_revision_and_publish_package_require_artifact_tenant_scope() -> None:
    pipeline = PersonalContentPipeline()
    _, _, _, context_bundle = bundle(pipeline)
    artifact = pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-tenant", writer=FakeWriter()
    )
    with pytest.raises(PersonalPipelineError) as revision:
        pipeline.save_revision(
            artifact["artifactRef"], tenant_id="tenant-other", title="R2", body="B2",
            baseline_revision=1, idempotency_key="revision-other",
        )
    assert revision.value.code == "artifact_not_found"
    with pytest.raises(PersonalPipelineError) as package:
        pipeline.build_publish_package(
            artifact["artifactRef"], tenant_id="tenant-other", revision=1, platform="douyin", platform_fields={},
        )
    assert package.value.code == "artifact_not_found"


def test_writer_cannot_reuse_existing_artifact_identity_for_another_request() -> None:
    pipeline = PersonalContentPipeline()
    _, _, _, context_bundle = bundle(pipeline)
    writer = FakeWriter()
    pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=writer
    )
    with pytest.raises(PersonalPipelineError) as conflict:
        pipeline.create_artifact(
            context(), context_bundle, title="Other", body="Body", idempotency_key="write-2", writer=writer
        )
    assert conflict.value.code == "artifact_identity_conflict"


def test_sqlite_store_replays_artifact_and_revision_after_pipeline_restart(tmp_path) -> None:
    database = tmp_path / "personal-content.sqlite3"
    first_pipeline = PersonalContentPipeline(store=SQLitePersonalContentStore(database))
    _, _, _, context_bundle = bundle(first_pipeline)
    first_writer = FakeWriter()
    first = first_pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=first_writer
    )
    first_revision = first_pipeline.save_revision(
        first["artifactRef"], tenant_id=TENANT, title="R2", body="B2", baseline_revision=1, idempotency_key="revision-1"
    )
    assert first_writer.calls == 1

    restarted = PersonalContentPipeline(store=SQLitePersonalContentStore(database))
    _, _, _, restarted_bundle = bundle(restarted)
    replay_writer = FakeWriter()
    replay = restarted.create_artifact(
        context(), restarted_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=replay_writer
    )
    replay_revision = restarted.save_revision(
        first["artifactRef"], tenant_id=TENANT, title="R2", body="B2", baseline_revision=1, idempotency_key="revision-1"
    )
    package = restarted.build_publish_package(
        first["artifactRef"], tenant_id=TENANT, revision=first_revision["revision"], platform="douyin", platform_fields={}
    )

    assert replay["replayed"] is True
    assert replay["artifactRef"] == first["artifactRef"]
    assert replay_revision["replayed"] is True
    assert replay_revision["revision"] == first_revision["revision"]
    assert package["externalPublishStatus"] == "not_published"
    assert package["publishable"] is False
    assert replay_writer.calls == 0


def test_sqlite_store_keeps_idempotency_and_revision_conflicts_after_restart(tmp_path) -> None:
    database = tmp_path / "personal-content.sqlite3"
    pipeline = PersonalContentPipeline(store=SQLitePersonalContentStore(database))
    _, _, _, context_bundle = bundle(pipeline)
    artifact = pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=FakeWriter()
    )
    pipeline.save_revision(
        artifact["artifactRef"], tenant_id=TENANT, title="R2", body="B2", baseline_revision=1, idempotency_key="revision-1"
    )

    restarted = PersonalContentPipeline(store=SQLitePersonalContentStore(database))
    _, _, _, restarted_bundle = bundle(restarted)
    with pytest.raises(IdempotencyConflict):
        restarted.create_artifact(
            context(), restarted_bundle, title="Changed", body="Body", idempotency_key="write-1", writer=FakeWriter()
        )
    with pytest.raises(RevisionConflict):
        restarted.save_revision(
            artifact["artifactRef"], tenant_id=TENANT, title="R3", body="B3", baseline_revision=1, idempotency_key="revision-2"
        )


def test_sqlite_store_rejects_corrupt_rows_fail_closed(tmp_path) -> None:
    database = tmp_path / "personal-content.sqlite3"
    pipeline = PersonalContentPipeline(store=SQLitePersonalContentStore(database))
    _, _, _, context_bundle = bundle(pipeline)
    artifact = pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=FakeWriter()
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE personal_artifacts SET artifact_json = ? WHERE artifact_ref = ?",
            ("not-json", artifact["artifactRef"]),
        )
    with pytest.raises(RuntimeError, match="artifact JSON is corrupt"):
        PersonalContentPipeline(store=SQLitePersonalContentStore(database)).build_publish_package(
            artifact["artifactRef"], tenant_id=TENANT, revision=1, platform="douyin", platform_fields={}
        )


def test_sqlite_store_rejects_artifact_json_tenant_drift(tmp_path) -> None:
    database = tmp_path / "personal-content.sqlite3"
    pipeline = PersonalContentPipeline(store=SQLitePersonalContentStore(database))
    _, _, _, context_bundle = bundle(pipeline)
    artifact = pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-tenant-drift", writer=FakeWriter()
    )
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT artifact_json FROM personal_artifacts WHERE artifact_ref = ?",
            (artifact["artifactRef"],),
        ).fetchone()
        payload = json.loads(row[0])
        payload["tenantId"] = "tenant-other"
        connection.execute(
            "UPDATE personal_artifacts SET artifact_json = ? WHERE artifact_ref = ?",
            (json.dumps(payload, separators=(",", ":")), artifact["artifactRef"]),
        )
    with pytest.raises(RuntimeError, match="artifact tenant mismatch"):
        PersonalContentPipeline(store=SQLitePersonalContentStore(database)).build_publish_package(
            artifact["artifactRef"], tenant_id=TENANT, revision=1, platform="douyin", platform_fields={}
        )


def test_sqlite_store_persists_write_readback_and_failure_status(tmp_path) -> None:
    database = tmp_path / "personal-content.sqlite3"
    pipeline = PersonalContentPipeline(store=SQLitePersonalContentStore(database))
    _, _, _, context_bundle = bundle(pipeline)
    artifact = pipeline.create_artifact(
        context(), context_bundle, title="Draft", body="Body", idempotency_key="write-1", writer=FakeWriter()
    )
    assert artifact["writeReceipt"] == {
        "idempotencyKey": "write-1",
        "writeStatus": "succeeded",
        "registrationStatus": "",
        "readbackStatus": "confirmed",
        "readback": {"status": "confirmed"},
        "failure": None,
    }

    failed_key = "write-failed"
    with pytest.raises(PersonalPipelineError):
        pipeline.create_artifact(
            context(), context_bundle, title="Failed", body="Body", idempotency_key=failed_key,
            writer=FakeWriter({"status": "failed"}),
        )
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT status, result_json FROM personal_operations WHERE replay_key = ?",
            (f"artifact:{TENANT}:{failed_key}",),
        ).fetchone()
    assert row[0] == "failed"
    assert '"errorCode":"writer_failed"' in row[1]


def test_in_memory_sqlite_store_is_safe_across_worker_threads() -> None:
    store = SQLitePersonalContentStore(":memory:")
    outcomes: list[object] = []

    def read_from_worker() -> None:
        try:
            outcomes.append(store.get_replay("missing"))
        except Exception as exc:  # pragma: no cover - assertion reports the exception
            outcomes.append(exc)

    worker = threading.Thread(target=read_from_worker)
    worker.start()
    worker.join(timeout=3)

    assert not worker.is_alive()
    assert outcomes == [None]
