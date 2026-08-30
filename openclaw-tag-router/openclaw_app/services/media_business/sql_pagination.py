"""Shared SQL text for tenant-scoped keyset pagination (gap1 audit).

Six modules (tracks, publishing, assets, runs, admin_tenants, decisions)
independently wrote the same ``CAST(%s AS timestamptz) IS NULL OR ts <
%s OR (ts = %s AND id > %s)`` WHERE-fragment plus a matching ``ORDER BY
ts DESC, id ASC`` / ``LIMIT %s`` tail, differing only in which table
alias, timestamp column, and tiebreak column they used. This module is
deliberately separate from ``foundation.py``, which stays SQL-free (it is
the package's provider-independent layer) -- this one is not.

``keyset_window`` returns the exact text every call site had inlined --
generated text is byte-identical to what it replaces, so no query plan,
index usage, or test-substring assertion moves. ``keyset_params`` builds
the matching 4-value parameter tuple the fragment's four ``%s``
placeholders bind against.
"""

from __future__ import annotations

from typing import Any


def keyset_window(
    alias: str,
    ts_column: str,
    id_column: str,
    *,
    and_indent: str = "          ",
    inner_indent: str = "            ",
    tail_indent: str = "        ",
    closing_indent: str = "    ",
    include_tail: bool = True,
) -> str:
    """The WHERE-fragment + ORDER BY + LIMIT tail shared by every keyset-
    paginated list query in this package.

    ``alias`` is the table alias INCLUDING its trailing dot (e.g. ``"t."``),
    or ``""`` for queries with no alias (runs.py). Meant to be spliced in
    with an f-string immediately after the query's own ``AND (`` block (or
    directly after ``WHERE ... = %s``), with the closing ``\"\"\"`` placed
    right after the call -- see any of the eight class-body call sites this
    was extracted from for the exact splice point and the default
    indentation. The four ``*_indent`` keywords exist only because
    admin_tenants.py's module-level query constants use a different (much
    shallower) indentation style than the class-body queries do; pass its
    own indentation there to keep the generated SQL text byte-identical to
    what it replaces rather than forcing a reformat.

    ``include_tail=False`` returns just the ``AND (...)`` fragment (through
    its closing paren and trailing newline), omitting the ``ORDER
    BY``/``LIMIT`` tail -- for decisions.py's ``_SIGNAL_LIST_QUERY``, whose
    first ``UNION ALL`` branch repeats the fragment but only the final
    branch carries the shared ORDER BY/LIMIT.
    """
    column = f"{alias}{ts_column}"
    tiebreak = f"{alias}{id_column}"
    fragment = (
        f"{and_indent}AND (\n"
        f"{inner_indent}CAST(%s AS timestamptz) IS NULL\n"
        f"{inner_indent}OR {column} < %s\n"
        f"{inner_indent}OR ({column} = %s AND {tiebreak} > %s)\n"
        f"{and_indent})\n"
    )
    if not include_tail:
        return fragment
    return fragment + (
        f"{tail_indent}ORDER BY {column} DESC, {tiebreak} ASC\n"
        f"{tail_indent}LIMIT %s\n"
        f"{closing_indent}"
    )


def keyset_params(ts: Any, id_value: Any, *, no_position_id: Any = "") -> tuple[Any, Any, Any, Any]:
    """The (ts, ts, ts, id) 4-tuple ``keyset_window()``'s WHERE-fragment
    binds. Pass ``ts=None`` for the first page (no cursor position yet) --
    ``id_value`` is ignored in that case and ``no_position_id`` is used for
    the tiebreak param instead. ``no_position_id`` defaults to ``""``,
    matching tracks/publishing/assets/runs' convention; admin_tenants.py's
    two call sites pass ``no_position_id=None`` instead, matching what they
    always passed (the SQL result is identical either way -- the tiebreak
    branch is unreachable once the leading ``CAST(%s AS timestamptz) IS
    NULL`` check is true -- but the exact parameter value is preserved
    rather than assumed harmless). Otherwise pass the decoded position's
    timestamp and id/public_id values verbatim.
    """
    if ts is None:
        return None, None, None, no_position_id
    return ts, ts, ts, id_value
