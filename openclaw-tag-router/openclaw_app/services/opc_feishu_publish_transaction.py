"""Durable local transactions for prepared OPC Feishu publication plans.

This module owns transaction state only. Remote writes are supplied by callers as
operation callbacks, keeping the Feishu client and document mutation authority in
the existing service layer.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping


TRANSACTION_SCHEMA_VERSION = "openclaw.opc-feishu-publish-transaction.v1"
ROLLBACK_SCHEMA_VERSION = "openclaw.opc-feishu-rollback-plan.v1"
_SOURCE_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_TARGET_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_COMPILER_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:-]{0,119}$")
_PUBLICATION_INTENT_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,119}$")
_OWNER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_STATES = {
    "planned",
    "reconciliation_required",
    "recovery_ready",
    "rollback_ready",
    "committed",
}
_OBSERVATION_STATUSES = {"present", "absent", "conflict"}
_MAX_OPERATIONS = 10000


def canonical_json(value: Any) -> str:
    """Return the one accepted canonical encoding for strict JSON values."""

    def validate(item: Any, path: str) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"{path} contains a non-finite number")
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                validate(child, f"{path}[{index}]")
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} contains a non-string key")
                validate(child, f"{path}.{key}")
            return
        raise ValueError(f"{path} is not valid JSON")

    validate(value, "value")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_identity(
    source_sha256: str,
    target_node_token: str,
    compiler_version: str,
    publication_intent: str,
) -> tuple[str, str, str, str]:
    values = (source_sha256, target_node_token, compiler_version, publication_intent)
    if not all(isinstance(value, str) for value in values):
        raise ValueError("transaction identity fields must be strings")
    if not _SOURCE_SHA256_RE.fullmatch(values[0]):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    if not _TARGET_TOKEN_RE.fullmatch(values[1]):
        raise ValueError("target_node_token is malformed")
    if not _COMPILER_VERSION_RE.fullmatch(values[2]):
        raise ValueError("compiler_version is malformed")
    if not _PUBLICATION_INTENT_RE.fullmatch(values[3]):
        raise ValueError("publication_intent is malformed")
    return values


def _identity_key(
    source_sha256: str,
    target_node_token: str,
    compiler_version: str,
    publication_intent: str,
    tenant_id: str,
    resource_owner_user_id: str,
) -> str:
    identity_json = canonical_json(
        {
            "compiler_version": compiler_version,
            "publication_intent": publication_intent,
            "resource_owner_user_id": resource_owner_user_id,
            "source_sha256": source_sha256,
            "target_node_token": target_node_token,
            "tenant_id": tenant_id,
        }
    )
    return f"opc-feishu-{_sha256_text(identity_json)}"


def _require_owner_identity(tenant_id: str, resource_owner_user_id: str) -> tuple[str, str]:
    if not isinstance(tenant_id, str) or not _OWNER_ID_RE.fullmatch(tenant_id):
        raise ValueError("tenant identity is malformed")
    if not isinstance(resource_owner_user_id, str) or not _OWNER_ID_RE.fullmatch(
        resource_owner_user_id
    ):
        raise ValueError("resource owner identity is malformed")
    return tenant_id, resource_owner_user_id


def _durable_prepared_plan(
    prepared_plan: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str]:
    if not isinstance(prepared_plan, dict):
        raise ValueError("prepared_plan must be an object")
    normalized_plan = json.loads(canonical_json(prepared_plan))
    authorization = normalized_plan.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("type") != "resource_owner_oauth":
        raise ValueError("prepared plan must contain resource owner authorization")
    tenant_id, resource_owner_user_id = _require_owner_identity(
        authorization.get("tenant_id"),
        authorization.get("resource_owner_user_id"),
    )
    allowed = {"type", "tenant_id", "resource_owner_user_id", "credential_fingerprint"}
    if set(authorization) - allowed:
        raise ValueError("prepared plan authorization contains execution credentials")
    authorization.pop("credential_fingerprint", None)
    return normalized_plan, tenant_id, resource_owner_user_id


def _prepared_operations(prepared_plan: dict[str, Any]) -> list[dict[str, Any]]:
    children = prepared_plan.get("children")
    image_uploads = prepared_plan.get("image_uploads", [])
    if not isinstance(children, list) or not children:
        raise ValueError("prepared plan must contain at least one child operation")
    if len(children) > _MAX_OPERATIONS:
        raise ValueError("prepared plan operation count exceeds the transaction bound")
    if not isinstance(image_uploads, list):
        raise ValueError("prepared plan image_uploads must be a list")

    upload_by_index: dict[int, dict[str, Any]] = {}
    for upload in image_uploads:
        if not isinstance(upload, dict):
            raise ValueError("prepared plan image upload is malformed")
        child_index = upload.get("child_index")
        if (
            isinstance(child_index, bool)
            or not isinstance(child_index, int)
            or child_index < 0
            or child_index >= len(children)
            or child_index in upload_by_index
        ):
            raise ValueError("prepared plan image upload child_index is malformed")
        upload_by_index[child_index] = upload

    operations: list[dict[str, Any]] = []
    for index, child in enumerate(children):
        payload: dict[str, Any] = {
            "action": "publish_child",
            "child": child,
            "child_index": index,
        }
        if index in upload_by_index:
            payload["image_upload"] = upload_by_index[index]
        operation_sha256 = _sha256_text(canonical_json(payload))
        operations.append(
            {
                "operation_id": f"op-{index:06d}-{operation_sha256[:24]}",
                "operation_index": index,
                "operation_sha256": operation_sha256,
                "payload": payload,
            }
        )
    return operations


class OpcFeishuPublishTransactionStore:
    """SQLite ledger for one canonical prepared-plan transaction protocol."""

    def __init__(self, ledger_path: str | Path):
        raw_path = str(ledger_path or "").strip()
        if not raw_path or raw_path == ":memory:":
            raise ValueError("ledger_path must identify a durable SQLite file")
        self.ledger_path = Path(raw_path).expanduser()
        if not self.ledger_path.parent.exists():
            raise ValueError("ledger_path parent directory does not exist")
        if self.ledger_path.exists() and self.ledger_path.is_dir():
            raise ValueError("ledger_path must identify a file")
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.ledger_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'opc_feishu_publish_transactions'"
            ).fetchone()
            if existing is not None:
                columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(opc_feishu_publish_transactions)"
                    ).fetchall()
                }
                required = {"tenant_id", "resource_owner_user_id"}
                if not required.issubset(columns):
                    raise ValueError(
                        "ownerless OPC transaction ledger requires an explicit one-time migration"
                    )
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS opc_feishu_publish_transactions (
                    idempotency_key TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    target_node_token TEXT NOT NULL,
                    compiler_version TEXT NOT NULL,
                    publication_intent TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    resource_owner_user_id TEXT NOT NULL,
                    prepared_plan_json TEXT NOT NULL,
                    operations_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    transaction_version INTEGER NOT NULL,
                    attempt_sequence INTEGER NOT NULL,
                    uncertain_operation_index INTEGER,
                    uncertain_attempt_sequence INTEGER,
                    last_error_code TEXT,
                    CHECK (state IN (
                        'planned', 'reconciliation_required', 'recovery_ready',
                        'rollback_ready', 'committed'
                    )),
                    CHECK (transaction_version >= 1),
                    CHECK (attempt_sequence >= 0)
                );

                CREATE TABLE IF NOT EXISTS opc_feishu_publish_results (
                    idempotency_key TEXT NOT NULL,
                    operation_index INTEGER NOT NULL,
                    operation_sha256 TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    confirmation_source TEXT NOT NULL,
                    PRIMARY KEY (idempotency_key, operation_index),
                    FOREIGN KEY (idempotency_key)
                        REFERENCES opc_feishu_publish_transactions(idempotency_key)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS opc_feishu_publish_attempts (
                    idempotency_key TEXT NOT NULL,
                    attempt_sequence INTEGER NOT NULL,
                    operation_index INTEGER NOT NULL,
                    operation_sha256 TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    PRIMARY KEY (idempotency_key, attempt_sequence),
                    FOREIGN KEY (idempotency_key)
                        REFERENCES opc_feishu_publish_transactions(idempotency_key)
                        ON DELETE RESTRICT
                );
                """
            )

    def open(
        self,
        prepared_plan: Mapping[str, Any],
        *,
        source_sha256: str,
        target_node_token: str,
        compiler_version: str,
        publication_intent: str,
    ) -> dict[str, Any]:
        source_sha256, target_node_token, compiler_version, publication_intent = _require_identity(
            source_sha256,
            target_node_token,
            compiler_version,
            publication_intent,
        )
        normalized_plan, tenant_id, resource_owner_user_id = _durable_prepared_plan(
            prepared_plan
        )
        prepared_json = canonical_json(normalized_plan)
        if normalized_plan.get("source_sha256") != source_sha256:
            raise ValueError("prepared plan source_sha256 does not match the transaction identity")
        operations = _prepared_operations(normalized_plan)
        operations_json = canonical_json(operations)
        request_sha256 = _sha256_text(prepared_json)
        idempotency_key = _identity_key(
            source_sha256,
            target_node_token,
            compiler_version,
            publication_intent,
            tenant_id,
            resource_owner_user_id,
        )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_sha256 FROM opc_feishu_publish_transactions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                if row["request_sha256"] != request_sha256:
                    raise ValueError("idempotency conflict: stable identity is bound to another prepared plan")
            else:
                connection.execute(
                    """
                    INSERT INTO opc_feishu_publish_transactions (
                        idempotency_key, request_sha256, source_sha256,
                        target_node_token, compiler_version, publication_intent,
                        tenant_id, resource_owner_user_id,
                        prepared_plan_json, operations_json, state,
                        transaction_version, attempt_sequence,
                        uncertain_operation_index, uncertain_attempt_sequence,
                        last_error_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', 1, 0, NULL, NULL, NULL)
                    """,
                    (
                        idempotency_key,
                        request_sha256,
                        source_sha256,
                        target_node_token,
                        compiler_version,
                        publication_intent,
                        tenant_id,
                        resource_owner_user_id,
                        prepared_json,
                        operations_json,
                    ),
                )
        return self.get(idempotency_key)

    def get(self, idempotency_key: str) -> dict[str, Any]:
        key = self._require_key(idempotency_key)
        with self._connect() as connection:
            row = self._transaction_row(connection, key)
            projection = self._projection(connection, row)
        projection["new_write_count"] = 0
        return projection

    def execute(
        self,
        idempotency_key: str,
        writer: Callable[[dict[str, Any]], Any],
        *,
        tenant_id: str,
        resource_owner_user_id: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Execute a planned transaction through the injected local writer."""

        return self._run(
            idempotency_key,
            writer,
            tenant_id=tenant_id,
            resource_owner_user_id=resource_owner_user_id,
            allowed_state="planned",
            expected_version=expected_version,
        )

    def recover(
        self,
        idempotency_key: str,
        writer: Callable[[dict[str, Any]], Any],
        *,
        tenant_id: str,
        resource_owner_user_id: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Write only unconfirmed operations after explicit reconciliation."""

        return self._run(
            idempotency_key,
            writer,
            tenant_id=tenant_id,
            resource_owner_user_id=resource_owner_user_id,
            allowed_state="recovery_ready",
            expected_version=expected_version,
        )

    def _run(
        self,
        idempotency_key: str,
        writer: Callable[[dict[str, Any]], Any],
        *,
        tenant_id: str,
        resource_owner_user_id: str,
        allowed_state: str,
        expected_version: int | None,
    ) -> dict[str, Any]:
        key = self._require_key(idempotency_key)
        if not callable(writer):
            raise ValueError("writer must be callable")
        self._assert_owner(key, tenant_id, resource_owner_user_id)
        current = self.get(key)
        self._check_expected_version(current["transaction_version"], expected_version)
        if current["state"] == "committed":
            return current
        if current["state"] != allowed_state:
            if current["state"] == "reconciliation_required":
                raise ValueError("transaction requires reconciliation before recovery or execution")
            if current["state"] == "rollback_ready":
                raise ValueError("transaction is rollback ready and cannot perform another write")
            raise ValueError(f"illegal transaction transition from {current['state']} to execution")

        pending = self._begin_attempt(key, allowed_state, expected_version)
        callback_count = 0
        if pending is None:
            committed = self.get(key)
            committed["new_write_count"] = 0
            return committed

        while pending is not None:
            operation, attempt_sequence = pending
            callback_count += 1
            try:
                receipt = writer(json.loads(canonical_json(operation)))
            except Exception:
                self._mark_uncertain(key, attempt_sequence, "callback_exception")
                result = self.get(key)
                result["new_write_count"] = callback_count
                return result
            try:
                receipt_json = canonical_json(receipt)
            except ValueError:
                self._mark_uncertain(key, attempt_sequence, "invalid_receipt")
                result = self.get(key)
                result["new_write_count"] = callback_count
                return result
            pending = self._confirm_and_advance(key, operation, attempt_sequence, receipt_json)

        result = self.get(key)
        result["new_write_count"] = callback_count
        return result

    def reconcile(
        self,
        idempotency_key: str,
        observations: Mapping[str, Any],
        *,
        tenant_id: str,
        resource_owner_user_id: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Resolve the uncertain boundary with explicit digest-bound observations."""

        key = self._require_key(idempotency_key)
        self._assert_owner(key, tenant_id, resource_owner_user_id)
        if not isinstance(observations, dict) or not observations:
            raise ValueError("invalid observation set")
        current = self.get(key)
        self._check_expected_version(current["transaction_version"], expected_version)
        if current["state"] != "reconciliation_required":
            raise ValueError(f"illegal transaction transition from {current['state']} to reconciliation")
        uncertain_index = current["uncertain_operation_index"]
        if not isinstance(uncertain_index, int):
            raise ValueError("transaction has no uncertain operation boundary")

        operation_by_id = {operation["operation_id"]: operation for operation in current["operations"]}
        uncertain_id = current["operations"][uncertain_index]["operation_id"]
        if uncertain_id not in observations:
            raise ValueError("invalid observation set: uncertain operation is missing")

        normalized: dict[str, dict[str, Any]] = {}
        digest_conflict = False
        semantic_conflict = False
        for operation_id, observation in observations.items():
            operation = operation_by_id.get(operation_id)
            if operation is None or operation["operation_index"] > uncertain_index:
                raise ValueError("invalid observation set: operation is unknown or was not attempted")
            if not isinstance(observation, dict) or set(observation) - {
                "status",
                "operation_sha256",
                "receipt",
            }:
                raise ValueError("invalid observation set: observation is malformed")
            status = observation.get("status")
            if status not in _OBSERVATION_STATUSES:
                raise ValueError("invalid observation set: status is malformed")
            receipt_json = canonical_json(observation.get("receipt"))
            if observation.get("operation_sha256") != operation["operation_sha256"]:
                digest_conflict = True
            if status == "conflict":
                semantic_conflict = True
            if operation["operation_index"] < uncertain_index and status != "present":
                semantic_conflict = True
            normalized[operation_id] = {
                "status": status,
                "receipt_json": receipt_json,
            }

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._transaction_row(connection, key)
            self._check_expected_version(row["transaction_version"], expected_version)
            if row["state"] != "reconciliation_required" or row["uncertain_operation_index"] != uncertain_index:
                raise ValueError("stale transaction version or reconciliation boundary")
            next_version = row["transaction_version"] + 1
            if digest_conflict or semantic_conflict:
                connection.execute(
                    """
                    UPDATE opc_feishu_publish_transactions
                    SET state = 'rollback_ready', transaction_version = ?,
                        last_error_code = 'reconciliation_conflict'
                    WHERE idempotency_key = ?
                    """,
                    (next_version, key),
                )
                connection.execute(
                    """
                    UPDATE opc_feishu_publish_attempts
                    SET outcome = 'observed_conflict'
                    WHERE idempotency_key = ? AND attempt_sequence = ?
                    """,
                    (key, row["uncertain_attempt_sequence"]),
                )
            else:
                uncertain_observation = normalized[uncertain_id]
                if uncertain_observation["status"] == "present":
                    operation = current["operations"][uncertain_index]
                    self._insert_result(
                        connection,
                        key,
                        operation,
                        uncertain_observation["receipt_json"],
                        "reconciliation",
                    )
                    attempt_outcome = "observed_present"
                else:
                    attempt_outcome = "observed_absent"
                connection.execute(
                    """
                    UPDATE opc_feishu_publish_attempts
                    SET outcome = ?
                    WHERE idempotency_key = ? AND attempt_sequence = ?
                    """,
                    (attempt_outcome, key, row["uncertain_attempt_sequence"]),
                )
                confirmed_count = connection.execute(
                    "SELECT COUNT(*) FROM opc_feishu_publish_results WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()[0]
                operation_count = len(current["operations"])
                next_state = "committed" if confirmed_count == operation_count else "recovery_ready"
                connection.execute(
                    """
                    UPDATE opc_feishu_publish_transactions
                    SET state = ?, transaction_version = ?,
                        uncertain_operation_index = NULL,
                        uncertain_attempt_sequence = NULL, last_error_code = NULL
                    WHERE idempotency_key = ?
                    """,
                    (next_state, next_version, key),
                )
        return self.get(key)

    def build_rollback_plan(
        self,
        idempotency_key: str,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Build a pure reverse-order plan; this method never invokes a writer."""

        current = self.get(self._require_key(idempotency_key))
        self._check_expected_version(current["transaction_version"], expected_version)
        if current["state"] != "rollback_ready":
            raise ValueError(f"illegal transaction transition from {current['state']} to rollback planning")
        confirmed_by_index = {
            result["operation_index"]: result for result in current["confirmed_results"]
        }
        attempted_indexes = {
            attempt["operation_index"] for attempt in current["attempts"]
        }
        operations: list[dict[str, Any]] = []
        for index in sorted(attempted_indexes, reverse=True):
            operation = current["operations"][index]
            result = confirmed_by_index.get(index)
            operations.append(
                {
                    "confirmation": "confirmed" if result is not None else "conflict_or_unknown",
                    "operation_id": operation["operation_id"],
                    "operation_index": index,
                    "operation_sha256": operation["operation_sha256"],
                    "receipt": result["receipt"] if result is not None else None,
                }
            )
        return {
            "idempotency_key": current["idempotency_key"],
            "operations": operations,
            "request_sha256": current["request_sha256"],
            "schema_version": ROLLBACK_SCHEMA_VERSION,
            "transaction_version": current["transaction_version"],
            "write_count": 0,
        }

    def _begin_attempt(
        self,
        key: str,
        allowed_state: str,
        expected_version: int | None,
    ) -> tuple[dict[str, Any], int] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._transaction_row(connection, key)
            self._check_expected_version(row["transaction_version"], expected_version)
            if row["state"] != allowed_state:
                raise ValueError(f"illegal transaction transition from {row['state']} to execution")
            operations = json.loads(row["operations_json"])
            confirmed = {
                result[0]
                for result in connection.execute(
                    "SELECT operation_index FROM opc_feishu_publish_results WHERE idempotency_key = ?",
                    (key,),
                ).fetchall()
            }
            next_index = next((index for index in range(len(operations)) if index not in confirmed), None)
            if next_index is None:
                connection.execute(
                    """
                    UPDATE opc_feishu_publish_transactions
                    SET state = 'committed', transaction_version = transaction_version + 1,
                        uncertain_operation_index = NULL,
                        uncertain_attempt_sequence = NULL, last_error_code = NULL
                    WHERE idempotency_key = ?
                    """,
                    (key,),
                )
                return None
            attempt_sequence = row["attempt_sequence"] + 1
            operation = operations[next_index]
            connection.execute(
                """
                INSERT INTO opc_feishu_publish_attempts (
                    idempotency_key, attempt_sequence, operation_index,
                    operation_sha256, outcome
                ) VALUES (?, ?, ?, ?, 'pending')
                """,
                (key, attempt_sequence, next_index, operation["operation_sha256"]),
            )
            connection.execute(
                """
                UPDATE opc_feishu_publish_transactions
                SET state = 'reconciliation_required',
                    transaction_version = transaction_version + 1,
                    attempt_sequence = ?, uncertain_operation_index = ?,
                    uncertain_attempt_sequence = ?, last_error_code = NULL
                WHERE idempotency_key = ?
                """,
                (attempt_sequence, next_index, attempt_sequence, key),
            )
        return operation, attempt_sequence

    def _confirm_and_advance(
        self,
        key: str,
        operation: dict[str, Any],
        attempt_sequence: int,
        receipt_json: str,
    ) -> tuple[dict[str, Any], int] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._transaction_row(connection, key)
            if (
                row["state"] != "reconciliation_required"
                or row["uncertain_operation_index"] != operation["operation_index"]
                or row["uncertain_attempt_sequence"] != attempt_sequence
            ):
                raise ValueError("stale transaction attempt boundary")
            self._insert_result(connection, key, operation, receipt_json, "writer")
            connection.execute(
                """
                UPDATE opc_feishu_publish_attempts
                SET outcome = 'confirmed'
                WHERE idempotency_key = ? AND attempt_sequence = ?
                """,
                (key, attempt_sequence),
            )
            operations = json.loads(row["operations_json"])
            confirmed = {
                result[0]
                for result in connection.execute(
                    "SELECT operation_index FROM opc_feishu_publish_results WHERE idempotency_key = ?",
                    (key,),
                ).fetchall()
            }
            next_index = next((index for index in range(len(operations)) if index not in confirmed), None)
            if next_index is None:
                connection.execute(
                    """
                    UPDATE opc_feishu_publish_transactions
                    SET state = 'committed', transaction_version = transaction_version + 1,
                        uncertain_operation_index = NULL,
                        uncertain_attempt_sequence = NULL, last_error_code = NULL
                    WHERE idempotency_key = ?
                    """,
                    (key,),
                )
                return None
            next_attempt = row["attempt_sequence"] + 1
            next_operation = operations[next_index]
            connection.execute(
                """
                INSERT INTO opc_feishu_publish_attempts (
                    idempotency_key, attempt_sequence, operation_index,
                    operation_sha256, outcome
                ) VALUES (?, ?, ?, ?, 'pending')
                """,
                (key, next_attempt, next_index, next_operation["operation_sha256"]),
            )
            connection.execute(
                """
                UPDATE opc_feishu_publish_transactions
                SET transaction_version = transaction_version + 1,
                    attempt_sequence = ?, uncertain_operation_index = ?,
                    uncertain_attempt_sequence = ?, last_error_code = NULL
                WHERE idempotency_key = ?
                """,
                (next_attempt, next_index, next_attempt, key),
            )
        return next_operation, next_attempt

    def _mark_uncertain(self, key: str, attempt_sequence: int, error_code: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._transaction_row(connection, key)
            if row["state"] != "reconciliation_required" or row["uncertain_attempt_sequence"] != attempt_sequence:
                raise ValueError("stale transaction attempt boundary")
            connection.execute(
                """
                UPDATE opc_feishu_publish_attempts
                SET outcome = ?
                WHERE idempotency_key = ? AND attempt_sequence = ?
                """,
                (error_code, key, attempt_sequence),
            )
            connection.execute(
                """
                UPDATE opc_feishu_publish_transactions
                SET transaction_version = transaction_version + 1,
                    last_error_code = ?
                WHERE idempotency_key = ?
                """,
                (error_code, key),
            )

    @staticmethod
    def _insert_result(
        connection: sqlite3.Connection,
        key: str,
        operation: dict[str, Any],
        receipt_json: str,
        confirmation_source: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO opc_feishu_publish_results (
                idempotency_key, operation_index, operation_sha256,
                receipt_json, confirmation_source
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                key,
                operation["operation_index"],
                operation["operation_sha256"],
                receipt_json,
                confirmation_source,
            ),
        )

    @staticmethod
    def _projection(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        operations = json.loads(row["operations_json"])
        results = [
            {
                "confirmation_source": result["confirmation_source"],
                "operation_index": result["operation_index"],
                "operation_sha256": result["operation_sha256"],
                "receipt": json.loads(result["receipt_json"]),
            }
            for result in connection.execute(
                """
                SELECT operation_index, operation_sha256, receipt_json, confirmation_source
                FROM opc_feishu_publish_results
                WHERE idempotency_key = ? ORDER BY operation_index
                """,
                (row["idempotency_key"],),
            ).fetchall()
        ]
        attempts = [
            {
                "attempt_sequence": attempt["attempt_sequence"],
                "operation_index": attempt["operation_index"],
                "operation_sha256": attempt["operation_sha256"],
                "outcome": attempt["outcome"],
            }
            for attempt in connection.execute(
                """
                SELECT attempt_sequence, operation_index, operation_sha256, outcome
                FROM opc_feishu_publish_attempts
                WHERE idempotency_key = ? ORDER BY attempt_sequence
                """,
                (row["idempotency_key"],),
            ).fetchall()
        ]
        if row["state"] not in _STATES:
            raise ValueError("stored transaction state is invalid")
        return {
            "attempts": attempts,
            "compiler_version": row["compiler_version"],
            "confirmed_operation_count": len(results),
            "confirmed_results": results,
            "idempotency_key": row["idempotency_key"],
            "last_error_code": row["last_error_code"],
            "operations": operations,
            "prepared_plan": json.loads(row["prepared_plan_json"]),
            "publication_intent": row["publication_intent"],
            "request_sha256": row["request_sha256"],
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "source_sha256": row["source_sha256"],
            "state": row["state"],
            "target_node_token": row["target_node_token"],
            "tenant_id": row["tenant_id"],
            "transaction_version": row["transaction_version"],
            "uncertain_operation_index": row["uncertain_operation_index"],
            "resource_owner_user_id": row["resource_owner_user_id"],
        }

    def _assert_owner(
        self,
        key: str,
        tenant_id: str,
        resource_owner_user_id: str,
    ) -> None:
        expected_tenant, expected_owner = _require_owner_identity(
            tenant_id,
            resource_owner_user_id,
        )
        with self._connect() as connection:
            row = self._transaction_row(connection, key)
        if row["tenant_id"] != expected_tenant:
            raise ValueError("tenant identity does not match the persisted transaction")
        if row["resource_owner_user_id"] != expected_owner:
            raise ValueError("resource owner identity does not match the persisted transaction")

    @staticmethod
    def _transaction_row(connection: sqlite3.Connection, key: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM opc_feishu_publish_transactions WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown OPC Feishu publish transaction: {key}")
        return row

    @staticmethod
    def _require_key(idempotency_key: str) -> str:
        if not isinstance(idempotency_key, str):
            raise ValueError("idempotency_key is malformed")
        key = idempotency_key
        if not re.fullmatch(r"opc-feishu-[a-f0-9]{64}", key):
            raise ValueError("idempotency_key is malformed")
        return key

    @staticmethod
    def _check_expected_version(actual: int, expected: int | None) -> None:
        if expected is None:
            return
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1 or expected != actual:
            raise ValueError(f"stale transaction version: expected {expected}, current {actual}")
