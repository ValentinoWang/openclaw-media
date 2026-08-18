from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any


MAX_PLATFORM_HASHTAGS = 30
MAX_PLATFORM_HASHTAG_LENGTH = 64

_HASHTAG_CHARS = r"\w\u3400-\u4dbf\u4e00-\u9fff-"
# Match the complete token first.  Applying the length check to a bounded
# regex would silently persist the first 64 characters of an overlong token.
_EXPLICIT_HASHTAG = re.compile(
    rf"(?<![#＃])[#＃](?P<tag>[{_HASHTAG_CHARS}]+)",
    re.UNICODE,
)
_NORMALIZED_HASHTAG = re.compile(
    rf"[{_HASHTAG_CHARS}]{{1,{MAX_PLATFORM_HASHTAG_LENGTH}}}",
    re.UNICODE,
)


def _items(value: Any) -> Iterable[Any]:
    if value is None or (isinstance(value, str) and value == ""):
        return ()
    if isinstance(value, Mapping):
        for key in ("name", "text", "value", "label"):
            if key in value:
                return _items(value[key])
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        flattened: list[Any] = []
        for item in value:
            flattened.extend(_items(item))
        return flattened
    return (value,)


def normalize_platform_hashtags(value: Any) -> list[str]:
    """Normalize structured platform hashtag values without inferring topics."""

    normalized: list[str] = []
    seen: set[str] = set()
    for item in _items(value):
        if not isinstance(item, str):
            continue
        hashtag = unicodedata.normalize("NFKC", item).strip()
        hashtag = hashtag.lstrip("#＃").strip()
        if not _NORMALIZED_HASHTAG.fullmatch(hashtag):
            continue
        identity = hashtag.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(hashtag)
        if len(normalized) >= MAX_PLATFORM_HASHTAGS:
            break
    return normalized


def extract_platform_hashtags(*source_texts: Any) -> list[str]:
    """Extract only explicit ``#topic`` tokens from captured source text."""

    matches: list[str] = []
    for source_text in source_texts:
        if not isinstance(source_text, str) or (
            "#" not in source_text and "＃" not in source_text
        ):
            continue
        text = unicodedata.normalize("NFKC", source_text)
        for match in _EXPLICIT_HASHTAG.finditer(text):
            hashtag = match.group("tag")
            if len(hashtag) <= MAX_PLATFORM_HASHTAG_LENGTH:
                matches.append(hashtag)
    return normalize_platform_hashtags(matches)


def resolve_platform_hashtags(
    structured_hashtags: Any,
    *source_texts: Any,
) -> list[str]:
    """Prefer explicit structured source hashtags, otherwise parse source text."""

    structured = normalize_platform_hashtags(structured_hashtags)
    if structured:
        return structured
    return extract_platform_hashtags(*source_texts)


__all__ = [
    "MAX_PLATFORM_HASHTAGS",
    "MAX_PLATFORM_HASHTAG_LENGTH",
    "extract_platform_hashtags",
    "normalize_platform_hashtags",
    "resolve_platform_hashtags",
]
