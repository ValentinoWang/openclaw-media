from __future__ import annotations

import copy
from dataclasses import dataclass

import pytest

from openclaw_app.services.stage2_writer_router import (
    AIExecutionContext,
    Binding,
    CapabilityEffectRegistry,
    CapabilitySpec,
    IdempotencyConflict,
    WriterRouter,
    WriterRouterError,
)


WRITE_BOTH = CapabilitySpec(
    "content_writer",
    "write",
    writes_to=("personal_web/internal", "organization_lark/lark"),
)


@dataclass
class SpyWriter:
    result: object
    calls: list[object] | None = None
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.calls = [] if self.calls is None else self.calls

    def write(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.result)


@dataclass
class StageAdapter:
    result: object
    calls: list[tuple[object, object]] | None = None

    def __post_init__(self) -> None:
        self.calls = [] if self.calls is None else self.calls

    def register(self, request, writer_result):
        self.calls.append((request, copy.deepcopy(writer_result)))
        return copy.deepcopy(self.result)

    def readback(self, request, writer_result):
        self.calls.append((request, copy.deepcopy(writer_result)))
        return copy.deepcopy(self.result)


def personal_context() -> AIExecutionContext:
    return AIExecutionContext(
        authority="personal_web",
        workspace="internal",
        tenant_id="tenant-personal",
        principal_id="user-personal",
    )


def organization_context(*, tenant_id: str = "tenant-org") -> AIExecutionContext:
    return AIExecutionContext(
        authority="organization_lark",
        workspace="lark",
        tenant_id=tenant_id,
        principal_id="user-org",
        active_binding=Binding(
            tenant_id=tenant_id,
            binding_id="binding-org-1",
            generation="credential-generation-1",
        ),
    )


def router_for(
    personal_writer: SpyWriter,
    organization_writer: SpyWriter,
    *specs: CapabilitySpec,
) -> WriterRouter:
    return WriterRouter(
        personal_writer,
        organization_writer,
        capability_registry=CapabilityEffectRegistry({item.capability_id: item for item in specs}),
    )


def personal_result() -> dict:
    return {
        "status": "success",
        "artifact_id": "internal-artifact-1",
        "registration": {"status": "registered", "artifact_id": "internal-artifact-1"},
        "readback": {"status": "verified", "revision": "1"},
    }


def organization_result() -> dict:
    return {
        "status": "success",
        "remote_ref": "https://feishu.cn/docx/remote-document-1",
        "registration": {"status": "registered", "artifact_id": "org-artifact-1"},
        "readback": {"status": "verified", "revision": "1"},
    }


def test_routes_personal_and_organization_to_the_matching_injected_writer() -> None:
    personal_writer = SpyWriter(personal_result())
    organization_writer = SpyWriter(organization_result())
    router = router_for(personal_writer, organization_writer, WRITE_BOTH)

    personal = router.write(personal_context(), "personal draft", "content_writer", "idem-personal-1")
    assert organization_writer.calls == []
    organization = router.write(
        organization_context(),
        "organization draft",
        "content_writer",
        "idem-organization-1",
    )

    assert personal["status"] == "succeeded"
    assert personal["remote_ref"] is None
    assert personal["published"] is False
    assert personal_writer.calls and personal_writer.calls[0].active_binding is None

    assert organization["status"] == "succeeded"
    assert organization["remote_ref"] == "https://feishu.cn/docx/remote-document-1"
    assert organization["published"] is False
    assert organization_writer.calls and organization_writer.calls[0].active_binding == organization_context().active_binding
    assert len(personal_writer.calls) == 1


def test_wrong_authority_fails_before_calling_a_writer() -> None:
    personal_writer = SpyWriter(personal_result())
    organization_writer = SpyWriter(organization_result())
    personal_only = CapabilitySpec(
        "personal_writer",
        "write",
        writes_to=("personal_web/internal",),
    )
    router = router_for(personal_writer, organization_writer, personal_only)

    with pytest.raises(WriterRouterError) as caught:
        router.write(organization_context(), "wrong route", "personal_writer", "idem-wrong-1")

    assert caught.value.code == "authority_mismatch"
    assert personal_writer.calls == []
    assert organization_writer.calls == []

    invalid_context = AIExecutionContext(
        authority="personal_web",
        workspace="internal",
        tenant_id="tenant-personal",
        active_binding=organization_context().active_binding,
    )
    with pytest.raises(WriterRouterError) as caught:
        router.write(invalid_context, "wrong binding", "personal_writer", "idem-wrong-2")
    assert caught.value.code == "authority_mismatch"


