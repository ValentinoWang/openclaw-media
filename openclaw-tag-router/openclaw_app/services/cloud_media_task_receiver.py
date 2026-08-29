"""Tenant-bound Content OS result receipt, readback, and retry handling."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any

import yaml

from ..router.content_os_project_lifecycle import ContentOSContractError
from ..router.content_os_queue import DONE_DIRECTORY, READY_DIRECTORY, RESULT_DIRECTORY, create_ready_task
from .device_job_service import DeviceJobService
from .media_business.foundation import DEVICE_KEY, idempotency_key


_TASK_ID = re.compile(r"task_\d{8}_\d{3}\Z")
_TASK_TYPE = re.compile(r"[A-Za-z0-9_]{1,80}\Z")


class CloudMediaTaskReceiverError(RuntimeError):
    def __init__(self, code: str, detail: str, *, status: HTTPStatus | int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = int(status)


class CloudMediaTaskReceiver:
    """Make the legacy vault handoff readable and safe to replay.

    The queue module remains the authority that validates and accepts a first
    result. This adapter adds the missing receiver-facing behavior: a stable
    receipt, tenant-bound readback, and an explicit retry path for blocked
    confirmed-change tasks.
    """

    receipt_version = "cloud_media_task_receipt.v1"

    def __init__(self, device_job_service: DeviceJobService, router: Any) -> None:
        self._device_job_service = device_job_service
        self._router = router

    def receive(
        self,
        *,
        credential: str,
        result: Mapping[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload = self._result_payload(result)
        tenant_id = self._authenticated_tenant(credential)
        identity = self._result_identity(payload, idempotency_key=idempotency_key)
        existing = self._accepted_result_for_payload(payload)
        if existing is not None:
            stored, result_path = existing
            self._assert_stored_tenant(stored, tenant_id)
            if self._source_digest(stored) != identity:
                raise CloudMediaTaskReceiverError(
                    "idempotency_conflict",
                    "该任务已接收不同内容的结果，不能覆盖原有证据。",
                    status=HTTPStatus.CONFLICT,
                )
            return self._receipt(stored, result_path, replayed=True)

        receiver = self._accepting_router()
        try:
            accepted = receiver(payload, expected_tenant_id=tenant_id)
        except TimeoutError as exc:
            raise CloudMediaTaskReceiverError(
                "cloud_receiver_timeout",
                "云端接收超时，结果尚未确认；请使用相同结果重试。",
                status=HTTPStatus.GATEWAY_TIMEOUT,
            ) from exc
        except ContentOSContractError as exc:
            # A concurrent delivery can complete after the first existence
            # check. Re-read only when the stored evidence is byte-equivalent.
            existing = self._accepted_result_for_payload(payload)
            if existing is not None:
                stored, result_path = existing
                self._assert_stored_tenant(stored, tenant_id)
                if self._source_digest(stored) == identity:
                    return self._receipt(stored, result_path, replayed=True)
            raise CloudMediaTaskReceiverError(
                "content_os_result_rejected",
                "Mac 回传与当前任务契约不一致。",
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            ) from exc

        if not isinstance(accepted, Mapping) or accepted.get("status") != "content_os_mac_result_accepted":
            raise CloudMediaTaskReceiverError(
                "content_os_receiver_invalid",
                "云端接收器未返回可确认的结果回执。",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        existing = self._accepted_result_for_payload(payload)
        if existing is None:
            raise CloudMediaTaskReceiverError(
                "content_os_readback_unavailable",
                "云端未保存可读回的结果证据。",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        stored, result_path = existing
        self._assert_stored_tenant(stored, tenant_id)
        if self._source_digest(stored) != identity:
            raise CloudMediaTaskReceiverError(
                "content_os_receiver_invalid",
                "云端保存的结果证据与本次提交不一致。",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return self._receipt(stored, result_path, replayed=False)

    def readback(self, *, credential: str, task_id: str) -> dict[str, Any]:
        tenant_id = self._authenticated_tenant(credential)
        stored, result_path = self._accepted_result_for_task(task_id)
        self._assert_stored_tenant(stored, tenant_id)
        return self._receipt(stored, result_path, replayed=True)

    def retry_blocked_change(
        self,
        *,
        credential: str,
        task_id: str,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, Any]:
        tenant_id = self._authenticated_tenant(credential)
        self._require_idempotency_key(idempotency_key)
        retry_reason = self._text(reason, "reason", maximum=300)
        stored, result_path = self._accepted_result_for_task(task_id)
        self._assert_stored_tenant(stored, tenant_id)
        source = self._source_payload(stored)
        if source.get("status") != "blocked":
            raise CloudMediaTaskReceiverError(
                "retry_not_allowed",
                "只有已回传 blocked 证据的任务可以重试。",
                status=HTTPStatus.CONFLICT,
            )
        change_request_id = self._text(source.get("change_request_id"), "change_request_id", maximum=160)
        completed_task = self._done_task(task_id)
        self._assert_stored_tenant(completed_task, tenant_id)
        if completed_task.get("task_type") != source.get("task_type"):
            raise CloudMediaTaskReceiverError(
                "retry_rejected",
                "已完成任务与回传结果不属于同一任务类型。",
                status=HTTPStatus.CONFLICT,
            )
        retry_marker = f"cloud_retry:{self._task_id(task_id)}:{self._source_digest(stored)}"
        existing = self._ready_retry(retry_marker, tenant_id)
        if existing is not None:
            return self._retry_receipt(existing, source_task_id=task_id, replayed=True)

        try:
            retry_task = create_ready_task(
                self._vault_root(),
                self._text(completed_task.get("project_id"), "project_id", maximum=160),
                task_type=self._task_type(completed_task.get("task_type")),
                project_revision=self._revision(completed_task.get("project_revision")),
                change_request_id=change_request_id,
                editor_backend=self._text(completed_task.get("editor_backend"), "editor_backend", maximum=80),
                human_confirmed_impact=completed_task.get("human_confirmed_impact") is True,
                inputs=self._mapping(completed_task.get("inputs"), "inputs"),
                expected_outputs=self._strings(completed_task.get("expected_outputs"), "expected_outputs"),
                allowed_actions=self._strings(completed_task.get("allowed_actions"), "allowed_actions"),
                notes=[*self._strings(completed_task.get("notes"), "notes"), retry_marker, f"cloud_retry_reason:{retry_reason}"],
                tenant_id=tenant_id,
            )
        except ContentOSContractError as exc:
            raise CloudMediaTaskReceiverError(
                "retry_rejected",
                "无法安全创建重试任务；当前项目或任务状态已变化。",
                status=HTTPStatus.CONFLICT,
            ) from exc
        return self._retry_receipt(retry_task.payload, source_task_id=task_id, replayed=False)

    def _accepting_router(self):
        receiver = getattr(self._router, "_accept_content_os_mac_result", None)
        root = getattr(self._router, "_content_os_vault_root", None)
        if not callable(receiver) or not callable(root):
            raise CloudMediaTaskReceiverError(
                "content_os_unavailable",
                "Content OS 云桥能力暂时不可用。",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return receiver

    def _vault_root(self) -> Path:
        self._accepting_router()
        root = self._router._content_os_vault_root()
        if not isinstance(root, Path):
            root = Path(root)
        return root

    def _authenticated_tenant(self, credential: str) -> str:
        identity = self._device_job_service.authenticated_credential(credential)
        return self._text(identity.get("tenant_id"), "tenant_id", maximum=160)

    def _accepted_result_for_payload(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], Path] | None:
        task_id = self._task_id(payload.get("task_id"))
        task_type = self._task_type(payload.get("task_type"))
        path = self._vault_root() / RESULT_DIRECTORY / f"accepted_{task_id.removeprefix('task_')}_{task_type}.yaml"
        if not path.is_file():
            return None
        return self._load_accepted(path), path

    def _accepted_result_for_task(self, task_id: str) -> tuple[dict[str, Any], Path]:
        normalized = self._task_id(task_id)
        root = self._vault_root() / RESULT_DIRECTORY
        matches = sorted(root.glob(f"accepted_{normalized.removeprefix('task_')}_*.yaml")) if root.is_dir() else []
        if len(matches) != 1:
            raise CloudMediaTaskReceiverError("not_found", "未找到该任务的已接收结果。", status=HTTPStatus.NOT_FOUND)
        return self._load_accepted(matches[0]), matches[0]

    def _done_task(self, task_id: str) -> dict[str, Any]:
        normalized = self._task_id(task_id)
        root = self._vault_root() / DONE_DIRECTORY
        matches = sorted(root.glob(f"{normalized}_*.yaml")) if root.is_dir() else []
        if len(matches) != 1:
            raise CloudMediaTaskReceiverError(
                "retry_rejected",
                "找不到唯一的已完成任务，不能创建重试。",
                status=HTTPStatus.CONFLICT,
            )
        return self._load_accepted(matches[0])

    @staticmethod
    def _load_accepted(path: Path) -> dict[str, Any]:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise CloudMediaTaskReceiverError(
                "content_os_readback_unavailable",
                "云端结果证据无法读取。",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            ) from exc
        if not isinstance(payload, dict):
            raise CloudMediaTaskReceiverError(
                "content_os_readback_unavailable",
                "云端结果证据格式无效。",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return payload

    def _receipt(self, stored: Mapping[str, Any], result_path: Path, *, replayed: bool) -> dict[str, Any]:
        source = self._source_payload(stored)
        tenant_id = self._text(source.get("tenant_id"), "tenant_id", maximum=160)
        status = self._text(source.get("status"), "status", maximum=32)
        evidence = {
            "outputs": source.get("outputs", {}),
            "validation": source.get("validation", {}),
            "blocked_reason": source.get("blocked_reason") if status == "blocked" else None,
            "blocked_detail": source.get("blocked_detail") if status == "blocked" else None,
            "sha256": self._source_digest(stored),
        }
        return {
            "receipt_version": self.receipt_version,
            "status": "content_os_mac_result_accepted",
            "replayed": replayed,
            "contract": {
                "spec_version": source["spec_version"],
                "doc_type": source["doc_type"],
            },
            "task": {
                "task_id": source["task_id"],
                "task_type": source["task_type"],
                "project_id": source["project_id"],
                "project_revision": source["project_revision"],
                "change_request_id": source["change_request_id"],
                "editor_backend": source["editor_backend"],
                "tenant_id": tenant_id,
            },
            "result": {"status": status, "evidence": evidence},
            "accepted": {
                "accepted_by": self._text(stored.get("accepted_by"), "accepted_by", maximum=80),
                "accepted_at": self._text(stored.get("accepted_at"), "accepted_at", maximum=80),
                "result_ref": self._relative_ref(result_path),
            },
            "retry": {
                "available": status == "blocked" and bool(str(source.get("change_request_id") or "").strip()),
                "source_task_id": source["task_id"],
            },
        }

    def _retry_receipt(self, payload: Mapping[str, Any], *, source_task_id: str, replayed: bool) -> dict[str, Any]:
        return {
            "receipt_version": self.receipt_version,
            "status": "content_os_retry_queued",
            "replayed": replayed,
            "source_task_id": self._task_id(source_task_id),
            "task": {
                "task_id": self._task_id(payload.get("task_id")),
                "task_type": self._task_type(payload.get("task_type")),
                "project_id": self._text(payload.get("project_id"), "project_id", maximum=160),
                "project_revision": self._revision(payload.get("project_revision")),
                "change_request_id": self._text(payload.get("change_request_id"), "change_request_id", maximum=160),
                "editor_backend": self._text(payload.get("editor_backend"), "editor_backend", maximum=80),
                "tenant_id": self._text(payload.get("tenant_id"), "tenant_id", maximum=160),
                "state": "ready",
            },
        }

    def _ready_retry(self, marker: str, tenant_id: str) -> dict[str, Any] | None:
        root = self._vault_root() / READY_DIRECTORY
        if not root.is_dir():
            return None
        matches: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.yaml")):
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(payload, dict) or marker not in payload.get("notes", []):
                continue
            if payload.get("tenant_id") != tenant_id:
                raise CloudMediaTaskReceiverError(
                    "retry_rejected",
                    "已存在属于其他租户的同源重试任务。",
                    status=HTTPStatus.CONFLICT,
                )
            matches.append(payload)
        if len(matches) > 1:
            raise CloudMediaTaskReceiverError(
                "retry_rejected",
                "同一结果存在多个待执行重试任务。",
                status=HTTPStatus.CONFLICT,
            )
        return matches[0] if matches else None

    def _assert_stored_tenant(self, stored: Mapping[str, Any], tenant_id: str) -> None:
        if self._text(stored.get("tenant_id"), "tenant_id", maximum=160) != tenant_id:
            # Use not-found to avoid leaking a valid result identifier across tenants.
            raise CloudMediaTaskReceiverError("not_found", "未找到该任务的已接收结果。", status=HTTPStatus.NOT_FOUND)

    def _result_payload(self, result: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            raise CloudMediaTaskReceiverError("invalid_content_os_result", "Mac 回传格式无效。", status=HTTPStatus.BAD_REQUEST)
        payload = dict(result)
        if "accepted_by" in payload or "accepted_at" in payload:
            raise CloudMediaTaskReceiverError("invalid_content_os_result", "Mac 回传不能伪造云端接收字段。", status=HTTPStatus.BAD_REQUEST)
        if payload.get("spec_version") != "content_os_v0.2" or payload.get("doc_type") != "mac_result":
            raise CloudMediaTaskReceiverError("invalid_content_os_result", "Mac 回传格式无效。", status=HTTPStatus.BAD_REQUEST)
        if payload.get("completed_by") != "mac_openclaw" or payload.get("status") not in {"done", "blocked"}:
            raise CloudMediaTaskReceiverError("invalid_content_os_result", "Mac 回传状态无效。", status=HTTPStatus.BAD_REQUEST)
        self._task_id(payload.get("task_id"))
        self._task_type(payload.get("task_type"))
        return payload

    def _result_identity(self, payload: Mapping[str, Any], *, idempotency_key: str | None) -> str:
        if idempotency_key is not None and idempotency_key.strip():
            self._require_idempotency_key(idempotency_key)
        return self._source_digest(payload)

    @staticmethod
    def _source_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if key not in {"accepted_by", "accepted_at"}}

    @classmethod
    def _source_digest(cls, payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(cls._source_payload(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _relative_ref(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._vault_root()))
        except ValueError as exc:
            raise CloudMediaTaskReceiverError(
                "content_os_readback_unavailable",
                "云端结果证据路径无效。",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            ) from exc

    @staticmethod
    def _require_idempotency_key(value: str) -> str:
        return idempotency_key(
            value,
            error=lambda: CloudMediaTaskReceiverError("invalid_request", "幂等键无效。", status=HTTPStatus.BAD_REQUEST),
            policy=DEVICE_KEY,
        )

    @staticmethod
    def _task_id(value: Any) -> str:
        task_id = str(value or "").strip()
        if not _TASK_ID.fullmatch(task_id):
            raise CloudMediaTaskReceiverError("invalid_content_os_result", "task_id 无效。", status=HTTPStatus.BAD_REQUEST)
        return task_id

    @staticmethod
    def _task_type(value: Any) -> str:
        task_type = str(value or "").strip()
        if not _TASK_TYPE.fullmatch(task_type):
            raise CloudMediaTaskReceiverError("invalid_content_os_result", "task_type 无效。", status=HTTPStatus.BAD_REQUEST)
        return task_type

    @staticmethod
    def _text(value: Any, field: str, *, maximum: int) -> str:
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
            raise CloudMediaTaskReceiverError("content_os_readback_unavailable", f"{field} 无效。", status=HTTPStatus.SERVICE_UNAVAILABLE)
        return value.strip()

    @staticmethod
    def _revision(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise CloudMediaTaskReceiverError("content_os_readback_unavailable", "project_revision 无效。", status=HTTPStatus.SERVICE_UNAVAILABLE)
        return value

    @staticmethod
    def _mapping(value: Any, field: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise CloudMediaTaskReceiverError("retry_rejected", f"{field} 无效。", status=HTTPStatus.CONFLICT)
        return dict(value)

    @staticmethod
    def _strings(value: Any, field: str) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise CloudMediaTaskReceiverError("retry_rejected", f"{field} 无效。", status=HTTPStatus.CONFLICT)
        return [item.strip() for item in value]


__all__ = ["CloudMediaTaskReceiver", "CloudMediaTaskReceiverError"]
