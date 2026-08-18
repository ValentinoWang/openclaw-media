"""Canonical local content-addressed workspace and project blob references."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import stat
import math
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


_BUFFER_SIZE = 1024 * 1024
_DIGEST_LENGTH = 64


class BlobDescriptor(BaseModel):
    """Public-safe identity for one CLI-managed CAS object."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    blob_ref: str
    sha256: str
    size_bytes: int


class ProjectBlobReference(BaseModel):
    """A project-owned reference to a managed blob, never a local path."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    project_id: str
    purpose: str
    blob_ref: str


class WorkspaceOutcome(BaseModel):
    """Sanitized result for a workspace operation."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    status: Literal["completed", "manual"]
    code: str
    blob: BlobDescriptor | None = None
    reference: ProjectBlobReference | None = None


def _manual(code: str) -> WorkspaceOutcome:
    return WorkspaceOutcome(status="manual", code=code)


class WorkspaceGcCandidate(BaseModel):
    """One fully described, reviewable GC plan entry."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    blob_ref: str
    sha256: str
    size_bytes: int
    reference_count: Literal[0] = 0
    reason: Literal["unreferenced_unleased_unpinned_expired"]


class WorkspaceGcOutcome(BaseModel):
    """Sanitized, deterministic lease/pin-aware garbage-collection receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    status: Literal["completed", "manual"]
    code: str
    dry_run: bool
    candidates: tuple[WorkspaceGcCandidate, ...] = ()
    deleted: tuple[str, ...] = ()


def _gc_manual(code: str, dry_run: object = True) -> WorkspaceGcOutcome:
    return WorkspaceGcOutcome(
        status="manual", code=code, dry_run=dry_run if isinstance(dry_run, bool) else True
    )


def _valid_label(value: object, *, maximum: int = 128) -> bool:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return False
    if value != value.strip() or value in {".", ".."}:
        return False
    return not any(character in "/\\\x00" or ord(character) < 32 for character in value)


def _parse_blob_ref(blob_ref: object) -> str | None:
    if not isinstance(blob_ref, str):
        return None
    parts = blob_ref.split("/")
    if len(parts) != 4 or parts[:2] != ["blobs", "sha256"]:
        return None
    prefix, digest = parts[2:]
    if len(prefix) != 2 or len(digest) != _DIGEST_LENGTH or prefix != digest[:2]:
        return None
    if any(character not in "0123456789abcdef" for character in digest):
        return None
    return digest


