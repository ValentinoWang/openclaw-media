"""Durable storage for the Stage-2 personal content pipeline.

The store owns only personal artifact state, revision history, and operation
receipts.  It deliberately has no transport or document-provider behavior.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class _Replay:
    __slots__ = ("fingerprint", "result")

    def __init__(self, fingerprint: str, result: Mapping[str, Any]) -> None:
        self.fingerprint = fingerprint
        self.result = result


class _StoreConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


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
        self.path = str(path)
        self._memory_connection: sqlite3.Connection | None = None
        if self.path != ":memory:":
            path_object = Path(self.path).expanduser().resolve()
            parent = path_object.parent
            parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(parent, 0o700)
            except OSError:
                pass
        else:
            # The store lock serializes access to this one process-local
            # connection. Disabling SQLite's creator-thread check lets the
            # same store remain usable from ThreadingHTTPServer workers.
            self._memory_connection = sqlite3.connect(
                self.path,
                timeout=30.0,
                isolation_level=None,
                check_same_thread=False,
            )
        self._lock = threading.RLock()
        self._initialize()
        if self.path != ":memory:":
            try:
                os.chmod(Path(self.path).expanduser().resolve(), 0o600)
            except OSError:
                pass

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
            with connection:
                yield connection
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS personal_store_meta (schema_version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS personal_artifacts (
                    artifact_ref TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    current_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS personal_replays (
                    replay_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS personal_operations (
                    replay_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            rows = connection.execute("SELECT schema_version FROM personal_store_meta").fetchall()
            if not rows:
                connection.execute("INSERT INTO personal_store_meta(schema_version) VALUES (?)", (self._SCHEMA_VERSION,))
            elif rows[0][0] != self._SCHEMA_VERSION:
                raise RuntimeError("personal store schema version is unsupported")
            self._validate_schema(connection)

    @staticmethod
    def _decode_json(raw: str, label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"personal store {label} JSON is corrupt") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"personal store {label} must be an object")
        return value

    def get_replay(self, key: str) -> _Replay | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute("SELECT fingerprint, result_json FROM personal_replays WHERE replay_key = ?", (key,)).fetchone()
            if row is None:
                return None
            return _Replay(str(row["fingerprint"]), self._decode_json(row["result_json"], "replay"))

    def get_failure(self, key: str) -> _Replay | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute("SELECT fingerprint, result_json FROM personal_operations WHERE replay_key = ? AND status = 'failed'", (key,)).fetchone()
            if row is None:
                return None
            return _Replay(str(row["fingerprint"]), self._decode_json(row["result_json"], "failure"))

    def get_artifact(self, artifact_ref: str, *, tenant_id: str) -> Mapping[str, Any] | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute("SELECT artifact_json FROM personal_artifacts WHERE artifact_ref = ? AND tenant_id = ?", (artifact_ref, tenant_id)).fetchone()
            if row is None:
                return None
            artifact = self._decode_json(row["artifact_json"], "artifact")
            if artifact.get("tenantId") != tenant_id:
                raise RuntimeError("personal store artifact tenant mismatch")
            return artifact

    def create_artifact(self, artifact: Mapping[str, Any], *, tenant_id: str, replay_key: str, fingerprint: str) -> tuple[Mapping[str, Any], bool]:
        artifact_ref = str(artifact["artifactRef"])
        if artifact.get("tenantId") != tenant_id:
            raise _StoreConflict("tenant_scope_mismatch", "personal artifact tenant does not match the session")
        stored_tenant_id = str(artifact["tenantId"])
        payload = _canonical(dict(artifact))
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay_row = connection.execute("SELECT fingerprint, result_json FROM personal_replays WHERE replay_key = ?", (replay_key,)).fetchone()
            if replay_row is not None:
                if str(replay_row["fingerprint"]) != fingerprint:
                    connection.rollback()
                    raise _StoreConflict("idempotency_conflict", "idempotency key was reused with another request")
                value = self._decode_json(replay_row["result_json"], "replay")
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
                connection.commit()
                return value, True
            row = connection.execute("SELECT artifact_json, current_revision FROM personal_artifacts WHERE artifact_ref = ? AND tenant_id = ?", (artifact_ref, tenant_id)).fetchone()
            if row is None:
                connection.rollback()
                raise _StoreConflict("artifact_not_found", "personal artifact does not exist")
            current = int(row["current_revision"])
            if isinstance(baseline_revision, bool) or baseline_revision != current:
                connection.rollback()
                raise _StoreConflict("revision_conflict", "baseline revision does not match the current revision")
            artifact = self._decode_json(row["artifact_json"], "artifact")
            if artifact.get("tenantId") != tenant_id:
                connection.rollback()
                raise RuntimeError("personal store artifact tenant mismatch")
            artifact.setdefault("revisions", []).append(copy.deepcopy(dict(revision)))
            artifact["currentRevision"] = int(revision["revision"])
            artifact_json = _canonical(artifact)
            revision_json = _canonical(dict(revision))
            connection.execute("UPDATE personal_artifacts SET artifact_json = ?, current_revision = ? WHERE artifact_ref = ?", (artifact_json, int(revision["revision"]), artifact_ref))
            connection.execute("INSERT INTO personal_replays(replay_key, fingerprint, result_json) VALUES (?, ?, ?)", (replay_key, fingerprint, revision_json))
            connection.execute("INSERT OR REPLACE INTO personal_operations(replay_key, fingerprint, status, result_json) VALUES (?, ?, ?, ?)", (replay_key, fingerprint, "succeeded", revision_json))
            connection.commit()
            return copy.deepcopy(dict(revision)), False

    def record_failure(self, *, replay_key: str, fingerprint: str, failure: Mapping[str, Any]) -> None:
        payload = _canonical(dict(failure))
        with self._lock, self._connection_scope() as connection:
            connection.execute("INSERT OR IGNORE INTO personal_operations(replay_key, fingerprint, status, result_json) VALUES (?, ?, ?, ?)", (replay_key, fingerprint, "failed", payload))
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
