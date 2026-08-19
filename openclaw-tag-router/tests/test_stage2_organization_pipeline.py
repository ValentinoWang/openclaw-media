from __future__ import annotations

from dataclasses import replace

import pytest

from openclaw_app.services.stage2_external_document import (
    BindingIdentity,
    ExternalReadbackOutcome,
    ExternalWriteOutcome,
    ExternalDocumentWriter,
    SQLiteWriteReceiptStore,
)
from openclaw_app.services.stage2_organization_pipeline import (
    IdempotencyConflict,
    OrganizationContentPipeline,
    OrganizationPipelineError,
    SQLiteOrganizationContentStore,
)


TENANT = "tenant-org"
DIGEST = "sha256:" + "a" * 64


def binding() -> BindingIdentity:
    return BindingIdentity(TENANT, "binding-1", 4)


def context():
    return {"tenant_id": TENANT, "workspace_mode": "organization_lark", "body_authority": "lark"}


def sources():
    return [{
        "sourceId": "brand-1", "sourceKind": "brand", "tenantId": TENANT,
        "workspaceMode": "organization_lark", "bodyAuthority": "lark",
        "bindingId": "binding-1", "bindingGeneration": 4, "payload": {"tone": "plain"},
    }]


class FakeAdapter:
    def __init__(self, write=None, readback=None):
        self.write_outcome = write or ExternalWriteOutcome("succeeded", "doc-1", "rev-1", TENANT, "binding-1", 4, DIGEST)
        self.readback_outcome = readback or ExternalReadbackOutcome("confirmed", "doc-1", "rev-1", TENANT, "binding-1", 4, DIGEST)
        self.write_calls = 0
        self.readback_calls = 0

    def write(self, request):
        self.write_calls += 1
        # The production adapter receives the digest from the pipeline request;
        # the fake keeps the declared identity fixed for focused tests.
        return replace(self.write_outcome, content_digest=request.content_digest)

    def readback(self, request, write):
        self.readback_calls += 1
        return replace(
            self.readback_outcome,
            content_digest=request.content_digest,
            remote_ref=write.remote_ref,
            remote_revision=write.remote_revision,
        )


def test_organization_scope_write_and_readback_produce_read_only_mirror() -> None:
    pipeline = OrganizationContentPipeline()
    scope = pipeline.build_scope(context(), binding(), sources())
    adapter = FakeAdapter()
    artifact = pipeline.write_document(
        context(), scope, title="Doc", body="Body", idempotency_key="write-1",
        binding=binding(), adapter=adapter, credential_generation="cred-7",
    )
    mirror = pipeline.readback_mirror(
        artifact["artifactRef"], tenant_id=TENANT, binding=binding(), remote_ref="doc-1",
        remote_revision="rev-1", content_digest=artifact["contentDigest"], trusted_open_url="https://feishu.cn/docx/doc-1",
    )
    assert artifact["editable"] is False
    assert mirror["readOnly"] is True
    assert mirror["trustedOpenUrl"].startswith("https://")
    assert adapter.write_calls == 1


def test_wrong_tenant_binding_personal_source_and_browser_claims_are_rejected() -> None:
    pipeline = OrganizationContentPipeline()
    with pytest.raises(OrganizationPipelineError) as tenant:
        pipeline.build_scope({"tenant_id": "other", "workspace_mode": "organization_lark", "body_authority": "lark"}, binding(), sources())
    assert tenant.value.code == "binding_tenant_mismatch"
    with pytest.raises(OrganizationPipelineError) as source:
        pipeline.build_scope(context(), binding(), [sources()[0] | {"workspaceMode": "personal_web"}])
    assert source.value.code == "personal_source_forbidden"
    with pytest.raises(OrganizationPipelineError) as claims:
        pipeline.build_scope(context(), binding(), sources(), browser_claims={"bindingId": "other"})
    assert claims.value.code == "authority_override_forbidden"


