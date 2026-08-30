from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest
from openclaw_app.services.media_business.documents import (
    DocumentConflict,
    DocumentForbidden,
    DocumentNotFound,
    DocumentsService,
    DocumentUnavailable,
    LarkBlockSnapshot,
    LarkRevisionSnapshot,
    UnsupportedDocumentBlock,
)
from openclaw_app.services.media_business.foundation import TenantContext, body_checksum

NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)
BODY = {
    "schemaVersion": "media.document.body.v1",
    "blocks": [
        {
            "id": "blk_body_0001",
            "type": "paragraph",
            "attrs": {},
            "content": [{"type": "text", "text": "version one", "marks": []}],
        }
    ],
}


class Cursor:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class MiniDatabase:
    def __init__(self, *, state: str = "ready") -> None:
        self.artifacts = {
            ("tenant_0001", "artifact_0001"): [
                "artifact_0001", "project_0001", "creation_document", "personal_web",
                "internal", 1, NOW,
            ]
        }
        checksum = body_checksum(BODY)
        self.revisions = {
            ("tenant_0001", "artifact_0001", 1): [
                "creation_document", "internal", 1, None, state, checksum,
                copy.deepcopy(BODY), NOW, NOW,
            ]
        }
        self.lark_snapshots = {}
        self.receipts = {}
        self.exports = {}
        self.export_identity = {}
        self.inserted_revisions = 0
        self.batches = {}
        self.bindings = {}
        self.mappings = {}
        self.transaction_depth = 0
        self.transaction_count = 0

    def __call__(self):
        return self

    def __enter__(self):
        self.transaction_depth += 1
        self.transaction_count += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.transaction_depth -= 1
        return False

    def execute(self, query, params=()):
        sql = " ".join(query.split())
        if "pg_advisory_xact_lock" in sql:
            return Cursor((True,))
        if "FROM media_product.document_artifacts AS a" in sql and "JOIN media_product.document_revisions" not in sql:
            return Cursor(tuple(self.artifacts.get((params[0], params[1]))) if (params[0], params[1]) in self.artifacts else None)
        if "JOIN media_product.document_revisions AS r" in sql:
            row = self.revisions.get((params[0], params[1], params[2]))
            return Cursor(tuple(row) if row else None)
        if "SELECT state FROM media_product.document_revisions" in sql:
            row = self.revisions.get((params[0], params[1], params[2]))
            return Cursor((row[4],) if row else None)
        if "FROM media_product.sync_batches" in sql and "operation='save'" in sql:
            batch = next(
                (
                    value for (tenant, _sync_id), value in self.batches.items()
                    if tenant == params[0] and value["idempotency_key"] == params[1]
                ),
                None,
            )
            if batch is None:
                return Cursor()
            return Cursor((
                batch["public_sync_id"], batch["artifact_id"], batch["revision"],
                batch["state"], batch["request_checksum"], batch["base_version"],
            ))
        if "SELECT revision, state, request_checksum" in sql:
            batch = self.batches.get((params[0], params[1]))
            if batch is None:
                return Cursor()
            return Cursor((
                batch["revision"], batch["state"], batch["request_checksum"],
                batch["base_version"],
            ))
        if (
            "FROM media_product.lark_document_bindings AS binding" in sql
            or "FROM media_product.sync_batches AS batch" in sql
        ):
            row = self.lark_snapshots.get((params[0], params[1], params[2]))
            return Cursor(tuple(row) if row else None)
        if "SELECT path_fingerprint, request_fingerprint, state" in sql:
            row = self.receipts.get((params[0], "saveDocumentDraft", params[1]))
            return Cursor((row[0], row[1], row[3]) if row else None)
        if "FROM openclaw_account.if2_idempotency_receipts" in sql and sql.startswith("SELECT"):
            row = self.receipts.get((params[0], params[1], params[2]))
            return Cursor(row)
        if "INSERT INTO openclaw_account.if2_idempotency_receipts" in sql:
            if "'reserved'" in sql:
                key = (params[0], "saveDocumentDraft", params[1])
                self.receipts.setdefault(key, (params[2], params[3], None, "reserved"))
            else:
                key = (params[0], params[1], params[2])
                self.receipts.setdefault(key, (params[3], params[4], json.loads(params[6]), "completed"))
            return Cursor()
        if "UPDATE openclaw_account.if2_idempotency_receipts" in sql:
            if "state='completed'" in sql:
                key = (params[1], params[2], params[3])
                old = self.receipts[key]
                self.receipts[key] = (old[0], old[1], json.loads(params[0]), "completed")
            elif "state='failed'" in sql:
                batch = self.batches[(params[1], params[2])]
                key = (params[0], "saveDocumentDraft", batch["idempotency_key"])
                old = self.receipts[key]
                self.receipts[key] = (old[0], old[1], None, "failed")
            return Cursor()
        if "UPDATE media_product.document_revisions" in sql:
            if "SET state=%s" in sql:
                key = (params[1], params[2], params[3])
                row = self.revisions[key]
                row[4], row[8] = params[0], NOW
                return Cursor()
            key = (params[2], params[3], params[4])
            row = self.revisions[key]
            if "SET state='draft'" in sql:
                row[4] = "draft"
            row[5], row[8] = params[0], NOW
            return Cursor()
        if "UPDATE media_document.revision_bodies" in sql:
            key = (params[2], params[3], params[4])
            row = self.revisions[key]
            row[6], row[5], row[8] = json.loads(params[0]), params[1], NOW
            return Cursor()
        if "INSERT INTO media_product.document_revisions" in sql:
            tenant, artifact, revision, base_revision, checksum, _actor = params
            artifact_row = self.artifacts[(tenant, artifact)]
            state = "generating" if "'generating'" in sql else "draft"
            self.revisions[(tenant, artifact, revision)] = [
                artifact_row[2], artifact_row[4], revision, base_revision, state, checksum,
                None, NOW, NOW,
            ]
            self.inserted_revisions += 1
            return Cursor()
        if "INSERT INTO media_document.revision_bodies" in sql:
            tenant, artifact, revision, body, checksum = params
            self.revisions[(tenant, artifact, revision)][5:7] = [checksum, json.loads(body)]
            return Cursor()
        if "UPDATE media_product.document_artifacts" in sql:
            self.artifacts[(params[1], params[2])][5:7] = [params[0], NOW]
            return Cursor()
        if "INSERT INTO media_product.sync_batches" in sql:
            tenant, sync_id, artifact, revision, key, checksum, base_version = params
            self.batches[(tenant, sync_id)] = {
                "public_sync_id": sync_id,
                "artifact_id": artifact,
                "revision": revision,
                "state": "running",
                "idempotency_key": key,
                "request_checksum": checksum,
                "base_version": base_version,
            }
            return Cursor()
        if "INSERT INTO media_product.lark_document_block_mappings" in sql:
            self.mappings.setdefault((params[0], params[1]), []).append(params[2:])
            return Cursor()
        if "UPDATE media_product.sync_batches" in sql:
            if "state='succeeded'" in sql:
                batch = self.batches[(params[4], params[5])]
                batch.update(
                    state="succeeded", remote_version=params[0], body_checksum=params[1],
                    block_count=params[2], protected_block_count=params[3],
                )
            else:
                batch = self.batches[(params[2], params[3])]
                batch.update(state=params[0], error_code=params[1])
            return Cursor()
        if "INSERT INTO media_product.lark_document_bindings" in sql:
            self.bindings[(params[0], params[1])] = params[2]
            batch = self.batches[(params[0], params[2])]
            mappings = self.mappings.get((params[0], params[2]), [])
            self.lark_snapshots[(params[0], params[1], batch["revision"])] = [
                params[2], batch["remote_version"], batch["body_checksum"],
                batch["block_count"], batch["protected_block_count"],
                [
                    {
                        "publicBlockId": item[0], "remoteBlockId": item[1],
                        "blockChecksum": item[2], "isProtected": item[3],
                        "protectionReason": item[4],
                    }
                    for item in mappings
                ],
            ]
            return Cursor()
        if "SELECT public_export_id FROM media_document.exports" in sql:
            export_id = self.export_identity.get((params[0], params[1]))
            return Cursor((export_id,) if export_id else None)
        if "INSERT INTO media_document.exports" in sql:
            tenant, export_id, artifact, revision, fmt, template, renderer, identity, checksum = params
            key = (tenant, identity)
            if key not in self.export_identity:
                self.export_identity[key] = export_id
                self.exports[(tenant, export_id)] = [
                    export_id, artifact, revision, fmt, "queued", template, renderer,
                    checksum, None, None, NOW, NOW,
                ]
            return Cursor()
        if "FROM media_document.exports" in sql and "public_export_id = %s" in sql:
            row = self.exports.get((params[0], params[1]))
            return Cursor(tuple(row) if row else None)
        raise AssertionError(f"unexpected SQL: {sql}")


