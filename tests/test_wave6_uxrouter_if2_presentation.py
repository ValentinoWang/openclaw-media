from http import HTTPStatus

from openclaw_app.adapters.http_api import if2_public_error
from openclaw_app.adapters.audit_reason_header import AuditReasonHeaderError
from openclaw_app.adapters.media_business_context import (
    AdminPermissionRequiredError,
    CsrfAssessment,
    CsrfRejectedError,
    RequestAuthenticationError,
    RequestAuthorizationError,
    RequestContextError,
)


def test_if2_errors_expose_only_creator_facing_chinese_messages() -> None:
    cases = (
        (
            RequestAuthenticationError("authenticated IF2 session is required"),
            (HTTPStatus.UNAUTHORIZED, "authentication_required", "请先登录后再继续操作。"),
        ),
        (
            CsrfRejectedError("required CSRF assessment did not pass"),
            (HTTPStatus.FORBIDDEN, "csrf_rejected", "安全校验未通过，请刷新页面后重试。"),
        ),
        (
            AdminPermissionRequiredError("maintainer route requires explicit maintainer authority"),
            (HTTPStatus.FORBIDDEN, "admin_required", "当前账号没有此操作权限。"),
        ),
        (
            RequestAuthorizationError("ordinary route requires an ordinary-user principal"),
            (HTTPStatus.FORBIDDEN, "forbidden", "当前账号没有此操作权限。"),
        ),
        (
            RequestContextError("forwarded client address chain is ambiguous"),
            (HTTPStatus.BAD_REQUEST, "invalid_request", "请求信息不完整或格式不正确，请检查后重试。"),
        ),
        (
            AuditReasonHeaderError("audit reason header uses an invalid wire format"),
            (HTTPStatus.BAD_REQUEST, "invalid_request", "请求信息不完整或格式不正确，请检查后重试。"),
        ),
    )

    for error, expected in cases:
        assert if2_public_error(error) == expected
        assert str(error) not in expected[2]


def test_failed_csrf_assessment_uses_the_structured_public_error_type() -> None:
    try:
        CsrfAssessment(
            required=True,
            origin=None,
            same_origin=False,
            token_valid=False,
            response_token="csrf-response-token",
        )
    except CsrfRejectedError as error:
        assert if2_public_error(error) == (
            HTTPStatus.FORBIDDEN,
            "csrf_rejected",
            "安全校验未通过，请刷新页面后重试。",
        )
    else:
        raise AssertionError("invalid CSRF assessment must be rejected")
