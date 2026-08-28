from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from .device_job_errors import DeviceJobError
from .device_job_store import DeviceJobStore
from .media_device_job_contract import SERVER_API_VERSION, catalog_digest, operation_metadata


_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class DeviceJobService:
    def __init__(self, store: DeviceJobStore, *, clock=None) -> None:
        self.store = store
        self._clock = clock or store._clock  # one clock boundary for expiry and tests

    def operation_metadata(self, operation_id: str) -> Mapping[str, Any]:
        return operation_metadata(operation_id)

    def create_pair_code(self, tenant_id: str, *, device_label: str, expires_in_seconds: int, idempotency_key: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        self._key(idempotency_key)
        label = self._text(device_label, "device_label", maximum=200)
        if isinstance(expires_in_seconds, bool) or not isinstance(expires_in_seconds, int) or not 60 <= expires_in_seconds <= 3_600:
            raise DeviceJobError("invalid_request", "expires_in_seconds is invalid")
        return self.store.create_pair_code(
            tenant,
            device_label=label,
            expires_in_seconds=expires_in_seconds,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint({"device_label": label, "expires_in_seconds": expires_in_seconds}),
        )

    def pair_device(self, *, pair_code: str, device_label: str, device_platform: str, client_version: str, idempotency_key: str) -> tuple[dict[str, Any], str]:
        self._key(idempotency_key)
        code = self._text(pair_code, "pair_code", maximum=256)
        label = self._text(device_label, "device_label", maximum=200)
        platform = self._text(device_platform, "device_platform", maximum=32)
        if platform != "macos":
            raise DeviceJobError("platform_unsupported", "only macos devices are supported")
        version = self._text(client_version, "client_version", maximum=100)
        return self.store.pair_device(
            pair_code=code,
            device_label=label,
            device_platform=platform,
            client_version=version,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint({"pair_code": code, "device_label": label, "device_platform": platform, "client_version": version}),
        )

    def list_devices(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        tenant = self._tenant(tenant_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise DeviceJobError("invalid_request", "limit is invalid")
        return self.store.list_devices(tenant)[:limit]

    def authenticated_credential(self, credential: str) -> dict[str, str]:
        secret = self._text(credential, "device_credential", maximum=256)
        return self.store.authenticated_credential(secret)

    def heartbeat(self, device_id: str, credential: str, *, observed_at: str, client_version: str, capabilities: list[str] | None, idempotency_key: str, expected_revision: int | None = None, api_version: str = SERVER_API_VERSION, reported_catalog_digest: str = catalog_digest()) -> dict[str, Any]:
        device = self._object_id(device_id, "device_id", prefix="dev_")
        secret = self._text(credential, "device_credential", maximum=256)
        observed = self._timestamp(observed_at)
        version = self._text(client_version, "client_version", maximum=100)
        normalized_api_version = self._text(api_version, "api_version", maximum=50)
        normalized_catalog_digest = self._text(reported_catalog_digest, "catalog_digest", maximum=300)
        caps = capabilities or []
        if not isinstance(caps, list) or any(not isinstance(item, str) or not item.strip() for item in caps) or len(caps) > 100:
            raise DeviceJobError("invalid_request", "capabilities is invalid")
        self._key(idempotency_key)
        revision = self._revision(expected_revision)
        return self.store.heartbeat(
            device_id=device,
            credential=secret,
            observed_at=observed,
            client_version=version,
            api_version=normalized_api_version,
            reported_catalog_digest=normalized_catalog_digest,
            capabilities=[item.strip() for item in caps],
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint({"observed_at": observed_at, "client_version": version, "api_version": normalized_api_version, "catalog_digest": normalized_catalog_digest, "capabilities": [item.strip() for item in caps], "expected_revision": revision}),
            expected_revision=revision,
        )

    def revoke_device(self, tenant_id: str, device_id: str, *, idempotency_key: str, expected_revision: int | None = None) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        device = self._object_id(device_id, "device_id", prefix="dev_")
        self._key(idempotency_key)
        return self.store.revoke_device(
            tenant,
            device,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint({"device_id": device}),
            expected_revision=self._revision(expected_revision),
        )

    def create_job(self, tenant_id: str, *, pipeline_id: str, pipeline_version: str, catalog_digest: str, device_id: str, input_refs: list[str], output_selection: list[str], confirmation_ref: str | None, idempotency_key: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        self._key(idempotency_key)
        pipeline = self._text(pipeline_id, "pipeline_id", maximum=200)
        version = self._text(pipeline_version, "pipeline_version", maximum=100)
        digest = self._text(catalog_digest, "catalog_digest", maximum=300)
        device = self._object_id(device_id, "device_id", prefix="dev_")
        inputs = self._refs(input_refs, "input_refs")
        outputs = self._refs(output_selection, "output_selection")
        confirmation = None if confirmation_ref is None else self._text(confirmation_ref, "confirmation_ref", maximum=300)
        payload = {"pipeline_id": pipeline, "pipeline_version": version, "catalog_digest": digest, "device_id": device, "input_refs": inputs, "output_selection": outputs, "confirmation_ref": confirmation}
        return self.store.create_job(
            tenant,
            pipeline_id=pipeline,
            pipeline_version=version,
            catalog_digest=digest,
            device_id=device,
            input_refs=inputs,
            output_selection=outputs,
            confirmation_ref=confirmation,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint(payload),
        )

    def list_jobs(self, tenant_id: str, *, state: str | None, limit: int = 100) -> list[dict[str, Any]]:
        tenant = self._tenant(tenant_id)
        if state is not None:
            state = self._text(state, "state", maximum=32)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise DeviceJobError("invalid_request", "limit is invalid")
        return self.store.list_jobs(tenant, state=state, limit=limit)

    def list_jobs_for_device(self, credential: str, *, state: str | None, limit: int = 100) -> list[dict[str, Any]]:
        secret = self._text(credential, "device_credential", maximum=256)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise DeviceJobError("invalid_request", "limit is invalid")
        if state is not None:
            state = self._text(state, "state", maximum=32)
        return self.store.list_jobs_for_device(secret, state=state, limit=limit)

    def get_job(self, tenant_id: str, job_id: str) -> dict[str, Any]:
        return self.store.get_job(self._tenant(tenant_id), self._object_id(job_id, "job_id", prefix="job_"))

    def lease_job(self, job_id: str, credential: str, *, lease_seconds: int, idempotency_key: str, expected_revision: int | None = None) -> dict[str, Any]:
        self._key(idempotency_key)
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= 86_400:
            raise DeviceJobError("invalid_request", "lease_seconds is invalid")
        job = self._object_id(job_id, "job_id", prefix="job_")
        secret = self._text(credential, "device_credential", maximum=256)
        revision = self._revision(expected_revision)
        return self.store.lease_job(job_id=job, credential=secret, lease_seconds=lease_seconds, idempotency_key=idempotency_key, request_fingerprint=self._fingerprint({"lease_seconds": lease_seconds, "revision": revision}), expected_revision=revision)

    def ack_job(self, job_id: str, credential: str, *, ack_ref: str, idempotency_key: str, expected_revision: int | None = None) -> dict[str, Any]:
        return self.store.ack_job(job_id=self._object_id(job_id, "job_id", prefix="job_"), credential=self._text(credential, "device_credential", maximum=256), ack_ref=self._text(ack_ref, "ack_ref", maximum=300), idempotency_key=self._key(idempotency_key), request_fingerprint=self._fingerprint({"ack_ref": ack_ref, "revision": expected_revision}), expected_revision=self._revision(expected_revision))

    def start_job(self, job_id: str, credential: str, *, start_ref: str, idempotency_key: str, expected_revision: int | None = None) -> dict[str, Any]:
        return self.store.start_job(job_id=self._object_id(job_id, "job_id", prefix="job_"), credential=self._text(credential, "device_credential", maximum=256), start_ref=self._text(start_ref, "start_ref", maximum=300), idempotency_key=self._key(idempotency_key), request_fingerprint=self._fingerprint({"start_ref": start_ref, "revision": expected_revision}), expected_revision=self._revision(expected_revision))

    def result_job(self, job_id: str, credential: str, *, result_status: str, result_refs: list[str], artifact_refs: list[str] | None, failure_code: str | None, idempotency_key: str, expected_revision: int | None = None) -> dict[str, Any]:
        status = self._text(result_status, "result_status", maximum=32)
        if status not in {"succeeded", "blocked", "failed"}:
            raise DeviceJobError("invalid_request", "result_status is invalid")
        refs = self._refs(result_refs, "result_refs")
        artifacts = self._refs(artifact_refs or [], "artifact_refs")
        failure = None if failure_code is None else self._text(failure_code, "failure_code", maximum=200)
        revision = self._revision(expected_revision)
        return self.store.result_job(job_id=self._object_id(job_id, "job_id", prefix="job_"), credential=self._text(credential, "device_credential", maximum=256), result_status=status, result_refs=refs, artifact_refs=artifacts, failure_code=failure, idempotency_key=self._key(idempotency_key), request_fingerprint=self._fingerprint({"result_status": status, "result_refs": refs, "artifact_refs": artifacts, "failure_code": failure, "revision": revision}), expected_revision=revision)

    @staticmethod
    def _tenant(value: str) -> str:
        if not isinstance(value, str):
            raise DeviceJobError("invalid_request", "tenant is not valid")
        try:
            normalized = str(uuid.UUID(value))
        except ValueError as exc:
            raise DeviceJobError("invalid_request", "tenant is not valid") from exc
        if normalized != value:
            raise DeviceJobError("invalid_request", "tenant is not valid")
        return normalized

    @staticmethod
    def _key(value: str) -> str:
        if not isinstance(value, str) or not _IDEMPOTENCY_KEY.fullmatch(value):
            raise DeviceJobError("invalid_request", "idempotency key is invalid")
        return value

    @staticmethod
    def _text(value: Any, field: str, *, maximum: int) -> str:
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
            raise DeviceJobError("invalid_request", f"{field} is invalid")
        return value.strip()

    @classmethod
    def _object_id(cls, value: Any, field: str, *, prefix: str) -> str:
        result = cls._text(value, field, maximum=128)
        if not result.startswith(prefix) or not re.fullmatch(r"[A-Za-z0-9_-]+", result):
            raise DeviceJobError("invalid_request", f"{field} is invalid")
        return result

    @classmethod
    def _refs(cls, value: Any, field: str) -> list[str]:
        if not isinstance(value, list) or len(value) > 200 or any(not isinstance(item, str) or not 1 <= len(item.strip()) <= 500 for item in value):
            raise DeviceJobError("invalid_request", f"{field} is invalid")
        return [item.strip() for item in value]

    @staticmethod
    def _timestamp(value: Any) -> float:
        if not isinstance(value, str):
            raise DeviceJobError("invalid_request", "observed_at is invalid")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DeviceJobError("invalid_request", "observed_at is invalid") from exc
        if parsed.tzinfo is None:
            raise DeviceJobError("invalid_request", "observed_at must include timezone")
        return parsed.astimezone(timezone.utc).timestamp()

    @staticmethod
    def _revision(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise DeviceJobError("invalid_request", "revision is invalid")
        return value

    @staticmethod
    def _fingerprint(payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["DeviceJobError", "DeviceJobService"]