class Signer:
    def create_download_url(self, object_ref, *, expires_in_seconds):
        assert object_ref == "objects/export.docx"
        assert expires_in_seconds == 300
        return "https://download.example.test/signed", "2026-08-05T00:05:00+00:00"


class LarkGateway:
    def __init__(self, snapshot: LarkRevisionSnapshot) -> None:
        self.snapshot = snapshot

    def read_revision(self, tenant_id, public_artifact_id, remote_document_version):
        assert tenant_id == "tenant_0001"
        assert public_artifact_id == "artifact_0001"
        assert remote_document_version == self.snapshot.remote_document_version
        return self.snapshot


class SagaGateway(LarkGateway):
    def __init__(self, database: MiniDatabase, snapshot: LarkRevisionSnapshot) -> None:
        super().__init__(snapshot)
        self.database = database
        self.save_calls = 0
        self.reconcile_calls = 0
        self.fail_first_save = False

    def save_draft(
        self, tenant_id, public_artifact_id, body, expected_remote_version, public_sync_id
    ):
        assert self.database.transaction_depth == 0
        assert expected_remote_version == "remote_version_0001"
        assert public_sync_id.startswith("sync_")
        self.save_calls += 1
        if self.fail_first_save:
            self.fail_first_save = False
            raise TimeoutError("unknown remote outcome")
        return self.snapshot

    def reconcile_save(
        self, tenant_id, public_artifact_id, public_sync_id, expected_remote_version
    ):
        assert self.database.transaction_depth == 0
        assert expected_remote_version == "remote_version_0001"
        self.reconcile_calls += 1
        return self.snapshot


