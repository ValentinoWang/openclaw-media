"""Organization-only Stage-2 document and readback boundary.

All transport work is injected through ``ExternalDocumentWriter``. The module
never obtains credentials or chooses a tenant/Binding on behalf of a caller.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from openclaw_app.services.stage2_external_document import (
    BindingIdentity,
    ExternalDocumentAdapter,
    ExternalDocumentError,
    ExternalDocumentWriter,
    OrganizationWriteRequest,
)


SCHEMA_VERSION = "stage2.organization_pipeline.v1"
ORGANIZATION_MODE = "organization_lark/lark"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class OrganizationPipelineError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class IdempotencyConflict(OrganizationPipelineError):
    def __init__(self) -> None:
        super().__init__("idempotency_conflict", "idempotency key was reused with another request")


class OrganizationStoreConflict(OrganizationPipelineError):
    """A durable organization state transition could not be applied safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


def _text(value: Any, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise OrganizationPipelineError("invalid_request", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise OrganizationPipelineError("invalid_request", f"{label} is invalid")
    return normalized


def _lookup(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _content_digest(value: Any) -> str:
    normalized = _text(value, "content_digest", 80)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise OrganizationPipelineError("invalid_request", "content_digest must be a sha256 digest")
    return normalized


def _assert_org_context(context: Any, binding: BindingIdentity) -> str:
    workspace = _lookup(context, "workspace_mode", "workspaceMode", "workspace")
    authority = _lookup(context, "body_authority", "bodyAuthority", "authority")
    mode = _lookup(context, "authority_mode", "authorityMode") or f"{workspace}/{authority}"
    if mode != ORGANIZATION_MODE:
        raise OrganizationPipelineError("organization_context_required", "organization_lark/lark context is required")
    tenant_id = _text(_lookup(context, "tenant_id", "tenantId"), "tenant_id")
    if tenant_id != binding.tenant_id:
        raise OrganizationPipelineError("binding_tenant_mismatch", "Binding tenant does not match context")
    return tenant_id


def _assert_browser_claims(claims: Mapping[str, Any] | None) -> None:
    if claims is None:
        return
    if not isinstance(claims, Mapping):
        raise OrganizationPipelineError("invalid_request", "browser claims must be an object")
    forbidden = {
        "tenantId", "tenant_id", "bindingId", "binding_id", "bindingGeneration", "binding_generation",
        "remoteRef", "remote_ref", "credentials", "larkAppId", "larkSpaceId",
    }.intersection(claims)
    if forbidden:
        raise OrganizationPipelineError("authority_override_forbidden", "browser claims cannot choose organization identity")


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: Mapping[str, Any]


class OrganizationContentStore(Protocol):
    def get_replay(self, key: str) -> _Stored | None: ...

    def save_replay(self, key: str, fingerprint: str, result: Mapping[str, Any]) -> None: ...

    def save_artifact_and_replay(
        self,
        artifact: Mapping[str, Any],
        *,
        replay_key: str,
        fingerprint: str,
    ) -> Mapping[str, Any]: ...

    def get_artifact(self, artifact_ref: str, *, tenant_id: str) -> Mapping[str, Any] | None: ...

    def update_artifact(self, artifact: Mapping[str, Any]) -> None: ...


class InMemoryOrganizationContentStore:
    """Explicit process-local store used by focused tests and local callers."""

    def __init__(self) -> None:
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._replays: dict[str, _Stored] = {}
        self._lock = threading.RLock()

    def get_replay(self, key: str) -> _Stored | None:
        with self._lock:
            value = self._replays.get(key)
            return copy.deepcopy(value) if value is not None else None

    def save_replay(self, key: str, fingerprint: str, result: Mapping[str, Any]) -> None:
        with self._lock:
            previous = self._replays.get(key)
            if previous is not None and previous.fingerprint != fingerprint:
                raise OrganizationStoreConflict("idempotency_conflict", "idempotency key was reused with another request")
            if previous is None:
                self._replays[key] = _Stored(fingerprint, copy.deepcopy(dict(result)))

    def save_artifact_and_replay(
        self,
        artifact: Mapping[str, Any],
        *,
        replay_key: str,
        fingerprint: str,
    ) -> Mapping[str, Any]:
        with self._lock:
            previous = self._replays.get(replay_key)
            if previous is not None:
                if previous.fingerprint != fingerprint:
                    raise OrganizationStoreConflict("idempotency_conflict", "idempotency key was reused with another request")
                return copy.deepcopy(dict(previous.result))
            artifact_ref = str(artifact["artifactRef"])
            existing = self._artifacts.get(artifact_ref)
            if existing is not None and existing != dict(artifact):
                raise OrganizationStoreConflict("artifact_identity_conflict", "organization artifact identity already exists")
            stored = copy.deepcopy(dict(existing or artifact))
            self._artifacts[artifact_ref] = stored
            self._replays[replay_key] = _Stored(fingerprint, copy.deepcopy(stored))
            return copy.deepcopy(stored)

    def get_artifact(self, artifact_ref: str, *, tenant_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            value = self._artifacts.get(artifact_ref)
            if value is None or value.get("tenantId") != tenant_id:
                return None
            return copy.deepcopy(value)

    def update_artifact(self, artifact: Mapping[str, Any]) -> None:
        with self._lock:
            artifact_ref = str(artifact["artifactRef"])
            if artifact_ref not in self._artifacts:
                raise OrganizationStoreConflict("artifact_not_found", "organization artifact does not exist")
            self._artifacts[artifact_ref] = copy.deepcopy(dict(artifact))


class SQLiteOrganizationContentStore:
    """Restart-safe organization artifact, mirror, and replay storage."""

    _SCHEMA_VERSION = 1
    _REQUIRED_COLUMNS = {
        "organization_store_meta": {"schema_version"},
        "organization_artifacts": {
            "artifact_ref", "tenant_id", "binding_id", "binding_generation", "artifact_json"
        },
        "organization_replays": {"replay_key", "fingerprint", "result_json"},
    }

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path == ":memory:":
            raise OrganizationStoreConflict("volatile_store_forbidden", "organization state must be file-backed")
        path_object = Path(self.path).expanduser().resolve()
        path_object.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path_object.parent, 0o700)
        except OSError:
            pass
        self._lock = threading.RLock()
        self._initialize()
        try:
            os.chmod(path_object, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def _connection_scope(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _decode(raw: str, label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise OrganizationStoreConflict("state_corrupt", f"organization {label} JSON is corrupt") from exc
        if not isinstance(value, dict):
            raise OrganizationStoreConflict("state_corrupt", f"organization {label} must be an object")
        return value

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        for table, required in self._REQUIRED_COLUMNS.items():
            columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
            if not required.issubset(columns):
                missing = ",".join(sorted(required - columns))
                raise OrganizationStoreConflict("state_schema_invalid", f"organization store schema is missing {table} columns: {missing}")

    def _initialize(self) -> None:
        with self._lock, self._connection_scope() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS organization_store_meta (schema_version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS organization_artifacts (
                    artifact_ref TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    binding_id TEXT NOT NULL,
                    binding_generation INTEGER NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS organization_replays (
                    replay_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            rows = connection.execute("SELECT schema_version FROM organization_store_meta").fetchall()
            if not rows:
                connection.execute("INSERT INTO organization_store_meta(schema_version) VALUES (?)", (self._SCHEMA_VERSION,))
            elif len(rows) != 1 or int(rows[0][0]) != self._SCHEMA_VERSION:
                raise OrganizationStoreConflict("state_schema_unsupported", "organization store schema version is unsupported")
            self._validate_schema(connection)

    def get_replay(self, key: str) -> _Stored | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute("SELECT fingerprint, result_json FROM organization_replays WHERE replay_key = ?", (key,)).fetchone()
        if row is None:
            return None
        return _Stored(str(row["fingerprint"]), self._decode(str(row["result_json"]), "replay"))

    def save_replay(self, key: str, fingerprint: str, result: Mapping[str, Any]) -> None:
        payload = json.dumps(dict(result), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT fingerprint FROM organization_replays WHERE replay_key = ?", (key,)).fetchone()
            if row is not None:
                if str(row["fingerprint"]) != fingerprint:
                    connection.rollback()
                    raise OrganizationStoreConflict("idempotency_conflict", "idempotency key was reused with another request")
                connection.commit()
                return
            connection.execute("INSERT INTO organization_replays(replay_key, fingerprint, result_json) VALUES (?, ?, ?)", (key, fingerprint, payload))
            connection.commit()

    def save_artifact_and_replay(self, artifact: Mapping[str, Any], *, replay_key: str, fingerprint: str) -> Mapping[str, Any]:
        artifact_ref = str(artifact["artifactRef"])
        payload = json.dumps(dict(artifact), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute("SELECT fingerprint, result_json FROM organization_replays WHERE replay_key = ?", (replay_key,)).fetchone()
            if replay is not None:
                if str(replay["fingerprint"]) != fingerprint:
                    connection.rollback()
                    raise OrganizationStoreConflict("idempotency_conflict", "idempotency key was reused with another request")
                connection.commit()
                return self._decode(str(replay["result_json"]), "replay")
            existing = connection.execute("SELECT artifact_json FROM organization_artifacts WHERE artifact_ref = ?", (artifact_ref,)).fetchone()
            if existing is not None and str(existing["artifact_json"]) != payload:
                connection.rollback()
                raise OrganizationStoreConflict("artifact_identity_conflict", "organization artifact identity already exists")
            if existing is None:
                connection.execute(
                    "INSERT INTO organization_artifacts(artifact_ref, tenant_id, binding_id, binding_generation, artifact_json) VALUES (?, ?, ?, ?, ?)",
                    (artifact_ref, str(artifact["tenantId"]), str(artifact["bindingId"]), int(artifact["bindingGeneration"]), payload),
                )
            connection.execute("INSERT INTO organization_replays(replay_key, fingerprint, result_json) VALUES (?, ?, ?)", (replay_key, fingerprint, payload))
            connection.commit()
        return copy.deepcopy(dict(artifact))

    def get_artifact(self, artifact_ref: str, *, tenant_id: str) -> Mapping[str, Any] | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute("SELECT artifact_json FROM organization_artifacts WHERE artifact_ref = ? AND tenant_id = ?", (artifact_ref, tenant_id)).fetchone()
        return None if row is None else self._decode(str(row["artifact_json"]), "artifact")

    def update_artifact(self, artifact: Mapping[str, Any]) -> None:
        artifact_ref = str(artifact["artifactRef"])
        payload = json.dumps(dict(artifact), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT 1 FROM organization_artifacts WHERE artifact_ref = ?", (artifact_ref,)).fetchone()
            if row is None:
                connection.rollback()
                raise OrganizationStoreConflict("artifact_not_found", "organization artifact does not exist")
            connection.execute(
                "UPDATE organization_artifacts SET tenant_id = ?, binding_id = ?, binding_generation = ?, artifact_json = ? WHERE artifact_ref = ?",
                (str(artifact["tenantId"]), str(artifact["bindingId"]), int(artifact["bindingGeneration"]), payload, artifact_ref),
            )
            connection.commit()


class OrganizationContentPipeline:
    def __init__(
        self,
        *,
        document_writer: ExternalDocumentWriter | None = None,
        store: OrganizationContentStore | None = None,
    ) -> None:
        self._document_writer = document_writer or ExternalDocumentWriter()
        self._store = store or InMemoryOrganizationContentStore()
        self._lock = threading.RLock()

    def build_scope(
        self,
        context: Any,
        binding: BindingIdentity,
        sources: Iterable[Mapping[str, Any]],
        *,
        browser_claims: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        _assert_browser_claims(browser_claims)
        if not isinstance(binding, BindingIdentity):
            raise OrganizationPipelineError("binding_required", "active Binding identity is required")
        if binding.status != "active":
            raise OrganizationPipelineError("binding_inactive", "organization Binding is inactive")
        tenant_id = _assert_org_context(context, binding)
        normalized: list[dict[str, Any]] = []
        for raw in sources:
            if not isinstance(raw, Mapping):
                raise OrganizationPipelineError("invalid_source", "organization source must be an object")
            source_tenant = _text(_lookup(raw, "tenant_id", "tenantId"), "source tenant")
            if source_tenant != tenant_id:
                raise OrganizationPipelineError("source_tenant_mismatch", "organization source belongs to another tenant")
            if _lookup(raw, "workspace_mode", "workspaceMode", "workspace") != "organization_lark":
                raise OrganizationPipelineError("personal_source_forbidden", "organization scope cannot read personal sources")
            if _lookup(raw, "body_authority", "bodyAuthority", "authority") != "lark":
                raise OrganizationPipelineError("source_authority_mismatch", "organization source must use Lark authority")
            source_binding_id = _lookup(raw, "binding_id", "bindingId")
            source_generation = _lookup(raw, "binding_generation", "bindingGeneration")
            if source_binding_id != binding.binding_id or source_generation != binding.binding_generation:
                raise OrganizationPipelineError("binding_generation_mismatch", "source Binding does not match active Binding")
            source_id = _text(_lookup(raw, "source_id", "sourceId", "id"), "source_id")
            source_kind = _text(_lookup(raw, "source_kind", "sourceKind", "kind"), "source_kind", 160)
            payload = _lookup(raw, "payload", "data", default={})
            if not isinstance(payload, Mapping):
                raise OrganizationPipelineError("invalid_source", "organization source payload must be an object")
            row = {
                "sourceId": source_id,
                "sourceKind": source_kind,
                "tenantId": tenant_id,
                "bindingId": binding.binding_id,
                "bindingGeneration": binding.binding_generation,
                "payload": copy.deepcopy(dict(payload)),
            }
            row["sourceDigest"] = _digest(row)
            normalized.append(row)
        normalized.sort(key=lambda item: (item["sourceKind"], item["sourceId"]))
        scope = {
            "schemaVersion": SCHEMA_VERSION,
            "tenantId": tenant_id,
            "authorityMode": ORGANIZATION_MODE,
            "bindingId": binding.binding_id,
            "bindingGeneration": binding.binding_generation,
            "sources": normalized,
        }
        scope["scopeDigest"] = _digest(scope)
        return scope

    def write_document(
        self,
        context: Any,
        scope: Mapping[str, Any],
        *,
        title: str,
        body: str,
        idempotency_key: str,
        binding: BindingIdentity,
        adapter: ExternalDocumentAdapter,
        credential_generation: str,
    ) -> dict[str, Any]:
        tenant_id = _assert_org_context(context, binding)
        if scope.get("tenantId") != tenant_id or scope.get("bindingId") != binding.binding_id or scope.get("bindingGeneration") != binding.binding_generation:
            raise OrganizationPipelineError("scope_binding_mismatch", "organization scope does not match active Binding")
        content = {"title": _text(title, "title", 240), "body": _text(body, "body"), "format": "markdown"}
        normalized_credential_generation = _text(credential_generation, "credential_generation", 160)
        digest = _digest(content)
        key = _text(idempotency_key, "idempotency_key", 256)
        fingerprint = _digest({"tenantId": tenant_id, "bindingId": binding.binding_id, "bindingGeneration": binding.binding_generation, "digest": digest})
        replay_key = f"write:{tenant_id}:{binding.binding_id}:{key}"
        with self._lock:
            previous = self._store.get_replay(replay_key)
            if previous is not None:
                if previous.fingerprint != fingerprint:
                    raise IdempotencyConflict()
                replay = copy.deepcopy(dict(previous.result))
                replay["replayed"] = True
                return replay
            request = OrganizationWriteRequest(
                binding=binding,
                idempotency_key=key,
                content_digest=digest,
                title=content["title"],
                body=content["body"],
                content_format=content["format"],
            )
            try:
                external = self._document_writer.write(request, adapter)
            except ExternalDocumentError as exc:
                raise OrganizationPipelineError(exc.code, exc.message) from exc
            if external.status != "written" or not external.remote_ref or not external.remote_revision:
                result = {
                    "schemaVersion": SCHEMA_VERSION,
                    "status": "needs_attention",
                    "publishable": False,
                    "tenantId": tenant_id,
                    "bindingId": binding.binding_id,
                    "bindingGeneration": binding.binding_generation,
                    "remoteRef": external.remote_ref,
                    "remoteRevision": external.remote_revision,
                    "errorCode": external.error_code or "external_write_needs_attention",
                }
                self._store.save_replay(replay_key, fingerprint, result)
                return result
            artifact_ref = "org-artifact-" + digest[7:31]
            artifact = {
                "schemaVersion": SCHEMA_VERSION,
                "status": "registered",
                "publishable": False,
                "editable": False,
                "tenantId": tenant_id,
                "bindingId": binding.binding_id,
                "bindingGeneration": binding.binding_generation,
                "credentialGeneration": normalized_credential_generation,
                "artifactRef": artifact_ref,
                "remoteRef": external.remote_ref,
                "remoteRevision": external.remote_revision,
                "contentDigest": digest,
                "scopeDigest": scope["scopeDigest"],
                "mirror": None,
                "replayed": False,
            }
            try:
                return dict(self._store.save_artifact_and_replay(artifact, replay_key=replay_key, fingerprint=fingerprint))
            except OrganizationStoreConflict as exc:
                if exc.code == "idempotency_conflict":
                    raise IdempotencyConflict() from exc
                raise OrganizationPipelineError(exc.code, exc.message) from exc

    def readback_mirror(
        self,
        artifact_ref: str,
        *,
        tenant_id: str,
        binding: BindingIdentity,
        remote_ref: str,
        remote_revision: str,
        content_digest: str,
        trusted_open_url: str,
    ) -> dict[str, Any]:
        if not trusted_open_url.startswith("https://") or any(char.isspace() for char in trusted_open_url):
            raise OrganizationPipelineError("untrusted_remote_url", "only an HTTPS trusted open URL is allowed")
        with self._lock:
            normalized_ref = _text(artifact_ref, "artifact_ref")
            artifact = self._store.get_artifact(normalized_ref, tenant_id=tenant_id)
            if artifact is None:
                raise OrganizationPipelineError("artifact_not_found", "organization artifact does not exist")
            if artifact["tenantId"] != tenant_id or artifact["bindingId"] != binding.binding_id or artifact["bindingGeneration"] != binding.binding_generation:
                raise OrganizationPipelineError("binding_mismatch", "readback Binding does not match artifact")
            if remote_ref != artifact["remoteRef"]:
                raise OrganizationPipelineError("remote_ref_mismatch", "readback document does not match artifact")
            if remote_revision != artifact["remoteRevision"]:
                raise OrganizationPipelineError("remote_revision_mismatch", "readback revision does not match artifact")
            if content_digest != artifact["contentDigest"]:
                raise OrganizationPipelineError("content_digest_mismatch", "readback content does not match artifact")
            mirror = {
                "schemaVersion": SCHEMA_VERSION,
                "artifactRef": artifact["artifactRef"],
                "tenantId": tenant_id,
                "bindingId": binding.binding_id,
                "bindingGeneration": binding.binding_generation,
                "remoteRef": remote_ref,
                "remoteRevision": remote_revision,
                "contentDigest": content_digest,
                "trustedOpenUrl": trusted_open_url,
                "editable": False,
                "readOnly": True,
            }
            mirror["mirrorDigest"] = _digest(mirror)
            updated = copy.deepcopy(dict(artifact))
            updated["mirror"] = copy.deepcopy(mirror)
            updated["status"] = "readback_verified"
            try:
                self._store.update_artifact(updated)
            except OrganizationStoreConflict as exc:
                raise OrganizationPipelineError(exc.code, exc.message) from exc
            return mirror

    def record_remote_edit_and_readback(
        self,
        artifact_ref: str,
        *,
        tenant_id: str,
        binding: BindingIdentity,
        remote_ref: str,
        remote_revision: str,
        content_digest: str,
        trusted_open_url: str,
    ) -> dict[str, Any]:
        with self._lock:
            normalized_ref = _text(artifact_ref, "artifact_ref")
            artifact = self._store.get_artifact(normalized_ref, tenant_id=tenant_id)
            if artifact is None:
                raise OrganizationPipelineError("artifact_not_found", "organization artifact does not exist")
            if (
                artifact["tenantId"] != tenant_id
                or artifact["bindingId"] != binding.binding_id
                or artifact["bindingGeneration"] != binding.binding_generation
            ):
                raise OrganizationPipelineError("binding_mismatch", "readback Binding does not match artifact")
            if remote_ref != artifact["remoteRef"]:
                raise OrganizationPipelineError("remote_ref_mismatch", "readback document does not match artifact")
            normalized_revision = _text(remote_revision, "remote_revision", 160)
            normalized_digest = _content_digest(content_digest)
            if normalized_revision == artifact["remoteRevision"]:
                raise OrganizationPipelineError("remote_revision_unchanged", "remote edit must produce a new revision")
            updated = copy.deepcopy(dict(artifact))
            updated["remoteRevision"] = normalized_revision
            updated["contentDigest"] = normalized_digest
            try:
                self._store.update_artifact(updated)
            except OrganizationStoreConflict as exc:
                raise OrganizationPipelineError(exc.code, exc.message) from exc
        return self.readback_mirror(
            artifact_ref,
            tenant_id=tenant_id,
            binding=binding,
            remote_ref=remote_ref,
            remote_revision=remote_revision,
            content_digest=content_digest,
            trusted_open_url=trusted_open_url,
        )


__all__ = [
    "BindingIdentity",
    "IdempotencyConflict",
    "OrganizationContentPipeline",
    "OrganizationContentStore",
    "OrganizationPipelineError",
    "OrganizationStoreConflict",
    "ORGANIZATION_MODE",
    "SCHEMA_VERSION",
    "InMemoryOrganizationContentStore",
    "SQLiteOrganizationContentStore",
]
