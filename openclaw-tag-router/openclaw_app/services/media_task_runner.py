from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from common.model_transport_context import bind_model_transport

from .capability_registry import CAPABILITY_REGISTRY
from .media_task_repository import (
    ClaimedMediaTask,
    MediaTaskRepositoryError,
    PostgresMediaTaskRepository,
    digest_json,
)
from .media_web_tasks import (
    DELETION_TARGET_SEPARATOR,
    SAFE_ID,
    MediaWebTaskService,
    _public_feishu_docx_url,
    _requires_model_transport,
)
from .stage1_writer_gate import WRITER_CLOSED_ERROR_CODE, WRITER_CLOSED_MESSAGE


DELETION_PREVIEW_TTL_SECONDS = 15 * 60
FORBIDDEN_RESULT_TOKENS = (
    "/home/",
    "media://",
    "raw_prompt",
    "raw_response",
    "stack_trace",
    "traceback",
    "access_token",
    "refresh_token",
    "cookie",
    "record_id",
)
INTERNAL_RESULT_LINE = re.compile(
    r"^(?:状态|运行状态|阻塞来源|追溯\s*id)\s*[:：]", re.IGNORECASE
)
INTERNAL_STORAGE_LINE = re.compile(
    r"^(?:本地(?:路径|归档|文件|记录)|暂存路径|素材目录|文字稿任务目录|逐字稿路径|"
    r"周记路径|obsidian(?:详情|原字稿)?|多维表格)\s*[:：]",
    re.IGNORECASE,
)
FORBIDDEN_RESULT_URL = re.compile(
    r"https://(?:[^\s/]+\.)?(?:feishu\.cn|larksuite\.com|larkoffice\.com)/(?:base|bitable|wiki)/",
    re.IGNORECASE,
)
INTERNAL_RESULT_IDENTIFIER = re.compile(
    r"\b(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)+|(?:holder|trace|run|record|task|job)[_-][a-z0-9_-]+)\b",
    re.IGNORECASE,
)


