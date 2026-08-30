"""Authenticated HTTP transport for the isolated current-main Stage-2 service."""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..account import AccountAuthService, AccountError, AccountSession
from ..services.stage2_gateway import Stage2GatewayError
from ..services.stage2_main_composition import Stage2ContractIdentity
from ..services.stage2_runtime import Stage2RuntimeError, runtime_status
from ..services.stage2_server_context import stage2_request_context


SESSION_COOKIE_NAME = "openclaw_session"
_IDEMPOTENCY_RE = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_STAGE2_ROUTES = {
    "/stage2/personal": "personal",
    "/stage2/organization": "organization",
}


class Stage2HttpError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class Stage2HttpAuthority:
    public_origin: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.public_origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("public_origin must be an absolute HTTP origin")

    @property
    def origin_tuple(self) -> tuple[str, str, int]:
        parsed = urlsplit(self.public_origin)
        return (
            parsed.scheme,
            str(parsed.hostname).lower(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    def matches(self, value: str) -> bool:
        try:
            parsed = urlsplit(value)
            observed = (
                parsed.scheme,
                str(parsed.hostname).lower() if parsed.hostname else "",
                parsed.port or (443 if parsed.scheme == "https" else 80),
            )
        except ValueError:
            return False
        expected = self.origin_tuple
        return all(
            hmac.compare_digest(str(left), str(right))
            for left, right in zip(observed, expected)
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedStage2Request:
    token: str
    session: AccountSession
    credential_kind: str


def _authorization_values(headers: Any) -> list[str]:
    getter = getattr(headers, "get_all", None)
    if callable(getter):
        return [str(item) for item in (getter("Authorization", failobj=[]) or [])]
    value = headers.get("Authorization", "")
    return [str(value)] if value else []


def _cookie_token(headers: Any) -> str | None:
    raw = str(headers.get("Cookie", "") or "")
    if not raw:
        return None
    parsed = SimpleCookie()
    try:
        parsed.load(raw)
    except CookieError as exc:
        raise Stage2HttpError(
            "authentication_invalid", "session cookie is invalid", status=401
        ) from exc
    morsel = parsed.get(SESSION_COOKIE_NAME)
    return None if morsel is None else str(morsel.value)


def extract_stage2_credential(headers: Any) -> tuple[str, str]:
    authorizations = _authorization_values(headers)
    if len(authorizations) > 1:
        raise Stage2HttpError(
            "authentication_invalid",
            "multiple Authorization headers are not allowed",
            status=401,
        )
    bearer: str | None = None
    if authorizations:
        scheme, separator, value = authorizations[0].partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not value.strip():
            raise Stage2HttpError(
                "authentication_invalid",
                "Authorization must contain one Bearer session",
                status=401,
            )
        bearer = value.strip()
    cookie = _cookie_token(headers)
    if bearer and cookie:
        raise Stage2HttpError(
            "authentication_ambiguous",
            "Bearer and Cookie credentials cannot be combined",
            status=401,
        )
    if bearer:
        return bearer, "bearer"
    if cookie:
        return cookie, "cookie"
    raise Stage2HttpError(
        "authentication_required", "an authenticated session is required", status=401
    )


def authenticate_stage2_request(
    headers: Any,
    *,
    account_auth: AccountAuthService,
    authority: Stage2HttpAuthority,
) -> AuthenticatedStage2Request:
    token, kind = extract_stage2_credential(headers)
    try:
        session = account_auth.resolve_session(token)
    except AccountError as exc:
        raise Stage2HttpError(exc.code, exc.detail, status=exc.status) from exc
    if session is None:
        raise Stage2HttpError(
            "authentication_required", "the session is invalid or expired", status=401
        )
    if kind == "cookie":
        origin = str(headers.get("Origin", "") or "")
        csrf = str(headers.get("X-OpenClaw-CSRF", "") or "")
        if not authority.matches(origin) or not account_auth.verify_csrf(token, csrf):
            raise Stage2HttpError(
                "csrf_rejected",
                "same-origin CSRF verification is required",
                status=403,
            )
    return AuthenticatedStage2Request(token=token, session=session, credential_kind=kind)


def normalize_stage2_operation(
    payload: Mapping[str, Any], headers: Any
) -> dict[str, Any]:
    key = str(headers.get("Idempotency-Key", "") or "").strip()
    if _IDEMPOTENCY_RE.fullmatch(key) is None:
        raise Stage2HttpError(
            "idempotency_key_required",
            "Idempotency-Key must be 8-128 ASCII letters, digits, '_' or '-'",
            status=400,
        )
    aliases = (
        "operation_id",
        "operationId",
        "idempotency_key",
        "idempotencyKey",
    )
    supplied = [str(payload[name]) for name in aliases if name in payload]
    if any(value != key for value in supplied):
        raise Stage2HttpError(
            "idempotency_conflict",
            "body operation identity does not match Idempotency-Key",
            status=409,
        )
    normalized = {name: value for name, value in payload.items() if name not in aliases}
    normalized["operation_id"] = key
    normalized["idempotency_key"] = key
    return normalized


class Stage2HttpHandler(BaseHTTPRequestHandler):
    stage2_app: Any = None
    account_auth: AccountAuthService | None = None
    authority: Stage2HttpAuthority | None = None
    contract_identity: Stage2ContractIdentity | None = None
    maximum_body_bytes = 1024 * 1024

    def _send_json(self, status: int | HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        try:
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_error(self, error: Stage2HttpError) -> None:
        self._send_json(
            error.status,
            {"ok": False, "error": {"code": error.code, "message": error.message}},
        )

    def _path(self) -> str:
        return urlsplit(self.path).path

    def _read_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise Stage2HttpError(
                "invalid_request", "Content-Length is required", status=400
            )
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise Stage2HttpError(
                "invalid_request", "Content-Length is invalid", status=400
            ) from exc
        if length < 0 or length > self.maximum_body_bytes:
            raise Stage2HttpError(
                "payload_too_large", "request body exceeds the Stage-2 limit", status=413
            )
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Stage2HttpError(
                "invalid_request", "request body is not valid JSON", status=400
            ) from exc
        if not isinstance(value, dict):
            raise Stage2HttpError(
                "invalid_request", "JSON request body must be an object", status=400
            )
        return value

    def do_GET(self) -> None:
        path = self._path()
        if path in {"/healthz", "/stage2/healthz"}:
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "openclaw-stage2",
                    "authenticatedProduction": True,
                },
            )
            return
        if path in {"/readyz", "/stage2/readyz"}:
            ready = all(
                item is not None
                for item in (
                    self.stage2_app,
                    self.account_auth,
                    self.authority,
                    self.contract_identity,
                )
            )
            identity = self.contract_identity
            self._send_json(
                HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "ok": ready,
                    "service": "openclaw-stage2",
                    "authenticatedProduction": True,
                    "contractDigest": None if identity is None else identity.digest,
                    "contractStatus": None if identity is None else identity.status,
                    "runtimeIntegration": False
                    if identity is None
                    else identity.runtime_integration,
                    "acceptanceMode": False
                    if identity is None
                    else identity.acceptance_mode,
                    "secretsEmitted": False,
                },
            )
            return
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"ok": False, "error": {"code": "not_found", "message": "route not found"}},
        )

    def do_POST(self) -> None:
        path = self._path()
        mode = _STAGE2_ROUTES.get(path)
        if mode is None:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": {"code": "not_found", "message": "route not found"}},
            )
            return
        try:
            if self.stage2_app is None or self.account_auth is None or self.authority is None:
                raise Stage2HttpError(
                    "stage2_unavailable", "Stage-2 is not configured", status=503
                )
            authenticated = authenticate_stage2_request(
                self.headers,
                account_auth=self.account_auth,
                authority=self.authority,
            )
            payload = normalize_stage2_operation(self._read_body(), self.headers)
            with stage2_request_context(
                {
                    "headers": {
                        "Authorization": f"Bearer {authenticated.token}"
                    },
                    "cookies": {},
                }
            ):
                receipt = self.stage2_app.process_stage2(mode, payload)
            self._send_json(HTTPStatus.OK, {"ok": True, "receipt": receipt})
        except Stage2HttpError as exc:
            self._send_error(exc)
        except Stage2GatewayError as exc:
            self._send_error(
                Stage2HttpError(exc.code, exc.message, status=int(exc.status))
            )
        except Stage2RuntimeError as exc:
            status = runtime_status(exc.code)
            self._send_error(Stage2HttpError(exc.code, exc.message, status=int(status)))
        except AccountError as exc:
            self._send_error(Stage2HttpError(exc.code, exc.detail, status=exc.status))
        except Exception:
            self._send_error(
                Stage2HttpError(
                    "internal_error", "Stage-2 request failed", status=500
                )
            )

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def make_stage2_http_server(
    host: str,
    port: int,
    *,
    stage2_app: Any,
    account_auth: AccountAuthService,
    authority: Stage2HttpAuthority,
    contract_identity: Stage2ContractIdentity,
) -> ThreadingHTTPServer:
    if stage2_app is None or not callable(getattr(stage2_app, "process_stage2", None)):
        raise ValueError("stage2_app must expose process_stage2")
    if not isinstance(account_auth, AccountAuthService):
        raise TypeError("account_auth must be AccountAuthService")
    if not isinstance(authority, Stage2HttpAuthority):
        raise TypeError("authority must be Stage2HttpAuthority")
    if not isinstance(contract_identity, Stage2ContractIdentity):
        raise TypeError("contract_identity must be Stage2ContractIdentity")
    handler = type(
        "BoundStage2HttpHandler",
        (Stage2HttpHandler,),
        {
            "stage2_app": stage2_app,
            "account_auth": account_auth,
            "authority": authority,
            "contract_identity": contract_identity,
        },
    )
    return ThreadingHTTPServer((host, port), handler)


__all__ = [
    "AuthenticatedStage2Request",
    "Stage2HttpAuthority",
    "Stage2HttpError",
    "Stage2HttpHandler",
    "authenticate_stage2_request",
    "extract_stage2_credential",
    "make_stage2_http_server",
    "normalize_stage2_operation",
]
