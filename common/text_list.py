"""Shared "value -> list of text items" splitting (TC-07, group A only).

selfmedia/creation/llm_generator.py and selfmedia/creation/platform_fit.py
independently re-implement the exact same _as_list shape: None/""/[] ->
[]; a list -> its items filtered by identity against (None, "", [])
(items are NOT stringified -- a list already containing non-string
values passes them through as-is); a string -> split on
r"[\\n,，、;；]+" and each fragment stripped, empty fragments dropped;
anything else -> wrapped as a single-item list. split_text_list is that
shape, taken verbatim from llm_generator.py's former _as_list.

string_list is llm_generator.py's former _as_string_list: split_text_list,
then each item coerced with str(item or "") and stripped, empty results
dropped. Its default strip_chars=" #\\t" (not just whitespace) matches
llm_generator.py's own choice; platform_fit.py's own _as_string_list
never stripped "#" and is not changed to.

selfmedia/context/media_context.py's own _as_list is a materially
different function (it stringifies list/tuple items rather than passing
them through, supports tuple input, and stringify-then-splits even a
non-string, non-list/tuple scalar) and is not migrated onto
split_text_list/string_list wholesale -- only the one fragment of it
that is byte-identical (splitting an already-cleaned string on the same
delimiter pattern) delegates here; see media_context.py's own _as_list
for the rest, kept local.
"""

from __future__ import annotations

import re
from typing import Any


def split_text_list(
    value: Any,
    *,
    delimiters: str = r"[\n,，、;；]+",
    strip_chars: str | None = None,
) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [])]
    if isinstance(value, str):
        return [item.strip(strip_chars) for item in re.split(delimiters, value) if item.strip(strip_chars)]
    return [value]


def string_list(value: Any, *, strip_chars: str | None = " #\t") -> list[str]:
    result: list[str] = []
    for item in split_text_list(value):
        text = str(item or "").strip(strip_chars)
        if text:
            result.append(text)
    return result
