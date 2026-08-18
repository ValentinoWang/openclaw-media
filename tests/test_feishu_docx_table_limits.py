from __future__ import annotations

import pytest

from common.feishu_docx_table_limits import (
    FeishuDocxTableBudgetError,
    FeishuDocxTableLimitError,
    chunk_docx_table_rows,
    ensure_docx_tables_write_budget,
    validate_docx_table_create_shape,
)


def test_live_create_shape_allows_9_by_9() -> None:
    validate_docx_table_create_shape(9, 9)


@pytest.mark.parametrize(("rows", "cols"), [(10, 1), (1, 10)])
def test_live_create_shape_rejects_known_live_failures(rows: int, cols: int) -> None:
    with pytest.raises(FeishuDocxTableLimitError):
        validate_docx_table_create_shape(rows, cols)


def test_chunk_docx_table_rows_uses_live_create_limit_with_repeated_header() -> None:
    rows = [["c1", "c2", "c3", "c4"]]
    rows.extend([[str(index), "a", "b", "c"] for index in range(1, 18)])

    chunks = chunk_docx_table_rows(rows)

    assert [len(chunk) for chunk in chunks] == [9, 9, 2]
    assert all(chunk[0] == rows[0] for chunk in chunks)


def test_cumulative_budget_counts_all_chunks() -> None:
    chunks = [
        [["c1", "c2"], ["a", "b"]],
        [["c1", "c2"], ["c", "d"]],
    ]

    with pytest.raises(FeishuDocxTableBudgetError):
        ensure_docx_tables_write_budget(chunks, budget_seconds=1)
