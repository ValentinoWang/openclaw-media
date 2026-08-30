from __future__ import annotations

from common.prompt_budget import REVIEW_PROMPT_FIELDS, compact_review, compact_review_list


def test_compact_review_orders_known_fields_ahead_of_extra_metadata() -> None:
    value = {
        "adapter_internal_id": "zzz",
        "summary": "复盘摘要",
        "review_id": "rev-1",
        "extra_note": "extra",
    }

    result = compact_review(value, 200)

    keys = list(result.keys())
    assert keys.index("review_id") < keys.index("summary")
    assert keys.index("summary") < keys.index("adapter_internal_id")
    assert "extra_note" in result


def test_compact_review_drops_empty_values() -> None:
    value = {"review_id": "rev-1", "title": "", "summary": None, "metrics": []}

    result = compact_review(value, 200)

    assert result == {"review_id": "rev-1"}


def test_compact_review_stops_at_max_keys() -> None:
    value = {field: f"value-{field}" for field in REVIEW_PROMPT_FIELDS}
    value["extra_a"] = "a"
    value["extra_b"] = "b"

    result = compact_review(value, 200, max_keys=5)

    assert len(result) == 5


def test_compact_review_list_caps_item_count_and_skips_non_dicts() -> None:
    reviews = [{"review_id": f"rev-{i}"} for i in range(5)] + ["not-a-dict"]

    result = compact_review_list(reviews, 3, 200)

    assert [item["review_id"] for item in result] == ["rev-0", "rev-1", "rev-2"]


def test_compact_review_truncates_long_text_values() -> None:
    value = {"review_id": "rev-1", "summary": "x" * 500}

    result = compact_review(value, 20)

    assert len(result["summary"]) <= 20
    assert result["summary"].endswith("...[truncated]")
