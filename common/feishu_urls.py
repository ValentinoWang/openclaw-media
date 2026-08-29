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

import os
import re
from urllib.parse import parse_qs, unquote, urlparse

_WIKI_TOKEN_RE = re.compile(r"/wiki/([A-Za-z0-9]+)")
_BASE_APP_TOKEN_RE = re.compile(r"/base/([A-Za-z0-9]+)")

# The single source of truth for "is this host a Feishu/Lark document host".
# tenant_owned_resources.py and media_business/overview.py both import this
# rather than keeping their own copies.
DEFAULT_FEISHU_DOC_HOSTS: tuple[str, ...] = ("feishu.cn", "larksuite.com", "larkoffice.com")

_DOC_TOKEN_KIND_SEGMENTS = {"docx": "docx", "doc": "docx", "docs": "docx", "wiki": "wiki"}
_DOC_TOKEN_QUERY_KEYS = (
    ("docx", "docx"),
    ("doc_token", "docx"),
    ("document_id", "docx"),
    ("wiki", "wiki"),
    ("wiki_id", "wiki"),
)
_DOC_TOKEN_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_-]")
_BARE_TOKEN_PREFIXES = ("dox", "doc")


def _host_allowed(host: str, hosts: tuple[str, ...] | None) -> bool:
    """True iff ``host`` equals, or is a dot-suffix subdomain of, one of ``hosts``.

    ``hosts=None`` means "skip the check" (any host, including no host at
    all, is accepted) -- used by callers that historically never validated
    a host and aren't being tightened this round for lack of test coverage
    over real production doc_link data.
    """
    if hosts is None:
        return True
    host = host.lower()
    if not host:
        return False
    for allowed in hosts:
        allowed = allowed.lower()
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def parse_feishu_document_ref(
    url: str,
    *,
    allow_bare_token: bool = False,
    hosts: tuple[str, ...] | None = DEFAULT_FEISHU_DOC_HOSTS,
) -> dict[str, str] | None:
    """Pure-parse a Feishu document share URL into ``{"kind", "token"}``.

    ``kind`` is ``"docx"`` (path segment `docx`/`doc`/`docs`, or query key
    `docx`/`doc_token`/`document_id`) or ``"wiki"`` (path segment `wiki`,
    or query key `wiki`/`wiki_id`). Scans every path segment (not just the
    last two) and unquotes each one, then falls back to query keys -- the
    most complete of the several near-duplicate implementations this was
    consolidated from (see feishu_service.py's former ``_parse_document_url``).

    Returns ``None`` when nothing matches, the URL has no path/query hit,
    or (when ``hosts`` is a tuple) the host isn't on the allowlist.

    ``allow_bare_token=True`` additionally accepts a bare token string with
    no URL structure at all, as long as it starts with ``"dox"`` or
    ``"doc"`` (retrieval.py's historical passthrough for a raw docx token);
    default is off since most callers pass an actual URL.
    """
    raw = str(url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if _host_allowed(parsed.netloc.lower(), hosts):
        segments = [unquote(item) for item in parsed.path.split("/") if item]
        for index, segment in enumerate(segments):
            normalized = segment.lower()
            if normalized in _DOC_TOKEN_KIND_SEGMENTS and index + 1 < len(segments):
                kind = _DOC_TOKEN_KIND_SEGMENTS[normalized]
                token = _DOC_TOKEN_SANITIZE_RE.sub("", segments[index + 1])
                if token:
                    return {"kind": kind, "token": token}
        query = parse_qs(parsed.query)
        for key, kind in _DOC_TOKEN_QUERY_KEYS:
            values = query.get(key) or []
            if values:
                token = _DOC_TOKEN_SANITIZE_RE.sub("", values[0])
                if token:
                    return {"kind": kind, "token": token}
    if allow_bare_token and raw.startswith(_BARE_TOKEN_PREFIXES):
        return {"kind": "docx", "token": raw}
    return None


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


def _resolve_feishu_doc_base(base: str | None) -> str:
    """Resolve the web (not open-platform-API) base URL for a Feishu link.

    Order: explicit ``base`` argument, then the ``FEISHU_DOC_BASE_URL``
    environment variable, then a ``RuntimeError``. Deliberately has no
    hardcoded fallback -- ``https://open.feishu.cn`` (the API domain, not
    the docs web domain) used to be the default here and produced dead
    links; fail fast instead of silently building another broken one.
    """
    explicit = str(base or "").strip().rstrip("/")
    if explicit:
        return explicit
    from_env = os.getenv("FEISHU_DOC_BASE_URL", "").strip().rstrip("/")
    if from_env:
        return from_env
    raise RuntimeError(
        "no Feishu document base URL configured -- pass base= explicitly or "
        "set the FEISHU_DOC_BASE_URL environment variable "
        "(e.g. https://your-tenant.feishu.cn)"
    )


def feishu_doc_url(kind: str, token: str, *, base: str | None = None) -> str:
    """Build a Feishu document web URL, e.g. ``{base}/docx/{token}``."""
    resolved_base = _resolve_feishu_doc_base(base)
    path = "wiki" if kind == "wiki" else "docx"
    return f"{resolved_base}/{path}/{token}"


def feishu_bitable_url(app_token: str, table_id: str, *, base: str | None = None) -> str:
    """Build a Feishu bitable web URL, e.g. ``{base}/base/{app_token}?table={table_id}``."""
    resolved_base = _resolve_feishu_doc_base(base)
    return f"{resolved_base}/base/{app_token}?table={table_id}"