def test_read_only_consultation_is_a_no_op_and_never_calls_a_writer() -> None:
    personal_writer = SpyWriter(personal_result())
    organization_writer = SpyWriter(organization_result())
    consultation = CapabilitySpec("consultation", "read")
    router = router_for(personal_writer, organization_writer, consultation)

    result = router.write(
        organization_context(),
        "answer this question",
        "consultation",
        "idem-consultation-1",
    )

    assert result["status"] == "no_op"
    assert result["writer_called"] is False
    assert result["needs_attention"] is False
    assert personal_writer.calls == []
    assert organization_writer.calls == []


def test_unregistered_capability_effect_fails_closed() -> None:
    personal_writer = SpyWriter(personal_result())
    organization_writer = SpyWriter(organization_result())
    router = router_for(personal_writer, organization_writer)

    with pytest.raises(WriterRouterError) as caught:
        router.write(personal_context(), "unregistered", "not_registered", "idem-unregistered-1")

    assert caught.value.code == "capability_unregistered"
    assert personal_writer.calls == []
    assert organization_writer.calls == []


def test_readback_incomplete_closes_the_write_as_needs_attention() -> None:
    writer = SpyWriter(
        {
            "status": "success",
            "artifact_id": "internal-artifact-2",
            "registration": {"status": "registered"},
        }
    )
    router = router_for(writer, SpyWriter(organization_result()), WRITE_BOTH)

    result = router.write(personal_context(), "missing readback", "content_writer", "idem-readback-1")
    replay = router.write(personal_context(), "missing readback", "content_writer", "idem-readback-1")

    assert result["status"] == "needs_attention"
    assert result["publish_success"] is False
    assert result["error"]["code"] == "readback_incomplete"
    assert replay["replayed"] is True
    assert len(writer.calls) == 1


def test_registration_failure_closes_the_write_as_needs_attention() -> None:
    writer = SpyWriter(
        {
            "status": "success",
            "artifact_id": "internal-artifact-3",
            "registration": {"status": "failed", "error": {"code": "db_down"}},
            "readback": {"status": "verified"},
        }
    )
    router = router_for(writer, SpyWriter(organization_result()), WRITE_BOTH)

    result = router.write(personal_context(), "registration failure", "content_writer", "idem-registration-1")

    assert result["status"] == "needs_attention"
    assert result["error"]["code"] == "registration_failed"
    assert result["published"] is False


def test_writer_exception_closes_without_claiming_publish_success() -> None:
    writer = SpyWriter(personal_result(), error=RuntimeError("adapter unavailable"))
    router = router_for(writer, SpyWriter(organization_result()), WRITE_BOTH)

    result = router.write(personal_context(), "writer failure", "content_writer", "idem-writer-failure-1")

    assert result["status"] == "needs_attention"
    assert result["error"]["code"] == "writer_failed"
    assert result["needs_attention"] is True
    assert result["published"] is False
    assert result["publish_success"] is False


def test_organization_result_without_remote_ref_needs_attention() -> None:
    organization_writer = SpyWriter(
        {
            "status": "success",
            "registration": {"status": "registered"},
            "readback": {"status": "verified"},
        }
    )
    router = router_for(SpyWriter(personal_result()), organization_writer, WRITE_BOTH)

    result = router.write(
        organization_context(),
        "missing remote ref",
        "content_writer",
        "idem-remote-ref-1",
    )

    assert result["status"] == "needs_attention"
    assert result["error"]["code"] == "organization_remote_ref_missing"


