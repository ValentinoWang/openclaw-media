"""Append-only hydration for Lark resources discovered without bodies."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .media_business.foundation import body_checksum, validate_body


class LarkResourceHydrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class HydrationTarget:
    tenant_id: str
    public_artifact_id: str
    current_revision: int
    actor_public_id: str
    lark_resource: Mapping[str, Any]

    @property
    def node_token(self) -> str:
        return str(self.lark_resource.get("nodeToken") or "").strip()

    @property
    def obj_token(self) -> str:
        return str(self.lark_resource.get("objToken") or "").strip()

    @property
    def obj_type(self) -> str:
        return str(self.lark_resource.get("objType") or "").strip().lower()

    @property
    def title(self) -> str:
        return str(self.lark_resource.get("title") or self.public_artifact_id).strip()


@dataclass(frozen=True)
class HydrationPayload:
    body: dict[str, Any]
    mappings: tuple[tuple[str, str, str], ...]
    source_url: str


@dataclass(frozen=True)
class HydrationResult:
    targets: int
    inserted: int
    unchanged: int
    failed: int
    failures: tuple[dict[str, str], ...]


def _wiki_node_token(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    return parts[1] if len(parts) == 2 and parts[0] == "wiki" else ""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _text_block(block_id: str, text: str, heading: int | None = None) -> dict[str, Any]:
    return {"id": block_id, "type": f"heading_{heading}" if heading else "paragraph", "attrs": {}, "content": [{"type": "text", "text": text or "（空）", "marks": []}]}


def _flatten_docx_blocks(blocks: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    def visit(items: Any) -> None:
        for item in items if isinstance(items, list) else []:
            if isinstance(item, Mapping):
                result.append(dict(item))
                visit(item.get("children"))
    visit(blocks)
    return result


def _docx_payload(target: HydrationTarget, snapshot: Mapping[str, Any] | None, fallback_text: str) -> HydrationPayload:
    blocks = [_text_block(f"lark_{target.public_artifact_id}_title", target.title, heading=1)]
    mappings = [(blocks[0]["id"], f"docx:{target.obj_token}:root", _digest(blocks[0]))]
    used_remote = {mappings[0][1]}
    for index, remote in enumerate(_flatten_docx_blocks(snapshot.get("root_blocks") if snapshot else []), start=1):
        remote_id, text = str(remote.get("block_id") or "").strip(), str(remote.get("text") or "").strip()
        if not remote_id or not text or remote_id in used_remote:
            continue
        public_id = f"lark_{target.public_artifact_id}_{index}"
        block_type = remote.get("block_type")
        heading = int(block_type) - 2 if isinstance(block_type, int) and 3 <= block_type <= 11 else None
        block = _text_block(public_id, text, heading=heading)
        blocks.append(block)
        mappings.append((public_id, remote_id, _digest(block)))
        used_remote.add(remote_id)
        if len(blocks) >= 5000:
            break
    if len(blocks) == 1:
        for index, line in enumerate(str(fallback_text or "").splitlines(), start=1):
            if not (text := line.strip()):
                continue
            block = _text_block(f"lark_{target.public_artifact_id}_line_{index}", text)
            blocks.append(block)
            mappings.append((block["id"], f"docx:{target.obj_token}:line:{index}", _digest(block)))
            if len(blocks) >= 5000:
                break
    return HydrationPayload(validate_body({"schemaVersion": "media.document.body.v1", "blocks": blocks}), tuple(mappings), f"https://tcnwueberajc.feishu.cn/wiki/{target.node_token}")


def _bitable_payload(target: HydrationTarget, tables: list[Mapping[str, Any]]) -> HydrationPayload:
    blocks: list[dict[str, Any]] = []
    mappings: list[tuple[str, str, str]] = []
    def add(block: dict[str, Any], remote_id: str) -> None:
        blocks.append(block)
        mappings.append((block["id"], remote_id, _digest(block)))
    add(_text_block(f"lark_{target.public_artifact_id}_title", target.title, heading=1), f"bitable:{target.obj_token}:root")
    for table_index, table in enumerate(tables):
        table_id = str(table.get("table_id") or "").strip()
        if not table_id or len(blocks) >= 5000:
            continue
        add(_text_block(f"lark_{target.public_artifact_id}_table_{table_index}", str(table.get("name") or table_id), heading=2), f"bitable:{target.obj_token}:table:{table_id}")
        for row_index, row in enumerate(table.get("records") if isinstance(table.get("records"), list) else []):
            if len(blocks) >= 5000:
                break
            record = dict(row) if isinstance(row, Mapping) else {"value": row}
            record_id = str(record.get("record_id") or record.get("recordId") or row_index)
            block = _text_block(f"lark_{target.public_artifact_id}_{table_index}_{row_index}", json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            add(block, f"bitable:{target.obj_token}:table:{table_id}:record:{record_id}")
    return HydrationPayload(validate_body({"schemaVersion": "media.document.body.v1", "blocks": blocks}), tuple(mappings), f"https://tcnwueberajc.feishu.cn/wiki/{target.node_token}")


class LarkResourceHydrationRepository:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def targets(self, tenant_id: str, owner_public_id: str = "") -> list[HydrationTarget]:
        with self._connection_factory() as connection:
            rows = connection.execute("""SELECT a.tenant_id,a.public_id,a.current_revision,COALESCE(NULLIF(%s,''),r.actor_public_id),s.error_detail->'larkResource',a.docx_url
                FROM media_product.document_artifacts a JOIN media_product.lark_document_bindings b ON b.tenant_id=a.tenant_id AND b.public_artifact_id=a.public_id
                JOIN media_product.sync_batches s ON s.tenant_id=b.tenant_id AND s.public_sync_id=b.public_sync_id
                JOIN media_product.document_revisions r ON r.tenant_id=a.tenant_id AND r.public_artifact_id=a.public_id AND r.revision=a.current_revision
                WHERE a.tenant_id=%s AND a.body_authority='lark' ORDER BY a.public_id""", (owner_public_id.strip(), tenant_id.strip())).fetchall()
        targets = []
        for row in rows:
            metadata = json.loads(row[4]) if isinstance(row[4], str) else row[4]
            resource = dict(metadata) if isinstance(metadata, Mapping) else {}
            if not resource.get("nodeToken"):
                resource["nodeToken"] = _wiki_node_token(row[5])
            resource.setdefault("title", str(row[1]))
            target = HydrationTarget(str(row[0]), str(row[1]), int(row[2]), str(row[3]), resource)
            if target.node_token and (not target.obj_type or target.obj_type in {"doc", "docx", "bitable"}):
                targets.append(target)
        return targets

    def append_if_changed(self, target: HydrationTarget, payload: HydrationPayload) -> str:
        checksum = body_checksum(payload.body)
        with self._connection_factory() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"lark-resource-hydration:{target.tenant_id}:{target.public_artifact_id}",))
            artifact = connection.execute("SELECT current_revision FROM media_product.document_artifacts WHERE tenant_id=%s AND public_id=%s FOR UPDATE", (target.tenant_id, target.public_artifact_id)).fetchone()
            if artifact is None:
                raise LarkResourceHydrationError("Lark artifact disappeared during hydration")
            current_revision = int(artifact[0])
            previous = connection.execute("SELECT body_checksum FROM media_document.lark_read_mirrors WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s", (target.tenant_id, target.public_artifact_id, current_revision)).fetchone()
            if previous is not None and str(previous[0]) == checksum:
                return "unchanged"
            revision = current_revision + 1
            sync_id = "sync_lark_hydrate_" + hashlib.sha256(f"{target.tenant_id}:{target.public_artifact_id}:{checksum}".encode()).hexdigest()[:40]
            connection.execute("INSERT INTO media_product.document_revisions (tenant_id,public_artifact_id,revision,state,base_revision,body_checksum,actor_public_id,generation_source) VALUES (%s,%s,%s,'ready',%s,%s,%s,'lark_resource_hydration')", (target.tenant_id, target.public_artifact_id, revision, current_revision, checksum, target.actor_public_id))
            connection.execute("INSERT INTO media_document.lark_read_mirrors (tenant_id,public_artifact_id,revision,body_json,body_checksum,source_url) VALUES (%s,%s,%s,%s::jsonb,%s,%s)", (target.tenant_id, target.public_artifact_id, revision, json.dumps(payload.body, ensure_ascii=False), checksum, payload.source_url))
            connection.execute("UPDATE media_product.document_artifacts SET current_revision=%s,docx_url=%s,updated_at=now() WHERE tenant_id=%s AND public_id=%s", (revision, payload.source_url, target.tenant_id, target.public_artifact_id))
            detail = {"larkResource": dict(target.lark_resource), "hydrated": True}
            connection.execute("""INSERT INTO media_product.sync_batches (tenant_id,public_sync_id,state,public_artifact_id,revision,operation,remote_document_version,body_checksum,block_count,protected_block_count,completed_at,error_detail)
                VALUES (%s,%s,'running',%s,%s,'read',%s,%s,%s,0,NULL,%s::jsonb)""", (target.tenant_id, sync_id, target.public_artifact_id, revision, checksum, checksum, len(payload.mappings), json.dumps(detail, ensure_ascii=False)))
            for public_id, remote_id, block_hash in payload.mappings:
                connection.execute("INSERT INTO media_product.lark_document_block_mappings (tenant_id,public_sync_id,public_block_id,remote_block_id,block_checksum,is_protected,protection_reason) VALUES (%s,%s,%s,%s,%s,false,NULL)", (target.tenant_id, sync_id, public_id, remote_id, block_hash))
            connection.execute("UPDATE media_product.sync_batches SET state='succeeded',completed_at=now() WHERE tenant_id=%s AND public_sync_id=%s AND state='running'", (target.tenant_id, sync_id))
            connection.execute("INSERT INTO media_product.lark_document_bindings (tenant_id,public_artifact_id,public_sync_id) VALUES (%s,%s,%s) ON CONFLICT (tenant_id,public_artifact_id) DO UPDATE SET public_sync_id=EXCLUDED.public_sync_id,updated_at=now()", (target.tenant_id, target.public_artifact_id, sync_id))
            connection.commit()
        return "inserted"


class LarkResourceHydrationService:
    def __init__(self, feishu_service: Any, repository: LarkResourceHydrationRepository) -> None:
        self._feishu, self._repository = feishu_service, repository

    def _bitable_tables(self, target: HydrationTarget) -> list[dict[str, Any]]:
        tables, page_token = [], ""
        while True:
            params = {"page_size": 100, **({"page_token": page_token} if page_token else {})}
            response = self._feishu._request("GET", f"/bitable/v1/apps/{target.obj_token}/tables", params=params)
            data = response.get("data", {}) if isinstance(response, Mapping) else {}
            for item in data.get("items", []) if isinstance(data, Mapping) and isinstance(data.get("items", []), list) else []:
                table_id = str(item.get("table_id") or "").strip() if isinstance(item, Mapping) else ""
                if table_id:
                    tables.append({"table_id": table_id, "name": item.get("name"), "records": self._feishu.list_bitable_records(target.obj_token, table_id, page_size=500)})
            if not isinstance(data, Mapping) or not data.get("has_more"):
                return tables
            next_token = str(data.get("page_token") or "").strip()
            if not next_token or next_token == page_token:
                raise LarkResourceHydrationError("Lark Bitable table pagination did not advance")
            page_token = next_token

    def _payload(self, target: HydrationTarget) -> HydrationPayload:
        if target.obj_type == "bitable":
            return _bitable_payload(target, self._bitable_tables(target))
        tree = self._feishu.hydrate_docx_child_tree(target.obj_token)
        if not isinstance(tree, list):
            raise LarkResourceHydrationError("Lark document child hydration returned invalid blocks")
        return _docx_payload(target, {"root_blocks": tree}, "")

    def _resolved_target(self, target: HydrationTarget) -> HydrationTarget:
        if target.obj_token and target.obj_type:
            return target
        metadata = self._feishu.resolve_wiki_node_metadata(target.node_token)
        resource = {
            "nodeToken": metadata["node_token"],
            "objToken": metadata["obj_token"],
            "objType": metadata["obj_type"],
            "title": metadata.get("title") or target.title,
            "spaceId": metadata["space_id"],
            "parentNodeToken": metadata.get("parent_node_token") or "",
        }
        return HydrationTarget(
            target.tenant_id,
            target.public_artifact_id,
            target.current_revision,
            target.actor_public_id,
            resource,
        )

    def hydrate(self, tenant_id: str, owner_public_id: str = "") -> HydrationResult:
        targets, failures, counts = self._repository.targets(tenant_id, owner_public_id), [], {"inserted": 0, "unchanged": 0}
        for target in targets:
            try:
                resolved = self._resolved_target(target)
                counts[self._repository.append_if_changed(resolved, self._payload(resolved))] += 1
            except Exception as exc:
                failures.append({"publicArtifactId": target.public_artifact_id, "title": target.title, "error": str(exc)})
        return HydrationResult(len(targets), counts["inserted"], counts["unchanged"], len(failures), tuple(failures))