def test_partial_external_write_fails_closed_and_missing_ref_is_preserved() -> None:
    pipeline = OrganizationContentPipeline()
    scope = pipeline.build_scope(context(), binding(), sources())
    adapter = FakeAdapter(write=ExternalWriteOutcome("failed", "doc-partial", "rev-1", TENANT, "binding-1", 4, DIGEST, "write_failed"))
    result = pipeline.write_document(
        context(), scope, title="Doc", body="Body", idempotency_key="partial",
        binding=binding(), adapter=adapter, credential_generation="cred-7",
    )
    assert result["status"] == "needs_attention"
    assert result["publishable"] is False
    assert result["remoteRef"] == "doc-partial"


def test_invalid_credential_generation_is_rejected_before_external_write() -> None:
    pipeline = OrganizationContentPipeline()
    scope = pipeline.build_scope(context(), binding(), sources())
    adapter = FakeAdapter()
    with pytest.raises(OrganizationPipelineError) as caught:
        pipeline.write_document(
            context(), scope, title="Doc", body="Body", idempotency_key="invalid-credential",
            binding=binding(), adapter=adapter, credential_generation="\n",
        )
    assert caught.value.code == "invalid_request"
    assert adapter.write_calls == 0


def test_readback_mismatch_and_untrusted_url_fail_closed() -> None:
    pipeline = OrganizationContentPipeline()
    scope = pipeline.build_scope(context(), binding(), sources())
    artifact = pipeline.write_document(
        context(), scope, title="Doc", body="Body", idempotency_key="write-1",
        binding=binding(), adapter=FakeAdapter(), credential_generation="cred-7",
    )
    with pytest.raises(OrganizationPipelineError) as revision:
        pipeline.readback_mirror(
            artifact["artifactRef"], tenant_id=TENANT, binding=binding(), remote_ref="doc-1",
            remote_revision="rev-2", content_digest=artifact["contentDigest"], trusted_open_url="https://feishu.cn/docx/doc-1",
        )
    assert revision.value.code == "remote_revision_mismatch"
    with pytest.raises(OrganizationPipelineError) as url:
        pipeline.readback_mirror(
            artifact["artifactRef"], tenant_id=TENANT, binding=binding(), remote_ref="doc-1",
            remote_revision="rev-1", content_digest=artifact["contentDigest"], trusted_open_url="javascript:alert(1)",
        )
    assert url.value.code == "untrusted_remote_url"


def test_remote_edit_requires_new_revision_and_updates_mirror() -> None:
    pipeline = OrganizationContentPipeline()
    scope = pipeline.build_scope(context(), binding(), sources())
    artifact = pipeline.write_document(
        context(), scope, title="Doc", body="Body", idempotency_key="write-1",
        binding=binding(), adapter=FakeAdapter(), credential_generation="cred-7",
    )
    digest = "sha256:" + "b" * 64
    mirror = pipeline.record_remote_edit_and_readback(
        artifact["artifactRef"], tenant_id=TENANT, binding=binding(), remote_ref="doc-1",
        remote_revision="rev-2", content_digest=digest, trusted_open_url="https://feishu.cn/docx/doc-1",
    )
    assert mirror["remoteRevision"] == "rev-2"
    with pytest.raises(OrganizationPipelineError) as unchanged:
        pipeline.record_remote_edit_and_readback(
            artifact["artifactRef"], tenant_id=TENANT, binding=binding(), remote_ref="doc-1",
            remote_revision="rev-2", content_digest=digest, trusted_open_url="https://feishu.cn/docx/doc-1",
        )
    assert unchanged.value.code == "remote_revision_unchanged"


