from __future__ import annotations

import base64
import json
import uuid
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from openclaw_app.adapters import http_api
from openclaw_app.services.media_web_tasks import MediaWebTaskError, MediaWebTaskService


class _App:
    router = SimpleNamespace()


def test_current_composition_accepts_repository_and_content_flow_client(tmp_path) -> None:
    service = MediaWebTaskService(
        _App(),
        root=tmp_path,
        repository=object(),
        content_flow_client=object(),
        start_worker=False,
        start_cleanup_worker=False,
    )
    try:
        assert service.repository is not None
        assert service.content_flow_client is not None
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
