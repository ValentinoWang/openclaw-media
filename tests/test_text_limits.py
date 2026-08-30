from __future__ import annotations

from common.text_limits import clean_to_limit


def test_clean_to_limit_joins_list_dropping_blank_items() -> None:
    assert clean_to_limit(["a", "  ", "b", "", "c"], 100) == "a b c"


def test_clean_to_limit_coerces_scalar_and_strips() -> None:
    assert clean_to_limit("  hello  ", 100) == "hello"


def test_clean_to_limit_treats_none_as_empty() -> None:
    assert clean_to_limit(None, 100) == ""


def test_clean_to_limit_hard_cuts_with_no_marker() -> None:
    assert clean_to_limit("x" * 50, 10) == "x" * 10


def test_clean_to_limit_custom_joiner() -> None:
    assert clean_to_limit(["a", "b"], 100, joiner="-") == "a-b"
