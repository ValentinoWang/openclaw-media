from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import urllib.parse
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from fnmatch import fnmatch
from threading import Lock
from typing import Any, Callable, Iterator

import requests

from .document_edit_contract import (
    DOCUMENT_EDIT_CONTRACT_ID,
    DocumentEditPatchPlan,
    DocumentEditReadbackResult,
    DocumentEditReplaceRequest,
    load_document_edit_op_whitelist,
)
from .feishu_docx_renderer import FeishuDocxBlockRenderer, NATIVE_TABLE_KIND
from .feishu_docx_table_limits import (
    chunk_docx_table_rows,
    ensure_docx_tables_write_budget,
    ensure_docx_table_write_budget,
    sleep_seconds_for_docx_write,
    validate_docx_table_create_shape,
)
from .utils import ensure_dir


DEFAULT_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
DEFAULT_FEISHU_DOC_BASE = "https://open.feishu.cn"
FEISHU_MAPPING_FILE = "doc_mapping.json"
FEISHU_DOC_WRITE_SLEEP_SEC = sleep_seconds_for_docx_write()
LARK_CHILD_HYDRATION_REQUEST_BUDGET = 64
LARK_CHILD_HYDRATION_RETRY_ATTEMPTS = 3
LARK_CHILD_HYDRATION_RETRY_BASE_DELAY = 0.25
LARK_CHILD_HYDRATION_MAX_BACKOFF = 2.0
DOCUMENT_EDIT_PATCH_QPS = 3
DOCUMENT_EDIT_PATCH_CREATE_CHILD_BATCH_SIZE = 20
DOCX_SNAPSHOT_DIR = Path(os.getenv("OPENCLAW_DOCX_SNAPSHOT_DIR", "/home/ubuntu/obsidian-日记/公共开发集/public/document-edit-snapshots"))
DOCX_ROUNDTRIP_SAFE_BLOCK_TYPES = {2, *range(3, 12), 12, 13, 17, 31, 32}
DOCX_NON_ROUNDTRIP_KEYS = {
    "admonition",
    "attachment",
    "bitable",
    "callout",
    "diagram",
    "embed",
    "file",
    "grid",
    "grid_column",
    "iframe",
    "image",
    "isv",
    "jira",
    "mindnote",
    "sheet",
    "synced_source",
}


def _env_or_value(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1].strip(), "")
    return value


def _env_or_value_with_aliases(value: str, *aliases: str) -> str:
    direct = _env_or_value(value)
    if direct:
        return direct
    for alias in aliases:
        resolved = _env_or_value(alias)
        if resolved:
            return resolved
    return ""


