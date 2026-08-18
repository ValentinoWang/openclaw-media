from __future__ import annotations

from dataclasses import replace

import pytest

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
from openclaw_app.services.stage2_runtime import (
    IdempotencyConflict,
    InMemoryReceiptStore,
    Stage2Runtime,
    Stage2RuntimeError,
)


PERSONAL_TENANT = "11111111-1111-4111-8111-111111111111"
ORG_TENANT = "22222222-2222-4222-8222-222222222222"
OTHER_TENANT = "33333333-3333-4333-8333-333333333333"


def personal_session() -> ServerSessionFacts:
    return ServerSessionFacts(
        session_id="session-personal",
        user_id="user-personal",
        tenant_id=PERSONAL_TENANT,
        tenant_type="personal",
        member_tenant_id=PERSONAL_TENANT,
    )


def organization_session(*, tenant_id: str = ORG_TENANT, generation: int = 5) -> ServerSessionFacts:
    return ServerSessionFacts(
        session_id="session-organization",
        user_id="user-organization",
        tenant_id=tenant_id,
        tenant_type="organization",
        member_tenant_id=tenant_id,
        binding_generation=generation,
    )


def organization_binding(*, tenant_id: str = ORG_TENANT, binding_id: str = "binding-org", generation: int = 5) -> BindingIdentity:
    return BindingIdentity(tenant_id, binding_id, generation)


def personal_sources(tenant_id: str = PERSONAL_TENANT) -> list[dict[str, object]]:
    return [
        {
            "sourceId": "material-1",
            "sourceKind": "personal_material",
            "tenantId": tenant_id,
            "workspaceMode": "personal_web",
            "bodyAuthority": "internal",
            "payload": {"title": "Material"},
        },
        {
            "sourceId": "memory-1",
            "sourceKind": "research_brief",
            "tenantId": tenant_id,
            "workspaceMode": "personal_web",
            "bodyAuthority": "internal",
            "payload": {"note": "Remember"},
        },
    ]


def organization_sources(
    tenant_id: str = ORG_TENANT,
    binding_id: str = "binding-org",
    generation: int = 5,
) -> list[dict[str, object]]:
    return [
        {
            "sourceId": "brand-1",
            "sourceKind": "organization_material",
            "tenantId": tenant_id,
            "workspaceMode": "organization_lark",
            "bodyAuthority": "lark",
            "bindingId": binding_id,
            "bindingGeneration": generation,
            "binding": {"tenantId": tenant_id},
            "payload": {"tone": "direct"},
        }
    ]


class FakePersonalWriter:
    def __init__(self, *, status: str = "succeeded", registration_status: str = "registered") -> None:
        self.status = status
        self.registration_status = registration_status
        self.calls = 0

    def write(self, context, content, capability_id, idempotency_key, context_receipt=None):
        self.calls += 1
        return {
            "status": self.status,
            "artifact_ref": "personal-artifact-1",
            "remote_ref": None,
            "registration": {"status": self.registration_status},
            "readback": {"status": "confirmed" if self.status == "succeeded" else "failed"},
        }


class FakeOrganizationAdapter:
    def __init__(self, *, write_status: str = "succeeded", readback_status: str = "confirmed") -> None:
        self.write_status = write_status
        self.readback_status = readback_status
        self.write_calls = 0
        self.readback_calls = 0

    def write(self, request):
        self.write_calls += 1
        binding = request.binding
        return ExternalWriteOutcome(
            self.write_status,
            "doc-org-1",
            "remote-1",
            binding.tenant_id,
            binding.binding_id,
            binding.binding_generation,
            request.content_digest,
            None if self.write_status == "succeeded" else "write_failed",
        )

    def readback(self, request, write):
        self.readback_calls += 1
        binding = request.binding
        return ExternalReadbackOutcome(
            self.readback_status,
            write.remote_ref,
            write.remote_revision,
            binding.tenant_id,
            binding.binding_id,
            binding.binding_generation,
            request.content_digest,
        )


def make_runtime(*, personal_writer=None, organization_adapter=None, store=None, clock=None) -> Stage2Runtime:
    return Stage2Runtime(
        personal_writer=personal_writer or FakePersonalWriter(),
        organization_adapter=organization_adapter or FakeOrganizationAdapter(),
        receipt_store=store,
        clock=clock,
    )


def run_personal(runtime: Stage2Runtime, *, operation_id: str = "personal-op-1", **overrides):
    values = {
        "session": personal_session(),
        "capability_id": DOCUMENT_WRITER_FIXTURE_ID,
        "operation_id": operation_id,
        "sources": personal_sources(),
        "title": "Draft",
        "body": "Body",
        "topic": "Topic",
        "target": "Audience",
        "tradeoffs": ["Speed"],
        "risks": ["Stale source"],
        "confirmed_by": "user-personal",
        "confirmation_ref": "confirmation-1",
        "platform_constraints": {"maxLength": 500},
    }
    values.update(overrides)
    return runtime.run_personal(**values)


def run_organization(runtime: Stage2Runtime, *, operation_id: str = "organization-op-1", **overrides):
    binding = organization_binding()
    values = {
        "session": organization_session(),
        "binding": binding,
        "capability_id": DOCUMENT_WRITER_FIXTURE_ID,
        "operation_id": operation_id,
        "sources": organization_sources(),
        "title": "Organization draft",
        "body": "Body",
        "credential_generation": "credential-9",
        "trusted_open_url": "https://feishu.cn/docx/doc-org-1",
    }
    values.update(overrides)
    return runtime.run_organization(**values)


