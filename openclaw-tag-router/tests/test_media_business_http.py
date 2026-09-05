from __future__ import annotations

import base64
import hashlib
import http.client
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from openclaw_app.account import AccountSession
from openclaw_app.adapters.http_api import AuthConfig, HttpAuthorityConfig, make_server
from openclaw_app.adapters.media_business_dispatcher import (
    MEDIA_BUSINESS_ROUTE_BINDINGS,
    MediaBusinessDispatcher,
)
from openclaw_app.services.media_business.documents import UnsupportedDocumentBlock


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ADMIN_ID = UUID("22222222-2222-4222-8222-222222222222")
ADMIN_TENANT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class _Auth:
    def __init__(self) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        self.sessions = {
            "user-token": AccountSession(
                UUID(int=1), USER_ID, TENANT_ID, "user", "user@example.com", "user", expires_at
            ),
            "admin-token": AccountSession(
                UUID(int=2), ADMIN_ID, ADMIN_TENANT_ID, "admin", "admin@example.com", "admin", expires_at
            ),
            "maintainer-token": AccountSession(
                UUID(int=3), ADMIN_ID, ADMIN_TENANT_ID, "maintainer", "maintainer@example.com", "admin",
                expires_at, True,
            ),
        }

    def resolve_session(self, token: str | None) -> AccountSession | None:
        return self.sessions.get(token or "")

    @staticmethod
    def verify_csrf(token: str, supplied: str) -> bool:
        return supplied == f"csrf-{token}"

    @staticmethod
    def csrf_token(token: str) -> str:
        return f"csrf-{token}"


class _Overview:
    def __init__(self) -> None:
        self.contexts: list[Any] = []

    def get_dashboard(self, context: Any) -> dict[str, Any]:
        self.contexts.append(context)
        return {"tenantId": context.tenant_id}


class _Tracks:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_track(self, context: Any, public_track_id: str) -> dict[str, Any]:
        self.calls.append({"context": context, "public_track_id": public_track_id})
        return {"item": {"publicTrackId": public_track_id}}


class _Decisions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def confirm_decision(
        self,
        context: Any,
        public_decision_id: str,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "context": context,
                "public_decision_id": public_decision_id,
                "request": request,
                "idempotency_key": idempotency_key,
            }
        )
        return {"confirmed": public_decision_id}


class _AdminTenants:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_admin_tenant(
        self,
        context: Any,
        public_tenant_id: str,
        audit_reason: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {"context": context, "public_tenant_id": public_tenant_id, "audit_reason": audit_reason}
        )
        return {"tenantId": public_tenant_id}


class _Tasks:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def cancel_task(
        self, task_id: str, *, tenant_id: str, user_public_id: str | None = None
    ) -> dict[str, Any]:
        del user_public_id
        self.calls.append({"operation": "cancel", "task_id": task_id, "tenant_id": tenant_id})
        return {"taskId": task_id, "status": "cancelled"}

    def confirm_task(
        self,
        task_id: str,
        payload: dict[str, Any],
        *,
        tenant_id: str,
        user_public_id: str | None = None,
    ) -> dict[str, Any]:
        del user_public_id
        self.calls.append(
            {
                "operation": "confirm",
                "task_id": task_id,
                "tenant_id": tenant_id,
                "payload": payload,
            }
        )
        status = "cancelled" if payload["decision"] == "reject" else "queued"
        return {"taskId": task_id, "status": status}


class MediaBusinessHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = _Auth()
        self.overview = _Overview()
        self.tracks = _Tracks()
        self.decisions = _Decisions()
        self.admin_tenants = _AdminTenants()
        self.tasks = _Tasks()
        self.services = {
            "overview": self.overview,
            "tracks": self.tracks,
            "assets": SimpleNamespace(),
            "decisions": self.decisions,
            "runs": SimpleNamespace(),
            "publishing": SimpleNamespace(),
            "reviews": SimpleNamespace(),
            "usage_billing": SimpleNamespace(),
            "invites": SimpleNamespace(),
            "admin_overview": SimpleNamespace(dashboard=lambda: {"admin": True}),
            "admin_access": SimpleNamespace(),
            "admin_tenants": self.admin_tenants,
            "admin_billing": SimpleNamespace(),
            "admin_upstreams": SimpleNamespace(),
            "admin_platform_cookies": SimpleNamespace(
                get_admin_platform_cookies=lambda: {
                    "schemaVersion": "media_web_business_pages_v2",
                    "platforms": [
                        {
                            "platform": "douyin",
                            "configured": True,
                            "updatedAt": "2026-08-09T00:00:00Z",
                            "validationStatus": "valid",
                            "errorCode": None,
                        }
                    ],
                }
            ),
            "documents": SimpleNamespace(),
        }
        self._start_server(HttpAuthorityConfig("http://127.0.0.1"))

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def _start_server(
        self,
        authority: HttpAuthorityConfig,
        *,
        dispatcher: MediaBusinessDispatcher | None = None,
    ) -> None:
        self.server = make_server(
            "127.0.0.1",
            0,
            None,
            auth_config=AuthConfig(b"s" * 48, cookie_secure=False),
            account_auth=self.auth,  # type: ignore[arg-type]
            authority_config=authority,
            media_web_tasks=self.tasks,  # type: ignore[arg-type]
            media_business_services=self.services,
            media_business_dispatcher=dispatcher,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def _restart_server(
        self,
        authority: HttpAuthorityConfig,
        *,
        dispatcher: MediaBusinessDispatcher | None = None,
    ) -> None:
        self.tearDown()
        self._start_server(authority, dispatcher=dispatcher)

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request_headers = dict(headers or {})
        if token:
            request_headers["Cookie"] = f"openclaw_session={token}"
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.request(method, path, body=encoded, headers=request_headers)
        response = connection.getresponse()
        payload = json.loads(response.read() or b"{}")
        status = response.status
        connection.close()
        return status, payload

    @staticmethod
    def _mutation_headers(token: str, key: str = "mutation-key-01") -> dict[str, str]:
        return {
            "Origin": "http://127.0.0.1",
            "X-OpenClaw-CSRF": f"csrf-{token}",
            "Idempotency-Key": key,
        }

    def test_canonical_get_composes_tenant_context_and_requires_authentication(self) -> None:
        status, body = self._request("GET", "/openclaw/media/api/dashboard", token="user-token")
        self.assertEqual((status, body), (200, {"tenantId": str(TENANT_ID)}))
        self.assertEqual(self.overview.contexts[0].tenant_id, str(TENANT_ID))

        status, body = self._request("GET", "/openclaw/media/api/dashboard")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "authentication_required")

    def test_platform_cookie_status_is_admin_only_and_redacted(self) -> None:
        status, body = self._request(
            "GET", "/openclaw/media/api/admin/platform-cookies", token="user-token"
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "admin_required")

        status, body = self._request(
            "GET", "/openclaw/media/api/admin/platform-cookies", token="admin-token"
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["platforms"][0]["validationStatus"], "valid")
        self.assertNotIn("COOKIE-", json.dumps(body))

    def test_media_session_matches_the_frozen_if2_response(self) -> None:
        # The frozen v2 session now carries the Stage-1 workspace facts the
        # Media Web frontend schema requires (workspaceMode/editorMode/...).
        for token, expected_user_id, expected_role in (
            ("user-token", USER_ID, "ordinary"),
            ("admin-token", ADMIN_ID, "admin"),
        ):
            with self.subTest(token=token):
                status, body = self._request(
                    "GET", "/openclaw/media/api/session", token=token
                )
                self.assertEqual(status, 200, body)
                self.assertEqual(
                    body,
                    {
                        "schemaVersion": "media_web_business_pages_v2",
                        "revision": 1,
                        "session": {
                            "publicUserId": str(expected_user_id),
                            "workspaceMode": "personal_web",
                            "editorMode": "web_edit",
                            "bodyAuthority": "internal",
                            "organizationName": None,
                            "memberRole": "owner",
                            "organizationConnection": "not_applicable",
                            "installationConnection": "not_applicable",
                            "role": expected_role,
                            "maintainer": False,
                            "routeGrants": (
                                [
                                    "/admin/overview",
                                    "/admin/access",
                                    "/admin/tenants",
                                    "/admin/billing",
                                    "/admin/upstreams",
                                ]
                                if expected_role == "admin"
                                else [
                                    "/today",
                                    "/studio",
                                    "/campaigns",
                                    "/business",
                                    "/desk",
                                    "/overview",
                                    "/assets",
                                    "/tracks",
                                    "/decisions",
                                    "/publishing",
                                    "/reviews",
                                    "/media-agent",
                                    "/archives",
                                    "/usage-billing",
                                    "/invites",
                                    "/workspace",
                                ]
                            ),
                            "csrfToken": f"csrf-{token}",
                            "expiresAt": self.auth.sessions[token].expires_at.isoformat(),
                            "schemaVersion": "media_web_business_pages_v2",
                        },
                    },
                )

    def test_listed_track_public_id_dispatches_to_get_track(self) -> None:
        track_id = "record_008bbc93d6"

        status, body = self._request(
            "GET", f"/openclaw/media/api/tracks/{track_id}", token="user-token"
        )

        self.assertEqual((status, body), (200, {"item": {"publicTrackId": track_id}}))
        self.assertEqual(self.tracks.calls[0]["public_track_id"], track_id)
        self.assertEqual(self.tracks.calls[0]["context"].tenant_id, str(TENANT_ID))

    def test_mutation_requires_csrf_and_idempotency_then_invokes_service(self) -> None:
        path = "/openclaw/media/api/decisions/decision_123/confirm"
        status, body = self._request(
            "POST", path, {"expectedRevision": 1}, token="user-token",
            headers={"Idempotency-Key": "mutation-key-01"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "csrf_rejected")

        status, body = self._request(
            "POST", path, {"expectedRevision": 1}, token="user-token",
            headers={"Origin": "http://127.0.0.1", "X-OpenClaw-CSRF": "csrf-user-token"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

        status, body = self._request(
            "POST", path, {"expectedRevision": 1}, token="user-token",
            headers=self._mutation_headers("user-token"),
        )
        self.assertEqual((status, body), (200, {"confirmed": "decision_123"}))
        self.assertEqual(self.decisions.calls[0]["idempotency_key"], "mutation-key-01")

    def test_upload_creation_fails_closed_on_contract_violations(self) -> None:
        status, body = self._request(
            "POST",
            "/openclaw/media/api/uploads",
            {"filename": "input.txt"},
            token="user-token",
            headers=self._mutation_headers("user-token", "upload-key-01"),
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

        status, body = self._request(
            "POST",
            "/openclaw/media/api/uploads",
            {
                "schemaVersion": "3",
                "filename": "input.txt",
                "contentBase64": "aGVsbG8=",
                "idempotencyKey": "other-key",
            },
            token="user-token",
            headers=self._mutation_headers("user-token", "upload-key-01"),
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

    def test_task_cancel_and_confirmation_dispatch_to_durable_task_state(self) -> None:
        task_id = "mwt_036a0e63c4ae458c8623f618ecb11ce2"
        status, body = self._request(
            "POST",
            f"/openclaw/media/api/tasks/{task_id}/confirm",
            {"decision": "reject", "note": ""},
            token="user-token",
            headers=self._mutation_headers("user-token", f"task-confirm-{task_id}-reject"),
        )
        self.assertEqual((status, body), (200, {"taskId": task_id, "status": "cancelled"}))
        self.assertEqual(
            self.tasks.calls[-1],
            {
                "operation": "confirm",
                "task_id": task_id,
                "tenant_id": str(TENANT_ID),
                "payload": {"decision": "reject", "note": ""},
            },
        )

        status, body = self._request(
            "POST",
            f"/openclaw/media/api/tasks/{task_id}/cancel",
            {},
            token="user-token",
            headers=self._mutation_headers("user-token", f"task-cancel-{task_id}"),
        )
        self.assertEqual((status, body), (200, {"taskId": task_id, "status": "cancelled"}))
        self.assertEqual(
            self.tasks.calls[-1],
            {"operation": "cancel", "task_id": task_id, "tenant_id": str(TENANT_ID)},
        )

    def test_role_and_maintainer_permissions_are_enforced_before_service_invocation(self) -> None:
        status, _ = self._request("GET", "/openclaw/media/api/admin/dashboard", token="user-token")
        self.assertEqual(status, 403)
        status, _ = self._request("GET", "/openclaw/media/api/dashboard", token="admin-token")
        self.assertEqual(status, 403)
        status, _ = self._request(
            "POST",
            "/openclaw/media/api/admin/upstream-credential/rotate",
            {},
            token="admin-token",
            headers=self._mutation_headers("admin-token"),
        )
        self.assertEqual(status, 403)

    def test_cross_tenant_read_requires_canonical_audit_reason(self) -> None:
        path = "/openclaw/media/api/admin/tenants/tenant_public_1"
        status, body = self._request("GET", path, token="maintainer-token")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

        reason = "approved tenant support read"
        wire = base64.urlsafe_b64encode(reason.encode()).decode().rstrip("=")
        status, body = self._request(
            "GET", path, token="maintainer-token",
            headers={"X-Audit-Reason": f"utf8-base64url-v1.{wire}"},
        )
        self.assertEqual((status, body), (200, {"tenantId": "tenant_public_1"}))
        call = self.admin_tenants.calls[0]
        self.assertEqual(call["audit_reason"], reason)
        self.assertEqual(call["context"].actor_session_id, UUID(int=3))

    def test_proxy_headers_are_ignored_unless_peer_is_trusted(self) -> None:
        contexts: list[Any] = []

        def capture(_match: Any, request: Any) -> None:
            handler, context, _body = request
            contexts.append(context)
            handler._send_json(200, {"ok": True})

        dispatcher = MediaBusinessDispatcher(
            {route.operation_id: capture for route in MEDIA_BUSINESS_ROUTE_BINDINGS}
        )
        self._restart_server(HttpAuthorityConfig("http://127.0.0.1"), dispatcher=dispatcher)
        spoofed = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Host": "evil.example"}
        status, _ = self._request(
            "GET", "/openclaw/media/api/dashboard", token="user-token", headers=spoofed
        )
        self.assertEqual(status, 200)
        self.assertEqual(contexts[-1].authority.client_ip, "127.0.0.1")
        self.assertFalse(contexts[-1].authority.trusted_proxy)

        self._restart_server(
            HttpAuthorityConfig("http://127.0.0.1", ("127.0.0.0/8",)),
            dispatcher=dispatcher,
        )
        status, body = self._request(
            "GET", "/openclaw/media/api/dashboard", token="user-token", headers=spoofed
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

        status, _ = self._request(
            "GET", "/openclaw/media/api/dashboard", token="user-token",
            headers={"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Host": "127.0.0.1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(contexts[-1].authority.client_ip, "203.0.113.9")
        self.assertTrue(contexts[-1].authority.trusted_proxy)

    def test_legacy_business_is_404_but_excluded_r1_and_archive_routes_survive(self) -> None:
        status, _ = self._request("GET", "/media/api/dashboard", token="user-token")
        self.assertEqual(status, 404)
        expected_status = {
            "/openclaw/media/api/pipelines": 503,
            "/openclaw/media/api/archives": 503,
            "/media/api/pipelines": 404,
            "/media/api/archives": 404,
        }
        for path, expected in expected_status.items():
            with self.subTest(path=path):
                status, _ = self._request("GET", path, token="user-token")
                self.assertEqual(status, expected)

    def test_startup_rejects_missing_and_extra_if2_services(self) -> None:
        missing = dict(self.services)
        missing.pop("documents")
        with self.assertRaisesRegex(ValueError, "missing=.*documents"):
            make_server("127.0.0.1", 0, None, media_business_services=missing)

        extra = {**self.services, "legacy": SimpleNamespace()}
        with self.assertRaisesRegex(ValueError, "extra=.*legacy"):
            make_server("127.0.0.1", 0, None, media_business_services=extra)

    def test_request_context_token_identity_is_hashed(self) -> None:
        contexts: list[Any] = []

        def capture(_match: Any, request: Any) -> None:
            handler, context, _body = request
            contexts.append(context)
            handler._send_json(200, {"ok": True})

        dispatcher = MediaBusinessDispatcher(
            {route.operation_id: capture for route in MEDIA_BUSINESS_ROUTE_BINDINGS}
        )
        self._restart_server(HttpAuthorityConfig("http://127.0.0.1"), dispatcher=dispatcher)
        status, _ = self._request("GET", "/openclaw/media/api/dashboard", token="user-token")
        self.assertEqual(status, 200)
        self.assertEqual(contexts[0].principal.session_token_hash, hashlib.sha256(b"user-token").digest())

    def test_document_block_error_exposes_block_ids_in_422_details(self) -> None:
        def reject_document(_match: Any, _request: Any) -> None:
            raise UnsupportedDocumentBlock({"blk_protected_2", "blk_protected_1"})

        dispatcher = MediaBusinessDispatcher(
            {route.operation_id: reject_document for route in MEDIA_BUSINESS_ROUTE_BINDINGS}
        )
        self._restart_server(HttpAuthorityConfig("http://127.0.0.1"), dispatcher=dispatcher)
        status, body = self._request(
            "PUT",
            "/openclaw/media/api/documents/aaaaaaaaaaaaaaaa/draft",
            body={"body": {"blocks": []}},
            token="user-token",
            headers=self._mutation_headers("user-token"),
        )
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["details"]["blockIds"], ["blk_protected_1", "blk_protected_2"])


if __name__ == "__main__":
    unittest.main()
