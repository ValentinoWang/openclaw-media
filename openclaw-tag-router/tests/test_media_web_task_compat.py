from __future__ import annotations

import ast
import base64
import inspect
import json
import uuid
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from openclaw_app.adapters import http_api
from openclaw_app.services.media_web_tasks import MediaWebTaskError, MediaWebTaskService


class _App:
    router = SimpleNamespace()


class _Repository:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[str] = []

    def create_task(self, task: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        self.calls.append("create")
        stored = {
            **task,
            "result": None,
            "error": None,
            "cancel_requested": False,
            "event_cursor": 1,
            "created_at": "2026-08-29T00:00:00Z",
            "updated_at": "2026-08-29T00:00:00Z",
        }
        self.tasks[stored["task_id"]] = stored
        self.events[stored["task_id"]] = [{
            "eventId": 1,
            "taskId": stored["task_id"],
            "type": "task.created",
            "status": stored["status"],
            "progress": stored["progress"],
            "message": "任务已提交，正在排队。",
            "createdAt": stored["created_at"],
        }]
        return stored, True

    def get_task(self, tenant_id: str, actor_public_id: str, task_id: str) -> dict[str, Any]:
        self.calls.append("get")
        task = self.tasks[task_id]
        assert task["tenant_id"] == tenant_id
        assert task["actor_public_id"] == actor_public_id
        return task

    def list_tasks(self, tenant_id: str, actor_public_id: str, limit: int) -> list[dict[str, Any]]:
        self.calls.append("list")
        return [
            task for task in self.tasks.values()
            if task["tenant_id"] == tenant_id and task["actor_public_id"] == actor_public_id
        ][:limit]

    def list_events(self, tenant_id: str, actor_public_id: str, task_id: str, after: int) -> list[dict[str, Any]]:
        self.calls.append("events")
        self.get_task(tenant_id, actor_public_id, task_id)
        return [event for event in self.events[task_id] if event["eventId"] > after]

    def request_cancel(self, tenant_id: str, actor_public_id: str, task_id: str) -> dict[str, Any]:
        self.calls.append("cancel")
        task = self.get_task(tenant_id, actor_public_id, task_id)
        task.update(status="cancelled", settlement_stage="cancelled", progress=100)
        return task

    def decide_confirmation(
        self,
        tenant_id: str,
        actor_public_id: str,
        task_id: str,
        *,
        decision: str,
        note: str,
    ) -> dict[str, Any]:
        self.calls.append("confirm")
        task = self.get_task(tenant_id, actor_public_id, task_id)
        task["confirmation"] = {
            **task["confirmation"],
            "state": "approved" if decision == "approve" else "rejected",
            "note": note,
            "decided_at": "2026-08-29T00:01:00Z",
        }
        return task

    def get_settlement(self, tenant_id: str, actor_public_id: str, task_id: str) -> dict[str, Any]:
        self.calls.append("settlement")
        self.get_task(tenant_id, actor_public_id, task_id)
        return {"attempt": None, "readbacks": {}, "receipt": None}


def test_current_composition_accepts_repository_and_content_flow_client(tmp_path) -> None:
    repository = object()
    content_flow_client = object()
    tenant_model_gateway = object()
    service = MediaWebTaskService(
        _App(),
        root=tmp_path,
        repository=repository,
        content_flow_client=content_flow_client,
        tenant_model_gateway=tenant_model_gateway,
        start_worker=False,
        start_cleanup_worker=False,
    )
    try:
        assert service.repository is repository
        assert service.content_flow_client is content_flow_client
        assert service._tenant_model_gateway is tenant_model_gateway
    finally:
        service.close()


def test_server_cli_constructs_the_repository_backed_task_service() -> None:
    source = (Path(__file__).resolve().parents[1] / "openclaw_app/server_cli.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    task_service_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "MediaWebTaskService"
    ]
    assert len(task_service_calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in task_service_calls[0].keywords}
    assert isinstance(keywords.get("repository"), ast.Name)
    assert keywords["repository"].id == "task_repository"
    assert isinstance(keywords.get("tenant_model_gateway"), ast.Name)
    assert keywords["tenant_model_gateway"].id == "tenant_model_gateway"
    assert isinstance(keywords.get("content_flow_client"), ast.Attribute)
    assert keywords["content_flow_client"].attr == "content_flow_client"


def test_repository_backed_tasks_are_visible_to_runner_without_file_task_state(tmp_path) -> None:
    repository = _Repository()
    service = MediaWebTaskService(
        _App(),
        root=tmp_path,
        repository=repository,
        start_worker=True,
        start_cleanup_worker=False,
    )
    tenant_id = str(uuid.uuid4())
    payload = {
        "schemaVersion": "3",
        "capabilityId": "platform_hotlist",
        "variantId": "default",
        "params": {"platform": "小红书", "field_1f7f0db90f93": "跑步"},
        "uploadIds": [],
        "idempotencyKey": "repository-task-0001",
        "catalogVersion": service.capability_catalog()["catalogVersion"],
        "initiation": "manual",
        "confirmationReceipt": None,
    }
    try:
        created, is_new = service.create_task(
            payload,
            tenant_id=tenant_id,
            user_public_id="user-public-001",
            workspace_mode="personal_web",
            role="user",
        )
        assert is_new is True
        assert created["status"] == "queued"
        assert created["terminal"] is False
        assert created["result"] is None
        assert service._executor is None
        assert not list((tmp_path / "tasks").rglob("mwt_*.json"))

        listed = service.list_tasks(tenant_id=tenant_id, user_public_id="user-public-001")
        assert listed["tasks"][0]["taskId"] == created["taskId"]
        assert service.get_events(created["taskId"], tenant_id=tenant_id, user_public_id="user-public-001")

        cancelled = service.cancel_task(
            created["taskId"], tenant_id=tenant_id, user_public_id="user-public-001"
        )
        assert cancelled["status"] == "cancelled"
        assert cancelled["terminal"] is True
        assert {"create", "list", "events", "cancel", "settlement"}.issubset(repository.calls)
    finally:
        service.close()


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("invalid_request", 400),
        ("task_not_found", 404),
        ("idempotency_conflict", 409),
        ("payload_too_large", 413),
        ("service_unavailable", 503),
    ],
)
def test_media_web_error_exposes_stable_http_contract(code: str, status: int) -> None:
    error = MediaWebTaskError(code, "message")
    assert error.status == status
    assert error.details == {}
    error.issues = [{"field": "title", "code": "required"}]
    assert error.details == {"issues": error.issues}


