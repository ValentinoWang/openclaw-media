#!/usr/bin/env python3
"""Browser-level verification for the Stage-2 HTTP routes.

This tool deliberately produces VERIFIED evidence only. It never changes an
SSOT node to ACCEPTED. Use --base-url against a deployed gateway; --fixture is
an isolated injected gateway for repeatable candidate regression.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Browser, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PERSONAL_TENANT = "11111111-1111-4111-8111-111111111111"
ORGANIZATION_TENANT = "22222222-2222-4222-8222-222222222222"
PERSONAL_TOKEN = "stage2-personal-session"
ORGANIZATION_TOKEN = "stage2-organization-session"


def _personal_sources() -> list[dict[str, Any]]:
    return [
        {
            "sourceId": "material-1",
            "sourceKind": "personal_material",
            "tenantId": PERSONAL_TENANT,
            "workspaceMode": "personal_web",
            "bodyAuthority": "internal",
            "payload": {"title": "Browser verification material"},
        }
    ]


def _organization_sources() -> list[dict[str, Any]]:
    return [
        {
            "sourceId": "brand-1",
            "sourceKind": "organization_material",
            "tenantId": ORGANIZATION_TENANT,
            "workspaceMode": "organization_lark",
            "bodyAuthority": "lark",
            "bindingId": "binding-org",
            "bindingGeneration": 5,
            "binding": {"tenantId": ORGANIZATION_TENANT},
            "payload": {"tone": "direct"},
        }
    ]


class _PersonalWriter:
    def write(self, context, content, capability_id, idempotency_key, context_receipt=None):
        return {
            "status": "succeeded",
            "artifact_ref": "browser-personal-artifact",
            "remote_ref": None,
            "registration": {"status": "registered"},
            "readback": {"status": "confirmed"},
        }


class _OrganizationAdapter:
    def write(self, request):
        from openclaw_app.services.stage2_external_document import ExternalWriteOutcome

        binding = request.binding
        return ExternalWriteOutcome(
            "succeeded",
            "browser-org-document",
            "1",
            binding.tenant_id,
            binding.binding_id,
            binding.binding_generation,
            request.content_digest,
        )

    def readback(self, request, write):
        from openclaw_app.services.stage2_external_document import ExternalReadbackOutcome

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


def _fixture_server():
    from openclaw_app.adapters.http_api import make_server
    from openclaw_app.services.stage2_context import DOCUMENT_WRITER_FIXTURE_ID
    from openclaw_app.services.stage2_gateway import Stage2Gateway
    from openclaw_app.services.stage2_runtime import Stage2Runtime
    from openclaw_app.services.stage2_server_context import (
        AuthenticatedSessionProvider,
        CurrentBindingProvider,
        ServerStage2ContextProviders,
        TenantProfileReader,
        current_request_session_token,
    )

    sessions = {
        PERSONAL_TOKEN: {
            "sessionId": "browser-personal-session",
            "userId": "browser-personal-user",
            "tenantId": PERSONAL_TENANT,
            "tenantType": "personal",
            "memberTenantId": PERSONAL_TENANT,
            "status": "active",
            "memberStatus": "active",
            "tenantStatus": "active",
        },
        ORGANIZATION_TOKEN: {
            "sessionId": "browser-organization-session",
            "userId": "browser-organization-user",
            "tenantId": ORGANIZATION_TENANT,
            "tenantType": "organization",
            "memberTenantId": ORGANIZATION_TENANT,
            "bindingGeneration": 5,
            "status": "active",
            "memberStatus": "active",
            "tenantStatus": "active",
        },
    }

    session_provider = AuthenticatedSessionProvider(
        lambda token: sessions.get(token),
        current_request_session_token,
    )
    context_providers = ServerStage2ContextProviders(
        session_provider,
        CurrentBindingProvider(
            lambda tenant_id: {
                "bindingId": "binding-org",
                "tenantId": tenant_id,
                "generation": 5,
                "status": "active",
                "credentialGeneration": "credential-9",
                "trustedOpenUrl": "https://feishu.cn/docx/browser-verification",
            }
            if tenant_id == ORGANIZATION_TENANT
            else None
        ),
        TenantProfileReader(
            lambda tenant_id, tenant_type: {
                "tenantId": tenant_id,
                "tenantType": tenant_type,
                "revision": "browser-1",
                "fields": {"verification": True},
            }
        ),
    )
    runtime = Stage2Runtime(
        personal_writer=_PersonalWriter(),
        organization_adapter=_OrganizationAdapter(),
    )
    gateway = Stage2Gateway(
        runtime,
        capability_id=DOCUMENT_WRITER_FIXTURE_ID,
        personal_session_provider=context_providers.personal_session,
        organization_context_provider=context_providers.organization_context,
        allow_transport_sources=True,
    )

    class _App:
        settings = {"content_flow": {}, "feishu": {}, "mac_agent": {}}

        def process_stage2(self, mode: str, payload: dict[str, Any]) -> dict[str, Any]:
            return gateway.run(mode, payload)

    server = make_server("127.0.0.1", 0, _App())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _browser_post(page: Page, base_url: str, path: str, payload: dict[str, Any], token: str | None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return page.evaluate(
        """
        async ({url, payload, headers}) => {
          const response = await fetch(url, {
            method: 'POST',
            headers,
            body: JSON.stringify(payload),
          });
          return {status: response.status, body: await response.json()};
        }
        """,
        {"url": f"{base_url}{path}", "payload": payload, "headers": headers},
    )


def _personal_payload(operation_id: str, *, include_sources: bool) -> dict[str, Any]:
    payload = {
        "operation_id": operation_id,
        # Keep each deployed run's first write content-unique. The replay
        # request reuses this exact payload, while a later run must not collide
        # with a durable artifact_ref from an earlier external write.
        "title": f"Browser personal draft {operation_id}",
        "body": f"Browser verification body {operation_id}",
        "topic": "Browser verification",
        "target": "verification user",
        "confirmed_by": "browser-verifier",
        "confirmation_ref": "browser-confirmation",
    }
    if include_sources:
        payload["sources"] = _personal_sources()
    return payload


def _organization_payload(operation_id: str, *, include_sources: bool) -> dict[str, Any]:
    payload = {
        "operation_id": operation_id,
        "title": f"Browser organization draft {operation_id}",
        "body": f"Browser organization verification body {operation_id}",
    }
    if include_sources:
        payload["sources"] = _organization_sources()
    return payload


def _assert_case(name: str, response: dict[str, Any], expected_status: int, expected_code: str | None = None) -> dict[str, Any]:
    status = int(response.get("status", -1))
    body = response.get("body")
    if status != expected_status:
        raise AssertionError(f"{name}: expected HTTP {expected_status}, got {status}: {body!r}")
    if expected_code is not None:
        actual = ((body or {}).get("error") or {}).get("code")
        if actual != expected_code:
            raise AssertionError(f"{name}: expected error {expected_code}, got {actual}: {body!r}")
    return {"name": name, "status": status, "passed": True, "body": body}


def _assert_success_receipt(name: str, response: dict[str, Any], route: str) -> dict[str, Any]:
    case = _assert_case(name, response, 200)
    receipt = (case["body"] or {}).get("receipt")
    if not isinstance(receipt, dict):
        raise AssertionError(f"{name}: success response has no receipt")
    if receipt.get("route") != route:
        raise AssertionError(f"{name}: route mismatch: {receipt!r}")
    if receipt.get("artifactStatus") != "readback_verified":
        raise AssertionError(f"{name}: artifact was not readback verified: {receipt!r}")
    if receipt.get("error") is not None:
        raise AssertionError(f"{name}: receipt contains an error: {receipt!r}")
    artifact_state = receipt.get("artifactState")
    if not isinstance(artifact_state, dict) or artifact_state.get("status") != "readback_verified":
        raise AssertionError(f"{name}: artifact state was not readback verified: {receipt!r}")
    if artifact_state.get("error_code") is not None:
        raise AssertionError(f"{name}: artifact state contains an error: {receipt!r}")
    if not isinstance(receipt.get("contextReceipt"), dict):
        raise AssertionError(f"{name}: context readback receipt is missing")
    return case


def verify(
    base_url: str,
    *,
    executable_path: str | None,
    fixture: bool,
    evidence_out: Path,
    host_resolver_rules: str | None = None,
    ignore_https_errors: bool = False,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    server = thread = None
    if fixture:
        server, thread = _fixture_server()
        base_url = f"http://127.0.0.1:{server.server_port}"
    base_url = base_url.rstrip("/")
    route_prefix = urlsplit(base_url).path.rstrip("/") == "/stage2"

    def route(path: str) -> str:
        return path if route_prefix else f"/stage2{path}"

    try:
        with sync_playwright() as playwright:
            launch_args: dict[str, Any] = {"headless": True}
            if executable_path:
                launch_args["executable_path"] = executable_path
            if host_resolver_rules:
                launch_args["args"] = [
                    f"--host-resolver-rules={host_resolver_rules}",
                    "--no-proxy-server",
                ]
            browser: Browser = playwright.chromium.launch(**launch_args)
            context = browser.new_context(ignore_https_errors=ignore_https_errors)
            page = context.new_page()
            health = page.goto(f"{base_url}/healthz", wait_until="domcontentloaded")
            if health is None or health.status != 200:
                raise AssertionError(f"healthz failed: {health.status if health else None}")
            cases.append({"name": "healthz", "status": health.status, "passed": True})

            ready = page.goto(f"{base_url}/readyz", wait_until="domcontentloaded")
            if ready is None or ready.status != 200:
                raise AssertionError(f"readyz failed: {ready.status if ready else None}")
            cases.append({"name": "readyz", "status": ready.status, "passed": True})

            include_sources = fixture
            operation_prefix = "fixture" if fixture else "deployed"
            run_id = uuid.uuid4().hex[:12]
            personal_operation_id = f"browser-{operation_prefix}-personal-{run_id}"
            organization_operation_id = f"browser-{operation_prefix}-organization-{run_id}"
            personal = _browser_post(
                page, base_url, route("/personal"), _personal_payload(personal_operation_id, include_sources=include_sources), PERSONAL_TOKEN if fixture else os.getenv("STAGE2_PERSONAL_TOKEN")
            )
            cases.append(_assert_success_receipt("personal_success", personal, "personal_web/internal"))
            personal_receipt = personal["body"]["receipt"]

            replay = _browser_post(
                page, base_url, route("/personal"), _personal_payload(personal_operation_id, include_sources=include_sources), PERSONAL_TOKEN if fixture else os.getenv("STAGE2_PERSONAL_TOKEN")
            )
            replay_case = _assert_case("personal_idempotent_replay", replay, 200)
            replay_receipt = replay["body"].get("receipt")
            replay_case["same_receipt_digest"] = replay_receipt.get("receiptDigest") == personal_receipt.get("receiptDigest")
            replay_case["replayed"] = replay_receipt.get("replayed") is True
            if not replay_case["same_receipt_digest"] or not replay_case["replayed"]:
                raise AssertionError(f"personal replay receipt is not a replay: {replay_receipt!r}")
            cases.append(replay_case)

            authority = _browser_post(
                page,
                base_url,
                route("/personal"),
                {**_personal_payload(f"browser-{operation_prefix}-authority-negative-{run_id}", include_sources=include_sources), "tenantId": ORGANIZATION_TENANT},
                PERSONAL_TOKEN if fixture else os.getenv("STAGE2_PERSONAL_TOKEN"),
            )
            cases.append(_assert_case("personal_authority_negative", authority, 400, "authority_override"))

            organization = _browser_post(
                page, base_url, route("/organization"), _organization_payload(organization_operation_id, include_sources=include_sources), ORGANIZATION_TOKEN if fixture else os.getenv("STAGE2_ORGANIZATION_TOKEN")
            )
            cases.append(_assert_success_receipt("organization_success", organization, "organization_lark/lark"))
            organization_receipt = organization["body"]["receipt"]

            binding = _browser_post(
                page,
                base_url,
                route("/organization"),
                {**_organization_payload(f"browser-{operation_prefix}-binding-negative-{run_id}", include_sources=include_sources), "bindingId": "attacker-binding"},
                ORGANIZATION_TOKEN if fixture else os.getenv("STAGE2_ORGANIZATION_TOKEN"),
            )
            cases.append(_assert_case("organization_authority_negative", binding, 400, "authority_override"))

            context.close()
            browser.close()
    finally:
        if server is not None:
            server.shutdown()
            if thread is not None:
                thread.join(timeout=3)
            server.server_close()

    result = {
        "schemaVersion": "stage2.playwright.verify.v1",
        "verification": "VERIFIED",
        "formalAcceptance": "NOT_ACCEPTED",
        "evidenceLevel": "browser-fixture" if fixture else "browser-deployed",
        "environmentIdentity": "stage2-playwright-fixture" if fixture else base_url,
        "baseUrl": base_url,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
        "notes": [
            "Playwright browser execution verifies HTTP behavior and negative authority cases.",
            "This receipt is not an SSOT ACCEPTED receipt and does not promote a node.",
            "Production mode requires STAGE2_PERSONAL_TOKEN and STAGE2_ORGANIZATION_TOKEN.",
        ],
    }
    evidence_out.parent.mkdir(parents=True, exist_ok=True)
    evidence_out.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("STAGE2_BASE_URL"), help="deployed Stage-2 HTTP base URL")
    parser.add_argument("--fixture", action="store_true", help="run an isolated injected gateway fixture")
    parser.add_argument("--executable-path", default=os.getenv("PLAYWRIGHT_EXECUTABLE_PATH"), help="Chromium executable path")
    parser.add_argument("--host-resolver-rules", default=os.getenv("PLAYWRIGHT_HOST_RESOLVER_RULES"), help="optional Chromium host resolver rules for a controlled gateway test")
    parser.add_argument("--ignore-https-errors", action="store_true", help="allow a locally terminated test certificate")
    parser.add_argument(
        "--evidence-out",
        default=None,
    )
    args = parser.parse_args()
    if not args.fixture and not args.base_url:
        parser.error("--base-url or --fixture is required")
    evidence_out = Path(args.evidence_out) if args.evidence_out else ROOT / "agents-results/2026-08-19/media-c-b-stage-2-content-ai-document-routing" / ("evidence-stage2-playwright-fixture.json" if args.fixture else "evidence-stage2-playwright-deployed.json")
    result = verify(
        args.base_url or "",
        executable_path=args.executable_path,
        fixture=args.fixture,
        evidence_out=evidence_out,
        host_resolver_rules=args.host_resolver_rules,
        ignore_https_errors=args.ignore_https_errors,
    )
    print(json.dumps({"verification": result["verification"], "cases": len(result["cases"]), "evidence": str(evidence_out)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
