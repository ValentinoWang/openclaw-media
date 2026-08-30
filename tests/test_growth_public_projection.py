from __future__ import annotations

from selfmedia.growth.public_projection import projection_id, projection_text


def test_projection_text_renders_bool_lowercase() -> None:
    assert projection_text(True) == "true"
    assert projection_text(False) == "false"


def test_projection_text_joins_list_tuple_set_with_slash() -> None:
    assert projection_text(["a", "b"]) == "a / b"
    assert projection_text(("a", "b")) == "a / b"


def test_projection_text_recurses_bool_inside_list() -> None:
    assert projection_text([True, "x"]) == "true / x"


def test_projection_id_is_stable_for_the_same_input() -> None:
    assert projection_id("run", "abc") == projection_id("run", "abc")


def test_projection_id_differs_by_kind() -> None:
    assert projection_id("run", "abc") != projection_id("review", "abc")


def test_projection_id_has_expected_shape() -> None:
    result = projection_id("asset", "xyz")
    prefix, _, digest = result.partition("_")
    assert prefix == "asset"
    assert len(digest) == 16
