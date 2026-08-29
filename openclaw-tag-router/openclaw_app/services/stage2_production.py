"""Fail-closed production composition for the Stage-2 HTTP gateway.

The factory deliberately owns no account database, Binding repository, Lark
credential, or document transport. Production callers must inject each of
those canonical dependencies. The concrete persistence supplied here is the
Stage-2-owned SQLite state used for personal and organization artifacts,
external write receipts, and runtime receipts.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .stage2_context import CapabilityEffectRegistry
from .stage2_external_document import ExternalDocumentWriter, SQLiteWriteReceiptStore
from .stage2_gateway import Stage2Gateway
from .stage2_organization_pipeline import OrganizationContentPipeline, SQLiteOrganizationContentStore
from .stage2_personal_store import SQLitePersonalContentStore
from .stage2_runtime import IdempotencyConflict, IdempotencyInProgress, Stage2Runtime
from .stage2_server_context import (
    AuthenticatedSessionProvider,
    CurrentBindingProvider,
    ServerStage2ContextProviders,
    TenantProfileReader,
    TenantSourceReader,
    current_request_session_token,
)


class Stage2ProductionAssemblyError(RuntimeError):
    """Stable failure for an incomplete or unsafe production composition."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class SQLiteStage2ReceiptStore:
    """Restart-safe top-level Stage-2 receipt and idempotency storage."""

    _SCHEMA_VERSION = 3
    _CLAIM_LEASE_SECONDS = 300.0
    _REQUIRED_COLUMNS = {
        "stage2_runtime_meta": {"schema_version"},
        "stage2_runtime_receipts": {
            "receipt_key",
            "request_fingerprint",
            "response_json",
            "created_at",
        },
        "stage2_runtime_claims": {
            "receipt_key",
            "request_fingerprint",
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
            raise Stage2ProductionAssemblyError(
                "volatile_store_forbidden",
                "production Stage-2 receipt storage must be file-backed",
            )
        self.path = Path(raw_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError as exc:
            raise Stage2ProductionAssemblyError(
                "state_store_permissions",
                "production Stage-2 receipt directory permissions could not be restricted",
            ) from exc
        self._lock = threading.RLock()
        self._initialize()
        try:
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise Stage2ProductionAssemblyError(
                "state_store_permissions",
                "production Stage-2 receipt file permissions could not be restricted",
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
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
                raise Stage2ProductionAssemblyError(
                    "receipt_schema_invalid",
                    f"production Stage-2 receipt schema is missing {table} columns: {missing}",
                )

    def _initialize(self) -> None:
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS stage2_runtime_meta "
                "(schema_version INTEGER NOT NULL)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS stage2_runtime_receipts (
                    receipt_key TEXT PRIMARY KEY,
                    request_fingerprint TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS stage2_runtime_claims (
                    receipt_key TEXT PRIMARY KEY,
                    request_fingerprint TEXT NOT NULL,
                    lease_until REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._validate_schema(connection)
            rows = connection.execute(
                "SELECT schema_version FROM stage2_runtime_meta"
            ).fetchall()
            if not rows:
                connection.execute(
                    "INSERT INTO stage2_runtime_meta(schema_version) VALUES (?)",
                    (self._SCHEMA_VERSION,),
                )
            else:
                try:
                    schema_version = int(rows[0][0])
                except (TypeError, ValueError, IndexError) as exc:
                    raise Stage2ProductionAssemblyError(
                        "receipt_schema_unsupported",
                        "production Stage-2 receipt schema is unsupported",
                    ) from exc
                if len(rows) != 1 or schema_version not in {1, 2, self._SCHEMA_VERSION}:
                    raise Stage2ProductionAssemblyError(
                        "receipt_schema_unsupported",
                        "production Stage-2 receipt schema is unsupported",
                    )
                if schema_version in {1, 2}:
                    # Versions 2/3 add durable pre-side-effect claims and a
                    # lease. The migration is additive and keeps old receipts.
                    connection.execute(
                        "UPDATE stage2_runtime_meta SET schema_version = ?",
                        (self._SCHEMA_VERSION,),
                    )
            claim_columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(stage2_runtime_claims)"
                ).fetchall()
            }
            if "lease_until" not in claim_columns:
                connection.execute(
                    "ALTER TABLE stage2_runtime_claims ADD COLUMN lease_until REAL NOT NULL DEFAULT 0"
                )
            if "lease_until" not in {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(stage2_runtime_claims)"
                ).fetchall()
            }:
                raise Stage2ProductionAssemblyError(
                    "receipt_schema_invalid",
                    "production Stage-2 receipt claim schema is incomplete",
                )
            connection.commit()

    @staticmethod
    def _response(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise Stage2ProductionAssemblyError(
                "receipt_corrupt",
                "stored Stage-2 runtime receipt is invalid",
            ) from exc
        if not isinstance(value, dict):
            raise Stage2ProductionAssemblyError(
                "receipt_corrupt",
                "stored Stage-2 runtime receipt must be an object",
            )
        if "publishable" in value and value["publishable"] is not False:
            raise Stage2ProductionAssemblyError(
                "receipt_corrupt",
                "stored Stage-2 runtime receipt cannot be publishable",
            )
        if "readyForPublish" in value and type(value["readyForPublish"]) is not bool:
            raise Stage2ProductionAssemblyError(
                "receipt_corrupt",
                "stored Stage-2 runtime receipt has an invalid publish state",
            )
        if value.get("artifactStatus") == "needs_attention" and value.get("readyForPublish") is not False:
            raise Stage2ProductionAssemblyError(
                "receipt_corrupt",
                "failed Stage-2 runtime receipt cannot be ready for publish",
            )
        artifact = value.get("artifact")
        if isinstance(artifact, Mapping) and (
            artifact.get("published") is True or artifact.get("publishable") is True
        ):
            raise Stage2ProductionAssemblyError(
                "receipt_corrupt",
                "stored Stage-2 artifact cannot be publishable",
            )
        return value

    def get(self, key: str) -> Mapping[str, Any] | None:
        with self._lock, self._connection_scope() as connection:
            row = connection.execute(
                "SELECT request_fingerprint, response_json FROM stage2_runtime_receipts WHERE receipt_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "request_fingerprint": str(row["request_fingerprint"]),
            "response": self._response(str(row["response_json"])),
        }

    def put(self, key: str, request_fingerprint: str, response: Mapping[str, Any]) -> None:
        if not isinstance(response, Mapping):
            raise Stage2ProductionAssemblyError(
                "receipt_invalid",
                "Stage-2 runtime receipt response must be an object",
            )
        payload = json.dumps(
            dict(response),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._response(payload)
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_fingerprint, response_json FROM stage2_runtime_receipts WHERE receipt_key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                if (
                    str(row["request_fingerprint"]) != request_fingerprint
                    or str(row["response_json"]) != payload
                ):
                    connection.rollback()
                    raise IdempotencyConflict()
                connection.execute(
                    "DELETE FROM stage2_runtime_claims WHERE receipt_key = ? AND request_fingerprint = ?",
                    (key, request_fingerprint),
                )
                connection.commit()
                return
            connection.execute(
                "INSERT INTO stage2_runtime_receipts(receipt_key, request_fingerprint, response_json) VALUES (?, ?, ?)",
                (key, request_fingerprint, payload),
            )
            connection.execute(
                "DELETE FROM stage2_runtime_claims WHERE receipt_key = ? AND request_fingerprint = ?",
                (key, request_fingerprint),
            )
            connection.commit()

    def claim(self, key: str, request_fingerprint: str) -> Mapping[str, Any] | None:
        """Atomically reserve a missing receipt before external side effects."""

        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_fingerprint, response_json FROM stage2_runtime_receipts WHERE receipt_key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                if str(row["request_fingerprint"]) != request_fingerprint:
                    connection.rollback()
                    raise IdempotencyConflict()
                connection.commit()
                return {
                    "request_fingerprint": str(row["request_fingerprint"]),
                    "response": self._response(str(row["response_json"])),
                }
            claim = connection.execute(
                "SELECT request_fingerprint, lease_until FROM stage2_runtime_claims WHERE receipt_key = ?",
                (key,),
            ).fetchone()
            if claim is not None:
                if str(claim["request_fingerprint"]) != request_fingerprint:
                    connection.rollback()
                    raise IdempotencyConflict()
                if float(claim["lease_until"]) > time.time():
                    connection.rollback()
                    raise IdempotencyInProgress()
                connection.execute(
                    "DELETE FROM stage2_runtime_claims WHERE receipt_key = ? AND request_fingerprint = ?",
                    (key, request_fingerprint),
                )
            connection.execute(
                "INSERT INTO stage2_runtime_claims(receipt_key, request_fingerprint, lease_until) VALUES (?, ?, ?)",
                (key, request_fingerprint, time.time() + self._CLAIM_LEASE_SECONDS),
            )
            connection.commit()
            return None

    def release(self, key: str, request_fingerprint: str) -> None:
        with self._lock, self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM stage2_runtime_claims WHERE receipt_key = ? AND request_fingerprint = ?",
                (key, request_fingerprint),
            )
            connection.commit()


@dataclass(frozen=True, slots=True)
class Stage2ProductionDependencies:
    """Canonical production dependencies required to enable Stage-2."""

    capability_id: str
    effect_registry: CapabilityEffectRegistry
    state_database_path: str | Path
    session_loader: Callable[[str], Mapping[str, Any] | None]
    binding_loader: Callable[[str], Mapping[str, Any] | None]
    profile_loader: Callable[[str, str], Mapping[str, Any] | None]
    source_loader: Callable[[str, str, tuple[str, ...]], Any]
    personal_writer: Any
    organization_adapter: Any
    token_provider: Callable[[], str | None] = current_request_session_token


def _require_callable(value: Any, label: str) -> None:
    if not callable(value):
        raise Stage2ProductionAssemblyError(
            "production_dependency_missing",
            f"{label} production dependency is required",
        )


def build_stage2_production_gateway(
    dependencies: Stage2ProductionDependencies,
) -> Stage2Gateway:
    """Build one gateway only after every production dependency is present."""

    if not isinstance(dependencies, Stage2ProductionDependencies):
        raise Stage2ProductionAssemblyError(
            "production_dependencies_invalid",
            "Stage-2 production dependencies are required",
        )
    if not isinstance(dependencies.effect_registry, CapabilityEffectRegistry):
        raise Stage2ProductionAssemblyError(
            "effect_registry_required",
            "a production capability effect registry is required",
        )
    try:
        dependencies.effect_registry.require(dependencies.capability_id)
    except Exception as exc:
        raise Stage2ProductionAssemblyError(
            "capability_not_registered",
            "the Stage-2 production capability is not registered",
        ) from exc
    for value, label in (
        (dependencies.session_loader, "session loader"),
        (dependencies.binding_loader, "Binding loader"),
        (dependencies.profile_loader, "tenant profile loader"),
        (dependencies.source_loader, "tenant source loader"),
        (dependencies.token_provider, "request token provider"),
    ):
        _require_callable(value, label)
    _require_callable(getattr(dependencies.personal_writer, "write", None), "personal writer")
    _require_callable(getattr(dependencies.organization_adapter, "write", None), "organization adapter write")
    _require_callable(getattr(dependencies.organization_adapter, "readback", None), "organization adapter readback")

    database_path = str(dependencies.state_database_path).strip()
    if not database_path:
        raise Stage2ProductionAssemblyError(
            "state_store_required",
            "a production Stage-2 state database path is required",
        )
    if database_path == ":memory:":
        raise Stage2ProductionAssemblyError(
            "volatile_store_forbidden",
            "production Stage-2 state must be file-backed",
        )

    session_provider = AuthenticatedSessionProvider(
        dependencies.session_loader,
        dependencies.token_provider,
    )
    contexts = ServerStage2ContextProviders(
        session_provider,
        CurrentBindingProvider(dependencies.binding_loader),
        TenantProfileReader(dependencies.profile_loader),
    )
    try:
        runtime = Stage2Runtime(
            source_reader=TenantSourceReader(dependencies.source_loader),
            personal_store=SQLitePersonalContentStore(database_path),
            personal_writer=dependencies.personal_writer,
            organization_pipeline=OrganizationContentPipeline(
                document_writer=ExternalDocumentWriter(SQLiteWriteReceiptStore(database_path)),
                store=SQLiteOrganizationContentStore(database_path),
            ),
            organization_adapter=dependencies.organization_adapter,
            receipt_store=SQLiteStage2ReceiptStore(database_path),
            effect_registry=dependencies.effect_registry,
        )
    except Stage2ProductionAssemblyError:
        raise
    except Exception as exc:
        raise Stage2ProductionAssemblyError(
            "state_store_init_failed",
            "production Stage-2 state stores could not be initialized",
        ) from exc
    return Stage2Gateway(
        runtime,
        capability_id=dependencies.capability_id,
        personal_session_provider=contexts.personal_session,
        organization_context_provider=contexts.organization_context,
    )


__all__ = [
    "SQLiteStage2ReceiptStore",
    "Stage2ProductionAssemblyError",
    "Stage2ProductionDependencies",
    "build_stage2_production_gateway",
]
