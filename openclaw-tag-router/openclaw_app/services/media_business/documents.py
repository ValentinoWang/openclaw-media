"""IF2 document service with one canonical body and ready-only exports.

This module is intentionally independent of the HTTP adapter.  The six public
methods map one-to-one to the frozen IF2 operationIds.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from common.canonical_digest import digest_bytes

from . import foundation
from .foundation import (
    IF2_KEY,
    MediaBusinessError,
    TenantContext,
    _fetchone,
    assert_autosave_state,
    assert_export_state,
    body_checksum,
    idempotency_key,
    preserve_protected_blocks,
    public_projection,
    require_context,
    validate_body,
)

SCHEMA_VERSION = "media_web_business_pages_v2"
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_CHECKSUM = re.compile(r"^[a-f0-9]{64}$")
_FORMATS = {"docx", "pdf"}


class DocumentServiceError(MediaBusinessError):
    block_ids: tuple[str, ...] = ()

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int,
        field: str | None = None,
        block_ids: tuple[str, ...] = (),
    ) -> None:
        super().__init__(code, message, status=status, field=field)
        self.block_ids = block_ids


class DocumentInvalidRequest(DocumentServiceError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(foundation.INVALID_REQUEST, message, status=400, field=field)


class DocumentNotFound(DocumentServiceError):
    def __init__(self) -> None:
        super().__init__(foundation.RESOURCE_NOT_FOUND, "document resource was not found", status=404)


class DocumentConflict(DocumentServiceError):
    def __init__(self, message: str = "document revision conflict") -> None:
        super().__init__("document_revision_conflict", message, status=409)


class UnsupportedDocumentBlock(DocumentServiceError):
    def __init__(self, block_ids: set[str] | tuple[str, ...]) -> None:
        ordered = tuple(sorted(block_ids))
        super().__init__(
            "unsupported_document_block",
            "document contains protected or unsupported blocks",
            status=422,
            block_ids=ordered,
        )


class DocumentUnavailable(DocumentServiceError):
    def __init__(self, message: str = "document service is unavailable") -> None:
        super().__init__(foundation.INTERNAL_ERROR, message, status=500)


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


ConnectionFactory = Callable[[], AbstractContextManager[DatabaseConnection]]


@dataclass(frozen=True)
class LarkBlockSnapshot:
    public_block_id: str
    remote_block_id: str
    block_checksum: str
    is_protected: bool
    protection_reason: str | None


@dataclass(frozen=True)
class LarkRevisionSnapshot:
    body: dict[str, Any]
    remote_document_version: str
    blocks: tuple[LarkBlockSnapshot, ...]


@dataclass(frozen=True)
class _StoredLarkSnapshot:
    public_sync_id: str
    remote_document_version: str
    body_checksum: str
    blocks: tuple[LarkBlockSnapshot, ...]

    @property
    def protected_block_ids(self) -> set[str]:
        return {block.public_block_id for block in self.blocks if block.is_protected}


@dataclass(frozen=True)
class _PreparedLarkSave:
    public_sync_id: str
    revision: int
    prior_revision: int
    base_remote_document_version: str
    body: dict[str, Any]
    reconcile: bool


class LarkDocumentGateway(Protocol):
    def read_revision(
        self,
        tenant_id: str,
        public_artifact_id: str,
        remote_document_version: str | None,
    ) -> LarkRevisionSnapshot: ...

    def save_draft(
        self,
        tenant_id: str,
        public_artifact_id: str,
        body: dict[str, Any],
        expected_remote_version: str,
        public_sync_id: str,
    ) -> LarkRevisionSnapshot: ...

    def reconcile_save(
        self,
        tenant_id: str,
        public_artifact_id: str,
        public_sync_id: str,
        expected_remote_version: str,
    ) -> LarkRevisionSnapshot: ...


class DownloadSigner(Protocol):
    def create_download_url(self, object_ref: str, *, expires_in_seconds: int) -> tuple[str, str]: ...


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise DocumentUnavailable("stored document JSON is invalid")
    return dict(value)


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return current.isoformat()
    if isinstance(value, str) and value.strip():
        return value
    raise DocumentUnavailable("stored document timestamp is invalid")


def _public_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _PUBLIC_ID.fullmatch(value):
        raise DocumentInvalidRequest(f"{field} is invalid", field=field)
    return value


def _positive_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DocumentInvalidRequest("revision is invalid", field="revision")
    return value


def _optional_checksum(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _CHECKSUM.fullmatch(value):
        raise DocumentInvalidRequest(f"{field} is invalid", field=field)
    return value


def _idempotency_key(value: Any) -> str:
    return idempotency_key(
        value,
        error=lambda: DocumentInvalidRequest("Idempotency-Key is invalid", field="Idempotency-Key"),
        policy=IF2_KEY,
    )


def _request_fingerprint(value: Mapping[str, Any]) -> bytes:
    return digest_bytes(value, allow_nan=True)


def _path_fingerprint(operation: str, public_id: str) -> bytes:
    return hashlib.sha256(f"{operation}:{public_id}".encode()).digest()


def prepare_autosave(
    body: dict[str, Any],
    state: str,
    *,
    previous_body: dict[str, Any] | None = None,
    protected_block_ids: set[str] | None = None,
    targeted_block_ids: set[str] | None = None,
) -> dict[str, Any]:
    assert_autosave_state(state)
    validated = validate_body(body)
    if previous_body is not None:
        validated = preserve_protected_blocks(
            previous_body,
            validated,
            protected_block_ids or set(),
            targeted_block_ids,
        )
    return {"body": validated, "bodyChecksum": body_checksum(validated)}


def prepare_export(
    body: dict[str, Any],
    state: str,
    *,
    protected_block_ids: set[str] | None = None,
) -> dict[str, str]:
    assert_export_state(state)
    validated = validate_body(body)
    if protected_block_ids:
        # Reuse the canonical protected-block detector so the block IDs survive.
        preserve_protected_blocks(validated, validated, protected_block_ids, protected_block_ids)
    return {"sourceBodyChecksum": body_checksum(validated)}


class DocumentsService:
    _ARTIFACT_QUERY = """
        SELECT a.public_id, a.public_project_id, a.artifact_kind, a.workspace_mode,
               a.body_authority, a.current_revision, a.updated_at
          FROM media_product.document_artifacts AS a
         WHERE a.tenant_id = %s AND a.public_id = %s
    """
    _REVISION_QUERY = """
        SELECT a.artifact_kind, a.body_authority, r.revision, r.base_revision,
               r.state, r.body_checksum,
               CASE WHEN a.body_authority = 'lark' THEN mirror.body_json ELSE b.body_json END,
               r.created_at, r.updated_at
          FROM media_product.document_artifacts AS a
          JOIN media_product.document_revisions AS r
            ON r.tenant_id = a.tenant_id AND r.public_artifact_id = a.public_id
          LEFT JOIN media_document.revision_bodies AS b
            ON b.tenant_id = r.tenant_id
           AND b.public_artifact_id = r.public_artifact_id
           AND b.revision = r.revision
          LEFT JOIN media_document.lark_read_mirrors AS mirror
            ON mirror.tenant_id = r.tenant_id
           AND mirror.public_artifact_id = r.public_artifact_id
           AND mirror.revision = r.revision
         WHERE a.tenant_id = %s AND a.public_id = %s AND r.revision = %s
    """
    _CURRENT_LARK_SNAPSHOT_QUERY = """
        SELECT batch.public_sync_id, batch.remote_document_version,
               batch.body_checksum, batch.block_count,
               batch.protected_block_count,
               COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           'publicBlockId', mapping.public_block_id,
                           'remoteBlockId', mapping.remote_block_id,
                           'blockChecksum', mapping.block_checksum,
                           'isProtected', mapping.is_protected,
                           'protectionReason', mapping.protection_reason
                       ) ORDER BY mapping.id
                   ) FILTER (WHERE mapping.id IS NOT NULL),
                   '[]'::jsonb
               )
          FROM media_product.lark_document_bindings AS binding
          JOIN media_product.sync_batches AS batch
            ON batch.tenant_id = binding.tenant_id
           AND batch.public_sync_id = binding.public_sync_id
          LEFT JOIN media_product.lark_document_block_mappings AS mapping
            ON mapping.tenant_id = batch.tenant_id
           AND mapping.public_sync_id = batch.public_sync_id
         WHERE binding.tenant_id = %s
           AND binding.public_artifact_id = %s
           AND batch.public_artifact_id = binding.public_artifact_id
           AND batch.revision = %s
           AND batch.state = 'succeeded'
         GROUP BY batch.id
    """
    _HISTORICAL_LARK_SNAPSHOT_QUERY = """
        SELECT batch.public_sync_id, batch.remote_document_version,
               batch.body_checksum, batch.block_count,
               batch.protected_block_count,
               COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           'publicBlockId', mapping.public_block_id,
                           'remoteBlockId', mapping.remote_block_id,
                           'blockChecksum', mapping.block_checksum,
                           'isProtected', mapping.is_protected,
                           'protectionReason', mapping.protection_reason
                       ) ORDER BY mapping.id
                   ) FILTER (WHERE mapping.id IS NOT NULL),
                   '[]'::jsonb
               )
          FROM media_product.sync_batches AS batch
          LEFT JOIN media_product.lark_document_block_mappings AS mapping
            ON mapping.tenant_id = batch.tenant_id
           AND mapping.public_sync_id = batch.public_sync_id
         WHERE batch.tenant_id = %s
           AND batch.public_artifact_id = %s
           AND batch.revision = %s
           AND batch.state = 'succeeded'
         GROUP BY batch.id
         ORDER BY batch.completed_at DESC, batch.id DESC
         LIMIT 1
    """
    _EXPORT_QUERY = """
        SELECT public_export_id, public_artifact_id, revision, format, state,
               template_version, renderer_version, source_body_checksum,
               content_checksum, object_ref, created_at, updated_at
          FROM media_document.exports
         WHERE tenant_id = %s AND public_export_id = %s
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        lark_gateway: LarkDocumentGateway | None = None,
        download_signer: DownloadSigner | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._lark_gateway = lark_gateway
        self._download_signer = download_signer

    def get_document_body(self, context: TenantContext, public_artifact_id: str) -> dict[str, Any]:
        tenant_id = self._tenant(context)
        artifact_id = _public_id(public_artifact_id, "publicArtifactId")
        with self._connection_factory() as connection:
            artifact = self._artifact(connection, tenant_id, artifact_id)
            revision = self._revision(connection, tenant_id, artifact_id, artifact[5], artifact)
        return self._body_response(artifact, revision)

    def save_document_draft(
        self,
        context: TenantContext,
        public_artifact_id: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        tenant_id = self._tenant(context)
        artifact_id = _public_id(public_artifact_id, "publicArtifactId")
        key = _idempotency_key(idempotency_key)
        normalized = self._draft_request(request)
        request_fingerprint = _request_fingerprint(
            {"publicArtifactId": artifact_id, "request": normalized}
        )
        path_fingerprint = _path_fingerprint("saveDocumentDraft", artifact_id)
        operation = "saveDocumentDraft"
        with self._connection_factory() as connection:
            self._lock(connection, tenant_id, artifact_id)
            replay = self._idempotent_replay(
                connection, tenant_id, operation, key, path_fingerprint, request_fingerprint
            )
            if replay is not None:
                return replay
            artifact = self._artifact(connection, tenant_id, artifact_id, for_update=True)
            if artifact[4] == "lark":
                prepared = self._prepare_lark_save(
                    connection,
                    context,
                    artifact,
                    normalized,
                    key,
                    path_fingerprint,
                    request_fingerprint,
                )
            else:
                prepared = None
        if prepared is not None:
            return self._execute_lark_save(
                context,
                artifact_id,
                operation,
                key,
                path_fingerprint,
                request_fingerprint,
                prepared,
            )
        with self._connection_factory() as connection:
            self._lock(connection, tenant_id, artifact_id)
            replay = self._idempotent_replay(
                connection, tenant_id, operation, key, path_fingerprint, request_fingerprint
            )
            if replay is not None:
                return replay
            artifact = self._artifact(connection, tenant_id, artifact_id, for_update=True)
            current = self._revision(connection, tenant_id, artifact_id, artifact[5], artifact)
            self._assert_expected(current, normalized)
            if current[4] not in {"draft", "ready"}:
                raise DocumentConflict("draft save requires the current draft or ready revision")
            body = prepare_autosave(normalized["body"], "draft")["body"]
            checksum = body_checksum(body)
            revision_number = current[2] if current[4] == "draft" else current[2] + 1
            if current[4] == "draft":
                connection.execute(
                    """UPDATE media_product.document_revisions
                          SET body_checksum=%s, actor_public_id=%s, generation_source='manual_save',
                              updated_at=now()
                        WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s AND state='draft'""",
                    (
                        checksum,
                        context.user_public_id,
                        tenant_id,
                        artifact_id,
                        revision_number,
                    ),
                )
                if artifact[4] == "internal":
                    connection.execute(
                        """UPDATE media_document.revision_bodies
                              SET body_json=%s::jsonb, body_checksum=%s, updated_at=now()
                            WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s""",
                        (json.dumps(body, ensure_ascii=False), checksum, tenant_id, artifact_id, revision_number),
                    )
            else:
                connection.execute(
                    """INSERT INTO media_product.document_revisions
                           (tenant_id, public_artifact_id, revision, state, base_revision,
                            body_checksum, actor_public_id, generation_source)
                         VALUES (%s,%s,%s,'draft',%s,%s,%s,'manual_save')""",
                    (
                        tenant_id,
                        artifact_id,
                        revision_number,
                        current[2],
                        checksum,
                        context.user_public_id,
                    ),
                )
                if artifact[4] == "internal":
                    connection.execute(
                        """INSERT INTO media_document.revision_bodies
                           (tenant_id, public_artifact_id, revision, schema_version, body_json, body_checksum)
                         VALUES (%s,%s,%s,'media.document.body.v1',%s::jsonb,%s)""",
                        (tenant_id, artifact_id, revision_number, json.dumps(body, ensure_ascii=False), checksum),
                    )
                connection.execute(
                    """UPDATE media_product.document_artifacts
                          SET current_revision=%s, updated_at=now()
                        WHERE tenant_id=%s AND public_id=%s""",
                    (revision_number, tenant_id, artifact_id),
                )
            saved_artifact = self._artifact(connection, tenant_id, artifact_id)
            saved = self._revision(connection, tenant_id, artifact_id, revision_number, saved_artifact)
            response = self._revision_response(saved)
            self._store_idempotency(
                connection,
                tenant_id,
                operation,
                key,
                path_fingerprint,
                request_fingerprint,
                200,
                response,
            )
            replay = self._idempotent_replay(
                connection, tenant_id, operation, key, path_fingerprint, request_fingerprint
            )
            if replay != response:
                raise DocumentUnavailable("draft write readback failed")
            return response

    def _prepare_lark_save(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        artifact: Any,
        request: dict[str, Any],
        key: str,
        path_fingerprint: bytes,
        request_fingerprint: bytes,
    ) -> _PreparedLarkSave:
        if self._lark_gateway is None:
            raise DocumentUnavailable("lark document connector is unavailable")
        tenant_id = context.tenant_id
        artifact_id = artifact[0]
        revision_row = _fetchone(
            connection.execute(
                self._REVISION_QUERY, (tenant_id, artifact_id, artifact[5])
            )
        )
        if revision_row is None:
            raise DocumentNotFound()
        self._assert_expected(revision_row, request)
        if revision_row[4] not in {"draft", "ready"}:
            raise DocumentConflict("draft save requires the current draft or ready revision")
        snapshot = self._lark_snapshot(
            connection,
            tenant_id,
            artifact_id,
            revision_row[2],
            current_revision=artifact[5],
        )
        expected_remote_version = request["expectedRemoteDocumentVersion"]
        if expected_remote_version != snapshot.remote_document_version:
            raise DocumentConflict("lark remote document version differs from the expected version")

        existing = _fetchone(
            connection.execute(
                """SELECT public_sync_id, public_artifact_id, revision, state,
                          request_checksum, base_remote_document_version
                     FROM media_product.sync_batches
                    WHERE tenant_id=%s AND operation='save' AND idempotency_key=%s
                    FOR UPDATE""",
                (tenant_id, key),
            )
        )
        request_checksum = request_fingerprint.hex()
        if existing is not None:
            if (
                existing[1] != artifact_id
                or existing[4] != request_checksum
                or existing[5] != expected_remote_version
            ):
                raise DocumentConflict("idempotency key is already bound to another request")
            if existing[3] == "running":
                return _PreparedLarkSave(
                    str(existing[0]), int(existing[2]), revision_row[2],
                    expected_remote_version, request["body"], True
                )
            if existing[3] in {"failed", "conflict"}:
                raise DocumentConflict("the Lark save already reached a terminal failure")
            raise DocumentUnavailable("completed Lark save is missing its mutation receipt")

        lease_owner = secrets.token_hex(16)
        connection.execute(
            """INSERT INTO openclaw_account.if2_idempotency_receipts
               (scope_kind, scope_id, operation_id, idempotency_key,
                path_fingerprint, request_fingerprint, state, lease_owner, lease_expires_at)
             VALUES ('tenant',%s,'saveDocumentDraft',%s,%s,%s,'reserved',%s,now()+interval '10 minutes')
             ON CONFLICT (scope_kind, scope_id, operation_id, idempotency_key) DO NOTHING""",
            (tenant_id, key, path_fingerprint, request_fingerprint, lease_owner),
        )
        receipt = _fetchone(
            connection.execute(
                """SELECT path_fingerprint, request_fingerprint, state
                     FROM openclaw_account.if2_idempotency_receipts
                    WHERE scope_kind='tenant' AND scope_id=%s
                      AND operation_id='saveDocumentDraft' AND idempotency_key=%s
                    FOR UPDATE""",
                (tenant_id, key),
            )
        )
        if receipt is None:
            raise DocumentUnavailable("draft mutation reservation readback failed")
        if bytes(receipt[0]) != path_fingerprint or bytes(receipt[1]) != request_fingerprint:
            raise DocumentConflict("idempotency key is already bound to another request")
        if receipt[2] != "reserved":
            raise DocumentUnavailable("draft mutation reservation state is invalid")

        body = prepare_autosave(request["body"], "draft")["body"]
        target_revision = revision_row[2]
        if revision_row[4] == "ready":
            target_revision += 1
            connection.execute(
                """INSERT INTO media_product.document_revisions
                   (tenant_id, public_artifact_id, revision, state, base_revision,
                    body_checksum, actor_public_id, generation_source)
                 VALUES (%s,%s,%s,'generating',%s,%s,%s,'manual_save')""",
                (
                    tenant_id, artifact_id, target_revision, revision_row[2],
                    body_checksum(body), context.user_public_id,
                ),
            )
        public_sync_id = "sync_" + secrets.token_urlsafe(18).replace("-", "_")
        connection.execute(
            """INSERT INTO media_product.sync_batches
               (tenant_id, public_sync_id, state, public_artifact_id, revision,
                operation, idempotency_key, request_checksum,
                base_remote_document_version)
             VALUES (%s,%s,'running',%s,%s,'save',%s,%s,%s)""",
            (
                tenant_id, public_sync_id, artifact_id, target_revision,
                key, request_checksum, expected_remote_version,
            ),
        )
        return _PreparedLarkSave(
            public_sync_id, target_revision, revision_row[2],
            expected_remote_version, body, False
        )

    def _execute_lark_save(
        self,
        context: TenantContext,
        artifact_id: str,
        operation: str,
        key: str,
        path_fingerprint: bytes,
        request_fingerprint: bytes,
        prepared: _PreparedLarkSave,
    ) -> dict[str, Any]:
        assert self._lark_gateway is not None
        try:
            if prepared.reconcile:
                remote = self._lark_gateway.reconcile_save(
                    context.tenant_id,
                    artifact_id,
                    prepared.public_sync_id,
                    prepared.base_remote_document_version,
                )
            else:
                remote = self._lark_gateway.save_draft(
                    context.tenant_id,
                    artifact_id,
                    prepared.body,
                    prepared.base_remote_document_version,
                    prepared.public_sync_id,
                )
        except UnsupportedDocumentBlock:
            self._finish_lark_failure(
                context.tenant_id,
                artifact_id,
                prepared.public_sync_id,
                "failed",
                "unsupported_document_block",
                prepared.revision,
                prepared.prior_revision,
            )
            raise
        except DocumentConflict:
            self._finish_lark_failure(
                context.tenant_id, artifact_id, prepared.public_sync_id, "conflict",
                "remote_document_conflict", prepared.revision, prepared.prior_revision,
            )
            raise
        except Exception as exc:
            raise DocumentUnavailable(
                "Lark save outcome is unknown and requires reconciliation"
            ) from exc
        return self._finalize_lark_save(
            context,
            artifact_id,
            operation,
            key,
            path_fingerprint,
            request_fingerprint,
            prepared,
            remote,
        )

    def _finalize_lark_save(
        self,
        context: TenantContext,
        artifact_id: str,
        operation: str,
        key: str,
        path_fingerprint: bytes,
        request_fingerprint: bytes,
        prepared: _PreparedLarkSave,
        remote: LarkRevisionSnapshot,
    ) -> dict[str, Any]:
        body = validate_body(remote.body)
        blocks = self._normalized_blocks(remote.blocks)
        body_block_ids = {str(block["id"]) for block in body["blocks"]}
        if body_block_ids != {block.public_block_id for block in blocks}:
            raise DocumentConflict("lark block mapping does not cover the canonical body")
        if not remote.remote_document_version.strip():
            raise DocumentConflict("lark save returned an invalid remote document version")
        checksum = body_checksum(body)
        with self._connection_factory() as connection:
            self._lock(connection, context.tenant_id, artifact_id)
            artifact = self._artifact(
                connection, context.tenant_id, artifact_id, for_update=True
            )
            batch = _fetchone(
                connection.execute(
                    """SELECT revision, state, request_checksum,
                              base_remote_document_version
                         FROM media_product.sync_batches
                        WHERE tenant_id=%s AND public_sync_id=%s FOR UPDATE""",
                    (context.tenant_id, prepared.public_sync_id),
                )
            )
            if batch is None or batch[1] != "running":
                raise DocumentConflict("Lark save batch is no longer running")
            if (
                batch[0] != prepared.revision
                or batch[2] != request_fingerprint.hex()
                or batch[3] != prepared.base_remote_document_version
                or artifact[5] != prepared.prior_revision
            ):
                raise DocumentConflict("Lark save baseline changed before finalization")
            binding = self._lark_snapshot(
                connection,
                context.tenant_id,
                artifact_id,
                prepared.prior_revision,
                current_revision=artifact[5],
            )
            if binding.remote_document_version != prepared.base_remote_document_version:
                raise DocumentConflict("Lark binding changed before finalization")
            revision = _fetchone(
                connection.execute(
                    """SELECT state FROM media_product.document_revisions
                        WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s
                        FOR UPDATE""",
                    (context.tenant_id, artifact_id, prepared.revision),
                )
            )
            expected_state = "draft" if prepared.revision == prepared.prior_revision else "generating"
            if revision is None or revision[0] != expected_state:
                raise DocumentConflict("Lark target revision changed before finalization")
            for block in blocks:
                connection.execute(
                    """INSERT INTO media_product.lark_document_block_mappings
                       (tenant_id, public_sync_id, public_block_id, remote_block_id,
                        block_checksum, is_protected, protection_reason)
                     VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        context.tenant_id, prepared.public_sync_id,
                        block.public_block_id, block.remote_block_id,
                        block.block_checksum, block.is_protected,
                        block.protection_reason,
                    ),
                )
            connection.execute(
                """UPDATE media_product.document_revisions
                      SET state='draft', body_checksum=%s, actor_public_id=%s,
                          generation_source='manual_save', updated_at=now()
                    WHERE tenant_id=%s AND public_artifact_id=%s AND revision=%s""",
                (
                    checksum, context.user_public_id, context.tenant_id,
                    artifact_id, prepared.revision,
                ),
            )
            connection.execute(
                """UPDATE media_product.sync_batches
                      SET state='succeeded', remote_document_version=%s,
                          body_checksum=%s, block_count=%s,
                          protected_block_count=%s, completed_at=now(), updated_at=now()
                    WHERE tenant_id=%s AND public_sync_id=%s AND state='running'""",
                (
                    remote.remote_document_version, checksum, len(blocks),
                    sum(block.is_protected for block in blocks),
                    context.tenant_id, prepared.public_sync_id,
                ),
            )
            if prepared.revision != prepared.prior_revision:
                connection.execute(
                    """UPDATE media_product.document_artifacts
                          SET current_revision=%s, updated_at=now()
                        WHERE tenant_id=%s AND public_id=%s""",
                    (prepared.revision, context.tenant_id, artifact_id),
                )
            connection.execute(
                """INSERT INTO media_product.lark_document_bindings
                   (tenant_id, public_artifact_id, public_sync_id)
                 VALUES (%s,%s,%s)
                 ON CONFLICT (tenant_id, public_artifact_id) DO UPDATE
                   SET public_sync_id=EXCLUDED.public_sync_id, updated_at=now()""",
                (context.tenant_id, artifact_id, prepared.public_sync_id),
            )
            saved_row = _fetchone(
                connection.execute(
                    self._REVISION_QUERY,
                    (context.tenant_id, artifact_id, prepared.revision),
                )
            )
            if saved_row is None:
                raise DocumentUnavailable("draft revision readback failed")
            saved = (
                *saved_row[:6], body, saved_row[7], saved_row[8],
                remote.remote_document_version,
                {block.public_block_id for block in blocks if block.is_protected},
                artifact_id,
            )
            response = self._revision_response(saved)
            connection.execute(
                """UPDATE openclaw_account.if2_idempotency_receipts
                      SET state='completed', response_status=200,
                          response_json=%s::jsonb, completed_at=now(),
                          lease_owner=NULL, lease_expires_at=NULL
                    WHERE scope_kind='tenant' AND scope_id=%s
                      AND operation_id=%s AND idempotency_key=%s
                      AND path_fingerprint=%s AND request_fingerprint=%s
                      AND state='reserved'""",
                (
                    json.dumps(response, ensure_ascii=False), context.tenant_id,
                    operation, key, path_fingerprint, request_fingerprint,
                ),
            )
            replay = self._idempotent_replay(
                connection, context.tenant_id, operation, key,
                path_fingerprint, request_fingerprint,
            )
            if replay != response:
                raise DocumentUnavailable("draft write readback failed")
            return response

    def _finish_lark_failure(
        self,
        tenant_id: str,
        artifact_id: str,
        public_sync_id: str,
        state: str,
        error_code: str,
        revision: int,
        prior_revision: int,
    ) -> None:
        with self._connection_factory() as connection:
            self._lock(connection, tenant_id, artifact_id)
            connection.execute(
                """UPDATE media_product.sync_batches
                      SET state=%s, error_code=%s, completed_at=now(), updated_at=now()
                    WHERE tenant_id=%s AND public_sync_id=%s AND state='running'""",
                (state, error_code, tenant_id, public_sync_id),
            )
            if revision != prior_revision:
                connection.execute(
                    """UPDATE media_product.document_revisions
                          SET state=%s, updated_at=now()
                        WHERE tenant_id=%s AND public_artifact_id=%s
                          AND revision=%s AND state='generating'""",
                    (state, tenant_id, artifact_id, revision),
                )
            connection.execute(
                """UPDATE openclaw_account.if2_idempotency_receipts
                      SET state='failed', lease_owner=NULL, lease_expires_at=NULL
                    WHERE scope_kind='tenant' AND scope_id=%s
                      AND operation_id='saveDocumentDraft'
                      AND idempotency_key=(
                          SELECT idempotency_key FROM media_product.sync_batches
                           WHERE tenant_id=%s AND public_sync_id=%s
                      ) AND state='reserved'""",
                (tenant_id, tenant_id, public_sync_id),
            )

    def get_document_revision(
        self, context: TenantContext, public_artifact_id: str, revision: int
    ) -> dict[str, Any]:
        tenant_id = self._tenant(context)
        artifact_id = _public_id(public_artifact_id, "publicArtifactId")
        number = _positive_revision(revision)
        with self._connection_factory() as connection:
            artifact = self._artifact(connection, tenant_id, artifact_id)
            row = self._revision(connection, tenant_id, artifact_id, number, artifact)
        return self._revision_response(row)

    def create_document_export(
        self,
        context: TenantContext,
        public_artifact_id: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        tenant_id = self._tenant(context)
        artifact_id = _public_id(public_artifact_id, "publicArtifactId")
        key = _idempotency_key(idempotency_key)
        normalized = self._export_request(request)
        operation = "createDocumentExport"
        path_fingerprint = _path_fingerprint(operation, artifact_id)
        request_fingerprint = _request_fingerprint(normalized)
        identity = hashlib.sha256(
            json.dumps(
                [artifact_id, normalized], ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        ).hexdigest()
        with self._connection_factory() as connection:
            self._lock(connection, tenant_id, artifact_id)
            replay = self._idempotent_replay(
                connection, tenant_id, operation, key, path_fingerprint, request_fingerprint
            )
            if replay is not None:
                return replay
            artifact = self._artifact(connection, tenant_id, artifact_id)
            revision = self._revision(connection, tenant_id, artifact_id, normalized["revision"], artifact)
            if revision[4] != "ready":
                raise DocumentConflict("exports require a ready revision")
            protected_ids = revision[10]
            try:
                source_checksum = prepare_export(
                    revision[6], revision[4], protected_block_ids=protected_ids
                )["sourceBodyChecksum"]
            except MediaBusinessError as exc:
                if getattr(exc, "block_ids", ()): 
                    raise UnsupportedDocumentBlock(set(exc.block_ids)) from exc
                raise DocumentConflict(str(exc)) from exc
            existing = _fetchone(connection.execute(
                """SELECT public_export_id FROM media_document.exports
                     WHERE tenant_id=%s AND idempotency_identity=%s""", (tenant_id, identity)
            ))
            if existing is None:
                public_export_id = "dexp_" + secrets.token_urlsafe(18).replace("-", "_")
                connection.execute(
                    """INSERT INTO media_document.exports
                       (tenant_id, public_export_id, public_artifact_id, revision, format, state,
                        template_version, renderer_version, idempotency_identity, source_body_checksum)
                     VALUES (%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s)
                     ON CONFLICT (tenant_id, idempotency_identity) DO NOTHING""",
                    (tenant_id, public_export_id, artifact_id, revision[2], normalized["format"],
                     normalized["templateVersion"], normalized["rendererVersion"], identity,
                     source_checksum),
                )
                existing = _fetchone(connection.execute(
                    """SELECT public_export_id FROM media_document.exports
                         WHERE tenant_id=%s AND idempotency_identity=%s""", (tenant_id, identity)
                ))
            if existing is None:
                raise DocumentUnavailable("export write readback failed")
            row = self._export(connection, tenant_id, str(existing[0]))
            response = self._export_response(row)
            self._store_idempotency(
                connection,
                tenant_id,
                operation,
                key,
                path_fingerprint,
                request_fingerprint,
                202,
                response,
            )
            replay = self._idempotent_replay(
                connection, tenant_id, operation, key, path_fingerprint, request_fingerprint
            )
            if replay != response:
                raise DocumentUnavailable("export write readback failed")
            return response

    def get_document_export(self, context: TenantContext, public_export_id: str) -> dict[str, Any]:
        tenant_id = self._tenant(context)
        export_id = _public_id(public_export_id, "publicExportId")
        with self._connection_factory() as connection:
            row = self._export(connection, tenant_id, export_id)
        return self._export_response(row)

    def get_document_export_download(
        self, context: TenantContext, public_export_id: str
    ) -> dict[str, Any]:
        tenant_id = self._tenant(context)
        export_id = _public_id(public_export_id, "publicExportId")
        with self._connection_factory() as connection:
            row = self._export(connection, tenant_id, export_id)
        if row[4] != "ready" or not row[8] or not row[9]:
            raise DocumentConflict("download is available only for a ready export")
        if self._download_signer is None:
            raise DocumentUnavailable("controlled download signer is unavailable")
        url, expires_at = self._download_signer.create_download_url(row[9], expires_in_seconds=300)
        return public_projection({
            "schemaVersion": SCHEMA_VERSION,
            "revision": row[2],
            "data": {"publicExportId": row[0], "format": row[3], "downloadUrl": url,
                     "expiresAt": expires_at, "contentChecksum": row[8]},
        })

    @staticmethod
    def _tenant(context: TenantContext) -> str:
        require_context(context)
        return context.tenant_id

    @staticmethod
    def _lock(connection: DatabaseConnection, tenant_id: str, artifact_id: str) -> None:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"if2:{tenant_id}:{artifact_id}",))

    def _artifact(self, connection: DatabaseConnection, tenant_id: str, artifact_id: str, *, for_update: bool = False) -> Any:
        query = self._ARTIFACT_QUERY + (" FOR UPDATE" if for_update else "")
        row = _fetchone(connection.execute(query, (tenant_id, artifact_id)))
        if row is None:
            raise DocumentNotFound()
        return row

    def _revision(self, connection: DatabaseConnection, tenant_id: str, artifact_id: str, revision: int, artifact: Any) -> Any:
        row = _fetchone(connection.execute(self._REVISION_QUERY, (tenant_id, artifact_id, revision)))
        if row is None:
            raise DocumentNotFound()
        if artifact[4] == "lark":
            snapshot = self._lark_snapshot(
                connection,
                tenant_id,
                artifact_id,
                revision,
                current_revision=artifact[5],
            )
            if row[6] is not None:
                body = validate_body(_json(row[6]))
                checksum = body_checksum(body)
                if checksum != row[5] or checksum != snapshot.body_checksum:
                    raise DocumentConflict("lark read mirror checksum differs from the indexed revision")
                return (
                    *row[:6],
                    body,
                    row[7],
                    row[8],
                    snapshot.remote_document_version,
                    snapshot.protected_block_ids,
                    artifact_id,
                )
            if self._lark_gateway is None:
                raise DocumentUnavailable("lark document connector is unavailable")
            remote = self._lark_gateway.read_revision(
                tenant_id, artifact_id, snapshot.remote_document_version
            )
            body = validate_body(remote.body)
            checksum = body_checksum(body)
            if checksum != row[5] or checksum != snapshot.body_checksum:
                raise DocumentConflict("lark body checksum readback differs from the indexed revision")
            if remote.remote_document_version != snapshot.remote_document_version:
                raise DocumentConflict("lark remote document version changed")
            remote_blocks = self._normalized_blocks(remote.blocks)
            if remote_blocks != snapshot.blocks:
                raise DocumentConflict("lark block mapping readback changed")
            body_block_ids = {str(block["id"]) for block in body["blocks"]}
            mapped_block_ids = {block.public_block_id for block in remote_blocks}
            if body_block_ids != mapped_block_ids:
                raise DocumentConflict("lark block mapping does not cover the canonical body")
            return (
                *row[:6],
                body,
                row[7],
                row[8],
                snapshot.remote_document_version,
                snapshot.protected_block_ids,
                artifact_id,
            )
        if row[6] is None:
            raise DocumentUnavailable("canonical revision body is missing")
        body = validate_body(_json(row[6]))
        if body_checksum(body) != row[5]:
            raise DocumentUnavailable("canonical revision body checksum mismatch")
        return (*row[:6], body, row[7], row[8], None, set(), artifact_id)

    def _lark_snapshot(
        self,
        connection: DatabaseConnection,
        tenant_id: str,
        artifact_id: str,
        revision: int,
        *,
        current_revision: int,
    ) -> _StoredLarkSnapshot:
        query = (
            self._CURRENT_LARK_SNAPSHOT_QUERY
            if revision == current_revision
            else self._HISTORICAL_LARK_SNAPSHOT_QUERY
        )
        row = _fetchone(connection.execute(query, (tenant_id, artifact_id, revision)))
        if row is None:
            raise DocumentUnavailable("lark revision has no complete successful sync snapshot")
        blocks = self._stored_blocks(row[5])
        if len(blocks) != row[3]:
            raise DocumentUnavailable("lark sync block inventory is incomplete")
        protected_count = sum(block.is_protected for block in blocks)
        if protected_count != row[4]:
            raise DocumentUnavailable("lark protected block inventory is incomplete")
        return _StoredLarkSnapshot(str(row[0]), str(row[1]), str(row[2]), blocks)

    @staticmethod
    def _stored_blocks(value: Any) -> tuple[LarkBlockSnapshot, ...]:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, list):
            raise DocumentUnavailable("stored Lark block mapping JSON is invalid")
        try:
            blocks = tuple(
                LarkBlockSnapshot(
                    public_block_id=str(item["publicBlockId"]),
                    remote_block_id=str(item["remoteBlockId"]),
                    block_checksum=str(item["blockChecksum"]),
                    is_protected=item["isProtected"],
                    protection_reason=item["protectionReason"],
                )
                for item in value
            )
        except (KeyError, TypeError) as exc:
            raise DocumentUnavailable("stored Lark block mapping JSON is invalid") from exc
        return DocumentsService._normalized_blocks(blocks)

    @staticmethod
    def _normalized_blocks(
        blocks: tuple[LarkBlockSnapshot, ...],
    ) -> tuple[LarkBlockSnapshot, ...]:
        public_ids: set[str] = set()
        remote_ids: set[str] = set()
        normalized: list[LarkBlockSnapshot] = []
        for block in blocks:
            if not isinstance(block, LarkBlockSnapshot):
                raise DocumentConflict("lark gateway returned an invalid block mapping")
            if (
                not block.public_block_id
                or not block.remote_block_id
                or not _CHECKSUM.fullmatch(block.block_checksum)
                or not isinstance(block.is_protected, bool)
                or (block.is_protected != bool(block.protection_reason))
                or block.public_block_id in public_ids
                or block.remote_block_id in remote_ids
            ):
                raise DocumentConflict("lark gateway returned an invalid block mapping")
            public_ids.add(block.public_block_id)
            remote_ids.add(block.remote_block_id)
            normalized.append(block)
        return tuple(sorted(normalized, key=lambda item: item.public_block_id))

    @staticmethod
    def _assert_expected(current: Any, request: dict[str, Any]) -> None:
        if current[2] != request["expectedRevision"]:
            raise DocumentConflict()
        if request["expectedBodyChecksum"] is not None and current[5] != request["expectedBodyChecksum"]:
            raise DocumentConflict()

    @staticmethod
    def _draft_request(request: Mapping[str, Any]) -> dict[str, Any]:
        expected = {"expectedRevision", "expectedBodyChecksum", "expectedRemoteDocumentVersion", "body"}
        if set(request) != expected:
            raise DocumentInvalidRequest("draft request fields do not match IF2")
        revision = request["expectedRevision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise DocumentInvalidRequest("expectedRevision is invalid", field="expectedRevision")
        remote = request["expectedRemoteDocumentVersion"]
        if remote is not None and (not isinstance(remote, str) or not remote.strip()):
            raise DocumentInvalidRequest("expectedRemoteDocumentVersion is invalid", field="expectedRemoteDocumentVersion")
        return {"expectedRevision": revision,
                "expectedBodyChecksum": _optional_checksum(request["expectedBodyChecksum"], "expectedBodyChecksum"),
                "expectedRemoteDocumentVersion": remote,
                "body": validate_body(request["body"])}

    @staticmethod
    def _export_request(request: Mapping[str, Any]) -> dict[str, Any]:
        expected = {"revision", "format", "templateVersion", "rendererVersion"}
        if set(request) != expected:
            raise DocumentInvalidRequest("export request fields do not match IF2")
        revision = _positive_revision(request["revision"])
        export_format = request["format"]
        if export_format not in _FORMATS:
            raise DocumentInvalidRequest("format must be docx or pdf", field="format")
        for field in ("templateVersion", "rendererVersion"):
            if not isinstance(request[field], str) or not request[field].strip():
                raise DocumentInvalidRequest(f"{field} is invalid", field=field)
        return {"revision": revision, "format": export_format,
                "templateVersion": request["templateVersion"].strip(),
                "rendererVersion": request["rendererVersion"].strip()}

    @staticmethod
    def _idempotent_replay(
        connection: DatabaseConnection,
        tenant_id: str,
        operation: str,
        key: str,
        path_fingerprint: bytes,
        request_fingerprint: bytes,
    ) -> dict[str, Any] | None:
        row = _fetchone(connection.execute(
            """SELECT path_fingerprint, request_fingerprint, response_json, state
                 FROM openclaw_account.if2_idempotency_receipts
                WHERE scope_kind='tenant' AND scope_id=%s
                  AND operation_id=%s AND idempotency_key=%s""",
            (tenant_id, operation, key),
        ))
        if row is None:
            return None
        if bytes(row[0]) != path_fingerprint or bytes(row[1]) != request_fingerprint:
            raise DocumentConflict("idempotency key is already bound to another request")
        if row[3] == "reserved":
            return None
        if row[3] != "completed" or row[2] is None:
            raise DocumentConflict("idempotency request is still in progress")
        return _json(row[2])

    @staticmethod
    def _store_idempotency(
        connection: DatabaseConnection,
        tenant_id: str,
        operation: str,
        key: str,
        path_fingerprint: bytes,
        request_fingerprint: bytes,
        response_status: int,
        response: dict[str, Any],
    ) -> None:
        connection.execute(
            """INSERT INTO openclaw_account.if2_idempotency_receipts
               (scope_kind, scope_id, operation_id, idempotency_key,
                path_fingerprint, request_fingerprint, state,
                response_status, response_json, completed_at)
             VALUES ('tenant',%s,%s,%s,%s,%s,'completed',%s,%s::jsonb,now())
             ON CONFLICT (scope_kind, scope_id, operation_id, idempotency_key) DO NOTHING""",
            (
                tenant_id,
                operation,
                key,
                path_fingerprint,
                request_fingerprint,
                response_status,
                json.dumps(response, ensure_ascii=False),
            ),
        )

    def _export(self, connection: DatabaseConnection, tenant_id: str, export_id: str) -> Any:
        row = _fetchone(connection.execute(self._EXPORT_QUERY, (tenant_id, export_id)))
        if row is None:
            raise DocumentNotFound()
        return row

    @staticmethod
    def _artifact_record(row: Any) -> dict[str, Any]:
        return {"publicArtifactId": row[0], "publicProjectId": row[1], "artifactKind": row[2],
                "workspaceMode": row[3], "bodyAuthority": row[4], "currentRevision": row[5],
                "updatedAt": _timestamp(row[6])}

    @staticmethod
    def _revision_record(row: Any) -> dict[str, Any]:
        return {"publicArtifactId": row[11], "artifactKind": row[0], "bodyAuthority": row[1],
                "revision": row[2], "baseRevision": row[3], "state": row[4],
                "bodyChecksum": row[5], "remoteDocumentVersion": row[9], "body": row[6],
                "createdAt": _timestamp(row[7]), "updatedAt": _timestamp(row[8])}

    def _body_response(self, artifact: Any, revision: Any) -> dict[str, Any]:
        record = self._revision_record(revision)
        record["publicArtifactId"] = artifact[0]
        return public_projection({"schemaVersion": SCHEMA_VERSION, "revision": revision[2],
                                  "data": {"artifact": self._artifact_record(artifact), "revision": record}})

    def _revision_response(self, revision: Any) -> dict[str, Any]:
        record = self._revision_record(revision)
        return public_projection({"schemaVersion": SCHEMA_VERSION, "revision": revision[2], "data": record})

    @staticmethod
    def _export_response(row: Any) -> dict[str, Any]:
        record = {"publicExportId": row[0], "publicArtifactId": row[1], "revision": row[2],
                  "format": row[3], "state": row[4], "templateVersion": row[5],
                  "rendererVersion": row[6], "sourceBodyChecksum": row[7],
                  "contentChecksum": row[8], "createdAt": _timestamp(row[10]),
                  "updatedAt": _timestamp(row[11])}
        return public_projection({"schemaVersion": SCHEMA_VERSION, "revision": row[2], "data": record})
