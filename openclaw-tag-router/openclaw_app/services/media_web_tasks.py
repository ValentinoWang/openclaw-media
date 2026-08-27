"""Canonical Media Web task facade.

This module keeps the audited task implementation in ``media_web_tasks_core``
and owns compatibility at the current HTTP/composition boundary.  It is not a
legacy copy: there is one implementation module and one small adapter surface.
"""

from __future__ import annotations

from typing import Any, Mapping

from . import media_web_tasks_core as _core

# Preserve the public surface used throughout the router without maintaining a
# second implementation.
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


_ERROR_STATUS_BY_CODE = {
    "invalid_request": 400,
    "invalid_tenant": 400,
    "capability_not_found": 404,
    "task_not_found": 404,
    "upload_not_found": 404,
    "payload_too_large": 413,
    "catalog_conflict": 409,
    "task_conflict": 409,
    "idempotency_conflict": 409,
    "confirmation_required": 409,
    "confirmation_expired": 409,
    "invalid_task_state": 409,
    "model_settlement_unknown": 503,
    "model_transport_unavailable": 503,
    "service_unavailable": 503,
}


def _error_status(error: _core.MediaWebTaskError) -> int:
    return _ERROR_STATUS_BY_CODE.get(str(error.code), 400)


def _error_details(error: _core.MediaWebTaskError) -> Mapping[str, Any]:
    issues = getattr(error, "issues", None)
    return {"issues": list(issues)} if isinstance(issues, list) and issues else {}


# The HTTP adapter historically read attributes that the domain error never
# exposed.  Properties keep one error type and one source of truth.
_core.MediaWebTaskError.status = property(_error_status)  # type: ignore[attr-defined]
_core.MediaWebTaskError.details = property(_error_details)  # type: ignore[attr-defined]
MediaWebTaskError = _core.MediaWebTaskError


def _install_upload_handler() -> None:
    """Replace the retired upload stub after the HTTP module is fully loaded."""

    from ..adapters import http_api as _http_api

    if getattr(_http_api.OpenClawHttpHandler, "_openclaw_upload_v3_installed", False):
        return

    def _execute_media_upload(self: Any, context: Any, body: Mapping[str, Any]) -> None:
        service = self.media_web_tasks
        if service is None:
            self._send_api_error(
                _http_api.HTTPStatus.SERVICE_UNAVAILABLE,
                "service_unavailable",
                "上传服务暂时不可用。",
            )
            return
        expected = {"schemaVersion", "filename", "contentBase64", "idempotencyKey"}
        optional = {"mimeType"}
        if not isinstance(body, Mapping) or not expected.issubset(body) or set(body) - expected - optional:
            raise _http_api.RequestContextError("上传请求不符合结构化契约。")
        if body.get("schemaVersion") != "3":
            raise _http_api.RequestContextError("上传协议版本无效。")
        if context.idempotency is None:
            raise _http_api.RequestContextError("上传请求缺少幂等键。")
        if str(body.get("idempotencyKey") or "") != context.idempotency.key:
            raise _http_api.RequestContextError("body and header idempotency keys differ")
        request = {
            "filename": str(body.get("filename") or ""),
            "mimeType": str(body.get("mimeType") or ""),
            "contentBase64": body.get("contentBase64"),
        }
        projection, created = service.create_upload(
            request,
            tenant_id=str(context.principal.tenant_id),
        )
        self._send_json(
            _http_api.HTTPStatus.CREATED if created else _http_api.HTTPStatus.OK,
            projection,
        )

    _http_api.OpenClawHttpHandler._execute_media_upload = _execute_media_upload
    _http_api.OpenClawHttpHandler._openclaw_upload_v3_installed = True


class MediaWebTaskService(_core.MediaWebTaskService):
    """Current composition adapter for the durable Media Web task engine."""

    def __init__(
        self,
        app: Any,
        *,
        repository: Any | None = None,
        content_flow_client: Any | None = None,
        **kwargs: Any,
    ) -> None:
        _install_upload_handler()
        self.repository = repository
        self.content_flow_client = content_flow_client
        super().__init__(app, **kwargs)


__all__ = sorted(
    {
        *(name for name in dir(_core) if not name.startswith("_")),
        "MediaWebTaskError",
        "MediaWebTaskService",
    }
)
