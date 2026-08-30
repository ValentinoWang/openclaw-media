"""Shared "structured value -> readable Chinese text" rendering (TC-05).

selfmedia/review/data_review.py's render_guidance_value and
selfmedia/creation/writer.py's _compact_text independently re-implement
the same recursive shape: render a dict as "key：value" lines joined by a
separator, a list as its items joined by a separator (optionally each
prefixed with a bullet), and any scalar as its stripped string form --
differing only in their separators, whether list items get a bullet
prefix, how a dict key becomes its label, whether a bool becomes a
Chinese word or falls through to Python's str(), and whether an
empty/None child is dropped before or after rendering it.

render_value is that shape, generalized. Every keyword parameter is
threaded through the function's own recursive dict/list calls, so it
applies at every nesting depth, not just the top level.
"""

from __future__ import annotations

from typing import Any, Callable


def render_value(
    value: Any,
    *,
    dict_sep: str,
    list_sep: str,
    list_bullet: str | None = None,
    label: Callable[[Any], str] = lambda key: key,
    bool_labels: tuple[str, str] | None = ("是", "否"),
    drop_empty: bool = False,
) -> str:
    """Render ``value`` as readable text.

    ``dict_sep`` / ``list_sep`` join a dict's "key：value" lines / a
    list's rendered items. ``list_bullet``, if set, prefixes each
    rendered list item (e.g. ``"- "``). ``label`` maps a dict key to its
    displayed label (identity by default). ``bool_labels``, if not
    ``None``, is the ``(true_text, false_text)`` pair a bool renders as;
    passing ``None`` instead lets a bool fall through to the scalar
    catch-all (Python's ``str(value)``, i.e. "True"/"False").

    ``drop_empty`` selects which of two child-filtering strategies a
    dict/list uses: ``False`` (the default) renders every child first
    and keeps only the ones whose rendered text came out non-empty;
    ``True`` instead drops a child up front whenever the *raw* value is
    ``None``, ``""``, or ``[]`` -- and, having done so, keeps whatever
    that child renders to even if that happens to be an empty string
    (e.g. a dict key paired with a further-empty nested dict still gets
    its own "key：" line).
    """
    if value is None:
        return ""
    if bool_labels is not None and isinstance(value, bool):
        return bool_labels[0] if value else bool_labels[1]
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            if drop_empty:
                if item in (None, "", []):
                    continue
                rendered = render_value(
                    item, dict_sep=dict_sep, list_sep=list_sep, list_bullet=list_bullet,
                    label=label, bool_labels=bool_labels, drop_empty=drop_empty,
                )
                parts.append(f"{label(key)}：{rendered}")
            else:
                rendered = render_value(
                    item, dict_sep=dict_sep, list_sep=list_sep, list_bullet=list_bullet,
                    label=label, bool_labels=bool_labels, drop_empty=drop_empty,
                )
                if rendered:
                    parts.append(f"{label(key)}：{rendered}")
        return dict_sep.join(parts)
    if isinstance(value, list):
        if drop_empty:
            items = [
                render_value(
                    item, dict_sep=dict_sep, list_sep=list_sep, list_bullet=list_bullet,
                    label=label, bool_labels=bool_labels, drop_empty=drop_empty,
                )
                for item in value
                if item not in (None, "", [])
            ]
        else:
            items = [
                rendered
                for rendered in (
                    render_value(
                        item, dict_sep=dict_sep, list_sep=list_sep, list_bullet=list_bullet,
                        label=label, bool_labels=bool_labels, drop_empty=drop_empty,
                    )
                    for item in value
                )
                if rendered
            ]
        if list_bullet:
            return list_sep.join(f"{list_bullet}{item}" for item in items)
        return list_sep.join(items)
    return str(value).strip()