def test_api_error_matches_media_web_task_error_schema() -> None:
    captured: dict[str, object] = {}
    handler = SimpleNamespace(
        _send_json=lambda status, payload, headers=None: captured.update(
            status=int(status),
            payload=payload,
            headers=headers,
        )
    )

    http_api.OpenClawHttpHandler._send_api_error(
        handler,
        HTTPStatus.SERVICE_UNAVAILABLE,
        "service_unavailable",
        "服务暂时不可用，请稍后重试。",
        details={"retryAfterSeconds": 30},
    )

    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "openclaw_app/contracts/media_web_task.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(captured["payload"])
    assert captured == {
        "status": 503,
        "payload": {
            "ok": False,
            "error": {
                "code": "service_unavailable",
                "message": "服务暂时不可用，请稍后重试。",
                "details": {"retryAfterSeconds": 30},
            },
        },
        "headers": None,
    }


def test_if2_upload_v3_calls_real_upload_service(tmp_path) -> None:
    service = MediaWebTaskService(
        _App(),
        root=tmp_path,
        start_worker=False,
        start_cleanup_worker=False,
    )
    tenant_id = str(uuid.uuid4())
    captured: dict[str, object] = {}
    handler = SimpleNamespace(
        media_web_tasks=service,
        _send_json=lambda status, payload: captured.update(status=int(status), payload=payload),
        _send_api_error=lambda *_args, **_kwargs: pytest.fail("unexpected API error"),
    )
    context = SimpleNamespace(
        principal=SimpleNamespace(tenant_id=tenant_id),
        idempotency=SimpleNamespace(key="upload-test-key"),
    )
    body = {
        "schemaVersion": "3",
        "filename": "note.txt",
        "contentBase64": base64.b64encode("hello".encode()).decode(),
        "idempotencyKey": "upload-test-key",
    }
    try:
        http_api.OpenClawHttpHandler._execute_media_upload(handler, context, body)
        assert captured["status"] == 201
        assert captured["payload"]["filename"] == "note.txt"
        assert captured["payload"]["mimeType"] == "text/plain"
        assert captured["payload"]["status"] == "ready"
    finally:
        service.close()


def test_upload_rejects_header_body_idempotency_drift(tmp_path) -> None:
    service = MediaWebTaskService(
        _App(),
        root=tmp_path,
        start_worker=False,
        start_cleanup_worker=False,
    )
    handler = SimpleNamespace(
        media_web_tasks=service,
        _send_json=lambda *_args, **_kwargs: pytest.fail("unexpected success"),
        _send_api_error=lambda *_args, **_kwargs: pytest.fail("unexpected API error"),
    )
    context = SimpleNamespace(
        principal=SimpleNamespace(tenant_id=str(uuid.uuid4())),
        idempotency=SimpleNamespace(key="header-key"),
    )
    body = {
        "schemaVersion": "3",
        "filename": "note.txt",
        "contentBase64": base64.b64encode(b"hello").decode(),
        "idempotencyKey": "body-key",
    }
    try:
        with pytest.raises(http_api.RequestContextError):
            http_api.OpenClawHttpHandler._execute_media_upload(handler, context, body)
    finally:
        service.close()


def test_media_task_compatibility_has_no_unrouted_legacy_handlers() -> None:
    for handler_name in (
        "_handle_media_task_create",
        "_handle_media_task_list",
        "_handle_media_task_get",
        "_handle_media_task_cancel",
        "_handle_media_task_confirm",
        "_handle_media_upload",
    ):
        assert not hasattr(http_api.OpenClawHttpHandler, handler_name)


def test_creator_task_events_exclude_audited_execution_jargon() -> None:
    from openclaw_app.services import media_task_repository, media_task_runner, media_web_tasks_core

    public_event_sources = "\n".join(
        (
            inspect.getsource(media_web_tasks_core),
            inspect.getsource(media_task_repository),
            inspect.getsource(media_task_runner),
        )
    )
    for wording in (
        "canonical handler 验证失败",
        "已进入 canonical Media 执行器",
        "伪装回滚",
        "幂等修复",
        "跨进程单 worker 队列",
        "独立 runner 已领取任务",
        "独立执行器已开始处理任务",
    ):
        assert wording not in public_event_sources
