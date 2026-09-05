from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from openclaw_app.account.auth import AccountSession
from openclaw_app.account.workspace_resolution import (
    InMemoryWorkspaceResolutionRepository,
    WorkspaceResolutionRow,
    WorkspaceResolver,
    _row_from_value,
)


class _AccountAuth:
    def __init__(self, session: AccountSession) -> None:
        self.session = session

    def resolve_session(self, _token: str) -> AccountSession:
        return self.session


def _session(*, tenant_id: UUID, user_id: UUID) -> AccountSession:
    return AccountSession(
        session_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=user_id,
        tenant_id=tenant_id,
        username="member@example.com",
        email="member@example.com",
        role="user",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_auth_session_without_workspace_fields_resolves_organization_candidate() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000010")
    personal_tenant = UUID("00000000-0000-0000-0000-000000000011")
    organization_tenant = UUID("00000000-0000-0000-0000-000000000012")
    rows = [
        WorkspaceResolutionRow(
            workspace_id=UUID("00000000-0000-0000-0000-000000000021"),
            tenant_id=personal_tenant,
            workspace_mode="personal_web",
            body_authority="internal",
            membership_role="owner",
            membership_state="ACTIVE",
            owner_user_id=user_id,
            user_id=user_id,
        ),
        WorkspaceResolutionRow(
            workspace_id=UUID("00000000-0000-0000-0000-000000000022"),
            tenant_id=organization_tenant,
            workspace_mode="organization_lark",
            body_authority="lark",
            membership_role="member",
            membership_state="ACTIVE",
            binding_id="binding-1",
            binding_status="ACTIVE",
            user_id=user_id,
        ),
    ]

    session = _session(tenant_id=organization_tenant, user_id=user_id)
    assert not hasattr(session, "workspace_mode")
    assert not hasattr(session, "body_authority")
    assert not hasattr(session, "member_role")

    result = WorkspaceResolver(
        _AccountAuth(session),
        InMemoryWorkspaceResolutionRepository(rows),
    ).resolve("opaque-token")

    assert result.resolution_state == "RESOLVED"
    assert result.selected_tenant_id == organization_tenant
    assert result.selected_workspace_mode == "organization_lark"
    assert result.principal is not None
    assert result.principal.workspace_mode == "organization_lark"
    assert result.principal.body_authority == "lark"


def test_authenticated_session_reuses_the_original_token_without_a_second_auth_lookup() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000010")
    tenant_id = UUID("00000000-0000-0000-0000-000000000011")
    session = _session(tenant_id=tenant_id, user_id=user_id)

    class NoSecondLookup(_AccountAuth):
        def resolve_session(self, _token: str) -> AccountSession:
            raise AssertionError("an authenticated session must not be resolved twice")

    result = WorkspaceResolver(
        NoSecondLookup(session),
        InMemoryWorkspaceResolutionRepository(
            [
                WorkspaceResolutionRow(
                    workspace_id=UUID("00000000-0000-0000-0000-000000000021"),
                    tenant_id=tenant_id,
                    workspace_mode="personal_web",
                    body_authority="internal",
                    membership_role="owner",
                    membership_state="ACTIVE",
                    owner_user_id=user_id,
                    user_id=user_id,
                )
            ]
        ),
    ).resolve(session, authenticated_token="opaque-token")

    assert result.resolution_state == "RESOLVED"
    assert result.principal is not None
    assert result.principal.session_token_hash == hashlib.sha256(b"opaque-token").digest()


def test_organization_name_is_preserved_from_workspace_row_to_selected_candidate() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000010")
    tenant_id = UUID("00000000-0000-0000-0000-000000000012")
    organization_name = "清华AI小王冲一级的自媒体工作室"
    result = WorkspaceResolver(
        _AccountAuth(_session(tenant_id=tenant_id, user_id=user_id)),
        InMemoryWorkspaceResolutionRepository(
            [
                WorkspaceResolutionRow(
                    workspace_id=UUID("00000000-0000-0000-0000-000000000022"),
                    tenant_id=tenant_id,
                    workspace_mode="organization_lark",
                    body_authority="lark",
                    membership_role="member",
                    membership_state="ACTIVE",
                    binding_id="binding-1",
                    binding_status="ACTIVE",
                    user_id=user_id,
                    organization_name=organization_name,
                )
            ]
        ),
    ).resolve("opaque-token")

    assert result.selected_workspace is not None
    assert result.selected_workspace.organization_name == organization_name
    assert result.selected_workspace.to_dict()["organizationName"] == organization_name


def test_workspace_row_mapping_reads_organization_name_from_nested_and_flat_shapes() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000010")
    tenant_id = UUID("00000000-0000-0000-0000-000000000012")
    workspace_id = UUID("00000000-0000-0000-0000-000000000022")

    nested = _row_from_value(
        {
            "workspace": {
                "id": str(workspace_id),
                "tenantId": str(tenant_id),
                "workspaceMode": "organization_lark",
                "bodyAuthority": "lark",
                "organizationName": "嵌套组织",
            },
            "membership": {"role": "member", "status": "ACTIVE"},
            "binding": {"id": "binding-1", "status": "ACTIVE"},
            "userId": str(user_id),
        },
        user_id,
    )
    flat = _row_from_value(
        {
            "workspaceId": str(workspace_id),
            "tenantId": str(tenant_id),
            "workspaceMode": "organization_lark",
            "bodyAuthority": "lark",
            "membershipRole": "member",
            "bindingId": "binding-1",
            "bindingStatus": "ACTIVE",
            "organization_name": "扁平组织",
            "userId": str(user_id),
        },
        user_id,
    )

    assert nested.organization_name == "嵌套组织"
    assert flat.organization_name == "扁平组织"
