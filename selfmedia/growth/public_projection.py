"""Shared "kind + redacted digest" public-ID generator for growth projections (r11).

``projection_id`` and its text normalizer, ``projection_text``, used to be
copied verbatim (only the local names differed) into
selfmedia/growth/dashboard.py and selfmedia/growth/creation_run_detail.py.
The two-line digest shell is trivial and was never the risk; the risk is
that each module paired it with its own private ``_text`` normalizer.
``projection_text`` below is dashboard.py's richer version (bool ->
"true"/"false", list/tuple/set -> " / ".join(...) with per-item recursion,
everything else via common.social_runtime.feishu_plain_text) -- it is what
dashboard.py has always fed into its digest, and it is the one this module
exports for that purpose. A module that only needs generic display-text
coercion, not ID-stable normalization, should keep using its own text
helper rather than importing this one -- see the module-level note in
creation_run_detail.py, which intentionally keeps two different text
functions for two different jobs (id computation vs. redaction display).
"""

from __future__ import annotations

import hashlib
from typing import Any

from common.social_runtime import feishu_plain_text as _shared_feishu_plain_text


def projection_text(value: Any) -> str:
    # bool and list/tuple/set are handled here, ahead of the shared
    # renderer, and recurse through projection_text (not feishu_plain_text)
    # so a bool anywhere inside a nested list/tuple/set keeps this
    # projection's own wording at every depth: feishu_plain_text formats a
    # bool as "True"/"False" (Python's str()) and only recurses into list,
    # not tuple/set -- both differ from this projection's established
    # "true"/"false" and tuple/set-join wording, which is kept unchanged
    # rather than folded into the shared default.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return " / ".join(item for item in (projection_text(entry) for entry in value) if item)
    return _shared_feishu_plain_text(value, list_separator=" / ", unknown_dict="empty")


def projection_id(kind: str, raw_id: Any) -> str:
    """Stable, redacted "<kind>_<sha256[:16]>" reference for a public projection.

    Callers resolving an id back to its source must recompute this with the
    exact same ``kind`` and value used to mint it -- there is no reverse
    lookup, only re-hashing and comparing.
    """
    digest = hashlib.sha256(f"{kind}:{projection_text(raw_id)}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}_{digest}"
