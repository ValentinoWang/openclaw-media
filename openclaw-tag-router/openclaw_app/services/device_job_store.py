from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .device_job_errors import DeviceJobError
from .media_device_job_contract import MIN_CLIENT_VERSION, SERVER_API_VERSION, catalog_digest, operation_metadata


MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "011_openclaw_media_device_jobs.sql"
TERMINAL_JOB_STATES = frozenset({"succeeded", "blocked", "failed", "expired", "cancelled"})


class DeviceJobStore:
    """Durable SQLite owner store for the generated R1 Device/LocalAgentJob API."""

    def __init__(
        self,
        path: str | Path,
        *,
        credential_secret: bytes,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(credential_secret) < 32:
            raise ValueError("device credential secret must be at least 32 bytes")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._credential_secret = bytes(credential_secret)
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

    def operation_metadata(self, operation_id: str) -> Mapping[str, Any]:
        return operation_metadata(operation_id)

    def create_pair_code(
        self,
        tenant_id: str,
        *,
        device_label: str,
        expires_in_seconds: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._write_transaction() as connection:
            existing = self._idempotency_get(connection, f"tenant:{tenant_id}", "pair_code_create", idempotency_key, request_fingerprint)
            if existing is not None:
                pair_code_id = str(existing["pair_code_id"])
                return self._pair_code_projection(connection, pair_code_id)
            pair_code_id = "pcr_" + uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO pair_codes(pair_code_id, tenant_id, pair_code_hash, device_label, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pair_code_id, tenant_id, self._hash(self._derive_pair_code(pair_code_id)), device_label, now + expires_in_seconds, now),
            )
            self._idempotency_put(
                connection,
                f"tenant:{tenant_id}",
                "pair_code_create",
                idempotency_key,
                request_fingerprint,
                {"pair_code_id": pair_code_id},
                201,
                now,
            )
            return self._pair_code_projection(connection, pair_code_id)

    def pair_device(
        self,
        *,
        pair_code: str,
        device_label: str,
        device_platform: str,
        client_version: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[dict[str, Any], str]:
        now = self._clock()
        pair_hash = self._hash(pair_code)
        with self._write_transaction() as connection:
            row = connection.execute("SELECT * FROM pair_codes WHERE pair_code_hash = ?", (pair_hash,)).fetchone()
            if row is None:
                raise DeviceJobError("invalid_pair_code", "pair code is invalid")
            if row["consumed_at"] is not None:
                if row["consumed_fingerprint"] != request_fingerprint or row["consumed_idempotency_key"] != idempotency_key:
                    raise DeviceJobError("invalid_pair_code", "pair code is invalid")
                device_id = str(row["consumed_device_id"])
                device = self._device_by_id(connection, device_id)
                if device is None:
                    raise DeviceJobError("invalid_pair_code", "pair code is invalid")
                return device, self._derive_credential(pair_code, device_id)
            if float(row["expires_at"]) <= now:
                raise DeviceJobError("expired_pair_code", "pair code has expired")
            device_id = "dev_" + uuid.uuid4().hex
            credential = self._derive_credential(pair_code, device_id)
            connection.execute(
                """
                INSERT INTO devices(
                    device_id, tenant_id, device_label, device_platform, client_version,
                    api_version, reported_catalog_digest, api_compatible, catalog_compatible,
                    credential_hash, state, revision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 'paired', 1, ?)
                """,
                (device_id, row["tenant_id"], device_label, device_platform, client_version,
                 SERVER_API_VERSION, catalog_digest(), self._hash(credential), now),
            )
            connection.execute(
                """
                UPDATE pair_codes
                SET consumed_at = ?, consumed_device_id = ?, consumed_fingerprint = ?, consumed_idempotency_key = ?
                WHERE pair_code_id = ? AND consumed_at IS NULL
                """,
                (now, device_id, request_fingerprint, idempotency_key, row["pair_code_id"]),
            )
            return self._device_by_id(connection, device_id), credential  # type: ignore[return-value]

    def list_devices(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM devices WHERE tenant_id = ? ORDER BY created_at DESC, device_id DESC", (tenant_id,)
            ).fetchall()
        return [self._device_projection(row) for row in rows]

    def heartbeat(
        self,
        *,
        device_id: str,
        credential: str,
        observed_at: float,
        client_version: str,
        api_version: str,
        reported_catalog_digest: str,
        capabilities: list[str],
        idempotency_key: str,
        request_fingerprint: str,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._write_transaction() as connection:
            device = self._authenticated_device(connection, device_id, credential)
            scope = f"device:{device['tenant_id']}:{device_id}"
            existing = self._idempotency_get(connection, scope, "device_heartbeat", idempotency_key, request_fingerprint)
            if existing is not None:
                return existing
            previous = device["last_observed_at"]
            self._check_revision(device, expected_revision)
            if previous is not None and observed_at < float(previous):
                raise DeviceJobError("invalid_state", "heartbeat revision is stale")
            connection.execute(
                """
                UPDATE devices
                SET state = 'online', client_version = ?, api_version = ?, reported_catalog_digest = ?,
                    api_compatible = ?, catalog_compatible = ?, capabilities_json = ?,
                    last_observed_at = ?, last_seen_at = ?, revision = revision + 1
                WHERE device_id = ? AND revision = ? AND state <> 'revoked'
                """,
                (client_version, api_version, reported_catalog_digest,
                 self._version_at_least(client_version, MIN_CLIENT_VERSION) and api_version == SERVER_API_VERSION,
                 reported_catalog_digest == catalog_digest(),
                 json.dumps(capabilities, separators=(",", ":")), observed_at, now, device_id, device["revision"]),
            )
            updated = connection.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
            api_compatible = bool(updated["api_compatible"])
            catalog_compatible = bool(updated["catalog_compatible"])
            claimable = connection.execute(
                "SELECT job_id, state FROM jobs WHERE tenant_id = ? AND device_id = ? AND state = 'queued' ORDER BY created_at ASC, job_id ASC LIMIT 1",
                (device["tenant_id"], device_id),
            ).fetchone() if api_compatible and catalog_compatible else None
            response = {
                "device_id": device_id, "accepted_at": self._iso(now), "revision": int(updated["revision"]),
                "state": str(updated["state"]), "accepted_client_version": client_version,
                "catalog_digest": catalog_digest(), "api_compatible": api_compatible,
                "catalog_compatible": catalog_compatible,
                "claimable_job": None if claimable is None else {"job_id": str(claimable["job_id"]), "state": str(claimable["state"])},
            }
            self._idempotency_put(connection, scope, "device_heartbeat", idempotency_key, request_fingerprint, response, 200, now)
            return response

    def revoke_device(self, tenant_id: str, device_id: str, *, idempotency_key: str, request_fingerprint: str, expected_revision: int | None) -> dict[str, Any]:
        now = self._clock()
        with self._write_transaction() as connection:
            device = self._owned_device(connection, tenant_id, device_id)
            scope = f"tenant:{tenant_id}"
            existing = self._idempotency_get(connection, scope, "device_revoke", idempotency_key, request_fingerprint)
            if existing is not None:
                return existing
            self._check_revision(device, expected_revision)
            connection.execute(
                "UPDATE devices SET state = 'revoked', revoked_at = ?, revision = revision + 1 WHERE device_id = ? AND state <> 'revoked'",
                (now, device_id),
            )
            response = {"device_id": device_id, "revoked_at": self._iso(now)}
            self._idempotency_put(connection, scope, "device_revoke", idempotency_key, request_fingerprint, response, 200, now)
            return response

    def create_job(
        self,
        tenant_id: str,
        *,
        pipeline_id: str,
        pipeline_version: str,
        catalog_digest: str,
        device_id: str,
        input_refs: list[str],
        output_selection: list[str],
        confirmation_ref: str | None,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._write_transaction() as connection:
            scope = f"tenant:{tenant_id}"
            existing = self._idempotency_get(connection, scope, "job_create", idempotency_key, request_fingerprint)
            if existing is not None:
                return existing
            device = self._owned_device(connection, tenant_id, device_id)
            if device["state"] == "revoked":
                raise DeviceJobError("device_unavailable", "device is unavailable")
            job_id = "job_" + uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id, tenant_id, pipeline_id, pipeline_version, catalog_digest, device_id,
                    input_refs_json, output_selection_json, confirmation_ref, state, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 1, ?, ?)
                """,
                (job_id, tenant_id, pipeline_id, pipeline_version, catalog_digest, device_id,
                 json.dumps(input_refs, separators=(",", ":")), json.dumps(output_selection, separators=(",", ":")),
                 confirmation_ref, now, now),
            )
            response = self._job_by_id(connection, job_id)
            self._idempotency_put(connection, scope, "job_create", idempotency_key, request_fingerprint, response, 201, now)
            return response

    def list_jobs(self, tenant_id: str, *, state: str | None, limit: int) -> list[dict[str, Any]]:
        with self._write_transaction() as connection:
            self._expire_due_jobs(connection)
            if state is None:
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE tenant_id = ? ORDER BY created_at DESC, job_id DESC LIMIT ?", (tenant_id, limit)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE tenant_id = ? AND state = ? ORDER BY created_at DESC, job_id DESC LIMIT ?",
                    (tenant_id, state, limit),
                ).fetchall()
        return [self._job_projection(row) for row in rows]

    def list_jobs_for_device(self, credential: str, *, state: str | None, limit: int) -> list[dict[str, Any]]:
        with self._write_transaction() as connection:
            device = connection.execute("SELECT * FROM devices WHERE credential_hash = ?", (self._hash(credential),)).fetchone()
            if device is None:
                raise DeviceJobError("invalid_device_credential", "device credential is invalid")
            if device["state"] == "revoked":
                raise DeviceJobError("device_revoked", "device is revoked")
            if not (device["api_compatible"] and device["catalog_compatible"]):
                return []
            self._expire_due_jobs(connection)
            target = state or "queued"
            if target not in {"queued", "leased", "acknowledged", "running"}:
                return []
            rows = connection.execute(
                "SELECT * FROM jobs WHERE tenant_id = ? AND device_id = ? AND state = ? ORDER BY created_at ASC, job_id ASC LIMIT ?",
                (device["tenant_id"], device["device_id"], target, limit),
            ).fetchall()
        return [self._job_projection(row) for row in rows]

    def get_job(self, tenant_id: str, job_id: str) -> dict[str, Any]:
        with self._write_transaction() as connection:
            self._expire_due_jobs(connection)
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ? AND tenant_id = ?", (job_id, tenant_id)).fetchone()
            if row is None:
                raise DeviceJobError("not_found", "resource not found")
            return self._job_projection(row)

    def lease_job(
        self,
        *,
        job_id: str,
        credential: str,
        lease_seconds: int,
        idempotency_key: str,
        request_fingerprint: str,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._write_transaction() as connection:
            device, job = self._authenticated_job(connection, job_id, credential)
            scope = f"device:{device['tenant_id']}:{device['device_id']}"
            existing = self._idempotency_get(connection, scope, "job_lease", idempotency_key, request_fingerprint)
            if existing is not None:
                return existing
            self._check_revision(job, expected_revision)
            if job["state"] != "queued":
                raise DeviceJobError("invalid_state", "job action is not allowed in this state")
            lease_id = "lease_" + uuid.uuid4().hex
            expires_at = now + lease_seconds
            cursor = connection.execute(
                """
                UPDATE jobs
                SET state = 'leased', revision = revision + 1, lease_id = ?, lease_expires_at = ?, lease_device_id = ?, leased_at = ?, updated_at = ?
                WHERE job_id = ? AND tenant_id = ? AND state = 'queued' AND revision = ?
                """,
                (lease_id, expires_at, device["device_id"], now, now, job_id, device["tenant_id"], job["revision"]),
            )
            if cursor.rowcount != 1:
                raise DeviceJobError("invalid_state", "job was claimed by another worker")
            response = self._job_by_id(connection, job_id)
            self._idempotency_put(connection, scope, "job_lease", idempotency_key, request_fingerprint, response, 200, now)
            return response

    def ack_job(self, *, job_id: str, credential: str, ack_ref: str, idempotency_key: str, request_fingerprint: str, expected_revision: int | None) -> dict[str, Any]:
        return self._advance_job("job_ack", "leased", "acknowledged", job_id=job_id, credential=credential, ref_column="ack_ref", ref=ack_ref, idempotency_key=idempotency_key, request_fingerprint=request_fingerprint, expected_revision=expected_revision)

    def start_job(self, *, job_id: str, credential: str, start_ref: str, idempotency_key: str, request_fingerprint: str, expected_revision: int | None) -> dict[str, Any]:
        return self._advance_job("job_start", "acknowledged", "running", job_id=job_id, credential=credential, ref_column="start_ref", ref=start_ref, idempotency_key=idempotency_key, request_fingerprint=request_fingerprint, expected_revision=expected_revision)

    def result_job(
        self,
        *,
        job_id: str,
        credential: str,
        result_status: str,
        result_refs: list[str],
        artifact_refs: list[str],
        failure_code: str | None,
        idempotency_key: str,
        request_fingerprint: str,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._write_transaction() as connection:
            device, job = self._authenticated_job(connection, job_id, credential)
            scope = f"device:{device['tenant_id']}:{device['device_id']}"
            existing = self._idempotency_get(connection, scope, "job_result", idempotency_key, request_fingerprint)
            if existing is not None:
                return existing
            if job["state"] in TERMINAL_JOB_STATES and job["result_fingerprint"] == request_fingerprint:
                return self._job_projection(job)
            self._check_revision(job, expected_revision)
            self._check_live_lease(job, device["device_id"])
            if job["state"] != "running":
                raise DeviceJobError("result_rejected", "job result is not allowed in this state")
            target_state = result_status
            connection.execute(
                """
                UPDATE jobs
                SET state = ?, revision = revision + 1, result_status = ?, result_refs_json = ?,
                    artifact_refs_json = ?, failure_code = ?, result_fingerprint = ?, completed_at = ?, updated_at = ?
                WHERE job_id = ? AND revision = ? AND state = 'running'
                """,
                (target_state, result_status, json.dumps(result_refs, separators=(",", ":")), json.dumps(artifact_refs, separators=(",", ":")), failure_code, request_fingerprint, now, now, job_id, job["revision"]),
            )
            response = self._job_by_id(connection, job_id)
            self._idempotency_put(connection, scope, "job_result", idempotency_key, request_fingerprint, response, 200, now)
            return response

    def _advance_job(self, operation_id: str, current_state: str, target_state: str, *, job_id: str, credential: str, ref_column: str, ref: str, idempotency_key: str, request_fingerprint: str, expected_revision: int | None) -> dict[str, Any]:
        now = self._clock()
        with self._write_transaction() as connection:
            device, job = self._authenticated_job(connection, job_id, credential)
            scope = f"device:{device['tenant_id']}:{device['device_id']}"
            existing = self._idempotency_get(connection, scope, operation_id, idempotency_key, request_fingerprint)
            if existing is not None:
                return existing
            self._check_revision(job, expected_revision)
            self._check_live_lease(job, device["device_id"])
            if job["state"] != current_state:
                raise DeviceJobError("invalid_state", "job action is not allowed in this state")
            cursor = connection.execute(
                f"UPDATE jobs SET state = ?, revision = revision + 1, {ref_column} = ?, {('acknowledged_at' if ref_column == 'ack_ref' else 'started_at')} = ?, updated_at = ? WHERE job_id = ? AND revision = ? AND state = ?",
                (target_state, ref, now, now, job_id, job["revision"], current_state),
            )
            if cursor.rowcount != 1:
                raise DeviceJobError("invalid_state", "job revision is stale")
            response = self._job_by_id(connection, job_id)
            self._idempotency_put(connection, scope, operation_id, idempotency_key, request_fingerprint, response, 200, now)
            return response

    def _authenticated_device(self, connection: sqlite3.Connection, device_id: str, credential: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM devices WHERE credential_hash = ?", (self._hash(credential),)).fetchone()
        if row is None:
            raise DeviceJobError("invalid_device_credential", "device credential is invalid")
        if row["state"] == "revoked":
            raise DeviceJobError("device_revoked", "device is revoked")
        if row["device_id"] != device_id:
            raise DeviceJobError("not_found", "resource not found")
        return row

    def _authenticated_job(self, connection: sqlite3.Connection, job_id: str, credential: str) -> tuple[sqlite3.Row, sqlite3.Row]:
        row = connection.execute("SELECT * FROM devices WHERE credential_hash = ?", (self._hash(credential),)).fetchone()
        if row is None:
            raise DeviceJobError("invalid_device_credential", "device credential is invalid")
        if row["state"] == "revoked":
            raise DeviceJobError("device_revoked", "device is revoked")
        if not (row["api_compatible"] and row["catalog_compatible"]):
            raise DeviceJobError("invalid_state", "device compatibility is not accepted")
        job = connection.execute("SELECT * FROM jobs WHERE job_id = ? AND tenant_id = ? AND device_id = ?", (job_id, row["tenant_id"], row["device_id"])).fetchone()
        if job is None:
            raise DeviceJobError("not_found", "resource not found")
        self._expire_job(connection, job)
        job = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return row, job  # type: ignore[return-value]

    def _owned_device(self, connection: sqlite3.Connection, tenant_id: str, device_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM devices WHERE device_id = ? AND tenant_id = ?", (device_id, tenant_id)).fetchone()
        if row is None:
            raise DeviceJobError("not_found", "resource not found")
        return row

    def _device_by_id(self, connection: sqlite3.Connection, device_id: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return None if row is None else self._device_projection(row)

    def _job_by_id(self, connection: sqlite3.Connection, job_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise DeviceJobError("not_found", "resource not found")
        return self._job_projection(row)

    def _expire_due_jobs(self, connection: sqlite3.Connection) -> None:
        now = self._clock()
        rows = connection.execute(
            "SELECT * FROM jobs WHERE state IN ('leased', 'acknowledged', 'running') AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
            (now,),
        ).fetchall()
        for row in rows:
            self._expire_job(connection, row)

    def _expire_job(self, connection: sqlite3.Connection, row: sqlite3.Row) -> None:
        if row["state"] not in {"leased", "acknowledged", "running"} or row["lease_expires_at"] is None or float(row["lease_expires_at"]) > self._clock():
            return
        connection.execute(
            "UPDATE jobs SET state = 'expired', revision = revision + 1, updated_at = ? WHERE job_id = ? AND revision = ? AND state = ?",
            (self._clock(), row["job_id"], row["revision"], row["state"]),
        )

    @staticmethod
    def _check_revision(row: sqlite3.Row, expected_revision: int | None) -> None:
        if expected_revision is not None and int(row["revision"]) != expected_revision:
            raise DeviceJobError("invalid_state", "job revision is stale")

    def _check_live_lease(self, row: sqlite3.Row, device_id: str) -> None:
        if row["lease_device_id"] != device_id or row["lease_expires_at"] is None or float(row["lease_expires_at"]) <= self._clock():
            raise DeviceJobError("invalid_state", "job lease is expired or invalid")

    @staticmethod
    def _version_at_least(value: str, minimum: str) -> bool:
        try:
            value_parts = tuple(int(part) for part in value.split("."))
            minimum_parts = tuple(int(part) for part in minimum.split("."))
        except (AttributeError, ValueError):
            return False
        if not value_parts or not minimum_parts or any(part < 0 for part in value_parts + minimum_parts):
            return False
        width = max(len(value_parts), len(minimum_parts))
        return value_parts + (0,) * (width - len(value_parts)) >= minimum_parts + (0,) * (width - len(minimum_parts))

    def _idempotency_get(self, connection: sqlite3.Connection, scope: str, operation_id: str, key: str, fingerprint: str) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT request_fingerprint, response_json FROM device_job_idempotency WHERE scope = ? AND operation_id = ? AND idempotency_key = ?",
            (scope, operation_id, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_fingerprint"] != fingerprint:
            raise DeviceJobError("idempotency_conflict", "idempotency key is bound to another request")
        return json.loads(row["response_json"])

    @staticmethod
    def _idempotency_put(connection: sqlite3.Connection, scope: str, operation_id: str, key: str, fingerprint: str, response: Mapping[str, Any], status_code: int, now: float) -> None:
        connection.execute(
            "INSERT INTO device_job_idempotency(scope, operation_id, idempotency_key, request_fingerprint, response_json, status_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (scope, operation_id, key, fingerprint, json.dumps(response, ensure_ascii=False, separators=(",", ":")), status_code, now),
        )

    def _pair_code_projection(self, connection: sqlite3.Connection, pair_code_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT expires_at FROM pair_codes WHERE pair_code_id = ?", (pair_code_id,)).fetchone()
        if row is None:
            raise DeviceJobError("invalid_pair_code", "pair code is invalid")
        return {"pair_code": self._derive_pair_code(pair_code_id), "expires_at": self._iso(float(row["expires_at"]))}

    def _device_projection(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "device_id": str(row["device_id"]),
            "state": str(row["state"]),
            "device_label": str(row["device_label"]),
            "device_platform": str(row["device_platform"]),
            "client_version": str(row["client_version"]),
            "capabilities": json.loads(row["capabilities_json"]),
            "revision": int(row["revision"]),
            "last_seen_at": None if row["last_seen_at"] is None else self._iso(float(row["last_seen_at"])),
        }

    def _job_projection(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": str(row["job_id"]),
            "state": str(row["state"]),
            "pipeline_id": str(row["pipeline_id"]),
            "pipeline_version": str(row["pipeline_version"]),
            "catalog_digest": str(row["catalog_digest"]),
            "device_id": str(row["device_id"]),
            "input_refs": json.loads(row["input_refs_json"]),
            "output_selection": json.loads(row["output_selection_json"]),
            "confirmation_ref": row["confirmation_ref"],
            "revision": int(row["revision"]),
            "lease_id": row["lease_id"],
            "lease_expires_at": None if row["lease_expires_at"] is None else self._iso(float(row["lease_expires_at"])),
            "ack_ref": row["ack_ref"],
            "start_ref": row["start_ref"],
            "result_status": row["result_status"],
            "result_refs": [] if row["result_refs_json"] is None else json.loads(row["result_refs_json"]),
            "artifact_refs": [] if row["artifact_refs_json"] is None else json.loads(row["artifact_refs_json"]),
            "failure_code": row["failure_code"],
            "created_at": self._iso(float(row["created_at"])),
            "updated_at": self._iso(float(row["updated_at"])),
            "leased_at": None if row["leased_at"] is None else self._iso(float(row["leased_at"])),
            "acknowledged_at": None if row["acknowledged_at"] is None else self._iso(float(row["acknowledged_at"])),
            "started_at": None if row["started_at"] is None else self._iso(float(row["started_at"])),
            "completed_at": None if row["completed_at"] is None else self._iso(float(row["completed_at"])),
        }

    @staticmethod
    def _hash(value: str) -> bytes:
        return hashlib.sha256(value.encode("utf-8")).digest()

    def _derive_pair_code(self, pair_code_id: str) -> str:
        digest = hmac.new(self._credential_secret, pair_code_id.encode("ascii"), hashlib.sha256).hexdigest()
        return "pc_" + digest

    def _derive_credential(self, pair_code: str, device_id: str) -> str:
        material = (pair_code + ":" + device_id).encode("utf-8")
        return "dc_" + hmac.new(self._credential_secret, material, hashlib.sha256).hexdigest()

    @staticmethod
    def _iso(value: float) -> str:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def _initialize(self) -> None:
        if not MIGRATION_PATH.is_file():
            raise RuntimeError(f"device/job schema migration is missing: {MIGRATION_PATH}")
        with self.connect() as connection:
            connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
            self._upgrade_legacy_v1(connection)
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != 1:
                raise RuntimeError(f"unsupported device/job schema revision: {version}")

    @staticmethod
    def _upgrade_legacy_v1(connection: sqlite3.Connection) -> None:
        """Complete the additive v1 schema if an older v1 database already existed."""
        upgrades = {
            "devices": {
                "api_version": "TEXT NOT NULL DEFAULT '1'",
                "reported_catalog_digest": "TEXT NOT NULL DEFAULT ''",
                "api_compatible": "INTEGER NOT NULL DEFAULT 0 CHECK (api_compatible IN (0, 1))",
                "catalog_compatible": "INTEGER NOT NULL DEFAULT 0 CHECK (catalog_compatible IN (0, 1))",
            },
            "jobs": {
                "leased_at": "REAL",
                "acknowledged_at": "REAL",
                "started_at": "REAL",
                "completed_at": "REAL",
            },
        }
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table, columns in upgrades.items():
                existing = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
                if not existing:
                    raise RuntimeError(f"device/job schema table is missing: {table}")
                for name, definition in columns.items():
                    if name not in existing:
                        connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