def test_personal_flow_is_server_owned_ready_and_never_published() -> None:
    writer = FakePersonalWriter()
    receipt = run_personal(make_runtime(personal_writer=writer))

    assert receipt["route"] == "personal_web/internal"
    assert receipt["authorityMode"] == "personal_web/internal"
    assert receipt["artifactStatus"] == "readback_verified"
    assert receipt["readyForPublish"] is True
    assert receipt["publishable"] is False
    assert receipt["error"] is None
    assert receipt["receiptDigest"].startswith("sha256:")
    assert writer.calls == 1


def test_organization_flow_requires_active_binding_and_keeps_mirror_read_only() -> None:
    adapter = FakeOrganizationAdapter()
    receipt = run_organization(make_runtime(organization_adapter=adapter))

    assert receipt["route"] == "organization_lark/lark"
    assert receipt["authorityMode"] == "organization_lark/lark"
    assert receipt["artifactStatus"] == "readback_verified"
    assert receipt["readyForPublish"] is True
    assert receipt["publishable"] is False
    assert receipt["artifact"]["editable"] is False
    assert receipt["mirror"]["readOnly"] is True
    assert adapter.write_calls == 1
    assert adapter.readback_calls == 1


def test_browser_authority_claims_are_rejected_before_any_adapter_call() -> None:
    writer = FakePersonalWriter()
    adapter = FakeOrganizationAdapter()
    runtime = make_runtime(personal_writer=writer, organization_adapter=adapter)

    with pytest.raises(Stage2RuntimeError) as personal_error:
        run_personal(runtime, browser_claims={"tenantId": OTHER_TENANT})
    assert personal_error.value.code == "authority_override"

    with pytest.raises(Stage2RuntimeError) as organization_error:
        run_organization(runtime, browser_claims={"bindingId": "other-binding"})
    assert organization_error.value.code == "authority_override"
    assert writer.calls == 0
    assert adapter.write_calls == 0
    assert adapter.readback_calls == 0


def test_cross_tenant_and_wrong_binding_inputs_fail_closed_without_external_calls() -> None:
    adapter = FakeOrganizationAdapter()
    runtime = make_runtime(organization_adapter=adapter)

    with pytest.raises(Stage2RuntimeError) as tenant_error:
        run_organization(runtime, binding=organization_binding(tenant_id=OTHER_TENANT))
    assert tenant_error.value.code == "binding_tenant_mismatch"

    wrong_source = organization_sources(binding_id="binding-other")
    with pytest.raises(Stage2RuntimeError) as binding_error:
        run_organization(runtime, sources=wrong_source, operation_id="wrong-source-op")
    assert binding_error.value.code == "source_binding_mismatch"
    assert adapter.write_calls == 0
    assert adapter.readback_calls == 0


def test_route_and_capability_mismatches_are_rejected_before_source_or_adapter_calls() -> None:
    adapter = FakeOrganizationAdapter()
    runtime = make_runtime(organization_adapter=adapter)

    with pytest.raises(Stage2RuntimeError) as route_error:
        run_organization(runtime, route="personal_web/internal")
    assert route_error.value.code == "route_mismatch"

    with pytest.raises(Stage2RuntimeError) as capability_error:
        run_organization(runtime, capability_id="missing_capability")
    assert capability_error.value.code == "unregistered_capability"
    assert adapter.write_calls == 0


def test_exact_replay_is_cached_and_conflicting_replay_fails_closed() -> None:
    writer = FakePersonalWriter()
    store = InMemoryReceiptStore()
    runtime = make_runtime(personal_writer=writer, store=store)

    first = run_personal(runtime)
    replay = run_personal(runtime)
    assert replay["replayed"] is True
    assert replay["receiptDigest"] == first["receiptDigest"]
    assert writer.calls == 1

    with pytest.raises(IdempotencyConflict):
        run_personal(runtime, body="different body")
    assert writer.calls == 1


def test_failure_receipts_are_deterministic_and_never_publishable() -> None:
    first_adapter = FakeOrganizationAdapter(write_status="failed")
    first_runtime = make_runtime(organization_adapter=first_adapter)
    first = run_organization(first_runtime, operation_id="failed-op")

    second_adapter = FakeOrganizationAdapter(write_status="failed")
    second_runtime = make_runtime(organization_adapter=second_adapter)
    second = run_organization(second_runtime, operation_id="failed-op")

    assert first["artifactStatus"] == "needs_attention"
    assert first["publishable"] is False
    assert first["readyForPublish"] is False
    assert first["error"]["code"] in {"write_failed", "external_write_needs_attention"}
    assert first["receiptDigest"] == second["receiptDigest"]
    assert first["receiptDigest"].startswith("sha256:")


def test_personal_registration_failure_is_never_publishable() -> None:
    receipt = run_personal(
        make_runtime(personal_writer=FakePersonalWriter(registration_status="failed")),
        operation_id="registration-failed-op",
    )
    assert receipt["artifactStatus"] == "needs_attention"
    assert receipt["publishable"] is False
    assert receipt["readyForPublish"] is False


def test_clock_and_generator_are_injected_without_direct_time_or_io() -> None:
    class Generator:
        def __init__(self):
            self.calls = 0

        def generate(self, context_bundle):
            self.calls += 1
            return {"title": "Generated", "body": "Generated body"}

    generator = Generator()
    runtime = Stage2Runtime(
        personal_writer=FakePersonalWriter(),
        organization_adapter=FakeOrganizationAdapter(),
        content_generator=generator,
        clock=lambda: "2026-08-19T00:00:00+00:00",
    )
    receipt = run_personal(runtime, body=None, operation_id="generated-op")

    assert receipt["observedAt"] == "2026-08-19T00:00:00+00:00"
    assert generator.calls == 1
