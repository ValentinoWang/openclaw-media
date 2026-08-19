from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import pytest

from openclaw_app.adapters.http_api import make_server
from openclaw_app.services.stage2_context import (
    DOCUMENT_WRITER_FIXTURE_ID,
    ServerSessionFacts,
)
from openclaw_app.services.stage2_external_document import (
    BindingIdentity,
    ExternalReadbackOutcome,
    ExternalWriteOutcome,
)
from openclaw_app.services.stage2_gateway import (
    OrganizationServerContext,
    Stage2Gateway,
    Stage2GatewayError,
)
from openclaw_app.services.stage2_runtime import Stage2Runtime
from openclaw_app.services.stage2_server_context import (
    AuthenticatedSessionProvider,
    CurrentBindingProvider,
    ServerStage2ContextProviders,
    Stage2ServerContextError,
    TenantProfileReader,
    current_request_session_token,
)


PERSONAL_TENANT = "11111111-1111-4111-8111-111111111111"
ORG_TENANT = "22222222-2222-4222-8222-222222222222"


def _personal_session() -> ServerSessionFacts:
    return ServerSessionFacts(
        session_id="session-personal",
        user_id="user-personal",
        tenant_id=PERSONAL_TENANT,
        tenant_type="personal",
        member_tenant_id=PERSONAL_TENANT,
    )


def _organization_context() -> OrganizationServerContext:
    session = ServerSessionFacts(
        session_id="session-organization",
        user_id="user-organization",
        tenant_id=ORG_TENANT,
        tenant_type="organization",
        member_tenant_id=ORG_TENANT,
        binding_generation=5,
    )
    return OrganizationServerContext(
        session=session,
        binding=BindingIdentity(ORG_TENANT, "binding-org", 5),
        credential_generation="credential-9",
        trusted_open_url="https://feishu.cn/docx/doc-org-1",
    )


def _personal_sources() -> list[dict[str, object]]:
    return [
        {
            "sourceId": "material-1",
            "sourceKind": "personal_material",
            "tenantId": PERSONAL_TENANT,
            "workspaceMode": "personal_web",
            "bodyAuthority": "internal",
            "payload": {"title": "Material"},
        }
    ]


def _organization_sources() -> list[dict[str, object]]:
    return [
        {
            "sourceId": "brand-1",
            "sourceKind": "organization_material",
            "tenantId": ORG_TENANT,
            "workspaceMode": "organization_lark",
            "bodyAuthority": "lark",
            "bindingId": "binding-org",
            "bindingGeneration": 5,
            "binding": {"tenantId": ORG_TENANT},
            "payload": {"tone": "direct"},
        }
    ]


class _PersonalWriter:
    def __init__(self) -> None:
        self.calls = 0

    def write(self, context, content, capability_id, idempotency_key, context_receipt=None):
        self.calls += 1
        return {
            "status": "succeeded",
            "artifact_ref": "personal-artifact-1",
            "remote_ref": None,
            "registration": {"status": "registered"},
            "readback": {"status": "confirmed"},
        }


class _OrganizationAdapter:
    def __init__(self) -> None:
        self.write_calls = 0
        self.readback_calls = 0

    def write(self, request):
        self.write_calls += 1
        binding = request.binding
        return ExternalWriteOutcome(
            "succeeded",
            "doc-org-1",
            "1",
            binding.tenant_id,
            binding.binding_id,
            binding.binding_generation,
            request.content_digest,
        )

    def readback(self, request, write):
        self.readback_calls += 1
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


def _runtime(writer: _PersonalWriter | None = None, adapter: _OrganizationAdapter | None = None) -> Stage2Runtime:
    return Stage2Runtime(
        personal_writer=writer or _PersonalWriter(),
        organization_adapter=adapter or _OrganizationAdapter(),
    )


def _personal_payload(operation_id: str = "gateway-personal-1") -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "sources": _personal_sources(),
        "title": "Draft",
        "body": "Body",
        "topic": "Topic",
        "target": "Audience",
        "confirmed_by": "user-personal",
        "confirmation_ref": "confirmation-1",
    }


def _organization_payload(operation_id: str = "gateway-organization-1") -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "sources": _organization_sources(),
        "title": "Organization draft",
        "body": "Body",
    }


class _App:
    def __init__(self, gateway: Stage2Gateway | None) -> None:
        self.stage2_gateway = gateway

    def process_stage2(self, mode: str, payload: dict[str, object]) -> dict[str, object]:
        if self.stage2_gateway is None:
            raise RuntimeError("stage2_unavailable")
        return self.stage2_gateway.run(mode, payload)


def _app(gateway: Stage2Gateway | None) -> _App:
    return _App(gateway)


def _fixture_gateway(
    runtime: Stage2Runtime,
    *,
    personal_session_provider=_personal_session,
    organization_context_provider=_organization_context,
) -> Stage2Gateway:
    return Stage2Gateway(
        runtime,
        capability_id=DOCUMENT_WRITER_FIXTURE_ID,
        personal_session_provider=personal_session_provider,
        organization_context_provider=organization_context_provider,
        allow_transport_sources=True,
    )


