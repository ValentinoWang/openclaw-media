from __future__ import annotations

from .errors import AccountAuthError


PASSWORD_MINIMUM_LENGTH = 8
PASSWORD_MAXIMUM_LENGTH = 128

_COMMON_PASSWORDS = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "abcdefgh",
        "abc12345",
        "admin123",
        "iloveyou",
        "letmein",
        "password",
        "password1",
        "password123",
        "qwerty12",
        "qwerty123",
        "qwertyui",
        "user1234",
        "welcome1",
    }
)


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not PASSWORD_MINIMUM_LENGTH <= len(password) <= PASSWORD_MAXIMUM_LENGTH:
        raise AccountAuthError(
            "invalid_request",
            f"密码长度必须为 {PASSWORD_MINIMUM_LENGTH} 至 {PASSWORD_MAXIMUM_LENGTH} 个字符。",
            status=400,
        )
    normalized = password.casefold()
    if normalized in _COMMON_PASSWORDS or len(set(normalized)) == 1:
        raise AccountAuthError("invalid_request", "密码过于常见或容易被猜测。", status=400)


__all__ = ["PASSWORD_MAXIMUM_LENGTH", "PASSWORD_MINIMUM_LENGTH", "validate_password"]
