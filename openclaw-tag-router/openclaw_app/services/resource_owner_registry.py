from __future__ import annotations

import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from media_vault.vault import canonical_tenant_id

from .canonical_resource_contracts import CANONICAL_RESOURCE_CONTRACTS, TENANT_PROJECTION_FIELD


_RESOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,511}\Z")


class ResourceOwnerError(RuntimeError):
    pass


class ResourceOwnerNotFound(ResourceOwnerError):
    """Uniform absent/cross-tenant/archived authorization failure."""


class ResourceOwnerConflict(ResourceOwnerError):
    pass


class ResourceOwnerInvalid(ResourceOwnerError):
    pass


class ResourceOwnerProjectionMismatch(ResourceOwnerError):
    """Feishu projection differs from the canonical owner and must not be trusted."""


@dataclass(frozen=True)
class ResourceOwner:
    resource_type: str
    canonical_resource_id: str
    tenant_id: str
    owner_revision: int
    status: str
    created_at: int
    archived_at: int | None = None


@dataclass(frozen=True)
class OwnerRepair:
    repair_id: str
    resource_type: str
    canonical_resource_id: str
    projection_source: str
    mismatch_kind: str
    canonical_tenant_id: str
    observed_tenant_id: str | None
    owner_revision: int
    status: str
    created_at: int


@dataclass(frozen=True)
class CreationRunSummary:
    canonical_resource_id: str
    title: str
    status: str
    entrypoint: str
    created_at: str
    updated_at: str
    sort_at: int
    summary_revision: int
    owner_revision: int


def require_tenant_id(value: str) -> str:
    return canonical_tenant_id(
        value,
        error=lambda: ResourceOwnerInvalid("tenant_id must be a canonical OpenClaw tenant UUID"),
    )


def _require_resource_identity(resource_type: str, canonical_resource_id: str) -> tuple[str, str]:
    normalized_type = str(resource_type or "").strip()
    if normalized_type not in CANONICAL_RESOURCE_CONTRACTS:
        raise ResourceOwnerInvalid("resource_type is not registered")
    normalized_id = str(canonical_resource_id or "").strip()
    if not _RESOURCE_ID.fullmatch(normalized_id):
        raise ResourceOwnerInvalid("canonical_resource_id is invalid")
    return normalized_type, normalized_id


