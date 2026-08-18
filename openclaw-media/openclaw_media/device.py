"""Owner-scoped device pairing and LocalAgentJob lease state machine."""

from __future__ import annotations

from hashlib import sha256
from secrets import token_urlsafe
from threading import RLock
from typing import Iterable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .catalog import InstalledCatalog


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class Device(_Model):
    device_id: str
    tenant_id: str
    name: str
    revision: int
    status: Literal["paired", "revoked"]
    last_heartbeat: int | None = None


class PairOutcome(_Model):
    status: Literal["completed", "manual"]
    code: str
    device: Device | None = None
    credential: str | None = Field(default=None, repr=False)


class DeviceOutcome(_Model):
    status: Literal["completed", "manual"]
    code: str
    device: Device | None = None


class LocalAgentJob(_Model):
    job_id: str
    tenant_id: str
    action: str
    revision: int
    status: Literal[
        "queued",
        "leased",
        "acknowledged",
        "running",
        "succeeded",
        "blocked",
        "failed",
        "expired",
        "cancelled",
    ]
    device_id: str | None = None
    lease_expires_at: int | None = None
    result_code: str | None = None


class JobOutcome(_Model):
    status: Literal["completed", "manual"]
    code: str
    job: LocalAgentJob | None = None


class DeviceRegistry:
    """Atomic in-process owner for pairing, device, and job state.

    Pair codes and credentials are stored only as SHA-256 digests.  The API has
    no command, environment, payload, or local-path field; an action must be an
    exact pipeline id from the installed immutable catalog (or an injected
    allowlist in a focused embedding).
    """

    def __init__(
        self,
        *,
        heartbeat_ttl: int = 60,
        lease_ttl: int = 30,
        pair_ttl: int = 300,
        allowed_actions: Iterable[str] | None = None,
    ) -> None:
        if not all(_positive_int(value) for value in (heartbeat_ttl, lease_ttl, pair_ttl)):
            raise ValueError("device registry TTLs must be positive integers")
        if allowed_actions is None:
            allowed_actions = (
                item["pipeline_id"] for item in InstalledCatalog().manifest["pipelines"]
            )
        actions = frozenset(allowed_actions)
        if not actions or any(not _action_label(action) for action in actions):
            raise ValueError("allowed actions must be safe pipeline identifiers")

        self.heartbeat_ttl = heartbeat_ttl
        self.lease_ttl = lease_ttl
        self.pair_ttl = pair_ttl
        self._allowed_actions = actions
        self._lock = RLock()
        self._pairs: dict[str, tuple[str, str, int]] = {}
        self._devices: dict[str, dict[str, object]] = {}
        self._credential_digests: dict[str, str] = {}
        self._jobs: dict[str, dict[str, object]] = {}

    def issue_pair(self, tenant_id: str, device_name: str, *, now: int) -> str:
        if not _label(tenant_id) or not _label(device_name) or not _timestamp(now):
            return ""
        code = token_urlsafe(24)
        with self._lock:
            self._pairs[_digest(code)] = (tenant_id, device_name, now + self.pair_ttl)
        return code

    def redeem_pair(self, tenant_id: str, code: str, *, now: int) -> PairOutcome:
        if not _label(tenant_id) or not _token(code) or not _timestamp(now):
            return PairOutcome(status="manual", code="pair_invalid")
        pair_key = _digest(code)
        with self._lock:
            item = self._pairs.get(pair_key)
            if item is None:
                return PairOutcome(status="manual", code="pair_invalid")
            owner, name, expiry = item
            if owner != tenant_id:
                return PairOutcome(status="manual", code="tenant_forbidden")
            if now > expiry:
                return PairOutcome(status="manual", code="pair_expired")

            credential = token_urlsafe(32)
            device_id = f"device/{uuid4().hex}"
            device = {
                "device_id": device_id,
                "tenant_id": owner,
                "name": name,
                "revision": 1,
                "status": "paired",
                "last_heartbeat": None,
            }
            self._pairs.pop(pair_key)
            self._devices[device_id] = device
            self._credential_digests[_digest(credential)] = device_id
            return PairOutcome(
                status="completed",
                code="paired",
                device=Device(**device),
                credential=credential,
            )

    def heartbeat(
        self, tenant_id: str, credential: str, *, revision: int, now: int
    ) -> DeviceOutcome:
        if not _timestamp(now):
            return DeviceOutcome(status="manual", code="invalid_request")
        with self._lock:
            device = self._active_device(tenant_id, credential)
            if device is None:
                return DeviceOutcome(status="manual", code="credential_invalid")
            if revision != device["revision"]:
                return DeviceOutcome(status="manual", code="stale_revision")
            previous = device["last_heartbeat"]
            if previous is not None and now < previous:
                return DeviceOutcome(status="manual", code="stale_heartbeat")
            device["last_heartbeat"] = now
            return DeviceOutcome(
                status="completed", code="heartbeat_ok", device=Device(**device)
            )

    def revoke(self, tenant_id: str, device_id: str) -> DeviceOutcome:
        with self._lock:
            device = self._devices.get(device_id)
            if device is None or device["tenant_id"] != tenant_id:
                return DeviceOutcome(status="manual", code="tenant_forbidden")
            if device["status"] == "revoked":
                return DeviceOutcome(
                    status="completed", code="revoked", device=Device(**device)
                )
            device["status"] = "revoked"
            device["revision"] = int(device["revision"]) + 1
            for digest, owned_device_id in tuple(self._credential_digests.items()):
                if owned_device_id == device_id:
                    self._credential_digests.pop(digest)
            return DeviceOutcome(
                status="completed", code="revoked", device=Device(**device)
            )

    def create_job(
        self, tenant_id: str, action: str, *, revision: int = 1
    ) -> JobOutcome:
        if not _label(tenant_id) or action not in self._allowed_actions:
            return JobOutcome(status="manual", code="wrong_action")
        if not _positive_int(revision):
            return JobOutcome(status="manual", code="invalid_revision")
        with self._lock:
            job_id = f"job/{uuid4().hex}"
            job = {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "action": action,
                "revision": revision,
                "status": "queued",
                "device_id": None,
                "lease_expires_at": None,
                "result_code": None,
            }
            self._jobs[job_id] = job
            return JobOutcome(status="completed", code="queued", job=LocalAgentJob(**job))

    def get_job(self, tenant_id: str, job_id: str) -> JobOutcome:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["tenant_id"] != tenant_id:
                return JobOutcome(status="manual", code="tenant_forbidden")
            return JobOutcome(status="completed", code="job_found", job=LocalAgentJob(**job))

    def claim(
        self,
        tenant_id: str,
        credential: str,
        job_id: str,
        *,
        revision: int,
        now: int,
    ) -> JobOutcome:
        if not _timestamp(now):
            return JobOutcome(status="manual", code="invalid_request")
        with self._lock:
            device, job, error = self._owned(tenant_id, credential, job_id)
            if error is not None:
                return error
            assert device is not None and job is not None
            if not self._heartbeat_is_current(device, now):
                return JobOutcome(status="manual", code="lease_expired")
            status = str(job["status"])
            lease_expiry = job["lease_expires_at"]
            if status in {"succeeded", "blocked", "failed", "expired", "cancelled"}:
                return JobOutcome(status="manual", code="invalid_transition")
            if status != "queued" and isinstance(lease_expiry, int) and now <= lease_expiry:
                return JobOutcome(status="manual", code="already_claimed")
            if revision != job["revision"]:
                return JobOutcome(status="manual", code="stale_revision")

            code = "claimed" if status == "queued" else "reclaimed"
            job.update(
                status="leased",
                device_id=device["device_id"],
                lease_expires_at=now + self.lease_ttl,
                result_code=None,
                revision=int(job["revision"]) + 1,
            )
            return JobOutcome(status="completed", code=code, job=LocalAgentJob(**job))

    def acknowledge(
        self,
        tenant_id: str,
        credential: str,
        job_id: str,
        *,
        revision: int,
        now: int,
    ) -> JobOutcome:
        return self._transition(
            tenant_id,
            credential,
            job_id,
            revision=revision,
            now=now,
            expected="leased",
            target="acknowledged",
            code="acknowledged",
        )

    def start(
        self,
        tenant_id: str,
        credential: str,
        job_id: str,
        *,
        revision: int,
        now: int,
    ) -> JobOutcome:
        return self._transition(
            tenant_id,
            credential,
            job_id,
            revision=revision,
            now=now,
            expected="acknowledged",
            target="running",
            code="running",
        )

    def complete(
        self,
        tenant_id: str,
        credential: str,
        job_id: str,
        *,
        revision: int,
        now: int,
        success: bool = True,
    ) -> JobOutcome:
        target = "succeeded" if success else "failed"
        code = "result_succeeded" if success else "result_failed"
        with self._lock:
            device, job, error = self._owned(tenant_id, credential, job_id)
            if error is not None:
                return error
            assert device is not None and job is not None
            if job["status"] == target and job["device_id"] == device["device_id"]:
                return JobOutcome(status="completed", code=code, job=LocalAgentJob(**job))
        return self._transition(
            tenant_id,
            credential,
            job_id,
            revision=revision,
            now=now,
            expected="running",
            target=target,
            code=code,
            result_code=code,
        )

    def _transition(
        self,
        tenant_id: str,
        credential: str,
        job_id: str,
        *,
        revision: int,
        now: int,
        expected: str,
        target: str,
        code: str,
        result_code: str | None = None,
    ) -> JobOutcome:
        if not _timestamp(now):
            return JobOutcome(status="manual", code="invalid_request")
        with self._lock:
            device, job, error = self._owned(tenant_id, credential, job_id)
            if error is not None:
                return error
            assert device is not None and job is not None
            if job["device_id"] != device["device_id"]:
                return JobOutcome(status="manual", code="tenant_forbidden")
            if revision != job["revision"]:
                return JobOutcome(status="manual", code="stale_revision")
            if job["status"] != expected:
                return JobOutcome(status="manual", code="invalid_transition")
            if not self._lease_is_current(device, job, now):
                return JobOutcome(status="manual", code="lease_expired")
            job.update(
                status=target,
                revision=int(job["revision"]) + 1,
                result_code=result_code,
            )
            return JobOutcome(status="completed", code=code, job=LocalAgentJob(**job))

    def _owned(
        self, tenant_id: str, credential: str, job_id: str
    ) -> tuple[dict[str, object] | None, dict[str, object] | None, JobOutcome | None]:
        device = self._active_device(tenant_id, credential)
        job = self._jobs.get(job_id)
        if device is None or job is None or job["tenant_id"] != tenant_id:
            return None, None, JobOutcome(status="manual", code="tenant_forbidden")
        if job["device_id"] not in (None, device["device_id"]):
            lease_expiry = job["lease_expires_at"]
            if isinstance(lease_expiry, int):
                return device, job, None
            return None, None, JobOutcome(status="manual", code="tenant_forbidden")
        return device, job, None

    def _active_device(
        self, tenant_id: str, credential: str
    ) -> dict[str, object] | None:
        if not _label(tenant_id) or not _token(credential):
            return None
        device_id = self._credential_digests.get(_digest(credential))
        device = self._devices.get(device_id or "")
        if (
            device is None
            or device["tenant_id"] != tenant_id
            or device["status"] != "paired"
        ):
            return None
        return device

    def _heartbeat_is_current(self, device: dict[str, object], now: int) -> bool:
        heartbeat = device["last_heartbeat"]
        return (
            isinstance(heartbeat, int)
            and heartbeat <= now
            and now - heartbeat <= self.heartbeat_ttl
        )

    def _lease_is_current(
        self, device: dict[str, object], job: dict[str, object], now: int
    ) -> bool:
        lease_expiry = job["lease_expires_at"]
        return (
            job["device_id"] == device["device_id"]
            and isinstance(lease_expiry, int)
            and now <= lease_expiry
            and self._heartbeat_is_current(device, now)
        )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _timestamp(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _token(value: object) -> bool:
    return isinstance(value, str) and 16 <= len(value) <= 256 and value == value.strip()


def _label(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 128
        and value == value.strip()
        and not any(character in value for character in "/\\\x00\r\n")
    )


def _action_label(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 128
        and value == value.strip()
        and all(character.isalnum() or character in ".-_" for character in value)
    )
