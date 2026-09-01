from __future__ import annotations

import os
import hashlib
import unittest
from uuid import UUID

import bcrypt
import psycopg

from openclaw_app.account import (
    AccountAuthError,
    AccountAuthService,
    AccountContractError,
    AccountDatabase,
    AccountDatabaseSettings,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")
TENANT_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
TENANT_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ADMIN = UUID("33333333-3333-4333-8333-333333333333")
ADMIN_TENANT = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
FEISHU_MEMBER = UUID("44444444-4444-4444-8444-444444444444")


class AccountAuthSessionTtlValidationTests(unittest.TestCase):
    """Pins the session-ttl bound/default without a real database connection
    -- the ValueError guards in AccountAuthService.__init__ fire before
    `database` is touched, so a dummy stand-in is enough."""

    def _service(self, **kwargs: object) -> AccountAuthService:
        return AccountAuthService(object(), csrf_secret=b"s" * 32, **kwargs)  # type: ignore[arg-type]

    def test_default_session_ttl_is_twenty_eight_days(self) -> None:
        service = self._service()
        self.assertEqual(service._session_ttl_seconds, 28 * 24 * 60 * 60)

    def test_twenty_eight_days_is_accepted(self) -> None:
        service = self._service(session_ttl_seconds=28 * 24 * 60 * 60)
        self.assertEqual(service._session_ttl_seconds, 28 * 24 * 60 * 60)

    def test_beyond_twenty_eight_days_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._service(session_ttl_seconds=28 * 24 * 60 * 60 + 1)

    def test_seven_and_fourteen_days_no_longer_rejected_as_prior_ceilings(self) -> None:
        # Regression guard: the ceiling moved 7 days -> 14 days -> 28 days
        # across successive requests; confirms both older values are still
        # accepted under the current (wider) ceiling rather than the check
        # having been narrowed back down by accident.
        for prior_ceiling in (7 * 24 * 60 * 60, 14 * 24 * 60 * 60):
            with self.subTest(prior_ceiling=prior_ceiling):
                service = self._service(session_ttl_seconds=prior_ceiling)
                self.assertEqual(service._session_ttl_seconds, prior_ceiling)


class AccountAuthPostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database_url = os.getenv("OPENCLAW_ACCOUNT_TEST_DATABASE_URL", "").strip()
        if not cls.database_url:
            raise unittest.SkipTest("OPENCLAW_ACCOUNT_TEST_DATABASE_URL is not configured")

    def setUp(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "TRUNCATE openclaw_account.admin_audit, openclaw_account.password_reset_tokens, "
                "openclaw_account.sessions, openclaw_account.affiliate_edges, "
                "openclaw_account.upstream_request_refs, openclaw_account.model_operations, "
                "openclaw_account.fund_holds, openclaw_account.ledger_entries, openclaw_account.wallet_accounts, "
                "openclaw_account.tenants, openclaw_account.users CASCADE"
            )
            for user_id, tenant_id, username, password, role in (
                (USER_A, TENANT_A, "user-a", "password-for-user-a", "user"),
                (USER_B, TENANT_B, "user-b", "password-for-user-b", "user"),
                (ADMIN, ADMIN_TENANT, "admin", "password-for-admin", "admin"),
            ):
                password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
                connection.execute(
                    "INSERT INTO openclaw_account.users(id, username, email, password_hash, role, display_name) VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, username, f"{username}@example.com", password_hash, role, username),
                )
                connection.execute(
                    "INSERT INTO openclaw_account.tenants(id, primary_user_id) VALUES (%s, %s)",
                    (tenant_id, user_id),
                )
                connection.execute(
                    "INSERT INTO openclaw_account.tenant_members(tenant_id, user_id, role, status) "
                    "VALUES (%s, %s, 'owner', 'active')",
                    (tenant_id, user_id),
                )
        database = AccountDatabase(AccountDatabaseSettings(self.database_url))
        self.auth = AccountAuthService(database, csrf_secret=b"s" * 48, bcrypt_rounds=12)

    def test_a_b_and_admin_login_use_distinct_openclaw_subjects(self) -> None:
        for username, password, user_id, tenant_id, role in (
            ("user-a", "password-for-user-a", USER_A, TENANT_A, "user"),
            ("user-b", "password-for-user-b", USER_B, TENANT_B, "user"),
            ("admin", "password-for-admin", ADMIN, ADMIN_TENANT, "admin"),
        ):
            login = self.auth.login(username, password)
            session = self.auth.resolve_session(login.token)
            self.assertIsNotNone(session)
            self.assertEqual(session.user_id, user_id)
            self.assertEqual(session.tenant_id, tenant_id)
            self.assertEqual(session.role, role)
            self.assertTrue(self.auth.verify_csrf(login.token, login.csrf_token))

    def test_wrong_password_is_rejected_without_creating_session(self) -> None:
        with self.assertRaises(AccountAuthError) as raised:
            self.auth.login("user-a", "incorrect-password")
        self.assertEqual(raised.exception.code, "invalid_credentials")
        with psycopg.connect(self.database_url) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM openclaw_account.sessions").fetchone()[0], 0)

    def test_feishu_union_identity_logs_into_bound_tenant_when_app_open_id_changes(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            password_hash = bcrypt.hashpw(b"no-password-login", bcrypt.gensalt(rounds=12)).decode()
            connection.execute(
                "INSERT INTO openclaw_account.users(id, username, email, password_hash, role, display_name) "
                "VALUES (%s, 'feishu-member', NULL, %s, 'user', 'Feishu Member')",
                (FEISHU_MEMBER, password_hash),
            )
            connection.execute(
                "INSERT INTO openclaw_account.tenant_members(tenant_id, user_id, role, status) "
                "VALUES (%s, %s, 'member', 'active')",
                (TENANT_A, FEISHU_MEMBER),
            )
            connection.execute(
                "INSERT INTO openclaw_account.tenant_member_identities("
                "tenant_id, user_id, tenant_key, open_id, union_id, external_user_id, display_name"
                ") VALUES (%s, %s, 'tenant-media-a', 'open-a', 'union-a', 'open-a', 'Member A')",
                (TENANT_A, FEISHU_MEMBER),
            )

        login = self.auth.login_verified_feishu_identity(
            tenant_key="tenant-media-a",
            open_id="open-from-independent-media-app",
            union_id="union-a",
        )
        session = self.auth.resolve_session(login.token)
        self.assertIsNotNone(session)
        self.assertEqual(session.user_id, FEISHU_MEMBER)
        self.assertEqual(session.tenant_id, TENANT_A)

    def test_organization_feishu_login_reads_the_canonical_tenant_membership(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE openclaw_account.tenants SET tenant_type='organization', "
                "workspace_mode='organization_lark', body_authority='lark', "
                "organization_name='Organization A' WHERE id=%s",
                (TENANT_A,),
            )
            password_hash = bcrypt.hashpw(b"no-password-login", bcrypt.gensalt(rounds=12)).decode()
            connection.execute(
                "INSERT INTO openclaw_account.users(id, username, email, password_hash, role, display_name) "
                "VALUES (%s, 'organization-member', NULL, %s, 'user', 'Organization Member')",
                (FEISHU_MEMBER, password_hash),
            )
            connection.execute(
                "INSERT INTO openclaw_account.tenant_members(tenant_id, user_id, role, status) "
                "VALUES (%s, %s, 'member', 'active')",
                (TENANT_A, FEISHU_MEMBER),
            )
            connection.execute(
                "INSERT INTO openclaw_account.tenant_member_identities("
                "tenant_id, user_id, tenant_key, open_id, union_id, external_user_id, display_name"
                ") VALUES (%s, %s, 'tenant-organization-a', 'open-org-a', 'union-org-a', "
                "'external-org-a', 'Organization Member')",
                (TENANT_A, FEISHU_MEMBER),
            )
            connection.execute(
                "INSERT INTO media_product.lark_tenant_bindings("
                "tenant_id, tenant_key, installation_public_id, app_id, app_secret_ref, "
                "space_id, parent_node_token, status) "
                "VALUES (%s, 'tenant-organization-a', 'installation-org-a', 'app-org-a', "
                "'secret://org-a', 'space-org-a', 'parent-org-a', 'active')",
                (TENANT_A,),
            )

        login = self.auth.login_verified_feishu_identity(
            tenant_key="tenant-organization-a",
            open_id="open-org-a",
            union_id="union-org-a",
            workspace_intent="organization_lark",
        )
        session = self.auth.resolve_session(login.token)
        self.assertIsNotNone(session)
        self.assertEqual(session.user_id, FEISHU_MEMBER)
        self.assertEqual(session.tenant_id, TENANT_A)

    def test_login_rotates_previous_session_and_expiry_is_persisted(self) -> None:
        first = self.auth.login("user-a", "password-for-user-a")
        second = self.auth.login("user-a", "password-for-user-a", previous_token=first.token)
        self.assertIsNone(self.auth.resolve_session(first.token))
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE openclaw_account.sessions SET issued_at = now() - interval '1 hour', "
                "expires_at = now() - interval '1 second' WHERE session_token_hash = %s",
                (hashlib.sha256(second.token.encode()).digest(),),
            )
        self.assertIsNone(self.auth.resolve_session(second.token))
        with psycopg.connect(self.database_url) as connection:
            status = connection.execute(
                "SELECT status FROM openclaw_account.sessions WHERE session_token_hash = %s",
                (hashlib.sha256(second.token.encode()).digest(),),
            ).fetchone()[0]
        self.assertEqual(status, "expired")

    def test_role_is_reread_on_every_session_resolution(self) -> None:
        login = self.auth.login("admin", "password-for-admin")
        self.assertEqual(self.auth.resolve_session(login.token).role, "admin")
        with psycopg.connect(self.database_url) as connection:
            connection.execute("UPDATE openclaw_account.users SET role = 'user' WHERE id = %s", (ADMIN,))
        self.assertEqual(self.auth.resolve_session(login.token).role, "user")

    def test_password_change_and_reset_revoke_sessions(self) -> None:
        login = self.auth.login("user-a", "password-for-user-a")
        self.auth.change_password(login.token, "password-for-user-a", "replacement-password-a")
        self.assertIsNone(self.auth.resolve_session(login.token))
        changed = self.auth.login("user-a", "replacement-password-a")
        reset_token = self.auth.issue_password_reset(USER_A)
        self.auth.reset_password(reset_token, "reset-password-for-user-a")
        self.assertIsNone(self.auth.resolve_session(changed.token))
        with self.assertRaises(AccountAuthError):
            self.auth.reset_password(reset_token, "another-password-for-user-a")

    def test_admin_revoke_is_role_checked_audited_and_append_only(self) -> None:
        target = self.auth.login("user-b", "password-for-user-b")
        user = self.auth.login("user-a", "password-for-user-a")
        with self.assertRaises(AccountAuthError) as raised:
            self.auth.admin_revoke_user_sessions(user.token, USER_B, "not allowed")
        self.assertEqual(raised.exception.code, "admin_required")
        admin = self.auth.login("admin", "password-for-admin")
        self.assertEqual(self.auth.admin_revoke_user_sessions(admin.token, USER_B, "security response"), 1)
        self.assertIsNone(self.auth.resolve_session(target.token))
        with psycopg.connect(self.database_url) as connection:
            audit_id = connection.execute(
                "SELECT id FROM openclaw_account.admin_audit WHERE target_user_id = %s",
                (USER_B,),
            ).fetchone()[0]
            with self.assertRaises(psycopg.Error):
                connection.execute("DELETE FROM openclaw_account.admin_audit WHERE id = %s", (audit_id,))

    def test_database_unavailable_fails_closed(self) -> None:
        unavailable = AccountAuthService(
            AccountDatabase(AccountDatabaseSettings("postgresql://127.0.0.1:1/unavailable?connect_timeout=1")),
            csrf_secret=b"s" * 48,
        )
        with self.assertRaises(AccountContractError) as raised:
            unavailable.login("user-a", "password-for-user-a")
        self.assertEqual(raised.exception.code, "account_database_unavailable")


if __name__ == "__main__":
    unittest.main()
