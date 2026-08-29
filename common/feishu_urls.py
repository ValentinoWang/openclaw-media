"""Pure (no-IO) helpers for parsing and building Feishu document/bitable URLs.

Several call sites across selfmedia and openclaw-tag-router each carried
their own near-identical regex-and-urlparse logic for pulling wiki/base
tokens and table ids out of a Feishu share URL, or for building one back.
This module centralizes the parsing/building algorithms; the IO half
(resolving a wiki token to a bitable app_token, or raising the right
exception type when something is missing) stays with each caller, since
that behavior is deliberately not identical across callers -- see the
url-6 / url-7 / url-8 dedup audits.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_WIKI_TOKEN_RE = re.compile(r"/wiki/([A-Za-z0-9]+)")
_BASE_APP_TOKEN_RE = re.compile(r"/base/([A-Za-z0-9]+)")


def parse_bitable_url(url: str) -> dict[str, str]:
    """Pure-parse a Feishu bitable share URL into its raw components.

    Returns ``{"table_id", "wiki_token", "app_token"}`` (each "" when not
    present in the URL). ``table_id`` is read from the query string only
    (via ``parse_qs``, accepting either a ``table`` or ``table_id`` param
    name) -- never by regex-scanning the whole URL text, which can
    false-positive on a `table=` that only appears in a `#fragment`.

    ``wiki_token`` / ``app_token`` are independent: a `/wiki/<token>` path
    segment populates ``wiki_token`` (resolving it to a real bitable
    app_token needs an extra IO round trip, which callers do themselves);
    a `/base/<app_token>` path segment populates ``app_token`` directly.
    When both are present (never happens on a real Feishu URL, but is
    possible on a malformed one), the historical policy across every
    caller of this parser is "wiki wins, base is the fallback" -- callers
    should check ``wiki_token`` first and only fall back to ``app_token``
    when it's empty.
    """
    parsed = urlparse(str(url or ""))
    query = parse_qs(parsed.query)
    table_id = str((query.get("table") or query.get("table_id") or [""])[0])
    wiki_match = _WIKI_TOKEN_RE.search(parsed.path)
    base_match = _BASE_APP_TOKEN_RE.search(parsed.path)
    return {
        "table_id": table_id,
        "wiki_token": wiki_match.group(1) if wiki_match else "",
        "app_token": base_match.group(1) if base_match else "",
    }
