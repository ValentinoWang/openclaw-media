from __future__ import annotations

import pytest

from openclaw_app.services.stage2_personal_pipeline import (
    IdempotencyConflict,
    PersonalContentPipeline,
    PersonalPipelineError,
    RevisionConflict,
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
        artifact["artifactRef"], title="Draft 2", body="Body 2", baseline_revision=1, idempotency_key="rev-1"
    )
    package = pipeline.build_publish_package(
        artifact["artifactRef"], revision=revision["revision"], platform="douyin", platform_fields={"hook": "A"}
    )
    assert package["externalPublishStatus"] == "not_published"
    assert package["publishable"] is False


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
        first["artifactRef"], title="R2", body="B2", baseline_revision=1, idempotency_key="revision-1"
    )
    replay_revision = pipeline.save_revision(
        first["artifactRef"], title="R2", body="B2", baseline_revision=1, idempotency_key="revision-1"
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
        artifact["artifactRef"], title="R2", body="B2", baseline_revision=1, idempotency_key="revision-1"
    )
    with pytest.raises(RevisionConflict):
        pipeline.save_revision(
            artifact["artifactRef"], title="R3", body="B3", baseline_revision=1, idempotency_key="revision-2"
        )
    with pytest.raises(PersonalPipelineError) as stale:
        pipeline.build_publish_package(
            artifact["artifactRef"], revision=1, platform="douyin", platform_fields={}
        )
    assert stale.value.code == "stale_revision"
