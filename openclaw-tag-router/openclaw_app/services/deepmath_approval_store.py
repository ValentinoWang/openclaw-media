"""Transactional SQLite ledger for the DeepMath U5 approval state machine."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Mapping

from .deepmath_ceo_thinking_schema import (
    DECISION_STATES,
    EXECUTION_STATES,
    PROPOSAL_STATES,
    canonical_json,
    make_execution_key,
)


class DeepMathApprovalStoreError(RuntimeError):
    """Base error for a malformed or unavailable approval ledger."""


class DeepMathApprovalStoreConflict(DeepMathApprovalStoreError):
    """The same idempotency identity was presented with different content."""


class DeepMathApprovalStoreNotFound(DeepMathApprovalStoreError):
    """The requested proposal item does not exist."""


class DeepMathApprovalStoreStale(DeepMathApprovalStoreError):
    """The requested item is no longer the current version."""


class DeepMathApprovalStoreTransitionError(DeepMathApprovalStoreError):
    """The requested state transition is not allowed."""


class DeepMathApprovalStoreSchemaError(DeepMathApprovalStoreError):
    """An existing database does not match the canonical U5 schema."""


class DeepMathApprovalStore:
    """Own the one durable U5 claim/receipt ledger at an injected path.

    The constructor deliberately requires a path.  There is no alternate
    runtime store and no path discovery in this class.
    """

    TABLE_NAME = "proposal_items"
    BUSY_TIMEOUT_MS = 10_000

    _CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS proposal_items (
        tenant_key TEXT NOT NULL,
        proposal_id TEXT NOT NULL,
        proposal_version INTEGER NOT NULL,
        approval_id TEXT NOT NULL,
        canonical_payload TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        proposal_state TEXT NOT NULL,
        decision_state TEXT NOT NULL,
        execution_state TEXT NOT NULL,
        approver_user_id TEXT,
        decided_at TEXT,
        execution_key TEXT NOT NULL UNIQUE,
        claim_token TEXT,
        claimed_at TEXT,
        attempt_no INTEGER NOT NULL DEFAULT 0,
        upstream_request_id TEXT,
        external_object_id TEXT,
        external_url TEXT,
        receipt TEXT,
        error_code TEXT,
        last_readback_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(tenant_key, proposal_id, proposal_version, approval_id)
    )
    """

    _EXPECTED_COLUMNS = (
        "tenant_key", "proposal_id", "proposal_version", "approval_id",
        "canonical_payload", "payload_sha256", "token_hash", "expires_at",
        "proposal_state", "decision_state", "execution_state", "approver_user_id",
        "decided_at", "execution_key", "claim_token", "claimed_at", "attempt_no",
        "upstream_request_id", "external_object_id", "external_url", "receipt",
        "error_code", "last_readback_at", "created_at", "updated_at",
    )

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = BUSY_TIMEOUT_MS):
        raw_path = str(path or "").strip()
        if not raw_path:
            raise ValueError("approval state path is required")
        self.path = Path(raw_path).expanduser()
        if self.path.exists() and not self.path.is_file():
            raise ValueError("approval state path must name a file")
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        self._initialize()

    @staticmethod
    def hash_token(token: str) -> str:
        value = str(token or "")
        if not value:
            raise ValueError("approval token is required")
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _timestamp(cls, value: Any = None) -> str:
        if value is None:
            value = cls._now()
        if isinstance(value, (int, float)):
            value = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
        if not isinstance(value, datetime):
            text = str(value).strip()
            if not text:
                raise ValueError("timestamp is required")
            try:
                value = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("timestamp must be ISO-8601") from exc
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

    @classmethod
    def _parse_timestamp(cls, value: Any) -> datetime:
        text = cls._timestamp(value)
        return datetime.fromisoformat(text.replace("Z", "+00:00"))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute(self._CREATE_SQL)
            columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(proposal_items)"))
            if columns != self._EXPECTED_COLUMNS:
                raise DeepMathApprovalStoreSchemaError("proposal_items schema is not the canonical U5 schema")
        finally:
            connection.close()
        try:
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise DeepMathApprovalStoreError("approval state file permissions could not be secured") from exc

    @staticmethod
    def _payload(value: Any) -> tuple[str, str]:
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("canonical payload must contain JSON") from exc
            canonical = canonical_json(decoded)
            if canonical != value:
                raise ValueError("canonical payload is not normalized")
        else:
            canonical = canonical_json(value)
        return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _receipt(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = {"message": value}
        return canonical_json(value)

    @classmethod
    def _row(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        try:
            value["canonical_payload"] = json.loads(value["canonical_payload"])
        except (TypeError, json.JSONDecodeError):
            pass
        if value.get("receipt") is not None:
            try:
                value["receipt"] = json.loads(value["receipt"])
            except (TypeError, json.JSONDecodeError):
                pass
        return value

    @classmethod
    def _validate_states(cls, proposal_state: str, decision_state: str, execution_state: str) -> None:
        if proposal_state not in PROPOSAL_STATES:
            raise ValueError("invalid proposal state")
        if decision_state not in DECISION_STATES:
            raise ValueError("invalid decision state")
        if execution_state not in EXECUTION_STATES:
            raise ValueError("invalid execution state")

    @staticmethod
    def _select_key(tenant_key: str, proposal_id: str, proposal_version: int, approval_id: str) -> tuple[str, str, int, str]:
        values = (str(tenant_key).strip(), str(proposal_id).strip(), int(proposal_version), str(approval_id).strip())
        if not values[0] or not values[1] or not values[3] or values[2] < 1:
            raise ValueError("proposal identity is incomplete")
        return values

    @classmethod
    def _select_locked(
        cls,
        connection: sqlite3.Connection,
        tenant_key: str,
        proposal_id: str,
        approval_id: str,
        proposal_version: int | None = None,
    ) -> sqlite3.Row | None:
        if proposal_version is None:
            return connection.execute(
                """SELECT * FROM proposal_items
                   WHERE tenant_key = ? AND proposal_id = ? AND approval_id = ?
                   ORDER BY proposal_version DESC LIMIT 1""",
                (tenant_key, proposal_id, approval_id),
            ).fetchone()
        return connection.execute(
            """SELECT * FROM proposal_items
               WHERE tenant_key = ? AND proposal_id = ? AND proposal_version = ? AND approval_id = ?""",
            (tenant_key, proposal_id, proposal_version, approval_id),
        ).fetchone()

    @classmethod
    def _select_by_key_locked(cls, connection: sqlite3.Connection, execution_key: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM proposal_items WHERE execution_key = ?", (execution_key,)
        ).fetchone()

    def insert_proposal_item(
        self,
        *,
        tenant_key: str,
        proposal_id: str,
        proposal_version: int,
        approval_id: str,
        canonical_payload_value: Any,
        token: str,
        expires_at: Any,
        proposal_state: str = "待确认",
        decision_state: str = "待决定",
        execution_state: str = "未授权",
        execution_key: str | None = None,
        attempt_no: int = 0,
        created_at: Any = None,
    ) -> dict[str, Any]:
        """Insert one immutable item or return its exact idempotent replay."""

        tenant_key, proposal_id, proposal_version, approval_id = self._select_key(
            tenant_key, proposal_id, proposal_version, approval_id
        )
        canonical_payload_value, payload_sha256 = self._payload(canonical_payload_value)
        token_hash = self.hash_token(token)
        expires_at_text = self._timestamp(expires_at)
        self._validate_states(proposal_state, decision_state, execution_state)
        if (proposal_state, decision_state, execution_state) != ("待确认", "待决定", "未授权"):
            raise ValueError("new proposal items must begin in the pending state")
        if int(attempt_no) != 0:
            raise ValueError("new proposal items must have zero execution attempts")
        expected_key = make_execution_key(tenant_key, proposal_id, proposal_version, approval_id, payload_sha256)
        requested_execution_key = str(execution_key or "").strip()
        if requested_execution_key and requested_execution_key != expected_key:
            existing = self.get_by_execution_key(requested_execution_key)
            if existing is not None:
                if existing.get("canonical_payload") != json.loads(canonical_payload_value):
                    raise DeepMathApprovalStoreConflict("execution key payload conflict")
                return existing
            raise ValueError("execution key does not match the canonical payload identity")
        execution_key = expected_key
        created_at_text = self._timestamp(created_at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            by_execution = self._select_by_key_locked(connection, execution_key)
            if by_execution is not None:
                if by_execution["canonical_payload"] != canonical_payload_value:
                    raise DeepMathApprovalStoreConflict("execution key payload conflict")
                return self._row(by_execution) or {}
            existing = self._select_locked(connection, tenant_key, proposal_id, approval_id, proposal_version)
            if existing is not None:
                if existing["canonical_payload"] != canonical_payload_value:
                    raise DeepMathApprovalStoreConflict("proposal item payload conflict")
                return self._row(existing) or {}
            connection.execute(
                """INSERT INTO proposal_items (
                    tenant_key, proposal_id, proposal_version, approval_id,
                    canonical_payload, payload_sha256, token_hash, expires_at,
                    proposal_state, decision_state, execution_state,
                    execution_key, attempt_no, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tenant_key, proposal_id, proposal_version, approval_id,
                    canonical_payload_value, payload_sha256, token_hash, expires_at_text,
                    proposal_state, decision_state, execution_state,
                    execution_key, 0, created_at_text, created_at_text,
                ),
            )
            row = self._select_locked(connection, tenant_key, proposal_id, approval_id, proposal_version)
            connection.execute("COMMIT")
            return self._row(row) or {}
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def get_item(
        self,
        *,
        tenant_key: str,
        proposal_id: str,
        proposal_version: int,
        approval_id: str,
    ) -> dict[str, Any] | None:
        tenant_key, proposal_id, proposal_version, approval_id = self._select_key(
            tenant_key, proposal_id, proposal_version, approval_id
        )
        connection = self._connect()
        try:
            return self._row(self._select_locked(connection, tenant_key, proposal_id, approval_id, proposal_version))
        finally:
            connection.close()

    def get_current_item(self, *, tenant_key: str, proposal_id: str, approval_id: str) -> dict[str, Any] | None:
        tenant_key, proposal_id, _, approval_id = self._select_key(tenant_key, proposal_id, 1, approval_id)
        connection = self._connect()
        try:
            return self._row(self._select_locked(connection, tenant_key, proposal_id, approval_id))
        finally:
            connection.close()

    def get_by_execution_key(self, execution_key: str) -> dict[str, Any] | None:
        value = str(execution_key or "").strip()
        if not value:
            raise ValueError("execution key is required")
        connection = self._connect()
        try:
            return self._row(self._select_by_key_locked(connection, value))
        finally:
            connection.close()

    def replace_current_item(
        self,
        *,
        tenant_key: str,
        proposal_id: str,
        approval_id: str,
        expected_version: int,
        expected_payload_sha256: str,
        new_payload: Any,
        new_token: str,
        expires_at: Any,
        now: Any = None,
    ) -> dict[str, Any]:
        """Atomically replace the current item and create its next version."""

        tenant_key, proposal_id, expected_version, approval_id = self._select_key(
            tenant_key, proposal_id, expected_version, approval_id
        )
        canonical_payload_value, payload_sha256 = self._payload(new_payload)
        if payload_sha256 == expected_payload_sha256:
            raise DeepMathApprovalStoreConflict("new proposal version must change its payload")
        token_hash = self.hash_token(new_token)
        expires_at_text = self._timestamp(expires_at)
        now_text = self._timestamp(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._select_locked(connection, tenant_key, proposal_id, approval_id)
            if current is None:
                raise DeepMathApprovalStoreNotFound("proposal item does not exist")
            if int(current["proposal_version"]) != expected_version or current["payload_sha256"] != expected_payload_sha256:
                raise DeepMathApprovalStoreStale("proposal item is not current")
            if current["proposal_state"] != "待确认" or current["decision_state"] != "待决定" or current["execution_state"] != "未授权":
                raise DeepMathApprovalStoreTransitionError("proposal item cannot be modified")
            next_version = expected_version + 1
            new_execution_key = make_execution_key(
                tenant_key, proposal_id, next_version, approval_id, payload_sha256
            )
            connection.execute(
                """UPDATE proposal_items
                   SET proposal_state = '已取代', updated_at = ?
                   WHERE tenant_key = ? AND proposal_id = ? AND proposal_version = ? AND approval_id = ?""",
                (now_text, tenant_key, proposal_id, expected_version, approval_id),
            )
            connection.execute(
                """INSERT INTO proposal_items (
                    tenant_key, proposal_id, proposal_version, approval_id,
                    canonical_payload, payload_sha256, token_hash, expires_at,
                    proposal_state, decision_state, execution_state,
                    execution_key, attempt_no, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '待确认', '待决定', '未授权', ?, 0, ?, ?)""",
                (
                    tenant_key, proposal_id, next_version, approval_id,
                    canonical_payload_value, payload_sha256, token_hash, expires_at_text,
                    new_execution_key, now_text, now_text,
                ),
            )
            row = self._select_locked(connection, tenant_key, proposal_id, approval_id, next_version)
            connection.execute("COMMIT")
            return self._row(row) or {}
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def expire_current_item(self, *, tenant_key: str, proposal_id: str, approval_id: str, now: Any = None) -> dict[str, Any] | None:
        tenant_key, proposal_id, _, approval_id = self._select_key(tenant_key, proposal_id, 1, approval_id)
        now_text = self._timestamp(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._select_locked(connection, tenant_key, proposal_id, approval_id)
            if current is None:
                connection.execute("COMMIT")
                return None
            if current["proposal_state"] == "待确认" and current["decision_state"] == "待决定":
                connection.execute(
                    """UPDATE proposal_items SET proposal_state = '已过期', updated_at = ?
                       WHERE tenant_key = ? AND proposal_id = ? AND proposal_version = ? AND approval_id = ?""",
                    (now_text, tenant_key, proposal_id, current["proposal_version"], approval_id),
                )
                current = self._select_locked(connection, tenant_key, proposal_id, approval_id)
            connection.execute("COMMIT")
            return self._row(current)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def finalize_current_item(
        self,
        *,
        tenant_key: str,
        proposal_id: str,
        approval_id: str,
        expected_version: int,
        expected_payload_sha256: str,
        proposal_state: str,
        decision_state: str,
        actor_id: str,
        now: Any = None,
    ) -> dict[str, Any]:
        """Atomically record a non-approving terminal decision."""

        self._validate_states(proposal_state, decision_state, "未授权")
        tenant_key, proposal_id, expected_version, approval_id = self._select_key(
            tenant_key, proposal_id, expected_version, approval_id
        )
        actor_id = str(actor_id or "").strip()
        if not actor_id:
            raise ValueError("actor id is required")
        now_text = self._timestamp(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._select_locked(connection, tenant_key, proposal_id, approval_id)
            if current is None:
                raise DeepMathApprovalStoreNotFound("proposal item does not exist")
            if int(current["proposal_version"]) != expected_version or current["payload_sha256"] != expected_payload_sha256:
                raise DeepMathApprovalStoreStale("proposal item is not current")
            if current["proposal_state"] != "待确认" or current["decision_state"] != "待决定":
                raise DeepMathApprovalStoreTransitionError("proposal item is already decided")
            connection.execute(
                """UPDATE proposal_items
                   SET proposal_state = ?, decision_state = ?, execution_state = '未授权',
                       approver_user_id = ?, decided_at = ?, updated_at = ?
                   WHERE tenant_key = ? AND proposal_id = ? AND proposal_version = ? AND approval_id = ?""",
                (
                    proposal_state, decision_state, actor_id, now_text, now_text,
                    tenant_key, proposal_id, expected_version, approval_id,
                ),
            )
            current = self._select_locked(connection, tenant_key, proposal_id, approval_id, expected_version)
            connection.execute("COMMIT")
            return self._row(current) or {}
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def claim_approval(
        self,
        *,
        tenant_key: str,
        proposal_id: str,
        approval_id: str,
        expected_version: int,
        expected_payload_sha256: str,
        actor_id: str,
        now: Any = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically authorize and claim an item for exactly one executor call."""

        tenant_key, proposal_id, expected_version, approval_id = self._select_key(
            tenant_key, proposal_id, expected_version, approval_id
        )
        actor_id = str(actor_id or "").strip()
        if not actor_id:
            raise ValueError("actor id is required")
        now_text = self._timestamp(now)
        now_dt = self._parse_timestamp(now_text)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._select_locked(connection, tenant_key, proposal_id, approval_id)
            if current is None:
                raise DeepMathApprovalStoreNotFound("proposal item does not exist")
            if int(current["proposal_version"]) != expected_version or current["payload_sha256"] != expected_payload_sha256:
                raise DeepMathApprovalStoreStale("proposal item is not current")
            if self._parse_timestamp(current["expires_at"]) <= now_dt and current["proposal_state"] == "待确认":
                connection.execute(
                    """UPDATE proposal_items SET proposal_state = '已过期', updated_at = ?
                       WHERE tenant_key = ? AND proposal_id = ? AND proposal_version = ? AND approval_id = ?""",
                    (now_text, tenant_key, proposal_id, expected_version, approval_id),
                )
                connection.execute("COMMIT")
                raise DeepMathApprovalStoreStale("proposal item has expired")
            if current["decision_state"] == "已批准" and current["execution_state"] in {
                "执行中", "执行成功", "执行失败", "结果未知", "已跳过", "人工处理"
            }:
                connection.execute("COMMIT")
                return self._row(current) or {}, False
            if current["proposal_state"] != "待确认" or current["decision_state"] != "待决定" or current["execution_state"] != "未授权":
                connection.execute("COMMIT")
                raise DeepMathApprovalStoreTransitionError("proposal item cannot be approved")
            claim_token = secrets.token_urlsafe(24)
            connection.execute(
                """UPDATE proposal_items
                   SET decision_state = '已批准', execution_state = '执行中',
                       approver_user_id = ?, decided_at = ?, claim_token = ?,
                       claimed_at = ?, attempt_no = attempt_no + 1, updated_at = ?
                   WHERE tenant_key = ? AND proposal_id = ? AND proposal_version = ? AND approval_id = ?
                     AND proposal_state = '待确认' AND decision_state = '待决定' AND execution_state = '未授权'""",
                (
                    actor_id, now_text, claim_token, now_text, now_text,
                    tenant_key, proposal_id, expected_version, approval_id,
                ),
            )
            if connection.total_changes != 1:
                raise DeepMathApprovalStoreTransitionError("proposal claim was lost")
            current = self._select_locked(connection, tenant_key, proposal_id, approval_id, expected_version)
            connection.execute("COMMIT")
            return self._row(current) or {}, True
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def record_execution(
        self,
        *,
        tenant_key: str,
        proposal_id: str,
        proposal_version: int,
        approval_id: str,
        claim_token: str,
        execution_state: str,
        receipt: Any,
        error_code: str | None = None,
        upstream_request_id: str | None = None,
        external_object_id: str | None = None,
        external_url: str | None = None,
        last_readback_at: Any = None,
        now: Any = None,
    ) -> dict[str, Any]:
        if execution_state not in {"执行成功", "执行失败", "结果未知", "已跳过", "人工处理"}:
            raise ValueError("execution result state is not terminal")
        tenant_key, proposal_id, proposal_version, approval_id = self._select_key(
            tenant_key, proposal_id, proposal_version, approval_id
        )
        claim_token = str(claim_token or "")
        if not claim_token:
            raise ValueError("claim token is required")
        now_text = self._timestamp(now)
        readback_text = self._timestamp(last_readback_at) if last_readback_at is not None else None
        receipt_text = self._receipt(receipt)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._select_locked(connection, tenant_key, proposal_id, approval_id, proposal_version)
            if current is None:
                raise DeepMathApprovalStoreNotFound("proposal item does not exist")
            if current["execution_state"] != "执行中":
                connection.execute("COMMIT")
                return self._row(current) or {}
            if not hmac.compare_digest(str(current["claim_token"] or ""), claim_token):
                raise DeepMathApprovalStoreTransitionError("claim token does not match")
            connection.execute(
                """UPDATE proposal_items
                   SET execution_state = ?, receipt = ?, error_code = ?,
                       upstream_request_id = ?, external_object_id = ?, external_url = ?,
                       last_readback_at = ?, updated_at = ?
                   WHERE tenant_key = ? AND proposal_id = ? AND proposal_version = ? AND approval_id = ?""",
                (
                    execution_state, receipt_text, str(error_code).strip() if error_code else None,
                    str(upstream_request_id).strip() if upstream_request_id else None,
                    str(external_object_id).strip() if external_object_id else None,
                    str(external_url).strip() if external_url else None,
                    readback_text, now_text,
                    tenant_key, proposal_id, proposal_version, approval_id,
                ),
            )
            current = self._select_locked(connection, tenant_key, proposal_id, approval_id, proposal_version)
            connection.execute("COMMIT")
            return self._row(current) or {}
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def count_approved_unclaimed(self) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT COUNT(*) AS count FROM proposal_items
                   WHERE decision_state = '已批准' AND execution_state IN ('未授权', '待领取')"""
            ).fetchone()
            return int(row["count"] if row else 0)
        finally:
            connection.close()
