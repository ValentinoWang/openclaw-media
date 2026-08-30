"""Shared Stage2 test fakes/fixtures for the runtime, gateway and production
HTTP-integration suites.

Base drawn from test_stage2_runtime.py (the most complete of the three
near-identical copies). Where the three suites needed genuinely different
behavior (a per-request artifact_ref, a different organization remote_ref,
a threading.Event-blocking writer for the concurrency-conflict test) those
differences are exposed as constructor parameters / a documented subclass
instead of being silently dropped.
"""

from __future__ import annotations

import threading

from openclaw_app.services.stage2_context import ServerSessionFacts
from openclaw_app.services.stage2_external_document import (
    BindingIdentity,
    ExternalReadbackOutcome,
    ExternalWriteOutcome,
)


PERSONAL_TENANT = "11111111-1111-4111-8111-111111111111"
ORG_TENANT = "22222222-2222-4222-8222-222222222222"


def personal_session(*, tenant_id: str = PERSONAL_TENANT) -> ServerSessionFacts:
    return ServerSessionFacts(
        session_id="session-personal",
        user_id="user-personal",
        tenant_id=tenant_id,
        tenant_type="personal",
        member_tenant_id=tenant_id,
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
    """``artifact_ref`` may be a plain string (the common case) or a
    ``(context, idempotency_key) -> str`` callable for suites whose
    idempotency assertions need a per-request-unique ref (e.g. production's
    ``f"personal-{context.tenant_id}-{idempotency_key}"``)."""

    def __init__(
        self,
        *,
        status: str = "succeeded",
        registration_status: str = "registered",
        artifact_ref: str | object = "personal-artifact-1",
    ) -> None:
        self.status = status
        self.registration_status = registration_status
        self._artifact_ref = artifact_ref
        self.calls = 0

    def write(self, context, content, capability_id, idempotency_key, context_receipt=None):
        self.calls += 1
        artifact_ref = self._artifact_ref
        if callable(artifact_ref):
            artifact_ref = artifact_ref(context, idempotency_key)
        return {
            "status": self.status,
            "artifact_ref": artifact_ref,
            "remote_ref": None,
            "registration": {"status": self.registration_status},
            "readback": {"status": "confirmed" if self.status == "succeeded" else "failed"},
        }


class BlockingPersonalWriter(FakePersonalWriter):
    """Blocks inside write() until released, so a test can assert two
    concurrent requests actually overlap before letting either finish.
    Used by the production idempotency-conflict test."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entered = threading.Event()
        self.release = threading.Event()

    def write(self, *args, **kwargs):
        self.entered.set()
        if not self.release.wait(timeout=3):
            raise RuntimeError("blocking writer was not released")
        return super().write(*args, **kwargs)


class FakeOrganizationAdapter:
    def __init__(
        self,
        *,
        write_status: str = "succeeded",
        readback_status: str = "confirmed",
        remote_ref: str = "doc-org-1",
        remote_revision: str = "remote-1",
    ) -> None:
        self.write_status = write_status
        self.readback_status = readback_status
        self.remote_ref = remote_ref
        self.remote_revision = remote_revision
        self.write_calls = 0
        self.readback_calls = 0

    def write(self, request) -> ExternalWriteOutcome:
        self.write_calls += 1
        binding = request.binding
        return ExternalWriteOutcome(
            self.write_status,
            self.remote_ref,
            self.remote_revision,
            binding.tenant_id,
            binding.binding_id,
            binding.binding_generation,
            request.content_digest,
            None if self.write_status == "succeeded" else "write_failed",
        )

    def readback(self, request, write) -> ExternalReadbackOutcome:
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
