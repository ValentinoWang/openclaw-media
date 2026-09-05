from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal
from uuid import UUID, uuid4

import bcrypt

from .csrf import CSRF_DOMAIN, derive_csrf_token
from .database import AccountDatabase
from .errors import AccountAuthError, AccountContractError
from .password_policy import validate_password
from .repository import AccountAuthRepository, AccountCredential, AccountSessionRow
from .username import canonicalize_username


@dataclass(frozen=True)
class AccountSession:
    session_id: UUID
    user_id: UUID
    tenant_id: UUID
    username: str
    email: str | None
    role: str
    expires_at: datetime
    is_maintainer: bool = False


@dataclass(frozen=True)
class AccountLogin:
    token: str
    csrf_token: str
    session: AccountSession


@dataclass(frozen=True)
class AccountSessionInspection:
    session: AccountSession
    state: Literal["active", "expired"]


class AccountAuthService:
    def __init__(
        self,
        database: AccountDatabase,
        *,
        csrf_secret: bytes,
        session_ttl_seconds: int = 28 * 24 * 60 * 60,
        repository: AccountAuthRepository | None = None,
        now: Callable[[], datetime] | None = None,
        bcrypt_rounds: int = 12,
    ) -> None:
        if len(csrf_secret) < 32:
            raise ValueError("account session secret must be at least 32 bytes")
        if not 60 <= session_ttl_seconds <= 28 * 24 * 60 * 60:
            raise ValueError("account session ttl must be between 60 seconds and twenty-eight days")
        if not 12 <= bcrypt_rounds <= 16:
            raise ValueError("bcrypt rounds must be between 12 and 16")
        self._database = database
        self._repository = repository or AccountAuthRepository()
        self._csrf_secret = csrf_secret
        self._session_ttl_seconds = session_ttl_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._bcrypt_rounds = bcrypt_rounds
        self._dummy_hash = bcrypt.hashpw(b"openclaw-invalid-credential", bcrypt.gensalt(rounds=bcrypt_rounds))

    @staticmethod
    def _token_hash(token: str) -> bytes:
        return hashlib.sha256(token.encode("ascii")).digest()

    def csrf_token(self, token: str) -> str:
        return derive_csrf_token(self._csrf_secret, token, domain=CSRF_DOMAIN)

    def verify_csrf(self, token: str, supplied: str) -> bool:
        if not supplied:
            return False
        try:
            expected = self.csrf_token(token)
        except (UnicodeEncodeError, ValueError):
            return False
        return hmac.compare_digest(expected, supplied)

    @staticmethod
    def _normalize_identifier(identifier: str) -> str:
        stripped = identifier.strip()
        value = stripped.lower() if "@" in stripped else canonicalize_username(stripped)
        if not 3 <= len(value) <= 254 or any(character.isspace() for character in value):
            raise AccountAuthError("invalid_credentials", "用户名或密码不正确。", status=401)
        return value

    @staticmethod
    def _validate_password(password: str) -> None:
        validate_password(password)

    def _verify_password(self, password: str, credential: AccountCredential | None) -> bool:
        candidate = credential.password_hash.encode("ascii") if credential is not None else self._dummy_hash
        try:
            return bool(bcrypt.checkpw(password.encode("utf-8"), candidate))
        except (ValueError, UnicodeEncodeError):
            return False

    def _session_from_row(self, row: AccountSessionRow) -> AccountSession:
        return AccountSession(
            session_id=row.session_id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            username=row.username,
            email=row.email,
            role=row.role,
            expires_at=row.expires_at,
            is_maintainer=row.is_maintainer,
        )

    def inspect_session(self, token: str | None) -> AccountSessionInspection | None:
        """Read a session for entry-state without changing persisted auth state."""
        if not token or not 20 <= len(token) <= 256:
            return None
        try:
            token_hash = self._token_hash(token)
        except (UnicodeEncodeError, ValueError):
            return None
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT s.id, u.id, t.id, u.username, u.email, u.role, u.status, t.status,
                           s.status, s.csrf_token_hash, s.expires_at, u.is_maintainer
                    FROM openclaw_account.sessions AS s
                    JOIN openclaw_account.users AS u ON u.id = s.user_id
                    JOIN openclaw_account.tenants AS t ON t.id = s.tenant_id
                    JOIN openclaw_account.tenant_members AS m
                      ON m.tenant_id = s.tenant_id AND m.user_id = s.user_id AND m.status = 'active'
                    WHERE s.session_token_hash = %s
                    """,
                    (token_hash,),
                ).fetchone()
                if row is None:
                    return None
                session_row = AccountSessionRow(*row)
                session = self._session_from_row(session_row)
                session_status = str(session_row.session_status).lower()
                if session_status == "expired" or (session_status == "active" and session.expires_at <= self._now()):
                    return AccountSessionInspection(session, "expired")
                if (
                    session_status != "active"
                    or str(session_row.user_status).lower() != "active"
                    or str(session_row.tenant_status).lower() != "active"
                ):
                    return None
                expected_csrf_hash = self._token_hash(self.csrf_token(token))
                if not hmac.compare_digest(session_row.csrf_token_hash, expected_csrf_hash):
                    return None
                return AccountSessionInspection(session, "active")
        except AccountContractError:
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def issue_session_for_account(
        self,
        connection: Any,
        *,
        user_id: UUID,
        tenant_id: UUID,
        username: str,
        email: str | None,
        role: str,
        is_maintainer: bool = False,
    ) -> AccountLogin:
        if role not in {"user", "admin"}:
            raise AccountContractError("account_contract_invalid", "account role is invalid")
        if is_maintainer and role != "admin":
            raise AccountContractError("account_contract_invalid", "maintainer authority requires admin role")
        token = secrets.token_urlsafe(32)
        csrf_token = self.csrf_token(token)
        expires_at = self._now() + timedelta(seconds=self._session_ttl_seconds)
        session_id = uuid4()
        self._repository.create_session(
            connection,
            session_id=session_id,
            session_token_hash=self._token_hash(token),
            csrf_token_hash=self._token_hash(csrf_token),
            user_id=user_id,
            tenant_id=tenant_id,
            expires_at=expires_at,
        )
        session = AccountSession(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            username=username,
            email=email,
            role=role,
            expires_at=expires_at,
            is_maintainer=is_maintainer,
        )
        return AccountLogin(token=token, csrf_token=csrf_token, session=session)

    def login(self, identifier: str, password: str, *, previous_token: str | None = None) -> AccountLogin:
        normalized = self._normalize_identifier(identifier)
        if not isinstance(password, str) or len(password) > 1024:
            raise AccountAuthError("invalid_credentials", "用户名或密码不正确。", status=401)
        try:
            with self._database.connect() as connection:
                credential = self._repository.credential_for_login(connection, normalized)
                password_valid = self._verify_password(password, credential)
                if (
                    credential is None
                    or not password_valid
                    or credential.user_status != "active"
                    or credential.tenant_status != "active"
                ):
                    raise AccountAuthError("invalid_credentials", "用户名或密码不正确。", status=401)
                if previous_token:
                    self._repository.revoke_by_token_hash(connection, self._token_hash(previous_token))
                login = self.issue_session_for_account(
                    connection,
                    user_id=credential.user_id,
                    tenant_id=credential.tenant_id,
                    username=credential.username,
                    email=credential.email,
                    role=credential.role,
                    is_maintainer=credential.is_maintainer,
                )
            return login
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def login_verified_feishu_identity(
        self,
        *,
        tenant_key: str,
        open_id: str | None,
        union_id: str | None,
        previous_token: str | None = None,
        workspace_intent: Literal["personal_web", "organization_lark"] = "personal_web",
    ) -> AccountLogin:
        if not isinstance(workspace_intent, str) or workspace_intent not in {"personal_web", "organization_lark"}:
            raise AccountAuthError("feishu_login_invalid_intent", "飞书登录工作区类型无效。", status=400)
        normalized_tenant_key = self._normalize_feishu_identity_value(tenant_key, required=True)
        normalized_open_id = self._normalize_feishu_identity_value(open_id, required=False)
        normalized_union_id = self._normalize_feishu_identity_value(union_id, required=False)
        if normalized_open_id is None and normalized_union_id is None:
            raise AccountAuthError(
                "feishu_identity_unavailable",
                "飞书未返回可验证的用户身份，请联系管理员检查应用权限。",
                status=403,
            )
        try:
            with self._database.connect() as connection:
                credential = self._repository.credential_for_feishu_identity(
                    connection,
                    tenant_key=normalized_tenant_key or "",
                    open_id=normalized_open_id,
                    union_id=normalized_union_id,
                    workspace_intent=workspace_intent,
                )
                if credential is None:
                    if workspace_intent == "organization_lark":
                        raise AccountAuthError(
                            "feishu_organization_workspace_unavailable",
                            "当前飞书身份没有可用的已绑定组织工作区，请联系组织管理员完成成员同步和组织绑定。",
                            status=403,
                        )
                    raise AccountAuthError(
                        "feishu_account_unlinked",
                        "该飞书账号尚未绑定 MediaClaw 账户。",
                        status=403,
                    )
                if credential.user_status != "active" or credential.tenant_status != "active":
                    raise AccountAuthError(
                        "feishu_account_unlinked",
                        "该飞书账号尚未绑定 MediaClaw 账户。",
                        status=403,
                    )
                if previous_token:
                    self._repository.revoke_by_token_hash(connection, self._token_hash(previous_token))
                login = self.issue_session_for_account(
                    connection,
                    user_id=credential.user_id,
                    tenant_id=credential.tenant_id,
                    username=credential.username,
                    email=credential.email,
                    role=credential.role,
                    is_maintainer=credential.is_maintainer,
                )
            return login
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    @staticmethod
    def _normalize_feishu_identity_value(value: str | None, *, required: bool) -> str | None:
        if value is None:
            if required:
                raise AccountAuthError(
                    "feishu_identity_unavailable",
                    "飞书未返回可验证的租户身份，请联系管理员检查应用权限。",
                    status=403,
                )
            return None
        if not isinstance(value, str):
            raise AccountAuthError("feishu_identity_invalid", "飞书身份格式无效。", status=400)
        normalized = value.strip()
        if not 1 <= len(normalized) <= 512 or any(ord(character) < 32 for character in normalized):
            raise AccountAuthError("feishu_identity_invalid", "飞书身份格式无效。", status=400)
        return normalized

    def resolve_session(self, token: str | None) -> AccountSession | None:
        if not token or not 20 <= len(token) <= 256:
            return None
        try:
            token_hash = self._token_hash(token)
        except (UnicodeEncodeError, ValueError):
            return None
        try:
            with self._database.connect() as connection:
                row = self._repository.session_for_update(connection, token_hash)
                if row is None or row.session_status != "active":
                    return None
                now = self._now()
                if row.expires_at <= now:
                    self._repository.mark_expired(connection, row.session_id)
                    return None
                if row.user_status != "active" or row.tenant_status != "active":
                    self._repository.revoke_by_token_hash(connection, token_hash)
                    return None
                expected_csrf_hash = self._token_hash(self.csrf_token(token))
                if not hmac.compare_digest(row.csrf_token_hash, expected_csrf_hash):
                    self._repository.revoke_by_token_hash(connection, token_hash)
                    raise AccountContractError("account_contract_invalid", "session CSRF binding is invalid")
                self._repository.mark_seen(connection, row.session_id)
                return self._session_from_row(row)
        except AccountContractError:
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        try:
            with self._database.connect() as connection:
                self._repository.revoke_by_token_hash(connection, self._token_hash(token))
        except AccountContractError:
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def change_password(self, token: str, old_password: str, new_password: str) -> None:
        self._validate_password(new_password)
        try:
            with self._database.connect() as connection:
                row = self._repository.session_for_update(connection, self._token_hash(token))
                if row is None or row.session_status != "active" or row.expires_at <= self._now():
                    raise AccountAuthError("authentication_required", "登录会话已失效。", status=401)
                credential = self._repository.credential_for_login(connection, row.username)
                if credential is None or not self._verify_password(old_password, credential):
                    raise AccountAuthError("invalid_credentials", "当前密码不正确。", status=401)
                password_hash = bcrypt.hashpw(
                    new_password.encode("utf-8"), bcrypt.gensalt(rounds=self._bcrypt_rounds)
                ).decode("ascii")
                self._repository.update_password(connection, row.user_id, password_hash)
                self._repository.revoke_user_sessions(connection, row.user_id)
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def issue_password_reset(self, user_id: UUID, *, ttl_seconds: int = 900) -> str:
        if not 60 <= ttl_seconds <= 3600:
            raise ValueError("password reset ttl must be between 60 and 3600 seconds")
        token = secrets.token_urlsafe(32)
        try:
            with self._database.connect() as connection:
                self._repository.create_password_reset(
                    connection,
                    reset_id=uuid4(),
                    user_id=user_id,
                    token_hash=self._token_hash(token),
                    expires_at=self._now() + timedelta(seconds=ttl_seconds),
                )
            return token
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def reset_password(self, token: str, new_password: str) -> None:
        self._validate_password(new_password)
        try:
            with self._database.connect() as connection:
                user_id = self._repository.consume_password_reset(connection, self._token_hash(token))
                if user_id is None:
                    raise AccountAuthError("invalid_request", "密码重置链接无效或已过期。", status=400)
                password_hash = bcrypt.hashpw(
                    new_password.encode("utf-8"), bcrypt.gensalt(rounds=self._bcrypt_rounds)
                ).decode("ascii")
                self._repository.update_password(connection, user_id, password_hash)
                self._repository.revoke_user_sessions(connection, user_id)
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def admin_revoke_user_sessions(self, actor_token: str, target_user_id: UUID, reason: str) -> int:
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise AccountAuthError("invalid_request", "请输入有效的操作原因。", status=400)
        try:
            with self._database.connect() as connection:
                actor = self._repository.session_for_update(connection, self._token_hash(actor_token))
                if (
                    actor is None
                    or actor.session_status != "active"
                    or actor.expires_at <= self._now()
                    or actor.user_status != "active"
                    or actor.tenant_status != "active"
                ):
                    raise AccountAuthError("authentication_required", "登录会话已失效。", status=401)
                if actor.role != "admin":
                    raise AccountAuthError("admin_required", "需要平台管理员权限。", status=403)
                revoked = self._repository.revoke_user_sessions(connection, target_user_id)
                self._repository.write_admin_audit(
                    connection,
                    audit_id=uuid4(),
                    actor_user_id=actor.user_id,
                    actor_session_id=actor.session_id,
                    action="user_sessions_revoke_all",
                    target_user_id=target_user_id,
                    reason=normalized_reason,
                    metadata=json.dumps({"revokedSessions": revoked}, separators=(",", ":")),
                )
                return revoked
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc
