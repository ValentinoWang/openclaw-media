from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
from uuid import UUID, uuid4

import bcrypt
import psycopg

from openclaw_app.account import (
    AccountAuthService,
    AccountDatabase,
    AccountDatabaseSettings,
    AccountRegistrationService,
)
from openclaw_app.adapters.http_api import AuthConfig, make_server


ADMIN = UUID("33333333-3333-4333-8333-333333333333")
ADMIN_TENANT = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


class AccountRegistrationHttpPostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database_url = os.getenv("OPENCLAW_ACCOUNT_TEST_DATABASE_URL", "").strip()
        if not cls.database_url:
            raise unittest.SkipTest("OPENCLAW_ACCOUNT_TEST_DATABASE_URL is not configured")

    def setUp(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "TRUNCATE openclaw_account.admin_audit, openclaw_account.admission_codes, "
                "openclaw_account.admission_batches, openclaw_account.affiliate_edges, "
                "openclaw_account.affiliate_profiles, openclaw_account.password_reset_tokens, "
                "openclaw_account.sessions, "
                "openclaw_account.upstream_request_refs, openclaw_account.model_operations, "
                "openclaw_account.fund_holds, openclaw_account.ledger_entries, "
                "openclaw_account.wallet_accounts, openclaw_account.tenants, "
                "openclaw_account.users CASCADE"
            )
            connection.execute(
                "INSERT INTO openclaw_account.registration_policy(singleton, mode) VALUES (TRUE, 'controlled')"
            )
            password_hash = bcrypt.hashpw(b"password-for-admin", bcrypt.gensalt(rounds=12)).decode()
            connection.execute(
                "INSERT INTO openclaw_account.users(id, username, email, password_hash, role) "
                "VALUES (%s, 'admin', 'admin@example.com', %s, 'admin')",
                (ADMIN, password_hash),
            )
            connection.execute(
                "INSERT INTO openclaw_account.tenants(id, primary_user_id) VALUES (%s, %s)",
                (ADMIN_TENANT, ADMIN),
            )
            connection.execute(
                "INSERT INTO openclaw_account.wallet_accounts(id, tenant_id) VALUES (%s, %s)",
                (uuid4(), ADMIN_TENANT),
            )
            connection.execute(
                "INSERT INTO openclaw_account.affiliate_profiles(user_id, invite_code) "
                "VALUES (%s, 'AAAAAAAAAAAAAAAAAAAA')",
                (ADMIN,),
            )

        database = AccountDatabase(AccountDatabaseSettings(self.database_url))
        self.database = database
        secret = b"s" * 48
        self.auth = AccountAuthService(database, csrf_secret=secret, bcrypt_rounds=12)
        self.registration = AccountRegistrationService(
            database,
            account_auth=self.auth,
            code_secret=secret,
            bcrypt_rounds=12,
        )
        config = AuthConfig(secret, session_ttl_seconds=3600, cookie_path="/", cookie_secure=False)
        self.server = make_server(
            "127.0.0.1",
            0,
            None,
            auth_config=config,
            account_auth=self.auth,
            account_registration=self.registration,
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
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        cookie: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object], dict[str, str]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        request_headers = dict(headers or {})
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        if body is not None:
            request_headers["Content-Type"] = "application/json"
            request_headers["Content-Length"] = str(len(body))
        if cookie:
            request_headers["Cookie"] = cookie
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, json.loads(raw) if raw else {}, response_headers

    def _issue_admin_session_cookie(self) -> str:
        with self.database.connect() as connection:
            login = self.auth.issue_session_for_account(
                connection,
                user_id=ADMIN,
                tenant_id=ADMIN_TENANT,
                username="admin",
                email="admin@example.com",
                role="admin",
            )
        return f"openclaw_session={login.token}"

    def _headers(self, cookie: str, key: str) -> dict[str, str]:
        token = cookie.split("=", 1)[1]
        return {
            "Origin": f"http://127.0.0.1:{self.port}",
            "X-OpenClaw-CSRF": self.auth.csrf_token(token),
            "Idempotency-Key": key,
        }

    def test_controlled_issue_register_login_and_authorization_readback(self) -> None:
        admin_cookie = self._issue_admin_session_cookie()
        status, body, headers = self._request(
            "POST",
            "/media/api/admin/admission-batches",
            {"name": "production-style batch", "codeCount": 1, "reason": "HTTP acceptance"},
            cookie=admin_cookie,
            headers=self._headers(admin_cookie, "u4-http-batch"),
        )
        self.assertEqual(status, 201, body)
        plaintext_code = body["codes"][0]

        status, body, headers = self._request(
            "POST",
            "/auth/register",
            {
                "username": "http-user",
                "email": "http-user@example.com",
                "password": "registration-password",
                "admissionCode": plaintext_code,
            },
        )
        self.assertEqual(status, 201, body)
        self.assertTrue(body["ok"])
        user_id = body["userId"]
        self.assertIsNone(body["inviterUserId"])
        user_cookie = headers["set-cookie"].split(";", 1)[0]

        status, session, _ = self._request("GET", "/media/api/session", cookie=user_cookie)
        self.assertEqual(status, 200, session)
        self.assertEqual(session["userId"], user_id)
        status, profile, _ = self._request(
            "GET", "/media/api/account/affiliate", cookie=user_cookie
        )
        self.assertEqual(status, 200, profile)
        self.assertEqual(profile["userId"], user_id)
        status, denied, _ = self._request(
            "GET", "/media/api/admin/admission-batches", cookie=user_cookie
        )
        self.assertEqual(status, 403, denied)
        self.assertEqual(denied["error"]["code"], "admin_required")

        with psycopg.connect(self.database_url) as connection:
            stored = connection.execute(
                "SELECT status, code_hmac, consumed_by_user_id FROM openclaw_account.admission_codes"
            ).fetchone()
            self.assertEqual(stored[0], "consumed")
            self.assertEqual(len(stored[1]), 32)
            self.assertEqual(str(stored[2]), user_id)
            self.assertNotIn(
                plaintext_code,
                json.dumps(
                    connection.execute(
                        "SELECT metadata FROM openclaw_account.admin_audit ORDER BY created_at"
                    ).fetchall(),
                    default=str,
                ),
            )

    def test_controlled_rejections_and_open_no_code_registration(self) -> None:
        for payload, code in (
            ({"username": "no-code", "password": "registration-password"}, "admission_required"),
            (
                {
                    "username": "two-code",
                    "password": "registration-password",
                    "admissionCode": "platform",
                    "affiliateCode": "affiliate",
                },
                "multiple_admission_sources",
            ),
        ):
            status, body, _ = self._request("POST", "/auth/register", payload)
            self.assertIn(status, {400, 403}, body)
            self.assertEqual(body["error"]["code"], code)

        admin_cookie = self._issue_admin_session_cookie()
        status, body, _ = self._request(
            "PUT",
            "/media/api/admin/registration-policy",
            {"registrationPolicyMode": "open", "reason": "HTTP acceptance"},
            cookie=admin_cookie,
            headers=self._headers(admin_cookie, "u4-http-policy-open"),
        )
        self.assertEqual(status, 200, body)
        status, body, _ = self._request(
            "POST",
            "/auth/register",
            {"username": "open-user", "password": "registration-password"},
        )
        self.assertEqual(status, 201, body)
        self.assertIsNone(body["inviterUserId"])


if __name__ == "__main__":
    unittest.main()
