from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from openclaw_app.adapters.http_api import make_server
from openclaw_app.services.stage2_context import (
    CapabilityEffect,
    CapabilityEffectRegistry,
    ORGANIZATION_AUTHORITY_MODE,
    PERSONAL_AUTHORITY_MODE,
)
from openclaw_app.services.stage2_external_document import (
    ExternalReadbackOutcome,
    ExternalWriteOutcome,
)
from openclaw_app.services.stage2_gateway import Stage2GatewayError
from openclaw_app.services.stage2_production import (
    SQLiteStage2ReceiptStore,
    Stage2ProductionAssemblyError,
    Stage2ProductionDependencies,
    build_stage2_production_gateway,
)
from openclaw_app.services.stage2_runtime import IdempotencyConflict, IdempotencyInProgress


PERSONAL_A = "11111111-1111-4111-8111-111111111111"
PERSONAL_B = "22222222-2222-4222-8222-222222222222"
ORGANIZATION = "33333333-3333-4333-8333-333333333333"
CAPABILITY = "stage2_document_writer"


class _PersonalWriter:
    def __init__(self) -> None:
        self.calls = 0

    def write(self, context, content, capability_id, idempotency_key, context_receipt=None):
        self.calls += 1
        return {
            "status": "succeeded",
            "artifact_ref": f"personal-{context.tenant_id}-{idempotency_key}",
            "remote_ref": None,
            "registration": {"status": "registered"},
            "readback": {"status": "confirmed"},
        }


class _BlockingPersonalWriter(_PersonalWriter):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def write(self, *args, **kwargs):
        self.entered.set()
        if not self.release.wait(timeout=3):
            raise RuntimeError("blocking writer was not released")
        return super().write(*args, **kwargs)