def test_rejected_remote_edit_does_not_mutate_artifact_state() -> None:
    pipeline = OrganizationContentPipeline()
    scope = pipeline.build_scope(context(), binding(), sources())
    artifact = pipeline.write_document(
        context(), scope, title="Doc", body="Body", idempotency_key="write-1",
        binding=binding(), adapter=FakeAdapter(), credential_generation="cred-7",
    )
    with pytest.raises(OrganizationPipelineError) as wrong_document:
        pipeline.record_remote_edit_and_readback(
            artifact["artifactRef"], tenant_id=TENANT, binding=binding(), remote_ref="doc-other",
            remote_revision="rev-2", content_digest="sha256:" + "b" * 64,
            trusted_open_url="https://feishu.cn/docx/doc-other",
        )
    assert wrong_document.value.code == "remote_ref_mismatch"
    mirror = pipeline.readback_mirror(
        artifact["artifactRef"], tenant_id=TENANT, binding=binding(), remote_ref="doc-1",
        remote_revision="rev-1", content_digest=artifact["contentDigest"],
        trusted_open_url="https://feishu.cn/docx/doc-1",
    )
    assert mirror["remoteRevision"] == "rev-1"


def test_exact_replay_and_conflict_are_idempotent() -> None:
    pipeline = OrganizationContentPipeline()
    scope = pipeline.build_scope(context(), binding(), sources())
    adapter = FakeAdapter()
    first = pipeline.write_document(
        context(), scope, title="Doc", body="Body", idempotency_key="write-1",
        binding=binding(), adapter=adapter, credential_generation="cred-7",
    )
    replay = pipeline.write_document(
        context(), scope, title="Doc", body="Body", idempotency_key="write-1",
        binding=binding(), adapter=adapter, credential_generation="cred-7",
    )
    assert replay["replayed"] is True
    assert adapter.write_calls == 1
    with pytest.raises(IdempotencyConflict):
        pipeline.write_document(
            context(), scope, title="Other", body="Body", idempotency_key="write-1",
            binding=binding(), adapter=adapter, credential_generation="cred-7",
        )
    assert first["remoteRef"] == replay["remoteRef"]


def test_sqlite_organization_state_replays_artifact_and_mirror_after_restart(tmp_path) -> None:
    database = tmp_path / "organization-state.sqlite3"
    first_adapter = FakeAdapter()
    first = OrganizationContentPipeline(
        document_writer=ExternalDocumentWriter(SQLiteWriteReceiptStore(database)),
        store=SQLiteOrganizationContentStore(database),
    )
    scope = first.build_scope(context(), binding(), sources())
    artifact = first.write_document(
        context(), scope, title="Doc", body="Body", idempotency_key="restart-write",
        binding=binding(), adapter=first_adapter, credential_generation="cred-7",
    )
    mirror = first.readback_mirror(
        artifact["artifactRef"], tenant_id=TENANT, binding=binding(), remote_ref="doc-1",
        remote_revision="rev-1", content_digest=artifact["contentDigest"],
        trusted_open_url="https://feishu.cn/docx/doc-1",
    )

    second_adapter = FakeAdapter()
    second = OrganizationContentPipeline(
        document_writer=ExternalDocumentWriter(SQLiteWriteReceiptStore(database)),
        store=SQLiteOrganizationContentStore(database),
    )
    second_scope = second.build_scope(context(), binding(), sources())
    replay = second.write_document(
        context(), second_scope, title="Doc", body="Body", idempotency_key="restart-write",
        binding=binding(), adapter=second_adapter, credential_generation="cred-7",
    )
    persisted = second.readback_mirror(
        artifact["artifactRef"], tenant_id=TENANT, binding=binding(), remote_ref="doc-1",
        remote_revision="rev-1", content_digest=artifact["contentDigest"],
        trusted_open_url="https://feishu.cn/docx/doc-1",
    )

    assert replay["remoteRef"] == artifact["remoteRef"]
    assert replay["replayed"] is True
    assert persisted["mirrorDigest"] == mirror["mirrorDigest"]
    assert first_adapter.write_calls == 1
    assert second_adapter.write_calls == 0
