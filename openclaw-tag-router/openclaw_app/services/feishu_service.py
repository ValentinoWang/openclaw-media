from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from fnmatch import fnmatch
from typing import Any

import requests

from .utils import ensure_dir


DEFAULT_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
DEFAULT_FEISHU_DOC_BASE = "https://open.feishu.cn"
FEISHU_MAPPING_FILE = "doc_mapping.json"


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
        fallback_space_id: str,
        fallback_parent_node_token: str,
    ) -> list[dict[str, str]]:
        spaces: list[dict[str, str]] = []
        if isinstance(raw_spaces, list):
            for item in raw_spaces:
                if not isinstance(item, dict):
                    continue
                space_id = _env_or_value(str(item.get("space_id", ""))).strip()
                if not space_id:
                    continue
                parent_node_token = _env_or_value(str(item.get("parent_node_token", ""))).strip() or fallback_parent_node_token
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

        if fallback_space_id:
            spaces.append({"space_id": fallback_space_id, "parent_node_token": fallback_parent_node_token, "pattern": "*"})
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
        response = requests.request(method, url, json=json_body, params=params, headers=headers, timeout=20)
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}
        if response.status_code >= 400:
            raise RuntimeError(f"Feishu API request failed ({method} {path}) status={response.status_code}, body={data}")
        if isinstance(data, dict) and data.get("code") not in {None, 0}:
            raise RuntimeError(f"Feishu API returned code={data.get('code')}, msg={data.get('msg')}, path={path}")
        return data

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

    def replace_document_url(self, url: str, content: str) -> dict[str, str]:
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

        self._replace_document_content(document_id, content)
        return {"status": "synced", "doc": doc_url, "document_id": document_id}

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
        if not self.app_id or not self.app_secret:
            raise RuntimeError("飞书 API 配置缺少 app_id/app_secret")

        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        headers = {"Content-Type": "application/json; charset=utf-8"}
        response = requests.post(f"{self.api_base_url}/auth/v3/tenant_access_token/internal", json=payload, headers=headers, timeout=20)
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
        lines = [line.rstrip() for line in self._safe_text_content(content).split("\n") if line.strip()]
        if not lines:
            lines = [" "]
        children: list[dict[str, Any]] = []
        for line in lines:
            heading = re.match(r"^(#{1,9})\s+(.+)$", line.strip())
            if heading:
                level = len(heading.group(1))
                children.append(self._heading_block(level, heading.group(2).strip()))
                continue
            children.append(self._text_block(line.strip()))
        return children

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
                for index in range(0, len(children), 20):
                    self._request(
                        "POST",
                        f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children",
                        json_body={"children": children[index:index + 20]},
                        params={"document_revision_id": -1},
                    )
                return
            except RuntimeError as exc:
                last_error = exc

        raise RuntimeError(f"追加飞书文档内容失败: {last_error}") from None

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
        self._request(
            "DELETE",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
            json_body={"start_index": 0, "end_index": child_count},
            params={"document_revision_id": -1},
        )

    def _replace_document_content(self, document_id: str, content: str) -> None:
        self._clear_document(document_id)
        self._append_to_document(document_id, content)

    def _replace_document_blocks(self, document_id: str, children: list[dict[str, Any]]) -> None:
        self._clear_document(document_id)
        self._append_blocks_to_document(document_id, children)

    def append_entry_blocks(self, doc_name: str, children: list[dict[str, Any]], fallback_content: str = "") -> dict[str, str]:
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

        return self.append_entry(doc_name, fallback_content)

    def append_child_entry_blocks(self, parent_doc_name: str, child_doc_name: str, children: list[dict[str, Any]], fallback_content: str = "") -> dict[str, str]:
        if self.mode != "knowledge_base":
            return self.append_entry_blocks(child_doc_name, children, fallback_content)

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
