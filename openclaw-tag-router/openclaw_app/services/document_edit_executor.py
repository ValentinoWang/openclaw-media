"""Small, idempotent consumer for web-created ``generating`` revisions.

The executor deliberately owns orchestration only.  Revision persistence and the
Lark writer are injected so the same contract is usable by the web worker and by
isolated tests; Lark writes must go through the injected DocumentsService writer.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Mapping
from typing import Any, Callable, Protocol

from .document_edit_contract import (
    DocumentEditPatchPlan,
    DocumentEditWorkingCopy,
)
from .media_business.foundation import body_checksum


class RevisionStore(Protocol):
    def claim_generating_revision(self, context: Any, artifact_id: str, revision: int) -> Mapping[str, Any] | None: ...
    def complete_revision(self, context: Any, artifact_id: str, revision: int, body: Mapping[str, Any], receipt: Mapping[str, Any]) -> Any: ...
    def fail_revision(self, context: Any, artifact_id: str, revision: int, error_code: str, message: str) -> Any: ...


class PostgresDocumentRevisionStore:
    """Minimal PostgreSQL adapter used by the process-local web worker."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _operation(artifact_id: str, revision: int) -> str:
        return f"documentEdit:{artifact_id}:{revision}"

    @staticmethod
    def _fingerprint(artifact_id: str, revision: int) -> bytes:
        import hashlib
        return hashlib.sha256(f"{artifact_id}:{revision}".encode("utf-8")).digest()

    def claim_generating_revision(self, context: Any, artifact_id: str, revision: int) -> Mapping[str, Any] | None:
        with self._connection_factory() as connection:
            owner = uuid.uuid4()
            fingerprint = self._fingerprint(artifact_id, revision)
            connection.execute(
                """INSERT INTO openclaw_account.if2_idempotency_receipts
                   (scope_kind,scope_id,operation_id,idempotency_key,path_fingerprint,request_fingerprint,state,lease_owner,lease_expires_at)
                   VALUES ('tenant',%s,%s,%s,%s,%s,'reserved',%s,now()+interval '10 minutes')
                   ON CONFLICT (scope_kind,scope_id,operation_id,idempotency_key) DO UPDATE
                     SET lease_owner=EXCLUDED.lease_owner, lease_expires_at=EXCLUDED.lease_expires_at
                   WHERE openclaw_account.if2_idempotency_receipts.state='reserved'
                     AND openclaw_account.if2_idempotency_receipts.lease_expires_at < now()""",
                (context.tenant_id, self._operation(artifact_id, revision), f"revision-{revision}", fingerprint, fingerprint, owner),
            )
            receipt = connection.execute(
                """SELECT state, lease_owner FROM openclaw_account.if2_idempotency_receipts
                   WHERE scope_kind='tenant' AND scope_id=%s AND operation_id=%s AND idempotency_key=%s""",
                (context.tenant_id, self._operation(artifact_id, revision), f"revision-{revision}"),
            ).fetchone()
            if receipt is None or receipt[0] != "reserved" or str(receipt[1]) != str(owner):
                return None
            row = connection.execute(
                """SELECT a.body_authority, r.base_revision FROM media_product.document_artifacts a
                   JOIN media_product.document_revisions r ON r.tenant_id=a.tenant_id
                    AND r.public_artifact_id=a.public_id AND r.revision=%s
                  WHERE a.tenant_id=%s AND a.public_id=%s AND r.state='generating'""",
                (revision, context.tenant_id, artifact_id),
            ).fetchone()
            if row is None:
                return None
            commit = getattr(connection, "commit", None)
            if callable(commit):
                commit()
            return {"bodyAuthority": row[0], "baseRevision": row[1], "documentId": artifact_id}

    def complete_revision(self, context: Any, artifact_id: str, revision: int, body: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
        import json
        with self._connection_factory() as connection:
            checksum = str(receipt["bodyChecksum"])
            connection.execute(
                """INSERT INTO media_document.revision_bodies
                   (tenant_id,public_artifact_id,revision,schema_version,body_json,body_checksum)
                   VALUES (%s,%s,%s,'media.document.body.v1',%s::jsonb,%s)
                   ON CONFLICT (tenant_id,public_artifact_id,revision) DO NOTHING""",
                (context.tenant_id, artifact_id, revision, json.dumps(body, ensure_ascii=False), checksum),
            )
            connection.execute(
                """UPDATE media_product.document_revisions SET state='ready', body_checksum=%s, updated_at=now()
                   WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s AND state='generating'""",
                (checksum, context.tenant_id, artifact_id, revision),
            )
            connection.execute(
                """UPDATE openclaw_account.if2_idempotency_receipts SET state='completed', response_status=200,
                      response_json=%s::jsonb, completed_at=now(), lease_owner=NULL, lease_expires_at=NULL
                   WHERE scope_kind='tenant' AND scope_id=%s AND operation_id=%s AND idempotency_key=%s AND state='reserved'""",
                (json.dumps(dict(receipt), ensure_ascii=False), context.tenant_id, self._operation(artifact_id, revision), f"revision-{revision}"),
            )
            commit = getattr(connection, "commit", None)
            if callable(commit):
                commit()

    def fail_revision(self, context: Any, artifact_id: str, revision: int, error_code: str, message: str) -> None:
        with self._connection_factory() as connection:
            connection.execute(
                """UPDATE media_product.document_revisions SET state='failed', updated_at=now()
                   WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s AND state='generating'""",
                (context.tenant_id, artifact_id, revision),
            )
            receipt = {"ok": False, "status": "failed", "revision": revision, "errorCode": error_code, "errorMessage": message}
            connection.execute(
                """UPDATE openclaw_account.if2_idempotency_receipts SET state='failed', response_status=500,
                      response_json=%s::jsonb, completed_at=now(), lease_owner=NULL, lease_expires_at=NULL
                   WHERE scope_kind='tenant' AND scope_id=%s AND operation_id=%s AND idempotency_key=%s AND state='reserved'""",
                (json.dumps(receipt, ensure_ascii=False), context.tenant_id, self._operation(artifact_id, revision), f"revision-{revision}"),
            )
            commit = getattr(connection, "commit", None)
            if callable(commit):
                commit()

    def get_revision_receipt(self, context: Any, artifact_id: str, revision: int) -> Mapping[str, Any] | None:
        with self._connection_factory() as connection:
            row = connection.execute(
                """SELECT response_json FROM openclaw_account.if2_idempotency_receipts
                   WHERE scope_kind='tenant' AND scope_id=%s AND operation_id=%s AND idempotency_key=%s
                     AND state IN ('completed','failed')""",
                (context.tenant_id, self._operation(artifact_id, revision), f"revision-{revision}"),
            ).fetchone()
        if row is None:
            return None
        payload = row[0]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return None
        return dict(payload) if isinstance(payload, Mapping) else None


class DocumentEditExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DocumentEditExecutor:
    """Consume one generating revision and return a stable public receipt.

    ``generator`` receives the instruction and source working copy and returns an
    intent payload (normally ``{"intent_operations": [...]}``) or a patch plan.
    A store claim is required before any write, making retries safe after a crash.
    """

    def __init__(self, revision_store: RevisionStore, document_service: Any, *, generator: Callable[..., Mapping[str, Any]] | None = None) -> None:
        self._store = revision_store
        self._documents = document_service
        self._generator = generator
        self._lock = threading.RLock()
        self._receipts: dict[tuple[str, str, int], dict[str, Any]] = {}

    def execute(self, context: Any, artifact_id: str, revision: int, instruction: Any = None) -> dict[str, Any]:
        tenant = str(getattr(context, "tenant_id", ""))
        key = (tenant, artifact_id, int(revision))
        with self._lock:
            if key in self._receipts:
                return dict(self._receipts[key])
            claimed = self._store.claim_generating_revision(context, artifact_id, int(revision))
            if claimed is None:
                return self._stable_existing(context, artifact_id, int(revision), key)
            try:
                result = self._run_claim(context, artifact_id, int(revision), claimed, instruction)
            except Exception as exc:
                code = getattr(exc, "code", None) or "document_edit_execution_failed"
                message = str(exc) or "document edit execution failed"
                self._store.fail_revision(context, artifact_id, int(revision), code, message)
                result = {"ok": False, "status": "failed", "errorCode": code, "errorMessage": message, "revision": int(revision)}
            self._receipts[key] = dict(result)
            return result

    def _run_claim(self, context: Any, artifact_id: str, revision: int, claimed: Mapping[str, Any], instruction: Any) -> dict[str, Any]:
        authority = str(claimed.get("bodyAuthority") or claimed.get("body_authority") or "internal")
        if authority not in {"internal", "lark"}:
            raise ValueError("unsupported body authority")
        base_revision = claimed.get("baseRevision")
        if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision < 1:
            raise DocumentEditExecutionError("document_edit_base_revision_missing", "document edit source revision is unavailable")
        body_response = self._documents.get_document_revision(context, artifact_id, base_revision)
        data = body_response.get("data", body_response) if isinstance(body_response, Mapping) else {}
        current = data.get("revision", data) if isinstance(data, Mapping) else {}
        body = current.get("body") if isinstance(current, Mapping) else None
        if not isinstance(body, Mapping):
            raise ValueError("document body is unavailable")
        working = self._working_copy(body, artifact_id, revision, claimed)
        payload = self._generate(instruction, working)
        if "intent_operations" in payload or "intent_ops" in payload:
            plan = DocumentEditPatchPlan.from_intent_mapping(payload, working_copy=working, executable_op_whitelist={"replace_text"})
        else:
            plan = DocumentEditPatchPlan.from_mapping(payload, executable_op_whitelist={"replace_text", "insert_table_row"})
        updated = self._apply(body, plan)
        receipt = {
            "contractId": "openclaw.document_edit.executor_receipt.v1",
            "status": "ready",
            "revision": revision,
            "bodyAuthority": authority,
            "applied": [op.operation_id or op.block.block_id for op in plan.operations],
            "appliedCount": len(plan.operations),
            "manualActions": [item.to_mapping() for item in plan.manual_actions],
            # A Lark write must surface protected remote blocks in the sync
            # receipt; internal revisions keep those blocks untouched and
            # expose any targeted skips through manualActions only.
            "protectedSkipped": [item.block_id for item in plan.manual_actions if item.block_id] if authority == "lark" else [],
            "bodyChecksum": body_checksum(updated),
        }
        if authority == "lark":
            writer = getattr(self._documents, "save_generated_revision", None)
            if not callable(writer):
                raise DocumentEditExecutionError("lark_writer_unavailable", "lark generated revision writer is unavailable")
            writer(context, artifact_id, revision, updated, receipt)
        self._store.complete_revision(context, artifact_id, revision, updated, receipt)
        return {"ok": True, "status": "ready", "revision": revision, "receipt": receipt}

    def _generate(self, instruction: Any, working: DocumentEditWorkingCopy) -> Mapping[str, Any]:
        if isinstance(instruction, Mapping):
            return instruction
        if isinstance(instruction, str) and instruction.strip():
            try:
                parsed = json.loads(instruction)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, Mapping):
                return parsed
        if self._generator is None:
            raise DocumentEditExecutionError("document_edit_generator_unavailable", "document edit generator is unavailable")
        result = self._generator(instruction, working)
        if not isinstance(result, Mapping):
            raise ValueError("document edit generator returned an invalid plan")
        return result

    @staticmethod
    def _working_copy(body: Mapping[str, Any], artifact_id: str, revision: int, claimed: Mapping[str, Any]) -> DocumentEditWorkingCopy:
        blocks = []
        protected = []
        for index, raw in enumerate(body.get("blocks", [])):
            if not isinstance(raw, Mapping) or not raw.get("id"):
                continue
            content = raw.get("content") if isinstance(raw.get("content"), list) else []
            text = "".join(str(item.get("text", "")) for item in content if isinstance(item, Mapping) and item.get("type") == "text")
            item = {"block_id": str(raw["id"]), "path": ["root", str(index)], "block_type": str(raw.get("type", "paragraph")), "text": text,
                    "table_shape": raw.get("table_shape") or {}}
            if raw.get("protected") or raw.get("type") in {"image", "attachment", "callout", "table", "31", "32"}:
                item["reason"] = "protected_block"
                protected.append(item)
            else:
                blocks.append(item)
        return DocumentEditWorkingCopy.from_patch_source({"ok": True, "url": str(claimed.get("url") or f"internal://artifacts/{artifact_id}"), "document_id": str(claimed.get("documentId", artifact_id)),
            "source_hash": str(claimed.get("sourceHash", body_checksum(body))), "revision_token": str(claimed.get("revisionToken", f"revision:{revision}")),
            "snapshot_path": str(claimed.get("snapshotPath", "executor")), "patchable_blocks": blocks, "protected_blocks": protected})

    @staticmethod
    def _apply(body: Mapping[str, Any], plan: DocumentEditPatchPlan) -> dict[str, Any]:
        result = json.loads(json.dumps(body, ensure_ascii=False))
        by_id = {str(block.get("id")): block for block in result.get("blocks", []) if isinstance(block, Mapping)}
        for operation in plan.operations:
            target = by_id.get(operation.block.block_id)
            if target is None:
                continue
            content = target.get("content") if isinstance(target.get("content"), list) else []
            for element in content:
                if isinstance(element, dict) and element.get("type") == "text":
                    element["text"] = operation.new_text
                    break
        return result

    def _stable_existing(self, context: Any, artifact_id: str, revision: int, key: tuple[str, str, int]) -> dict[str, Any]:
        getter = getattr(self._store, "get_revision_receipt", None)
        result = getter(context, artifact_id, revision) if callable(getter) else None
        if isinstance(result, Mapping):
            return dict(result)
        return {"ok": False, "status": "failed", "errorCode": "revision_not_claimable", "revision": revision}
