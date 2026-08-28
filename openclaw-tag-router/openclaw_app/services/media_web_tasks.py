"""Canonical Media Web task facade.

The file-backed engine remains responsible for the locally quarantined upload
store. When a task repository is configured, task lifecycle facts are read and
written through it so the independent runner and HTTP surface share one task.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from . import media_web_tasks_core as _core
from .media_task_repository import (
    TERMINAL_TASK_STATUSES,
    MediaTaskRepositoryError,
    task_requires_owned_account,
)

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


_REPOSITORY_TERMINAL_STATES = frozenset(TERMINAL_TASK_STATUSES)


def _as_media_task_error(error: MediaTaskRepositoryError) -> _core.MediaWebTaskError:
    return _core.MediaWebTaskError(error.code, error.message)


class MediaWebTaskService(_core.MediaWebTaskService):
    """HTTP-compatible service with a repository-backed task lifecycle."""

    def __init__(
        self,
        app: Any,
        *,
        repository: Any | None = None,
        content_flow_client: Any | None = None,
        **kwargs: Any,
    ) -> None:
        # A repository task is claimed by MediaTaskRunner. The historical file
        # worker must not become a second execution owner.
        if repository is not None:
            kwargs["start_worker"] = False
        self.repository = repository
        self.content_flow_client = content_flow_client
        super().__init__(app, **kwargs)

    def create_task(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        is_maintainer: bool = False,
        user_public_id: str | None = None,
        workspace_mode: str | None = None,
        role: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if self.repository is None:
            return super().create_task(
                payload,
                tenant_id=tenant_id,
                is_maintainer=is_maintainer,
                user_public_id=user_public_id,
                workspace_mode=workspace_mode,
                role=role,
            )

        tenant_id = _core._require_tenant_id(tenant_id)
        actor_public_id = str(user_public_id or "").strip()
        normalized_workspace_mode = str(workspace_mode or "").strip()
        normalized_role = str(role or "").strip()
        expected_keys = {
            "schemaVersion",
            "capabilityId",
            "variantId",
            "params",
            "uploadIds",
            "idempotencyKey",
            "catalogVersion",
            "initiation",
            "confirmationReceipt",
        }
        if (
            set(payload) != expected_keys
            or payload.get("schemaVersion") != "3"
            or _core._contains_reserved_tenant_key(payload)
        ):
            raise _core.MediaWebTaskError("invalid_request", "任务请求不符合结构化契约。")

        capability_id = str(payload.get("capabilityId") or "").strip()
        variant_id = str(payload.get("variantId") or "").strip()
        capability = self._registry.get(capability_id)
        if (
            capability is None
            or not capability.enabled
            or not set(capability.bots) & {"Media bot", "任意 Bot"}
            or capability.visibility
            not in ({"public", "ops", "maintainer"} if is_maintainer else {"public", "ops"})
        ):
            raise _core.MediaWebTaskError("capability_not_found", "未找到可用的 Media 能力。")
        if payload.get("catalogVersion") != self._registry.catalog_version:
            raise _core.MediaWebTaskError("catalog_conflict", "能力目录已更新，请刷新后重新确认任务。")

        raw_params = payload.get("params")
        if not isinstance(raw_params, Mapping):
            raise _core.MediaWebTaskError("invalid_request", "任务参数必须是结构化对象。")
        params = dict(raw_params)
        if len(json.dumps(params, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > _core.MAX_PARAMS_BYTES:
            raise _core.MediaWebTaskError("payload_too_large", "输入或文件超过大小限制。")
        issues = self._registry.validation_issues(capability_id, variant_id, params)
        if issues:
            raise _core.MediaWebTaskError(
                str(issues[0]["code"]),
                str(issues[0]["message"]),
                details={"issues": list(issues)},
            )

        raw_upload_ids = payload.get("uploadIds")
        if not isinstance(raw_upload_ids, list) or len(raw_upload_ids) > _core.MAX_UPLOADS_PER_TASK:
            raise _core.MediaWebTaskError("invalid_request", "上传文件引用无效。")
        upload_ids = [str(value) for value in raw_upload_ids]
        uploads = [self._load_upload(value, tenant_id=tenant_id) for value in upload_ids]
        if any(item["status"] != "ready" for item in uploads):
            raise _core.MediaWebTaskError("task_conflict", "上传文件尚未准备完成。")
        self._validate_upload_contract(capability, uploads)

        if str(payload.get("initiation") or "") not in {"manual", "ai"}:
            raise _core.MediaWebTaskError("invalid_request", "任务发起来源无效。")
        confirmation_receipt = payload.get("confirmationReceipt")
        requires_preview = (
            (capability_id == "universal_deletion" and variant_id == "confirm")
            or (capability_id == "creator_profile_upsert" and variant_id == "confirm")
            or (capability_id == "track_creator_membership_query" and variant_id == "confirm")
        )
        if not requires_preview and confirmation_receipt is not None:
            raise _core.MediaWebTaskError("invalid_request", "此任务不接受确认回执。")
        if requires_preview and not isinstance(confirmation_receipt, Mapping):
            raise _core.MediaWebTaskError(
                _core._confirmation_receipt_error(capability_id),
                "确认必须携带用户所见预览的完整回执。",
            )
        if requires_preview:
            self._validate_repository_confirmation_preview(
                tenant_id=tenant_id,
                actor_public_id=actor_public_id,
                capability_id=capability_id,
                params=params,
                receipt=dict(confirmation_receipt or {}),
            )

        idempotency_key = str(payload.get("idempotencyKey") or "").strip()
        if (
            not idempotency_key
            or len(idempotency_key) > 128
            or not _core.SAFE_ID.fullmatch(idempotency_key)
        ):
            raise _core.MediaWebTaskError("invalid_request", "幂等键无效。")
        if not actor_public_id or not normalized_workspace_mode or not normalized_role:
            raise _core.MediaWebTaskError("workspace_not_allowed", "当前会话不能在该工作区创建任务。")

        if self._tenant_model_gateway is not None and _core._requires_model_transport(capability_id, variant_id):
            try:
                self._tenant_model_gateway.prepare()
            except Exception as exc:
                raise _core.MediaWebTaskError(
                    str(getattr(exc, "code", "model_transport_unavailable")),
                    "租户模型凭证不可用。",
                ) from exc

        account_binding: dict[str, str] | None = None
        if task_requires_owned_account(capability_id, params):
            try:
                account_binding = self.repository.resolve_owned_account(
                    tenant_id=tenant_id,
                    user_public_id=actor_public_id,
                    platform=str(params.get("platform") or ""),
                    submitted_account_ref=str(params.get("field_311bb313fdec") or ""),
                )
            except MediaTaskRepositoryError as exc:
                raise _as_media_task_error(exc) from exc

        confirmation_required = self._invocation_requires_confirmation(capability, variant_id)
        invocation: dict[str, Any] = {
            "capability_id": capability.capability_id,
            "variant_id": variant_id,
            "params": params,
            "upload_ids": upload_ids,
            "initiation": payload["initiation"],
            "catalog_version": self._registry.catalog_version,
            "confirmation_receipt": confirmation_receipt,
        }
        if account_binding is not None:
            invocation["account_binding"] = account_binding
        repository_task = {
            "tenant_id": tenant_id,
            "task_id": f"mwt_{uuid.uuid4().hex}",
            "actor_public_id": actor_public_id,
            "owned_account_public_id": (
                account_binding.get("owned_account_public_id")
                if account_binding is not None
                else None
            ),
            "idempotency_key": idempotency_key,
            "request_fingerprint": _core._task_request_fingerprint(payload),
            "capability_id": capability.capability_id,
            "variant_id": variant_id,
            "catalog_version": self._registry.catalog_version,
            "invocation": invocation,
            "capability_path": list(capability.hierarchy.path_names),
            "authorization": {
                "workspace_mode": normalized_workspace_mode,
                "role": normalized_role,
                "is_maintainer": bool(is_maintainer),
            },
            "confirmation": {
                "state": "required" if confirmation_required else "not_required",
                "required": confirmation_required,
                "note": "",
                "decided_at": "",
            },
            "status": "awaiting_confirmation" if confirmation_required else "queued",
            "settlement_stage": "awaiting_confirmation" if confirmation_required else "queued",
            "progress": 0,
            "summary": self._registry.summary(capability_id, params),
            "model_request_root": f"mreq_{uuid.uuid4().hex}",
        }
        try:
            stored, created = self.repository.create_task(repository_task)
        except MediaTaskRepositoryError as exc:
            raise _as_media_task_error(exc) from exc
        return self._project_repository_task(stored, actor_public_id), created

    def list_tasks(
        self,
        *,
        tenant_id: str,
        limit: int = 20,
        user_public_id: str | None = None,
    ) -> dict[str, Any]:
        if self.repository is None:
            return super().list_tasks(tenant_id=tenant_id, limit=limit, user_public_id=user_public_id)
        actor_public_id = str(user_public_id or "").strip()
        try:
            tasks = self.repository.list_tasks(tenant_id, actor_public_id, limit)
        except MediaTaskRepositoryError as exc:
            raise _as_media_task_error(exc) from exc
        return {
            "schemaVersion": _core.SCHEMA_VERSION,
            "tasks": [self._project_repository_task(task, actor_public_id) for task in tasks],
        }

    def get_task(
        self,
        task_id: str,
        *,
        tenant_id: str,
        user_public_id: str | None = None,
    ) -> dict[str, Any]:
        if self.repository is None:
            return super().get_task(task_id, tenant_id=tenant_id, user_public_id=user_public_id)
        return self._repository_task_projection(task_id, tenant_id=tenant_id, user_public_id=user_public_id)

    def get_events(
        self,
        task_id: str,
        *,
        tenant_id: str,
        after: int = 0,
        user_public_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.repository is None:
            return super().get_events(task_id, tenant_id=tenant_id, after=after, user_public_id=user_public_id)
        try:
            return self.repository.list_events(tenant_id, str(user_public_id or "").strip(), task_id, after)
        except MediaTaskRepositoryError as exc:
            raise _as_media_task_error(exc) from exc

    def cancel_task(
        self,
        task_id: str,
        *,
        tenant_id: str,
        user_public_id: str | None = None,
    ) -> dict[str, Any]:
        if self.repository is None:
            return super().cancel_task(task_id, tenant_id=tenant_id, user_public_id=user_public_id)
        actor_public_id = str(user_public_id or "").strip()
        try:
            task = self.repository.request_cancel(tenant_id, actor_public_id, task_id)
        except MediaTaskRepositoryError as exc:
            raise _as_media_task_error(exc) from exc
        return self._project_repository_task(task, actor_public_id)

    def confirm_task(
        self,
        task_id: str,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        user_public_id: str | None = None,
    ) -> dict[str, Any]:
        if self.repository is None:
            return super().confirm_task(task_id, payload, tenant_id=tenant_id, user_public_id=user_public_id)
        if set(payload) != {"decision", "note"} or _core._contains_reserved_tenant_key(payload):
            raise _core.MediaWebTaskError("invalid_request", "确认信息无效。")
        decision = str(payload.get("decision") or "").strip()
        note = str(payload.get("note") or "").strip()
        if decision not in {"approve", "reject"} or len(note.encode("utf-8")) > 4096:
            raise _core.MediaWebTaskError("invalid_request", "确认信息无效。")
        actor_public_id = str(user_public_id or "").strip()
        try:
            current = self.repository.get_task(tenant_id, actor_public_id, task_id)
            invocation = current.get("invocation")
            if decision == "approve" and isinstance(invocation, Mapping):
                capability_id = str(invocation.get("capability_id") or "")
                variant_id = str(invocation.get("variant_id") or "")
                receipt = invocation.get("confirmation_receipt")
                if variant_id == "confirm" and capability_id in {
                    "universal_deletion",
                    "creator_profile_upsert",
                    "track_creator_membership_query",
                }:
                    self._validate_repository_confirmation_preview(
                        tenant_id=tenant_id,
                        actor_public_id=actor_public_id,
                        capability_id=capability_id,
                        params=(dict(invocation.get("params")) if isinstance(invocation.get("params"), Mapping) else {}),
                        receipt=dict(receipt) if isinstance(receipt, Mapping) else {},
                    )
            task = self.repository.decide_confirmation(
                tenant_id, actor_public_id, task_id, decision=decision, note=note
            )
        except MediaTaskRepositoryError as exc:
            raise _as_media_task_error(exc) from exc
        return self._project_repository_task(task, actor_public_id)

    def _repository_task_projection(
        self,
        task_id: str,
        *,
        tenant_id: str,
        user_public_id: str | None,
    ) -> dict[str, Any]:
        actor_public_id = str(user_public_id or "").strip()
        try:
            task = self.repository.get_task(tenant_id, actor_public_id, task_id)
        except MediaTaskRepositoryError as exc:
            raise _as_media_task_error(exc) from exc
        return self._project_repository_task(task, actor_public_id)

    def _project_repository_task(self, task: Mapping[str, Any], actor_public_id: str) -> dict[str, Any]:
        tenant_id = str(task.get("tenant_id") or "")
        task_id = str(task.get("task_id") or "")
        try:
            settlement = self.repository.get_settlement(tenant_id, actor_public_id, task_id)
        except MediaTaskRepositoryError as exc:
            raise _as_media_task_error(exc) from exc
        internal = dict(task)
        invocation = dict(task.get("invocation") or {})
        internal["invocation"] = invocation
        binding = invocation.get("account_binding")
        internal["account_binding"] = (
            {
                "userPublicId": binding.get("actor_public_id"),
                "ownedAccountPublicId": binding.get("owned_account_public_id"),
                "relationshipRef": binding.get("relationship_ref"),
                "platform": binding.get("platform"),
                "normalizedAccount": binding.get("normalized_account"),
            }
            if isinstance(binding, Mapping)
            else None
        )
        internal["attempt"] = settlement.get("attempt")
        internal["readbacks"] = settlement.get("readbacks") or None
        internal["receipt"] = settlement.get("receipt")
        readbacks = settlement.get("readbacks")
        internal["missing_readbacks"] = [
            str(kind)
            for kind, item in (readbacks.items() if isinstance(readbacks, Mapping) else [])
            if isinstance(item, Mapping) and item.get("required") is True and item.get("status") != "verified"
        ]
        projection = self._project(internal)
        projection["terminal"] = str(task.get("status") or "") in _REPOSITORY_TERMINAL_STATES
        return projection

    def _validate_repository_confirmation_preview(
        self,
        *,
        tenant_id: str,
        actor_public_id: str,
        capability_id: str,
        params: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        error_code = _core._confirmation_receipt_error(capability_id)
        preview_task_id = str(receipt.get("previewTaskId") or "")
        if not _core.SAFE_ID.fullmatch(preview_task_id):
            raise _core.MediaWebTaskError(error_code, "确认所需预览不存在、已过期或不匹配。")
        try:
            preview = self.repository.get_task(tenant_id, actor_public_id, preview_task_id)
        except MediaTaskRepositoryError as exc:
            raise _core.MediaWebTaskError(error_code, "确认所需预览不存在、已过期或不匹配。") from exc
        result = preview.get("result")
        actual = result.get("receipt") if isinstance(result, Mapping) else None
        expected_kind = {
            "universal_deletion": "deletion_preview",
            "creator_profile_upsert": "creator_profile_candidate",
            "track_creator_membership_query": "track_creator_membership_preview",
        }[capability_id]
        expected_statuses = (
            {"multi_system_readback_complete", "pending_manual"}
            if capability_id == "track_creator_membership_query"
            else {"multi_system_readback_complete"}
        )
        digest_key = {
            "universal_deletion": "planDigest",
            "creator_profile_upsert": "candidateDigest",
            "track_creator_membership_query": "fieldsDigest",
        }[capability_id]
        if (
            preview.get("status") not in expected_statuses
            or not isinstance(actual, Mapping)
            or dict(receipt) != dict(actual)
            or actual.get("kind") != expected_kind
            or actual.get("previewTaskId") != preview.get("task_id")
            or not _core.RECEIPT_DIGEST.fullmatch(str(actual.get(digest_key) or ""))
            or _core._timestamp(actual.get("expiresAt")) is None
            or (_core._timestamp(actual.get("expiresAt")) or 0) <= self._clock()
        ):
            raise _core.MediaWebTaskError(error_code, "确认所需预览不存在、已过期或不匹配。")
        if capability_id == "universal_deletion":
            target_ids = actual.get("targetIds")
            if (
                not isinstance(target_ids, list)
                or not target_ids
                or any(not isinstance(value, str) or not _core.SAFE_ID.fullmatch(value) for value in target_ids)
                or actual.get("targetCount") != len(target_ids)
                or not isinstance(actual.get("entityCount"), int)
                or actual["entityCount"] < 0
                or tuple(sorted(target_ids)) != _core._deletion_target_ids(params)
            ):
                raise _core.MediaWebTaskError(error_code, "确认所需预览不存在、已过期或不匹配。")
        elif capability_id == "creator_profile_upsert":
            if actual.get("runId") != str(params.get("run_id") or ""):
                raise _core.MediaWebTaskError(error_code, "确认所需预览不存在、已过期或不匹配。")
        elif actual.get("fieldsDigest") != _core._confirmation_fields_digest(params):
            raise _core.MediaWebTaskError(error_code, "确认所需预览不存在、已过期或不匹配。")


MediaWebTaskError = _core.MediaWebTaskError


__all__ = sorted(
    {
        *(name for name in dir(_core) if not name.startswith("_")),
        "MediaWebTaskError",
        "MediaWebTaskService",
    }
)
