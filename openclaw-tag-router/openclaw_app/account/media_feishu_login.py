from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .errors import AccountAuthError


AUTHORIZE_ENDPOINT = "https://open.feishu.cn/open-apis/authen/v1/authorize"
TOKEN_ENDPOINT = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
USER_INFO_ENDPOINT = "https://open.feishu.cn/open-apis/authen/v1/user_info"
MEDIA_LOGIN_SCOPE = "contact:user.email:readonly"
MEDIA_STATE_PREFIX = "m_"
MEDIA_CALLBACK_PATH = "/openclaw/media/oauth/callback"
WorkspaceIntent = Literal["personal_web", "organization_lark"]
_WORKSPACE_INTENTS = frozenset({"personal_web", "organization_lark"})


@dataclass(frozen=True)
class MediaFeishuLoginStart:
    authorization_url: str
    expires_at: str
    maximum_age: int


@dataclass(frozen=True)
class MediaFeishuIdentity:
    tenant_key: str
    open_id: str | None
    union_id: str | None
    user_id: str | None = None
    email: str | None = None
    workspace_intent: WorkspaceIntent = "personal_web"


@dataclass
class _LoginAttempt:
    state: str
    code_verifier: str
    expires_at: float
    workspace_intent: WorkspaceIntent


def load_media_feishu_identity(path: str | Path) -> tuple[str, str]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Media Feishu application configuration is unavailable") from exc
    media = (((payload.get("channels") or {}).get("feishu") or {}).get("accounts") or {}).get("media") or {}
    app_id = str(media.get("appId") or "").strip()
    app_secret = str(media.get("appSecret") or "").strip()
    if not app_id.startswith("cli_") or len(app_id) < 12 or not app_secret:
        raise RuntimeError("Media Feishu application identity is incomplete")
    return app_id, app_secret


