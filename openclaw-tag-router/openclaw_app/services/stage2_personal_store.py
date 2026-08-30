"""Durable storage for the Stage-2 personal content pipeline.

The store owns only personal artifact state, revision history, and operation
receipts.  It deliberately has no transport or document-provider behavior.
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
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from common.canonical_digest import canonical_json as _shared_canonical_json
from openclaw_app.services.stage2_errors import Stage2StoreConflict


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PERSONAL_ARTIFACT_SCHEMA_VERSION = "stage2.personal_pipeline.v1"


def _canonical(value: Any) -> str:
    return _shared_canonical_json(value, allow_nan=True)


def _is_volatile_sqlite_path(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized == ":memory:"
        or normalized.startswith("file::memory:")
        or "mode=memory" in normalized
    )


def _secure_path(path: Path) -> None:
    try:
        os.chmod(path.parent, 0o700)
    except OSError as exc:
        raise RuntimeError("personal store directory permissions could not be restricted") from exc


def _secure_database_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        raise RuntimeError("personal store file permissions could not be restricted") from exc


class _Replay:
    __slots__ = ("fingerprint", "result")

    def __init__(self, fingerprint: str, result: Mapping[str, Any]) -> None:
        self.fingerprint = fingerprint
        self.result = result


# Private by naming convention, but stage2_personal_pipeline.py imports it
# directly -- kept as an alias onto the shared Stage2StoreConflict (see
# openclaw_app/services/stage2_errors.py) rather than a redefinition of the
# same class, per exc-6 in the dedup audit.
_StoreConflict = Stage2StoreConflict


class PersonalContentStore(Protocol):
    """Storage boundary used by :class:`PersonalContentPipeline`."""

    def get_replay(self, key: str) -> _Replay | None: ...

    def get_failure(self, key: str) -> _Replay | None: ...

    def get_artifact(self, artifact_ref: str, *, tenant_id: str) -> Mapping[str, Any] | None: ...

    def create_artifact(
        self,
        artifact: Mapping[str, Any],
        *,
        tenant_id: str,
        replay_key: str,
        fingerprint: str,
    ) -> tuple[Mapping[str, Any], bool]: ...

    def save_revision(
        self,
        artifact_ref: str,
        revision: Mapping[str, Any],
        *,
        tenant_id: str,
        baseline_revision: int,
        replay_key: str,
        fingerprint: str,
    ) -> tuple[Mapping[str, Any], bool]: ...

    def record_failure(self, *, replay_key: str, fingerprint: str, failure: Mapping[str, Any]) -> None: ...


class InMemoryPersonalContentStore:
    """Thread-safe store for tests and explicitly process-local callers."""

    def __init__(self) -> None:
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._replays: dict[str, _Replay] = {}
        self._failures: dict[str, _Replay] = {}
        self._lock = threading.RLock()

    def get_replay(self, key: str) -> _Replay | None:
        with self._lock:
            replay = self._replays.get(key)
            return copy.deepcopy(replay) if replay is not None else None

    def get_failure(self, key: str) -> _Replay | None:
        with self._lock:
            failure = self._failures.get(key)
            return copy.deepcopy(failure) if failure is not None else None

    def get_artifact(self, artifact_ref: str, *, tenant_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            artifact = self._artifacts.get(artifact_ref)
            if artifact is not None and artifact.get("tenantId") != tenant_id:
                return None
            return copy.deepcopy(artifact) if artifact is not None else None

    def create_artifact(
        self,
        artifact: Mapping[str, Any],
        *,
        tenant_id: str,
        replay_key: str,
        fingerprint: str,
    ) -> tuple[Mapping[str, Any], bool]:
        with self._lock:
            replay = self._replays.get(replay_key)
            if replay is not None:
                if replay.fingerprint != fingerprint:
                    raise _StoreConflict("idempotency_conflict", "idempotency key was reused with another request")
                return copy.deepcopy(dict(replay.result)), True
            artifact_ref = str(artifact["artifactRef"])
            if artifact.get("tenantId") != tenant_id:
                raise _StoreConflict("tenant_scope_mismatch", "personal artifact tenant does not match the session")
            if artifact_ref in self._artifacts:
                raise _StoreConflict("artifact_identity_conflict", "writer returned an artifact identity that already exists")
            stored = copy.deepcopy(dict(artifact))
            self._artifacts[artifact_ref] = stored
            self._replays[replay_key] = _Replay(fingerprint, copy.deepcopy(stored))
            return copy.deepcopy(stored), False

    def save_revision(
        self,
        artifact_ref: str,
        revision: Mapping[str, Any],
        *,
        tenant_id: str,
        baseline_revision: int,
        replay_key: str,
        fingerprint: str,
    ) -> tuple[Mapping[str, Any], bool]:
        with self._lock:
            replay = self._replays.get(replay_key)
            if replay is not None:
                if replay.fingerprint != fingerprint:
                    raise _StoreConflict("idempotency_conflict", "idempotency key was reused with another request")
                return copy.deepcopy(dict(replay.result)), True
            artifact = self._artifacts.get(artifact_ref)
            if artifact is None or artifact.get("tenantId") != tenant_id:
                raise _StoreConflict("artifact_not_found", "personal artifact does not exist")
            current = artifact.get("currentRevision")
            if isinstance(baseline_revision, bool) or baseline_revision != current:
                raise _StoreConflict("revision_conflict", "baseline revision does not match the current revision")
            updated = copy.deepcopy(artifact)
            updated.setdefault("revisions", []).append(copy.deepcopy(dict(revision)))
            updated["currentRevision"] = revision["revision"]
            stored_revision = copy.deepcopy(dict(revision))
            self._artifacts[artifact_ref] = updated
            self._replays[replay_key] = _Replay(fingerprint, stored_revision)
            return stored_revision, False

    def record_failure(self, *, replay_key: str, fingerprint: str, failure: Mapping[str, Any]) -> None:
        with self._lock:
            self._failures.setdefault(replay_key, _Replay(fingerprint, copy.deepcopy(dict(failure))))


class SQLitePersonalContentStore:
    """SQLite-backed store with restart-safe idempotency and revisions."""

    _SCHEMA_VERSION = 1
    _REQUIRED_COLUMNS = {
        "personal_store_meta": {"schema_version"},
        "personal_artifacts": {"artifact_ref", "tenant_id", "artifact_json", "current_revision", "created_at"},
        "personal_replays": {"replay_key", "fingerprint", "result_json", "created_at"},
        "personal_operations": {"replay_key", "fingerprint", "status", "result_json", "created_at"},
    }

    def __init__(self, path: str | Path) -> None:
        raw_path = str(path)
        self._memory_connection: sqlite3.Connection | None = None
        if raw_path.strip() == ":memory:":
            self.path = ":memory:"
            # The explicit in-memory mode is retained for tests and callers
            # that deliberately accept process-local state.
            path_object = None
        else:
            if _is_volatile_sqlite_path(raw_path):
                raise RuntimeError("personal store path must be file-backed")
            path_object = Path(raw_path).expanduser().resolve()
            self.path = str(path_object)
            parent = path_object.parent
            parent.mkdir(parents=True, exist_ok=True)
            _secure_path(path_object)
        if path_object is None:
            # The store lock serializes access to this one process-local
            # connection. Disabling SQLite's creator-thread check lets the
            # same store remain usable from ThreadingHTTPServer workers.
            self._memory_connection = sqlite3.connect(
                self.path,
                timeout=30.0,
                isolation_level=None,
                check_same_thread=False,
            )
        else:
            self._memory_connection = None
        self._lock = threading.RLock()
        self._initialize()
        if path_object is not None:
            _secure_database_file(path_object)

    def _connect(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            connection = self._memory_connection
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
            return connection
        connection = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def _connection_scope(self):
        """Close file-backed connections after commit/rollback completes."""

        connection = self._connect()
        try:
            yield connection
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            if self._memory_connection is None:
                connection.close()

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        for table, required in self._REQUIRED_COLUMNS.items():
            columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not required.issubset(columns):
                missing = ",".join(sorted(required - columns))
                raise RuntimeError(f"personal store schema is missing {table} columns: {missing}")

    def _initialize(self) -> None:
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS personal_store_meta (schema_version INTEGER NOT NULL)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_artifacts (
                    artifact_ref TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    current_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_replays (
                    replay_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_operations (
                    replay_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            rows = connection.execute("SELECT schema_version FROM personal_store_meta").fetchall()
            if not rows:
                connection.execute("INSERT INTO personal_store_meta(schema_version) VALUES (?)", (self._SCHEMA_VERSION,))
            elif len(rows) != 1 or rows[0][0] != self._SCHEMA_VERSION:
                raise RuntimeError("personal store schema version is unsupported")
            self._validate_schema(connection)
            connection.commit()

    @staticmethod
    def _decode_json(raw: str, label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"personal store {label} JSON is corrupt") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"personal store {label} must be an object")
        return value

    @classmethod
    def _validate_revision(
        cls,
        value: Mapping[str, Any],
        *,
        label: str,
        expected: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        revision = value.get("revision")
        content = value.get("content")
        content_digest = value.get("contentDigest")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(content, Mapping)
            or not isinstance(content_digest, str)
            or _DIGEST_RE.fullmatch(content_digest) is None
            or content_digest
            != "sha256:" + hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
            or "verified" in value
            and value["verified"] is not True
        ):
            raise RuntimeError(f"personal store {label} revision is invalid")
        if expected is not None and _canonical(dict(value)) != _canonical(dict(expected)):
            raise RuntimeError(f"personal store {label} JSON does not match the request")
        return dict(value)

    @classmethod
    def _validate_artifact(
        cls,
        value: Mapping[str, Any],
        *,
        label: str,
        artifact_ref: str | None = None,
        tenant_id: str | None = None,
        current_revision: int | None = None,
    ) -> dict[str, Any]:
        stored_ref = value.get("artifactRef")
        stored_tenant = value.get("tenantId")
        stored_revision = value.get("currentRevision")
        revisions = value.get("revisions")
        if (
            not isinstance(stored_ref, str)
            or not stored_ref
            or not isinstance(stored_tenant, str)
            or not stored_tenant
            or value.get("schemaVersion") != _PERSONAL_ARTIFACT_SCHEMA_VERSION
            or value.get("authorityMode") != "personal_web/internal"
            or isinstance(stored_revision, bool)
            or not isinstance(stored_revision, int)
            or stored_revision < 1
            or not isinstance(revisions, list)
            or len(revisions) != stored_revision
            or type(value.get("published")) is not bool
            or value["published"] is not False
        ):
            raise RuntimeError(f"personal store {label} JSON is invalid")
        if artifact_ref is not None and stored_ref != artifact_ref:
            raise RuntimeError(f"personal store {label} artifact identity mismatch")
        if tenant_id is not None and stored_tenant != tenant_id:
            raise RuntimeError(f"personal store {label} tenant mismatch")
        if current_revision is not None and stored_revision != current_revision:
            raise RuntimeError(f"personal store {label} revision mismatch")
        for index, revision in enumerate(revisions, start=1):
            if not isinstance(revision, Mapping) or revision.get("revision") != index:
                raise RuntimeError(f"personal store {label} revision history is invalid")
            cls._validate_revision(revision, label=f"{label} history")
        return dict(value)

    @classmethod
    def _validate_failure(cls, value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
        if value.get("status") != "failed":
            raise RuntimeError(f"personal store {label} JSON is invalid")
        for field in ("publishable", "readyForPublish"):
            if field in value and type(value[field]) is not bool:
                raise RuntimeError(f"personal store {label} JSON is invalid")
            if value.get(field) is True:
                raise RuntimeError(f"personal store {label} JSON is invalid")
        return dict(value)

    @classmethod
    def _validate_replay_shape(cls, key: str, value: Mapping[str, Any]) -> dict[str, Any]:
        if key.startswith("artifact:"):
            return cls._validate_artifact(value, label="replay")
        if key.startswith("revision:"):
            return cls._validate_revision(value, label="replay")
        return dict(value)

    def get_replay(self, key: str) -> _Replay | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute("SELECT fingerprint, result_json FROM personal_replays WHERE replay_key = ?", (key,)).fetchone()
            if row is None:
                return None
            value = self._decode_json(row["result_json"], "replay")
            return _Replay(str(row["fingerprint"]), self._validate_replay_shape(key, value))

    def get_failure(self, key: str) -> _Replay | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute("SELECT fingerprint, result_json FROM personal_operations WHERE replay_key = ? AND status = 'failed'", (key,)).fetchone()
            if row is None:
                return None
            value = self._decode_json(row["result_json"], "failure")
            return _Replay(str(row["fingerprint"]), self._validate_failure(value, label="failure"))

    def get_artifact(self, artifact_ref: str, *, tenant_id: str) -> Mapping[str, Any] | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute(
                "SELECT artifact_ref, tenant_id, artifact_json, current_revision "
                "FROM personal_artifacts WHERE artifact_ref = ? AND tenant_id = ?",
                (artifact_ref, tenant_id),
            ).fetchone()
            if row is None:
                return None
            try:
                current_revision = int(row["current_revision"])
            except (TypeError, ValueError) as exc:
                raise RuntimeError("personal store artifact row revision is invalid") from exc
            return self._validate_artifact(
                self._decode_json(row["artifact_json"], "artifact"),
                label="artifact",
                artifact_ref=str(row["artifact_ref"]),
                tenant_id=tenant_id,
                current_revision=current_revision,
            )

    def create_artifact(self, artifact: Mapping[str, Any], *, tenant_id: str, replay_key: str, fingerprint: str) -> tuple[Mapping[str, Any], bool]:
        artifact_ref = str(artifact["artifactRef"])
        if artifact.get("tenantId") != tenant_id:
            raise _StoreConflict("tenant_scope_mismatch", "personal artifact tenant does not match the session")
        stored_tenant_id = str(artifact["tenantId"])
        self._validate_artifact(artifact, label="artifact", artifact_ref=artifact_ref, tenant_id=tenant_id)
        payload = _canonical(dict(artifact))
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay_row = connection.execute("SELECT fingerprint, result_json FROM personal_replays WHERE replay_key = ?", (replay_key,)).fetchone()
            if replay_row is not None:
                if str(replay_row["fingerprint"]) != fingerprint:
                    connection.rollback()
                    raise _StoreConflict("idempotency_conflict", "idempotency key was reused with another request")
                value = self._decode_json(replay_row["result_json"], "replay")
                self._validate_artifact(value, label="replay", artifact_ref=artifact_ref, tenant_id=tenant_id)
                if _canonical(value) != payload:
                    connection.rollback()
                    raise RuntimeError("personal store replay JSON does not match the request")
                connection.commit()
                return value, True
            existing = connection.execute("SELECT 1 FROM personal_artifacts WHERE artifact_ref = ?", (artifact_ref,)).fetchone()
            if existing is not None:
                connection.rollback()
                raise _StoreConflict("artifact_identity_conflict", "writer returned an artifact identity that already exists")
            connection.execute("INSERT INTO personal_artifacts(artifact_ref, tenant_id, artifact_json, current_revision) VALUES (?, ?, ?, ?)", (artifact_ref, stored_tenant_id, payload, int(artifact["currentRevision"])))
            connection.execute("INSERT INTO personal_replays(replay_key, fingerprint, result_json) VALUES (?, ?, ?)", (replay_key, fingerprint, payload))
            connection.execute("INSERT OR REPLACE INTO personal_operations(replay_key, fingerprint, status, result_json) VALUES (?, ?, ?, ?)", (replay_key, fingerprint, "succeeded", payload))
            connection.commit()
            return copy.deepcopy(dict(artifact)), False

    def save_revision(self, artifact_ref: str, revision: Mapping[str, Any], *, tenant_id: str, baseline_revision: int, replay_key: str, fingerprint: str) -> tuple[Mapping[str, Any], bool]:
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay_row = connection.execute("SELECT fingerprint, result_json FROM personal_replays WHERE replay_key = ?", (replay_key,)).fetchone()
            if replay_row is not None:
                if str(replay_row["fingerprint"]) != fingerprint:
                    connection.rollback()
                    raise _StoreConflict("idempotency_conflict", "idempotency key was reused with another request")
                value = self._decode_json(replay_row["result_json"], "replay")
                self._validate_revision(value, label="replay", expected=revision)
                connection.commit()
                return value, True
            row = connection.execute("SELECT artifact_json, current_revision FROM personal_artifacts WHERE artifact_ref = ? AND tenant_id = ?", (artifact_ref, tenant_id)).fetchone()
            if row is None:
                connection.rollback()
                raise _StoreConflict("artifact_not_found", "personal artifact does not exist")
            try:
                current = int(row["current_revision"])
            except (TypeError, ValueError) as exc:
                connection.rollback()
                raise RuntimeError("personal store artifact row revision is invalid") from exc
            if isinstance(baseline_revision, bool) or baseline_revision != current:
                connection.rollback()
                raise _StoreConflict("revision_conflict", "baseline revision does not match the current revision")
            artifact = self._validate_artifact(
                self._decode_json(row["artifact_json"], "artifact"),
                label="artifact",
                artifact_ref=artifact_ref,
                tenant_id=tenant_id,
                current_revision=current,
            )
            next_revision = self._validate_revision(revision, label="revision")
            if next_revision["revision"] != current + 1:
                connection.rollback()
                raise _StoreConflict("revision_conflict", "revision number does not follow the current revision")
            artifact["revisions"].append(copy.deepcopy(next_revision))
            artifact["currentRevision"] = next_revision["revision"]
            artifact_json = _canonical(artifact)
            revision_json = _canonical(next_revision)
            connection.execute(
                "UPDATE personal_artifacts SET artifact_json = ?, current_revision = ? "
                "WHERE artifact_ref = ? AND tenant_id = ?",
                (artifact_json, int(next_revision["revision"]), artifact_ref, tenant_id),
            )
            connection.execute("INSERT INTO personal_replays(replay_key, fingerprint, result_json) VALUES (?, ?, ?)", (replay_key, fingerprint, revision_json))
            connection.execute("INSERT OR REPLACE INTO personal_operations(replay_key, fingerprint, status, result_json) VALUES (?, ?, ?, ?)", (replay_key, fingerprint, "succeeded", revision_json))
            connection.commit()
            return copy.deepcopy(dict(revision)), False

    def record_failure(self, *, replay_key: str, fingerprint: str, failure: Mapping[str, Any]) -> None:
        validated = self._validate_failure(failure, label="failure")
        payload = _canonical(validated)
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT fingerprint, status, result_json FROM personal_operations WHERE replay_key = ?",
                (replay_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["fingerprint"]) != fingerprint:
                    connection.rollback()
                    raise _StoreConflict("idempotency_conflict", "idempotency key was reused with another request")
                status = str(existing["status"])
                if status not in {"failed", "succeeded"}:
                    connection.rollback()
                    raise RuntimeError("personal store operation status is invalid")
                if status == "failed":
                    self._validate_failure(
                        self._decode_json(existing["result_json"], "failure"), label="failure"
                    )
                connection.commit()
                return
            connection.execute(
                "INSERT INTO personal_operations(replay_key, fingerprint, status, result_json) "
                "VALUES (?, ?, ?, ?)",
                (replay_key, fingerprint, "failed", payload),
            )
            connection.commit()


# Both spellings are common in existing OpenClaw stores.  Keep one class and
# expose the conventional ``Sqlite`` spelling without creating another path.
SqlitePersonalContentStore = SQLitePersonalContentStore


__all__ = [
    "InMemoryPersonalContentStore",
    "PersonalContentStore",
    "SQLitePersonalContentStore",
    "SqlitePersonalContentStore",
]
