from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping


MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "012_openclaw_media_archives.sql"
_REQUIRED_COLUMNS = {
    "archive_records": {
        "archive_id",
        "tenant_id",
        "commit_id",
        "manifest_id",
        "run_id",
        "pipeline_id",
        "pipeline_version",
        "device_id",
        "artifacts_json",
        "cloud_bytes",
        "media_cloud_bytes",
        "state",
        "revision",
        "created_at",
        "updated_at",
    },
    "archive_commits": {
        "commit_id",
        "tenant_id",
        "archive_id",
        "manifest_id",
        "run_id",
        "state",
        "artifact_refs_json",
        "total_bytes",
        "cloud_bytes",
        "media_cloud_bytes",
        "committed_at",
        "created_at",
        "updated_at",
    },
    "archive_attachments": {
        "attachment_id",
        "archive_id",
        "artifact_ref",
        "mode",
        "mime_type",
        "sha256",
        "size_bytes",
        "encoding",
        "metadata_json",
        "content",
    },
    "archive_projections": {
        "projection_id",
        "archive_id",
        "kind",
        "ref",
        "artifact_refs_json",
        "consistent",
    },
    "archive_delete_plans": {"delete_plan_id", "archive_id", "tenant_id", "expires_at", "created_at"},
    "archive_readback_receipts": {
        "readback_receipt_ref",
        "archive_id",
        "tenant_id",
        "kind",
        "artifact_refs_json",
        "projection_refs_json",
        "verified",
        "db_present",
        "attachments_present",
        "projections_present",
        "checked_at",
        "created_at",
    },
    "archive_idempotency": {
        "scope",
        "operation_id",
        "idempotency_key",
        "request_fingerprint",
        "archive_id",
        "replay_kind",
        "response_json",
        "status_code",
        "created_at",
    },
}
_SCHEMA_VERSION = 4


class MediaArchiveStore:
    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._write_lock = threading.Lock()
        self._initialize()
        self.path.chmod(0o600)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self) -> None:
        with self.connect() as connection:
            for table, columns in _REQUIRED_COLUMNS.items():
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
                ).fetchone()
                if exists is not None:
                    actual = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                    if actual != columns:
                        raise RuntimeError(f"archive database has an unsupported legacy schema: {table}")
            try:
                connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
            except sqlite3.DatabaseError as exc:
                raise RuntimeError("archive database has an unsupported legacy schema") from exc
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version != _SCHEMA_VERSION:
                raise RuntimeError(f"archive database has an unsupported schema version: {version}")
            for table, columns in _REQUIRED_COLUMNS.items():
                actual = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                if actual != columns:
                    raise RuntimeError(f"archive database has an unsupported legacy schema: {table}")
            attachment_ddl = str(
                connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'archive_attachments'"
                ).fetchone()[0]
            ).lower()
            if "'forbidden'" not in attachment_ddl:
                raise RuntimeError("archive database has an unsupported legacy schema: archive_attachments")
            idempotency_ddl = str(
                connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'archive_idempotency'"
                ).fetchone()[0]
            ).lower()
            if "replay_kind" not in idempotency_ddl:
                raise RuntimeError("archive database has an unsupported legacy schema: archive_idempotency")

    @staticmethod
    def json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @classmethod
    def row_projection(
        cls,
        row: Mapping[str, Any],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        projections: list[dict[str, Any]] | None = None,
        iso: Callable[[float], str] | None = None,
    ) -> dict[str, Any]:
        to_iso = iso or (lambda value: str(value))
        if artifacts is None:
            artifacts = json.loads(str(row["artifacts_json"]))
        if projections is None:
            projections = []
        return {
            "archive_id": str(row["archive_id"]),
            "state": str(row["state"]),
            "commit_id": str(row["commit_id"]),
            "manifest_id": str(row["manifest_id"]),
            "run_id": str(row["run_id"]),
            "pipeline_id": row["pipeline_id"],
            "pipeline_version": row["pipeline_version"],
            "device_id": row["device_id"],
            "artifacts": artifacts,
            "projections": projections,
            "cloud_bytes": int(row["cloud_bytes"]),
            "media_cloud_bytes": int(row["media_cloud_bytes"]),
            "revision": int(row["revision"]),
            "created_at": to_iso(float(row["created_at"])),
            "updated_at": to_iso(float(row["updated_at"])),
        }


__all__ = ["MediaArchiveStore", "MIGRATION_PATH"]
