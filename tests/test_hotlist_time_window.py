from __future__ import annotations

from datetime import datetime

import pytest

from selfmedia.hotlist.service import HotlistValidationError, SHANGHAI_TZ, parse_time_window


def test_invalid_time_window_explains_the_date_range_format_without_a_stale_example() -> None:
    with pytest.raises(HotlistValidationError, match="YYYY-MM-DD至YYYY-MM-DD") as exc_info:
        parse_time_window("上个月中旬", now=datetime(2026, 8, 29, tzinfo=SHANGHAI_TZ))

    assert "2026-07-01" not in str(exc_info.value)
