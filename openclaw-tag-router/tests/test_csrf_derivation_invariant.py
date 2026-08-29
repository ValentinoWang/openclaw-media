"""Cross-module invariant: the CSRF derivation chain is shared, not re-implemented.

``AccountAuthService.csrf_token``, ``PersonalAuthService._csrf_token`` and
``_CanonicalReaders._csrf_hash`` (stage2 production factory) all derive a
session's CSRF token via
``derive_csrf_token`` with the same domain separator (``CSRF_DOMAIN``); the
factory additionally hashes the result with ``token_digest`` before comparing
it against the ``bytea`` column read from Postgres. Before the TI-06 dedup
this was three independently hand-written HMAC derivations with no test
tying them together — a change to one could silently desync from the others
without any test failing. This file locks that relationship down.
"""

from __future__ import annotations

import unittest

from openclaw_app.account.auth import AccountAuthService
from openclaw_app.account.csrf import (
    CSRF_DOMAIN,
    PERSONAL_CSRF_DOMAIN,
    derive_csrf_token,
    token_digest,
)
from openclaw_app.account.lifecycle import PersonalAuthService
from openclaw_app.services.stage2_production_factory import _CanonicalReaders


class CsrfDerivationInvariantTests(unittest.TestCase):
    def test_factory_csrf_hash_matches_account_auth_service_csrf_token(self) -> None:
        secret = b"a" * 32
        factory = _CanonicalReaders(
            dsn="postgresql://unused/unused",
            session_secret=secret.decode("ascii"),
        )
        auth_service = AccountAuthService.__new__(AccountAuthService)
        auth_service._csrf_secret = secret

        for token in ("session-token-abc123", "another-session-token", "x" * 200):
            with self.subTest(token=token):
                expected = token_digest(AccountAuthService.csrf_token(auth_service, token))
                self.assertEqual(factory._csrf_hash(token), expected)

    def test_derive_csrf_token_is_domain_separated(self) -> None:
        secret = b"b" * 32
        token = "shared-raw-token"
        account_style = derive_csrf_token(secret, token, domain=CSRF_DOMAIN)
        personal_style = derive_csrf_token(secret, token, domain=PERSONAL_CSRF_DOMAIN)
        self.assertNotEqual(account_style, personal_style)

    def test_lifecycle_csrf_token_uses_personal_domain(self) -> None:
        secret = b"c" * 32
        lifecycle = PersonalAuthService.__new__(PersonalAuthService)
        lifecycle._csrf_secret = secret
        token = "personal-session-token"
        self.assertEqual(
            lifecycle._csrf_token(token),
            derive_csrf_token(secret, token, domain=PERSONAL_CSRF_DOMAIN),
        )


if __name__ == "__main__":
    unittest.main()
