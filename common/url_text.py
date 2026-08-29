"""Shared helpers for pulling URLs out of free-form text.

Consolidates several byte-similar implementations that had drifted apart
(``selfmedia/growth/contracts.py``, ``common/social_runtime.py``,
``openclaw-tag-router/scripts/cleanup_creation_runs.py``). The character
class and trailing-punctuation set below are the union of what those
copies used, so this is the most permissive (and most correct) of the
group — see the url-2 dedup audit for the rationale.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# Characters that stop a URL match outright. Taken from
# selfmedia/growth/contracts.py, which had the most complete class.
_URL_PATTERN = re.compile(r"https?://[^\s<>\]\)\"'，。；、]+")

# Trailing punctuation to strip off a matched URL after the fact (covers
# punctuation that the char class above does not itself exclude, e.g. the
# full-width closing paren "）" or bracket "】").
_TRAILING_PUNCTUATION = ".,;:!?，。；：！？、）)]】》"


def extract_urls(text: str) -> tuple[str, ...]:
    """Return the deduped URLs found in ``text``, in order of appearance."""
    urls: list[str] = []
    for match in _URL_PATTERN.finditer(str(text or "")):
        url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if url and url not in urls:
            urls.append(url)
    return tuple(urls)


def extract_urls_from_values(values: Iterable[str]) -> list[str]:
    """Extract URLs from an iterable of text blobs, deduped across all of them.

    Mirrors the historical ``common.social_runtime.extract_urls(values)``
    signature (a sequence of strings in, a flat deduped list out).
    """
    seen: set[str] = set()
    urls: list[str] = []
    for value in values:
        for url in extract_urls(value):
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def extract_urls_deep(value: Any) -> list[str]:
    """Recursively pull URLs out of a possibly-nested dict/list/str structure.

    Mirrors ``cleanup_creation_runs.py``'s recursive ``extract_urls``: for
    dicts, only the ``link``/``url``/``text`` keys are considered.
    """
    result: list[str] = []
    if isinstance(value, dict):
        for key in ("link", "url", "text"):
            result.extend(extract_urls_deep(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            result.extend(extract_urls_deep(item))
    elif isinstance(value, str):
        result.extend(extract_urls(value))
    seen: set[str] = set()
    unique: list[str] = []
    for item in result:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def first_url(text: str) -> str:
    """Return the first URL found in ``text``, or ``""`` if none."""
    urls = extract_urls(text)
    return urls[0] if urls else ""
