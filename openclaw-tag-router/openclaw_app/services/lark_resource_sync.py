"""Tenant-scoped, idempotent discovery of Media OS resources in Lark.

The repository intentionally uses only the canonical PostgreSQL media tables.
External identity is retained in ``sync_batches.error_detail``; it is metadata
about the Lark resource, never a second content authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


SUPPORTED_OBJECT_TYPES = frozenset({"docx", "bitable", "sheet"})
PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,160}$")


class LarkResourceSyncError(RuntimeError):
    """Raised when the discovery response or canonical write is invalid."""


@dataclass(frozen=True)
class LarkResource:
    node_token: str
    obj_token: str
    obj_type: str
    title: str
    space_id: str
    parent_node_token: str
    has_child: bool = False

    @property
    def fingerprint(self) -> str:
        payload = {
            "nodeToken": self.node_token,
            "objToken": self.obj_token,
            "objType": self.obj_type,
            "title": self.title,
            "spaceId": self.space_id,
            "parentNodeToken": self.parent_node_token,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SyncResult:
    discovered: int
    inserted: int
    updated: int
    unchanged: int


def _value(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _node(raw: Mapping[str, Any], *, fallback_space: str = "", fallback_parent: str = "") -> LarkResource | None:
    node_token = str(_value(raw, "node_token", "nodeToken", "token") or "").strip()
    obj_token = str(_value(raw, "obj_token", "objToken", "obj_token_id") or "").strip()
    obj_type = str(_value(raw, "obj_type", "objType", "object_type") or "").strip().lower()
    title = str(_value(raw, "title", "name") or "").strip()
    space_id = str(_value(raw, "space_id", "spaceId") or fallback_space).strip()
    parent = str(_value(raw, "parent_node_token", "parentNodeToken") or fallback_parent).strip()
    if not node_token or not obj_token or obj_type not in SUPPORTED_OBJECT_TYPES or not space_id:
        return None
    return LarkResource(
        node_token=node_token,
        obj_token=obj_token,
        obj_type=obj_type,
        title=title or node_token,
        space_id=space_id,
        parent_node_token=parent,
        has_child=_as_bool(_value(raw, "has_child", "hasChild", "has_children")),
    )


class LarkResourceDiscoverer:
    """Parse a wiki node and recursively enumerate its child nodes."""

    def __init__(self, feishu_service: Any) -> None:
        self._service = feishu_service
        request = getattr(feishu_service, "_request", None)
        if not callable(request):
            raise TypeError("FeishuService request helper is required")
        self._request = request

    def resolve_wiki_node(self, node_token: str) -> dict[str, Any]:
        resolver = getattr(self._service, "resolve_wiki_node_metadata", None)
        if callable(resolver):
            value = resolver(node_token)
            if isinstance(value, Mapping):
                return {
                    "nodeToken": str(value.get("node_token") or value.get("nodeToken") or "").strip(),
                    "objToken": str(value.get("obj_token") or value.get("objToken") or "").strip(),
                    "objType": str(value.get("obj_type") or value.get("objType") or "").strip().lower(),
                    "title": str(value.get("title") or "").strip(),
                    "spaceId": str(value.get("space_id") or value.get("spaceId") or "").strip(),
                    "parentNodeToken": str(value.get("parent_node_token") or value.get("parentNodeToken") or "").strip(),
                    "hasChild": _as_bool(value.get("has_child") if "has_child" in value else value.get("hasChild")),
                }
        token = str(node_token or "").strip()
        if not token:
            raise LarkResourceSyncError("wiki node token is required")
        payload = self._request("GET", "/wiki/v2/spaces/get_node", params={"token": token})
        data = payload.get("data", {}) if isinstance(payload, Mapping) else {}
        raw = data.get("node", {}) if isinstance(data, Mapping) else {}
        if not isinstance(raw, Mapping):
            raw = data if isinstance(data, Mapping) else {}
        resource = _node(raw, fallback_parent="")
        if resource is None:
            raise LarkResourceSyncError("wiki node has incomplete or unsupported identity")
        return {
            "nodeToken": resource.node_token,
            "objToken": resource.obj_token,
            "objType": resource.obj_type,
            "title": resource.title,
            "spaceId": resource.space_id,
            "parentNodeToken": resource.parent_node_token,
            "hasChild": resource.has_child,
        }

    def enumerate_children(self, space_id: str, parent_node_token: str) -> list[LarkResource]:
        lister = getattr(self._service, "list_knowledge_resource_nodes", None)
        if callable(lister):
            items = lister(parent_node_token)
            if not isinstance(items, list):
                raise LarkResourceSyncError("wiki child inventory is invalid")
            resources: list[LarkResource] = []
            for item in items:
                if isinstance(item, Mapping):
                    resource = _node(item, fallback_space=space_id, fallback_parent=parent_node_token)
                    if resource is not None:
                        resources.append(resource)
            return resources
        space = str(space_id or "").strip()
        parent = str(parent_node_token or "").strip()
        if not space or not parent:
            raise LarkResourceSyncError("wiki space and parent node are required")
        discovered: list[LarkResource] = []
        queue = [parent]
        seen: set[str] = set()
        while queue:
            current_parent = queue.pop(0)
            if current_parent in seen:
                continue
            seen.add(current_parent)
            page_token = ""
            while True:
                params: dict[str, Any] = {"parent_node_token": current_parent, "page_size": 50}
                if page_token:
                    params["page_token"] = page_token
                payload = self._request("GET", f"/wiki/v2/spaces/{space}/nodes", params=params)
                data = payload.get("data", {}) if isinstance(payload, Mapping) else {}
                items = data.get("items", []) if isinstance(data, Mapping) else []
                if not isinstance(items, list):
                    raise LarkResourceSyncError("wiki child inventory is invalid")
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    child = _node(item, fallback_space=space, fallback_parent=current_parent)
                    # Unknown container nodes remain traversal points, while
                    # only supported Media OS object types become resources.
                    child_token = str(_value(item, "node_token", "nodeToken", "token") or "").strip()
                    child_has_child = _as_bool(_value(item, "has_child", "hasChild", "has_children"))
                    if child is not None:
                        discovered.append(child)
                    if child_token and child_has_child and child_token not in seen:
                        queue.append(child_token)
                has_more = bool(data.get("has_more") or data.get("hasMore")) if isinstance(data, Mapping) else False
                next_token = str(data.get("page_token") or data.get("pageToken") or "").strip() if isinstance(data, Mapping) else ""
                if not has_more or not next_token or next_token == page_token:
                    break
                page_token = next_token
        unique: dict[str, LarkResource] = {}
        for item in discovered:
            unique.setdefault(item.node_token, item)
        return list(unique.values())

    def discover(self, root_node_token: str) -> tuple[dict[str, Any], list[LarkResource]]:
        root = self.resolve_wiki_node(root_node_token)
        return root, self.enumerate_children(root["spaceId"], root["nodeToken"])


def _safe_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:40]
    result = f"{prefix}_{digest}"
    if not PUBLIC_ID_RE.fullmatch(result):
        raise LarkResourceSyncError("generated public identity is invalid")
    return result


class LarkResourceSyncRepository:
    """Canonical PostgreSQL upserts for a discovered tenant resource."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def sync(
        self,
        tenant_id: str,
        owner_public_id: str,
        root: Mapping[str, Any],
        resources: list[LarkResource],
    ) -> SyncResult:
        if not tenant_id.strip() or not owner_public_id.strip():
            raise LarkResourceSyncError("tenant and owner are required")
        project_id = _safe_id("project_lark", f"{tenant_id}:{root['nodeToken']}")
        root_fingerprint = hashlib.sha256(
            json.dumps(
                {"root": dict(root), "resources": [item.fingerprint for item in resources]},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        counts = {"inserted": 0, "updated": 0, "unchanged": 0}
        with self._connection_factory() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"lark-resource-sync:{tenant_id}:{root['nodeToken']}",),
            )
            project = connection.execute(
                "SELECT revision, canonical_data FROM media_product.content_projects WHERE tenant_id=%s AND public_id=%s FOR UPDATE",
                (tenant_id, project_id),
            ).fetchone()
            project_data = {
                "workspaceMode": "organization_lark",
                "source": "lark_wiki_discovery",
                "root": dict(root),
                "resourceCount": len(resources),
                "fingerprint": root_fingerprint,
            }
            if project is None:
                project_revision = 1
                connection.execute(
                    """INSERT INTO media_product.content_projects
                       (tenant_id, public_id, title, stage, revision, canonical_data)
                       VALUES (%s,%s,%s,'creation',%s,%s::jsonb)""",
                    (tenant_id, project_id, str(root.get("title") or "Media OS Lark"), project_revision, json.dumps(project_data, ensure_ascii=False)),
                )
            else:
                prior_data = project[1]
                if isinstance(prior_data, str):
                    prior_data = json.loads(prior_data)
                prior_fingerprint = prior_data.get("fingerprint") if isinstance(prior_data, Mapping) else None
                project_revision = int(project[0])
                if prior_fingerprint != root_fingerprint:
                    project_revision += 1
                    connection.execute(
                        """UPDATE media_product.content_projects
                           SET title=%s, stage='creation', revision=%s, canonical_data=%s::jsonb, updated_at=now()
                           WHERE tenant_id=%s AND public_id=%s""",
                        (str(root.get("title") or "Media OS Lark"), project_revision, json.dumps(project_data, ensure_ascii=False), tenant_id, project_id),
                    )
            for resource in resources:
                self._sync_resource(connection, tenant_id, owner_public_id, project_id, resource, counts)
            connection.commit()
        return SyncResult(len(resources), counts["inserted"], counts["updated"], counts["unchanged"])

    @staticmethod
    def _sync_resource(connection: Any, tenant_id: str, owner_public_id: str, project_id: str, resource: LarkResource, counts: dict[str, int]) -> None:
        artifact_id = _safe_id("artifact_lark", f"{tenant_id}:{resource.node_token}")
        artifact_kind = {"docx": "creation_document", "bitable": "asset_digest", "sheet": "research_snapshot"}[resource.obj_type]
        metadata = {
            "nodeToken": resource.node_token,
            "objToken": resource.obj_token,
            "objType": resource.obj_type,
            "title": resource.title,
            "spaceId": resource.space_id,
            "parentNodeToken": resource.parent_node_token,
            "source": "lark_wiki_discovery",
        }
        checksum = resource.fingerprint
        artifact = connection.execute(
            "SELECT current_revision FROM media_product.document_artifacts WHERE tenant_id=%s AND public_id=%s FOR UPDATE",
            (tenant_id, artifact_id),
        ).fetchone()
        if artifact is None:
            revision = 1
            connection.execute(
                """INSERT INTO media_product.document_artifacts
                   (tenant_id, public_id, public_project_id, artifact_kind, workspace_mode, body_authority, current_revision)
                   VALUES (%s,%s,%s,%s,'organization_lark','lark',%s)""",
                (tenant_id, artifact_id, project_id, artifact_kind, revision),
            )
            connection.execute(
                """INSERT INTO media_product.document_revisions
                   (tenant_id, public_artifact_id, revision, state, base_revision, body_checksum, actor_public_id, generation_source)
                   VALUES (%s,%s,%s,'ready',NULL,%s,%s,'lark_resource_discovery')""",
                (tenant_id, artifact_id, revision, checksum, owner_public_id),
            )
            status = "inserted"
        else:
            revision = int(artifact[0])
            prior = connection.execute(
                "SELECT body_checksum FROM media_product.document_revisions WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s",
                (tenant_id, artifact_id, revision),
            ).fetchone()
            if prior and str(prior[0]) == checksum:
                counts["unchanged"] += 1
                return
            revision += 1
            connection.execute(
                """INSERT INTO media_product.document_revisions
                   (tenant_id, public_artifact_id, revision, state, base_revision, body_checksum, actor_public_id, generation_source)
                   VALUES (%s,%s,%s,'ready',%s,%s,%s,'lark_resource_discovery')""",
                (tenant_id, artifact_id, revision, revision - 1, checksum, owner_public_id),
            )
            connection.execute(
                "UPDATE media_product.document_artifacts SET current_revision=%s, updated_at=now() WHERE tenant_id=%s AND public_id=%s",
                (revision, tenant_id, artifact_id),
            )
            status = "updated"
        sync_id = _safe_id("sync_lark", f"{tenant_id}:{resource.node_token}:{checksum}")
        connection.execute(
            """INSERT INTO media_product.sync_batches
               (tenant_id, public_sync_id, state, public_artifact_id, revision, operation,
                remote_document_version, body_checksum, block_count, protected_block_count,
                completed_at, error_detail)
               VALUES (%s,%s,'succeeded',%s,%s,'read',%s,%s,0,0,now(),%s::jsonb)
               ON CONFLICT (tenant_id, public_sync_id) DO NOTHING""",
            (tenant_id, sync_id, artifact_id, revision, f"discovery:{checksum}", checksum, json.dumps({"larkResource": metadata}, ensure_ascii=False)),
        )
        connection.execute(
            """INSERT INTO media_product.lark_document_bindings (tenant_id, public_artifact_id, public_sync_id)
               VALUES (%s,%s,%s)
               ON CONFLICT (tenant_id, public_artifact_id) DO UPDATE
                  SET public_sync_id=EXCLUDED.public_sync_id, updated_at=now()""",
            (tenant_id, artifact_id, sync_id),
        )
        counts[status] += 1


class LarkResourceSyncService:
    def __init__(self, feishu_service: Any, repository: LarkResourceSyncRepository) -> None:
        self._discoverer = LarkResourceDiscoverer(feishu_service)
        self._repository = repository

    def discover_and_sync(self, tenant_id: str, owner_public_id: str, root_node_token: str) -> SyncResult:
        root, resources = self._discoverer.discover(root_node_token)
        return self._repository.sync(tenant_id, owner_public_id, root, resources)
