from __future__ import annotations

from datetime import datetime, timezone

import pytest

from openclaw_app.services.stage2_server_context import (
    AuthenticatedSessionProvider,
    CurrentBindingProvider,
    ServerStage2ContextProviders,
    Stage2ServerContextError,
    TenantProfileReader,
    TenantSourceReader,
    current_request_session_token,
    extract_session_token,
    stage2_request_context,
)
from openclaw_app.services.stage2_context import ServerSessionFacts


PERSONAL_TENANT = "11111111-1111-4111-8111-111111111111"
ORG_TENANT = "22222222-2222-4222-8222-222222222222"


def _session_record(tenant_id: str, tenant_type: str = "personal") -> dict[str, object]:
    return {
        "sessionId": "session-1",
        "userId": "user-1",
        "tenantId": tenant_id,
        "tenantType": tenant_type,
        "memberTenantId": tenant_id,
        "memberRole": "member",
        "status": "active",
        "memberStatus": "active",
        "tenantStatus": "active",
    }


def test_session_token_extraction_accepts_only_injected_transport_credentials() -> None:
    assert extract_session_token({"headers": {"Authorization": "Bearer opaque-token"}}) == "opaque-token"
    assert extract_session_token({"cookies": {"openclaw_session": "cookie-token"}}) == "cookie-token"
    with pytest.raises(Stage2ServerContextError) as malformed:
        extract_session_token(
            {
                "headers": {"authorization": "Basic opaque-token"},
                "cookies": {"openclaw_session": "cookie-token"},
            }
        )
    assert malformed.value.code == "authentication_invalid"
    assert extract_session_token({"cookies": {"session": "alias-token"}}) is None
    assert extract_session_token({"body": {"tenantId": ORG_TENANT, "session": "attacker"}}) is None


@pytest.mark.parametrize(
    "request",
    [
        {"headers": {"Authorization": "Bearer token"}, "cookies": {"openclaw_session": "cookie"}},
        {"headers": {"Authorization": "Bearer "}},
        {"headers": {"Authorization": "Bearer first,second"}},
        {"cookies": {"openclaw_session": " token"}},
        {"cookies": {"openclaw_session": "one", "OPENCLAW_SESSION": "two"}},
    ],
)
def test_stage2_transport_rejects_ambiguous_or_blank_credentials(request: dict[str, object]) -> None:
    with pytest.raises(Stage2ServerContextError) as error:
        extract_session_token(request)
    assert error.value.code == "authentication_invalid"


def test_stage2_server_alias_conflict_fails_closed() -> None:
    record = _session_record(PERSONAL_TENANT)
    record["tenant_id"] = ORG_TENANT
    provider = AuthenticatedSessionProvider(lambda token: record, lambda: "server-token")
    with pytest.raises(Stage2ServerContextError) as error:
        provider.resolve()
    assert error.value.code == "server_record_invalid"


def test_request_token_context_is_scoped_and_nested_values_are_copied() -> None:
    headers = {"Authorization": "Bearer scoped-token"}
    cookies: dict[str, str] = {}

    with stage2_request_context({"headers": headers, "cookies": cookies}):
        headers["Authorization"] = "Bearer attacker"
        cookies["openclaw_session"] = "attacker"
        assert current_request_session_token() == "scoped-token"

    assert current_request_session_token() is None


def test_authenticated_session_provider_builds_server_facts_and_checks_expiry() -> None:
    now = datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc)
    record = _session_record(PERSONAL_TENANT)
    record["expiresAt"] = "2026-08-19T02:00:00+00:00"
    provider = AuthenticatedSessionProvider(lambda token: record if token == "valid" else None, lambda: "valid", clock=lambda: now)

    session = provider.resolve()

    assert session.tenant_id == PERSONAL_TENANT
    assert session.tenant_type == "personal"
    assert session.member_tenant_id == PERSONAL_TENANT

    expired = dict(record)
    expired["expiresAt"] = "2026-08-19T00:59:59+00:00"
    expired_provider = AuthenticatedSessionProvider(lambda token: expired, lambda: "expired", clock=lambda: now)
    with pytest.raises(Stage2ServerContextError) as error:
        expired_provider.resolve()
    assert error.value.code == "session_invalid"


def test_binding_provider_requires_current_active_generation_and_https_url() -> None:
    session_record = _session_record(ORG_TENANT, "organization")
    session_record["bindingGeneration"] = 7
    session = AuthenticatedSessionProvider(lambda token: session_record, lambda: "org").resolve()
    provider = CurrentBindingProvider(
        lambda tenant_id: {
            "bindingId": "binding-7",
            "tenantId": tenant_id,
            "generation": 7,
            "status": "active",
            "credentialGeneration": "cred-7",
            "trustedOpenUrl": "https://feishu.cn/docx/doc-7",
        }
    )

    resolved = provider.resolve(session)

    assert resolved.identity.tenant_id == ORG_TENANT
    assert resolved.identity.generation == 7
    assert resolved.credential_generation == "cred-7"

    bad_provider = CurrentBindingProvider(
        lambda tenant_id: {
            "bindingId": "binding-8",
            "tenantId": tenant_id,
                "generation": 7,
            "status": "active",
            "credentialGeneration": "cred-8",
            "trustedOpenUrl": "http://feishu.cn/docx/doc-8",
        }
    )
    with pytest.raises(Stage2ServerContextError) as error:
        bad_provider.resolve(session)
    assert error.value.code == "binding_invalid"
    assert error.value.status == 503


