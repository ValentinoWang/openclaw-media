"""Shared reserved-field-name scanning for client-supplied claim/payload bodies.

Two call sites independently re-implement "does this client-supplied
structure try to self-declare a field that must only ever be server-
resolved" -- stage2_context._reject_browser_claims (browser session
claims, checking only the top level) and
media_web_tasks_core._contains_reserved_tenant_key (IF2 task payloads,
recursing into nested dicts/lists). Their field tables are deliberately
different (_FORBIDDEN_BROWSER_FIELDS vs. RESERVED_TENANT_KEYS) and this
module does not merge them -- only the traversal algorithm is shared.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import AbstractSet, Any


def find_reserved_keys(
    value: Any,
    reserved: AbstractSet[str],
    *,
    recursive: bool = True,
) -> list[str]:
    """Return the reserved field names found in ``value``, sorted.

    ``recursive=True`` (default) descends into dict values and list/tuple
    items -- media_web_tasks_core._contains_reserved_tenant_key's original
    algorithm. ``recursive=False`` only inspects the top-level mapping's
    keys and never looks at any value -- stage2_context._reject_browser_claims's
    original algorithm. Passing the wrong one grants (or removes) recursive
    scanning power a caller did not have before, so callers must choose
    explicitly rather than rely on the default when replicating an existing
    call site.
    """
    found: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key) in reserved:
                    found.add(str(key))
                if recursive:
                    walk(child)
        elif recursive and isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)
    return sorted(found)
