from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .resource_owner_registry import (
    ResourceOwnerConflict,
    ResourceOwnerInvalid,
    ResourceOwnerNotFound,
    ResourceOwnerRegistry,
    _require_resource_identity,
    require_tenant_id,
)


_DOCX_TOKEN = re.compile(r"[A-Za-z0-9_-]{8,160}\Z")
_RELATION_TYPE = re.compile(r"[a-z][a-z0-9_.:-]{0,63}\Z")


class ResourceAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResourceLink:
    resource_type: str
    canonical_resource_id: str
    tenant_id: str
    document_url: str
    policy: str
    status: str
    updated_at: int


class ResourceAccessService:
    """Canonical resource-link and graph ownership boundary.

    User reads are owner checked and only render tenant-owned Docx URLs. Bitable
    application, table and view identifiers never enter this service's output.
    """

    def __init__(
        self,
        registry: ResourceOwnerRegistry,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.registry = registry
        self.path = registry.path
        self._clock = clock
        self._write_lock = threading.Lock()
        migration = Path(__file__).resolve().parent.parent / "migrations" / "002_resource_access.sql"
        if not migration.is_file():
            raise ResourceAccessError("resource access schema migration is missing")
        with self._connect() as connection:
            connection.executescript(migration.read_text(encoding="utf-8"))

    def put_docx_link(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
        docx_token: str,
        policy: str,
    ) -> ResourceLink:
        resource_type, canonical_resource_id = _require_resource_identity(resource_type, canonical_resource_id)
        tenant_id = require_tenant_id(session_tenant_id)
        self.registry.assert_owner(resource_type, canonical_resource_id, session_tenant_id=tenant_id)
        token = self._require_docx_token(docx_token)
        if policy not in {"org_link_edit", "anyone_editable"}:
            raise ResourceOwnerInvalid("invalid document sharing policy")
        now = int(self._clock())
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT status FROM resource_links
                WHERE resource_type = ? AND canonical_resource_id = ?
                """,
                (resource_type, canonical_resource_id),
            ).fetchone()
            if existing is not None and str(existing[0]) != "active":
                raise ResourceOwnerConflict("revoked or archived document link cannot be reactivated")
            connection.execute(
                """
                INSERT INTO resource_links (
                    resource_type, canonical_resource_id, tenant_id, docx_token,
                    policy, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(resource_type, canonical_resource_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    docx_token = excluded.docx_token,
                    policy = excluded.policy,
                    status = 'active',
                    updated_at = excluded.updated_at
                """,
                (resource_type, canonical_resource_id, tenant_id, token, policy, now, now),
            )
        return self.get_docx_link(
            resource_type,
            canonical_resource_id,
            session_tenant_id=tenant_id,
        )

    def get_docx_link(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
    ) -> ResourceLink:
        resource_type, canonical_resource_id = _require_resource_identity(resource_type, canonical_resource_id)
        tenant_id = require_tenant_id(session_tenant_id)
        self.registry.assert_owner(resource_type, canonical_resource_id, session_tenant_id=tenant_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT tenant_id, docx_token, policy, status, updated_at
                FROM resource_links
                WHERE resource_type = ? AND canonical_resource_id = ?
                  AND tenant_id = ? AND status = 'active'
                """,
                (resource_type, canonical_resource_id, tenant_id),
            ).fetchone()
        if row is None:
            raise ResourceOwnerNotFound("resource not found")
        return ResourceLink(
            resource_type=resource_type,
            canonical_resource_id=canonical_resource_id,
            tenant_id=str(row[0]),
            document_url=f"https://feishu.cn/docx/{self._require_docx_token(str(row[1]))}",
            policy=str(row[2]),
            status=str(row[3]),
            updated_at=int(row[4]),
        )

    def set_link_status(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
        status: str,
    ) -> None:
        resource_type, canonical_resource_id = _require_resource_identity(resource_type, canonical_resource_id)
        tenant_id = require_tenant_id(session_tenant_id)
        self.registry.assert_owner(resource_type, canonical_resource_id, session_tenant_id=tenant_id)
        if status not in {"revoked", "archived"}:
            raise ResourceOwnerInvalid("invalid resource link status")
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE resource_links SET status = ?, updated_at = ?
                WHERE resource_type = ? AND canonical_resource_id = ?
                  AND tenant_id = ? AND status = 'active'
                """,
                (status, int(self._clock()), resource_type, canonical_resource_id, tenant_id),
            )
            if cursor.rowcount != 1:
                raise ResourceOwnerNotFound("resource not found")

    def add_graph_edge(
        self,
        parent_resource_type: str,
        parent_resource_id: str,
        child_resource_type: str,
        child_resource_id: str,
        *,
        session_tenant_id: str | int,
        relation_type: str,
    ) -> None:
        parent = _require_resource_identity(parent_resource_type, parent_resource_id)
        child = _require_resource_identity(child_resource_type, child_resource_id)
        tenant_id = require_tenant_id(session_tenant_id)
        self.registry.assert_owner(*parent, session_tenant_id=tenant_id)
        self.registry.assert_owner(*child, session_tenant_id=tenant_id)
        relation = str(relation_type or "").strip()
        if not _RELATION_TYPE.fullmatch(relation):
            raise ResourceOwnerInvalid("invalid relation type")
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO resource_graph_edges (
                    parent_resource_type, parent_resource_id,
                    child_resource_type, child_resource_id, relation_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (*parent, *child, relation, int(self._clock())),
            )

    @staticmethod
    def _require_docx_token(value: str) -> str:
        token = str(value or "").strip()
        if not _DOCX_TOKEN.fullmatch(token):
            raise ResourceOwnerInvalid("invalid Feishu Docx token")
        return token

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection
