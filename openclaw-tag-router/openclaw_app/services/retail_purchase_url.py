"""Shared predicate for validating a Liandong (链动) purchase URL.

retail_admin.py and media_business/admin_billing.py each carried their own
near-identical "purchase_url" validator, each wrapping the same rule set in
their own exception type. This module holds the rule set as a plain
predicate with no exception binding; each caller wraps it in whichever
error type/code/field name its own contract requires -- see the url-10
dedup audit.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_MIN_LENGTH = 20
_MAX_LENGTH = 2048
_ALLOWED_HOST = "ldxp.cn"


def is_liandong_purchase_url(value: str) -> bool:
    """True iff ``value`` is a well-formed Liandong HTTPS purchase URL.

    Rules (union of both prior implementations): a plain ``str`` (any
    other type is simply not a valid URL), stripped of leading/trailing
    whitespace, 20-2048 characters, no whitespace anywhere in it, HTTPS
    scheme, no userinfo, no explicit port, no fragment, and a host that is
    exactly ``ldxp.cn`` or a subdomain of it. A malformed port (e.g. out of
    the 0-65535 range) makes ``urlsplit(...).port`` raise ``ValueError``
    internally -- treated as "not a valid URL" rather than propagating.
    """
    if not isinstance(value, str):
        return False
    if value != value.strip():
        return False
    if not _MIN_LENGTH <= len(value) <= _MAX_LENGTH:
        return False
    if any(character.isspace() for character in value):
        return False
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
        or not (host == _ALLOWED_HOST or host.endswith(f".{_ALLOWED_HOST}"))
    ):
        return False
    return True
