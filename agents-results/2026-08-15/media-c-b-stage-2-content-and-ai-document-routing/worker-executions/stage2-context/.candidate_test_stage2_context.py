from __future__ import annotations

from datetime import datetime, timezone

import pytest

from openclaw_app.services.stage2_context import (
    AIExecutionContext,
    CapabilityEffectRegistry,
    ContextAuthorityError,
    ContextBuilder,
    ContextSourceError,
    DOCUMENT_WRITER_FIXTURE_ID,
    ORGANIZATION_AUTHORITY_MODE,
    ORGANIZATION_BODY_AUTHORITY,
    ORGANIZATION_WORKSPACE_MODE,
    OrganizationBinding,
    PERSONAL_BODY_AUTHORITY,
    PERSONAL_WORKSPACE_MODE,
    READ_ONLY_CONSULTATION_FIXTURE_ID,
    ServerSessionFacts,
    Stage2ContextError,
)


TENANT_A = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
TENANT_B = "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"
USER_A = "0b3d6ed2-9f3f-4d44-9c6a-1e3a9dfd2e11"


def session(
    *,
    tenant_id: str = TENANT_A,
    tenant_type: str = "personal",
    binding_generation: int | None = None,
    member_status: str = "active",
    session_status: str = "active",
) -> ServerSessionFacts:
    return ServerSessionFacts(
        session_id="session-ctx-a",
        user_id=USER_A,
        tenant_id=tenant_id,
        tenant_type=tenant_type,
        session_status=session_status,
        member_status=member_status,
        member_tenant_id=tenant_id,
        member_role="member",
        binding_generation=binding_generation,
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def binding(*, tenant_id: str = TENANT_A, generation: int = 4, status: str = "active") -> OrganizationBinding:
    return OrganizationBinding("binding-a", tenant_id, generation, status=status)


def personal_row(*, source_id: str = "research-a", payload: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "sourceId": source_id,
        "sourceKind": "research_brief",
        "tenantId": TENANT_A,
        "workspaceMode": PERSONAL_WORKSPACE_MODE,
        "bodyAuthority": PERSONAL_BODY_AUTHORITY,
        "payload": payload or {"title": "Private research"},
        "revision": "2",
    }


def organization_row(*, generation: int = 4, tenant_id: str = TENANT_A) -> dict[str, object]:
    return {
        "sourceId": "org-research-a",
        "sourceKind": "research_brief",
        "tenantId": tenant_id,
        "workspaceMode": ORGANIZATION_WORKSPACE_MODE,
        "bodyAuthority": "lark",
        "binding": {"id": "binding-a", "tenantId": tenant_id, "generation": generation},
        "payload": {"title": "Organization research"},
    }


def test_positive_personal_context_is_server_derived() -> None:
    context = ContextBuilder().build_context(session(), DOCUMENT_WRITER_FIXTURE_ID)

    assert isinstance(context, AIExecutionContext)
    assert context.tenant_id == TENANT_A
    assert context.workspace_mode == PERSONAL_WORKSPACE_MODE
    assert context.body_authority == PERSONAL_BODY_AUTHORITY
    assert context.binding_id is None
    assert context.binding_generation is None
    assert context.member_role == "member"


def test_positive_organization_context_requires_matching_active_binding() -> None:
    context = ContextBuilder().build_context(
        session(tenant_type="organization", binding_generation=4),
        DOCUMENT_WRITER_FIXTURE_ID,
        binding=binding(),
    )

    assert context.authority_mode == ORGANIZATION_AUTHORITY_MODE
    assert context.binding_id == "binding-a"
    assert context.binding_generation == 4


@pytest.mark.parametrize(
    "field",
    [
        "tenantId",
        "workspaceMode",
        "bodyAuthority",
        "binding",
        "bindingGeneration",
        "role",
    ],
)
def test_browser_authority_claims_are_rejected(field: str) -> None:
    with pytest.raises(ContextAuthorityError) as raised:
        ContextBuilder().build_context(
            session(),
            DOCUMENT_WRITER_FIXTURE_ID,
            browser_claims={field: "attacker-controlled"},
        )

    assert raised.value.code == "authority_override"
    assert field in raised.value.fields


def test_inactive_session_or_member_is_rejected() -> None:
    with pytest.raises(Stage2ContextError) as session_error:
        ContextBuilder().build_context(
            session(session_status="revoked"),
            DOCUMENT_WRITER_FIXTURE_ID,
        )
    assert session_error.value.code == "session_inactive"

    with pytest.raises(Stage2ContextError) as member_error:
        ContextBuilder().build_context(
            session(member_status="revoked"),
            DOCUMENT_WRITER_FIXTURE_ID,
        )
    assert member_error.value.code == "member_inactive"


@pytest.mark.parametrize(
    "bad_binding",
    [binding(tenant_id=TENANT_B), binding(generation=5), binding(status="revoked")],
)
def test_wrong_tenant_generation_or_binding_state_is_rejected(bad_binding: OrganizationBinding) -> None:
    with pytest.raises(Stage2ContextError):
        ContextBuilder().build_context(
            session(tenant_type="organization", binding_generation=4),
            DOCUMENT_WRITER_FIXTURE_ID,
            binding=bad_binding,
        )


def test_context_builder_requests_only_authenticated_tenant_and_workspace() -> None:
    class Reader:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def list_sources(self, **kwargs: object):
            self.calls.append(kwargs)
            return [personal_row()]

    reader = Reader()
    result = ContextBuilder(reader).build_for_session(session(), DOCUMENT_WRITER_FIXTURE_ID)

    assert result.items[0].tenant_id == TENANT_A
    assert reader.calls == [
        {
            "tenant_id": TENANT_A,
            "workspace_mode": PERSONAL_WORKSPACE_MODE,
            "source_kinds": (
                "decision_brief",
                "organization_material",
                "personal_material",
                "research_brief",
            ),
        }
    ]


def test_mismatched_source_tenant_is_rejected_instead_of_filtered() -> None:
    leaked = personal_row()
    leaked["tenantId"] = TENANT_B

    with pytest.raises(ContextSourceError) as raised:
        ContextBuilder().build_for_session(session(), DOCUMENT_WRITER_FIXTURE_ID, source_rows=[leaked])

    assert raised.value.code == "source_tenant_mismatch"


def test_personal_context_rejects_binding_data_and_org_context_requires_matching_binding_row() -> None:
    personal_with_binding = personal_row()
    personal_with_binding["binding"] = {"id": "binding-a", "generation": 4}
    with pytest.raises(ContextSourceError) as personal_error:
        ContextBuilder().build_for_session(
            session(), DOCUMENT_WRITER_FIXTURE_ID, source_rows=[personal_with_binding]
        )
    assert personal_error.value.code == "personal_binding_forbidden"

    org_context = session(tenant_type="organization", binding_generation=4)
    with pytest.raises(ContextSourceError) as missing_error:
        ContextBuilder().build_for_session(
            org_context,
            DOCUMENT_WRITER_FIXTURE_ID,
            binding=binding(),
            source_rows=[
                {
                    "sourceId": "org-missing-binding",
                    "sourceKind": "research_brief",
                    "tenantId": TENANT_A,
                    "workspaceMode": ORGANIZATION_WORKSPACE_MODE,
                    "bodyAuthority": "lark",
                    "payload": {"title": "missing binding"},
                }
            ],
        )
    assert missing_error.value.code == "source_binding_required"

    wrong_row = organization_row(generation=5)
    with pytest.raises(ContextSourceError) as mismatch_error:
        ContextBuilder().build_for_session(
            org_context,
            DOCUMENT_WRITER_FIXTURE_ID,
            binding=binding(),
            source_rows=[wrong_row],
        )
    assert mismatch_error.value.code == "source_binding_mismatch"

def test_deterministic_context_checksums_and_readback_receipts() -> None:
    rows = [
        personal_row(source_id="research-a"),
        personal_row(source_id="research-b", payload={"title": "Second"}),
    ]
    first = ContextBuilder().build_for_session(session(), DOCUMENT_WRITER_FIXTURE_ID, source_rows=rows)
    second = ContextBuilder().build_for_session(session(), DOCUMENT_WRITER_FIXTURE_ID, source_rows=list(reversed(rows)))

    assert first.context_checksum == second.context_checksum
    assert first.receipt.checksum == second.receipt.checksum
    assert first.receipt.as_dict() == second.receipt.as_dict()
    assert first.as_dict() == second.as_dict()
    assert first.receipt.receipt_id.startswith("stage2_receipt_")


def test_unregistered_capability_effects_fail_closed() -> None:
    registry = CapabilityEffectRegistry()

    with pytest.raises(Stage2ContextError) as raised:
        registry.require("not-registered")
    assert raised.value.code == "unregistered_capability"

    with pytest.raises(Stage2ContextError) as context_error:
        ContextBuilder(effect_registry=registry).build_context(session(), "not-registered")
    assert context_error.value.code == "unregistered_capability"


def test_read_only_fixture_cannot_be_promoted_to_document_side_effect() -> None:
    registry = CapabilityEffectRegistry()
    effect = registry.require(READ_ONLY_CONSULTATION_FIXTURE_ID)
    assert effect.document_side_effect is False
    assert effect.readback_required is False

    with pytest.raises(Stage2ContextError) as raised:
        registry.authorize(
            READ_ONLY_CONSULTATION_FIXTURE_ID,
            authority_mode=ORGANIZATION_AUTHORITY_MODE,
            document_side_effect=True,
        )
    assert raised.value.code == "capability_effect_mismatch"