class MediaFeishuLoginService:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        redirect_uri: str,
        *,
        timeout_seconds: int = 8,
        maximum_age: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        parsed_redirect = urlsplit(redirect_uri)
        if (
            parsed_redirect.scheme not in {"http", "https"}
            or not parsed_redirect.hostname
            or parsed_redirect.path != MEDIA_CALLBACK_PATH
            or parsed_redirect.query
            or parsed_redirect.fragment
            or parsed_redirect.username
            or parsed_redirect.password
        ):
            raise ValueError("Media Feishu redirect URI must use the canonical Media callback path")
        if not app_id.startswith("cli_") or len(app_id) < 12 or not app_secret:
            raise ValueError("Media Feishu application identity is invalid")
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("Media Feishu OAuth timeout must be between 1 and 30 seconds")
        if not 60 <= maximum_age <= 300:
            raise ValueError("Media Feishu login lifetime must be between 60 and 300 seconds")
        self._app_id = app_id
        self._app_secret = app_secret
        self._redirect_uri = redirect_uri
        self._timeout_seconds = timeout_seconds
        self._maximum_age = maximum_age
        self._clock = clock
        self._lock = threading.Lock()
        self._attempts: dict[str, _LoginAttempt] = {}

    @classmethod
    def from_openclaw_config(
        cls,
        path: str | Path,
        *,
        redirect_uri: str,
        timeout_seconds: int = 8,
    ) -> MediaFeishuLoginService:
        app_id, app_secret = load_media_feishu_identity(path)
        return cls(app_id, app_secret, redirect_uri, timeout_seconds=timeout_seconds)

    @property
    def app_id(self) -> str:
        return self._app_id

    @property
    def redirect_uri(self) -> str:
        return self._redirect_uri

    def start(self, *, workspace_intent: WorkspaceIntent = "personal_web") -> MediaFeishuLoginStart:
        if not isinstance(workspace_intent, str) or workspace_intent not in _WORKSPACE_INTENTS:
            raise AccountAuthError("feishu_login_invalid_intent", "飞书登录工作区类型无效。", status=400)
        now = self._clock()
        state = MEDIA_STATE_PREFIX + secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        attempt = _LoginAttempt(
            state=state,
            code_verifier=code_verifier,
            expires_at=now + self._maximum_age,
            workspace_intent=workspace_intent,
        )
        with self._lock:
            self._cleanup(now)
            if len(self._attempts) >= 512:
                oldest = min(self._attempts.values(), key=lambda item: item.expires_at)
                self._remove(oldest)
            self._attempts[state] = attempt
        authorization_url = AUTHORIZE_ENDPOINT + "?" + urlencode(
            {
                "app_id": self._app_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": MEDIA_LOGIN_SCOPE,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return MediaFeishuLoginStart(
            authorization_url=authorization_url,
            expires_at=self._timestamp(attempt.expires_at),
            maximum_age=self._maximum_age,
        )

    def complete_callback(
        self,
        *,
        state: str,
        code: str | None,
        error: str | None = None,
    ) -> MediaFeishuIdentity:
        now = self._clock()
        with self._lock:
            self._cleanup(now)
            attempt = self._attempts.pop(state, None)
            if attempt is None or attempt.expires_at <= now:
                raise AccountAuthError(
                    "feishu_login_invalid_state",
                    "MediaClaw 登录请求已失效，请返回登录页重新发起登录。",
                    status=400,
                )
            if error or not code:
                raise AccountAuthError(
                    "feishu_authorization_rejected",
                    "未完成 MediaClaw 飞书授权，请返回登录页重试。",
                    status=400,
                )
            verifier = attempt.code_verifier
        identity = self._exchange_identity(code, verifier)
        if attempt.expires_at <= self._clock():
            raise AccountAuthError(
                "feishu_login_expired",
                "MediaClaw 登录请求已过期，请返回登录页重新发起登录。",
                status=400,
            )
        return replace(identity, workspace_intent=attempt.workspace_intent)

    def _exchange_identity(self, code: str, code_verifier: str) -> MediaFeishuIdentity:
        if not isinstance(code, str) or not 1 <= len(code) <= 2048:
            raise self._oauth_failure("token_exchange")
        token_payload = self._request_json(
            TOKEN_ENDPOINT,
            stage="token_exchange",
            method="POST",
            payload={
                "grant_type": "authorization_code",
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        token_data = self._success_data(token_payload, stage="token_exchange")
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            self._record_provider_failure("token_exchange", reason="missing_access_token")
            raise self._oauth_failure("token_exchange")
        user_payload = self._request_json(
            USER_INFO_ENDPOINT,
            stage="user_info",
            method="GET",
            bearer_token=access_token,
        )
        user_data = self._success_data(user_payload, stage="user_info")
        tenant_key = self._required_identity_value(user_data.get("tenant_key"), field="tenant_key")
        open_id = self._optional_identity_value(user_data.get("open_id"), field="open_id")
        union_id = self._optional_identity_value(user_data.get("union_id"), field="union_id")
        if open_id is None and union_id is None:
            raise AccountAuthError(
                "feishu_identity_unavailable",
                "飞书未返回可验证的用户身份，请联系管理员检查应用权限。",
                status=403,
            )
        email = self._optional_email(user_data.get("email") or user_data.get("enterprise_email"))
        return MediaFeishuIdentity(
            tenant_key=tenant_key,
            open_id=open_id,
            union_id=union_id,
            user_id=self._optional_identity_value(user_data.get("user_id"), field="user_id"),
            email=email,
        )

    def _request_json(
        self,
        url: str,
        *,
        stage: str,
        method: str,
        payload: Mapping[str, str] | None = None,
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else urlencode(dict(payload)).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read(512_000)
        except HTTPError as exc:
            provider_payload: Mapping[str, Any] | None = None
            try:
                decoded = json.loads(exc.read(64_000).decode("utf-8"))
                if isinstance(decoded, dict):
                    provider_payload = decoded
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass
            self._record_provider_failure(stage, http_status=exc.code, payload=provider_payload)
            raise self._oauth_failure(stage) from exc
        except (URLError, TimeoutError, OSError) as exc:
            self._record_provider_failure(stage, reason=type(exc).__name__)
            raise self._oauth_failure(stage) from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._record_provider_failure(stage, reason="invalid_json")
            raise self._oauth_failure(stage) from exc
        if not isinstance(result, dict):
            self._record_provider_failure(stage, reason="invalid_payload")
            raise self._oauth_failure(stage)
        return result

    @staticmethod
    def _success_data(payload: Mapping[str, Any], *, stage: str) -> Mapping[str, Any]:
        code = payload.get("code")
        if code not in {None, 0}:
            MediaFeishuLoginService._record_provider_failure(stage, payload=payload)
            raise MediaFeishuLoginService._oauth_failure(stage)
        data = payload.get("data")
        if data is None:
            return payload
        if not isinstance(data, dict):
            MediaFeishuLoginService._record_provider_failure(stage, reason="invalid_data")
            raise MediaFeishuLoginService._oauth_failure(stage)
        return data

    @staticmethod
    def _record_provider_failure(
        stage: str,
        *,
        http_status: int | None = None,
        payload: Mapping[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        diagnostic: dict[str, Any] = {"event": "media_feishu_oauth_failure", "stage": stage}
        if http_status is not None:
            diagnostic["http_status"] = http_status
        if reason:
            diagnostic["reason"] = reason
        for key in ("code", "error", "msg"):
            value = None if payload is None else payload.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                diagnostic[f"provider_{key}"] = value
            elif isinstance(value, str) and 0 < len(value) <= 160 and all(ord(char) >= 32 for char in value):
                diagnostic[f"provider_{key}"] = value
        print(json.dumps(diagnostic, ensure_ascii=True, sort_keys=True), file=sys.stderr, flush=True)

    @staticmethod
    def _oauth_failure(stage: str) -> AccountAuthError:
        if stage == "token_exchange":
            return AccountAuthError(
                "feishu_token_exchange_failed",
                "MediaClaw 未能完成飞书授权码换票，请返回登录页重新发起登录。",
                status=502,
            )
        return AccountAuthError(
            "feishu_user_info_failed",
            "MediaClaw 未能读取飞书用户身份，请返回登录页重新发起登录。",
            status=502,
        )

    @staticmethod
    def _required_identity_value(value: Any, *, field: str) -> str:
        normalized = MediaFeishuLoginService._optional_identity_value(value, field=field)
        if normalized is None:
            raise AccountAuthError(
                "feishu_identity_unavailable",
                "飞书未返回可验证的租户身份，请联系管理员检查应用权限。",
                status=403,
            )
        return normalized

    @staticmethod
    def _optional_identity_value(value: Any, *, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            MediaFeishuLoginService._record_provider_failure(
                "user_info", reason=f"invalid_{field}_type"
            )
            raise MediaFeishuLoginService._oauth_failure("user_info")
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 512 or any(ord(character) < 32 for character in normalized):
            MediaFeishuLoginService._record_provider_failure(
                "user_info", reason=f"invalid_{field}_value"
            )
            raise MediaFeishuLoginService._oauth_failure("user_info")
        return normalized

    @staticmethod
    def _optional_email(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            MediaFeishuLoginService._record_provider_failure("user_info", reason="invalid_email_type")
            raise MediaFeishuLoginService._oauth_failure("user_info")
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized.count("@") != 1 or any(character.isspace() for character in normalized):
            MediaFeishuLoginService._record_provider_failure("user_info", reason="invalid_email_value")
            raise MediaFeishuLoginService._oauth_failure("user_info")
        return normalized

    @staticmethod
    def _timestamp(value: float) -> str:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    def _cleanup(self, now: float) -> None:
        for attempt in tuple(self._attempts.values()):
            if attempt.expires_at + 60 <= now:
                self._remove(attempt)

    def _remove(self, attempt: _LoginAttempt) -> None:
        self._attempts.pop(attempt.state, None)