def _post(
    server,
    path: str,
    payload: object,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=body,
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_gateway_injects_server_personal_context_and_rejects_client_authority() -> None:
    writer = _PersonalWriter()
    provider_calls = 0

    def personal_provider() -> ServerSessionFacts:
        nonlocal provider_calls
        provider_calls += 1
        return _personal_session()

    gateway = _fixture_gateway(
        _runtime(writer=writer),
        personal_session_provider=personal_provider,
        organization_context_provider=_organization_context,
    )
    receipt = gateway.run("personal", _personal_payload())
    assert receipt["route"] == "personal_web/internal"
    assert provider_calls == 1
    assert writer.calls == 1

    with pytest.raises(Stage2GatewayError) as error:
        gateway.run("personal", {**_personal_payload("rejected"), "tenantId": ORG_TENANT})
    assert error.value.code == "authority_override"
    assert provider_calls == 1
    assert writer.calls == 1


def test_gateway_keeps_organization_binding_and_credentials_server_owned() -> None:
    adapter = _OrganizationAdapter()
    gateway = _fixture_gateway(_runtime(adapter=adapter))
    receipt = gateway.run("organization", _organization_payload())
    assert receipt["route"] == "organization_lark/lark"
    assert adapter.write_calls == 1
    assert adapter.readback_calls == 1

    with pytest.raises(Stage2GatewayError) as error:
        gateway.run("organization", {**_organization_payload("rejected"), "bindingId": "attacker-binding"})
    assert error.value.code == "authority_override"
    assert adapter.write_calls == 1
    assert adapter.readback_calls == 1


def test_http_route_is_fail_closed_without_an_injected_gateway() -> None:
    server = make_server("127.0.0.1", 0, _app(None))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(server, "/stage2/personal", _personal_payload())
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
    assert status == 503
    assert body == {"ok": False, "error": {"code": "stage2_unavailable"}}


def test_http_routes_dispatch_personal_and_organization_to_gateway() -> None:
    writer = _PersonalWriter()
    adapter = _OrganizationAdapter()
    gateway = _fixture_gateway(_runtime(writer=writer, adapter=adapter))
    server = make_server("127.0.0.1", 0, _app(gateway))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        personal_status, personal_body = _post(server, "/stage2/personal", _personal_payload("http-personal"))
        organization_status, organization_body = _post(
            server,
            "/stage2/organization",
            _organization_payload("http-organization"),
        )
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
    assert personal_status == 200
    assert personal_body["ok"] is True
    assert personal_body["receipt"]["route"] == "personal_web/internal"
    assert organization_status == 200
    assert organization_body["ok"] is True
    assert organization_body["receipt"]["route"] == "organization_lark/lark"


def test_gateway_preserves_stable_server_context_error_status() -> None:
    def missing_session() -> ServerSessionFacts:
        raise Stage2ServerContextError(
            "authentication_required",
            "an authenticated session is required",
            status=401,
        )

    gateway = _fixture_gateway(
        _runtime(),
        personal_session_provider=missing_session,
        organization_context_provider=_organization_context,
    )

    with pytest.raises(Stage2GatewayError) as error:
        gateway.run("personal", _personal_payload("missing-session"))

    assert error.value.code == "authentication_required"
    assert error.value.status == 401


def test_http_cookie_context_is_request_scoped_and_cleared_after_dispatch() -> None:
    session_record = {
        "sessionId": "session-personal",
        "userId": "user-personal",
        "tenantId": PERSONAL_TENANT,
        "tenantType": "personal",
        "memberTenantId": PERSONAL_TENANT,
        "status": "active",
        "memberStatus": "active",
        "tenantStatus": "active",
    }
    tokens: list[str] = []

    def session_loader(token: str) -> dict[str, object] | None:
        tokens.append(token)
        return session_record if token == "cookie-token" else None

    session_provider = AuthenticatedSessionProvider(
        session_loader,
        current_request_session_token,
    )
    contexts = ServerStage2ContextProviders(
        session_provider,
        CurrentBindingProvider(lambda tenant_id: None),
        TenantProfileReader(
            lambda tenant_id, tenant_type: {
                "tenantId": tenant_id,
                "tenantType": tenant_type,
                "revision": "1",
                "fields": {},
            }
        ),
    )
    gateway = _fixture_gateway(
        _runtime(),
        personal_session_provider=contexts.personal_session,
        organization_context_provider=contexts.organization_context,
    )
    server = make_server("127.0.0.1", 0, _app(gateway))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ok_status, ok_body = _post(
            server,
            "/stage2/personal",
            _personal_payload("cookie-authenticated"),
            headers={"Cookie": "openclaw_session=cookie-token"},
        )
        missing_status, missing_body = _post(
            server,
            "/stage2/personal",
            _personal_payload("cookie-missing"),
        )
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()

    assert ok_status == 200
    assert ok_body["ok"] is True
    assert missing_status == 401
    assert missing_body["error"]["code"] == "authentication_required"
    assert tokens == ["cookie-token"]
