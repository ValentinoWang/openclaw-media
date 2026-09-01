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
from .media_business.foundation import TenantContext


class RevisionStore(Protocol):
    def enqueue_job(self, connection: Any, context: Any, artifact_id: str, revision: int, instruction: str) -> None: ...
    def claim_generating_revision(self, context: Any, artifact_id: str, revision: int) -> Mapping[str, Any] | None: ...
    def persist_generated_plan(self, context: Any, artifact_id: str, revision: int, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def complete_revision(self, context: Any, artifact_id: str, revision: int, body: Mapping[str, Any], receipt: Mapping[str, Any]) -> Any: ...
    def complete_lark_revision(self, context: Any, artifact_id: str, revision: int, receipt: Mapping[str, Any]) -> Any: ...
    def fail_revision(self, context: Any, artifact_id: str, revision: int, error_code: str, message: str) -> Any: ...
    def recover_pending(self, limit: int = 10) -> list[Mapping[str, Any]]: ...


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

    def enqueue_job(self, connection: Any, context: Any, artifact_id: str, revision: int, instruction: str) -> None:
        connection.execute(
            """INSERT INTO media_product.document_edit_jobs
                   (tenant_id, public_artifact_id, revision, actor_public_id, instruction)
                 VALUES (%s,%s,%s,%s,%s)
                 ON CONFLICT (tenant_id, public_artifact_id, revision) DO NOTHING""",
            (context.tenant_id, artifact_id, revision, context.user_public_id, instruction),
        )

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
                """SELECT a.body_authority, r.base_revision, r.state, r.body_checksum,
                          job.instruction, job.generated_plan
                     FROM media_product.document_edit_jobs AS job
                     JOIN media_product.document_artifacts AS a
                       ON a.tenant_id=job.tenant_id AND a.public_id=job.public_artifact_id
                     JOIN media_product.document_revisions AS r
                       ON r.tenant_id=job.tenant_id
                      AND r.public_artifact_id=job.public_artifact_id
                      AND r.revision=job.revision
                    WHERE job.tenant_id=%s AND job.public_artifact_id=%s
                      AND job.revision=%s AND job.state IN ('pending','running')
                      AND r.state IN ('generating','ready')
                    FOR UPDATE""",
                (context.tenant_id, artifact_id, revision),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE media_product.document_edit_jobs
                      SET state='running', started_at=COALESCE(started_at, now())
                    WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s
                      AND state IN ('pending','running')""",
                (context.tenant_id, artifact_id, revision),
            )
            commit = getattr(connection, "commit", None)
            if callable(commit):
                commit()
            plan = row[5]
            if isinstance(plan, str):
                plan = json.loads(plan)
            return {
                "bodyAuthority": row[0], "baseRevision": row[1], "revisionState": row[2],
                "bodyChecksum": row[3], "instruction": row[4], "generatedPlan": plan,
                "documentId": artifact_id,
            }

    def persist_generated_plan(self, context: Any, artifact_id: str, revision: int, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        with self._connection_factory() as connection:
            connection.execute(
                """UPDATE media_product.document_edit_jobs
                      SET generated_plan=COALESCE(generated_plan, %s::jsonb)
                    WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s
                      AND state='running'""",
                (json.dumps(dict(plan), ensure_ascii=False), context.tenant_id, artifact_id, revision),
            )
            row = connection.execute(
                """SELECT generated_plan FROM media_product.document_edit_jobs
                    WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s""",
                (context.tenant_id, artifact_id, revision),
            ).fetchone()
            if row is None or row[0] is None:
                raise DocumentEditExecutionError("document_edit_plan_persist_failed", "document edit plan persistence failed")
            persisted = row[0]
            if isinstance(persisted, str):
                persisted = json.loads(persisted)
            if not isinstance(persisted, Mapping):
                raise DocumentEditExecutionError("document_edit_plan_persist_failed", "document edit plan persistence failed")
            commit = getattr(connection, "commit", None)
            if callable(commit):
                commit()
            return dict(persisted)

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
                """UPDATE media_product.document_edit_jobs
                      SET state='succeeded', execution_receipt=%s::jsonb, completed_at=now()
                    WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s AND state='running'""",
                (json.dumps(dict(receipt), ensure_ascii=False), context.tenant_id, artifact_id, revision),
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

    def complete_lark_revision(self, context: Any, artifact_id: str, revision: int, receipt: Mapping[str, Any]) -> None:
        with self._connection_factory() as connection:
            row = connection.execute(
                """SELECT state FROM media_product.document_revisions
                     WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s
                     FOR UPDATE""",
                (context.tenant_id, artifact_id, revision),
            ).fetchone()
            if row is None or row[0] != "ready":
                raise DocumentEditExecutionError("document_edit_lark_not_confirmed", "Lark revision is not confirmed ready")
            connection.execute(
                """UPDATE media_product.document_edit_jobs
                      SET state='succeeded', execution_receipt=%s::jsonb, completed_at=now()
                    WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s AND state='running'""",
                (json.dumps(dict(receipt), ensure_ascii=False), context.tenant_id, artifact_id, revision),
            )
            connection.execute(
                """UPDATE openclaw_account.if2_idempotency_receipts SET state='completed', response_status=200,
                      response_json=%s::jsonb, completed_at=now(), lease_owner=NULL, lease_expires_at=NULL
                   WHERE scope_kind='tenant' AND scope_id=%s AND operation_id=%s AND idempotency_key=%s AND state='reserved'""",
                (json.dumps({"ok": True, "status": "ready", "revision": revision, "receipt": dict(receipt)}, ensure_ascii=False), context.tenant_id, self._operation(artifact_id, revision), f"revision-{revision}"),
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
            connection.execute(
                """UPDATE media_product.document_edit_jobs
                      SET state='failed', execution_receipt=%s::jsonb, completed_at=now()
                    WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s AND state='running'""",
                (json.dumps({"status": "failed", "errorCode": error_code, "errorMessage": message}, ensure_ascii=False), context.tenant_id, artifact_id, revision),
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

    def recover_pending(self, limit: int = 10) -> list[Mapping[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("document edit recovery limit is invalid")
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT tenant_id, actor_public_id, public_artifact_id, revision, instruction
                     FROM media_product.document_edit_jobs
                    WHERE state IN ('pending','running')
                    ORDER BY created_at, id
                    LIMIT %s""",
                (limit,),
            ).fetchall()
        return [
            {"tenantId": row[0], "userPublicId": row[1], "artifactId": row[2], "revision": row[3], "instruction": row[4]}
            for row in rows
        ]


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
        if claimed.get("revisionState") == "ready":
            receipt = self._receipt_for_ready_retry(context, artifact_id, revision, claimed)
            self._store.complete_lark_revision(context, artifact_id, revision, receipt)
            return {"ok": True, "status": "ready", "revision": revision, "receipt": receipt}
        body_response = self._documents.get_document_revision(context, artifact_id, base_revision)
        data = body_response.get("data", body_response) if isinstance(body_response, Mapping) else {}
        current = data.get("revision", data) if isinstance(data, Mapping) else {}
        body = current.get("body") if isinstance(current, Mapping) else None
        if not isinstance(body, Mapping):
            raise ValueError("document body is unavailable")
        working = self._working_copy(body, artifact_id, revision, claimed)
        stored_plan = claimed.get("generatedPlan") or claimed.get("generated_plan")
        payload = stored_plan if isinstance(stored_plan, Mapping) else self._generate(instruction if instruction is not None else claimed.get("instruction"), working)
        if any(
            isinstance(item, Mapping) and item.get("op") == "insert_table_row"
            for item in payload.get("operations", []) if isinstance(payload.get("operations"), list)
        ):
            raise DocumentEditExecutionError(
                "document_edit_table_row_unavailable",
                "insert_table_row is not available in the document edit executor",
            )
        if "intent_operations" in payload or "intent_ops" in payload:
            plan = DocumentEditPatchPlan.from_intent_mapping(payload, working_copy=working, executable_op_whitelist={"replace_text"})
        else:
            plan = DocumentEditPatchPlan.from_mapping(payload, executable_op_whitelist={"replace_text"})
        if not isinstance(stored_plan, Mapping):
            persisted = getattr(self._store, "persist_generated_plan", None)
            if callable(persisted):
                plan = DocumentEditPatchPlan.from_mapping(
                    persisted(context, artifact_id, revision, plan.to_mapping()),
                    executable_op_whitelist={"replace_text"},
                )
        if any(operation.op == "insert_table_row" for operation in plan.operations):
            raise DocumentEditExecutionError(
                "document_edit_table_row_unavailable",
                "insert_table_row is not available in the document edit executor",
            )
        updated = self._apply(body, plan)
        receipt = {
            "contractId": "openclaw.document_edit.executor_receipt.v1",
            "status": "ready",
            "revision": revision,
            "bodyAuthority": authority,
            "applied": [
                {"operation": op.op, "blockId": op.block.block_id}
                for op in plan.operations
            ],
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
            complete_lark = getattr(self._store, "complete_lark_revision", None)
            if not callable(complete_lark):
                raise DocumentEditExecutionError("document_edit_lark_completion_unavailable", "Lark completion store is unavailable")
            complete_lark(context, artifact_id, revision, receipt)
        else:
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

    def recover_pending(self, limit: int = 10) -> list[dict[str, Any]]:
        recover = getattr(self._store, "recover_pending", None)
        if not callable(recover):
            return []
        results: list[dict[str, Any]] = []
        for item in recover(limit):
            if not isinstance(item, Mapping):
                continue
            try:
                context = TenantContext(str(item["tenantId"]), str(item["userPublicId"]))
                results.append(self.execute(context, str(item["artifactId"]), int(item["revision"]), item.get("instruction")))
            except Exception:
                continue
        return results

    @staticmethod
    def _receipt_for_ready_retry(context: Any, artifact_id: str, revision: int, claimed: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "contractId": "openclaw.document_edit.executor_receipt.v1",
            "status": "ready",
            "revision": revision,
            "bodyAuthority": "lark",
            "applied": [],
            "appliedCount": 0,
            "manualActions": [],
            "protectedSkipped": [],
            "bodyChecksum": str(claimed.get("bodyChecksum") or ""),
        }
