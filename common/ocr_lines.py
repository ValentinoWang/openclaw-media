"""Shared line-level OCR text cleanup (TC-03).

selfmedia/deconstruct/viral_content/src/evidence/ocr.py,
selfmedia/ingest/content_flow/src/pipeline.py, and
openclaw-tag-router/openclaw_app/router/activity_daily.py each
independently re-implemented the same "adjacent-duplicate-line" cleanup:
treat a form-feed as a newline, collapse each line's internal whitespace,
drop empty lines, and drop a line that is an exact repeat of the line
immediately before it.

This is a *narrower* pass than
openclaw_app.services.media_text_cleaner.MediaTextCleaner.clean_ocr_for_copy,
which additionally drops noise tokens, normalizes common OCR
misrecognitions, and dedupes globally (not just adjacent repeats) -- that
is a deliberately different, second-stage cleanup and is not folded into
this function; the two coexist.
"""

from __future__ import annotations


def clean_ocr_lines(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw in str(text or "").replace("\f", "\n").splitlines():
        line = " ".join(raw.split()).strip()
        if not line or line == previous:
            continue
        previous = line
        lines.append(line)
    return "\n".join(lines).strip()
