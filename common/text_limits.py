"""Marker-free hard-truncation to a character budget (TC-06).

``clean_to_limit`` joins a list into one line (or coerces a scalar to text),
strips it, and slices to at most ``limit`` characters with no truncation
marker appended -- the result length is always <= ``limit``, exactly.

This is a deliberately different contract from
``common/prompt_budget.py``'s ``truncate_text``/``truncate_nested`` (TC-01),
which append a marker when cutting and can therefore exceed a naive
"fits in limit" expectation by the marker's length for very small limits.
Call sites here (Feishu cell length caps, LLM-inferred field length caps)
depend on the result being at most ``limit`` characters, full stop -- do
not swap in the marked/budgeted version for these.
"""

from __future__ import annotations

from typing import Any


def clean_to_limit(value: Any, limit: int, *, joiner: str = " ") -> str:
    """Join a list (dropping empty/whitespace-only items) with ``joiner``,
    or ``str()`` a scalar; strip; hard-cut to ``limit`` characters, no marker."""
    if isinstance(value, list):
        text = joiner.join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value or "").strip()
    return text[:limit]
