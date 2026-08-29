"""Shared secret-bearing key detection for production contract modules.

`production_release_manifest.py` and `production_reconciliation_planner.py`
both need to answer the same narrow question -- "does this field name look
like it carries a secret?" -- before they will accept or serialize a key.
This module is the single, shared answer to that question so the two
independently-audited modules cannot silently drift apart on it again.

Nothing else about the two modules is unified here: their JSON-shape
strictness (`_plain_json` vs. `_json_copy`) and *when* they bother to ask
this question (allow-listed-keys-only vs. every key) are deliberately
different policies that live in their own modules.
"""

from __future__ import annotations

import re

_SECRET_KEY_RE = re.compile(
    r"(?:access[_-]?token|api[_-]?key|credential|cookie|password|passwd|private[_-]?key|secret|token)",
    re.IGNORECASE,
)


def is_secret_key(key: str) -> bool:
    """Return True when `key` looks like it names a secret-bearing field."""

    return bool(_SECRET_KEY_RE.search(key))


__all__ = ["is_secret_key"]
