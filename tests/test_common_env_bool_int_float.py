from __future__ import annotations

import pytest

from common.env import env_bool, env_float, env_int


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        ("  on  ", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
        ("garbage", False),
    ],
)
def test_env_bool_accepts_known_truthy_tokens(monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool) -> None:
    monkeypatch.setenv("OPENCLAW_TEST_BOOL_FLAG", raw)
    assert env_bool("OPENCLAW_TEST_BOOL_FLAG") is expected


def test_env_bool_unset_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCLAW_TEST_BOOL_FLAG", raising=False)
    assert env_bool("OPENCLAW_TEST_BOOL_FLAG") is False
    assert env_bool("OPENCLAW_TEST_BOOL_FLAG", default=True) is True


def test_env_int_parses_and_falls_back_on_malformed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_TEST_INT", "5")
    assert env_int("OPENCLAW_TEST_INT", 2) == 5

    monkeypatch.setenv("OPENCLAW_TEST_INT", "not-a-number")
    assert env_int("OPENCLAW_TEST_INT", 2) == 2

    monkeypatch.delenv("OPENCLAW_TEST_INT", raising=False)
    assert env_int("OPENCLAW_TEST_INT", 2) == 2


def test_env_int_strict_raises_on_malformed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_TEST_INT", "not-a-number")
    with pytest.raises(ValueError):
        env_int("OPENCLAW_TEST_INT", 2, strict=True)


def test_env_float_parses_and_falls_back_on_malformed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_TEST_FLOAT", "1.5")
    assert env_float("OPENCLAW_TEST_FLOAT", 0.5) == 1.5

    monkeypatch.setenv("OPENCLAW_TEST_FLOAT", "not-a-number")
    assert env_float("OPENCLAW_TEST_FLOAT", 0.5) == 0.5


def test_env_float_strict_raises_on_malformed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_TEST_FLOAT", "not-a-number")
    with pytest.raises(ValueError):
        env_float("OPENCLAW_TEST_FLOAT", 0.5, strict=True)


def test_llm_settings_re_exports_env_helpers() -> None:
    from common import llm_settings

    assert llm_settings.env_bool is env_bool
    assert llm_settings.env_int is env_int
    assert llm_settings.env_float is env_float