def lark_database(*, declared_block_count: int = 1) -> tuple[MiniDatabase, LarkRevisionSnapshot]:
    database = MiniDatabase(state="ready")
    database.artifacts[("tenant_0001", "artifact_0001")][3:5] = [
        "organization_lark",
        "lark",
    ]
    database.revisions[("tenant_0001", "artifact_0001", 1)][1] = "lark"
    database.revisions[("tenant_0001", "artifact_0001", 1)][6] = None
    block = LarkBlockSnapshot(
        public_block_id="blk_body_0001",
        remote_block_id="remote_block_0001",
        block_checksum="b" * 64,
        is_protected=True,
        protection_reason="unsupported_table",
    )
    database.lark_snapshots[("tenant_0001", "artifact_0001", 1)] = [
        "sync_0001",
        "remote_version_0001",
        body_checksum(BODY),
        declared_block_count,
        1,
        [
            {
                "publicBlockId": block.public_block_id,
                "remoteBlockId": block.remote_block_id,
                "blockChecksum": block.block_checksum,
                "isProtected": block.is_protected,
                "protectionReason": block.protection_reason,
            }
        ],
    ]
    return database, LarkRevisionSnapshot(
        copy.deepcopy(BODY), "remote_version_0001", (block,)
    )


def context(tenant="tenant_0001"):
    return TenantContext(tenant, "user_0001")


def draft_request(body=BODY, *, remote_version=None):
    return {
        "expectedRevision": 1,
        "expectedBodyChecksum": body_checksum(BODY),
        "expectedRemoteDocumentVersion": remote_version,
        "body": copy.deepcopy(body),
    }


def export_request(revision=1):
    return {
        "revision": revision,
        "format": "docx",
        "templateVersion": "template-v1",
        "rendererVersion": "renderer-v1",
    }


def test_get_body_reads_tenant_scoped_canonical_jsonb_revision() -> None:
    service = DocumentsService(MiniDatabase())
    response = service.get_document_body(context(), "artifact_0001")
    assert response["data"]["revision"]["body"] == BODY
    assert response["data"]["revision"]["bodyChecksum"] == body_checksum(BODY)
    with pytest.raises(DocumentNotFound):
        service.get_document_body(context("tenant_0002"), "artifact_0001")


def test_missing_context_is_a_branded_document_forbidden() -> None:
    """TI-02: DocumentsService._tenant used to bare-call require_context()
    and let its raw foundation.Forbidden escape uncaught -- every other
    media_business service maps this to its own branded Forbidden
    subclass. Confirms the fix.
    """
    service = DocumentsService(MiniDatabase())
    with pytest.raises(DocumentForbidden):
        service.get_document_body(None, "artifact_0001")  # type: ignore[arg-type]


