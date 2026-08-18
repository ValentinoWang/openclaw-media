"""Retired compatibility helpers for the former Lark projection path.

Production discovery and body hydration use ``lark_resource_sync`` and
``lark_resource_hydration``.  This module keeps the pure discovery/body helpers
needed by older isolated tests, but deliberately contains no database store.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from .foundation import body_checksum

SUPPORTED_TYPES = frozenset({"doc", "docx", "bitable"})


@dataclass(frozen=True)
class LarkResource:
    obj_type: str
    obj_token: str
    node_token: str
    title: str
    space_id: str
    parent_node_token: str


@dataclass(frozen=True)
class ProjectionItem:
    resource: LarkResource
    public_project_id: str
    public_artifact_id: str
    public_sync_id: str
    revision: int
    body_checksum: str
    changed: bool


class LarkService(Protocol):
    def _request(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> dict: ...
    def _wiki_url(self, node_token: str) -> str: ...
    def read_document_text(self, url: str) -> dict[str, Any]: ...
    def list_bitable_records(self, app_token: str, table_id: str, *, page_size: int = 500, filter_formula: str = "") -> list[dict[str, Any]]: ...


class LarkProjectionStore(Protocol):
    def upsert_resource(self, resource: LarkResource, source_url: str, body: dict[str, Any], checksum: str) -> ProjectionItem: ...


def stable_resource_ids(tenant_id: str, resource: LarkResource) -> tuple[str, str, str]:
    identity = f"{tenant_id}:{resource.obj_type}:{resource.obj_token}".encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:48]
    return f"lark_project_{digest}", f"lark_artifact_{digest}", f"lark_sync_{digest}"


def _text_block(block_id: str, text: str, heading: int | None = None) -> dict[str, Any]:
    return {
        "id": block_id,
        "type": f"heading_{heading}" if heading else "paragraph",
        "attrs": {},
        "content": [{"type": "text", "text": text or "（空）", "marks": []}],
    }


def document_body(resource: LarkResource, text: str) -> dict[str, Any]:
    blocks = [_text_block(f"lark_{resource.obj_token}_title", resource.title, heading=1)]
    for index, line in enumerate(str(text or "").splitlines()[:4999], start=1):
        if line.strip():
            blocks.append(_text_block(f"lark_{resource.obj_token}_{index}", line.strip()))
    return {"schemaVersion": "media.document.body.v1", "blocks": blocks}


def bitable_body(resource: LarkResource, tables: list[dict[str, Any]]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [_text_block(f"lark_{resource.obj_token}_title", resource.title, heading=1)]
    for table_index, table in enumerate(tables):
        table_name = str(table.get("name") or table.get("table_name") or table.get("table_id") or "数据表")
        blocks.append(_text_block(f"lark_{resource.obj_token}_table_{table_index}", table_name, heading=2))
        rows = table.get("records") if isinstance(table.get("records"), list) else []
        for row_index, row in enumerate(rows[:1000], start=1):
            payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            blocks.append(_text_block(f"lark_{resource.obj_token}_{table_index}_{row_index}", payload))
            if len(blocks) >= 5000:
                break
        if len(blocks) >= 5000:
            break
    return {"schemaVersion": "media.document.body.v1", "blocks": blocks}


class FeishuResourceSynchronizer:
    def __init__(self, feishu_service: LarkService, store: LarkProjectionStore, *, tenant_id: str, parent_node_token: str) -> None:
        self.feishu_service = feishu_service
        self.store = store
        self.tenant_id = tenant_id.strip()
        self.parent_node_token = parent_node_token.strip()
        if not self.tenant_id or not self.parent_node_token:
            raise ValueError("tenant_id and parent_node_token are required")

    def discover(self) -> list[LarkResource]:
        root = self.feishu_service._request("GET", "/wiki/v2/spaces/get_node", params={"token": self.parent_node_token})
        node = root.get("data", {}).get("node", {}) if isinstance(root, dict) else {}
        space_id = str(node.get("space_id") or "").strip()
        if not space_id:
            raise RuntimeError("Lark parent node did not return space_id")
        resources: list[LarkResource] = []
        seen_nodes: set[str] = set()
        pending = [self.parent_node_token]
        while pending:
            parent = pending.pop()
            if parent in seen_nodes:
                continue
            seen_nodes.add(parent)
            page_token = ""
            while True:
                params: dict[str, Any] = {"parent_node_token": parent, "page_size": 50}
                if page_token:
                    params["page_token"] = page_token
                payload = self.feishu_service._request("GET", f"/wiki/v2/spaces/{space_id}/nodes", params=params)
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                items = data.get("items", []) if isinstance(data, dict) else []
                for item in items if isinstance(items, list) else []:
                    if not isinstance(item, dict):
                        continue
                    node_token = str(item.get("node_token") or "").strip()
                    obj_token = str(item.get("obj_token") or "").strip()
                    obj_type = str(item.get("obj_type") or "").strip().lower()
                    title = str(item.get("title") or "").strip()
                    if node_token:
                        pending.append(node_token)
                    if obj_type in SUPPORTED_TYPES and node_token and obj_token and title:
                        resources.append(LarkResource(obj_type, obj_token, node_token, title, space_id, parent))
                if not isinstance(data, dict) or not data.get("has_more"):
                    break
                next_token = str(data.get("page_token") or "").strip()
                if not next_token or next_token == page_token:
                    raise RuntimeError("Lark node pagination did not advance")
                page_token = next_token
        unique: dict[tuple[str, str], LarkResource] = {}
        for resource in resources:
            unique.setdefault((resource.obj_type, resource.obj_token), resource)
        return sorted(unique.values(), key=lambda item: (item.title, item.obj_type, item.obj_token))

    def _body(self, resource: LarkResource, source_url: str) -> dict[str, Any]:
        if resource.obj_type in {"doc", "docx"}:
            result = self.feishu_service.read_document_text(source_url)
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "Lark document read failed"))
            return document_body(resource, str(result.get("text") or ""))
        tables: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            payload = self.feishu_service._request("GET", f"/bitable/v1/apps/{resource.obj_token}/tables", params=params)
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            items = data.get("items", []) if isinstance(data, dict) else []
            for table in items if isinstance(items, list) else []:
                if not isinstance(table, dict):
                    continue
                table_id = str(table.get("table_id") or "").strip()
                if table_id:
                    tables.append({"table_id": table_id, "name": table.get("name"), "records": self.feishu_service.list_bitable_records(resource.obj_token, table_id, page_size=500)})
            if not isinstance(data, dict) or not data.get("has_more"):
                break
            next_token = str(data.get("page_token") or "").strip()
            if not next_token or next_token == page_token:
                raise RuntimeError("Lark table pagination did not advance")
            page_token = next_token
        return bitable_body(resource, tables)

    def sync(self, *, execute: bool) -> dict[str, Any]:
        resources = self.discover()
        items: list[ProjectionItem] = []
        failures: list[dict[str, str]] = []
        for resource in resources:
            source_url = self.feishu_service._wiki_url(resource.node_token)
            try:
                body = self._body(resource, source_url)
                checksum = body_checksum(body)
                project_id, artifact_id, sync_id = stable_resource_ids(self.tenant_id, resource)
                item = self.store.upsert_resource(resource, source_url, body, checksum) if execute else ProjectionItem(resource, project_id, artifact_id, sync_id, 0, checksum, True)
                items.append(item)
            except Exception as exc:
                failures.append({"title": resource.title, "objType": resource.obj_type, "error": str(exc)})
        return {"tenantId": self.tenant_id, "parentNode": self.parent_node_token, "discovered": len(resources), "projected": len(items), "failed": failures, "items": [{"title": item.resource.title, "objType": item.resource.obj_type, "publicProjectId": item.public_project_id, "publicArtifactId": item.public_artifact_id, "revision": item.revision, "changed": item.changed} for item in items]}