def test_binding_record_shape_errors_are_service_failures() -> None:
    session_record = _session_record(ORG_TENANT, "organization")
    session_record["bindingGeneration"] = 1
    session = AuthenticatedSessionProvider(lambda token: session_record, lambda: "org").resolve()
    provider = CurrentBindingProvider(
        lambda tenant_id: {
            "bindingId": "binding-1",
            "tenantId": tenant_id,
            "generation": 1,
            "status": "active",
            "credentialGeneration": None,
            "trustedOpenUrl": "https://feishu.cn/docx/doc-1",
        }
    )

    with pytest.raises(Stage2ServerContextError) as error:
        provider.resolve(session)

    assert error.value.code == "server_record_invalid"
    assert error.value.status == 503


def test_provider_entrypoints_reject_inactive_sessions_before_loaders() -> None:
    session = ServerSessionFacts(
        session_id="s", user_id="u", tenant_id=ORG_TENANT, tenant_type="organization",
        member_tenant_id=ORG_TENANT, session_status="revoked", binding_generation=1,
    )
    binding_calls: list[str] = []
    profile_calls: list[str] = []
    with pytest.raises(Stage2ServerContextError) as binding_error:
        CurrentBindingProvider(lambda tenant: binding_calls.append(tenant)).resolve(session)
    with pytest.raises(Stage2ServerContextError) as profile_error:
        TenantProfileReader(lambda tenant, kind: profile_calls.append(tenant)).read(session)
    assert binding_error.value.code == "session_invalid"
    assert profile_error.value.code == "session_invalid"
    assert binding_calls == []
    assert profile_calls == []


def test_organization_context_resolves_binding_before_profile() -> None:
    session_record = _session_record(ORG_TENANT, "organization") | {"bindingGeneration": 1}
    events: list[str] = []
    session_provider = AuthenticatedSessionProvider(lambda token: session_record, lambda: "org")
    binding_provider = CurrentBindingProvider(lambda tenant: events.append("binding") or {
        "bindingId": "binding-1", "tenantId": tenant, "generation": 1,
        "status": "active", "credentialGeneration": "cred-1",
        "trustedOpenUrl": "https://feishu.cn/docx/doc-1",
    })
    profile_reader = TenantProfileReader(lambda tenant, kind: events.append("profile") or {
        "tenantId": tenant, "tenantType": kind, "revision": "r1", "fields": {},
    })
    ServerStage2ContextProviders(session_provider, binding_provider, profile_reader).organization_context()
    assert events == ["binding", "profile"]


def test_server_context_composition_reads_profile_and_never_accepts_client_identity() -> None:
    calls: list[tuple[str, str]] = []
    session_record = _session_record(ORG_TENANT, "organization")
    session_record["bindingGeneration"] = 3
    session_provider = AuthenticatedSessionProvider(lambda token: session_record, lambda: "org")
    binding_provider = CurrentBindingProvider(
        lambda tenant_id: {
            "bindingId": "binding-3",
            "tenantId": tenant_id,
            "generation": 3,
            "status": "active",
            "credentialGeneration": "cred-3",
            "trustedOpenUrl": "https://feishu.cn/docx/doc-3",
        }
    )

    def profile_loader(tenant_id: str, tenant_type: str) -> dict[str, object]:
        calls.append((tenant_id, tenant_type))
        return {"tenantId": tenant_id, "tenantType": tenant_type, "revision": "r3", "fields": {"name": "Org"}}

    providers = ServerStage2ContextProviders(session_provider, binding_provider, TenantProfileReader(profile_loader))
    context = providers.organization_context()

    assert context.session.tenant_id == ORG_TENANT
    assert context.binding.tenant_id == ORG_TENANT
    assert calls == [(ORG_TENANT, "organization")]


def test_tenant_profile_and_source_readers_fail_closed_on_cross_tenant_rows() -> None:
    session_record = _session_record(PERSONAL_TENANT)
    session = AuthenticatedSessionProvider(lambda token: session_record, lambda: "personal").resolve()
    profile_reader = TenantProfileReader(
        lambda tenant_id, tenant_type: {
            "tenantId": ORG_TENANT,
            "tenantType": tenant_type,
            "revision": "bad",
            "fields": {},
        }
    )
    with pytest.raises(Stage2ServerContextError) as profile_error:
        profile_reader.read(session)
    assert profile_error.value.code == "tenant_profile_mismatch"

    source_reader = TenantSourceReader(
        lambda tenant_id, workspace_mode, source_kinds: [
            {
                "sourceId": "foreign",
                "sourceKind": "personal_material",
                "tenantId": ORG_TENANT,
                "workspaceMode": workspace_mode,
                "bodyAuthority": "internal",
                "payload": {"title": "foreign"},
            }
        ]
    )
    with pytest.raises(Stage2ServerContextError) as source_error:
        source_reader.list_sources(
            tenant_id=PERSONAL_TENANT,
            workspace_mode="personal_web",
            source_kinds=("personal_material",),
        )
    assert source_error.value.code == "source_tenant_mismatch"