def test_registration_and_readback_adapters_receive_only_normalized_writer_state() -> None:
    writer = SpyWriter({"status": "success", "remote_ref": "remote-doc-2"})
    registrar = StageAdapter({"status": "registered", "artifact_id": "org-artifact-2"})
    readback = StageAdapter({"status": "verified", "revision": "2"})
    router = WriterRouter(
        SpyWriter(personal_result()),
        writer,
        capability_registry=CapabilityEffectRegistry({"content_writer": WRITE_BOTH}),
        artifact_registrar=registrar,
        readback_verifier=readback,
    )

    result = router.write(organization_context(), "adapter path", "content_writer", "idem-adapter-1")

    assert result["status"] == "succeeded"
    assert result["registration"]["status"] == "succeeded"
    assert result["readback"]["status"] == "succeeded"
    assert registrar.calls and registrar.calls[0][0].active_binding == organization_context().active_binding
    assert registrar.calls[0][1]["remote_ref"] == "remote-doc-2"
    assert readback.calls and readback.calls[0][1]["registration"]["status"] == "succeeded"


def test_idempotent_replay_is_deterministic_and_receipt_is_opaque() -> None:
    writer = SpyWriter(personal_result())
    router = router_for(writer, SpyWriter(organization_result()), WRITE_BOTH)

    first = router.write(
        personal_context(),
        "same content",
        "content_writer",
        "idem-replay-1",
        context_receipt="receipt|tenant-personal|not-a-storage-key",
    )
    replay = router.write(
        AIExecutionContext(
            authority="personal_web",
            workspace="internal",
            tenant_id="tenant-personal",
            principal_id="a-different-member",
        ),
        "same content",
        "content_writer",
        "idem-replay-1",
        context_receipt="a completely different opaque receipt",
    )

    assert first["status"] == "succeeded"
    assert replay["status"] == "succeeded"
    assert replay["replayed"] is True
    assert first["receipt_storage_key"] == replay["receipt_storage_key"]
    assert first["context_receipt_present"] is True
    assert len(writer.calls) == 1


def test_conflicting_idempotency_key_is_rejected_without_a_second_write() -> None:
    writer = SpyWriter(personal_result())
    router = router_for(writer, SpyWriter(organization_result()), WRITE_BOTH)
    router.write(personal_context(), "first body", "content_writer", "idem-conflict-1")

    with pytest.raises(IdempotencyConflict) as caught:
        router.write(personal_context(), "different body", "content_writer", "idem-conflict-1")

    assert caught.value.code == "idempotency_conflict"
    assert len(writer.calls) == 1


def test_accepts_server_owned_stage2_context_and_effect_registry() -> None:
    from openclaw_app.services.stage2_context import (
        AIExecutionContext as ServerAIExecutionContext,
        DEFAULT_CAPABILITY_EFFECT_REGISTRY,
        DOCUMENT_WRITER_FIXTURE_ID,
        OrganizationBinding as ServerOrganizationBinding,
        ServerSessionFacts,
    )

    tenant_id = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
    personal_session = ServerSessionFacts(
        "session-personal",
        "user-personal",
        tenant_id,
        "personal",
        member_tenant_id=tenant_id,
    )
    organization_session = ServerSessionFacts(
        "session-organization",
        "user-organization",
        tenant_id,
        "organization",
        member_tenant_id=tenant_id,
        binding_generation=4,
    )
    personal_context = ServerAIExecutionContext.from_server_facts(
        personal_session,
        DOCUMENT_WRITER_FIXTURE_ID,
    )
    organization_context = ServerAIExecutionContext.from_server_facts(
        organization_session,
        DOCUMENT_WRITER_FIXTURE_ID,
        binding=ServerOrganizationBinding("binding-organization", tenant_id, 4),
    )
    personal_writer = SpyWriter(personal_result())
    organization_writer = SpyWriter(organization_result())
    router = WriterRouter(
        personal_writer,
        organization_writer,
        capability_registry=DEFAULT_CAPABILITY_EFFECT_REGISTRY,
    )

    personal = router.write(
        personal_context,
        "personal body",
        DOCUMENT_WRITER_FIXTURE_ID,
        "stage2-context-personal",
    )
    organization = router.write(
        organization_context,
        "organization body",
        DOCUMENT_WRITER_FIXTURE_ID,
        "stage2-context-organization",
    )

    assert personal["status"] == "succeeded"
    assert organization["status"] == "succeeded"
    assert len(personal_writer.calls) == 1
    assert len(organization_writer.calls) == 1
    assert organization_writer.calls[0].active_binding.binding_id == "binding-organization"
