"""Shared CSRF token derivation primitives.

Three call sites (``AccountAuthService.csrf_token``,
``PersonalAccountLifecycle._csrf_token`` and
``_CanonicalReaders._csrf_hash``) independently derive a CSRF token from a
session token by HMAC-ing a domain-separated message and base64url-encoding
the digest. This module centralizes that derivation so the algorithm is
defined once and locked down by a cross-module invariant test.

Domain separation: each caller mixes in a distinct domain prefix so tokens
derived for one CSRF namespace cannot be replayed against another.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

CSRF_DOMAIN = b"openclaw-csrf\0"
PERSONAL_CSRF_DOMAIN = b"openclaw-personal-csrf\0"


def derive_csrf_token(secret: bytes, token: str, *, domain: bytes) -> str:
    """Derive a CSRF token for ``token`` under HMAC key ``secret``.

    Raises ``UnicodeEncodeError`` if ``token`` is not ASCII, matching the
    behaviour of the call sites this replaces (they either let the error
    propagate to a caller-side try/except, or never receive non-ASCII input).
    """
    digest = hmac.new(secret, domain + token.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def token_digest(token: str) -> bytes:
    """SHA-256 digest of an ASCII token, as raw bytes.

    Same algorithm as ``AccountAuthService._token_hash`` and
    ``_CanonicalReaders._token_hash``: ``hashlib.sha256(token.encode("ascii")).digest()``.
    Does not defensively guard non-str/non-ASCII input (unlike
    ``lifecycle._token_digest``, which is a distinct, separately-scoped
    helper this module does not touch) — callers that need that guard keep
    it at their own call site, exactly as today.
    """
    return hashlib.sha256(token.encode("ascii")).digest()