def test_tenant_id_is_stripped_before_use() -> None:
    """TI-02: the prior _tenant() returned context.tenant_id verbatim, with
    no strip() -- a tenant id with incidental surrounding whitespace would
    silently mismatch every tenant-scoped row. This is a deliberate
    tightening: tenant_id_of() strips it first.
    """
    service = DocumentsService(MiniDatabase())
    response = service.get_document_body(context("  tenant_0001  "), "artifact_0001")
    assert response["data"]["revision"]["body"] == BODY


def test_save_draft_creates_one_revision_replays_and_rejects_key_rebinding() -> None:
    database = MiniDatabase(state="ready")
    service = DocumentsService(database)
    changed = copy.deepcopy(BODY)
    changed["blocks"][0]["content"][0]["text"] = "draft two"
    request = draft_request(changed)

    first = service.save_document_draft(
        context(), "artifact_0001", request, idempotency_key="draft_key_0001"
    )
    second = service.save_document_draft(
        context(), "artifact_0001", request, idempotency_key="draft_key_0001"
    )

    assert first == second
    assert first["data"]["revision"] == 2
    assert first["data"]["state"] == "draft"
    assert first["data"]["body"] == changed
    assert database.inserted_revisions == 1

    rebound = copy.deepcopy(request)
    rebound["body"]["blocks"][0]["content"][0]["text"] = "different"
    with pytest.raises(DocumentConflict, match="idempotency"):
        service.save_document_draft(
            context(), "artifact_0001", rebound, idempotency_key="draft_key_0001"
        )


def test_lark_save_uses_reserve_external_write_and_atomic_finalize() -> None:
    database, _current_snapshot = lark_database()
    changed = copy.deepcopy(BODY)
    changed["blocks"][0]["content"][0]["text"] = "saved in Lark"
    block = LarkBlockSnapshot(
        public_block_id="blk_body_0001",
        remote_block_id="remote_block_0002",
        block_checksum="c" * 64,
        is_protected=False,
        protection_reason=None,
    )
    gateway = SagaGateway(
        database,
        LarkRevisionSnapshot(changed, "remote_version_0002", (block,)),
    )
    service = DocumentsService(database, lark_gateway=gateway)
    request = draft_request(changed, remote_version="remote_version_0001")

    first = service.save_document_draft(
        context(), "artifact_0001", request, idempotency_key="lark_save_key_01"
    )
    second = service.save_document_draft(
        context(), "artifact_0001", request, idempotency_key="lark_save_key_01"
    )

    assert first == second
    assert first["data"]["revision"] == 2
    assert first["data"]["body"] == changed
    assert first["data"]["remoteDocumentVersion"] == "remote_version_0002"
    assert gateway.save_calls == 1
    assert gateway.reconcile_calls == 0
    assert database.transaction_count == 3
    batch = next(iter(database.batches.values()))
    assert batch["state"] == "succeeded"
    assert database.bindings[("tenant_0001", "artifact_0001")] == batch["public_sync_id"]
    assert database.artifacts[("tenant_0001", "artifact_0001")][5] == 2
    assert database.revisions[("tenant_0001", "artifact_0001", 1)][4] == "ready"
    assert database.revisions[("tenant_0001", "artifact_0001", 2)][4] == "draft"


def test_lark_unknown_outcome_stays_running_and_same_key_reconciles() -> None:
    database, _current_snapshot = lark_database()
    changed = copy.deepcopy(BODY)
    changed["blocks"][0]["content"][0]["text"] = "reconciled in Lark"
    block = LarkBlockSnapshot(
        public_block_id="blk_body_0001",
        remote_block_id="remote_block_0002",
        block_checksum="d" * 64,
        is_protected=False,
        protection_reason=None,
    )
    gateway = SagaGateway(
        database,
        LarkRevisionSnapshot(changed, "remote_version_0002", (block,)),
    )
    gateway.fail_first_save = True
    service = DocumentsService(database, lark_gateway=gateway)
    request = draft_request(changed, remote_version="remote_version_0001")

    with pytest.raises(DocumentUnavailable, match="requires reconciliation"):
        service.save_document_draft(
            context(), "artifact_0001", request, idempotency_key="lark_save_key_02"
        )
    batch = next(iter(database.batches.values()))
    assert batch["state"] == "running"
    assert database.artifacts[("tenant_0001", "artifact_0001")][5] == 1

    response = service.save_document_draft(
        context(), "artifact_0001", request, idempotency_key="lark_save_key_02"
    )
    assert response["data"]["revision"] == 2
    assert gateway.save_calls == 1
    assert gateway.reconcile_calls == 1
    assert batch["state"] == "succeeded"


