from __future__ import annotations

import pytest

from openclaw_app.account import AccountAuthError
from openclaw_app.account.username import normalize_username


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("清华ai小王冲一级", "清华ai小王冲一级"),
        (" Creator.Name-01 ", "creator.name-01"),
        ("ＡＩ创作者", "ai创作者"),
        ("E\u0301lan", "élan"),
    ),
)
def test_normalize_username_accepts_unicode_letters_and_numbers(raw: str, expected: str) -> None:
    assert normalize_username(raw) == expected


@pytest.mark.parametrize(
    "username",
    (
        "ab",
        ".creator",
        "creator name",
        "creator@",
        "创作🚀",
        "a" * 65,
        None,
    ),
)
def test_normalize_username_rejects_values_outside_the_bounded_policy(username: object) -> None:
    with pytest.raises(AccountAuthError) as raised:
        normalize_username(username)
    assert raised.value.code == "invalid_request"


def test_registration_services_share_the_unicode_username_policy() -> None:
    from openclaw_app.account.auth import AccountAuthService
    from openclaw_app.account.lifecycle import (
        _normalize_identifier as normalize_personal_identifier,
        normalize_username as lifecycle_policy,
    )
    from openclaw_app.account.registration import AccountRegistrationService

    username = "清华ai小王冲一级"
    assert lifecycle_policy(username) == username
    assert AccountRegistrationService._normalize_username(username) == username
    assert normalize_personal_identifier(username) == username
    assert AccountAuthService._normalize_identifier(username) == username


def test_username_lookup_uses_the_same_compatibility_normalization_as_registration() -> None:
    from openclaw_app.account.auth import AccountAuthService
    from openclaw_app.account.lifecycle import _normalize_identifier as normalize_personal_identifier

    raw = "ＡＩ创作者"
    stored = normalize_username(raw)
    assert normalize_personal_identifier(raw) == stored
    assert AccountAuthService._normalize_identifier(raw) == stored
