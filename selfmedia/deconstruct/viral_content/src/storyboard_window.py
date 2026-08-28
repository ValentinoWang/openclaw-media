from __future__ import annotations

import re
from typing import Any


_UNBOUNDED_ANALYSIS_RANGES = {"", "全部", "历史未标注"}
_TIME_RANGE_PATTERN = re.compile(r"\s*(\d+(?:\.\d+)?)s?-(\d+(?:\.\d+)?)s?\s*")


def parse_explicit_analysis_time_range(value: Any) -> list[tuple[float, float]]:
    """Return requested storyboard windows, or no windows for the default scope."""
    text = str(value or "").strip()
    if text in _UNBOUNDED_ANALYSIS_RANGES:
        return []
    ranges: list[tuple[float, float]] = []
    for item in text.split(","):
        match = _TIME_RANGE_PATTERN.fullmatch(item)
        if not match:
            raise ValueError(f"analysis_time_range 格式无效: {text}")
        start, end = float(match.group(1)), float(match.group(2))
        if end <= start:
            raise ValueError("analysis_time_range 结束时间必须大于开始时间")
        ranges.append((max(0.0, start), end))
    return ranges
