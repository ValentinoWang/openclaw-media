from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from selfmedia.deconstruct.viral_content.src.jsonable import jsonable, jsonable_model_dict


class _Status(str, Enum):
    OK = "ok"
    BAD = "bad"


class _Nested(BaseModel):
    status: _Status
    tags: list[str]


class _Model(BaseModel):
    name: str
    nested: _Nested
    items: list[_Nested]


def test_jsonable_converts_enum_to_its_value() -> None:
    assert jsonable(_Status.OK) == "ok"


def test_jsonable_recurses_through_dict_and_list() -> None:
    value = {"a": [_Status.OK, {"b": _Status.BAD}]}
    assert jsonable(value) == {"a": ["ok", {"b": "bad"}]}


def test_jsonable_passes_through_plain_values_unchanged() -> None:
    assert jsonable("text") == "text"
    assert jsonable(5) == 5
    assert jsonable(None) is None


def test_jsonable_model_dict_walks_nested_models_and_enums() -> None:
    model = _Model(
        name="n",
        nested=_Nested(status=_Status.OK, tags=["x"]),
        items=[_Nested(status=_Status.BAD, tags=[])],
    )

    result = jsonable_model_dict(model)

    assert result == {
        "name": "n",
        "nested": {"status": "ok", "tags": ["x"]},
        "items": [{"status": "bad", "tags": []}],
    }
