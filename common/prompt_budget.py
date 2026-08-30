"""Shared character-budget truncation helpers for LLM prompt assembly (TC-01).

Several modules independently re-implemented "cut this text to at most N
characters, append a marker" -- and two of those independent
implementations had real budget-accounting bugs: one reserved only 1
character for a 3-character marker (and, for a max_chars of 0 or 1, sliced
with a negative index instead of truncating at all), another reserved 12
characters for a 3-character marker (wasting 9 characters of budget on
every truncation). selfmedia/context/media_context.py's
_truncate_context_prompt was the one implementation that got the
accounting right:

    max_chars <= 0            -> ""
    max_chars <= len(marker)  -> marker[:max_chars]
    otherwise                 -> text[:max_chars - len(marker)].rstrip() + marker

which guarantees len(result) <= max_chars always, for any marker and any
max_chars including 0 and negative values. truncate_text below is exactly
that accounting, generalized to a configurable marker.

Each call site keeps its own marker text (visually distinct truncation
suffixes: "…", "...", "...[truncated]", a Chinese "已截断" note, ...) and
its own dict-key/list-item caps -- this module shares only the mechanical
budget math, not any particular call site's specific limits or wording.
"""

from __future__ import annotations

from typing import Any


def truncate_text(value: Any, max_chars: int, *, marker: str = "…", strip: bool = True) -> str:
    """Cut ``value`` to at most ``max_chars`` characters, ending in ``marker`` if cut.

    ``value`` is coerced with ``str(value or "")`` (a falsy value, including
    ``None``, becomes ``""``); callers that need their own upfront
    whitespace stripping (most do) apply it before calling this, since
    whether "already fits, no truncation needed" text gets stripped is a
    per-call-site behavior this function does not impose.

    ``strip``: when the text must be cut, whether to ``.rstrip()`` the kept
    portion before appending ``marker`` (avoids a dangling space right
    before the marker). Every current call site wants this except one
    (viral_content's feishu_writer), which is why it is a parameter and
    not baked in.

    The result is always at most ``max_chars`` characters long, for any
    ``marker`` and any ``max_chars`` including 0 or negative.
    """
    text = str(value or "")
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= len(marker):
        return marker[:max_chars]
    body = text[: max_chars - len(marker)]
    if strip:
        body = body.rstrip()
    return body + marker


def truncate_nested(
    value: Any,
    max_chars: int,
    *,
    max_keys: int | None = 40,
    max_items: int = 20,
    marker: str = "…",
    drop_empty: bool = False,
) -> Any:
    """Recursively apply ``truncate_text`` to every string leaf of ``value``.

    Lists are capped at ``max_items`` entries. Dicts are capped at
    ``max_keys`` entries (``None`` means uncapped); when a dict is cut, a
    ``"_truncated_keys"`` receipt with the omitted-key count is added --
    unless ``max_keys`` is ``None``, in which case no cap is ever hit and no
    receipt is ever written. ``drop_empty=True`` silently omits dict items
    whose value is ``None``, ``""``, or ``[]`` instead of keeping them
    (matching selfmedia/creation/workflow.py's pre-existing behavior; the
    default ``False`` keeps them, matching every other caller).

    Non-str/list/dict leaves (numbers, bools, None, ...) pass through
    unchanged.
    """
    if isinstance(value, str):
        return truncate_text(str(value or "").strip(), max_chars, marker=marker, strip=True)
    if isinstance(value, list):
        return [
            truncate_nested(item, max_chars, max_keys=max_keys, max_items=max_items, marker=marker, drop_empty=drop_empty)
            for item in value[:max_items]
        ]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if drop_empty and item in (None, "", []):
                continue
            if max_keys is not None and index >= max_keys:
                result["_truncated_keys"] = len(value) - max_keys
                break
            result[str(key)] = truncate_nested(
                item, max_chars, max_keys=max_keys, max_items=max_items, marker=marker, drop_empty=drop_empty
            )
        return result
    return value


