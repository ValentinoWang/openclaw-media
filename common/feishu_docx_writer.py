"""Shared low-level helpers for reading back freshly-created Feishu docx blocks.

Consolidated from three near-duplicate copies (selfmedia/creation/writer.py,
openclaw-tag-router/scripts/sync_tag_router_docs_to_feishu.py, and
selfmedia/deconstruct/viral_content/src/feishu_doc_writer.py) -- see the
FC-07 dedup audit.

This is the auxiliary layer only: pure parsing helpers plus the two GET
primitives, each accepting an injected ``request`` transport so this module
has no opinion on which HTTP client or auth scheme a caller uses (mirrors
common/feishu_wiki_docs.py's convention). The higher-level
"create a table, hydrate its cell ids, write every cell, roll back the
whole table on any failure" orchestration (``append_table_chunk`` in two
of the three copies) is deliberately NOT included here yet -- the three
copies' rollback boundaries and root-children counting genuinely differ
(see the module docstring note below), and reconciling that safely needs
its own dedicated pass. That's a known, intentional scope cut for this
round, not an oversight.

Note for whoever picks up the orchestration layer next: writer.py's
_append_native_table_chunk computes its rollback start_index from a
single non-paginated GET of the document's root children
(_get_docx_children), while sync_tag_router_docs_to_feishu.py's
append_table_chunk uses list_root_children, which paginates through all
of them. On a document with more root children than one page, these
disagree about where "the start of this table's blocks" actually is --
that's a real correctness difference to resolve deliberately, not
something to paper over while merging. The two files' cell-text-append
helpers (append_cell_text / _append_cell_text) also differ in more than
retry policy: sync's builds blocks via paragraph_block(), which runs
expand_inline_code_literal_newlines() first; writer.py's does not.
"""

from __future__ import annotations

import time
from typing import Any, Callable

# request(method, path, *, params=None) -> parsed response body. The
# callable owns transport, auth headers, and turning a non-2xx status / a
# Feishu `code != 0` payload into a raised exception whose str() contains
# the numeric Feishu error code (e.g. "...code: 1770002...") -- that's
# what get_docx_block/get_docx_children's retry_codes matching depends on.
RequestFn = Callable[..., dict[str, Any]]

#: get_docx_block/get_docx_children's default retry_codes: Feishu's
#: "block not found yet" transient error right after creating a block.
DEFAULT_RETRY_CODES: tuple[str, ...] = ("1770002",)


def extract_block_id(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("block_id") or item.get("id") or "")
    return ""


def extract_table_cell_ids(table_block: dict[str, Any], expected: int) -> list[str]:
    table = table_block.get("table") if isinstance(table_block, dict) else {}
    candidates: list[Any] = []
    if isinstance(table, dict):
        candidates.extend(table.get("cells") or [])
    candidates.extend(table_block.get("children") or [])
    ids = [extract_block_id(item) for item in candidates]
    ids = [item for item in ids if item]
    return ids[:expected] if len(ids) >= expected else ids


def find_created_block(payload: dict[str, Any], block_type: int) -> dict[str, Any]:
    """Find the first newly-created block of ``block_type`` in a "create
    children" response payload.

    Primary path: scan the direct children list (``data.children`` /
    ``data.items``) -- the shape every known caller's payload actually
    has. Falls back to a full recursive walk of the whole payload
    (data_review.py's original, more defensive approach) for a payload
    shape where the target block isn't a direct child at the top level.
    """
    children = (payload.get("data") or {}).get("children") or (payload.get("data") or {}).get("items") or []
    for child in children:
        if isinstance(child, dict) and child.get("block_type") == block_type:
            return child

    def visit(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            if value.get("block_type") == block_type and value.get("block_id"):
                return value
            for child in value.values():
                found = visit(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found:
                    return found
        return {}

    return visit(payload)


def get_docx_block(
    document_id: str,
    block_id: str,
    *,
    request: RequestFn,
    retry_codes: tuple[str, ...] | None = DEFAULT_RETRY_CODES,
) -> dict[str, Any]:
    """GET one docx block, retrying on a transient "not found yet" error.

    ``retry_codes`` is a tuple of Feishu error-code substrings to retry on
    (30 attempts, 1s apart) -- pass ``()`` to disable retrying entirely.
    """
    retry_codes = retry_codes or ()
    last_error: Exception | None = None
    attempts = 30 if retry_codes else 1
    for attempt in range(attempts):
        try:
            payload = request("GET", f"/docx/v1/documents/{document_id}/blocks/{block_id}")
            return (payload.get("data") or {}).get("block") or payload.get("data") or {}
        except Exception as exc:
            last_error = exc
            if not any(code in str(exc) for code in retry_codes) or attempt >= attempts - 1:
                raise
            time.sleep(1.0)
    raise last_error or RuntimeError(f"failed to get block {block_id}")


def get_docx_children(
    document_id: str,
    block_id: str,
    *,
    request: RequestFn,
    retry_codes: tuple[str, ...] | None = DEFAULT_RETRY_CODES,
) -> list[dict[str, Any]]:
    """GET one docx block's children, retrying on a transient "not found yet" error.

    ``retry_codes`` is a tuple of Feishu error-code substrings to retry on
    (30 attempts, 1s apart) -- pass ``()`` to disable retrying entirely.
    """
    retry_codes = retry_codes or ()
    last_error: Exception | None = None
    attempts = 30 if retry_codes else 1
    for attempt in range(attempts):
        try:
            payload = request(
                "GET",
                f"/docx/v1/documents/{document_id}/blocks/{block_id}/children",
                params={"document_revision_id": -1},
            )
            return (payload.get("data") or {}).get("items") or (payload.get("data") or {}).get("children") or []
        except Exception as exc:
            last_error = exc
            if not any(code in str(exc) for code in retry_codes) or attempt >= attempts - 1:
                raise
            time.sleep(1.0)
    raise last_error or RuntimeError(f"failed to get block children {block_id}")