class LocalWorkspace:
    """Own one SQLite reference index and one SHA-256 CAS beneath ``root``."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.database_path = self.root / "workspace.sqlite3"
        self._ready = False
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            (self.root / "blobs" / "sha256").mkdir(mode=0o700, parents=True, exist_ok=True)
            (self.root / "tmp").mkdir(mode=0o700, parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS blobs (
                        blob_ref TEXT PRIMARY KEY,
                        sha256 TEXT NOT NULL UNIQUE,
                        size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                        created_at REAL NOT NULL DEFAULT 0,
                        last_accessed_at REAL NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS project_blob_refs (
                        project_id TEXT NOT NULL,
                        purpose TEXT NOT NULL,
                        blob_ref TEXT NOT NULL REFERENCES blobs(blob_ref),
                        PRIMARY KEY (project_id, purpose)
                    );
                    CREATE INDEX IF NOT EXISTS project_blob_refs_blob
                        ON project_blob_refs(blob_ref);
                    CREATE TABLE IF NOT EXISTS blob_leases (
                        blob_ref TEXT NOT NULL REFERENCES blobs(blob_ref) ON DELETE CASCADE,
                        lease_id TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        PRIMARY KEY (blob_ref, lease_id)
                    );
                    CREATE TABLE IF NOT EXISTS blob_pins (
                        blob_ref TEXT NOT NULL REFERENCES blobs(blob_ref) ON DELETE CASCADE,
                        pin_id TEXT NOT NULL,
                        PRIMARY KEY (blob_ref, pin_id)
                    );
                    """
                )
                columns = {row[1] for row in connection.execute("PRAGMA table_info(blobs)")}
                if "created_at" not in columns:
                    connection.execute("ALTER TABLE blobs ADD COLUMN created_at REAL NOT NULL DEFAULT 0")
                if "last_accessed_at" not in columns:
                    connection.execute("ALTER TABLE blobs ADD COLUMN last_accessed_at REAL NOT NULL DEFAULT 0")
                connection.execute("UPDATE blobs SET created_at = ? WHERE created_at = 0", (time.time(),))
                connection.execute("UPDATE blobs SET last_accessed_at = created_at WHERE last_accessed_at = 0")
            self._ready = True
        except (OSError, sqlite3.Error):
            self._ready = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _descriptor(self, digest: str, size_bytes: int) -> BlobDescriptor:
        return BlobDescriptor(
            blob_ref=f"blobs/sha256/{digest[:2]}/{digest}",
            sha256=f"sha256:{digest}",
            size_bytes=size_bytes,
        )

    def _hash_file(self, path: Path) -> tuple[str, int] | None:
        digest = sha256()
        size_bytes = 0
        try:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
                return None
            with path.open("rb") as handle:
                while block := handle.read(_BUFFER_SIZE):
                    digest.update(block)
                    size_bytes += len(block)
        except OSError:
            return None
        return digest.hexdigest(), size_bytes

    def _check_managed_blob(self, descriptor: BlobDescriptor) -> str:
        path = self.root / descriptor.blob_ref
        measured = self._hash_file(path)
        if measured is None:
            return "blob_missing" if not path.exists() else "blob_corrupt"
        if measured != (descriptor.sha256.removeprefix("sha256:"), descriptor.size_bytes):
            return "blob_corrupt"
        return "ok"

    def _copy_source(self, source: Path) -> tuple[Path, str, int] | str:
        temporary = self.root / "tmp" / f"import-{uuid4().hex}.tmp"
        digest = sha256()
        size_bytes = 0
        input_descriptor: int | None = None
        output_descriptor: int | None = None
        keep_temporary = False
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            input_descriptor = os.open(source, flags)
            before = os.fstat(input_descriptor)
            if not stat.S_ISREG(before.st_mode):
                return "invalid_source"
            output_descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            while block := os.read(input_descriptor, _BUFFER_SIZE):
                digest.update(block)
                size_bytes += len(block)
                view = memoryview(block)
                while view:
                    written = os.write(output_descriptor, view)
                    view = view[written:]
            os.fsync(output_descriptor)
            after = os.fstat(input_descriptor)
            stable = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if not stable or size_bytes != after.st_size:
                return "source_changed"
            keep_temporary = True
            return temporary, digest.hexdigest(), size_bytes
        except FileNotFoundError:
            return "source_not_found"
        except OSError:
            return "source_unreadable"
        finally:
            if input_descriptor is not None:
                os.close(input_descriptor)
            if output_descriptor is not None:
                os.close(output_descriptor)
            if temporary.exists() and not keep_temporary:
                temporary.unlink(missing_ok=True)

    def import_file(
        self,
        source: Path | str,
        *,
        project_id: str,
        purpose: str,
    ) -> WorkspaceOutcome:
        """Import bytes once and bind one immutable project/purpose reference."""

        if not _valid_label(project_id):
            return _manual("invalid_project_id")
        if not _valid_label(purpose):
            return _manual("invalid_purpose")
        if not self._ready:
            return _manual("workspace_unavailable")
        try:
            source_path = Path(source)
        except (TypeError, ValueError):
            return _manual("invalid_source")
        if not source_path.exists():
            return _manual("source_not_found")
        if source_path.is_symlink() or not source_path.is_file():
            return _manual("invalid_source")

        copied = self._copy_source(source_path)
        if isinstance(copied, str):
            return _manual(copied)
        temporary, digest, size_bytes = copied
        descriptor = self._descriptor(digest, size_bytes)
        target = self.root / descriptor.blob_ref
        created_target = False
        try:
            with self._connect() as connection:
                existing_reference = connection.execute(
                    "SELECT blob_ref FROM project_blob_refs WHERE project_id = ? AND purpose = ?",
                    (project_id, purpose),
                ).fetchone()
                if existing_reference is not None and existing_reference[0] != descriptor.blob_ref:
                    return _manual("reference_conflict")

                existing_blob = connection.execute(
                    "SELECT sha256, size_bytes FROM blobs WHERE blob_ref = ?",
                    (descriptor.blob_ref,),
                ).fetchone()
                if existing_blob is not None:
                    if existing_blob != (descriptor.sha256, descriptor.size_bytes):
                        return _manual("workspace_corrupt")
                    state = self._check_managed_blob(descriptor)
                    if state != "ok":
                        return _manual(state)
                elif target.exists():
                    state = self._check_managed_blob(descriptor)
                    if state != "ok":
                        return _manual(state)
                    connection.execute(
                        "INSERT INTO blobs(blob_ref, sha256, size_bytes, created_at, last_accessed_at) VALUES (?, ?, ?, ?, ?)",
                        (descriptor.blob_ref, descriptor.sha256, descriptor.size_bytes, time.time(), time.time()),
                    )
                else:
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    os.replace(temporary, target)
                    created_target = True
                    connection.execute(
                        "INSERT INTO blobs(blob_ref, sha256, size_bytes, created_at, last_accessed_at) VALUES (?, ?, ?, ?, ?)",
                        (descriptor.blob_ref, descriptor.sha256, descriptor.size_bytes, time.time(), time.time()),
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO project_blob_refs(project_id, purpose, blob_ref) VALUES (?, ?, ?)",
                    (project_id, purpose, descriptor.blob_ref),
                )
            reference = ProjectBlobReference(
                project_id=project_id,
                purpose=purpose,
                blob_ref=descriptor.blob_ref,
            )
            return WorkspaceOutcome(
                status="completed",
                code="ok",
                blob=descriptor,
                reference=reference,
            )
        except (OSError, sqlite3.Error):
            if created_target:
                try:
                    with self._connect() as connection:
                        retained = connection.execute(
                            "SELECT 1 FROM blobs WHERE blob_ref = ?", (descriptor.blob_ref,)
                        ).fetchone()
                    if retained is None:
                        target.unlink(missing_ok=True)
                except (OSError, sqlite3.Error):
                    pass
            return _manual("workspace_unavailable")
        finally:
            temporary.unlink(missing_ok=True)

    def verify_blob(self, blob_ref: str, *, now: float | None = None) -> WorkspaceOutcome:
        """Read back both the SQLite identity and managed bytes."""

        digest = _parse_blob_ref(blob_ref)
        if digest is None:
            return _manual("invalid_blob_ref")
        if not self._ready:
            return _manual("workspace_unavailable")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT sha256, size_bytes FROM blobs WHERE blob_ref = ?", (blob_ref,)
                ).fetchone()
        except sqlite3.Error:
            return _manual("workspace_unavailable")
        if row is None:
            return _manual("blob_not_found")
        sha256_identity, size_bytes = row
        if sha256_identity != f"sha256:{digest}" or not isinstance(size_bytes, int) or size_bytes < 0:
            return _manual("workspace_corrupt")
        descriptor = BlobDescriptor(
            blob_ref=blob_ref, sha256=sha256_identity, size_bytes=size_bytes
        )
        state = self._check_managed_blob(descriptor)
        if state != "ok":
            return _manual(state)
        timestamp = time.time() if now is None else now
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool) or not math.isfinite(timestamp):
            return _manual("invalid_timestamp")
        try:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE blobs SET last_accessed_at = ? WHERE blob_ref = ?",
                    (timestamp, blob_ref),
                )
        except sqlite3.Error:
            return _manual("workspace_unavailable")
        return WorkspaceOutcome(status="completed", code="ok", blob=descriptor)

    def release_project_reference(self, project_id: str, purpose: str) -> WorkspaceOutcome:
        """Release one project-owned reference without deleting managed bytes."""

        if not _valid_label(project_id):
            return _manual("invalid_project_id")
        if not _valid_label(purpose):
            return _manual("invalid_purpose")
        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM project_blob_refs WHERE project_id = ? AND purpose = ?",
                    (project_id, purpose),
                )
        except sqlite3.Error:
            return _manual("workspace_unavailable")
        return WorkspaceOutcome(status="completed", code="ok")

    def project_references(self, project_id: str) -> tuple[ProjectBlobReference, ...]:
        """Return stable project references without resolving local paths."""

        if not _valid_label(project_id) or not self._ready:
            return ()
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT purpose, blob_ref FROM project_blob_refs WHERE project_id = ? ORDER BY purpose, blob_ref",
                    (project_id,),
                ).fetchall()
        except sqlite3.Error:
            return ()
        return tuple(
            ProjectBlobReference(project_id=project_id, purpose=purpose, blob_ref=blob_ref)
            for purpose, blob_ref in rows
            if _parse_blob_ref(blob_ref) is not None
        )

    def lease_blob(self, blob_ref: str, lease_id: str, *, ttl_seconds: float, now: float | None = None) -> WorkspaceOutcome:
        """Renew one bounded lease without exposing local state."""
        if _parse_blob_ref(blob_ref) is None:
            return _manual("invalid_blob_ref")
        if not _valid_label(lease_id):
            return _manual("invalid_lease_id")
        if not isinstance(ttl_seconds, (int, float)) or isinstance(ttl_seconds, bool) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0 or ttl_seconds > 7 * 86400:
            return _manual("invalid_lease_ttl")
        timestamp = time.time() if now is None else now
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool) or not math.isfinite(timestamp):
            return _manual("invalid_timestamp")
        try:
            with self._connect() as connection:
                if connection.execute("SELECT 1 FROM blobs WHERE blob_ref = ?", (blob_ref,)).fetchone() is None:
                    return _manual("blob_not_found")
                connection.execute("INSERT OR REPLACE INTO blob_leases(blob_ref, lease_id, expires_at) VALUES (?, ?, ?)", (blob_ref, lease_id, timestamp + ttl_seconds))
        except sqlite3.Error:
            return _manual("workspace_unavailable")
        return WorkspaceOutcome(status="completed", code="ok")

    def release_lease(self, blob_ref: str, lease_id: str) -> WorkspaceOutcome:
        if _parse_blob_ref(blob_ref) is None:
            return _manual("invalid_blob_ref")
        if not _valid_label(lease_id):
            return _manual("invalid_lease_id")
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM blob_leases WHERE blob_ref = ? AND lease_id = ?", (blob_ref, lease_id))
        except sqlite3.Error:
            return _manual("workspace_unavailable")
        return WorkspaceOutcome(status="completed", code="ok")

    def pin_blob(self, blob_ref: str, pin_id: str) -> WorkspaceOutcome:
        if _parse_blob_ref(blob_ref) is None:
            return _manual("invalid_blob_ref")
        if not _valid_label(pin_id):
            return _manual("invalid_pin_id")
        try:
            with self._connect() as connection:
                if connection.execute("SELECT 1 FROM blobs WHERE blob_ref = ?", (blob_ref,)).fetchone() is None:
                    return _manual("blob_not_found")
                connection.execute("INSERT OR IGNORE INTO blob_pins(blob_ref, pin_id) VALUES (?, ?)", (blob_ref, pin_id))
        except sqlite3.Error:
            return _manual("workspace_unavailable")
        return WorkspaceOutcome(status="completed", code="ok")

    def unpin_blob(self, blob_ref: str, pin_id: str) -> WorkspaceOutcome:
        if _parse_blob_ref(blob_ref) is None:
            return _manual("invalid_blob_ref")
        if not _valid_label(pin_id):
            return _manual("invalid_pin_id")
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM blob_pins WHERE blob_ref = ? AND pin_id = ?", (blob_ref, pin_id))
        except sqlite3.Error:
            return _manual("workspace_unavailable")
        return WorkspaceOutcome(status="completed", code="ok")

    def collect_garbage(self, *, now: float | None = None, min_age_seconds: float = 14 * 86400, dry_run: bool = True) -> WorkspaceGcOutcome:
        timestamp = time.time() if now is None else now
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool) or not math.isfinite(timestamp):
            return _gc_manual("invalid_timestamp", dry_run)
        if not isinstance(min_age_seconds, (int, float)) or isinstance(min_age_seconds, bool) or not math.isfinite(min_age_seconds) or min_age_seconds < 0:
            return _gc_manual("invalid_age", dry_run)
        if not isinstance(dry_run, bool):
            return _gc_manual("invalid_dry_run")
        try:
            with self._connect() as connection:
                rows = connection.execute("""
                    SELECT b.blob_ref, b.sha256, b.size_bytes,
                           (SELECT COUNT(*) FROM project_blob_refs r WHERE r.blob_ref = b.blob_ref)
                    FROM blobs b
                    WHERE b.last_accessed_at <= ?
                      AND NOT EXISTS (SELECT 1 FROM project_blob_refs r WHERE r.blob_ref = b.blob_ref)
                      AND NOT EXISTS (SELECT 1 FROM blob_pins p WHERE p.blob_ref = b.blob_ref)
                      AND NOT EXISTS (SELECT 1 FROM blob_leases l WHERE l.blob_ref = b.blob_ref AND l.expires_at > ?)
                    ORDER BY b.blob_ref
                """, (timestamp - min_age_seconds, timestamp)).fetchall()
                try:
                    candidates = tuple(
                        WorkspaceGcCandidate(
                            blob_ref=blob_ref,
                            sha256=sha256_identity,
                            size_bytes=size_bytes,
                            reference_count=reference_count,
                            reason="unreferenced_unleased_unpinned_expired",
                        )
                        for blob_ref, sha256_identity, size_bytes, reference_count in rows
                        if _parse_blob_ref(blob_ref) is not None
                    )
                except (TypeError, ValueError):
                    return _gc_manual("workspace_corrupt", dry_run)
                if dry_run:
                    return WorkspaceGcOutcome(status="completed", code="ok", dry_run=True, candidates=candidates)
                for candidate in candidates:
                    descriptor = BlobDescriptor(
                        blob_ref=candidate.blob_ref,
                        sha256=candidate.sha256,
                        size_bytes=candidate.size_bytes,
                    )
                    state = self._check_managed_blob(descriptor)
                    if state != "ok":
                        return _gc_manual(state, False)
                deleted: list[str] = []
                for candidate in candidates:
                    blob_ref = candidate.blob_ref
                    path = self.root / candidate.blob_ref
                    path.unlink()
                    connection.execute("DELETE FROM blobs WHERE blob_ref = ?", (blob_ref,))
                    deleted.append(blob_ref)
                return WorkspaceGcOutcome(status="completed", code="ok", dry_run=False, candidates=candidates, deleted=tuple(deleted))
        except (OSError, sqlite3.Error):
            return _gc_manual("workspace_unavailable", dry_run)
