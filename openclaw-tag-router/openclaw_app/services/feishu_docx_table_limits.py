from __future__ import annotations

from dataclasses import dataclass


FEISHU_DOCX_TABLE_MAX_COLUMNS = 100
FEISHU_DOCX_TABLE_MAX_CELLS = 2000
FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_ROWS = 9
FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_COLUMNS = 9
FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_CELLS = 81
FEISHU_DOCX_BLOCK_WRITE_QPS = 3
FEISHU_DOCX_TABLE_DEFAULT_WRITE_BUDGET_SECONDS = 1500


class FeishuDocxTableLimitError(ValueError):
    pass


class FeishuDocxTableBudgetError(ValueError):
    pass


@dataclass(frozen=True)
class FeishuDocxTableWriteEstimate:
    non_empty_cells: int
    request_count: int
    minimum_seconds: float
    budget_seconds: float


def validate_docx_table_official_shape(row_count: int, column_count: int) -> None:
    if row_count < 1:
        raise FeishuDocxTableLimitError("Feishu Docx table row_size must be positive")
    if column_count < 1:
        raise FeishuDocxTableLimitError("Feishu Docx table column_size must be positive")
    if column_count > FEISHU_DOCX_TABLE_MAX_COLUMNS:
        raise FeishuDocxTableLimitError(
            f"Feishu Docx table column_size exceeds {FEISHU_DOCX_TABLE_MAX_COLUMNS}: {column_count}"
        )
    cell_count = row_count * column_count
    if cell_count > FEISHU_DOCX_TABLE_MAX_CELLS:
        raise FeishuDocxTableLimitError(
            f"Feishu Docx table cell count exceeds {FEISHU_DOCX_TABLE_MAX_CELLS}: {cell_count}"
        )


def validate_docx_table_create_shape(row_count: int, column_count: int) -> None:
    validate_docx_table_official_shape(row_count, column_count)
    if row_count > FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_ROWS:
        raise FeishuDocxTableLimitError(
            "Feishu Docx table row_size exceeds live create limit "
            f"{FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_ROWS}: {row_count}"
        )
    if column_count > FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_COLUMNS:
        raise FeishuDocxTableLimitError(
            "Feishu Docx table column_size exceeds live create limit "
            f"{FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_COLUMNS}: {column_count}"
        )
    cell_count = row_count * column_count
    if cell_count > FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_CELLS:
        raise FeishuDocxTableLimitError(
            "Feishu Docx table cell count exceeds live create limit "
            f"{FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_CELLS}: {cell_count}"
        )


def max_docx_table_rows(column_count: int) -> int:
    validate_docx_table_official_shape(1, column_count)
    if column_count > FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_COLUMNS:
        raise FeishuDocxTableLimitError(
            "Feishu Docx table column_size exceeds live create limit "
            f"{FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_COLUMNS}: {column_count}"
        )
    official_rows = FEISHU_DOCX_TABLE_MAX_CELLS // column_count
    live_rows = FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_CELLS // column_count
    return min(FEISHU_DOCX_TABLE_LIVE_CREATE_MAX_ROWS, official_rows, live_rows)


def max_docx_table_rows_for_cell_writer(
    column_count: int,
    *,
    budget_seconds: float = FEISHU_DOCX_TABLE_DEFAULT_WRITE_BUDGET_SECONDS,
    requests_per_non_empty_cell: int = 1,
) -> int:
    shape_rows = max_docx_table_rows(column_count)
    per_row_requests = column_count * max(1, requests_per_non_empty_cell)
    budget_rows = int((float(budget_seconds) * FEISHU_DOCX_BLOCK_WRITE_QPS) // per_row_requests)
    return max(1, min(shape_rows, budget_rows))


def chunk_docx_table_rows(rows: list[list[str]]) -> list[list[list[str]]]:
    if not rows:
        return []
    column_count = max(len(row) for row in rows)
    max_rows = max_docx_table_rows(column_count)
    if len(rows) <= max_rows:
        validate_docx_table_create_shape(len(rows), column_count)
        return [rows]
    header = rows[0]
    data_rows = rows[1:]
    data_rows_per_chunk = max(1, max_rows - 1)
    return [
        [header, *data_rows[index:index + data_rows_per_chunk]]
        for index in range(0, len(data_rows), data_rows_per_chunk)
    ]


def count_non_empty_cells(rows: list[list[str]]) -> int:
    return sum(1 for row in rows for cell in row if str(cell or "").strip())


def estimate_cell_write_requests(non_empty_cell_count: int) -> int:
    return max(0, int(non_empty_cell_count))


def estimate_min_write_seconds(request_count: int) -> float:
    return estimate_cell_write_requests(request_count) / FEISHU_DOCX_BLOCK_WRITE_QPS


def estimate_docx_table_write(
    rows: list[list[str]],
    *,
    budget_seconds: float = FEISHU_DOCX_TABLE_DEFAULT_WRITE_BUDGET_SECONDS,
    requests_per_non_empty_cell: int = 1,
) -> FeishuDocxTableWriteEstimate:
    non_empty_cells = count_non_empty_cells(rows)
    request_count = estimate_cell_write_requests(non_empty_cells * max(1, requests_per_non_empty_cell))
    minimum_seconds = estimate_min_write_seconds(request_count)
    return FeishuDocxTableWriteEstimate(
        non_empty_cells=non_empty_cells,
        request_count=request_count,
        minimum_seconds=minimum_seconds,
        budget_seconds=float(budget_seconds),
    )


def ensure_docx_table_write_budget(
    rows: list[list[str]],
    *,
    budget_seconds: float = FEISHU_DOCX_TABLE_DEFAULT_WRITE_BUDGET_SECONDS,
    requests_per_non_empty_cell: int = 1,
) -> FeishuDocxTableWriteEstimate:
    estimate = estimate_docx_table_write(
        rows,
        budget_seconds=budget_seconds,
        requests_per_non_empty_cell=requests_per_non_empty_cell,
    )
    if estimate.minimum_seconds > estimate.budget_seconds:
        raise FeishuDocxTableBudgetError(
            "Feishu Docx table cell writes exceed budget: "
            f"requests={estimate.request_count} min_seconds={estimate.minimum_seconds:.1f} "
            f"budget_seconds={estimate.budget_seconds:.1f}"
        )
    return estimate


def ensure_docx_tables_write_budget(
    table_chunks: list[list[list[str]]],
    *,
    budget_seconds: float = FEISHU_DOCX_TABLE_DEFAULT_WRITE_BUDGET_SECONDS,
    requests_per_non_empty_cell: int = 1,
) -> FeishuDocxTableWriteEstimate:
    non_empty_cells = sum(count_non_empty_cells(rows) for rows in table_chunks)
    request_count = estimate_cell_write_requests(non_empty_cells * max(1, requests_per_non_empty_cell))
    minimum_seconds = estimate_min_write_seconds(request_count)
    estimate = FeishuDocxTableWriteEstimate(
        non_empty_cells=non_empty_cells,
        request_count=request_count,
        minimum_seconds=minimum_seconds,
        budget_seconds=float(budget_seconds),
    )
    if estimate.minimum_seconds > estimate.budget_seconds:
        raise FeishuDocxTableBudgetError(
            "Feishu Docx table cell writes exceed cumulative budget: "
            f"requests={estimate.request_count} min_seconds={estimate.minimum_seconds:.1f} "
            f"budget_seconds={estimate.budget_seconds:.1f}"
        )
    return estimate


def sleep_seconds_for_docx_write() -> float:
    return 1.0 / FEISHU_DOCX_BLOCK_WRITE_QPS