class _OrganizationAdapter:
    def __init__(self) -> None:
        self.write_calls = 0
        self.readback_calls = 0

    def write(self, request):
        self.write_calls += 1
        binding = request.binding
        return ExternalWriteOutcome(
            "succeeded",
            "organization-document-1",
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


def _registry() -> CapabilityEffectRegistry:
    return CapabilityEffectRegistry(
        (
            CapabilityEffect(
                capability_id=CAPABILITY,
                document_side_effect=True,
                allowed_authority_modes=frozenset(
                    {PERSONAL_AUTHORITY_MODE, ORGANIZATION_AUTHORITY_MODE}
                ),
                readback_required=True,
                source_kinds=frozenset(
                    {"personal_material", "organization_material"}
                ),
            ),
        )
    )


def _session_loader(token: str):
    records = {
        "personal-a": {
            "sessionId": "session-a",
            "userId": "user-a",
            "tenantId": PERSONAL_A,
            "tenantType": "personal",
            "memberTenantId": PERSONAL_A,
        },
        "personal-b": {
            "sessionId": "session-b",
            "userId": "user-b",
            "tenantId": PERSONAL_B,
            "tenantType": "personal",
            "memberTenantId": PERSONAL_B,
        },
        "organization": {
            "sessionId": "session-org",
            "userId": "user-org",
            "tenantId": ORGANIZATION,
            "tenantType": "organization",
            "memberTenantId": ORGANIZATION,
            "bindingGeneration": 4,
        },
    }
    return records.get(token)


def _binding_loader(tenant_id: str):
    if tenant_id != ORGANIZATION:
        return None
    return {
        "bindingId": "binding-4",
        "tenantId": tenant_id,
        "generation": 4,
        "status": "active",
        "credentialGeneration": "credential-4",
        "trustedOpenUrl": "https://feishu.cn/docx/organization-document-1",
    }


def _profile_loader(tenant_id: str, tenant_type: str):
    return {
        "tenantId": tenant_id,
        "tenantType": tenant_type,
        "revision": "profile-1",
        "fields": {"displayName": "Tenant"},
    }


def _source_loader(tenant_id: str, workspace_mode: str, source_kinds: tuple[str, ...]):
    if workspace_mode == "personal_web":
        row = {
            "sourceId": f"personal-source-{tenant_id}",
            "sourceKind": "personal_material",
            "tenantId": tenant_id,
            "workspaceMode": workspace_mode,
            "bodyAuthority": "internal",
            "payload": {"title": "Personal source"},
        }
    else:
        row = {
            "sourceId": "organization-source",
            "sourceKind": "organization_material",
            "tenantId": tenant_id,
            "workspaceMode": workspace_mode,
            "bodyAuthority": "lark",
            "bindingId": "binding-4",
            "bindingGeneration": 4,
            "bindingTenantId": tenant_id,
            "payload": {"title": "Organization source"},
        }
    return [row] if row["sourceKind"] in source_kinds else []


def _dependencies(
    database: Path | str,
    writer: _PersonalWriter,
    adapter: _OrganizationAdapter,
) -> Stage2ProductionDependencies:
    return Stage2ProductionDependencies(
        capability_id=CAPABILITY,
        effect_registry=_registry(),
        state_database_path=database,
        session_loader=_session_loader,
        binding_loader=_binding_loader,
        profile_loader=_profile_loader,
        source_loader=_source_loader,
        personal_writer=writer,
        organization_adapter=adapter,
    )


def _personal_payload(operation_id: str) -> dict[str, object]:
    return {
        "operationId": operation_id,
        "title": "Personal draft",
        "body": "Body",
        "topic": "Topic",
        "target": "Audience",
        "confirmedBy": "user-confirmation",
        "confirmationRef": "confirmation-1",
    }


def _organization_payload(operation_id: str) -> dict[str, object]:
    return {
        "operationId": operation_id,
        "title": "Organization draft",
        "body": "Body",
    }


class _App:
    settings: dict[str, object] = {}

    def __init__(self, gateway) -> None:
        self.gateway = gateway

    def process_stage2(self, mode: str, payload: dict[str, object]):
        return self.gateway.run(mode, payload)


def _post(server, path: str, payload: dict[str, object], headers: dict[str, str]):
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_sqlite_runtime_receipts_are_restart_safe_and_conflict_atomically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stage2.sqlite3"
    first = SQLiteStage2ReceiptStore(path)
    second = SQLiteStage2ReceiptStore(path)
    first.put("key", "fingerprint-a", {"ok": True})

    assert second.get("key") == {
        "request_fingerprint": "fingerprint-a",
        "response": {"ok": True},
    }
    second.put("key", "fingerprint-a", {"ok": True})
    with pytest.raises(IdempotencyConflict):
        second.put("key", "fingerprint-b", {"ok": True})
    with pytest.raises(IdempotencyConflict):
        second.put("key", "fingerprint-a", {"ok": False})


def test_sqlite_runtime_receipt_schema_migrates_claim_table_additively(
    tmp_path: Path,
) -> None:
    path = tmp_path / "schema-v1.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE stage2_runtime_meta (schema_version INTEGER NOT NULL);
        INSERT INTO stage2_runtime_meta(schema_version) VALUES (1);
        CREATE TABLE stage2_runtime_receipts (
            receipt_key TEXT PRIMARY KEY,
            request_fingerprint TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    connection.commit()
    connection.close()

    store = SQLiteStage2ReceiptStore(path)
    with sqlite3.connect(path) as migrated:
        assert migrated.execute(
            "SELECT schema_version FROM stage2_runtime_meta"
        ).fetchone() == (3,)
        assert migrated.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stage2_runtime_claims'"
        ).fetchone() == ("stage2_runtime_claims",)
        assert "lease_until" in {
            row[1] for row in migrated.execute("PRAGMA table_info(stage2_runtime_claims)")
        }
    assert store.get("missing") is None


def test_sqlite_runtime_claim_blocks_duplicate_before_external_writer(
    tmp_path: Path,
) -> None:
    database = tmp_path / "claim.sqlite3"
    first_writer = _BlockingPersonalWriter()
    first_gateway = build_stage2_production_gateway(
        _dependencies(database, first_writer, _OrganizationAdapter())
    )
    second_writer = _PersonalWriter()
    second_gateway = build_stage2_production_gateway(
        _dependencies(database, second_writer, _OrganizationAdapter())
    )
    from openclaw_app.services.stage2_server_context import stage2_request_context

    request = {"headers": {"Authorization": "Bearer personal-a"}, "cookies": {}}

    def run_first():
        with stage2_request_context(request):
            return first_gateway.run("personal", _personal_payload("claim-op"))

    def run_second():
        with stage2_request_context(request):
            return second_gateway.run("personal", _personal_payload("claim-op"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(run_first)
        assert first_writer.entered.wait(timeout=3)
        second_future = pool.submit(run_second)
        with pytest.raises(IdempotencyInProgress):
            second_future.result(timeout=3)
        first_writer.release.set()
        first = first_future.result(timeout=3)

    assert first["artifactStatus"] == "readback_verified"
    assert first_writer.calls == 1
    assert second_writer.calls == 0


def test_sqlite_runtime_claim_reclaims_expired_same_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "expired-claim.sqlite3"
    store = SQLiteStage2ReceiptStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO stage2_runtime_claims(receipt_key, request_fingerprint, lease_until) VALUES (?, ?, ?)",
            ("expired", "fingerprint-a", 0),
        )
    assert store.claim("expired", "fingerprint-a") is None
    with pytest.raises(IdempotencyInProgress):
        store.claim("expired", "fingerprint-a")
    with pytest.raises(IdempotencyConflict):
        store.claim("expired", "fingerprint-b")


def test_production_factory_rejects_volatile_state_and_missing_capability() -> None:
    writer = _PersonalWriter()
    adapter = _OrganizationAdapter()
    with pytest.raises(Stage2ProductionAssemblyError) as volatile:
        build_stage2_production_gateway(_dependencies(":memory:", writer, adapter))
    assert volatile.value.code == "volatile_store_forbidden"

    dependencies = _dependencies("unused.sqlite3", writer, adapter)
    invalid = Stage2ProductionDependencies(
        **{
            field: getattr(dependencies, field)
            for field in dependencies.__dataclass_fields__
            if field != "capability_id"
        },
        capability_id="unregistered",
    )
    with pytest.raises(Stage2ProductionAssemblyError) as capability:
        build_stage2_production_gateway(invalid)
    assert capability.value.code == "capability_not_registered"


def test_production_http_uses_request_bearer_and_replays_outer_receipt_after_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "production.sqlite3"
    first_writer = _PersonalWriter()
    first_gateway = build_stage2_production_gateway(
        _dependencies(database, first_writer, _OrganizationAdapter())
    )
    server = make_server("127.0.0.1", 0, _App(first_gateway))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, first = _post(
            server,
            "/stage2/personal",
            _personal_payload("restart-personal"),
            {"Authorization": "Bearer personal-a"},
        )
        forged_status, forged = _post(
            server,
            "/stage2/personal",
            {**_personal_payload("forged"), "session": "personal-a"},
            {},
        )
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()

    second_writer = _PersonalWriter()
    second_gateway = build_stage2_production_gateway(
        _dependencies(database, second_writer, _OrganizationAdapter())
    )
    second_server = make_server("127.0.0.1", 0, _App(second_gateway))
    second_thread = threading.Thread(target=second_server.serve_forever, daemon=True)
    second_thread.start()
    try:
        replay_status, replay = _post(
            second_server,
            "/stage2/personal",
            _personal_payload("restart-personal"),
            {"Cookie": "openclaw_session=personal-a"},
        )
    finally:
        second_server.shutdown()
        second_thread.join(timeout=3)
        second_server.server_close()

    assert status == 200
    assert replay_status == 200
    assert first["receipt"]["receiptDigest"] == replay["receipt"]["receiptDigest"]
    assert replay["receipt"]["replayed"] is True
    assert first_writer.calls == 1
    assert second_writer.calls == 0
    assert forged_status == 400
    assert forged["error"]["code"] == "authority_override"


def test_production_gateway_rejects_transport_source_rows(tmp_path: Path) -> None:
    gateway = build_stage2_production_gateway(
        _dependencies(
            tmp_path / "source-override.sqlite3",
            _PersonalWriter(),
            _OrganizationAdapter(),
        )
    )

    from openclaw_app.services.stage2_server_context import stage2_request_context

    with stage2_request_context(
        {"headers": {"Authorization": "Bearer personal-a"}, "cookies": {}}
    ):
        with pytest.raises(Stage2GatewayError) as error:
            gateway.run(
                "personal",
                {
                    **_personal_payload("source-override"),
                    "sourceRows": [
                        {
                            "sourceId": "forged",
                            "sourceKind": "personal_material",
                            "tenantId": PERSONAL_A,
                            "workspaceMode": "personal_web",
                            "bodyAuthority": "internal",
                            "payload": {"forged": True},
                        }
                    ],
                },
            )

    assert error.value.code == "authority_override"


def test_production_http_authentication_fails_closed_and_request_tokens_do_not_leak(
    tmp_path: Path,
) -> None:
    barrier = threading.Barrier(2)

    def concurrent_session_loader(token: str):
        barrier.wait(timeout=3)
        return _session_loader(token)

    writer = _PersonalWriter()
    dependencies = replace(
        _dependencies(tmp_path / "concurrent.sqlite3", writer, _OrganizationAdapter()),
        session_loader=concurrent_session_loader,
    )
    server = make_server(
        "127.0.0.1",
        0,
        _App(build_stage2_production_gateway(dependencies)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            bearer = pool.submit(
                _post,
                server,
                "/stage2/personal",
                _personal_payload("concurrent-a"),
                {"Authorization": "Bearer personal-a"},
            )
            cookie = pool.submit(
                _post,
                server,
                "/stage2/personal",
                _personal_payload("concurrent-b"),
                {"Cookie": "openclaw_session=personal-b"},
            )
            bearer_status, bearer_body = bearer.result(timeout=5)
            cookie_status, cookie_body = cookie.result(timeout=5)

        missing_status, missing = _post(
            server,
            "/stage2/personal",
            _personal_payload("missing-auth"),
            {},
        )
        malformed_status, malformed = _post(
            server,
            "/stage2/personal",
            _personal_payload("malformed-auth"),
            {
                "Authorization": "Basic attacker",
                "Cookie": "openclaw_session=personal-a",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()

    assert bearer_status == 200
    assert cookie_status == 200
    assert bearer_body["receipt"]["tenantId"] == PERSONAL_A
    assert cookie_body["receipt"]["tenantId"] == PERSONAL_B
    assert missing_status == 401
    assert missing["error"]["code"] == "authentication_required"
    assert malformed_status == 401
    assert malformed["error"]["code"] == "authentication_invalid"
    assert writer.calls == 2


def test_production_receipts_are_isolated_by_tenant_and_route(tmp_path: Path) -> None:
    database = tmp_path / "isolated.sqlite3"
    writer = _PersonalWriter()
    adapter = _OrganizationAdapter()
    gateway = build_stage2_production_gateway(
        _dependencies(database, writer, adapter)
    )

    from openclaw_app.services.stage2_server_context import stage2_request_context

    with stage2_request_context(
        {"headers": {"Authorization": "Bearer personal-a"}, "cookies": {}}
    ):
        first = gateway.run("personal", _personal_payload("shared-operation"))
    with stage2_request_context(
        {"headers": {"Authorization": "Bearer personal-b"}, "cookies": {}}
    ):
        second = gateway.run("personal", _personal_payload("shared-operation"))
    with stage2_request_context(
        {"headers": {"Authorization": "Bearer organization"}, "cookies": {}}
    ):
        organization = gateway.run(
            "organization",
            _organization_payload("shared-operation"),
        )

    assert first["tenantId"] == PERSONAL_A
    assert second["tenantId"] == PERSONAL_B
    assert organization["tenantId"] == ORGANIZATION
    assert writer.calls == 2
    assert adapter.write_calls == 1


def test_organization_outer_receipt_replays_after_restart(tmp_path: Path) -> None:
    database = tmp_path / "organization.sqlite3"
    first_adapter = _OrganizationAdapter()
    first_gateway = build_stage2_production_gateway(
        _dependencies(database, _PersonalWriter(), first_adapter)
    )

    from openclaw_app.services.stage2_server_context import stage2_request_context

    request = {"headers": {"Authorization": "Bearer organization"}, "cookies": {}}
    with stage2_request_context(request):
        first = first_gateway.run("organization", _organization_payload("restart-org"))

    second_adapter = _OrganizationAdapter()
    second_gateway = build_stage2_production_gateway(
        _dependencies(database, _PersonalWriter(), second_adapter)
    )
    with stage2_request_context(request):
        replay = second_gateway.run("organization", _organization_payload("restart-org"))

    assert replay["replayed"] is True
    assert replay["receiptDigest"] == first["receiptDigest"]
    assert first_adapter.write_calls == 1
    assert second_adapter.write_calls == 0
