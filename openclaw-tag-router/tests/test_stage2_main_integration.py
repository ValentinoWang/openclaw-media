from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from uuid import uuid4

import pytest

from openclaw_app.account.auth import AccountSession
from openclaw_app.adapters.stage2_http_api import (
    Stage2HttpAuthority,
    Stage2HttpError,
    authenticate_stage2_request,
    extract_stage2_credential,
    normalize_stage2_operation,
)
from openclaw_app.services.stage2_main_composition import (
    Stage2ProductionAssemblyError,
    StrictStage2Gateway,
    load_stage2_contract_identity,
)


class FakeAuth:
    def __init__(self, token: str = "t" * 32) -> None:
        self.token = token
        self.session = AccountSession(
            session_id=uuid4(),
            user_id=uuid4(),
            tenant_id=uuid4(),
            username="acceptance-user",
            email=None,
            role="user",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )

    def resolve_session(self, token: str):
        return self.session if token == self.token else None

    def verify_csrf(self, token: str, supplied: str) -> bool:
        return token == self.token and supplied == "csrf-ok"


def headers(**values: str) -> Message:
    result = Message()
    for name, value in values.items():
        result[name.replace("_", "-")] = value
    return result


def test_transport_rejects_duplicate_and_mixed_credentials() -> None:
    duplicate = Message()
    duplicate.add_header("Authorization", "Bearer " + "a" * 32)
    duplicate.add_header("Authorization", "Bearer " + "b" * 32)
    with pytest.raises(Stage2HttpError) as caught:
        extract_stage2_credential(duplicate)
    assert caught.value.code == "authentication_invalid"

    mixed = headers(
        Authorization="Bearer " + "a" * 32,
        Cookie="openclaw_session=" + "b" * 32,
    )
    with pytest.raises(Stage2HttpError) as caught:
        extract_stage2_credential(mixed)
    assert caught.value.code == "authentication_ambiguous"


def test_cookie_auth_requires_same_origin_and_current_csrf() -> None:
    auth = FakeAuth()
    authority = Stage2HttpAuthority("http://127.0.0.1:8892")
    with pytest.raises(Stage2HttpError) as caught:
        authenticate_stage2_request(
            headers(Cookie=f"openclaw_session={auth.token}"),
            account_auth=auth,  # type: ignore[arg-type]
            authority=authority,
        )
    assert caught.value.code == "csrf_rejected"

    accepted = authenticate_stage2_request(
        headers(
            Cookie=f"openclaw_session={auth.token}",
            Origin="http://127.0.0.1:8892",
            X_OpenClaw_CSRF="csrf-ok",
        ),
        account_auth=auth,  # type: ignore[arg-type]
        authority=authority,
    )
    assert accepted.credential_kind == "cookie"
    assert accepted.session.tenant_id == auth.session.tenant_id


def test_idempotency_header_is_canonical_and_body_conflicts_fail_closed() -> None:
    request_headers = headers(Idempotency_Key="acceptance-op-01")
    normalized = normalize_stage2_operation(
        {"operationId": "acceptance-op-01", "title": "Draft"}, request_headers
    )
    assert normalized["operation_id"] == "acceptance-op-01"
    assert normalized["idempotency_key"] == "acceptance-op-01"
    assert "operationId" not in normalized

    with pytest.raises(Stage2HttpError) as caught:
        normalize_stage2_operation(
            {"operation_id": "different-op", "title": "Draft"}, request_headers
        )
    assert caught.value.code == "idempotency_conflict"


def test_strict_gateway_rejects_alias_ambiguity_before_dispatch() -> None:
    class Delegate:
        calls = 0

        def run(self, mode, payload):
            self.calls += 1
            return {"mode": mode, "payload": payload}

    delegate = Delegate()
    gateway = StrictStage2Gateway(delegate)
    with pytest.raises(Exception) as caught:
        gateway.run("personal", {"operation_id": "op-1", "operationId": "op-1"})
    assert getattr(caught.value, "code", None) == "invalid_request"
    assert delegate.calls == 0


def test_provisional_contract_is_acceptance_only() -> None:
    contract = (
        Path(__file__).resolve().parents[1]
        / "openclaw_app"
        / "contracts"
        / "stage2_writer_contract.json"
    )
    identity = load_stage2_contract_identity(contract, acceptance_mode=True)
    assert identity.status == "provisional"
    assert identity.runtime_integration is False
    with pytest.raises(Stage2ProductionAssemblyError) as caught:
        load_stage2_contract_identity(contract, acceptance_mode=False)
    assert caught.value.code == "production_contract_not_accepted"
