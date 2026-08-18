from __future__ import annotations

import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import bcrypt
import psycopg

from openclaw_app.account import (
    AccountAuthRepository,
    AccountAuthService,
    AccountAuthError,
    AccountContractError,
    AccountDatabase,
    AccountDatabaseSettings,
    AccountRegistrationRepository,
    AccountRegistrationService,
)


ADMIN = UUID("33333333-3333-4333-8333-333333333333")
ADMIN_TENANT = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ADMIN_SESSION = UUID("44444444-4444-4444-8444-444444444444")


class _FailingEdgeRepository(AccountRegistrationRepository):
    def create_affiliate_edge(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AccountContractError("account_database_unavailable", "forced edge failure")


class _FailingSessionRepository(AccountAuthRepository):
    def create_session(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AccountContractError("account_database_unavailable", "forced session failure")


class AccountRegistrationPostgreSQLTests(unittest.TestCase):
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
                "UPDATE openclaw_account.registration_policy SET mode = 'controlled', "
                "updated_by_user_id = NULL, reason = NULL, updated_at = now() WHERE singleton"
            )
            connection.execute(
                "INSERT INTO openclaw_account.registration_policy(singleton, mode) "
                "VALUES (TRUE, 'controlled') ON CONFLICT (singleton) DO NOTHING"
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
                "INSERT INTO openclaw_account.sessions("
                "id, session_token_hash, csrf_token_hash, user_id, tenant_id, expires_at"
                ") VALUES (%s, %s, %s, %s, %s, now() + interval '1 hour')",
                (ADMIN_SESSION, b"s" * 32, b"c" * 32, ADMIN, ADMIN_TENANT),
            )
        self.database = AccountDatabase(AccountDatabaseSettings(self.database_url))
        self.auth = AccountAuthService(self.database, csrf_secret=b"s" * 48, bcrypt_rounds=12)
        self.service = AccountRegistrationService(
            self.database,
            account_auth=self.auth,
            code_secret=b"r" * 48,
            bcrypt_rounds=12,
        )

    def _set_open(self) -> None:
        self.service.admin_set_registration_policy(
            actor_user_id=ADMIN,
            actor_session_id=ADMIN_SESSION,
            mode="open",
            reason="registration acceptance test",
        )

    def _counts(self) -> tuple[int, int, int, int, int, int]:
        with psycopg.connect(self.database_url) as connection:
            return tuple(
                connection.execute(f"SELECT count(*) FROM openclaw_account.{table}").fetchone()[0]
                for table in ("users", "tenants", "wallet_accounts", "affiliate_profiles", "affiliate_edges", "sessions")
            )  # type: ignore[return-value]

    def test_controlled_registration_requires_exactly_one_admission_source(self) -> None:
        before = self._counts()
        for kwargs, expected_code in (
            ({}, "admission_required"),
            ({"admission_code": "platform-code", "affiliate_code": "affiliate-code"}, "multiple_admission_sources"),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(AccountAuthError) as raised:
                    self.service.register(
                        username=f"rejected-{expected_code}",
                        email=None,
                        password="registration-password",
                        **kwargs,
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(self._counts(), before)

    def test_platform_code_is_consumed_once_in_the_registration_transaction(self) -> None:
        issue = self.service.admin_create_admission_batch(
            actor_user_id=ADMIN,
            actor_session_id=ADMIN_SESSION,
            name="controlled launch",
            code_count=1,
            reason="registration acceptance test",
        )
        result = self.service.register(
            username="platform-user",
            email="platform-user@example.com",
            password="registration-password",
            admission_code=issue.codes[0],
        )
        self.assertIsNone(result.inviter_user_id)
        with self.assertRaises(AccountAuthError) as raised:
            self.service.register(
                username="duplicate-platform-user",
                email=None,
                password="registration-password",
                admission_code=issue.codes[0],
            )
        self.assertEqual(raised.exception.code, "admission_unavailable")
        with psycopg.connect(self.database_url) as connection:
            consumed = connection.execute(
                "SELECT status, consumed_by_user_id FROM openclaw_account.admission_codes"
            ).fetchone()
        self.assertEqual(consumed, ("consumed", result.user_id))

    def test_admin_can_read_admission_codes_after_batch_creation(self) -> None:
        issue = self.service.admin_create_admission_batch(
            actor_user_id=ADMIN,
            actor_session_id=ADMIN_SESSION,
            name="persistent admin readback",
            code_count=2,
            reason="registration acceptance test",
        )

        first = self.service.admin_admission_batches(ADMIN, page=1, page_size=30)
        second = self.service.admin_admission_batches(ADMIN, page=1, page_size=30)
        self.assertEqual(first, second)
        self.assertEqual(first["items"][0]["batchId"], str(issue.batch_id))
        self.assertEqual(
            {item["code"] for item in first["items"][0]["codes"]},
            set(issue.codes),
        )
        self.assertEqual(
            [item["status"] for item in first["items"][0]["codes"]],
            ["active", "active"],
        )
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "SELECT code_hmac, code_ciphertext FROM openclaw_account.admission_codes ORDER BY created_at, id"
            ).fetchall()
        self.assertEqual(len(rows), 2)
        for code_hmac, ciphertext in rows:
            for code in issue.codes:
                self.assertNotIn(code.encode("utf-8"), bytes(ciphertext))
            self.assertEqual(len(code_hmac), 32)

    def test_database_rejects_admission_code_without_persistent_ciphertext(self) -> None:
        issue = self.service.admin_create_admission_batch(
            actor_user_id=ADMIN,
            actor_session_id=ADMIN_SESSION,
            name="ciphertext contract",
            code_count=1,
            reason="registration acceptance test",
        )
        with psycopg.connect(self.database_url) as connection:
            with self.assertRaises(psycopg.Error):
                connection.execute(
                    "INSERT INTO openclaw_account.admission_codes(id, batch_id, code_hmac) VALUES (%s, %s, %s)",
                    (uuid4(), issue.batch_id, b"h" * 32),
                )

    def test_open_registration_accepts_no_code_and_optional_direct_inviter(self) -> None:
        self._set_open()
        inviter = self.service.register(
            username="inviter",
            email=None,
            password="registration-password",
        )
        profile = self.service.admin_update_affiliate_profile(
            actor_user_id=ADMIN,
            actor_session_id=ADMIN_SESSION,
            target_user_id=inviter.user_id,
            signup_enabled=True,
            signup_quota=2,
            signup_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            reason="registration acceptance test",
        )
        direct = self.service.register(
            username="direct-invitee",
            email=None,
            password="registration-password",
            affiliate_code=profile.invite_code,
        )
        no_code = self.service.register(
            username="open-no-code",
            email=None,
            password="registration-password",
        )
        self.assertEqual(direct.inviter_user_id, inviter.user_id)
        self.assertIsNone(no_code.inviter_user_id)
        self.assertEqual(self.service.affiliate_profile(inviter.user_id).signup_used, 1)
        page = self.service.invitees(inviter.user_id, page=1, page_size=30)
        self.assertEqual([item.user_id for item in page.items], [direct.user_id])

    def test_last_affiliate_quota_cannot_be_oversold(self) -> None:
        self._set_open()
        inviter = self.service.register(
            username="quota-inviter",
            email=None,
            password="registration-password",
        )
        profile = self.service.admin_update_affiliate_profile(
            actor_user_id=ADMIN,
            actor_session_id=ADMIN_SESSION,
            target_user_id=inviter.user_id,
            signup_enabled=True,
            signup_quota=1,
            signup_expires_at=None,
            reason="registration acceptance test",
        )
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def register(index: int) -> None:
            barrier.wait()
            try:
                self.service.register(
                    username=f"quota-user-{index}",
                    email=None,
                    password="registration-password",
                    affiliate_code=profile.invite_code,
                )
            except AccountAuthError as exc:
                outcome = exc.code
            else:
                outcome = "created"
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=register, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(sorted(outcomes), ["affiliate_unavailable", "created"])
        self.assertEqual(self.service.affiliate_profile(inviter.user_id).signup_used, 1)

    def test_edge_failure_rolls_back_every_registration_row_and_quota(self) -> None:
        self._set_open()
        inviter = self.service.register(
            username="rollback-inviter",
            email=None,
            password="registration-password",
        )
        profile = self.service.admin_update_affiliate_profile(
            actor_user_id=ADMIN,
            actor_session_id=ADMIN_SESSION,
            target_user_id=inviter.user_id,
            signup_enabled=True,
            signup_quota=1,
            signup_expires_at=None,
            reason="registration acceptance test",
        )
        before = self._counts()
        failing = AccountRegistrationService(
            self.database,
            account_auth=self.auth,
            code_secret=b"r" * 48,
            bcrypt_rounds=12,
            repository=_FailingEdgeRepository(),
        )
        with self.assertRaises(AccountContractError):
            failing.register(
                username="rolled-back-user",
                email=None,
                password="registration-password",
                affiliate_code=profile.invite_code,
            )
        self.assertEqual(self._counts(), before)
        self.assertEqual(self.service.affiliate_profile(inviter.user_id).signup_used, 0)

    def test_session_failure_rolls_back_the_entire_registration(self) -> None:
        self._set_open()
        before = self._counts()
        failing_auth = AccountAuthService(
            self.database,
            csrf_secret=b"s" * 48,
            repository=_FailingSessionRepository(),
            bcrypt_rounds=12,
        )
        failing = AccountRegistrationService(
            self.database,
            account_auth=failing_auth,
            code_secret=b"r" * 48,
            bcrypt_rounds=12,
        )
        with self.assertRaises(AccountContractError):
            failing.register(
                username="session-rollback-user",
                email="session-rollback@example.com",
                password="registration-password",
            )
        self.assertEqual(self._counts(), before)

    def test_database_rejects_self_invite_cycles_and_rebinding(self) -> None:
        self._set_open()
        users = [
            self.service.register(username=name, email=None, password="registration-password")
            for name in ("cycle-user-a", "cycle-user-b", "cycle-user-c")
        ]
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO openclaw_account.affiliate_edges(id, inviter_user_id, invitee_user_id) VALUES (%s, %s, %s), (%s, %s, %s)",
                (uuid4(), users[0].user_id, users[1].user_id, uuid4(), users[1].user_id, users[2].user_id),
            )
            for inviter, invitee in (
                (users[0].user_id, users[0].user_id),
                (users[2].user_id, users[0].user_id),
            ):
                connection.execute("SAVEPOINT edge_probe")
                with self.assertRaises(psycopg.Error):
                    connection.execute(
                        "INSERT INTO openclaw_account.affiliate_edges(id, inviter_user_id, invitee_user_id) VALUES (%s, %s, %s)",
                        (uuid4(), inviter, invitee),
                    )
                connection.execute("ROLLBACK TO SAVEPOINT edge_probe")
                connection.execute("RELEASE SAVEPOINT edge_probe")
            connection.execute("SAVEPOINT rebind_probe")
            with self.assertRaises(psycopg.Error):
                connection.execute(
                    "UPDATE openclaw_account.affiliate_edges SET inviter_user_id = %s WHERE invitee_user_id = %s",
                    (users[2].user_id, users[1].user_id),
                )
            connection.execute("ROLLBACK TO SAVEPOINT rebind_probe")


if __name__ == "__main__":
    unittest.main()
