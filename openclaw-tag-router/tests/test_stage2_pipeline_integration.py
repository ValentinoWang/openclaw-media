from __future__ import annotations

from openclaw_app.services.stage2_artifact_state import ArtifactStateMachine
from openclaw_app.services.stage2_context import (
    AIExecutionContext,
    DOCUMENT_WRITER_FIXTURE_ID,
    OrganizationBinding,
    ServerSessionFacts,
)
from openclaw_app.services.stage2_external_document import (
    BindingIdentity,
    ExternalReadbackOutcome,
    ExternalWriteOutcome,
)
from openclaw_app.services.stage2_organization_pipeline import OrganizationContentPipeline
from openclaw_app.services.stage2_personal_pipeline import PersonalContentPipeline


PERSONAL_TENANT = "11111111-1111-4111-8111-111111111111"
ORG_TENANT = "22222222-2222-4222-8222-222222222222"


def personal_context() -> AIExecutionContext:
    return AIExecutionContext.from_server_facts(
        ServerSessionFacts(
            session_id="session-personal",
            user_id="user-personal",
            tenant_id=PERSONAL_TENANT,
            tenant_type="personal",
            member_tenant_id=PERSONAL_TENANT,
        ),
        DOCUMENT_WRITER_FIXTURE_ID,
    )


def organization_context() -> AIExecutionContext:
    session = ServerSessionFacts(
        session_id="session-org",
        user_id="user-org",
        tenant_id=ORG_TENANT,
        tenant_type="organization",
        member_tenant_id=ORG_TENANT,
        binding_generation=5,
    )
    return AIExecutionContext.from_server_facts(
        session,
        DOCUMENT_WRITER_FIXTURE_ID,
        binding=OrganizationBinding("binding-org", ORG_TENANT, 5),
    )


class PersonalWriter:
    def write(self, context, content, capability_id, idempotency_key, context_receipt=None):
        return {
            "status": "succeeded",
            "artifact_ref": "personal-artifact",
            "remote_ref": None,
            "readback": {"status": "confirmed"},
        }


class OrganizationAdapter:
    def write(self, request):
        binding = request.binding
        return ExternalWriteOutcome(
            "succeeded",
            "doc-org",
            "remote-1",
            binding.tenant_id,
            binding.binding_id,
            binding.binding_generation,
            request.content_digest,
        )

    def readback(self, request, write):
        binding = request.binding
        return ExternalReadbackOutcome(
            "confirmed",
            write.remote_ref,
            write.remote_revision,
            binding.tenant_id,
            binding.binding_id,
            binding.binding_generation,
            request.content_digest,
        )


def test_personal_context_to_verified_artifact_and_package() -> None:
    context = personal_context()
    pipeline = PersonalContentPipeline()
    scope = pipeline.build_scope(
        context,
        [{
            "sourceId": "source-personal",
            "sourceKind": "personal_material",
            "tenantId": PERSONAL_TENANT,
            "workspaceMode": "personal_web",
            "bodyAuthority": "internal",
            "payload": {"title": "Material"},
        }],
    )
    research = pipeline.build_research_brief(scope)
    decision = pipeline.build_decision_brief(
        scope,
        topic="Topic",
        target="Audience",
        tradeoffs=["Focus"],
        risks=["Stale"],
        confirmed_by="user-personal",
        confirmation_ref="confirmation-1",
    )
    bundle = pipeline.build_context_bundle(scope, research, decision, platform_constraints={"maxLength": 500})
    artifact = pipeline.create_artifact(
        context,
        bundle,
        title="Draft",
        body="Body",
        idempotency_key="personal-write-1",
        writer=PersonalWriter(),
    )
    revision = artifact["revisions"][0]
    state = ArtifactStateMachine().record({
        "tenantId": PERSONAL_TENANT,
        "authorityMode": "personal_web/internal",
        "idempotencyKey": "personal-state-1",
        "contentDigest": revision["contentDigest"],
        "writeStatus": "written",
        "registrationStatus": "registered",
        "readbackStatus": "confirmed",
        "artifactRef": artifact["artifactRef"],
        "revision": "1",
        "readbackContentDigest": revision["contentDigest"],
        "readbackArtifactRef": artifact["artifactRef"],
        "readbackRevision": "1",
    })
    package = pipeline.build_publish_package(
        artifact["artifactRef"], tenant_id=PERSONAL_TENANT, revision=1, platform="douyin", platform_fields={"caption": "Draft"}
    )
    assert state.ready_for_publish is True
    assert package["externalPublishStatus"] == "not_published"


def test_organization_context_to_binding_write_and_read_only_mirror() -> None:
    context = organization_context()
    binding = BindingIdentity(ORG_TENANT, "binding-org", 5)
    pipeline = OrganizationContentPipeline()
    scope = pipeline.build_scope(
        context,
        binding,
        [{
            "sourceId": "source-org",
            "sourceKind": "brand",
            "tenantId": ORG_TENANT,
            "workspaceMode": "organization_lark",
            "bodyAuthority": "lark",
            "bindingId": "binding-org",
            "bindingGeneration": 5,
            "payload": {"tone": "direct"},
        }],
    )
    artifact = pipeline.write_document(
        context,
        scope,
        title="Organization draft",
        body="Body",
        idempotency_key="org-write-1",
        binding=binding,
        adapter=OrganizationAdapter(),
        credential_generation="credential-9",
    )
    mirror = pipeline.readback_mirror(
        artifact["artifactRef"],
        tenant_id=ORG_TENANT,
        binding=binding,
        remote_ref="doc-org",
        remote_revision="remote-1",
        content_digest=artifact["contentDigest"],
        trusted_open_url="https://feishu.cn/docx/doc-org",
    )
    assert artifact["remoteRef"] == "doc-org"
    assert mirror["readOnly"] is True
    assert mirror["editable"] is False