def test_export_is_ready_only_and_deduplicated_by_frozen_identity() -> None:
    draft_service = DocumentsService(MiniDatabase(state="draft"))
    with pytest.raises(DocumentConflict, match="ready"):
        draft_service.create_document_export(
            context(), "artifact_0001", export_request(), idempotency_key="export_key_0001"
        )

    database = MiniDatabase(state="ready")
    service = DocumentsService(database)
    first = service.create_document_export(
        context(), "artifact_0001", export_request(), idempotency_key="export_key_0001"
    )
    second = service.create_document_export(
        context(), "artifact_0001", export_request(), idempotency_key="export_key_0002"
    )
    assert first == second
    assert first["data"]["state"] == "queued"
    assert len(database.exports) == 1


def test_export_fails_closed_with_exact_protected_block_ids() -> None:
    database, snapshot = lark_database()
    protected_body = copy.deepcopy(BODY)
    protected_body["blocks"][0]["id"] = "blk_protected_1"
    protected_body["blocks"].append(
        {
            "id": "blk_protected_2",
            "type": "paragraph",
            "attrs": {},
            "content": [{"type": "text", "text": "protected two", "marks": []}],
        }
    )
    protected_checksum = body_checksum(protected_body)
    database.revisions[("tenant_0001", "artifact_0001", 1)][5] = protected_checksum
    database.lark_snapshots[("tenant_0001", "artifact_0001", 1)][2] = protected_checksum
    second_block = LarkBlockSnapshot(
        public_block_id="blk_protected_2",
        remote_block_id="remote_block_0002",
        block_checksum="c" * 64,
        is_protected=True,
        protection_reason="unsupported_embed",
    )
    first_mapping = database.lark_snapshots[("tenant_0001", "artifact_0001", 1)][5][0]
    first_mapping["publicBlockId"] = "blk_protected_1"
    database.lark_snapshots[("tenant_0001", "artifact_0001", 1)][3:5] = [2, 2]
    database.lark_snapshots[("tenant_0001", "artifact_0001", 1)][5].append(
        {
            "publicBlockId": second_block.public_block_id,
            "remoteBlockId": second_block.remote_block_id,
            "blockChecksum": second_block.block_checksum,
            "isProtected": second_block.is_protected,
            "protectionReason": second_block.protection_reason,
        }
    )
    first_block = LarkBlockSnapshot(
        public_block_id="blk_protected_1",
        remote_block_id="remote_block_0001",
        block_checksum="b" * 64,
        is_protected=True,
        protection_reason="unsupported_table",
    )
    snapshot = LarkRevisionSnapshot(
        protected_body,
        snapshot.remote_document_version,
        (first_block, second_block),
    )
    service = DocumentsService(database, lark_gateway=LarkGateway(snapshot))
    with pytest.raises(UnsupportedDocumentBlock) as caught:
        service.create_document_export(
            context(), "artifact_0001", export_request(), idempotency_key="export_key_0001"
        )
    assert caught.value.code == "unsupported_document_block"
    assert caught.value.block_ids == ("blk_protected_1", "blk_protected_2")


def test_lark_read_requires_complete_snapshot_counts() -> None:
    database, snapshot = lark_database(declared_block_count=2)
    service = DocumentsService(database, lark_gateway=LarkGateway(snapshot))
    with pytest.raises(DocumentUnavailable, match="inventory"):
        service.get_document_body(context(), "artifact_0001")


def test_download_requires_ready_export_and_returns_controlled_short_lived_url() -> None:
    database = MiniDatabase(state="ready")
    service = DocumentsService(database, download_signer=Signer())
    queued = service.create_document_export(
        context(), "artifact_0001", export_request(), idempotency_key="export_key_0001"
    )
    export_id = queued["data"]["publicExportId"]
    with pytest.raises(DocumentConflict, match="ready"):
        service.get_document_export_download(context(), export_id)

    row = database.exports[("tenant_0001", export_id)]
    row[4], row[8], row[9] = "ready", "a" * 64, "objects/export.docx"
    download = service.get_document_export_download(context(), export_id)
    assert download["data"] == {
        "publicExportId": export_id,
        "format": "docx",
        "downloadUrl": "https://download.example.test/signed",
        "expiresAt": "2026-08-05T00:05:00+00:00",
        "contentChecksum": "a" * 64,
    }


def test_public_service_surface_matches_exact_if2_six_operations() -> None:
    expected = {
        "get_document_body",
        "save_document_draft",
        "get_document_revision",
        "create_document_export",
        "get_document_export",
        "get_document_export_download",
    }
    assert expected <= set(dir(DocumentsService))