class MediaTaskRunnerError(RuntimeError):
    def __init__(self, code: str, message: str, *, needs_manual: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.needs_manual = needs_manual


class _LeaseHeartbeat(AbstractContextManager["_LeaseHeartbeat"]):
    def __init__(
        self,
        repository: PostgresMediaTaskRepository,
        claim: ClaimedMediaTask,
        *,
        lease_seconds: int,
        heartbeat_seconds: float,
    ) -> None:
        self._repository = repository
        self._claim = claim
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_LeaseHeartbeat":
        self._repository.heartbeat(self._claim, lease_seconds=self._lease_seconds)
        self._thread = threading.Thread(
            target=self._run,
            name=f"media-task-heartbeat-{self._claim.attempt_public_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._heartbeat_seconds + 1)
        if exc is None:
            self.check()

    def check(self) -> None:
        if self._failure is not None:
            raise self._failure

    def _run(self) -> None:
        while not self._stop.wait(self._heartbeat_seconds):
            try:
                self._repository.heartbeat(
                    self._claim,
                    lease_seconds=self._lease_seconds,
                )
            except BaseException as exc:
                self._failure = exc
                self._stop.set()
                return


class MediaTaskRunner:
    """Independent process owner for PostgreSQL-backed Media task execution."""

    def __init__(
        self,
        app: Any,
        repository: PostgresMediaTaskRepository,
        task_service: MediaWebTaskService,
        *,
        runner_public_id: str,
        executor_public_id: str,
        tenant_model_gateway: Any | None = None,
        lease_seconds: int = 60,
        heartbeat_seconds: float | None = None,
        declared_application_ref: str = "",
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.app = app
        self.repository = repository
        self.task_service = task_service
        self.runner_public_id = str(runner_public_id or "").strip()
        self.executor_public_id = str(executor_public_id or "").strip()
        if not self.runner_public_id or not self.executor_public_id:
            raise ValueError("runner and executor public identities are required")
        if self.runner_public_id == self.executor_public_id:
            raise ValueError("runner and executor public identities must differ")
        self.lease_seconds = max(15, int(lease_seconds))
        default_heartbeat = max(1.0, self.lease_seconds / 3)
        self.heartbeat_seconds = float(heartbeat_seconds or default_heartbeat)
        if not 0 < self.heartbeat_seconds < self.lease_seconds:
            raise ValueError("heartbeat interval must be shorter than the lease")
        self.tenant_model_gateway = tenant_model_gateway
        self.declared_application_ref = str(declared_application_ref or "").strip()
        self._clock = clock
        self._sleeper = sleeper

    def run_once(self) -> bool:
        claim = self.repository.claim_next(
            runner_public_id=self.runner_public_id,
            executor_public_id=self.executor_public_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        try:
            self._execute_claim(claim)
        except MediaTaskRepositoryError as exc:
            if exc.code != "runner_lease_lost":
                self._record_failure(claim, exc.code, needs_manual=False)
        except MediaTaskRunnerError as exc:
            self._record_failure(claim, exc.code, needs_manual=exc.needs_manual)
        except Exception:
            self._record_failure(claim, "task_execution_failed", needs_manual=False)
        return True

    def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        interval = max(0.05, float(poll_seconds))
        while True:
            if not self.run_once():
                self._sleeper(interval)

    def _execute_claim(self, claim: ClaimedMediaTask) -> None:
        task = claim.task
        invocation = task.get("invocation")
        if not isinstance(invocation, Mapping):
            raise MediaTaskRunnerError("invalid_task_state", "任务调用结构无效。")
        capability_id = str(invocation.get("capability_id") or "")
        if capability_id == "selfmedia_creation":
            raise MediaTaskRunnerError(WRITER_CLOSED_ERROR_CODE, WRITER_CLOSED_MESSAGE)
        variant_id = str(invocation.get("variant_id") or "")
        params = invocation.get("params")
        if (
            invocation.get("catalog_version") != CAPABILITY_REGISTRY.catalog_version
            or not isinstance(params, Mapping)
        ):
            raise MediaTaskRunnerError("catalog_conflict", "任务能力目录版本已过期。")
        capability = CAPABILITY_REGISTRY.require_valid_invocation(
            capability_id,
            variant_id,
            params,
        )
        if not callable(getattr(self.app, "process_capability_invocation", None)):
            raise MediaTaskRunnerError("service_unavailable", "能力执行服务不可用。")
        if not callable(getattr(getattr(self.app, "router", None), capability.handler, None)):
            raise MediaTaskRunnerError("service_unavailable", "能力处理器不可用。")

        uploads = self.task_service.runner_uploads(task)
        MediaWebTaskService._validate_upload_contract(capability, uploads)
        attachments = [
            {
                "file_name": item["filename"],
                "mime_type": item["mime_type"],
                "local_path": item["storage_path"],
                "sha256": item["sha256"],
            }
            for item in uploads
        ]
        binding = invocation.get("account_binding")
        metadata = {
            "tenant_id": task["tenant_id"],
            "tenant_context": {"tenant_id": task["tenant_id"]},
            "user_public_id": task["actor_public_id"],
            "account_binding": dict(binding) if isinstance(binding, Mapping) else None,
            "channel": "media_task_runner",
            "account_id": "media",
            "bot": "Media bot",
            "canonical_capability_id": capability_id,
            "capability_variant_id": variant_id,
            "media_web_task_id": task["task_id"],
            "media_task_attempt_id": claim.attempt_public_id,
            "attachments": attachments,
            "downloaded_paths": [item["storage_path"] for item in uploads],
            "is_maintainer": bool((task.get("authorization") or {}).get("is_maintainer")),
        }
        self.repository.transition_claim(
            claim,
            task_status="running",
            settlement_stage="executing",
            attempt_status="running",
            progress=20,
            message="任务开始处理。",
        )
        with _LeaseHeartbeat(
            self.repository,
            claim,
            lease_seconds=self.lease_seconds,
            heartbeat_seconds=self.heartbeat_seconds,
        ) as heartbeat:
            model_request_root = str(task.get("model_request_root") or "")
            if self.tenant_model_gateway is not None and _requires_model_transport(
                capability_id, variant_id
            ):
                if not model_request_root:
                    raise MediaTaskRunnerError("invalid_task_state", "任务缺少模型调用引用。")
                model_scope = self.tenant_model_gateway.bind(
                    task["tenant_id"],
                    task["actor_public_id"],
                    task["task_id"],
                    model_request_root,
                )
            else:
                model_scope = bind_model_transport(
                    None,
                    required=_requires_model_transport(capability_id, variant_id),
                )
            with model_scope:
                result = self.app.process_capability_invocation(
                    capability_id=capability_id,
                    variant_id=variant_id,
                    params=dict(params),
                    source="web",
                    chat_type="private",
                    metadata=metadata,
                )
            heartbeat.check()
            if self._model_settlement_unknown(task["tenant_id"], task["task_id"]):
                raise MediaTaskRunnerError(
                    "model_settlement_unknown",
                    "模型调用结果需要对账。",
                    needs_manual=True,
                )
            refreshed = self.repository.get_task_for_runner(
                task["tenant_id"], task["task_id"]
            )
            if refreshed.get("cancel_requested"):
                raise MediaTaskRunnerError(
                    "task_cancelled_after_execution",
                    "任务执行后收到取消请求，需要核对已发生写入。",
                    needs_manual=True,
                )
            raw_result = asdict(result) if is_dataclass(result) else dict(result or {})
            result_projection = self._project_result(raw_result, task=task)
            if not result_projection["ok"]:
                needs_manual = result_projection["status"] == "needs_attention"
                raise MediaTaskRunnerError(
                    "capability_execution_incomplete",
                    "能力执行未形成可结算结果。",
                    needs_manual=needs_manual,
                )

            self.repository.transition_claim(
                claim,
                task_status="waiting_database_readback",
                settlement_stage="database_readback",
                attempt_status="waiting_database_readback",
                progress=70,
                message="内容已生成，正在确认保存结果。",
            )
            artifacts = self._artifact_records(task, raw_result, result_projection)
            self.repository.transition_claim(
                claim,
                task_status="waiting_external_readback",
                settlement_stage="external_readback",
                attempt_status="waiting_external_readback",
                progress=80,
                message="正在确认任务结果。",
            )
            external_objects, external_readback = self._external_readback(
                capability_id,
                raw_result,
            )
            heartbeat.check()
            self.repository.record_execution_result(
                claim,
                result_projection=result_projection,
                artifact_records=artifacts,
                external_objects=external_objects,
                external_readback=external_readback,
            )

    def _external_readback(
        self,
        capability_id: str,
        raw_result: Mapping[str, Any],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        if capability_id == "selfmedia_creation_consultation":
            return [], {
                "status": "not_applicable",
                "noNewFeishuObject": True,
                "externalWriteSet": [],
            }
        if capability_id != "selfmedia_creation":
            return [], {"status": "not_applicable"}
        document_url = _public_feishu_docx_url(raw_result.get("feishu_doc"))
        if not document_url:
            raise MediaTaskRunnerError(
                "external_readback_incomplete",
                "写入创作链缺少严格的飞书 Docx 链接。",
            )
        if not self.declared_application_ref:
            raise MediaTaskRunnerError(
                "declared_application_identity_missing",
                "写入创作链缺少声明应用身份。",
            )
        read_document = getattr(getattr(self.app, "feishu_service", None), "read_document_text", None)
        if not callable(read_document):
            raise MediaTaskRunnerError("service_unavailable", "飞书读回服务不可用。")
        readback = read_document(document_url)
        text = readback.get("text") if isinstance(readback, Mapping) else None
        if not isinstance(readback, Mapping) or readback.get("ok") is not True or not isinstance(text, str):
            raise MediaTaskRunnerError(
                "external_readback_incomplete",
                "写入创作链尚未完成声明应用身份的飞书读回。",
            )
        return [
            {
                "external_system": "feishu",
                "external_object_public_ref": document_url,
                "object_digest": digest_json(text),
                "declared_application_ref": self.declared_application_ref,
            }
        ], {"status": "verified"}

    @staticmethod
    def _artifact_records(
        task: Mapping[str, Any],
        raw_result: Mapping[str, Any],
        result_projection: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        runtime_id = str(raw_result.get("task_id") or "").strip()
        artifact_suffix = runtime_id if SAFE_ID.fullmatch(runtime_id) else str(task["task_id"])
        return [
            {
                "artifact_public_id": f"result:{task['capability_id']}:{artifact_suffix}",
                "artifact_kind": "structured_result",
                "content_digest": digest_json(result_projection),
            }
        ]

    def _model_settlement_unknown(self, tenant_id: str, task_id: str) -> bool:
        if self.tenant_model_gateway is None:
            return False
        calls = self.tenant_model_gateway.task_calls(tenant_id, task_id)
        return any(
            isinstance(item, Mapping) and item.get("status") == "unknown_reconcile"
            for item in calls
        )

    def _record_failure(
        self,
        claim: ClaimedMediaTask,
        code: str,
        *,
        needs_manual: bool,
    ) -> None:
        try:
            self.repository.record_failure(
                claim,
                code=str(code or "task_execution_failed"),
                message="任务未形成完整结果。",
                action=(
                    "请由维护者核对已发生的执行和外部写入后再处理。"
                    if needs_manual
                    else "检查输入与来源状态后重试；仍失败时由维护者查看任务审计。"
                ),
                needs_manual=needs_manual,
            )
        except MediaTaskRepositoryError as exc:
            if exc.code != "runner_lease_lost":
                raise

    def _project_result(
        self,
        raw: Mapping[str, Any],
        *,
        task: Mapping[str, Any],
    ) -> dict[str, Any]:
        status = str(raw.get("status") or "unknown")
        public_status = (
            "completed"
            if bool(raw.get("ok"))
            else "needs_attention"
            if any(token in status.lower() for token in ("pending", "manual", "attention"))
            else "failed"
        )
        receipt = self._capability_receipt(raw, task=task)
        links: list[dict[str, str]] = []
        document_url = _public_feishu_docx_url(raw.get("feishu_doc"))
        if document_url:
            links.append({"label": "查看交付文档", "url": document_url})
        return {
            "ok": bool(raw.get("ok")),
            "status": public_status,
            "reply": self._public_reply(
                str(raw.get("reply") or ""),
                receipt=receipt,
                public_status=public_status,
            ),
            "links": links,
            "receipt": receipt,
        }

    def _capability_receipt(
        self,
        raw: Mapping[str, Any],
        *,
        task: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        status = str(raw.get("status") or "")
        extra = raw.get("extra") if isinstance(raw.get("extra"), Mapping) else {}
        if status == "creator_profile_candidate_ready":
            candidate = extra.get("creator_profile_candidate")
            run_id = str(candidate.get("run_id") or "") if isinstance(candidate, Mapping) else ""
            return {"kind": "creator_profile_candidate", "runId": run_id} if SAFE_ID.fullmatch(run_id) else None
        if status == "creator_profile_confirmed_written":
            confirmation = extra.get("creator_profile_confirm")
            creator = confirmation.get("creator_profile") if isinstance(confirmation, Mapping) else None
            record_id = str(creator.get("record_id") or "") if isinstance(creator, Mapping) else ""
            return {"kind": "creator_profile_written", "recordId": record_id} if SAFE_ID.fullmatch(record_id) else None
        if status != "deletion_dry_run":
            return None
        invocation = task.get("invocation") if isinstance(task.get("invocation"), Mapping) else {}
        params = invocation.get("params") if isinstance(invocation.get("params"), Mapping) else {}
        target_ids = sorted(
            value
            for value in DELETION_TARGET_SEPARATOR.split(str(params.get("id") or "").strip())
            if value
        )
        if not target_ids:
            return None
        deletion = extra.get("deletion")
        entity_count = 0
        digest_source: Any = {"target_ids": target_ids, "reply": str(raw.get("reply") or "")}
        if isinstance(deletion, list):
            planned = sorted(
                {
                    str(item.get("target_id") or "")
                    for item in deletion
                    if isinstance(item, Mapping) and item.get("target_id")
                }
            )
            target_ids = planned or target_ids
            entity_count = sum(
                len(item.get("entities") or [])
                for item in deletion
                if isinstance(item, Mapping)
            )
            digest_source = deletion
        encoded = json.dumps(
            digest_source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expires_at = datetime.fromtimestamp(
            self._clock() + DELETION_PREVIEW_TTL_SECONDS,
            tz=timezone.utc,
        ).isoformat().replace("+00:00", "Z")
        return {
            "kind": "deletion_preview",
            "previewTaskId": str(task["task_id"]),
            "targetIds": target_ids,
            "targetCount": len(target_ids),
            "entityCount": entity_count,
            "planDigest": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
            "expiresAt": expires_at,
        }

    @staticmethod
    def _public_reply(
        reply: str,
        *,
        receipt: Mapping[str, Any] | None,
        public_status: str,
    ) -> str:
        receipt_kind = str((receipt or {}).get("kind") or "")
        if receipt_kind == "creator_profile_candidate":
            return "候选已生成，请核对表单后确认写入达人档案。"
        if receipt_kind == "creator_profile_written":
            return "达人档案已写入并确认完成。"
        if receipt_kind == "deletion_preview":
            return "删除影响范围已生成。"
        lines: list[str] = []
        for raw_line in reply.splitlines():
            line = raw_line.strip()
            lowered = line.lower()
            if not line or INTERNAL_RESULT_LINE.search(line) or INTERNAL_STORAGE_LINE.search(line):
                continue
            if any(token in lowered for token in FORBIDDEN_RESULT_TOKENS):
                continue
            if FORBIDDEN_RESULT_URL.search(line) or INTERNAL_RESULT_IDENTIFIER.search(line):
                continue
            lines.append(line)
        if lines:
            return "\n".join(lines)
        if public_status == "completed":
            return "任务已完成，可从对应业务页面查看结果。"
        if public_status == "needs_attention":
            return "任务需要补充信息或外部来源暂不可用，请检查输入与来源状态后重试。"
        return "任务未完成，请检查输入后重试；仍失败时由维护者查看受控审计记录。"


__all__ = ["MediaTaskRunner", "MediaTaskRunnerError"]
