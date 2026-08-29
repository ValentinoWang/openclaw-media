"""Shared primitives for "find-or-create a same-title child doc under a wiki node".

This module consolidates four previously independent copies of the same
find/create-under-wiki-parent logic (selfmedia/creation/writer.py,
selfmedia/creator_profiles/docs_builder.py,
selfmedia/deconstruct/viral_content/src/feishu_doc_writer.py, and the
"query" half of openclaw-tag-router's FeishuService._find_knowledge_child_node).

HTTP transport is injected via a `request` callable so this module has no
opinion on which HTTP client or auth scheme a caller uses (selfmedia call
sites use the `requests` library directly; openclaw-tag-router injects
`FeishuService._request`, which already owns auth/session handling).

``WikiDoc.created`` has exactly one meaning everywhere in this codebase:
``True`` means this call newly created the document, ``False`` means an
existing document was found and reused. Do not reintroduce the inverted
convention that selfmedia/creator_profiles/docs_builder.py used to have
(there, the third tuple element used to mean "reused").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator

# request(method, path, *, params=None, json=None) -> parsed response body.
# The callable owns transport, auth headers, and turning a non-2xx status /
# a Feishu `code != 0` payload into a raised exception -- this module only
# ever sees an already-successful, already-parsed JSON dict back.
RequestFn = Callable[..., dict[str, Any]]

DEFAULT_OBJ_TYPES = frozenset({"docx", "doc"})


@dataclass(frozen=True)
class WikiDoc:
    document_id: str
    node_token: str
    created: bool  # True = newly created this call; False = reused an existing doc.


def clean_wiki_title(value: Any) -> str:
    """Normalize a title for comparison/submission.

    Mirrors FeishuService._safe_text_content (normalize CRLF, strip trailing
    whitespace) rather than a plain .strip(), since that is the most
    thorough cleaning among the four prior implementations.
    """
    text = str(value or "")
    return text.replace("\r\n", "\n").rstrip()


def get_wiki_node(node_token: str, *, request: RequestFn) -> dict[str, Any]:
    """GET /wiki/v2/spaces/get_node and return the `node` dict.

    This is the same "resolve one wiki node's metadata" call that used to be
    duplicated verbatim as writer.py::_get_wiki_node,
    feishu_doc_writer.py::_wiki_node, and docs_builder.py::get_wiki_node.
    """
    data = request("GET", "/wiki/v2/spaces/get_node", params={"token": node_token})
    node = data.get("data", {}).get("node") if isinstance(data, dict) else None
    return node if isinstance(node, dict) else {}


def resolve_wiki_space_id(
    parent_node_token: str,
    *,
    request: RequestFn,
    knowledge_base_spaces: list[dict[str, str]] | None = None,
) -> str:
    """Resolve the space_id that owns `parent_node_token`.

    Falls back to a configured `knowledge_base_spaces` list (matched on
    parent_node_token) when the node lookup itself doesn't carry space_id,
    matching FeishuService._knowledge_space_id_for_parent_node.
    """
    node = get_wiki_node(parent_node_token, request=request)
    space_id = str(node.get("space_id") or "").strip()
    if space_id:
        return space_id
    for item in knowledge_base_spaces or []:
        if item.get("parent_node_token") == parent_node_token and item.get("space_id"):
            return str(item["space_id"])
    raise RuntimeError("目标知识库节点缺少 space_id")


def iter_wiki_children(
    space_id: str,
    parent_node_token: str,
    *,
    request: RequestFn,
    page_size: int = 50,
) -> Iterator[dict[str, Any]]:
    """Yield every child node dict under parent_node_token, paging as needed."""
    page_token = ""
    while True:
        params: dict[str, Any] = {"parent_node_token": parent_node_token, "page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        data = request("GET", f"/wiki/v2/spaces/{space_id}/nodes", params=params)
        payload = data.get("data", {}) if isinstance(data, dict) else {}
        items = payload.get("items") if isinstance(payload, dict) else None
        for item in items or []:
            if isinstance(item, dict):
                yield item
        if not isinstance(payload, dict) or not payload.get("has_more"):
            return
        next_token = str(payload.get("page_token") or "").strip()
        if not next_token:
            return
        page_token = next_token


def find_wiki_child_doc(
    space_id: str,
    parent_node_token: str,
    title: str,
    *,
    request: RequestFn,
    obj_types: frozenset[str] = DEFAULT_OBJ_TYPES,
    pick: str = "first",
) -> WikiDoc | None:
    """Find an existing same-title child doc under parent_node_token.

    pick="first" (default) returns on the first match and stops paginating
    early, matching three of the four prior implementations
    (feishu_service.py, feishu_doc_writer.py, docs_builder.py).

    pick="last" walks every page and returns the last match instead, which
    is the behavior selfmedia/creation/writer.py's callers actually depend
    on (see tests/test_creation_v1.py::test_creation_doc_lookup_reuses_latest_same_title_doc).
    """
    if pick not in ("first", "last"):
        raise ValueError(f"pick must be 'first' or 'last', got {pick!r}")
    clean_title = clean_wiki_title(title)
    last_match: WikiDoc | None = None
    for item in iter_wiki_children(space_id, parent_node_token, request=request):
        if clean_wiki_title(item.get("title")) != clean_title:
            continue
        if str(item.get("obj_type") or "").lower() not in obj_types:
            continue
        document_id = str(item.get("obj_token") or "").strip()
        node_token = str(item.get("node_token") or "").strip()
        if not document_id or not node_token:
            continue
        doc = WikiDoc(document_id=document_id, node_token=node_token, created=False)
        if pick == "first":
            return doc
        last_match = doc
    return last_match


def create_wiki_doc(
    space_id: str,
    parent_node_token: str,
    title: str,
    *,
    request: RequestFn,
    obj_type: str = "docx",
) -> WikiDoc:
    """One-step create: POST /wiki/v2/spaces/{space_id}/nodes with node_type=origin.

    This is the "single-step direct create" shape (as opposed to
    FeishuService._create_knowledge_node's two-step create-docx-then-bind
    shape, which is intentionally NOT folded into this module -- see the
    module docstring and the migration report for why).
    """
    data = request(
        "POST",
        f"/wiki/v2/spaces/{space_id}/nodes",
        json={
            "obj_type": obj_type,
            "parent_node_token": parent_node_token,
            "node_type": "origin",
            "title": title,
        },
    )
    node = data.get("data", {}).get("node") if isinstance(data, dict) else None
    node = node if isinstance(node, dict) else {}
    document_id = str(node.get("obj_token") or "").strip()
    node_token = str(node.get("node_token") or "").strip()
    return WikiDoc(document_id=document_id, node_token=node_token, created=True)


def create_or_reuse_wiki_doc(
    parent_node_token: str,
    title: str,
    *,
    request: RequestFn,
    obj_types: frozenset[str] = DEFAULT_OBJ_TYPES,
    pick: str = "first",
    obj_type: str = "docx",
    knowledge_base_spaces: list[dict[str, str]] | None = None,
) -> WikiDoc:
    """resolve_wiki_space_id -> find_wiki_child_doc -> create_wiki_doc if not found.

    Returns a WikiDoc whose `created` flag callers MUST branch on directly
    (True: newly created; False: reused) -- see the module docstring.
    """
    space_id = resolve_wiki_space_id(
        parent_node_token,
        request=request,
        knowledge_base_spaces=knowledge_base_spaces,
    )
    existing = find_wiki_child_doc(
        space_id,
        parent_node_token,
        title,
        request=request,
        obj_types=obj_types,
        pick=pick,
    )
    if existing is not None:
        return existing
    return create_wiki_doc(space_id, parent_node_token, title, request=request, obj_type=obj_type)


def requests_adapter(
    token: str,
    *,
    feishu_base: str,
    headers_fn: Callable[[str], dict[str, str]],
    timeout: int = 20,
) -> RequestFn:
    """Build a RequestFn on top of the `requests` library.

    Matches the call convention used by selfmedia's writer.py,
    feishu_doc_writer.py, and creator_profiles/docs_builder.py: a module-level
    FEISHU_BASE prefix plus a `headers_fn(token) -> dict` helper
    (`common.social_runtime.feishu_headers` /
    `selfmedia.deconstruct.viral_content.src.feishu_writer._headers`).

    Dispatches to the verb-specific `requests.get`/`requests.post`/... module
    functions (rather than the generic `requests.request`) so that existing
    tests which patch `<module>.requests.get` / `<module>.requests.post`
    directly keep working -- `requests` is a single cached module object
    (see sys.modules), so a patch applied through any import site is visible
    here too, but only if the same verb-specific attribute is called.
    """
    import requests

    verb_fns = {
        "GET": requests.get,
        "POST": requests.post,
        "DELETE": requests.delete,
        "PATCH": requests.patch,
        "PUT": requests.put,
    }

    def _call(method: str, path: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> dict[str, Any]:
        method_upper = method.upper()
        verb_fn = verb_fns.get(method_upper)
        url = f"{feishu_base}{path}"
        headers = headers_fn(token)
        if verb_fn is not None:
            resp = verb_fn(url, params=params, json=json, headers=headers, timeout=timeout)
        else:
            resp = requests.request(method, url, params=params, json=json, headers=headers, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"飞书 wiki 文档接口请求失败 {method} {path}：{payload}")
        return payload

    return _call