class ResourceOwnerRegistry:
    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._write_lock = threading.Lock()
        self._initialize()
        self.path.chmod(0o600)

    def create(self, resource_type: str, canonical_resource_id: str, *, session_tenant_id: str | int) -> ResourceOwner:
        resource_type, canonical_resource_id = _require_resource_identity(resource_type, canonical_resource_id)
        tenant_id = require_tenant_id(session_tenant_id)
        now = int(self._clock())
        try:
            with self._write_lock, self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO resource_owners (
                        resource_type, canonical_resource_id, tenant_id,
                        owner_revision, status, created_at, archived_at
                    ) VALUES (?, ?, ?, 1, 'active', ?, NULL)
                    """,
                    (resource_type, canonical_resource_id, tenant_id, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ResourceOwnerConflict("resource owner already exists") from exc
        return ResourceOwner(resource_type, canonical_resource_id, tenant_id, 1, "active", now)

    def get(self, resource_type: str, canonical_resource_id: str) -> ResourceOwner:
        resource_type, canonical_resource_id = _require_resource_identity(resource_type, canonical_resource_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT tenant_id, owner_revision, status, created_at, archived_at
                FROM resource_owners
                WHERE resource_type = ? AND canonical_resource_id = ?
                """,
                (resource_type, canonical_resource_id),
            ).fetchone()
        if row is None:
            raise ResourceOwnerNotFound("resource not found")
        return ResourceOwner(
            resource_type,
            canonical_resource_id,
            str(row[0]),
            int(row[1]),
            str(row[2]),
            int(row[3]),
            int(row[4]) if row[4] is not None else None,
        )

    def assert_owner(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
    ) -> ResourceOwner:
        expected = require_tenant_id(session_tenant_id)
        owner = self.get(resource_type, canonical_resource_id)
        if owner.status != "active" or owner.tenant_id != expected:
            raise ResourceOwnerNotFound("resource not found")
        return owner

    def list_by_tenant(
        self,
        session_tenant_id: str | int,
        *,
        resource_type: str | None = None,
        include_archived: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ResourceOwner]:
        tenant_id = require_tenant_id(session_tenant_id)
        if resource_type is not None:
            resource_type, _ = _require_resource_identity(resource_type, "placeholder")
        if not 1 <= limit <= 500 or offset < 0:
            raise ResourceOwnerInvalid("invalid pagination")
        clauses = ["tenant_id = ?"]
        values: list[object] = [tenant_id]
        if resource_type is not None:
            clauses.append("resource_type = ?")
            values.append(resource_type)
        if not include_archived:
            clauses.append("status = 'active'")
        values.extend([limit, offset])
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT resource_type, canonical_resource_id, tenant_id,
                       owner_revision, status, created_at, archived_at
                FROM resource_owners
                WHERE """ + " AND ".join(clauses) + """
                ORDER BY resource_type, canonical_resource_id
                LIMIT ? OFFSET ?
                """,
                values,
            ).fetchall()
        return [
            ResourceOwner(str(row[0]), str(row[1]), str(row[2]), int(row[3]), str(row[4]), int(row[5]), int(row[6]) if row[6] is not None else None)
            for row in rows
        ]

    def list_all_by_tenant(
        self,
        session_tenant_id: str | int,
        *,
        resource_type: str | None = None,
        include_archived: bool = False,
    ) -> list[ResourceOwner]:
        owners: list[ResourceOwner] = []
        offset = 0
        while True:
            page = self.list_by_tenant(
                session_tenant_id,
                resource_type=resource_type,
                include_archived=include_archived,
                limit=500,
                offset=offset,
            )
            owners.extend(page)
            if len(page) < 500:
                return owners
            offset += len(page)

    def upsert_creation_run_summary(
        self,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
        fields: Mapping[str, Any],
    ) -> CreationRunSummary:
        resource_type, canonical_resource_id = _require_resource_identity(
            "media.creation_run", canonical_resource_id
        )
        tenant_id = require_tenant_id(session_tenant_id)
        title = self._summary_text(fields.get("input_summary") or fields.get("title"), 500)
        status = self._summary_text(fields.get("status"), 100)
        entrypoint = self._summary_text(fields.get("entrypoint"), 200)
        created_at_text = self._summary_text(fields.get("created_at"), 100)
        updated_at_text = self._summary_text(fields.get("updated_at"), 100)
        now = int(self._clock())
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            owner = connection.execute(
                """
                SELECT owner_revision, created_at
                FROM resource_owners
                WHERE resource_type = ? AND canonical_resource_id = ?
                  AND tenant_id = ? AND status = 'active'
                """,
                (resource_type, canonical_resource_id, tenant_id),
            ).fetchone()
            if owner is None:
                raise ResourceOwnerNotFound("resource not found")
            existing = connection.execute(
                """
                SELECT title, status, entrypoint, created_at_text, updated_at_text,
                       sort_at, summary_revision
                FROM creation_run_summaries
                WHERE canonical_resource_id = ?
                """,
                (canonical_resource_id,),
            ).fetchone()
            if existing is not None:
                title = title or str(existing[0])
                status = status or str(existing[1])
                entrypoint = entrypoint or str(existing[2])
                created_at_text = str(existing[3]) or created_at_text
                updated_at_text = updated_at_text or str(existing[4])
            title = title or canonical_resource_id
            status = status or "unknown"
            sort_at = self._summary_timestamp(created_at_text, default=int(owner[1]))
            search_text = " ".join(
                (canonical_resource_id, title, status, entrypoint, created_at_text, updated_at_text)
            ).casefold()
            connection.execute(
                """
                INSERT INTO creation_run_summaries (
                    canonical_resource_id, title, status, entrypoint,
                    created_at_text, updated_at_text, sort_at, search_text,
                    summary_revision, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(canonical_resource_id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    entrypoint = excluded.entrypoint,
                    created_at_text = excluded.created_at_text,
                    updated_at_text = excluded.updated_at_text,
                    sort_at = excluded.sort_at,
                    search_text = excluded.search_text,
                    summary_revision = creation_run_summaries.summary_revision + 1,
                    indexed_at = excluded.indexed_at
                """,
                (
                    canonical_resource_id,
                    title,
                    status,
                    entrypoint,
                    created_at_text,
                    updated_at_text,
                    sort_at,
                    search_text,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT title, status, entrypoint, created_at_text, updated_at_text,
                       sort_at, summary_revision
                FROM creation_run_summaries WHERE canonical_resource_id = ?
                """,
                (canonical_resource_id,),
            ).fetchone()
        assert row is not None
        return CreationRunSummary(
            canonical_resource_id=canonical_resource_id,
            title=str(row[0]),
            status=str(row[1]),
            entrypoint=str(row[2]),
            created_at=str(row[3]),
            updated_at=str(row[4]),
            sort_at=int(row[5]),
            summary_revision=int(row[6]),
            owner_revision=int(owner[0]),
        )

    def list_creation_run_summaries(
        self,
        session_tenant_id: str | int,
        *,
        search: str,
        limit: int,
        offset: int,
    ) -> list[CreationRunSummary]:
        tenant_id = require_tenant_id(session_tenant_id)
        if not 1 <= limit <= 501 or offset < 0:
            raise ResourceOwnerInvalid("invalid pagination")
        normalized_search = self._summary_text(search, 500).casefold()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT summaries.canonical_resource_id, summaries.title,
                       summaries.status, summaries.entrypoint,
                       summaries.created_at_text, summaries.updated_at_text,
                       summaries.sort_at, summaries.summary_revision,
                       owners.owner_revision
                FROM resource_owners AS owners
                     INDEXED BY resource_owners_tenant_status_idx
                JOIN creation_run_summaries AS summaries
                  ON summaries.canonical_resource_id = owners.canonical_resource_id
                WHERE owners.tenant_id = ?
                  AND owners.status = 'active'
                  AND owners.resource_type = 'media.creation_run'
                  AND (? = '' OR instr(summaries.search_text, ?) > 0)
                ORDER BY summaries.sort_at DESC,
                         summaries.canonical_resource_id DESC
                LIMIT ? OFFSET ?
                """,
                (tenant_id, normalized_search, normalized_search, limit, offset),
            ).fetchall()
        return [
            CreationRunSummary(
                canonical_resource_id=str(row[0]),
                title=str(row[1]),
                status=str(row[2]),
                entrypoint=str(row[3]),
                created_at=str(row[4]),
                updated_at=str(row[5]),
                sort_at=int(row[6]),
                summary_revision=int(row[7]),
                owner_revision=int(row[8]),
            )
            for row in rows
        ]

    def creation_run_summary_state(self, session_tenant_id: str | int) -> tuple[int, int, int]:
        tenant_id = require_tenant_id(session_tenant_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(summaries.summary_revision), 0),
                       COALESCE(SUM(owners.owner_revision), 0)
                FROM resource_owners AS owners
                     INDEXED BY resource_owners_tenant_status_idx
                JOIN creation_run_summaries AS summaries
                  ON summaries.canonical_resource_id = owners.canonical_resource_id
                WHERE owners.tenant_id = ?
                  AND owners.status = 'active'
                  AND owners.resource_type = 'media.creation_run'
                """,
                (tenant_id,),
            ).fetchone()
        assert row is not None
        return int(row[0]), int(row[1]), int(row[2])

    @staticmethod
    def _summary_text(value: Any, limit: int) -> str:
        return str(value or "").strip()[:limit]

    @staticmethod
    def _summary_timestamp(value: str, *, default: int) -> int:
        if not value:
            return default
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return default
        return max(0, int(parsed.timestamp()))

    def archive(self, resource_type: str, canonical_resource_id: str, *, session_tenant_id: str | int) -> ResourceOwner:
        resource_type, canonical_resource_id = _require_resource_identity(resource_type, canonical_resource_id)
        tenant_id = require_tenant_id(session_tenant_id)
        now = int(self._clock())
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE resource_owners
                SET status = 'archived', archived_at = ?
                WHERE resource_type = ? AND canonical_resource_id = ?
                  AND tenant_id = ? AND status = 'active'
                """,
                (now, resource_type, canonical_resource_id, tenant_id),
            )
            if cursor.rowcount != 1:
                raise ResourceOwnerNotFound("resource not found")
        return self.get(resource_type, canonical_resource_id)

    def build_feishu_projection(self, resource_type: str, canonical_resource_id: str) -> dict[str, str]:
        owner = self.get(resource_type, canonical_resource_id)
        contract = CANONICAL_RESOURCE_CONTRACTS[owner.resource_type]
        if owner.status != "active" or contract.tenant_projection_field != TENANT_PROJECTION_FIELD:
            raise ResourceOwnerNotFound("resource not found")
        return {TENANT_PROJECTION_FIELD: owner.tenant_id}

    def inspect_feishu_projection(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        observed_tenant_id: object,
        projection_source: str,
    ) -> OwnerRepair | None:
        owner = self.get(resource_type, canonical_resource_id)
        if owner.status != "active":
            raise ResourceOwnerNotFound("resource not found")
        observed_raw = "" if observed_tenant_id is None else str(observed_tenant_id).strip()
        if not observed_raw:
            mismatch_kind = "missing"
            observed = None
        else:
            try:
                observed_canonical = str(uuid.UUID(observed_raw))
            except ValueError:
                observed_canonical = ""
            if observed_canonical != observed_raw:
                mismatch_kind = "invalid"
                observed = observed_raw[:128]
            elif observed_raw != owner.tenant_id:
                mismatch_kind = "mismatch"
                observed = observed_raw
            else:
                return None
        source = str(projection_source or "").strip()
        if not re.fullmatch(r"feishu:[A-Za-z0-9_.:/-]{1,240}", source):
            raise ResourceOwnerInvalid("projection_source is invalid")
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT repair_id, mismatch_kind, canonical_tenant_id,
                       observed_tenant_id, owner_revision, status, created_at
                FROM resource_owner_repairs
                WHERE resource_type = ? AND canonical_resource_id = ?
                  AND projection_source = ? AND status = 'pending'
                """,
                (owner.resource_type, owner.canonical_resource_id, source),
            ).fetchone()
            if existing is not None:
                return OwnerRepair(str(existing[0]), owner.resource_type, owner.canonical_resource_id, source, str(existing[1]), str(existing[2]), str(existing[3]) if existing[3] is not None else None, int(existing[4]), str(existing[5]), int(existing[6]))
            repair_id = "repair_" + secrets.token_urlsafe(18)
            now = int(self._clock())
            connection.execute(
                """
                INSERT INTO resource_owner_repairs (
                    repair_id, resource_type, canonical_resource_id,
                    projection_source, mismatch_kind, canonical_tenant_id,
                    observed_tenant_id, owner_revision, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (repair_id, owner.resource_type, owner.canonical_resource_id, source, mismatch_kind, owner.tenant_id, observed, owner.owner_revision, now),
            )
        return OwnerRepair(repair_id, owner.resource_type, owner.canonical_resource_id, source, mismatch_kind, owner.tenant_id, observed, owner.owner_revision, "pending", now)

    def assert_feishu_projection(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        observed_tenant_id: object,
        projection_source: str,
    ) -> ResourceOwner:
        repair = self.inspect_feishu_projection(
            resource_type,
            canonical_resource_id,
            observed_tenant_id=observed_tenant_id,
            projection_source=projection_source,
        )
        if repair is not None:
            raise ResourceOwnerProjectionMismatch("tenant projection mismatch")
        return self.get(resource_type, canonical_resource_id)

    def list_repairs(self, *, status: str = "pending", limit: int = 100) -> list[OwnerRepair]:
        if status not in {"pending", "resolved"} or not 1 <= limit <= 500:
            raise ResourceOwnerInvalid("invalid repair query")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT repair_id, resource_type, canonical_resource_id,
                       projection_source, mismatch_kind, canonical_tenant_id,
                       observed_tenant_id, owner_revision, status, created_at
                FROM resource_owner_repairs WHERE status = ?
                ORDER BY created_at, repair_id LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        return [OwnerRepair(str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]), str(row[6]) if row[6] is not None else None, int(row[7]), str(row[8]), int(row[9])) for row in rows]

    def resolve_repair(
        self,
        repair_id: str,
        *,
        actor_user_id: str | int,
        resolution_note: str,
    ) -> None:
        normalized_id = str(repair_id or "").strip()
        actor = require_tenant_id(actor_user_id)
        note = str(resolution_note or "").strip()
        if not re.fullmatch(r"repair_[A-Za-z0-9_-]{16,128}", normalized_id):
            raise ResourceOwnerInvalid("repair_id is invalid")
        if not note or len(note) > 1000:
            raise ResourceOwnerInvalid("resolution_note is required")
        now = int(self._clock())
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE resource_owner_repairs
                SET status = 'resolved', resolved_at = ?,
                    resolved_by_user_id = ?, resolution_note = ?
                WHERE repair_id = ? AND status = 'pending'
                """,
                (now, actor, note, normalized_id),
            )
            if cursor.rowcount != 1:
                raise ResourceOwnerNotFound("repair not found")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        migration = Path(__file__).resolve().parent.parent / "migrations" / "001_resource_owner_registry.sql"
        if not migration.is_file():
            raise ResourceOwnerError("resource owner schema migration is missing")
        with self._connect() as connection:
            connection.executescript(migration.read_text(encoding="utf-8"))
