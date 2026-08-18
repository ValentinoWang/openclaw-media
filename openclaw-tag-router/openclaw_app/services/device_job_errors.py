from __future__ import annotations

from http import HTTPStatus


_STATUS_BY_CODE = {
    "unauthenticated": HTTPStatus.UNAUTHORIZED,
    "invalid_device_credential": HTTPStatus.UNAUTHORIZED,
    "device_revoked": HTTPStatus.UNAUTHORIZED,
    "invalid_pair_code": HTTPStatus.BAD_REQUEST,
    "expired_pair_code": HTTPStatus.BAD_REQUEST,
    "platform_unsupported": HTTPStatus.BAD_REQUEST,
    "not_found": HTTPStatus.NOT_FOUND,
    "forbidden": HTTPStatus.FORBIDDEN,
    "device_unavailable": HTTPStatus.CONFLICT,
    "pipeline_unavailable": HTTPStatus.CONFLICT,
    "invalid_state": HTTPStatus.CONFLICT,
    "result_rejected": HTTPStatus.CONFLICT,
    "idempotency_conflict": HTTPStatus.CONFLICT,
    "invalid_request": HTTPStatus.BAD_REQUEST,
}


class DeviceJobError(RuntimeError):
    def __init__(self, code: str, detail: str, *, status: HTTPStatus | int | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = int(status or _STATUS_BY_CODE.get(code, HTTPStatus.BAD_REQUEST))