def truncate_list(
    value: Any,
    max_items: int,
    max_chars: int,
    *,
    max_keys: int | None = 40,
    marker: str = "…",
) -> list[Any]:
    """Cap ``value`` (if a list) at ``max_items`` entries, then ``truncate_nested`` each one."""
    items = value if isinstance(value, list) else []
    return [truncate_nested(item, max_chars, max_keys=max_keys, marker=marker) for item in items[:max_items]]


REVIEW_PROMPT_FIELDS = (
    "review_id", "created_at", "platform", "account", "track", "topic", "title",
    "summary", "lesson", "performance_level", "metrics", "atomic_facts",
    "priority_metrics", "key_insights", "metric_interpretation", "problems",
    "next_actions", "next_step", "content_guidance", "publishing_guidance",
    "data_quality_notes", "publish_url", "creation_record_id",
)
"""Review-evidence field order for prompt compaction (TC-02).

selfmedia/creation/llm_generator.py and selfmedia/creation/platform_fit.py
each carried a byte-for-byte identical copy of this tuple, plus their own
compact_review/compact_review_list pair reordering a review dict so these
fields sort ahead of arbitrary adapter metadata before truncate_nested runs
over it. llm_generator.py's version (max_items and max_chars both left to
the caller) is the one moved here; platform_fit.py's copy (item count
hardcoded to 20, key cap hardcoded to 30) still needs a caller-side
migration to the max_items=20, max_keys=30 keywords below to preserve its
exact behavior -- that edit falls outside this change's file scope and is
not done here.
"""


def compact_review(
    value: dict[str, Any],
    max_chars: int,
    *,
    max_keys: int = 40,
    max_nested_items: int = 20,
    marker: str = "...[truncated]",
    fields: tuple[str, ...] = REVIEW_PROMPT_FIELDS,
) -> dict[str, Any]:
    """Keep ``fields`` ahead of arbitrary adapter metadata, then ``truncate_nested`` each kept value.

    A key is dropped if its value is missing or empty (``None``, ``""``, or
    ``[]``); collection stops once ``max_keys`` keys have been kept, same as
    ``truncate_nested``'s own dict cap (passed through here so a review's
    top-level field count and a nested dict's field count share one limit
    by default, matching every existing call site).
    """
    keys = list(fields) + [key for key in value if key not in fields]
    result: dict[str, Any] = {}
    for key in keys:
        if key not in value or value[key] in (None, "", []):
            continue
        result[str(key)] = truncate_nested(value[key], max_chars, max_keys=max_keys, max_items=max_nested_items, marker=marker)
        if len(result) >= max_keys:
            break
    return result


def compact_review_list(
    value: Any,
    max_items: int,
    max_chars: int,
    *,
    max_keys: int = 40,
    max_nested_items: int = 20,
    marker: str = "...[truncated]",
    fields: tuple[str, ...] = REVIEW_PROMPT_FIELDS,
) -> list[dict[str, Any]]:
    """Cap ``value`` (if a list) at ``max_items`` entries, then ``compact_review`` each dict entry."""
    items = value if isinstance(value, list) else []
    return [
        compact_review(item, max_chars, max_keys=max_keys, max_nested_items=max_nested_items, marker=marker, fields=fields)
        for item in items[:max_items]
        if isinstance(item, dict)
    ]


def truncate_to_budget(value: Any, max_chars: int, *, marker: str = "...[truncated]") -> str:
    """``truncate_text`` defaulted to the "...[truncated]" marker, for a single free-text field.

    Unlike ``truncate_nested``'s leaf handling, this does not strip ``value``
    up front -- an already-within-budget value passes through byte for
    byte, matching selfmedia/creation/llm_generator.py's former
    _truncate_to_budget (whose own "fits" fast path returned the input
    unmodified).
    """
    return truncate_text(value, max_chars, marker=marker, strip=True)
