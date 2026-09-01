from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from openclaw_app.account import AccountAuthService, AccountSession
from openclaw_app.account.auth import AccountSessionInspection
from openclaw_app.account.workspace_resolution import (
    InMemoryWorkspaceResolutionRepository,
    WorkspaceResolutionRow,
    WorkspaceResolver,
)
from openclaw_app.adapters.http_api import AuthConfig, HttpAuthorityConfig, make_server


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
PERSONAL_TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ORGANIZATION_TENANT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PERSONAL_WORKSPACE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ORGANIZATION_WORKSPACE_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
PERSONAL_TOKEN = "opaque-entry-personal-token-0001"
ORGANIZATION_TOKEN = "opaque-entry-organization-token-0001"
EXPIRED_TOKEN = "opaque-entry-expired-token-0001"


class _ReadOnlyConnection:
    def __init__(self) -> None:
        self.row: tuple[Any, ...] | None = None
        self.statements: list[str] = []

    def __enter__(self) -> "_ReadOnlyConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, _parameters: object) -> "_ReadOnlyConnection":
        self.statements.append(statement)
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class _ReadOnlyDatabase:
    def __init__(self, connection: _ReadOnlyConnection) -> None:
        self.connection = connection

    def connect(self) -> _ReadOnlyConnection:
        return self.connection


class _EntryStateAuth:
    def __init__(self, inspections: dict[str, AccountSessionInspection]) -> None:
        self._inspections = inspections
        self.inspect_calls: list[str | None] = []
        self.resolve_calls: list[str | None] = []

    def inspect_session(self, token: str | None) -> AccountSessionInspection | None:
        self.inspect_calls.append(token)
        return self._inspections.get(token or "")

    def resolve_session(self, token: str | None) -> AccountSession | None:
        self.resolve_calls.append(token)
        inspection = self._inspections.get(token or "")
        if inspection is None or inspection.state != "active":
            return None
        return inspection.session

    @staticmethod
    def csrf_token(token: str) -> str:
        return hmac.new(b"entry-state-test-secret", token.encode("ascii"), hashlib.sha256).hexdigest()

    def verify_csrf(self, token: str, supplied: str) -> bool:
        return hmac.compare_digest(self.csrf_token(token), supplied)


def _session(tenant_id: UUID, *, expires_at: datetime = NOW + timedelta(hours=1)) -> AccountSession:
    return AccountSession(
        session_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        user_id=USER_ID,
        tenant_id=tenant_id,
        username="sensitive-entry-user",
        email="sensitive.entry.user@example.com",
        role="user",
        expires_at=expires_at,
    )


def _workspace_rows() -> tuple[WorkspaceResolutionRow, ...]:
    return (
        WorkspaceResolutionRow(
            workspace_id=PERSONAL_WORKSPACE_ID,
            tenant_id=PERSONAL_TENANT_ID,
            workspace_mode="personal_web",
            body_authority="internal",
            membership_role="owner",
            owner_user_id=USER_ID,
            user_id=USER_ID,
        ),
        WorkspaceResolutionRow(
            workspace_id=ORGANIZATION_WORKSPACE_ID,
            tenant_id=ORGANIZATION_TENANT_ID,
            workspace_mode="organization_lark",
            body_authority="lark",
            membership_role="member",
            binding_id="binding-secret",
            binding_status="ACTIVE",
            user_id=USER_ID,
        ),
    )


class AuthEntryStateHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = _EntryStateAuth(
            {
                PERSONAL_TOKEN: AccountSessionInspection(_session(PERSONAL_TENANT_ID), "active"),
                ORGANIZATION_TOKEN: AccountSessionInspection(_session(ORGANIZATION_TENANT_ID), "active"),
                EXPIRED_TOKEN: AccountSessionInspection(
                    _session(PERSONAL_TENANT_ID, expires_at=NOW - timedelta(seconds=1)), "expired"
                ),
            }
        )
        self.server = make_server(
            "127.0.0.1",
            0,
            None,
            auth_config=AuthConfig(session_secret=b"s" * 48, cookie_secure=False),
            account_auth=self.auth,  # type: ignore[arg-type]
            workspace_resolver=WorkspaceResolver(
                self.auth,
                InMemoryWorkspaceResolutionRepository(_workspace_rows()),
                now=lambda: NOW,
            ),
            authority_config=HttpAuthorityConfig(public_origin="http://127.0.0.1"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def _request(
        self,
        path: str,
        *,
        cookie: str | None = None,
    ) -> tuple[int, dict[str, Any] | None, str]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        headers = {"Cookie": cookie} if cookie else {}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        connection.close()
        return response.status, json.loads(raw) if raw else None, raw

    @staticmethod
    def _cookie(token: str) -> str:
        return f"openclaw_session={token}"

    def test_entry_state_returns_all_four_states_and_mode_fallbacks(self) -> None:
        cases = (
            ("/openclaw/auth/entry-state?mode=personal", self._cookie(PERSONAL_TOKEN), "matched", "password"),
            ("/openclaw/auth/entry-state?mode=personal", None, "none", "password"),
            ("/openclaw/auth/entry-state?mode=organization", self._cookie(EXPIRED_TOKEN), "expired", "feishu_oauth"),
            (
                "/openclaw/auth/entry-state?mode=personal",
                self._cookie(ORGANIZATION_TOKEN),
                "mismatched",
                "password",
            ),
        )
        for path, cookie, expected_state, expected_fallback in cases:
            with self.subTest(expected_state=expected_state):
                status, body, _ = self._request(path, cookie=cookie)
                self.assertEqual(status, 200, body)
                self.assertIsNotNone(body)
                assert body is not None
                self.assertEqual(body["schemaVersion"], "media_auth_entry_state_v1")
                self.assertEqual(body["state"], expected_state)
                self.assertEqual(body["fallback"], expected_fallback)
                if expected_state == "matched":
                    self.assertIsNotNone(body["entry"])
                else:
                    self.assertIsNone(body["entry"])

    def test_organization_match_is_resolved_from_session_tenant(self) -> None:
        status, body, _ = self._request(
            "/openclaw/auth/entry-state?mode=organization",
            cookie=self._cookie(ORGANIZATION_TOKEN),
        )
        self.assertEqual(status, 200, body)
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(body["state"], "matched")
        self.assertEqual(body["entry"]["displayLabel"], "当前组织工作区")
        self.assertEqual(body["fallback"], "feishu_oauth")

    def test_matched_entry_is_redacted_and_does_not_expose_session_fields(self) -> None:
        status, body, raw = self._request(
            "/openclaw/auth/entry-state?mode=personal",
            cookie=self._cookie(PERSONAL_TOKEN),
        )
        self.assertEqual(status, 200, body)
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(
            body["entry"],
            {
                "entryId": "current",
                "displayLabel": "当前个人工作区",
                "maskedIdentity": "s***@example.com",
                "expiresAt": (NOW + timedelta(hours=1)).isoformat(),
            },
        )
        for secret in (
            PERSONAL_TOKEN,
            "sensitive.entry.user@example.com",
            str(USER_ID),
            str(PERSONAL_TENANT_ID),
            str(PERSONAL_WORKSPACE_ID),
            "binding-secret",
        ):
            self.assertNotIn(secret, raw)
        self.assertNotIn("csrfToken", body)
        self.assertNotIn("sessionId", body)

    def test_malformed_mode_uses_invalid_request_and_does_not_inspect_cookie(self) -> None:
        for path in (
            "/openclaw/auth/entry-state",
            "/openclaw/auth/entry-state?mode=",
            "/openclaw/auth/entry-state?mode=admin",
            "/openclaw/auth/entry-state?mode=personal&mode=organization",
            "/openclaw/auth/entry-state?mode=personal&extra=ignored",
        ):
            with self.subTest(path=path):
                status, body, _ = self._request(path, cookie=self._cookie(PERSONAL_TOKEN))
                self.assertEqual(status, 400, body)
                self.assertIsNotNone(body)
                assert body is not None
                self.assertEqual(body["error"]["code"], "invalid_request")
        self.assertEqual(self.auth.inspect_calls, [])

    def test_entry_state_does_not_call_mutating_legacy_session_resolution(self) -> None:
        status, body, _ = self._request(
            "/openclaw/auth/entry-state?mode=personal",
            cookie=self._cookie(PERSONAL_TOKEN),
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(self.auth.inspect_calls, [PERSONAL_TOKEN])
        self.assertEqual(self.auth.resolve_calls, [])

    def test_legacy_media_session_contract_remains_separate(self) -> None:
        status, body, _ = self._request(
            "/openclaw/media/api/session",
            cookie=self._cookie(PERSONAL_TOKEN),
        )
        self.assertEqual(status, 200, body)
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(set(body), {"schemaVersion", "revision", "session"})
        self.assertEqual(set(body["session"]), {
            "publicUserId",
            "workspaceMode",
            "editorMode",
            "bodyAuthority",
            "organizationName",
            "memberRole",
            "organizationConnection",
            "installationConnection",
            "role",
            "maintainer",
            "csrfToken",
            "expiresAt",
            "routeGrants",
            "schemaVersion",
        })
        self.assertEqual(body["session"]["workspaceMode"], "personal_web")
        self.assertGreaterEqual(len(self.auth.resolve_calls), 1)
        self.assertTrue(all(token == PERSONAL_TOKEN for token in self.auth.resolve_calls))


class AccountAuthReadOnlyInspectionTests(unittest.TestCase):
    def _service_with_row(
        self,
        *,
        token: str,
        session_status: str = "active",
        expires_at: datetime = NOW + timedelta(hours=1),
        user_status: str = "active",
        tenant_status: str = "active",
        csrf_token_hash: bytes | None = None,
    ) -> tuple[AccountAuthService, _ReadOnlyConnection]:
        connection = _ReadOnlyConnection()
        service = AccountAuthService(
            _ReadOnlyDatabase(connection),  # type: ignore[arg-type]
            csrf_secret=b"s" * 48,
            bcrypt_rounds=12,
            now=lambda: NOW,
        )
        connection.row = (
            UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
            USER_ID,
            PERSONAL_TENANT_ID,
            "sensitive-entry-user",
            "sensitive.entry.user@example.com",
            "user",
            user_status,
            tenant_status,
            session_status,
            csrf_token_hash if csrf_token_hash is not None else hashlib.sha256(
                service.csrf_token(token).encode("ascii")
            ).digest(),
            expires_at,
            False,
        )
        return service, connection

    def test_inspect_session_uses_select_without_session_mutation(self) -> None:
        service, connection = self._service_with_row(token=PERSONAL_TOKEN)

        inspection = service.inspect_session(PERSONAL_TOKEN)

        self.assertIsNotNone(inspection)
        assert inspection is not None
        self.assertEqual(inspection.state, "active")
        self.assertEqual(len(connection.statements), 1)
        statement = connection.statements[0].upper()
        self.assertIn("SELECT", statement)
        self.assertNotIn("UPDATE", statement)
        self.assertNotIn("FOR UPDATE", statement)

    def test_inspect_session_reports_expiry_without_marking_the_row(self) -> None:
        service, connection = self._service_with_row(
            token=EXPIRED_TOKEN,
            expires_at=NOW - timedelta(seconds=1),
        )

        inspection = service.inspect_session(EXPIRED_TOKEN)

        self.assertIsNotNone(inspection)
        assert inspection is not None
        self.assertEqual(inspection.state, "expired")
        self.assertNotIn("UPDATE", connection.statements[0].upper())


if __name__ == "__main__":
    unittest.main()
