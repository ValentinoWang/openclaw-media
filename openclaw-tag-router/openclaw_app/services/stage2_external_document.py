"""Fail-closed external document write/readback boundary for Stage 2.

The adapter is deliberately transport-neutral.  A later integration layer may
provide a Feishu or database implementation, but this module only accepts
server-owned Binding facts and verifies the returned identity before declaring
the document write complete.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sqlite3
import re
import threading
import time
from contextlib import contextmanager
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from openclaw_app.services.stage2_errors import (
    IDEMPOTENCY_CONFLICT,
    IDEMPOTENCY_IN_PROGRESS,
    Stage2CodedError,
)


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SUCCESS_STATES = frozenset({"ok", "success", "succeeded", "written", "created"})


class ExternalDocumentError(Stage2CodedError):
    """Stable fail-closed error raised before an external adapter call."""


class IdempotencyConflict(ExternalDocumentError):
    def __init__(self, message: str = "idempotency key was reused with a different request") -> None:
        super().__init__(IDEMPOTENCY_CONFLICT, message)


class IdempotencyInProgress(ExternalDocumentError):
    def __init__(self, message: str = "external document write is already in progress") -> None:
        super().__init__(IDEMPOTENCY_IN_PROGRESS, message)


def _required_text(value: Any, label: str, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentError("invalid_request", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise ExternalDocumentError("invalid_request", f"{label} is invalid")
    return normalized


def _positive_generation(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExternalDocumentError("binding_invalid", "binding_generation must be a positive integer")
    return value


def _digest(value: Any, label: str = "content_digest") -> str:
    normalized = _required_text(value, label, 80)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ExternalDocumentError("invalid_request", f"{label} must be a sha256 digest")
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


@dataclass(frozen=True, slots=True)
class BindingIdentity:
    """Server-owned organization Binding identity; no credential material."""

    tenant_id: str
    binding_id: str
    binding_generation: int
    status: str = "active"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _required_text(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "binding_id", _required_text(self.binding_id, "binding_id"))
        object.__setattr__(self, "binding_generation", _positive_generation(self.binding_generation))
        object.__setattr__(self, "status", _required_text(self.status, "binding_status").lower())


@dataclass(frozen=True, slots=True)
class OrganizationWriteRequest:
    binding: BindingIdentity | None
    idempotency_key: str
    content_digest: str
    title: str = ""
    body: str = ""
    content_format: str = "markdown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "idempotency_key", _required_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "content_digest", _digest(self.content_digest))
        if self.title:
            object.__setattr__(self, "title", _required_text(self.title, "title", 240))
        if self.body:
            object.__setattr__(self, "body", _required_text(self.body, "body"))
        object.__setattr__(self, "content_format", _required_text(self.content_format, "content_format", 32).lower())


@dataclass(frozen=True, slots=True)
class ExternalWriteOutcome:
    status: str
    remote_ref: str | None
    remote_revision: str | None
    tenant_id: str | None
    binding_id: str | None
    binding_generation: int | None
    content_digest: str | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalReadbackOutcome:
    status: str
    remote_ref: str | None
    remote_revision: str | None
    tenant_id: str | None
    binding_id: str | None
    binding_generation: int | None
    content_digest: str | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalDocumentWriteResult:
    status: str
    publishable: bool
    ready_for_registration: bool
    idempotency_key: str
    content_digest: str
    remote_ref: str | None
    remote_revision: str | None
    error_code: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExternalDocumentAdapter(Protocol):
    def write(self, request: OrganizationWriteRequest) -> ExternalWriteOutcome | Mapping[str, Any]: ...

    def readback(
        self,
        request: OrganizationWriteRequest,
        write: ExternalWriteOutcome,
    ) -> ExternalReadbackOutcome | Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _StoredReceipt:
    fingerprint: str
    result: ExternalDocumentWriteResult


class InMemoryWriteReceiptStore:
    """Thread-safe idempotency store; production persistence remains injected."""

    def __init__(self) -> None:
        self._records: dict[str, _StoredReceipt] = {}
        self._claims: dict[str, tuple[str, float]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> _StoredReceipt | None:
        with self._lock:
            value = self._records.get(key)
            return copy.deepcopy(value) if value is not None else None

    def put(self, key: str, fingerprint: str, result: ExternalDocumentWriteResult) -> None:
        with self._lock:
            existing = self._records.get(key)
            if existing is not None and existing.fingerprint != fingerprint:
                raise IdempotencyConflict()
            if existing is None:
                self._records[key] = _StoredReceipt(fingerprint, copy.deepcopy(result))
            self._claims.pop(key, None)

    def replace(self, key: str, fingerprint: str, result: ExternalDocumentWriteResult) -> None:
        with self._lock:
            existing = self._records.get(key)
            if existing is None:
                raise ExternalDocumentError("receipt_missing", "write receipt does not exist")
            if existing.fingerprint != fingerprint:
                raise IdempotencyConflict()
            self._records[key] = _StoredReceipt(fingerprint, copy.deepcopy(result))
            self._claims.pop(key, None)

    def claim(self, key: str, fingerprint: str) -> _StoredReceipt | None:
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise IdempotencyConflict()
                return copy.deepcopy(existing)
            now = time.time()
            claim = self._claims.get(key)
            if claim is not None:
                if claim[0] != fingerprint:
                    raise IdempotencyConflict()
                if claim[1] > now:
                    raise IdempotencyInProgress()
            self._claims[key] = (fingerprint, now + 300.0)
            return None

    def release(self, key: str, fingerprint: str) -> None:
        with self._lock:
            claim = self._claims.get(key)
            if claim is not None and claim[0] == fingerprint:
                self._claims.pop(key, None)


class SQLiteWriteReceiptStore:
    """Restart-safe external write receipts used before artifact registration."""

    _SCHEMA_VERSION = 2
    _CLAIM_LEASE_SECONDS = 300.0
    _REQUIRED_COLUMNS = {
        "organization_external_meta": {"schema_version"},
        "organization_external_receipts": {
            "idempotency_key",
            "fingerprint",
            "result_json",
            "created_at",
        },
        "organization_external_claims": {
            "idempotency_key",
            "fingerprint",
            "lease_until",
            "created_at",
        },
    }

    def __init__(self, path: str | Path) -> None:
        raw_path = str(path).strip()
        if (
            not raw_path
            or raw_path == ":memory:"
            or raw_path.lower().startswith("file::memory:")
            or "mode=memory" in raw_path.lower()
        ):
            raise ExternalDocumentError("volatile_store_forbidden", "external write receipts must be file-backed")
        path_object = Path(raw_path).expanduser().resolve()
        self.path = str(path_object)
        path_object.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path_object.parent, 0o700)
        except OSError as exc:
            raise ExternalDocumentError(
                "receipt_store_permissions",
                "external receipt directory permissions could not be restricted",
            ) from exc
        self._lock = threading.RLock()
        self._initialize()
        try:
            os.chmod(path_object, 0o600)
        except OSError as exc:
            raise ExternalDocumentError(
                "receipt_store_permissions",
                "external receipt file permissions could not be restricted",
            ) from exc

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
            yield connection
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        for table, required in self._REQUIRED_COLUMNS.items():
            columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not required.issubset(columns):
                missing = ",".join(sorted(required - columns))
                raise ExternalDocumentError(
                    "receipt_schema_invalid",
                    f"external receipt schema is missing {table} columns: {missing}",
                )

    def _initialize(self) -> None:
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS organization_external_meta "
                "(schema_version INTEGER NOT NULL)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS organization_external_receipts (
                    idempotency_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS organization_external_claims (
                    idempotency_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    lease_until REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._validate_schema(connection)
            rows = connection.execute(
                "SELECT schema_version FROM organization_external_meta"
            ).fetchall()
            if not rows:
                connection.execute(
                    "INSERT INTO organization_external_meta(schema_version) VALUES (?)",
                    (self._SCHEMA_VERSION,),
                )
            else:
                try:
                    schema_version = int(rows[0][0])
                except (TypeError, ValueError, IndexError) as exc:
                    raise ExternalDocumentError(
                        "receipt_schema_unsupported",
                        "external receipt schema version is unsupported",
                    ) from exc
                if len(rows) != 1 or schema_version not in {1, self._SCHEMA_VERSION}:
                    raise ExternalDocumentError(
                        "receipt_schema_unsupported",
                        "external receipt schema version is unsupported",
                    )
                if schema_version == 1:
                    connection.execute(
                        "UPDATE organization_external_meta SET schema_version = ?",
                        (self._SCHEMA_VERSION,),
                    )
            connection.commit()

    @staticmethod
    def _validate_result(result: ExternalDocumentWriteResult, *, code: str) -> ExternalDocumentWriteResult:
        if not isinstance(result, ExternalDocumentWriteResult):
            raise ExternalDocumentError(code, "external write receipt is not a valid result")
        if (
            not isinstance(result.status, str)
            or result.status not in {"written", "needs_attention"}
            or type(result.publishable) is not bool
            or result.publishable is not False
            or type(result.ready_for_registration) is not bool
            or not isinstance(result.idempotency_key, str)
            or not result.idempotency_key.strip()
            or not isinstance(result.content_digest, str)
            or _DIGEST_RE.fullmatch(result.content_digest) is None
            or result.remote_ref is not None
            and (not isinstance(result.remote_ref, str) or not result.remote_ref.strip())
            or result.remote_revision is not None
            and (not isinstance(result.remote_revision, str) or not result.remote_revision.strip())
            or result.error_code is not None
            and (not isinstance(result.error_code, str) or not result.error_code.strip())
        ):
            raise ExternalDocumentError(code, "external write receipt fields are invalid")
        if result.status == "written":
            if (
                result.ready_for_registration is not True
                or result.remote_ref is None
                or result.remote_revision is None
                or result.error_code is not None
            ):
                raise ExternalDocumentError(code, "written external receipt is incomplete")
        elif result.ready_for_registration is not False or result.error_code is None:
            raise ExternalDocumentError(code, "failed external receipt is publishable or incomplete")
        return result

    @classmethod
    def _encode(cls, result: ExternalDocumentWriteResult) -> str:
        cls._validate_result(result, code="receipt_invalid")
        return json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _decode(cls, raw: str) -> ExternalDocumentWriteResult:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ExternalDocumentError("receipt_corrupt", "external write receipt is corrupt") from exc
        if not isinstance(value, Mapping):
            raise ExternalDocumentError("receipt_corrupt", "external write receipt must be an object")
        try:
            result = ExternalDocumentWriteResult(
                status=value["status"],
                publishable=value["publishable"],
                ready_for_registration=value["ready_for_registration"],
                idempotency_key=value["idempotency_key"],
                content_digest=value["content_digest"],
                remote_ref=value.get("remote_ref"),
                remote_revision=value.get("remote_revision"),
                error_code=value.get("error_code"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalDocumentError("receipt_corrupt", "external write receipt fields are invalid") from exc
        try:
            return cls._validate_result(result, code="receipt_corrupt")
        except ExternalDocumentError as exc:
            if exc.code == "receipt_corrupt":
                raise
            raise ExternalDocumentError("receipt_corrupt", exc.message) from exc

    def get(self, key: str) -> _StoredReceipt | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute("SELECT fingerprint, result_json FROM organization_external_receipts WHERE idempotency_key = ?", (key,)).fetchone()
        if row is None:
            return None
        return _StoredReceipt(str(row["fingerprint"]), self._decode(str(row["result_json"])))

    def put(self, key: str, fingerprint: str, result: ExternalDocumentWriteResult) -> None:
        self._save(key, fingerprint, result, replace=False)

    def replace(self, key: str, fingerprint: str, result: ExternalDocumentWriteResult) -> None:
        self._save(key, fingerprint, result, replace=True)

    def _save(self, key: str, fingerprint: str, result: ExternalDocumentWriteResult, *, replace: bool) -> None:
        payload = self._encode(result)
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT fingerprint, result_json FROM organization_external_receipts "
                "WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                if replace:
                    connection.rollback()
                    raise ExternalDocumentError("receipt_missing", "write receipt does not exist")
                connection.execute("INSERT INTO organization_external_receipts(idempotency_key, fingerprint, result_json) VALUES (?, ?, ?)", (key, fingerprint, payload))
            else:
                if str(row["fingerprint"]) != fingerprint:
                    connection.rollback()
                    raise IdempotencyConflict()
                self._decode(str(row["result_json"]))
                if replace:
                    connection.execute("UPDATE organization_external_receipts SET result_json = ? WHERE idempotency_key = ?", (payload, key))
            connection.execute(
                "DELETE FROM organization_external_claims WHERE idempotency_key = ? AND fingerprint = ?",
                (key, fingerprint),
            )
            connection.commit()

    def claim(self, key: str, fingerprint: str) -> _StoredReceipt | None:
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT fingerprint, result_json FROM organization_external_receipts "
                "WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                if str(row["fingerprint"]) != fingerprint:
                    connection.rollback()
                    raise IdempotencyConflict()
                result = self._decode(str(row["result_json"]))
                connection.commit()
                return _StoredReceipt(str(row["fingerprint"]), result)
            claim = connection.execute(
                "SELECT fingerprint, lease_until FROM organization_external_claims "
                "WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            now = time.time()
            if claim is not None:
                if str(claim["fingerprint"]) != fingerprint:
                    connection.rollback()
                    raise IdempotencyConflict()
                try:
                    lease_until = float(claim["lease_until"])
                except (TypeError, ValueError) as exc:
                    connection.rollback()
                    raise ExternalDocumentError(
                        "receipt_corrupt",
                        "external write claim lease is invalid",
                    ) from exc
                if not math.isfinite(lease_until):
                    connection.rollback()
                    raise ExternalDocumentError(
                        "receipt_corrupt",
                        "external write claim lease is invalid",
                    )
                if lease_until > now:
                    connection.rollback()
                    raise IdempotencyInProgress()
                connection.execute(
                    "DELETE FROM organization_external_claims "
                    "WHERE idempotency_key = ? AND fingerprint = ?",
                    (key, fingerprint),
                )
            connection.execute(
                "INSERT INTO organization_external_claims(idempotency_key, fingerprint, lease_until) "
                "VALUES (?, ?, ?)",
                (key, fingerprint, now + self._CLAIM_LEASE_SECONDS),
            )
            connection.commit()
            return None

    def release(self, key: str, fingerprint: str) -> None:
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM organization_external_claims WHERE idempotency_key = ? AND fingerprint = ?",
                (key, fingerprint),
            )
            connection.commit()


def _fingerprint(request: OrganizationWriteRequest) -> str:
    payload = {
        "binding": asdict(request.binding) if request.binding is not None else None,
        "idempotency_key": request.idempotency_key,
        "content_digest": request.content_digest,
        "title": request.title,
        "body": request.body,
        "content_format": request.content_format,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_outcome(value: ExternalWriteOutcome | Mapping[str, Any]) -> ExternalWriteOutcome:
    if isinstance(value, ExternalWriteOutcome):
        return value
    if not isinstance(value, Mapping):
        raise ExternalDocumentError("write_failed", "external adapter returned an invalid write outcome")
    return ExternalWriteOutcome(
        status=str(_lookup(value, "status", default="")),
        remote_ref=_lookup(value, "remote_ref", "remoteRef"),
        remote_revision=_lookup(value, "remote_revision", "remoteRevision"),
        tenant_id=_lookup(value, "tenant_id", "tenantId"),
        binding_id=_lookup(value, "binding_id", "bindingId"),
        binding_generation=_lookup(value, "binding_generation", "bindingGeneration"),
        content_digest=_lookup(value, "content_digest", "contentDigest"),
        error_code=_lookup(value, "error_code", "errorCode"),
    )


def _readback_outcome(value: ExternalReadbackOutcome | Mapping[str, Any]) -> ExternalReadbackOutcome:
    if isinstance(value, ExternalReadbackOutcome):
        return value
    if not isinstance(value, Mapping):
        raise ExternalDocumentError("readback_incomplete", "external adapter returned an invalid readback")
    return ExternalReadbackOutcome(
        status=str(_lookup(value, "status", default="")),
        remote_ref=_lookup(value, "remote_ref", "remoteRef"),
        remote_revision=_lookup(value, "remote_revision", "remoteRevision"),
        tenant_id=_lookup(value, "tenant_id", "tenantId"),
        binding_id=_lookup(value, "binding_id", "bindingId"),
        binding_generation=_lookup(value, "binding_generation", "bindingGeneration"),
        content_digest=_lookup(value, "content_digest", "contentDigest"),
        error_code=_lookup(value, "error_code", "errorCode"),
    )


class ExternalDocumentWriter:
    """Coordinate an injected write plus readback without external knowledge."""

    def __init__(self, store: InMemoryWriteReceiptStore | SQLiteWriteReceiptStore | None = None) -> None:
        self._store = store or InMemoryWriteReceiptStore()
        self._lock = threading.RLock()

    def write(
        self,
        request: OrganizationWriteRequest,
        adapter: ExternalDocumentAdapter,
    ) -> ExternalDocumentWriteResult:
        self._validate_request(request)
        fingerprint = _fingerprint(request)
        with self._lock:
            claim = getattr(self._store, "claim", None)
            release = getattr(self._store, "release", None)
            stored = claim(request.idempotency_key, fingerprint) if callable(claim) else self._store.get(request.idempotency_key)
            if stored is not None:
                return self._replay_result(request, stored, fingerprint)

            try:
                try:
                    write = _write_outcome(adapter.write(request))
                except ExternalDocumentError as exc:
                    result = self._attention(request, None, None, exc.code)
                    self._store.put(request.idempotency_key, fingerprint, result)
                    return result
                except Exception:
                    result = self._attention(request, None, None, "write_failed")
                    self._store.put(request.idempotency_key, fingerprint, result)
                    return result

                if not self._write_matches(request, write):
                    result = self._attention(
                        request,
                        write.remote_ref,
                        write.remote_revision,
                        write.error_code or "external_write_needs_attention",
                    )
                    self._store.put(request.idempotency_key, fingerprint, result)
                    return result

                try:
                    readback = _readback_outcome(adapter.readback(request, write))
                except Exception:
                    result = self._attention(request, write.remote_ref, write.remote_revision, "readback_incomplete")
                    self._store.put(request.idempotency_key, fingerprint, result)
                    return result

                if not self._readback_matches(request, write, readback):
                    result = self._attention(request, write.remote_ref, write.remote_revision, "readback_incomplete")
                else:
                    result = ExternalDocumentWriteResult(
                        status="written",
                        # External write/readback is only the first part of the
                        # Stage-2 success boundary. Artifact registration still
                        # has to succeed before a caller may publish.
                        publishable=False,
                        ready_for_registration=True,
                        idempotency_key=request.idempotency_key,
                        content_digest=request.content_digest,
                        remote_ref=write.remote_ref,
                        remote_revision=write.remote_revision,
                        error_code=None,
                    )
                self._store.put(request.idempotency_key, fingerprint, result)
                return result
            finally:
                if callable(release):
                    release(request.idempotency_key, fingerprint)

    def resume_readback(
        self,
        request: OrganizationWriteRequest,
        adapter: ExternalDocumentAdapter,
    ) -> ExternalDocumentWriteResult:
        """Resume only the readback step after a partial external success."""

        self._validate_request(request)
        fingerprint = _fingerprint(request)
        with self._lock:
            stored = self._store.get(request.idempotency_key)
            if stored is None:
                raise ExternalDocumentError("receipt_missing", "no external write receipt exists")
            previous = self._replay_result(request, stored, fingerprint)
            if previous.status == "written":
                return previous
            if not previous.remote_ref or not previous.remote_revision:
                return previous

            binding = request.binding
            write = ExternalWriteOutcome(
                status="succeeded",
                remote_ref=previous.remote_ref,
                remote_revision=previous.remote_revision,
                tenant_id=binding.tenant_id,
                binding_id=binding.binding_id,
                binding_generation=binding.binding_generation,
                content_digest=request.content_digest,
            )
            try:
                readback = _readback_outcome(adapter.readback(request, write))
            except Exception:
                return previous
            if not self._readback_matches(request, write, readback):
                return previous

            resumed = ExternalDocumentWriteResult(
                status="written",
                publishable=False,
                ready_for_registration=True,
                idempotency_key=request.idempotency_key,
                content_digest=request.content_digest,
                remote_ref=previous.remote_ref,
                remote_revision=previous.remote_revision,
                error_code=None,
            )
            self._store.replace(request.idempotency_key, fingerprint, resumed)
            return resumed

    @staticmethod
    def _replay_result(
        request: OrganizationWriteRequest,
        stored: _StoredReceipt,
        fingerprint: str,
    ) -> ExternalDocumentWriteResult:
        if stored.fingerprint != fingerprint:
            raise IdempotencyConflict()
        try:
            SQLiteWriteReceiptStore._validate_result(stored.result, code="receipt_corrupt")
        except ExternalDocumentError as exc:
            if exc.code == "receipt_corrupt":
                raise
            raise ExternalDocumentError("receipt_corrupt", exc.message) from exc
        if (
            stored.result.idempotency_key != request.idempotency_key
            or stored.result.content_digest != request.content_digest
        ):
            raise ExternalDocumentError(
                "receipt_corrupt",
                "stored external receipt does not match the request",
            )
        return copy.deepcopy(stored.result)

    @staticmethod
    def _validate_request(request: OrganizationWriteRequest) -> None:
        if not isinstance(request, OrganizationWriteRequest):
            raise ExternalDocumentError("invalid_request", "organization write request is required")
        binding = request.binding
        if binding is None:
            raise ExternalDocumentError("binding_required", "organization Binding identity is required")
        if binding.status != "active":
            raise ExternalDocumentError("binding_inactive", "organization Binding is not active")

    @staticmethod
    def _write_matches(request: OrganizationWriteRequest, write: ExternalWriteOutcome) -> bool:
        binding = request.binding
        return (
            write.status.lower() in _SUCCESS_STATES
            and bool(write.remote_ref)
            and bool(write.remote_revision)
            and write.tenant_id == binding.tenant_id
            and write.binding_id == binding.binding_id
            and write.binding_generation == binding.binding_generation
            and write.content_digest == request.content_digest
        )

    @staticmethod
    def _readback_matches(
        request: OrganizationWriteRequest,
        write: ExternalWriteOutcome,
        readback: ExternalReadbackOutcome,
    ) -> bool:
        binding = request.binding
        return (
            readback.status.lower() in {"ok", "success", "succeeded", "confirmed", "read"}
            and readback.remote_ref == write.remote_ref
            and readback.remote_revision == write.remote_revision
            and readback.tenant_id == binding.tenant_id
            and readback.binding_id == binding.binding_id
            and readback.binding_generation == binding.binding_generation
            and readback.content_digest == request.content_digest
        )

    @staticmethod
    def _attention(
        request: OrganizationWriteRequest,
        remote_ref: str | None,
        remote_revision: str | None,
        error_code: str,
    ) -> ExternalDocumentWriteResult:
        return ExternalDocumentWriteResult(
            status="needs_attention",
            publishable=False,
            ready_for_registration=False,
            idempotency_key=request.idempotency_key,
            content_digest=request.content_digest,
            remote_ref=remote_ref,
            remote_revision=remote_revision,
            error_code=error_code,
        )


__all__ = [
    "BindingIdentity",
    "ExternalDocumentAdapter",
    "ExternalDocumentError",
    "ExternalDocumentWriteResult",
    "ExternalReadbackOutcome",
    "ExternalWriteOutcome",
    "ExternalDocumentWriter",
    "IdempotencyConflict",
    "IdempotencyInProgress",
    "InMemoryWriteReceiptStore",
    "SQLiteWriteReceiptStore",
    "OrganizationWriteRequest",
]
