from __future__ import annotations

import unicodedata

from .errors import AccountAuthError


_USERNAME_PUNCTUATION = frozenset("._-")


def canonicalize_username(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.strip()).casefold()
    return unicodedata.normalize("NFC", normalized)


def _is_username_start(character: str) -> bool:
    return unicodedata.category(character)[0] in {"L", "N"}


def _is_username_continuation(character: str) -> bool:
    return (
        _is_username_start(character)
        or unicodedata.category(character)[0] == "M"
        or character in _USERNAME_PUNCTUATION
    )


def normalize_username(value: object) -> str:
    if not isinstance(value, str):
        raise AccountAuthError("invalid_request", "用户名格式无效。", status=400)
    normalized = canonicalize_username(value)
    if (
        not 3 <= len(normalized) <= 64
        or not _is_username_start(normalized[0])
        or not all(_is_username_continuation(character) for character in normalized[1:])
    ):
        raise AccountAuthError("invalid_request", "用户名格式无效。", status=400)
    return normalized
