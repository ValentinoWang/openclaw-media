from __future__ import annotations

from dataclasses import replace

import pytest

from openclaw_app.services.stage2_context import (
    AIExecutionContext,
    DOCUMENT_WRITER_FIXTURE_ID,
    OrganizationBinding,
    ServerSessionFacts,
)
from openclaw_app.services.stage2_runtime import (
    IdempotencyConflict,
    InMemoryReceiptStore,
    Stage2Runtime,
    Stage2RuntimeError,
)
from openclaw_app.services.stage2_personal_pipeline import SQLitePersonalContentStore

from _fixtures.stage2 import (
    FakeOrganizationAdapter,
    FakePersonalWriter,
    organization_binding,
    organization_session,
    organization_sources,
    personal_session,
    personal_sources,
)


PERSONAL_TENANT = "11111111-1111-4111-8111-111111111111"
ORG_TENANT = "22222222-2222-4222-8222-222222222222"
OTHER_TENANT = "33333333-3333-4333-8333-333333333333"


def make_runtime(*, personal_writer=None, organization_adapter=None, store=None, personal_store=None, clock=None) -> Stage2Runtime:
    return Stage2Runtime(
        personal_writer=personal_writer or FakePersonalWriter(),
        personal_store=personal_store,
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


def test_runtime_accepts_durable_personal_store_across_instances(tmp_path) -> None:
    database = tmp_path / "runtime-personal.sqlite3"
    writer = FakePersonalWriter()
    first = make_runtime(
        personal_writer=writer,
        personal_store=SQLitePersonalContentStore(database),
    )
    first_receipt = run_personal(first, operation_id="durable-op")

    second_writer = FakePersonalWriter()
    second = make_runtime(
        personal_writer=second_writer,
        personal_store=SQLitePersonalContentStore(database),
    )
    second_receipt = run_personal(second, operation_id="durable-op")

    assert first_receipt["artifactStatus"] == "readback_verified"
    assert second_receipt["artifactStatus"] == "readback_verified"
    assert second_receipt["artifact"]["replayed"] is True
    assert writer.calls == 1
    assert second_writer.calls == 0