class FeishuService:
    def __init__(
        self,
        mode: str,
        local_docs_dir: str,
        webhook_url: str = "",
        app_id: str = "",
        app_secret: str = "",
        api_base_url: str = DEFAULT_FEISHU_API_BASE,
        web_base_url: str = DEFAULT_FEISHU_DOC_BASE,
        folder_token: str = "",
        knowledge_base_space_id: str = "",
        knowledge_base_parent_node_token: str = "",
        knowledge_base_obj_type: str = "docx",
        knowledge_base_spaces: list[dict[str, str]] | None = None,
    ):
        self.mode = (mode or "local_markdown").strip().lower()
        self.local_docs_dir = Path(local_docs_dir)
        self.webhook_url = webhook_url.strip()
        self.app_id = _env_or_value(app_id)
        self.app_secret = _env_or_value(app_secret)
        self.api_base_url = api_base_url.rstrip("/") or DEFAULT_FEISHU_API_BASE
        self.web_base_url = web_base_url.rstrip("/") or DEFAULT_FEISHU_DOC_BASE
        self.folder_token = folder_token.strip()
        self.knowledge_base_space_id = _env_or_value_with_aliases(
            knowledge_base_space_id,
            "${FEISHU_WANG_KB_SPACE_ID}",
        ).strip()
        self.knowledge_base_parent_node_token = _env_or_value_with_aliases(
            knowledge_base_parent_node_token,
            "${FEISHU_WANG_KB_PARENT_NODE_TOKEN}",
            "${FEISHU_WANG_KB_PARENT_CONTENT_NODE_TOKEN}",
        ).strip()
        self.knowledge_base_spaces = self._normalize_knowledge_base_spaces(
            knowledge_base_spaces,
            self.knowledge_base_space_id,
            self.knowledge_base_parent_node_token,
        )
        normalized_kb_obj_type = (knowledge_base_obj_type or "docx").strip().lower() or "docx"
        self.knowledge_base_obj_type = "docx" if normalized_kb_obj_type == "doc" else normalized_kb_obj_type
        self._tenant_access_token = ""
        self._tenant_access_expire_at = 0.0
        self._tenant_access_token_lock = Lock()
        self._opc_owner_execution: ContextVar[dict[str, str] | None] = ContextVar(
            "openclaw_opc_owner_execution",
            default=None,
        )
        self.doc_mapping_path = self.local_docs_dir / FEISHU_MAPPING_FILE
        self._doc_mapping: dict[str, dict[str, str]] = self._load_doc_mapping()
        ensure_dir(self.local_docs_dir)

    @staticmethod
    def _extract_payload_value(payload: dict, *paths: str) -> str:
        current = payload
        for key in paths:
            if not isinstance(current, dict) or key not in current:
                return ""
            current = current[key]
        return str(current) if current is not None else ""

    @staticmethod
    def _safe_text_content(content: str) -> str:
        return content.replace("\r\n", "\n").rstrip()

    @staticmethod
    def _pick(mapping: dict, *path_variants: list[str]) -> str:
        for paths in path_variants:
            current = mapping
            found = True
            for key in paths:
                if not isinstance(current, dict) or key not in current:
                    found = False
                    break
                current = current[key]
            if found and current not in (None, ""):
                return str(current)
        return ""

    def _require_credentials(self) -> None:
        if not self.app_id or not self.app_secret:
            raise RuntimeError("飞书 API 配置缺少 app_id/app_secret")

    @staticmethod
    def _normalize_knowledge_base_spaces(
        raw_spaces: list[dict[str, str]] | None,
        default_space_id: str,
        default_parent_node_token: str,
    ) -> list[dict[str, str]]:
        spaces: list[dict[str, str]] = []
        if isinstance(raw_spaces, list):
            for item in raw_spaces:
                if not isinstance(item, dict):
                    continue
                space_id = _env_or_value(str(item.get("space_id", ""))).strip()
                if not space_id:
                    continue
                parent_node_token = _env_or_value(str(item.get("parent_node_token", ""))).strip() or default_parent_node_token
                pattern = str(item.get("pattern", "")).strip()
                name = str(item.get("name", "")).strip()
                space = {
                    "space_id": space_id,
                    "parent_node_token": parent_node_token,
                }
                if pattern:
                    space["pattern"] = pattern
                if name:
                    space["name"] = name
                spaces.append(space)

        if default_space_id:
            spaces.append({"space_id": default_space_id, "parent_node_token": default_parent_node_token, "pattern": "*"})
        return spaces

    def _resolve_knowledge_base_target(self, doc_name: str) -> tuple[str, str]:
        for item in self.knowledge_base_spaces:
            name = item.get("name", "")
            pattern = item.get("pattern", "")
            if name and name == doc_name:
                return item.get("space_id", ""), item.get("parent_node_token", "")
            if pattern and fnmatch(doc_name, pattern):
                return item.get("space_id", ""), item.get("parent_node_token", "")

        raise RuntimeError("知识库模式缺少知识库空间 ID（knowledge_base_space_id）")

    def _require_knowledge_base(self, doc_name: str) -> tuple[str, str]:
        self._require_credentials()
        return self._resolve_knowledge_base_target(doc_name)

    def _kb_map_key(self, doc_name: str, space_id: str) -> str:
        return f"{space_id}\0{doc_name}"

    def _kb_child_map_key(self, parent_node_token: str, doc_name: str, space_id: str) -> str:
        return f"{space_id}\0{parent_node_token}\0{doc_name}"

    def _docx_url(self, document_id: str) -> str:
        return f"{self.web_base_url}/docx/{document_id}"

    def _wiki_url(self, node_token: str) -> str:
        return f"{self.web_base_url}/wiki/{node_token}"

    def _extract_node_fields(self, data: dict) -> tuple[str, str, str]:
        raw_node = data.get("data", {}).get("node", {}) if isinstance(data, dict) else {}
        node = raw_node if isinstance(raw_node, dict) else {}
        if isinstance(node, dict):
            node_token = self._pick(
                node,
                ("node_token",),
                ("node", "token"),
                ("token",),
            )
            node_url = self._pick(node, ("node_url",), ("url",), ("wiki_url",), ("web_url",), ("detail_url",))
            obj_token = self._pick(
                node,
                ("obj", "obj_token"),
                ("obj_token",),
                ("obj", "token"),
                ("document_id",),
                ("token",),
            )
            if obj_token:
                return node_token, obj_token, node_url

        node_token = self._pick(data, ("data", "node_token"), ("data", "token"), ("data", "obj_token"))
        node_url = self._pick(data, ("data", "node_url"), ("data", "url"), ("data", "wiki_url"), ("data", "web_url"))
        obj_token = self._pick(data, ("data", "obj_token"), ("data", "node", "obj_token"), ("data", "document", "document_id"), ("data", "document_id"))
        return node_token, obj_token, node_url

    def _load_doc_mapping(self) -> dict[str, dict[str, str]]:
        if not self.doc_mapping_path.exists():
            return {}
        try:
            raw = self.doc_mapping_path.read_text(encoding="utf-8")
            mapping = json.loads(raw) if raw.strip() else {}
        except (OSError, json.JSONDecodeError):
            return {}
        return mapping if isinstance(mapping, dict) else {}

    def _save_doc_mapping(self) -> None:
        self.doc_mapping_path.write_text(json.dumps(self._doc_mapping, ensure_ascii=False, indent=2), encoding="utf-8")

    def _request(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> dict:
        token = self._get_tenant_access_token()
        url = f"{self.api_base_url}{path}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
        try:
            response = requests.request(method, url, json=json_body, params=params, headers=headers, timeout=20)
        except requests.RequestException as exc:
            raise RuntimeError(f"Feishu API request failed ({method} {path}): {exc}") from exc
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}
        if response.status_code >= 400:
            raise RuntimeError(f"Feishu API request failed ({method} {path}) status={response.status_code}, body={data}")
        if isinstance(data, dict) and data.get("code") not in {None, 0}:
            raise RuntimeError(f"Feishu API returned code={data.get('code')}, msg={data.get('msg')}, path={path}")
        return data

    @contextmanager
    def opc_owner_execution(
        self,
        *,
        tenant_id: str,
        resource_owner_user_id: str,
        owner_access_token: str,
    ) -> Iterator[None]:
        """Bind one resource-owner OAuth credential for one OPC execution."""

        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        if not isinstance(resource_owner_user_id, str) or not resource_owner_user_id.strip():
            raise ValueError("resource_owner_user_id must be a non-empty string")
        if not isinstance(owner_access_token, str) or not owner_access_token.strip():
            raise ValueError("an owner OAuth credential is required")
        if self._opc_owner_execution.get() is not None:
            raise RuntimeError("an OPC owner execution is already bound")

        execution = {
            "tenant_id": tenant_id,
            "resource_owner_user_id": resource_owner_user_id,
            "owner_access_token": owner_access_token,
        }
        context_token = self._opc_owner_execution.set(execution)
        try:
            yield
        finally:
            execution["owner_access_token"] = ""
            self._opc_owner_execution.reset(context_token)

    def _require_opc_owner_execution(self) -> dict[str, str]:
        execution = self._opc_owner_execution.get()
        if (
            not isinstance(execution, dict)
            or not execution.get("tenant_id")
            or not execution.get("resource_owner_user_id")
            or not execution.get("owner_access_token")
        ):
            raise RuntimeError("an active owner OAuth execution is required")
        return execution

    def _opc_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        execution = self._require_opc_owner_execution()
        token = execution["owner_access_token"]
        url = f"{self.api_base_url}{path}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
        try:
            response = requests.request(method, url, json=json_body, params=params, headers=headers, timeout=20)
        except requests.RequestException as exc:
            raise RuntimeError(f"Feishu API request failed ({method} {path}): {exc}") from exc
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}
        if response.status_code >= 400:
            raise RuntimeError(f"Feishu API request failed ({method} {path}) status={response.status_code}, body={data}")
        if isinstance(data, dict) and data.get("code") not in {None, 0}:
            raise RuntimeError(f"Feishu API returned code={data.get('code')}, msg={data.get('msg')}, path={path}")
        return data

    def hydrate_docx_child_tree(
        self,
        document_id: str,
        *,
        max_depth: int = 6,
        max_blocks: int = 2000,
        request_budget: int = LARK_CHILD_HYDRATION_REQUEST_BUDGET,
        retry_attempts: int = LARK_CHILD_HYDRATION_RETRY_ATTEMPTS,
        retry_base_delay: float = LARK_CHILD_HYDRATION_RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> list[dict[str, Any]]:
        """Read a stable Docx tree, retrying only transient fixed-revision child reads."""
        document_id = str(document_id or "").strip()
        if not document_id:
            raise RuntimeError("Lark child hydration requires a document ID")
        if max_depth < 0 or max_blocks < 1 or request_budget < 1 or retry_attempts < 1 or retry_base_delay < 0:
            raise ValueError("Lark child hydration limits are invalid")

        used_requests = 0

        def request_page(
            parent_block_id: str,
            revision_id: int,
            page_token: str = "",
            *,
            retry_99991400: bool,
        ) -> dict[str, Any]:
            nonlocal used_requests
            attempts = 0
            while True:
                if used_requests >= request_budget:
                    raise RuntimeError("Lark child hydration request budget exhausted")
                used_requests += 1
                params: dict[str, Any] = {"document_revision_id": revision_id, "page_size": 500}
                if page_token:
                    params["page_token"] = page_token
                try:
                    payload = self._request(
                        "GET",
                        f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children",
                        params=params,
                    )
                except RuntimeError as exc:
                    attempts += 1
                    retryable = retry_99991400 and re.search(r"(?<!\d)99991400(?!\d)", str(exc)) is not None
                    if not retryable or attempts >= retry_attempts:
                        raise
                    if used_requests >= request_budget:
                        raise RuntimeError("Lark child hydration request budget exhausted") from exc
                    delay = min(
                        LARK_CHILD_HYDRATION_MAX_BACKOFF,
                        retry_base_delay * (2 ** (attempts - 1)),
                    ) * max(0.0, min(1.0, float(jitter())))
                    sleep(delay)
                    continue
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, dict):
                    raise RuntimeError("Lark child hydration returned an invalid response")
                return data

        def page_items(data: dict[str, Any]) -> list[dict[str, Any]]:
            raw_items = data.get("items") or data.get("children") or []
            if not isinstance(raw_items, list):
                raise RuntimeError("Lark child hydration returned invalid child blocks")
            return [item for item in raw_items if isinstance(item, dict)]

        def collect_pages(
            parent_block_id: str,
            revision_id: int,
            first_page: dict[str, Any] | None = None,
        ) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            data = first_page
            page_token = ""
            seen_tokens: set[str] = set()
            while True:
                if data is None:
                    data = request_page(parent_block_id, revision_id, page_token, retry_99991400=True)
                items.extend(page_items(data))
                if not data.get("has_more"):
                    return items
                page_token = str(data.get("page_token") or "").strip()
                if not page_token or page_token in seen_tokens:
                    raise RuntimeError("Lark child hydration pagination did not advance")
                seen_tokens.add(page_token)
                data = None

        root_page = request_page(document_id, -1, retry_99991400=False)
        raw_revision = root_page.get("document_revision_id") or root_page.get("revision_id")
        try:
            fixed_revision = int(raw_revision)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Lark child hydration did not return a fixed document revision") from exc
        if fixed_revision < 0:
            raise RuntimeError("Lark child hydration did not return a fixed document revision")
        root_blocks = collect_pages(document_id, fixed_revision, root_page)
        visited: set[str] = set()
        seen_blocks = 0
        truncated = False

        def hydrate(block: dict[str, Any], depth: int, path: str) -> dict[str, Any]:
            nonlocal seen_blocks, truncated
            seen_blocks += 1
            summary = self._summarize_docx_block(block, path=path)
            if seen_blocks >= max_blocks:
                truncated = True
                summary["children_truncated"] = True
                return summary
            if depth >= max_depth:
                summary["children_truncated"] = True
                return summary
            block_id = self._extract_block_id(block)
            if not block_id or block_id in visited or not self._docx_block_may_have_children(block):
                return summary
            visited.add(block_id)
            children = collect_pages(block_id, fixed_revision)
            if children:
                summary["children"] = [
                    hydrate(child, depth + 1, f"{path}.{index}")
                    for index, child in enumerate(children)
                ]
            return summary

        tree = [hydrate(block, 0, str(index)) for index, block in enumerate(root_blocks)]
        self._annotate_docx_heading_paths(tree)
        if truncated and tree:
            tree[-1]["tree_truncated"] = True
        return tree

    def read_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}")
        record = payload.get("data", {}).get("record") if isinstance(payload, dict) else {}
        return record if isinstance(record, dict) else {}

    def download_bitable_attachment(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        file_token: str,
    ) -> dict[str, Any]:
        """Download an attachment only after the caller has authorized its Base record.

        This deliberately returns binary content rather than a provider tmp_url;
        tmp_url values expire and must not become product read-model data.
        """
        # Feishu Base attachment tokens are exchanged for a short-lived URL at
        # request time. The URL is consumed immediately and never returned to
        # callers or stored in the product read model.
        temporary = self._request(
            "GET",
            "/drive/v1/medias/batch_get_tmp_download_url",
            params={"file_tokens": file_token},
        )
        candidates = temporary.get("data", {}).get("tmp_download_urls", []) if isinstance(temporary, dict) else []
        download_url = ""
        for candidate in candidates if isinstance(candidates, list) else []:
            if not isinstance(candidate, dict) or str(candidate.get("file_token") or "") != file_token:
                continue
            download_url = str(candidate.get("tmp_download_url") or "").strip()
            break
        parsed_url = urllib.parse.urlsplit(download_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise RuntimeError("Feishu attachment download failed")
        try:
            response = requests.get(download_url, timeout=20, stream=True)
        except requests.RequestException as exc:
            raise RuntimeError("Feishu attachment download failed") from exc
        try:
            if response.status_code >= 400:
                raise RuntimeError("Feishu attachment download failed")
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                raise RuntimeError("Feishu attachment download returned unsupported content")
            content_length = response.headers.get("Content-Length")
            if content_length and (not content_length.isdigit() or int(content_length) > 10 * 1024 * 1024):
                raise RuntimeError("Feishu attachment download exceeded the preview limit")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body.extend(chunk)
                if len(body) > 10 * 1024 * 1024:
                    raise RuntimeError("Feishu attachment download exceeded the preview limit")
            if not body:
                raise RuntimeError("Feishu attachment download returned empty content")
            return {"body": bytes(body), "contentType": content_type}
        finally:
            response.close()

    def list_bitable_records(
        self,
        app_token: str,
        table_id: str,
        *,
        page_size: int = 500,
        filter_formula: str = "",
        automatic_fields: bool = False,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token = ""
        seen_tokens: set[str] = set()
        while True:
            params: dict[str, Any] = {"page_size": max(1, min(page_size, 500))}
            if automatic_fields:
                params["automatic_fields"] = "true"
            if filter_formula:
                params["filter"] = filter_formula
            if page_token:
                params["page_token"] = page_token
            payload = self._request(
                "GET",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                params=params,
            )
            data = payload.get("data") if isinstance(payload, dict) else {}
            if not isinstance(data, dict):
                raise RuntimeError("Feishu Bitable record list returned invalid data")
            items = data.get("items") or []
            if not isinstance(items, list):
                raise RuntimeError("Feishu Bitable record list returned invalid items")
            records.extend(item for item in items if isinstance(item, dict))
            if not data.get("has_more"):
                return records
            next_token = str(data.get("page_token") or "").strip()
            if not next_token or next_token in seen_tokens:
                raise RuntimeError("Feishu Bitable record pagination did not advance")
            seen_tokens.add(next_token)
            page_token = next_token

    def create_docx_with_blocks(self, doc_name: str, children: list[dict[str, Any]]) -> dict[str, str]:
        self._require_credentials()
        document_id, doc_url = self._create_docx_document(doc_name)
        self._replace_document_blocks(document_id, children)
        return {"status": "synced", "doc": doc_url, "document_id": document_id, "mode": "docx"}

    def render_docx_blocks_from_markdown(self, content: str) -> list[dict[str, Any]]:
        return self._content_to_docx_blocks(content)

    def set_docx_public_editable(self, document_id: str, *, file_type: str = "docx") -> dict[str, Any]:
        self._require_credentials()
        payload = {
            "external_access": True,
            "security_entity": "anyone_can_edit",
            "comment_entity": "anyone_can_edit",
            "share_entity": "anyone",
            "link_share_entity": "anyone_editable",
            "invite_external": True,
        }
        self._request(
            "PATCH",
            f"/drive/v1/permissions/{document_id}/public",
            json_body=payload,
            params={"type": file_type},
        )
        readback = self.get_public_permission(document_id, file_type=file_type)
        permission = readback.get("permission_public") or readback.get("public_permission") or readback
        link_share_entity = str(permission.get("link_share_entity") or "").strip()
        external_access = permission.get("external_access")
        if link_share_entity != "anyone_editable" or external_access is not True:
            raise RuntimeError(
                "飞书文档公开编辑权限读回失败："
                f"link_share_entity={link_share_entity or '<missing>'}, external_access={external_access}"
            )
        return readback

    def get_public_permission(self, token: str, *, file_type: str = "docx") -> dict[str, Any]:
        payload = self._request("GET", f"/drive/v1/permissions/{token}/public", params={"type": file_type})
        data = payload.get("data") if isinstance(payload, dict) else {}
        return data if isinstance(data, dict) else {}

    def document_has_native_table(self, document_id: str) -> bool:
        return any(item.get("block_type") == 31 for item in self._list_document_child_blocks(document_id))

    def delete_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}")

    def read_calendar_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/calendar/v4/calendars/{urllib.parse.quote(calendar_id, safe='')}/events/{urllib.parse.quote(event_id, safe='')}")
        event = payload.get("data", {}).get("event") if isinstance(payload, dict) else {}
        return event if isinstance(event, dict) else {}

    def delete_calendar_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/calendar/v4/calendars/{urllib.parse.quote(calendar_id, safe='')}/events/{urllib.parse.quote(event_id, safe='')}")

    def parse_document_url(self, url: str) -> dict[str, str] | None:
        return self._parse_document_url(url)

    def resolve_document_reference(self, url: str) -> dict[str, str]:
        info = self._parse_document_url(url)
        if not info:
            raise RuntimeError("未识别飞书文档 token")
        result = {"url": url, "kind": info["kind"], "token": info["token"], "document_id": "", "obj_type": ""}
        if info["kind"] == "wiki":
            document_id, obj_type = self._resolve_wiki_document(info["token"])
            result.update({"document_id": document_id, "obj_type": obj_type or "docx"})
        else:
            result.update({"document_id": info["token"], "obj_type": "docx"})
        return result

    def read_document_reference(self, ref: dict[str, str]) -> dict[str, Any]:
        url = str(ref.get("url") or "")
        return self.read_document_text(url) if url else {"ok": False, "error": "missing document url"}

    def verify_document_edit_readback(self, doc_url: str, expected_content: str, source: dict[str, Any]) -> dict[str, Any]:
        try:
            resolved = self._resolve_docx_url_for_snapshot(doc_url)
            document_id = resolved["document_id"]
            readback = self.read_document_text(doc_url)
            root_blocks = self._read_docx_block_tree(document_id, max_depth=6, max_blocks=2000)
        except Exception as exc:
            return {"ok": False, "status": "document_edit_readback_failed", "error": f"文档写回读回校验失败：{exc}"}

        text = str(readback.get("text") or "")
        if not readback.get("ok") or not text.strip():
            return {"ok": False, "status": "document_edit_readback_failed", "reply": f"文档写回后读回失败：{readback.get('error') or '正文为空'}"}
        patch_reason = self._document_edit_patch_like_reason(text)
        if patch_reason:
            return {"ok": False, "status": "document_edit_patch_like_readback", "reply": f"文档读回仍包含补丁式修改痕迹：{patch_reason}"}

        native_table_count = self._docx_native_table_count(root_blocks)
        markdown_table_residue_found = self._docx_markdown_table_residue_found(text)
        if markdown_table_residue_found:
            return {
                "ok": False,
                "status": "document_edit_markdown_table_residue",
                "reply": "文档读回仍包含 Markdown pipe 表格残留，未转换为飞书原生表格。",
                "native_table_count": native_table_count,
                "markdown_table_residue_found": True,
            }

        document_family = str(source.get("document_family") or "generic_docx")
        source_native_table_count = self._docx_native_table_count(source.get("root_blocks") or source.get("source_block_snapshot") or [])
        table_required = document_family in {"creation", "shooting_execution", "commercial_delivery"} or source_native_table_count > 0
        if table_required and native_table_count <= 0:
            return {
                "ok": False,
                "status": "document_edit_native_table_missing",
                "reply": "文档家族要求保留飞书原生表格，但写回读回未发现 block_type=31。",
                "native_table_count": native_table_count,
                "markdown_table_residue_found": markdown_table_residue_found,
            }

        family_checks = self._verify_document_edit_family_shape(document_family, text, root_blocks, source)
        if not family_checks.get("ok"):
            return family_checks

        result = {
            "ok": True,
            "status": "document_edit_readback_ok",
            "document_id": document_id,
            "text_length": len(text),
            "native_table_count": native_table_count,
            "markdown_table_residue_found": False,
            "family_requirements_checked": family_checks.get("family_requirements_checked") or ["generic_docx_readback", "no_patch_residue"],
            "root_block_count": len(root_blocks),
        }
        DocumentEditReadbackResult.from_mapping(result)
        return result

    def delete_document_reference(self, ref: dict[str, str]) -> dict[str, Any]:
        file_token = str(ref.get("document_id") or ref.get("token") or "").strip()
        if not file_token:
            raise RuntimeError("缺少可删除的飞书 file_token/document_id")
        file_type = str(ref.get("obj_type") or "docx").strip().lower()
        if file_type == "doc":
            file_type = "docx"
        return self._request("DELETE", f"/drive/v1/files/{file_token}", params={"type": file_type})

    @staticmethod
    def _docx_native_table_count(blocks: Any) -> int:
        count = 0

        def visit(value: Any) -> None:
            nonlocal count
            if isinstance(value, dict):
                if FeishuService._coerce_int(value.get("block_type")) == 31 or value.get("kind") == "table":
                    count += 1
                for child in value.get("children") or []:
                    visit(child)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(blocks)
        return count

    @staticmethod
    def _docx_markdown_table_residue_found(text: str) -> bool:
        lines = [line.strip() for line in str(text or "").splitlines()]
        for index, line in enumerate(lines[:-1]):
            next_line = lines[index + 1]
            if line.startswith("|") and line.endswith("|") and re.search(r"\|\s*:?-{3,}:?\s*(\||$)", next_line):
                return True
        return False

    @staticmethod
    def _document_edit_patch_like_reason(text: str) -> str:
        checks = {
            "补充记录": "补充记录",
            "追加内容": "追加内容",
            "修改记录": "修改记录",
            "融合版": "融合版",
            "_openclaw_feishu_table": "渲染中间标记",
            "Traceback": "异常堆栈",
        }
        for snippet, reason in checks.items():
            if snippet in str(text or ""):
                return reason
        return ""

    def _verify_document_edit_family_shape(
        self,
        document_family: str,
        text: str,
        root_blocks: list[dict[str, Any]],
        source: dict[str, Any],
    ) -> dict[str, Any]:
        checks = ["generic_docx_readback", "no_patch_residue"]
        if document_family not in {"creation", "shooting_execution"}:
            return {"ok": True, "family_requirements_checked": checks}

        checks.extend(["block_type=31", "storyboard_headers", "evidence_appendix_last"])
        text_blob = str(text or "")
        required_headers = ("时间", "画面", "字幕/口播", "声音/拍摄注意")
        if "分镜脚本" not in text_blob and "图片脚本" not in text_blob:
            return {"ok": False, "status": "document_edit_storyboard_missing", "reply": "创作/拍摄文档读回缺少分镜脚本或图片脚本章节。"}
        missing_headers = [header for header in required_headers if header not in text_blob]
        if missing_headers:
            return {
                "ok": False,
                "status": "document_edit_storyboard_headers_missing",
                "reply": "创作/拍摄文档读回缺少分镜/图片脚本表头：" + "、".join(missing_headers),
            }
        source_text = str(source.get("text") or "")
        if "证据附录" in source_text or "证据附录" in text_blob:
            if not self._docx_heading_is_last(root_blocks, "证据附录"):
                return {
                    "ok": False,
                    "status": "document_edit_evidence_appendix_not_last",
                    "reply": "创作/拍摄文档读回后证据附录不是最后一个业务章节。",
                }
        return {"ok": True, "family_requirements_checked": checks}

    @staticmethod
    def _docx_heading_is_last(root_blocks: list[dict[str, Any]], heading_text: str) -> bool:
        headings: list[tuple[int, str]] = []
        flat: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                flat.append(value)
                for child in value.get("children") or []:
                    visit(child)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(root_blocks)
        for index, block in enumerate(flat):
            block_type = FeishuService._coerce_int(block.get("block_type"))
            if block_type in range(3, 12):
                headings.append((index, str(block.get("text") or "")))
        matched = [index for index, title in headings if heading_text in title]
        if not matched:
            return False
        last_heading_index = headings[-1][0] if headings else -1
        return matched[-1] == last_heading_index

    def read_document_text(self, url: str) -> dict[str, Any]:
        info = self._parse_document_url(url)
        if not info:
            return {"ok": False, "url": url, "kind": "feishu_doc", "text": "", "error": "未识别飞书文档 token"}

        candidates: list[tuple[str, str]] = []
        if info["kind"] == "wiki":
            try:
                obj_token, obj_type = self._resolve_wiki_document(info["token"])
                if obj_token:
                    candidates.append((obj_token, obj_type or "docx"))
            except RuntimeError as exc:
                candidates.append((info["token"], "wiki"))
                last_error = str(exc)
            else:
                last_error = ""
        else:
            candidates.append((info["token"], info["kind"]))
            last_error = ""

        seen: set[str] = set()
        for token, kind in candidates:
            if token in seen:
                continue
            seen.add(token)
            for reader in (self._read_docx_raw_content, self._read_docx_child_blocks):
                try:
                    text = reader(token)
                except RuntimeError as exc:
                    last_error = str(exc)
                    continue
                if text:
                    return {"ok": True, "url": url, "kind": kind, "token": token, "text": text, "error": ""}

        return {
            "ok": False,
            "url": url,
            "kind": info["kind"],
            "token": info["token"],
            "text": "",
            "error": last_error or "未能读取飞书文档正文",
        }

    def snapshot_docx_url(
        self,
        url: str,
        *,
        snapshot_reason: str = "document_edit_preflight",
        snapshot_dir: str | Path | None = None,
        max_depth: int = 6,
        max_blocks: int = 2000,
    ) -> dict[str, Any]:
        resolved = self._resolve_docx_url_for_snapshot(url)
        snapshot = self._build_docx_snapshot(
            resolved["document_id"],
            url=resolved["doc_url"],
            kind=resolved["kind"],
            snapshot_reason=snapshot_reason,
            max_depth=max_depth,
            max_blocks=max_blocks,
        )
        safety = self._evaluate_docx_roundtrip_safety(snapshot.get("root_blocks") or [])
        snapshot["roundtrip_safety"] = safety
        snapshot_path = self._write_docx_snapshot(snapshot, snapshot_dir=snapshot_dir)
        return {
            "ok": True,
            "url": resolved["doc_url"],
            "kind": resolved["kind"],
            "document_id": resolved["document_id"],
            "text": snapshot.get("text", ""),
            "root_blocks": snapshot.get("root_blocks") or [],
            "source_hash": snapshot.get("source_hash", ""),
            "revision_token": snapshot.get("revision_token", ""),
            "snapshot_path": str(snapshot_path),
            "safe_to_replace": safety.get("safe_to_replace") is True,
            "unsupported_blocks": safety.get("unsupported_blocks") or [],
            "block_count": safety.get("block_count", 0),
            "error": "",
        }

    def preflight_docx_replace_url(
        self,
        url: str,
        *,
        snapshot_reason: str = "document_edit_preflight",
        snapshot_dir: str | Path | None = None,
        max_depth: int = 6,
        max_blocks: int = 2000,
    ) -> dict[str, Any]:
        try:
            return self.snapshot_docx_url(
                url,
                snapshot_reason=snapshot_reason,
                snapshot_dir=snapshot_dir,
                max_depth=max_depth,
                max_blocks=max_blocks,
            )
        except RuntimeError as exc:
            return {
                "ok": False,
                "url": url,
                "kind": "feishu_doc",
                "document_id": "",
                "text": "",
                "root_blocks": [],
                "source_hash": "",
                "revision_token": "",
                "snapshot_path": "",
                "safe_to_replace": False,
                "unsupported_blocks": [],
                "block_count": 0,
                "error": str(exc),
            }

    def prepare_document_edit_patch_source(
        self,
        url: str,
        *,
        snapshot_reason: str = "document_edit_patch_preflight",
        snapshot_dir: str | Path | None = None,
        max_depth: int = 1,
        max_blocks: int = 500,
    ) -> dict[str, Any]:
        try:
            snapshot = self.snapshot_docx_url(
                url,
                snapshot_reason=snapshot_reason,
                snapshot_dir=snapshot_dir,
                max_depth=max_depth,
                max_blocks=max_blocks,
            )
        except RuntimeError as exc:
            return {
                "ok": False,
                "status": "document_edit_patch_preflight_failed",
                "url": url,
                "document_id": "",
                "text": "",
                "root_blocks": [],
                "source_hash": "",
                "revision_token": "",
                "snapshot_path": "",
                "protected_block_ids": [],
                "protected_table_shapes": [],
                "patchable_blocks": [],
                "manual_actions": [],
                "error": str(exc),
            }
        protected = self._docx_patch_protected_inventory(snapshot.get("root_blocks") or [])
        patchable_blocks = self._docx_patchable_block_refs(snapshot.get("root_blocks") or [])
        return {
            **snapshot,
            "ok": True,
            "status": "document_edit_patch_preflight_ok",
            "safe_to_patch": True,
            "snapshot_depth": max_depth,
            "snapshot_max_blocks": max_blocks,
            "protected_block_ids": [item["block_id"] for item in protected if item.get("block_id")],
            "protected_blocks": protected,
            "protected_table_shapes": [
                {
                    "block_id": item.get("block_id", ""),
                    "path": item.get("path", ""),
                    "table_shape": item.get("table_shape") or {},
                }
                for item in self._flatten_docx_summary_blocks(snapshot.get("root_blocks") or [])
                if item.get("table_shape")
            ],
            "patchable_blocks": patchable_blocks,
            "manual_actions": [
                {
                    "reason": "protected_block",
                    "instructions": "This block is protected by default and must not be changed by executable document_edit patch operations.",
                    "block_id": item.get("block_id", ""),
                    "path": [str(item.get("path") or "")],
                    "requested_op": "",
                }
                for item in protected
            ],
            "error": "",
        }

    def compute_docx_source_token_url(self, url: str, *, max_depth: int = 6, max_blocks: int = 2000) -> dict[str, Any]:
        resolved = self._resolve_docx_url_for_snapshot(url)
        snapshot = self._build_docx_snapshot(
            resolved["document_id"],
            url=resolved["doc_url"],
            kind=resolved["kind"],
            snapshot_reason="source_token",
            max_depth=max_depth,
            max_blocks=max_blocks,
        )
        return {
            "ok": True,
            "url": resolved["doc_url"],
            "kind": resolved["kind"],
            "document_id": resolved["document_id"],
            "source_hash": snapshot.get("source_hash", ""),
            "revision_token": snapshot.get("revision_token", ""),
            "error": "",
        }

    def verify_document_edit_patch_source_unchanged(self, source: dict[str, Any]) -> dict[str, Any]:
        document_id = str(source.get("document_id") or "").strip()
        expected = str(source.get("source_hash") or source.get("revision_token") or "").strip()
        if not document_id:
            return {"ok": False, "status": "document_edit_patch_source_missing", "reply": "patch source 缺少 document_id，已停止写入。"}
        try:
            self._verify_docx_source_hash_with_limits(
                document_id,
                expected,
                max_depth=int(source.get("snapshot_depth") or 1),
                max_blocks=int(source.get("snapshot_max_blocks") or 500),
            )
        except RuntimeError as exc:
            if "document_changed_since_read" in str(exc):
                return {"ok": False, "status": "document_changed_since_read", "reply": "写入前复核发现文档已变化，已停止写入。", "error": str(exc)}
            return {"ok": False, "status": "document_edit_hash_check_failed", "reply": f"写前 hash 复核失败：{exc}"}
        return {"ok": True, "status": "document_edit_patch_source_unchanged"}

    def apply_document_edit_patch_plan(self, plan_payload: dict[str, Any]) -> dict[str, Any]:
        plan = DocumentEditPatchPlan.from_mapping(
            plan_payload,
            executable_op_whitelist=load_document_edit_op_whitelist(),
        )
        source = plan.source.to_mapping()
        unchanged = self.verify_document_edit_patch_source_unchanged(source)
        if not unchanged.get("ok"):
            return unchanged
        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        document_id = plan.source.document_id
        current_snapshot = self._build_docx_snapshot(
            document_id,
            url=self._docx_url(document_id),
            kind="docx",
            snapshot_reason="document_edit_patch_expected_text_precheck",
            max_depth=int(source.get("snapshot_depth") or 1),
            max_blocks=int(source.get("snapshot_max_blocks") or 500),
        )
        current_blocks = self._flatten_docx_summary_blocks(current_snapshot.get("root_blocks") or [])
        current_text_by_block_id = {
            str(block.get("block_id") or ""): str(block.get("text") or "")
            for block in current_blocks
            if isinstance(block, dict)
        }
        for operation in plan.operations:
            if operation.op not in {"replace_text", "delete_text_block"}:
                continue
            current_text = current_text_by_block_id.get(operation.block.block_id)
            if current_text != operation.expected_old_text:
                return {
                    "ok": False,
                    "status": "patch_apply_failed",
                    "document_id": document_id,
                    "doc": plan.source.url,
                    "source_hash": plan.source.source_hash,
                    "revision_token": plan.source.revision_token,
                    "applied_operations": [],
                    "manual_actions": [action.to_mapping() for action in plan.manual_actions],
                    "errors": [
                        {
                            **operation.to_mapping(),
                            "error": "document_edit_patch_expected_old_text_mismatch",
                            "current_text": current_text or "",
                        }
                    ],
                    "recovery_snapshot_path": "",
                }
        for index, operation in enumerate(plan.operations):
            op_payload = operation.to_mapping()
            try:
                if operation.op == "replace_text":
                    response = self._patch_docx_text_elements(document_id, operation.block.block_id, operation.new_text)
                elif operation.op == "insert_text_after":
                    insert_index = self._resolve_docx_child_insert_index(
                        document_id,
                        operation.parent_block_id,
                        operation.anchor_block_id or operation.block.block_id,
                        after=True,
                    )
                    response = self._insert_docx_children_at(
                        document_id,
                        operation.parent_block_id,
                        insert_index,
                        [self._text_block(operation.new_text)],
                    )
                elif operation.op == "delete_text_block":
                    delete_index = self._resolve_docx_child_block_index(document_id, operation.parent_block_id, operation.block.block_id)
                    response = self._delete_docx_child_range(document_id, operation.parent_block_id, delete_index, delete_index + 1)
                elif operation.op == "append_text_to_cell":
                    response = self._insert_docx_children_at(
                        document_id,
                        operation.cell_block_id or operation.block.block_id,
                        -1,
                        [self._text_block(operation.new_text)],
                    )
                elif operation.op == "insert_table_row":
                    response = self._insert_docx_table_row_with_values(
                        document_id,
                        operation.table_block_id or operation.block.block_id,
                        operation.row_index,
                        operation.cell_texts,
                    )
                else:
                    raise RuntimeError(f"unsupported document_edit patch op: {operation.op}")
                applied.append({**op_payload, "response_keys": sorted(response.keys()) if isinstance(response, dict) else []})
                time.sleep(max(0.0, 1.0 / DOCUMENT_EDIT_PATCH_QPS))
            except Exception as exc:
                errors.append({**op_payload, "error": str(exc), "operation_index": index})
                break
        recovery_snapshot_path = ""
        if errors and applied:
            try:
                recovery = self.snapshot_docx_url(
                    plan.source.url,
                    snapshot_reason="document_edit_patch_partial_recovery",
                    max_depth=int(source.get("snapshot_depth") or 1),
                    max_blocks=int(source.get("snapshot_max_blocks") or 500),
                )
                recovery_snapshot_path = str(recovery.get("snapshot_path") or "")
            except Exception as exc:
                recovery_snapshot_path = f"recovery_snapshot_failed: {exc}"
        status = "patch_apply_ok" if applied and not errors else "patch_apply_partial" if applied else "patch_apply_failed"
        if not plan.operations and plan.manual_actions:
            status = "patch_apply_manual"
        return {
            "ok": status in {"patch_apply_ok", "patch_apply_partial"},
            "status": status,
            "document_id": document_id,
            "doc": plan.source.url,
            "source_hash": plan.source.source_hash,
            "revision_token": plan.source.revision_token,
            "applied_operations": applied,
            "manual_actions": [action.to_mapping() for action in plan.manual_actions],
            "errors": errors,
            "recovery_snapshot_path": recovery_snapshot_path,
        }

    def verify_document_edit_patch_readback(self, plan_payload: dict[str, Any], apply_result: dict[str, Any]) -> dict[str, Any]:
        plan = DocumentEditPatchPlan.from_mapping(
            plan_payload,
            executable_op_whitelist=load_document_edit_op_whitelist(),
        )
        try:
            snapshot = self.snapshot_docx_url(
                plan.source.url,
                snapshot_reason="document_edit_patch_readback",
                max_depth=int(plan.source.to_mapping().get("snapshot_depth") or 1),
                max_blocks=int(plan.source.to_mapping().get("snapshot_max_blocks") or 500),
            )
        except RuntimeError as exc:
            return {"ok": False, "status": "document_edit_patch_readback_failed", "reply": f"patch 读回失败：{exc}"}
        blocks = self._flatten_docx_summary_blocks(snapshot.get("root_blocks") or [])
        block_ids = {str(item.get("block_id") or "") for item in blocks}
        text = str(snapshot.get("text") or "")
        native_table_count = sum(1 for item in blocks if item.get("block_type") == 31 or item.get("kind") == "table")
        markdown_table_residue_found = bool(re.search(r"(?m)^\s*\|.+\|\s*$", text))
        protected_missing = [block_id for block_id in plan.source.protected_block_ids if block_id and block_id not in block_ids]
        allowed_table_row_increments: dict[str, int] = {}
        for operation in plan.operations:
            if operation.op == "insert_table_row":
                table_block_id = operation.table_block_id or operation.block.block_id
                if table_block_id:
                    allowed_table_row_increments[table_block_id] = allowed_table_row_increments.get(table_block_id, 0) + 1
        table_shape_changes = self._docx_table_shape_changes(
            plan.source.protected_table_shapes,
            blocks,
            allowed_row_increments=allowed_table_row_increments,
        )
        missing_text: list[str] = []
        for operation in plan.operations:
            if operation.op in {"replace_text", "insert_text_after", "append_text_to_cell", "insert_table_row"} and operation.new_text and operation.new_text not in text:
                missing_text.append(operation.operation_id or operation.block.block_id)
        ok = not protected_missing and not table_shape_changes and not missing_text
        family_requirements_checked = [
            "patch_readback",
            "protected_block_ids_unchanged",
            "protected_table_shapes_checked",
        ]
        if allowed_table_row_increments:
            family_requirements_checked.append("insert_table_row_readback")
        return {
            "ok": ok,
            "status": "document_edit_patch_readback_ok" if ok else "document_edit_patch_readback_failed",
            "document_id": plan.source.document_id,
            "source_hash": snapshot.get("source_hash") or "",
            "revision_token": snapshot.get("revision_token") or "",
            "changed_since_read": True,
            "applied_operation_ids": [
                str(item.get("operation_id") or item.get("block_id") or "")
                for item in apply_result.get("applied_operations") or []
                if isinstance(item, dict)
            ],
            "protected_block_ids_missing": protected_missing,
            "protected_table_shape_changes": table_shape_changes,
            "missing_applied_text_operations": missing_text,
            "manual_actions": apply_result.get("manual_actions") or [],
            "snapshot_path": snapshot.get("snapshot_path") or "",
            "text": text,
            "native_table_count": native_table_count,
            "markdown_table_residue_found": markdown_table_residue_found,
            "family_requirements_checked": family_requirements_checked,
        }

    def replace_document_url(
        self,
        url: str,
        content: str,
        *,
        source_hash: str = "",
        source_block_hash: str = "",
        safe_replace: bool = False,
        snapshot_dir: str | Path | None = None,
        snapshot_path: str = "",
        document_family: str = "generic_docx",
    ) -> dict[str, str]:
        info = self._parse_document_url(url)
        if not info:
            raise RuntimeError("未识别飞书文档 token")

        document_id = ""
        doc_url = url
        if info["kind"] == "wiki":
            document_id, obj_type = self._resolve_wiki_document(info["token"])
            if (obj_type or "docx").lower() not in {"docx", "doc"}:
                raise RuntimeError(f"当前只支持重写 docx/doc 文档，不支持 obj_type={obj_type}")
            doc_url = self._wiki_url(info["token"])
        else:
            document_id = info["token"]
            doc_url = self._docx_url(document_id)

        snapshot_path = snapshot_path
        document_family = document_family or "generic_docx"
        expected_source_hash = source_hash or source_block_hash
        if safe_replace:
            preflight = self.snapshot_docx_url(doc_url, snapshot_dir=snapshot_dir)
            snapshot_path = snapshot_path or str(preflight.get("snapshot_path") or "")
            if not preflight.get("safe_to_replace"):
                unsupported = preflight.get("unsupported_blocks") or []
                raise RuntimeError(
                    "document_not_roundtrip_safe: "
                    f"snapshot_path={snapshot_path or '<missing>'}, unsupported_blocks={unsupported[:5]}"
                )
            expected_source_hash = expected_source_hash or str(preflight.get("source_hash") or "")

        try:
            self._replace_document_content(document_id, content, expected_source_hash=expected_source_hash)
        except RuntimeError as exc:
            if "document_changed_since_read" in str(exc):
                raise RuntimeError(f"document_changed_since_read: document_family={document_family}, {exc}") from exc
            raise
        result = {"status": "synced", "doc": doc_url, "document_id": document_id, "document_family": document_family}
        if snapshot_path:
            result["snapshot_path"] = snapshot_path
        if expected_source_hash:
            result["source_hash"] = self._normalize_docx_source_hash(expected_source_hash)
        return result

    def replace_document_url_safely(
        self,
        url: str,
        content: str,
        *,
        source_hash: str,
        snapshot_path: str,
        document_family: str = "generic_docx",
        contract_id: str = DOCUMENT_EDIT_CONTRACT_ID,
    ) -> dict[str, str]:
        if contract_id != DOCUMENT_EDIT_CONTRACT_ID:
            raise RuntimeError(f"unsupported document_edit contract_id={contract_id}")
        request = DocumentEditReplaceRequest(
            doc_url=url,
            content=content,
            source_hash=source_hash,
            snapshot_path=snapshot_path,
            document_family=document_family or "generic_docx",
        )
        return self.replace_document_url(
            request.doc_url,
            request.content,
            source_hash=request.source_hash,
            snapshot_path=request.snapshot_path,
            document_family=request.document_family,
            safe_replace=True,
        )

    def _resolve_docx_url_for_snapshot(self, url: str) -> dict[str, str]:
        info = self._parse_document_url(url)
        if not info:
            raise RuntimeError("未识别飞书文档 token")
        if info["kind"] == "wiki":
            document_id, obj_type = self._resolve_wiki_document(info["token"])
            if (obj_type or "docx").lower() not in {"docx", "doc"}:
                raise RuntimeError(f"当前只支持读取 docx/doc 文档，不支持 obj_type={obj_type}")
            return {"document_id": document_id, "kind": obj_type or "docx", "doc_url": self._wiki_url(info["token"])}
        return {"document_id": info["token"], "kind": info["kind"], "doc_url": self._docx_url(info["token"])}

    def _build_docx_snapshot(
        self,
        document_id: str,
        *,
        url: str,
        kind: str,
        snapshot_reason: str,
        max_depth: int,
        max_blocks: int,
    ) -> dict[str, Any]:
        raw_text = ""
        raw_content_error = ""
        try:
            raw_text = self._read_docx_raw_content(document_id)
        except RuntimeError as exc:
            raw_content_error = str(exc)

        root_blocks = self._read_docx_block_tree(document_id, max_depth=max_depth, max_blocks=max_blocks)
        block_text = self._extract_readable_text({"items": root_blocks})
        text = raw_text or block_text
        snapshot = {
            "schema": "openclaw.docx_snapshot.v1",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": snapshot_reason,
            "url": url,
            "kind": kind,
            "document_id": document_id,
            "text": text,
            "text_source": "raw_content" if raw_text else "block_tree",
            "raw_content_error": raw_content_error,
            "root_blocks": root_blocks,
        }
        source_hash = self._docx_source_hash(snapshot)
        snapshot["source_hash"] = source_hash
        snapshot["revision_token"] = f"docx-sha256:{source_hash}"
        return snapshot

    def _read_docx_block_tree(self, document_id: str, *, max_depth: int = 6, max_blocks: int = 2000) -> list[dict[str, Any]]:
        root_blocks = self._list_document_child_blocks(document_id)
        visited: set[str] = set()
        seen_count = 0
        truncated = False

        def hydrate(block: dict[str, Any], depth: int, path: str) -> dict[str, Any]:
            nonlocal seen_count, truncated
            seen_count += 1
            summary = self._summarize_docx_block(block, path=path)
            if seen_count >= max_blocks:
                truncated = True
                summary["children_truncated"] = True
                return summary
            if depth >= max_depth:
                summary["children_truncated"] = True
                return summary

            block_id = self._extract_block_id(block)
            if not block_id or block_id in visited or not self._docx_block_may_have_children(block):
                return summary
            visited.add(block_id)
            try:
                children = self._get_docx_children(document_id, block_id)
            except RuntimeError as exc:
                summary["children_error"] = str(exc)[:300]
                children = []
            if children:
                summary["children"] = [
                    hydrate(child, depth + 1, f"{path}.{index}")
                    for index, child in enumerate(children)
                    if isinstance(child, dict)
                ]
            return summary

        tree = [hydrate(block, 0, str(index)) for index, block in enumerate(root_blocks) if isinstance(block, dict)]
        self._annotate_docx_heading_paths(tree)
        if truncated and tree:
            tree[-1]["tree_truncated"] = True
        return tree

    def _annotate_docx_heading_paths(self, blocks: list[dict[str, Any]]) -> None:
        def visit(items: Any, heading_stack: list[str]) -> None:
            if not isinstance(items, list):
                return
            current_stack = list(heading_stack)
            for item in items:
                if not isinstance(item, dict):
                    continue
                block_type = self._coerce_int(item.get("block_type"))
                child_stack = list(current_stack)
                if block_type in range(3, 12):
                    level = block_type - 2
                    title = str(item.get("text") or "").strip()
                    child_stack = current_stack[: max(level - 1, 0)]
                    if title:
                        child_stack.append(title)
                    current_stack = list(child_stack)
                    item["heading_path"] = list(child_stack)
                else:
                    item["heading_path"] = list(current_stack)
                visit(item.get("children"), child_stack)

        visit(blocks, [])

    def _summarize_docx_block(self, block: dict[str, Any], *, path: str) -> dict[str, Any]:
        block_type = self._coerce_int(block.get("block_type"))
        summary: dict[str, Any] = {
            "path": path,
            "block_id": self._extract_block_id(block),
            "parent_id": str(block.get("parent_id") or ""),
            "block_type": block_type,
            "kind": self._docx_block_kind(block),
            "raw_keys": sorted(str(key) for key in block.keys()),
        }
        text = self._extract_readable_text(block, limit=1200)
        if text:
            summary["text"] = text
        text_elements = self._summarize_docx_text_elements(block)
        if text_elements.get("element_count"):
            summary["text_elements_summary"] = text_elements
            summary["text_element_kinds"] = text_elements.get("element_kinds", [])
            summary["non_plain_text_element_kinds"] = text_elements.get("non_plain_text_element_kinds", [])
            summary["is_plain_text_patchable"] = bool(text_elements.get("is_plain_text_patchable"))
        table = block.get("table") if isinstance(block.get("table"), dict) else {}
        property_payload = table.get("property") if isinstance(table, dict) else {}
        if isinstance(property_payload, dict):
            row_size = property_payload.get("row_size")
            column_size = property_payload.get("column_size")
            if row_size is not None or column_size is not None:
                summary["table_shape"] = {"row_size": row_size, "column_size": column_size}
        return summary

    @staticmethod
    def _summarize_docx_text_elements(block: dict[str, Any]) -> dict[str, Any]:
        elements: list[dict[str, Any]] = []

        def visit(value: Any, key: str = "") -> None:
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    visit(child_value, str(child_key))
                return
            if isinstance(value, list):
                if key == "elements":
                    elements.extend(item for item in value if isinstance(item, dict))
                    return
                for item in value:
                    visit(item, key)

        visit(block)
        if not elements:
            return {"element_count": 0, "element_kinds": [], "non_plain_text_element_kinds": [], "is_plain_text_patchable": False}

        element_kinds: list[str] = []
        non_plain: list[str] = []
        styled_run_count = 0
        plain_run_count = 0

        for element in elements:
            kind = FeishuService._docx_text_element_kind(element)
            element_kinds.append(kind)
            if kind == "text_run_plain":
                plain_run_count += 1
                continue
            if kind == "text_run_styled":
                styled_run_count += 1
            non_plain.append(kind)

        return {
            "element_count": len(elements),
            "element_kinds": sorted(set(element_kinds)),
            "plain_text_run_count": plain_run_count,
            "styled_text_run_count": styled_run_count,
            "non_plain_text_element_kinds": sorted(set(non_plain)),
            "is_plain_text_patchable": bool(elements) and not non_plain,
        }

    @staticmethod
    def _docx_text_element_kind(element: dict[str, Any]) -> str:
        text_run = element.get("text_run") if isinstance(element.get("text_run"), dict) else {}
        if text_run:
            style = text_run.get("text_element_style")
            if isinstance(style, dict) and any(value not in (None, "", False, [], {}) for value in style.values()):
                return "text_run_styled"
            if any(key in text_run for key in ("link", "mention_user", "equation", "inline_file", "file")):
                return "text_run_styled"
            return "text_run_plain"
        for key in sorted(str(item) for item in element.keys()):
            if key not in {"text_element_style", "style"}:
                return key
        return "unknown_element"

    @staticmethod
    def _docx_block_may_have_children(block: dict[str, Any]) -> bool:
        if block.get("children"):
            return True
        block_type = FeishuService._coerce_int(block.get("block_type"))
        if block_type in {31, 32}:
            return True
        if block_type in {2, *range(3, 12)}:
            return False
        return True

    @staticmethod
    def _docx_block_kind(block: dict[str, Any]) -> str:
        for key in sorted(DOCX_NON_ROUNDTRIP_KEYS):
            if key in block:
                return key
        block_type = FeishuService._coerce_int(block.get("block_type"))
        if block_type == 2:
            return "text"
        if block_type in range(3, 12):
            return f"heading{block_type - 2}"
        if block_type in {12, 13, 17}:
            return "list"
        if block_type == 31:
            return "table"
        if block_type == 32:
            return "table_cell"
        return f"block_type_{block_type}" if block_type is not None else "unknown"

    def _evaluate_docx_roundtrip_safety(self, root_blocks: list[dict[str, Any]]) -> dict[str, Any]:
        unsupported: list[dict[str, Any]] = []
        block_count = 0

        def visit(node: dict[str, Any]) -> None:
            nonlocal block_count
            block_count += 1
            raw_keys = set(str(key) for key in node.get("raw_keys") or [])
            non_roundtrip_keys = sorted(raw_keys & DOCX_NON_ROUNDTRIP_KEYS)
            block_type = self._coerce_int(node.get("block_type"))
            is_safe_type = block_type in DOCX_ROUNDTRIP_SAFE_BLOCK_TYPES
            if non_roundtrip_keys or not is_safe_type:
                unsupported.append(
                    {
                        "path": str(node.get("path") or ""),
                        "block_id": str(node.get("block_id") or ""),
                        "block_type": block_type,
                        "kind": str(node.get("kind") or ""),
                        "reason": "non_roundtrip_key" if non_roundtrip_keys else "unsupported_block_type",
                        "keys": non_roundtrip_keys,
                    }
                )
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    visit(child)

        for block in root_blocks:
            if isinstance(block, dict):
                visit(block)
        return {
            "safe_to_replace": not unsupported,
            "unsupported_blocks": unsupported,
            "block_count": block_count,
        }

    def _write_docx_snapshot(self, snapshot: dict[str, Any], *, snapshot_dir: str | Path | None = None) -> Path:
        base_dir = Path(snapshot_dir) if snapshot_dir else DOCX_SNAPSHOT_DIR
        target_dir = base_dir / time.strftime("%Y-%m-%d")
        ensure_dir(target_dir)
        document_id = re.sub(r"[^A-Za-z0-9_-]", "", str(snapshot.get("document_id") or "docx")) or "docx"
        source_hash = str(snapshot.get("source_hash") or "nohash")
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        target = target_dir / f"{document_id}-{timestamp}-{source_hash[:12]}.json"
        target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def _verify_docx_source_hash(self, document_id: str, expected_source_hash: str) -> None:
        self._verify_docx_source_hash_with_limits(document_id, expected_source_hash, max_depth=6, max_blocks=2000)

    def _verify_docx_source_hash_with_limits(
        self,
        document_id: str,
        expected_source_hash: str,
        *,
        max_depth: int,
        max_blocks: int,
    ) -> None:
        expected = self._normalize_docx_source_hash(expected_source_hash)
        if not expected:
            return
        snapshot = self._build_docx_snapshot(
            document_id,
            url=self._docx_url(document_id),
            kind="docx",
            snapshot_reason="write_precheck",
            max_depth=max_depth,
            max_blocks=max_blocks,
        )
        current = self._normalize_docx_source_hash(str(snapshot.get("source_hash") or ""))
        if current != expected:
            raise RuntimeError(f"document_changed_since_read: expected_source_hash={expected}, current_source_hash={current}")

    def _flatten_docx_summary_blocks(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []

        def visit(items: Any) -> None:
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                flattened.append(item)
                visit(item.get("children"))

        visit(blocks)
        return flattened

    def _docx_patchable_block_refs(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        patchable_types = {2, *range(3, 12), 32}
        refs: list[dict[str, Any]] = []
        for block in self._flatten_docx_summary_blocks(blocks):
            block_id = str(block.get("block_id") or "")
            block_type = self._coerce_int(block.get("block_type"))
            if not block_id or block_type not in patchable_types or not str(block.get("text") or "").strip():
                continue
            if block.get("non_plain_text_element_kinds"):
                continue
            if block.get("is_plain_text_patchable") is False and block_type != 32:
                continue
            refs.append(
                {
                    "block_id": block_id,
                    "path": [str(block.get("path") or "")],
                    "block_type": str(block_type),
                    "text": str(block.get("text") or ""),
                    "heading_path": list(block.get("heading_path") or []),
                    "protected": False,
                    "has_non_plain_text_elements": False,
                }
            )
        return refs

    def _docx_patch_protected_inventory(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        patchable_ids = {item["block_id"] for item in self._docx_patchable_block_refs(blocks)}
        protected: list[dict[str, Any]] = []
        for block in self._flatten_docx_summary_blocks(blocks):
            block_id = str(block.get("block_id") or "")
            if not block_id or block_id in patchable_ids:
                continue
            reason = "non_text_or_structure_block"
            if block.get("non_plain_text_element_kinds"):
                reason = "rich_text_elements_without_style_run_proof"
            elif block.get("table_shape"):
                reason = "table_shape_protected"
            protected.append(
                {
                    "block_id": block_id,
                    "path": str(block.get("path") or ""),
                    "block_type": block.get("block_type"),
                    "kind": block.get("kind"),
                    "text": str(block.get("text") or "")[:300],
                    "heading_path": list(block.get("heading_path") or []),
                    "table_shape": block.get("table_shape") or {},
                    "reason": reason,
                }
            )
        return protected

    def _docx_table_shape_changes(
        self,
        expected_shapes: list[Any],
        blocks: list[dict[str, Any]],
        *,
        allowed_row_increments: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        allowed_row_increments = allowed_row_increments or {}
        by_id = {str(item.get("block_id") or ""): item for item in blocks if isinstance(item, dict)}
        changes: list[dict[str, Any]] = []
        for expected in expected_shapes:
            if not isinstance(expected, dict):
                continue
            block_id = str(expected.get("block_id") or "")
            if not block_id:
                continue
            actual = by_id.get(block_id)
            if not actual:
                changes.append({"block_id": block_id, "reason": "table_missing"})
                continue
            expected_shape = dict(expected.get("table_shape") or {})
            allowed_increment = allowed_row_increments.get(block_id, 0)
            if allowed_increment:
                expected_rows = self._coerce_int(expected_shape.get("row_size"))
                if expected_rows is not None:
                    expected_shape["row_size"] = expected_rows + allowed_increment
            if (actual.get("table_shape") or {}) != expected_shape:
                changes.append(
                    {
                        "block_id": block_id,
                        "expected": expected.get("table_shape") or {},
                        "allowed_row_increment": allowed_increment,
                        "actual": actual.get("table_shape") or {},
                    }
                )
        return changes

    def _resolve_docx_child_block_index(self, document_id: str, parent_block_id: str, block_id: str) -> int:
        children = self._get_docx_children(document_id, parent_block_id)
        for index, child in enumerate(children):
            if self._extract_block_id(child) == block_id:
                return index
        raise RuntimeError(
            "document_edit_block_not_found: "
            f"document_id={document_id}, parent_block_id={parent_block_id}, block_id={block_id}"
        )

    @staticmethod
    def _normalize_docx_source_hash(value: str) -> str:
        clean = str(value or "").strip().lower()
        for prefix in ("docx-sha256:", "sha256:"):
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
        return re.sub(r"[^a-f0-9]", "", clean)

    @staticmethod
    def _docx_source_hash(snapshot: dict[str, Any]) -> str:
        def stable_block(block: Any) -> dict[str, Any]:
            if not isinstance(block, dict):
                return {}
            return {
                "block_id": str(block.get("block_id") or ""),
                "path": str(block.get("path") or ""),
                "block_type": block.get("block_type"),
                "kind": str(block.get("kind") or ""),
                "text": str(block.get("text") or ""),
                "heading_path": list(block.get("heading_path") or []),
                "table_shape": block.get("table_shape") or {},
                "is_plain_text_patchable": block.get("is_plain_text_patchable"),
                "non_plain_text_element_kinds": list(block.get("non_plain_text_element_kinds") or []),
                "tree_truncated": bool(block.get("tree_truncated")),
                "children_truncated": bool(block.get("children_truncated")),
                "children": [stable_block(child) for child in block.get("children") or [] if isinstance(child, dict)],
            }

        payload = {
            "document_id": snapshot.get("document_id") or "",
            "root_blocks": [stable_block(block) for block in snapshot.get("root_blocks") or [] if isinstance(block, dict)],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_document_url(self, url: str) -> dict[str, str] | None:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
        if "feishu.cn" not in host and "larksuite.com" not in host:
            return None
        segments = [urllib.parse.unquote(item) for item in parsed.path.split("/") if item]
        for index, segment in enumerate(segments):
            normalized = segment.lower()
            if normalized in {"docx", "doc", "docs", "wiki"} and index + 1 < len(segments):
                kind = "docx" if normalized in {"docx", "doc", "docs"} else "wiki"
                token = re.sub(r"[^A-Za-z0-9_-]", "", segments[index + 1])
                if token:
                    return {"kind": kind, "token": token}
        query = urllib.parse.parse_qs(parsed.query)
        for key, kind in (("docx", "docx"), ("doc_token", "docx"), ("document_id", "docx"), ("wiki", "wiki"), ("wiki_id", "wiki")):
            values = query.get(key) or []
            if values:
                token = re.sub(r"[^A-Za-z0-9_-]", "", values[0])
                if token:
                    return {"kind": kind, "token": token}
        return None

    def _resolve_wiki_document(self, node_token: str) -> tuple[str, str]:
        data = self._request("GET", "/wiki/v2/spaces/get_node", params={"token": node_token})
        node = data.get("data", {}).get("node", {}) if isinstance(data, dict) else {}
        if not isinstance(node, dict):
            node = {}
        obj_token = self._pick(node, ("obj_token",), ("obj", "obj_token"), ("document_id",), ("token",))
        obj_type = self._pick(node, ("obj_type",), ("obj", "obj_type"), ("type",)) or "docx"
        if not obj_token:
            obj_token = self._pick(data, ("data", "obj_token"), ("data", "document_id"))
        if not obj_token:
            raise RuntimeError("未能从 wiki 节点解析 obj_token")
        return obj_token, obj_type

    def _read_docx_raw_content(self, document_id: str) -> str:
        data = self._request("GET", f"/docx/v1/documents/{document_id}/raw_content")
        return self._extract_readable_text(data)

    def _read_docx_child_blocks(self, document_id: str) -> str:
        blocks = self._list_document_child_blocks(document_id)
        return self._extract_readable_text({"items": blocks})

    def _extract_readable_text(self, payload: Any, *, limit: int = 60000) -> str:
        text_keys = {"title", "content", "text", "plain_text", "raw_content", "summary"}
        ignored_keys = {"token", "id", "document_id", "block_id", "parent_id", "revision_id", "url", "href"}
        values: list[str] = []

        def visit(value: Any, key: str = "") -> None:
            if len("\n".join(values)) >= limit:
                return
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    visit(child_value, str(child_key))
                return
            if isinstance(value, list):
                for item in value:
                    visit(item, key)
                return
            if not isinstance(value, str):
                return
            clean = value.strip()
            if not clean or key in ignored_keys:
                return
            if key not in text_keys and len(clean) < 12:
                return
            if re.fullmatch(r"[A-Za-z0-9_-]{12,}", clean):
                return
            values.append(clean)

        visit(payload)
        compact: list[str] = []
        seen: set[str] = set()
        for value in values:
            for line in value.splitlines():
                clean = line.strip()
                if clean and clean not in seen:
                    seen.add(clean)
                    compact.append(clean)
                if len("\n".join(compact)) >= limit:
                    return "\n".join(compact)[:limit]
        return "\n".join(compact)[:limit]

    def _get_tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._tenant_access_expire_at:
            return self._tenant_access_token
        with self._tenant_access_token_lock:
            now = time.time()
            if self._tenant_access_token and now < self._tenant_access_expire_at:
                return self._tenant_access_token
            if not self.app_id or not self.app_secret:
                raise RuntimeError("飞书 API 配置缺少 app_id/app_secret")

            payload = {"app_id": self.app_id, "app_secret": self.app_secret}
            headers = {"Content-Type": "application/json; charset=utf-8"}
            try:
                response = requests.post(f"{self.api_base_url}/auth/v3/tenant_access_token/internal", json=payload, headers=headers, timeout=20)
            except requests.RequestException as exc:
                raise RuntimeError(f"获取 tenant_access_token 失败：{exc}") from exc
            try:
                data = response.json()
            except ValueError:
                data = {"raw": response.text}
            if response.status_code >= 400:
                raise RuntimeError(f"获取 tenant_access_token 失败 status={response.status_code}, body={data}")

            code = data.get("code")
            if code not in {None, 0}:
                raise RuntimeError(f"获取 tenant_access_token 失败 code={code}, msg={data.get('msg')}")

            token = self._extract_payload_value(data, "tenant_access_token")
            if not token:
                token = self._extract_payload_value(data, "data", "tenant_access_token")
            if not token:
                raise RuntimeError("返回值中未找到 tenant_access_token")

            expire = data.get("expire") or self._extract_payload_value(data, "data", "expire")
            try:
                expire_seconds = float(expire) if expire not in (None, "") else 3600.0
            except (TypeError, ValueError):
                expire_seconds = 3600.0
            self._tenant_access_token = token
            self._tenant_access_expire_at = now + max(expire_seconds - 60, 60)
            return token

    def _get_or_create_document(self, doc_name: str) -> tuple[str, str]:
        mapping = self._doc_mapping.get(doc_name)
        if isinstance(mapping, dict):
            doc_id = mapping.get("document_id", "")
            doc_url = mapping.get("doc_url", "")
            if doc_id:
                return doc_id, doc_url

        payload = {"title": self._safe_text_content(doc_name)}
        if self.folder_token:
            payload["folder_token"] = self.folder_token

        data = self._request("POST", "/docx/v1/documents", json_body=payload)
        document_id = self._extract_payload_value(data, "data", "document", "document_id")
        if not document_id:
            document_id = self._extract_payload_value(data, "data", "document_id")
        if not document_id:
            raise RuntimeError(f"创建飞书文档失败：未能从响应中解析 document_id, response={data}")

        doc_url = self._extract_payload_value(data, "data", "document", "url")
        if not doc_url:
            doc_url = self._extract_payload_value(data, "data", "url")
        if not doc_url:
            doc_url = f"{self.web_base_url}/docx/{document_id}"

        self._doc_mapping[doc_name] = {
            "document_id": document_id,
            "doc_url": doc_url,
            "title": self._safe_text_content(doc_name),
        }
        self._save_doc_mapping()
        return document_id, doc_url

    def _create_docx_document(self, doc_name: str) -> tuple[str, str]:
        payload = {"title": self._safe_text_content(doc_name)}
        if self.folder_token:
            payload["folder_token"] = self.folder_token

        data = self._request("POST", "/docx/v1/documents", json_body=payload)
        document_id = self._extract_payload_value(data, "data", "document", "document_id")
        if not document_id:
            document_id = self._extract_payload_value(data, "data", "document_id")
        if not document_id:
            raise RuntimeError(f"创建飞书文档失败：未能从响应中解析 document_id, response={data}")

        doc_url = self._extract_payload_value(data, "data", "document", "url")
        if not doc_url:
            doc_url = self._extract_payload_value(data, "data", "url")
        if not doc_url:
            doc_url = f"{self.web_base_url}/docx/{document_id}"

        return document_id, doc_url

    def _create_knowledge_node(
        self,
        doc_name: str,
        document_id: str,
        space_id: str,
        parent_node_token: str = "",
    ) -> tuple[str, str, str]:
        if not space_id:
            raise RuntimeError("知识库模式缺少知识库空间 ID（knowledge_base_space_id）")

        payload_variants = [
            {
                "title": self._safe_text_content(doc_name),
                "node_type": "origin",
                "obj_type": self.knowledge_base_obj_type,
                "obj_token": document_id,
            },
            {
                "title": self._safe_text_content(doc_name),
                "node_type": "origin",
                "obj_type": self.knowledge_base_obj_type,
                "doc_token": document_id,
            },
        ]
        if parent_node_token:
            for payload in payload_variants:
                payload["parent_node_token"] = parent_node_token

        last_error: RuntimeError | None = None
        for payload in payload_variants:
            try:
                data = self._request("POST", f"/wiki/v2/spaces/{space_id}/nodes", json_body=payload)
                node_token, obj_token, node_url = self._extract_node_fields(data)
                if not obj_token:
                    obj_token = self._extract_payload_value(data, "data", "document", "document_id")
                if node_token and (not node_url or "open.feishu.cn" in node_url):
                    node_url = self._wiki_url(node_token)
                elif not node_url and obj_token:
                    node_url = self._docx_url(obj_token)
                if not node_token or not obj_token:
                    if obj_token:
                        return document_id, obj_token, node_url
                    raise RuntimeError(f"创建知识库节点失败：响应缺失 node_token/obj_token, response={data}")
                return node_token, obj_token, node_url
            except RuntimeError as exc:
                last_error = exc
        raise RuntimeError(f"创建知识库节点失败：{last_error}") from None

    def _find_knowledge_child_node(self, space_id: str, parent_node_token: str, title: str) -> tuple[str, str, str] | None:
        clean_title = self._safe_text_content(title)
        page_token = ""
        while True:
            params = {"parent_node_token": parent_node_token, "page_size": 50}
            if page_token:
                params["page_token"] = page_token
            data = self._request("GET", f"/wiki/v2/spaces/{space_id}/nodes", params=params)
            payload = data.get("data", {}) if isinstance(data, dict) else {}
            items = payload.get("items", []) if isinstance(payload, dict) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("title") or "").strip() != clean_title:
                    continue
                obj_type = str(item.get("obj_type") or "").lower()
                if obj_type not in {"docx", "doc"}:
                    continue
                document_id = str(item.get("obj_token") or "")
                node_token = str(item.get("node_token") or "")
                if document_id and node_token:
                    return document_id, self._wiki_url(node_token), node_token
            if not payload.get("has_more"):
                break
            page_token = str(payload.get("page_token") or "")
            if not page_token:
                break
        return None

    def _knowledge_space_id_for_parent_node(self, parent_node_token: str) -> str:
        data = self._request("GET", "/wiki/v2/spaces/get_node", params={"token": parent_node_token})
        node = data.get("data", {}).get("node", {}) if isinstance(data, dict) else {}
        if not isinstance(node, dict):
            node = {}
        space_id = str(node.get("space_id") or self._pick(data, ("data", "space_id"), ("data", "node", "space_id")) or "").strip()
        if space_id:
            return space_id
        for item in self.knowledge_base_spaces:
            if item.get("parent_node_token") == parent_node_token and item.get("space_id"):
                return item["space_id"]
        raise RuntimeError("目标知识库节点缺少 space_id")

    def list_knowledge_child_nodes(self, parent_node_token: str) -> list[dict[str, str]]:
        self._require_credentials()
        space_id = self._knowledge_space_id_for_parent_node(parent_node_token)
        items: list[dict[str, str]] = []
        page_token = ""
        while True:
            params = {"parent_node_token": parent_node_token, "page_size": 50}
            if page_token:
                params["page_token"] = page_token
            data = self._request("GET", f"/wiki/v2/spaces/{space_id}/nodes", params=params)
            payload = data.get("data", {}) if isinstance(data, dict) else {}
            batch = payload.get("items", []) if isinstance(payload, dict) else []
            for item in batch:
                if not isinstance(item, dict):
                    continue
                obj_type = str(item.get("obj_type") or "").lower()
                if obj_type not in {"docx", "doc"}:
                    continue
                node_token = str(item.get("node_token") or "")
                obj_token = str(item.get("obj_token") or "")
                title = str(item.get("title") or "").strip()
                if not node_token or not obj_token or not title:
                    continue
                items.append(
                    {
                        "title": title,
                        "document_id": obj_token,
                        "node_token": node_token,
                        "doc_url": self._wiki_url(node_token),
                        "space_id": space_id,
                    }
                )
            if not payload.get("has_more"):
                break
            page_token = str(payload.get("page_token") or "")
            if not page_token:
                break
        return items

    def resolve_wiki_node_metadata(self, node_token: str) -> dict[str, str | bool]:
        """Resolve the stable identity needed by tenant-scoped resource sync."""
        self._require_credentials()
        token = str(node_token or "").strip()
        if not token:
            raise RuntimeError("wiki 节点 token 不能为空")
        data = self._request("GET", "/wiki/v2/spaces/get_node", params={"token": token})
        raw = data.get("data", {}).get("node", {}) if isinstance(data, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        node_token = str(raw.get("node_token") or raw.get("token") or token).strip()
        obj_token = str(raw.get("obj_token") or raw.get("document_id") or "").strip()
        obj_type = str(raw.get("obj_type") or raw.get("type") or "").strip().lower()
        space_id = str(raw.get("space_id") or self._pick(data, ("data", "space_id")) or "").strip()
        if not node_token or not obj_token or obj_type not in {"docx", "doc", "bitable", "sheet"} or not space_id:
            raise RuntimeError("wiki 节点缺少可同步的稳定身份")
        return {
            "node_token": node_token,
            "obj_token": obj_token,
            "obj_type": "docx" if obj_type == "doc" else obj_type,
            "title": str(raw.get("title") or raw.get("name") or node_token).strip(),
            "space_id": space_id,
            "parent_node_token": str(raw.get("parent_node_token") or "").strip(),
            "has_child": bool(raw.get("has_child") or raw.get("has_children")),
        }

    def list_knowledge_resource_nodes(self, parent_node_token: str) -> list[dict[str, str | bool]]:
        """Enumerate docx, bitable and sheet descendants under one wiki node."""
        self._require_credentials()
        root = self.resolve_wiki_node_metadata(parent_node_token)
        space_id = str(root["space_id"])
        queue = [str(root["node_token"])]
        seen: set[str] = set()
        resources: dict[str, dict[str, str | bool]] = {}
        while queue:
            parent = queue.pop(0)
            if parent in seen:
                continue
            seen.add(parent)
            page_token = ""
            while True:
                params: dict[str, str | int] = {"parent_node_token": parent, "page_size": 50}
                if page_token:
                    params["page_token"] = page_token
                data = self._request("GET", f"/wiki/v2/spaces/{space_id}/nodes", params=params)
                payload = data.get("data", {}) if isinstance(data, dict) else {}
                batch = payload.get("items", []) if isinstance(payload, dict) else []
                if not isinstance(batch, list):
                    raise RuntimeError("知识库子节点返回格式无效")
                for raw in batch:
                    if not isinstance(raw, dict):
                        continue
                    child_token = str(raw.get("node_token") or raw.get("token") or "").strip()
                    if not child_token:
                        continue
                    obj_type = str(raw.get("obj_type") or raw.get("type") or "").strip().lower()
                    if obj_type in {"doc", "docx", "bitable", "sheet"}:
                        resources.setdefault(
                            child_token,
                            {
                                "node_token": child_token,
                                "obj_token": str(raw.get("obj_token") or raw.get("document_id") or "").strip(),
                                "obj_type": "docx" if obj_type == "doc" else obj_type,
                                "title": str(raw.get("title") or raw.get("name") or child_token).strip(),
                                "space_id": space_id,
                                "parent_node_token": str(raw.get("parent_node_token") or parent).strip(),
                                "has_child": bool(raw.get("has_child") or raw.get("has_children")),
                            },
                        )
                    if bool(raw.get("has_child") or raw.get("has_children")):
                        queue.append(child_token)
                if not payload.get("has_more"):
                    break
                page_token = str(payload.get("page_token") or "").strip()
                if not page_token:
                    break
        return [item for item in resources.values() if item.get("obj_token")]

    def replace_child_entry_under_node(self, parent_node_token: str, child_doc_name: str, content: str) -> dict[str, str]:
        self._require_credentials()
        space_id = self._knowledge_space_id_for_parent_node(parent_node_token)
        existing = self._find_knowledge_child_node(space_id, parent_node_token, child_doc_name)
        if existing:
            document_id, doc_url, node_token = existing
        else:
            document_id, doc_url = self._create_docx_document(child_doc_name)
            try:
                node_token, obj_token, node_url = self._create_knowledge_node(
                    child_doc_name,
                    document_id,
                    space_id,
                    parent_node_token,
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    "知识库写入失败：无法在目标认知池下创建子文档，请确认应用具备 wiki:wiki 或 "
                    "wiki:space:write_only 权限，并且应用已加入该知识库。"
                ) from exc
            if obj_token:
                document_id = obj_token
            if node_url:
                doc_url = node_url
        self._replace_document_content(document_id, content)
        if node_token:
            doc_url = self._wiki_url(node_token)
        map_key = self._kb_child_map_key(parent_node_token, child_doc_name, space_id)
        self._doc_mapping[map_key] = {
            "document_id": document_id,
            "title": self._safe_text_content(child_doc_name),
            "doc_url": doc_url or self._docx_url(document_id),
            "knowledge_base_space_id": space_id,
            "knowledge_base_parent_node_token": parent_node_token,
            "node_token": node_token,
        }
        self._save_doc_mapping()
        return {
            "status": "synced",
            "doc": self._doc_mapping[map_key]["doc_url"],
            "document_id": document_id,
            "node_token": node_token,
            "mode": "knowledge_base",
            "space_id": space_id,
            "parent_node_token": parent_node_token,
        }

    def replace_child_entry_under_node_blocks(
        self,
        parent_node_token: str,
        child_doc_name: str,
        children: list[dict[str, Any]],
        *,
        source_hash: str = "",
    ) -> dict[str, str]:
        self._require_credentials()
        space_id = self._knowledge_space_id_for_parent_node(parent_node_token)
        existing = self._find_knowledge_child_node(space_id, parent_node_token, child_doc_name)
        if existing:
            document_id, doc_url, node_token = existing
        else:
            document_id, doc_url = self._create_docx_document(child_doc_name)
            try:
                node_token, obj_token, node_url = self._create_knowledge_node(
                    child_doc_name,
                    document_id,
                    space_id,
                    parent_node_token,
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    "知识库写入失败：无法在目标认知池下创建子文档，请确认应用具备 wiki:wiki 或 "
                    "wiki:space:write_only 权限，并且应用已加入该知识库。"
                ) from exc
            if obj_token:
                document_id = obj_token
            if node_url:
                doc_url = node_url
        self._replace_document_blocks(document_id, children, expected_source_hash=source_hash)
        if node_token:
            doc_url = self._wiki_url(node_token)
        map_key = self._kb_child_map_key(parent_node_token, child_doc_name, space_id)
        self._doc_mapping[map_key] = {
            "document_id": document_id,
            "title": self._safe_text_content(child_doc_name),
            "doc_url": doc_url or self._docx_url(document_id),
            "knowledge_base_space_id": space_id,
            "knowledge_base_parent_node_token": parent_node_token,
            "node_token": node_token,
        }
        self._save_doc_mapping()
        return {
            "status": "synced",
            "doc": self._doc_mapping[map_key]["doc_url"],
            "document_id": document_id,
            "node_token": node_token,
            "mode": "knowledge_base",
            "space_id": space_id,
            "parent_node_token": parent_node_token,
            "render_mode": "docx_blocks",
        }

    def _get_or_create_knowledge_base_entry(self, doc_name: str) -> tuple[str, str, str]:
        space_id, parent_node_token = self._require_knowledge_base(doc_name)
        map_key = self._kb_map_key(doc_name, space_id)

        mapping = self._doc_mapping.get(map_key)
        if isinstance(mapping, dict):
            doc_id = mapping.get("document_id", "")
            doc_url = mapping.get("doc_url", "")
            node_token = mapping.get("node_token", "")
            if doc_id and (doc_url or node_token):
                if node_token and (not doc_url or "open.feishu.cn" in doc_url):
                    doc_url = self._wiki_url(node_token)
                    mapping["doc_url"] = doc_url
                    self._doc_mapping[map_key] = mapping
                    self._save_doc_mapping()
                elif not doc_url:
                    doc_url = self._docx_url(doc_id)
                return doc_id, doc_url, space_id

        # 历史数据迁移：已有文档但没入库知识库节点时，尝试补建一次节点
        mapping = self._doc_mapping.get(doc_name)
        if isinstance(mapping, dict):
            doc_id = mapping.get("document_id", "")
            if doc_id:
                try:
                    _node_token, _obj_token, node_url = self._create_knowledge_node(
                        doc_name,
                        doc_id,
                        space_id,
                        parent_node_token,
                    )
                except RuntimeError:
                    raise RuntimeError(
                        "知识库写入失败：历史记录里的文档无法在目标知识库创建节点，请确认应用具备 wiki:wiki 或 "
                        "wiki:space:write_only 权限，并且应用已加入该知识库。"
                    )

                document_id = _obj_token or doc_id
                doc_url = node_url or mapping.get("doc_url", "")
                mapping_payload = {
                    "document_id": document_id,
                    "title": self._safe_text_content(doc_name),
                    "doc_url": doc_url or self._docx_url(document_id),
                    "knowledge_base_space_id": space_id,
                    "knowledge_base_parent_node_token": parent_node_token,
                }
                if _node_token:
                    mapping_payload["node_token"] = _node_token
                self._doc_mapping[map_key] = mapping_payload
                if doc_name in self._doc_mapping and doc_name != map_key:
                    del self._doc_mapping[doc_name]
                self._save_doc_mapping()
                return document_id, mapping_payload["doc_url"], space_id

        document_id, doc_url = self._create_docx_document(doc_name)
        try:
            node_token, obj_token, node_url = self._create_knowledge_node(
                doc_name,
                document_id,
                space_id,
                parent_node_token,
            )
        except RuntimeError as exc:
            raise RuntimeError(
                "知识库写入失败：无法在目标知识库创建节点，请确认应用具备 wiki:wiki 或 "
                "wiki:space:write_only 权限，并且应用已加入该知识库。"
            ) from exc
        if obj_token:
            document_id = obj_token
        if node_url:
            doc_url = node_url

        mapping_payload = {
            "document_id": document_id,
            "title": self._safe_text_content(doc_name),
            "doc_url": doc_url,
            "knowledge_base_space_id": space_id,
            "knowledge_base_parent_node_token": parent_node_token,
        }
        if node_token:
            mapping_payload["node_token"] = node_token
        self._doc_mapping[map_key] = mapping_payload
        self._save_doc_mapping()
        if not doc_url and document_id:
            doc_url = self._docx_url(document_id)
        return document_id, doc_url, space_id

    def _get_or_create_knowledge_base_child_entry(self, parent_doc_name: str, child_doc_name: str) -> tuple[str, str, str]:
        _parent_document_id, _parent_doc_url, space_id = self._get_or_create_knowledge_base_entry(parent_doc_name)
        parent_mapping = self._doc_mapping.get(self._kb_map_key(parent_doc_name, space_id))
        parent_node_token = parent_mapping.get("node_token", "") if isinstance(parent_mapping, dict) else ""
        if not parent_node_token:
            raise RuntimeError(f"知识库父文档缺少 node_token，无法创建子文档：{parent_doc_name}")

        map_key = self._kb_child_map_key(parent_node_token, child_doc_name, space_id)
        mapping = self._doc_mapping.get(map_key)
        if isinstance(mapping, dict):
            doc_id = mapping.get("document_id", "")
            doc_url = mapping.get("doc_url", "")
            node_token = mapping.get("node_token", "")
            if doc_id and (doc_url or node_token):
                if node_token and (not doc_url or "open.feishu.cn" in doc_url):
                    doc_url = self._wiki_url(node_token)
                    mapping["doc_url"] = doc_url
                    self._doc_mapping[map_key] = mapping
                    self._save_doc_mapping()
                elif not doc_url:
                    doc_url = self._docx_url(doc_id)
                return doc_id, doc_url, space_id

        existing = self._find_knowledge_child_node(space_id, parent_node_token, child_doc_name)
        if existing:
            document_id, doc_url, node_token = existing
            self._doc_mapping[map_key] = {
                "document_id": document_id,
                "title": self._safe_text_content(child_doc_name),
                "doc_url": doc_url,
                "knowledge_base_space_id": space_id,
                "knowledge_base_parent_node_token": parent_node_token,
                "parent_doc_title": self._safe_text_content(parent_doc_name),
                "node_token": node_token,
            }
            self._save_doc_mapping()
            return document_id, doc_url, space_id

        document_id, doc_url = self._create_docx_document(child_doc_name)
        try:
            node_token, obj_token, node_url = self._create_knowledge_node(
                child_doc_name,
                document_id,
                space_id,
                parent_node_token,
            )
        except RuntimeError as exc:
            raise RuntimeError(
                "知识库写入失败：无法在任务池下创建子文档，请确认应用具备 wiki:wiki 或 "
                "wiki:space:write_only 权限，并且应用已加入该知识库。"
            ) from exc
        if obj_token:
            document_id = obj_token
        if node_url:
            doc_url = node_url

        mapping_payload = {
            "document_id": document_id,
            "title": self._safe_text_content(child_doc_name),
            "doc_url": doc_url or self._docx_url(document_id),
            "knowledge_base_space_id": space_id,
            "knowledge_base_parent_node_token": parent_node_token,
            "parent_doc_title": self._safe_text_content(parent_doc_name),
        }
        if node_token:
            mapping_payload["node_token"] = node_token
        self._doc_mapping[map_key] = mapping_payload
        self._save_doc_mapping()
        return document_id, mapping_payload["doc_url"], space_id

    def _append_to_document(self, document_id: str, content: str) -> None:
        children = self._content_to_docx_blocks(content)
        self._append_blocks_to_document(document_id, children)

    def _content_to_docx_blocks(self, content: str) -> list[dict[str, Any]]:
        return FeishuDocxBlockRenderer(self._heading_block, self._text_block).render(self._safe_text_content(content))

    def prepare_opc_feishu_publish_plan(
        self,
        plan: dict[str, Any],
        *,
        expected_source_sha256: str = "",
    ) -> dict[str, Any]:
        """Validate and adapt an OPC publish plan without performing any I/O."""

        execution = self._require_opc_owner_execution()

        def fail(subject: str, detail: str) -> None:
            raise ValueError(f"opc feishu publish plan {subject}: {detail}")

        def json_value(value: Any, path: str) -> Any:
            if value is None or isinstance(value, (str, bool, int)):
                return value
            if isinstance(value, float):
                if value != value or value in (float("inf"), float("-inf")):
                    fail("block", f"{path} contains a non-finite number")
                return value
            if isinstance(value, list):
                return [json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
            if isinstance(value, dict):
                cloned: dict[str, Any] = {}
                for key, item in value.items():
                    if not isinstance(key, str):
                        fail("block", f"{path} contains a non-string key")
                    if key in {"source_spans", "mermaid_asset_id", "cell_values", "source", "uploadable", "media_type"}:
                        fail("block", f"{path}.{key} is audit-only")
                    cloned[key] = json_value(item, f"{path}.{key}")
                return cloned
            fail("block", f"{path} is not JSON-compatible")

        def exact_int(value: Any, path: str, *, minimum: int = 0) -> int:
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                fail("block", f"{path} must be an integer >= {minimum}")
            return value

        def source_spans(value: Any, path: str) -> list[list[int]]:
            if not isinstance(value, list) or not value:
                fail("block", f"{path} must be a non-empty list")
            spans: list[list[int]] = []
            previous_end = -1
            for index, span in enumerate(value):
                if not isinstance(span, list) or len(span) != 2:
                    fail("block", f"{path}[{index}] must be [start, end]")
                start = exact_int(span[0], f"{path}[{index}][0]")
                end = exact_int(span[1], f"{path}[{index}][1]")
                if end <= start or start < previous_end:
                    fail("block", f"{path}[{index}] is invalid or out of order")
                spans.append([start, end])
                previous_end = end
            return spans

        def text_elements(value: Any, path: str) -> list[dict[str, Any]]:
            if not isinstance(value, list):
                fail("block", f"{path} must be a list")
            elements: list[dict[str, Any]] = []
            for index, element in enumerate(value):
                element_path = f"{path}[{index}]"
                if not isinstance(element, dict) or len(element) != 1:
                    fail("block", f"{element_path} must contain one native inline element")
                if "text_run" in element:
                    text_run = element["text_run"]
                    if not isinstance(text_run, dict) or set(text_run) - {"content", "text_element_style"}:
                        fail("block", f"{element_path}.text_run is malformed")
                    content = text_run.get("content")
                    if not isinstance(content, str):
                        fail("block", f"{element_path}.text_run.content must be a string")
                    style = text_run.get("text_element_style", {})
                    if not isinstance(style, dict):
                        fail("block", f"{element_path}.text_run.text_element_style must be an object")
                    elements.append(
                        {
                            "text_run": {
                                "content": content,
                                "text_element_style": json_value(style, f"{element_path}.text_run.text_element_style"),
                            }
                        }
                    )
                    continue
                if "equation" in element:
                    equation = element["equation"]
                    if not isinstance(equation, dict) or set(equation) != {"content"}:
                        fail("block", f"{element_path}.equation is malformed")
                    content = equation.get("content")
                    if not isinstance(content, str) or not content:
                        fail("block", f"{element_path}.equation.content must be non-empty")
                    elements.append({"equation": {"content": content}})
                    continue
                fail("block", f"{element_path} has an unsupported inline element")
            return elements

        if not isinstance(plan, dict):
            fail("schema", "plan must be an object")
        if plan.get("schema_version") != "opc.feishu-publish-plan.v1":
            fail("schema", "expected opc.feishu-publish-plan.v1")

        source_sha256 = plan.get("source_sha256")
        if not isinstance(source_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None:
            fail("source", "source_sha256 must be a lowercase SHA-256")
        if expected_source_sha256:
            if not isinstance(expected_source_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256) is None:
                fail("source", "expected_source_sha256 must be a lowercase SHA-256")
            if source_sha256 != expected_source_sha256:
                fail("source", "source_sha256 does not match the expected source")

        unmapped_count = plan.get("unmapped_business_node_count")
        unmapped_nodes = plan.get("unmapped_business_nodes")
        if isinstance(unmapped_count, bool) or not isinstance(unmapped_count, int) or unmapped_count != 0:
            fail("unmapped", "unmapped_business_node_count must be zero")
        if not isinstance(unmapped_nodes, list) or unmapped_nodes:
            fail("unmapped", "unmapped_business_nodes must be an empty list")

        publication = plan.get("publication")
        if not isinstance(publication, dict):
            fail("publish", "publication must be an object")
        blocking_errors = publication.get("blocking_errors", [])
        if not isinstance(blocking_errors, list):
            fail("publish", "blocking_errors must be a list")
        if blocking_errors:
            error_text = json.dumps(blocking_errors, ensure_ascii=False, sort_keys=True)
            fail("publish", f"blocked by {error_text}")
        if publication.get("status") != "ready" or publication.get("publishable") is not True:
            fail("publish", "publication is not ready and publishable")

        blocks = plan.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            fail("block", "blocks must be a non-empty list")
        assets = plan.get("mermaid_assets")
        if not isinstance(assets, list):
            fail("mermaid", "mermaid_assets must be a list")

        asset_by_id: dict[str, dict[str, Any]] = {}
        for index, asset in enumerate(assets):
            path = f"mermaid_assets[{index}]"
            if not isinstance(asset, dict):
                fail("mermaid", f"{path} must be an object")
            asset_id = asset.get("asset_id")
            if not isinstance(asset_id, str) or re.fullmatch(r"mermaid-[0-9a-f]{64}", asset_id) is None:
                fail("mermaid", f"{path}.asset_id is invalid")
            if asset_id in asset_by_id:
                fail("mermaid", f"duplicate asset identity {asset_id}")
            if exact_int(asset.get("sequence"), f"{path}.sequence") != index:
                fail("mermaid", f"{path}.sequence must match asset order")
            source = asset.get("source")
            rendered = asset.get("rendered_image")
            if not isinstance(source, dict) or not isinstance(rendered, dict):
                fail("mermaid", f"{path} requires source and rendered_image objects")
            source_content = source.get("content")
            source_span = source.get("source_span")
            source_digest = source.get("sha256")
            if source.get("language") != "mermaid" or not isinstance(source_content, str) or not source_content:
                fail("mermaid", f"{path}.source is missing Mermaid content")
            if not isinstance(source_span, list) or len(source_span) != 2:
                fail("mermaid", f"{path}.source.source_span is invalid")
            normalized_span = source_spans([source_span], f"{path}.source.source_span")[0]
            if not isinstance(source_digest, str) or re.fullmatch(r"[0-9a-f]{64}", source_digest) is None:
                fail("mermaid", f"{path}.source.sha256 is invalid")
            image_data = rendered.get("data")
            media_type = rendered.get("media_type")
            if not isinstance(image_data, str) or not image_data or not isinstance(media_type, str) or not media_type:
                fail("mermaid", f"{path}.rendered_image payload is empty")
            if rendered.get("uploadable") is not True:
                fail("mermaid", f"{path}.rendered_image is not uploadable")
            asset_by_id[asset_id] = {
                "content": source_content,
                "source_span": normalized_span,
                "source_sha256": source_digest,
                "image_data": image_data,
                "media_type": media_type,
                "image_index": None,
                "source_index": None,
            }

        normalized_blocks: list[dict[str, Any]] = []
        mappings: list[dict[str, Any]] = []
        image_uploads: list[dict[str, Any]] = []
        code_language_values = {
            "plaintext": 1,
            "text": 1,
            "plain text": 1,
            "abap": 2,
            "ada": 3,
            "apache": 4,
            "arduino": 5,
            "bash": 6,
            "c": 7,
            "csharp": 8,
            "c#": 8,
            "cpp": 9,
            "c++": 9,
            "clojure": 10,
            "coffeescript": 11,
            "css": 12,
            "dart": 13,
            "delphi": 14,
            "django": 15,
            "dockerfile": 16,
            "erlang": 17,
            "fortran": 18,
            "foxpro": 19,
            "go": 20,
            "groovy": 21,
            "haskell": 22,
            "html": 23,
            "http": 24,
            "json": 25,
            "java": 26,
            "javascript": 27,
            "js": 27,
            "julia": 28,
            "kotlin": 29,
            "latex": 30,
            "lisp": 31,
            "lua": 32,
            "matlab": 33,
            "makefile": 34,
            "markdown": 35,
            "nginx": 36,
            "objective-c": 37,
            "opengl": 38,
            "pascal": 39,
            "perl": 40,
            "php": 41,
            "powershell": 42,
            "protobuf": 43,
            "python": 44,
            "r": 45,
            "ruby": 46,
            "rust": 47,
            "sas": 48,
            "scss": 49,
            "scala": 50,
            "scheme": 51,
            "shell": 52,
            "sh": 52,
            "sql": 53,
            "swift": 54,
            "thrift": 55,
            "typescript": 56,
            "ts": 56,
            "visual basic": 57,
            "vb": 57,
            "xml": 58,
            "yaml": 59,
            "yml": 59,
            "mermaid": 60,
            "graphql": 61,
        }
        allowed_text_types = {
            2: "text",
            **{block_type: f"heading{block_type - 2}" for block_type in range(3, 12)},
            12: "bullet",
            13: "ordered",
            15: "quote",
        }

        for index, block in enumerate(blocks):
            path = f"blocks[{index}]"
            if not isinstance(block, dict):
                fail("block", f"{path} must be an object")
            block_type = block.get("block_type")
            if isinstance(block_type, bool) or not isinstance(block_type, int):
                fail("block", f"{path}.block_type must be an integer")
            spans = source_spans(block.get("source_spans"), f"{path}.source_spans")
            mapping: dict[str, Any] = {
                "source_block_index": index,
                "source_block_type": block_type,
                "child_index": index,
                "source_spans": spans,
            }

            if block_type in allowed_text_types:
                key = allowed_text_types[block_type]
                if set(block) != {"block_type", key, "source_spans"}:
                    fail("block", f"{path} has fields inconsistent with block_type {block_type}")
                container = block.get(key)
                if not isinstance(container, dict) or set(container) - {"elements", "style"}:
                    fail("block", f"{path}.{key} is malformed")
                native_container: dict[str, Any] = {
                    "elements": text_elements(container.get("elements"), f"{path}.{key}.elements")
                }
                if "style" in container:
                    if not isinstance(container["style"], dict):
                        fail("block", f"{path}.{key}.style must be an object")
                    native_container["style"] = json_value(container["style"], f"{path}.{key}.style")
                native_block = {"block_type": block_type, key: native_container}
            elif block_type == 17:
                if set(block) != {"block_type", "divider", "source_spans"} or not isinstance(block.get("divider"), dict):
                    fail("block", f"{path}.divider is malformed")
                native_block = {"block_type": 17, "divider": json_value(block["divider"], f"{path}.divider")}
            elif block_type == 18:
                if set(block) != {"block_type", "equation", "source_spans"}:
                    fail("block", f"{path}.equation fields are malformed")
                equation = block.get("equation")
                if not isinstance(equation, dict) or set(equation) != {"elements"}:
                    fail("block", f"{path}.equation is malformed")
                elements = text_elements(equation.get("elements"), f"{path}.equation.elements")
                if not elements or any(set(element) != {"equation"} for element in elements):
                    fail("block", f"{path}.equation must contain non-empty equation elements")
                native_block = {"block_type": 18, "equation": {"elements": elements}}
            elif block_type == 14:
                allowed = {"block_type", "code", "source_spans"}
                if "mermaid_asset_id" in block:
                    allowed.add("mermaid_asset_id")
                if set(block) != allowed:
                    fail("block", f"{path}.code fields are malformed")
                code = block.get("code")
                if not isinstance(code, dict) or set(code) != {"language", "content"}:
                    fail("block", f"{path}.code is malformed")
                language = code.get("language")
                content = code.get("content")
                if not isinstance(language, str) or not isinstance(content, str):
                    fail("block", f"{path}.code language and content must be strings")
                asset_id = block.get("mermaid_asset_id")
                normalized_language = language.strip().lower()
                if normalized_language == "mermaid":
                    asset = asset_by_id.get(asset_id) if isinstance(asset_id, str) else None
                    if asset is None or asset["content"] != content or asset["source_span"] not in spans:
                        fail("mermaid", f"{path} does not match its registered Mermaid source")
                    if asset["source_index"] is not None:
                        fail("mermaid", f"duplicate source block for {asset_id}")
                    asset["source_index"] = index
                    mapping["mermaid_asset_id"] = asset_id
                    mapping["mermaid_source_sha256"] = asset["source_sha256"]
                elif asset_id is not None:
                    fail("mermaid", f"{path} has a Mermaid identity on non-Mermaid code")
                native_block = {
                    "block_type": 14,
                    "code": {
                        "elements": [{"text_run": {"content": content}}],
                        "style": {"language": code_language_values.get(normalized_language, 1), "wrap": True},
                    },
                }
                mapping["code_language"] = language
            elif block_type == 31:
                if set(block) != {"block_type", "table", "cell_values", "source_spans"}:
                    fail("table", f"{path} fields are malformed")
                table = block.get("table")
                rows = block.get("cell_values")
                if not isinstance(table, dict) or set(table) != {"property"} or not isinstance(table.get("property"), dict):
                    fail("table", f"{path}.table is malformed")
                if set(table["property"]) != {"row_size", "column_size"}:
                    fail("table", f"{path}.table.property is malformed")
                if not isinstance(rows, list) or not rows or not all(isinstance(row, list) for row in rows):
                    fail("table", f"{path}.cell_values must be a non-empty matrix")
                column_count = len(rows[0])
                if column_count < 1 or any(len(row) != column_count for row in rows):
                    fail("table", f"{path}.cell_values must be rectangular and non-empty")
                if any(not isinstance(cell, str) for row in rows for cell in row):
                    fail("table", f"{path}.cell_values must contain only strings")
                row_count = len(rows)
                if exact_int(table["property"].get("row_size"), f"{path}.table.property.row_size", minimum=1) != row_count:
                    fail("table", f"{path} row_size does not match cell_values")
                if exact_int(table["property"].get("column_size"), f"{path}.table.property.column_size", minimum=1) != column_count:
                    fail("table", f"{path} column_size does not match cell_values")
                try:
                    validate_docx_table_create_shape(row_count, column_count)
                except ValueError as exc:
                    fail("table", str(exc))
                copied_rows = [[cell for cell in row] for row in rows]
                native_block = {
                    "_openclaw_kind": NATIVE_TABLE_KIND,
                    "rows": copied_rows,
                }
                mapping["cell_values"] = [[cell for cell in row] for row in rows]
            elif block_type == 27:
                if set(block) != {"block_type", "image", "mermaid_asset_id", "source_spans"}:
                    fail("mermaid", f"{path} image fields are malformed")
                image = block.get("image")
                asset_id = block.get("mermaid_asset_id")
                asset = asset_by_id.get(asset_id) if isinstance(asset_id, str) else None
                if not isinstance(image, dict) or set(image) != {"source", "media_type", "uploadable", "alt"}:
                    fail("mermaid", f"{path}.image is malformed")
                if asset is None:
                    fail("mermaid", f"{path} has no registered Mermaid asset")
                alt = image.get("alt")
                if (
                    image.get("source") != asset["image_data"]
                    or image.get("media_type") != asset["media_type"]
                    or image.get("uploadable") is not True
                    or not isinstance(alt, str)
                    or asset["source_span"] not in spans
                ):
                    fail("mermaid", f"{path} does not match its rendered Mermaid asset")
                if asset["image_index"] is not None:
                    fail("mermaid", f"duplicate image block for {asset_id}")
                asset["image_index"] = index
                mapping["mermaid_asset_id"] = asset_id
                mapping["mermaid_source_sha256"] = asset["source_sha256"]
                native_block = {"block_type": 27, "image": {"token": ""}}
                image_uploads.append(
                    {
                        "child_index": index,
                        "mermaid_asset_id": asset_id,
                        "source": asset["image_data"],
                        "media_type": asset["media_type"],
                        "alt": alt,
                    }
                )
            else:
                fail("block", f"unsupported block_type {block_type} at {path}")

            normalized_blocks.append(native_block)
            mappings.append(mapping)

        for asset_id, asset in asset_by_id.items():
            image_index = asset["image_index"]
            source_index = asset["source_index"]
            if image_index is None or source_index is None:
                fail("mermaid", f"{asset_id} requires both image and source blocks")
            if image_index >= source_index:
                fail("mermaid", f"{asset_id} image must precede its source block")

        return {
            "schema_version": "openclaw.feishu-service-plan.v2",
            "source_sha256": source_sha256,
            "children": normalized_blocks,
            "image_uploads": image_uploads,
            "audit": {
                "unmapped_business_node_count": 0,
                "unmapped_business_nodes": [],
                "block_mappings": mappings,
            },
            "authorization": {
                "type": "resource_owner_oauth",
                "tenant_id": execution["tenant_id"],
                "resource_owner_user_id": execution["resource_owner_user_id"],
                "credential_fingerprint": hashlib.sha256(
                    execution["owner_access_token"].encode("utf-8")
                ).hexdigest(),
            },
            "write_count": 0,
        }

    def open_opc_feishu_publish_transaction(
        self,
        plan: dict[str, Any],
        *,
        target_node_token: str,
        compiler_version: str,
        publication_intent: str,
        ledger_path: str | Path,
        expected_source_sha256: str = "",
    ) -> dict[str, Any]:
        """Prepare an OPC plan, then durably open its canonical local transaction."""

        prepared_plan = self.prepare_opc_feishu_publish_plan(
            plan,
            expected_source_sha256=expected_source_sha256,
        )
        from .opc_feishu_publish_transaction import OpcFeishuPublishTransactionStore

        return OpcFeishuPublishTransactionStore(ledger_path).open(
            prepared_plan,
            source_sha256=prepared_plan["source_sha256"],
            target_node_token=target_node_token,
            compiler_version=compiler_version,
            publication_intent=publication_intent,
        )

    @staticmethod
    def _heading_block(level: int, text: str) -> dict[str, Any]:
        normalized_level = min(max(level, 1), 9)
        block_type = normalized_level + 2
        key = f"heading{normalized_level}"
        return {
            "block_type": block_type,
            key: {"elements": [{"text_run": {"content": str(text or "")[:500]}}]},
        }

    @staticmethod
    def _text_block(text: str) -> dict[str, Any]:
        return {
            "block_type": 2,
            "text": {
                "elements": [
                    {
                        "text_run": {
                            "content": str(text or "")[:1800],
                            "text_element_style": {},
                        }
                    }
                ]
            },
        }

    def _append_blocks_to_document(self, document_id: str, children: list[dict[str, Any]]) -> None:
        if not children:
            return
        last_error: RuntimeError | None = None
        for parent_block_id in (document_id, "root"):
            try:
                pending: list[dict[str, Any]] = []

                def flush_pending() -> None:
                    if not pending:
                        return
                    for index in range(0, len(pending), 20):
                        self._request(
                            "POST",
                            f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children",
                            json_body={"children": pending[index:index + 20]},
                            params={"document_revision_id": -1},
                        )
                    pending.clear()

                for child in children:
                    if child.get("_openclaw_kind") == NATIVE_TABLE_KIND:
                        flush_pending()
                        self._append_native_table_to_document(document_id, child.get("rows") or [])
                    else:
                        pending.append(child)
                flush_pending()
                return
            except RuntimeError as exc:
                last_error = exc

        raise RuntimeError(f"追加飞书文档内容失败: {last_error}") from None

    def _patch_docx_text_elements(self, document_id: str, block_id: str, text: str) -> dict[str, Any]:
        payload = {
            "update_text_elements": {
                "elements": [
                    {
                        "text_run": {
                            "content": str(text or "")[:1800],
                            "text_element_style": {},
                        }
                    }
                ]
            }
        }
        return self._request(
            "PATCH",
            f"/docx/v1/documents/{document_id}/blocks/{block_id}",
            json_body=payload,
            params={"document_revision_id": -1},
        )

    def _insert_docx_children_at(
        self,
        document_id: str,
        parent_block_id: str,
        index: int,
        children: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if len(children) > DOCUMENT_EDIT_PATCH_CREATE_CHILD_BATCH_SIZE:
            raise RuntimeError(
                "document_edit_patch_batch_too_large: "
                f"children={len(children)}, limit={DOCUMENT_EDIT_PATCH_CREATE_CHILD_BATCH_SIZE}"
            )
        return self._request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children",
            json_body={"children": children, "index": int(index)},
            params={"document_revision_id": -1},
        )

    def _insert_docx_table_row_with_values(
        self,
        document_id: str,
        table_block_id: str,
        row_index: int,
        cell_texts: list[str],
    ) -> dict[str, Any]:
        table_block_id = str(table_block_id or "").strip()
        if not table_block_id:
            raise RuntimeError("insert_table_row requires table_block_id")
        if int(row_index) != -1:
            raise RuntimeError("insert_table_row currently supports only append row_index=-1")
        before = self._hydrate_docx_table_block(document_id, table_block_id)
        before_shape = self._extract_docx_table_shape(before)
        before_rows = self._coerce_int(before_shape.get("row_size")) or 0
        column_count = self._coerce_int(before_shape.get("column_size")) or len(cell_texts)
        if column_count <= 0:
            raise RuntimeError(f"insert_table_row cannot resolve column count for table_id={table_block_id}")
        before_expected = before_rows * column_count if before_rows and column_count else 0
        before_cell_ids = self._extract_table_cell_ids(before, before_expected) if before_expected else []
        response = self._request(
            "PATCH",
            f"/docx/v1/documents/{document_id}/blocks/{table_block_id}",
            json_body={"insert_table_row": {"row_index": -1}},
            params={"document_revision_id": -1},
        )
        time.sleep(FEISHU_DOC_WRITE_SLEEP_SEC)
        after = self._hydrate_docx_table_block(document_id, table_block_id)
        after_shape = self._extract_docx_table_shape(after)
        after_rows = self._coerce_int(after_shape.get("row_size")) or before_rows + 1
        after_cols = self._coerce_int(after_shape.get("column_size")) or column_count
        if after_cols != column_count:
            raise RuntimeError(
                "insert_table_row changed table column count: "
                f"before={column_count}, after={after_cols}, table_id={table_block_id}"
            )
        if after_rows < before_rows + 1:
            raise RuntimeError(
                "insert_table_row did not increase row count: "
                f"before={before_rows}, after={after_rows}, table_id={table_block_id}"
            )
        after_expected = after_rows * after_cols
        after_cell_ids = self._extract_table_cell_ids(after, after_expected)
        row_start = (after_rows - 1) * after_cols
        new_cell_ids = after_cell_ids[row_start: row_start + after_cols] if len(after_cell_ids) >= row_start + after_cols else []
        if len(new_cell_ids) < after_cols:
            before_set = set(before_cell_ids)
            new_cell_ids = [cell_id for cell_id in after_cell_ids if cell_id not in before_set][:after_cols]
        if len(new_cell_ids) < after_cols:
            raise RuntimeError(
                "insert_table_row could not resolve inserted cell ids: "
                f"expected={after_cols}, got={len(new_cell_ids)}, table_id={table_block_id}"
            )
        for column_index in range(after_cols):
            text = cell_texts[column_index] if column_index < len(cell_texts) else ""
            self._append_table_cell_text(document_id, new_cell_ids[column_index], text)
        return {
            "status": "insert_table_row_ok",
            "table_block_id": table_block_id,
            "row_index": -1,
            "before_shape": before_shape,
            "after_shape": after_shape,
            "written_cell_ids": new_cell_ids,
            "response_keys": sorted(response.keys()) if isinstance(response, dict) else [],
        }

    def _hydrate_docx_table_block(self, document_id: str, table_block_id: str) -> dict[str, Any]:
        table_block = self._get_docx_block(document_id, table_block_id)
        if not isinstance(table_block, dict):
            table_block = {}
        children = table_block.get("children") if isinstance(table_block.get("children"), list) else []
        if not children:
            children = self._get_docx_children(document_id, table_block_id)
            if children:
                table_block = {**table_block, "children": children}
        return table_block

    @staticmethod
    def _extract_docx_table_shape(table_block: dict[str, Any]) -> dict[str, Any]:
        table = table_block.get("table") if isinstance(table_block, dict) else {}
        property_payload = table.get("property") if isinstance(table, dict) else {}
        if not isinstance(property_payload, dict):
            return {}
        return {
            "row_size": property_payload.get("row_size"),
            "column_size": property_payload.get("column_size"),
        }

    def _resolve_docx_child_insert_index(
        self,
        document_id: str,
        parent_block_id: str,
        anchor_block_id: str,
        *,
        after: bool = True,
    ) -> int:
        children = self._get_docx_children(document_id, parent_block_id)
        for index, child in enumerate(children):
            if self._extract_block_id(child) == anchor_block_id:
                return index + 1 if after else index
        raise RuntimeError(
            "document_edit_anchor_not_found: "
            f"document_id={document_id}, parent_block_id={parent_block_id}, anchor_block_id={anchor_block_id}"
        )

    def _delete_docx_child_range(self, document_id: str, parent_block_id: str, start_index: int, end_index: int) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children/batch_delete",
            json_body={"start_index": int(start_index), "end_index": int(end_index)},
            params={"document_revision_id": -1},
        )

    def _append_native_table_to_document(self, document_id: str, rows: list[list[str]]) -> None:
        chunks = self._table_chunks(rows)
        ensure_docx_tables_write_budget(chunks)
        for chunk in chunks:
            self._append_native_table_chunk(document_id, chunk)

    @staticmethod
    def _table_chunks(rows: list[list[str]]) -> list[list[list[str]]]:
        return chunk_docx_table_rows(rows)

    def _append_native_table_chunk(self, document_id: str, rows: list[list[str]]) -> None:
        if not rows:
            return
        row_count = len(rows)
        column_count = max(len(row) for row in rows)
        validate_docx_table_create_shape(row_count, column_count)
        ensure_docx_table_write_budget(rows)
        start_index = len(self._list_document_child_blocks(document_id))
        try:
            payload = self._request(
                "POST",
                f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                json_body={"children": [{"block_type": 31, "table": {"property": {"row_size": row_count, "column_size": column_count}}}], "index": -1},
                params={"document_revision_id": -1},
            )
            table_block = self._find_created_table(payload)
            time.sleep(1.2)
            table_id = str(table_block.get("block_id") or "")
            expected = row_count * column_count
            cell_ids = self._extract_table_cell_ids(table_block, expected)
            if len(cell_ids) < expected and table_id:
                hydrated = self._get_docx_block(document_id, table_id)
                cell_ids = self._extract_table_cell_ids(hydrated, expected)
            if len(cell_ids) < expected and table_id:
                children = self._get_docx_children(document_id, table_id)
                cell_ids = [self._extract_block_id(item) for item in children]
                cell_ids = [item for item in cell_ids if item]
            if len(cell_ids) < expected:
                raise RuntimeError(f"飞书表格 cell id 不足：expected={expected} got={len(cell_ids)} table_id={table_id}")
            for row_index, row in enumerate(rows):
                for column_index in range(column_count):
                    text = row[column_index] if column_index < len(row) else ""
                    self._append_table_cell_text(document_id, cell_ids[row_index * column_count + column_index], text)
        except Exception:
            self._delete_document_children_from(document_id, start_index)
            raise

    @staticmethod
    def _find_created_table(payload: dict[str, Any]) -> dict[str, Any]:
        children = payload.get("data", {}).get("children") or payload.get("data", {}).get("items") or []
        for child in children:
            if isinstance(child, dict) and child.get("block_type") == 31:
                return child
        return {}

    @staticmethod
    def _extract_block_id(item: Any) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            return str(item.get("block_id") or item.get("id") or "")
        return ""

    def _extract_table_cell_ids(self, table_block: dict[str, Any], expected: int) -> list[str]:
        table = table_block.get("table") if isinstance(table_block, dict) else {}
        candidates: list[Any] = []
        if isinstance(table, dict):
            candidates.extend(table.get("cells") or [])
        candidates.extend(table_block.get("children") or [])
        ids: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            block_id = self._extract_block_id(item)
            if block_id and block_id not in seen:
                ids.append(block_id)
                seen.add(block_id)
        return ids[:expected] if len(ids) >= expected else ids

    def _get_docx_block(self, document_id: str, block_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/docx/v1/documents/{document_id}/blocks/{block_id}")
        return payload.get("data", {}).get("block") or payload.get("data", {})

    def _get_docx_children(self, document_id: str, block_id: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"/docx/v1/documents/{document_id}/blocks/{block_id}/children",
            params={"document_revision_id": -1},
        )
        return payload.get("data", {}).get("items") or payload.get("data", {}).get("children") or []

    def _append_table_cell_text(self, document_id: str, cell_id: str, text: str) -> None:
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        blocks = [self._text_block(line[:900]) for line in cleaned.splitlines() if line.strip()]
        if not blocks:
            return
        self._request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{cell_id}/children",
            json_body={"children": blocks, "index": -1},
            params={"document_revision_id": -1},
        )
        time.sleep(FEISHU_DOC_WRITE_SLEEP_SEC)

    def _list_document_child_blocks(self, document_id: str) -> list[dict]:
        items: list[dict] = []
        page_token = ""
        while True:
            params = {"document_revision_id": -1, "page_size": 500}
            if page_token:
                params["page_token"] = page_token
            data = self._request(
                "GET",
                f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                params=params,
            )
            payload = data.get("data", {}) if isinstance(data, dict) else {}
            batch = payload.get("items", []) if isinstance(payload, dict) else []
            if isinstance(batch, list):
                items.extend([item for item in batch if isinstance(item, dict)])
            if not payload.get("has_more"):
                break
            page_token = str(payload.get("page_token") or "")
            if not page_token:
                break
        return items

    def _clear_document(self, document_id: str) -> None:
        child_count = len(self._list_document_child_blocks(document_id))
        if child_count <= 0:
            return
        self._delete_document_child_range(document_id, 0, child_count)

    def _delete_document_children_from(self, document_id: str, start_index: int) -> None:
        child_count = len(self._list_document_child_blocks(document_id))
        if child_count <= start_index:
            return
        self._delete_document_child_range(document_id, start_index, child_count)

    def _delete_document_child_range(self, document_id: str, start_index: int, end_index: int) -> None:
        self._delete_docx_child_range(document_id, document_id, start_index, end_index)

    def _replace_document_content(self, document_id: str, content: str, *, expected_source_hash: str = "") -> None:
        self._verify_docx_source_hash(document_id, expected_source_hash)
        self._clear_document(document_id)
        self._append_to_document(document_id, content)

    def _replace_document_blocks(
        self,
        document_id: str,
        children: list[dict[str, Any]],
        *,
        expected_source_hash: str = "",
    ) -> None:
        self._verify_docx_source_hash(document_id, expected_source_hash)
        self._clear_document(document_id)
        self._append_blocks_to_document(document_id, children)

    def append_entry_blocks(self, doc_name: str, children: list[dict[str, Any]]) -> dict[str, str]:
        if self.mode == "knowledge_base":
            document_id, doc_url, space_id = self._get_or_create_knowledge_base_entry(doc_name)
            try:
                self._append_blocks_to_document(document_id, children)
            except Exception:
                self._doc_mapping.pop(doc_name, None)
                self._doc_mapping.pop(self._kb_map_key(doc_name, space_id), None)
                self._save_doc_mapping()
                document_id, doc_url, space_id = self._get_or_create_knowledge_base_entry(doc_name)
                self._append_blocks_to_document(document_id, children)
            return {
                "status": "synced",
                "doc": doc_url,
                "document_id": document_id,
                "mode": "knowledge_base",
                "space_id": space_id,
            }

        raise RuntimeError("append_entry_blocks requires knowledge_base mode")

    def append_child_entry_blocks(self, parent_doc_name: str, child_doc_name: str, children: list[dict[str, Any]]) -> dict[str, str]:
        if self.mode != "knowledge_base":
            raise RuntimeError("append_child_entry_blocks requires knowledge_base mode")

        document_id, doc_url, space_id = self._get_or_create_knowledge_base_child_entry(parent_doc_name, child_doc_name)
        try:
            self._append_blocks_to_document(document_id, children)
        except Exception:
            parent_mapping = self._doc_mapping.get(self._kb_map_key(parent_doc_name, space_id))
            parent_node_token = parent_mapping.get("node_token", "") if isinstance(parent_mapping, dict) else ""
            if parent_node_token:
                self._doc_mapping.pop(self._kb_child_map_key(parent_node_token, child_doc_name, space_id), None)
                self._save_doc_mapping()
            document_id, doc_url, space_id = self._get_or_create_knowledge_base_child_entry(parent_doc_name, child_doc_name)
            self._append_blocks_to_document(document_id, children)
        return {
            "status": "synced",
            "doc": doc_url,
            "document_id": document_id,
            "mode": "knowledge_base",
            "space_id": space_id,
            "parent_doc": parent_doc_name,
        }

    def append_entry(self, doc_name: str, content: str) -> dict[str, str]:
        if self.mode == "webhook":
            if self.app_id and self.app_secret:
                self._require_credentials()
                document_id, doc_url = self._get_or_create_document(doc_name)
                try:
                    self._append_to_document(document_id, content)
                except Exception:
                    self._doc_mapping.pop(doc_name, None)
                    self._save_doc_mapping()
                    document_id, doc_url = self._get_or_create_document(doc_name)
                    self._append_to_document(document_id, content)
                return {
                    "status": "synced",
                    "doc": doc_url,
                    "document_id": document_id,
                }
            if self.webhook_url:
                resp = requests.post(self.webhook_url, json={"msg_type": "text", "content": {"text": content}}, timeout=10)
                resp.raise_for_status()
                return {"status": "synced", "doc": doc_name}
            raise RuntimeError("webhook 模式未配置 app_id/app_secret 或 webhook_url")

        if self.mode == "knowledge_base":
            document_id, doc_url, space_id = self._get_or_create_knowledge_base_entry(doc_name)
            try:
                self._append_to_document(document_id, content)
            except Exception:
                self._doc_mapping.pop(doc_name, None)
                self._doc_mapping.pop(self._kb_map_key(doc_name, space_id), None)
                self._save_doc_mapping()
                document_id, doc_url, space_id = self._get_or_create_knowledge_base_entry(doc_name)
                self._append_to_document(document_id, content)
            return {
                "status": "synced",
                "doc": doc_url,
                "document_id": document_id,
                "mode": "knowledge_base",
                "space_id": space_id,
            }

        if self.mode in {"local", "local_markdown"}:
            target = self.local_docs_dir / f"{doc_name}.md"
            with target.open("a", encoding="utf-8") as fh:
                fh.write(content.rstrip() + "\n\n")
            return {"status": "synced", "doc": doc_name, "path": str(target)}

        raise RuntimeError(f"不支持的 feishu.mode: {self.mode}")

    def replace_entry(self, doc_name: str, content: str) -> dict[str, str]:
        if self.mode == "knowledge_base":
            document_id, doc_url, space_id = self._get_or_create_knowledge_base_entry(doc_name)
            self._replace_document_content(document_id, content)
            return {
                "status": "synced",
                "doc": doc_url,
                "document_id": document_id,
                "mode": "knowledge_base",
                "space_id": space_id,
            }

        if self.mode == "webhook" and self.app_id and self.app_secret:
            self._require_credentials()
            document_id, doc_url = self._get_or_create_document(doc_name)
            self._replace_document_content(document_id, content)
            return {"status": "synced", "doc": doc_url, "document_id": document_id}

        if self.mode in {"local", "local_markdown"}:
            target = self.local_docs_dir / f"{doc_name}.md"
            target.write_text(content.rstrip() + "\n", encoding="utf-8")
            return {"status": "synced", "doc": doc_name, "path": str(target)}

        raise RuntimeError(f"当前飞书模式不支持替换写入: {self.mode}")
