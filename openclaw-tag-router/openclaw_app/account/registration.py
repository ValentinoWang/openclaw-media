from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

import bcrypt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .database import AccountDatabase
from .errors import AccountAuthError, AccountContractError
from .auth import AccountAuthService, AccountLogin
from .password_policy import validate_password
from .repository import AccountAuthRepository
from .registration_repository import AccountRegistrationRepository, AffiliateProfileRow
from .username import normalize_username


@dataclass(frozen=True)
class RegistrationResult:
    user_id: UUID
    tenant_id: UUID
    username: str
    inviter_user_id: UUID | None
    login: AccountLogin


@dataclass(frozen=True)
class AdmissionBatchIssue:
    batch_id: UUID
    codes: tuple[str, ...]


@dataclass(frozen=True)
class AffiliateProfile:
    user_id: UUID
    username: str
    invite_code: str
    signup_enabled: bool
    signup_quota: int
    signup_used: int
    signup_expires_at: datetime | None


@dataclass(frozen=True)
class Invitee:
    user_id: UUID
    username: str
    created_at: datetime


@dataclass(frozen=True)
class InviteePage:
    items: tuple[Invitee, ...]
    page: int
    page_size: int
    total: int


class AccountRegistrationService:
    def __init__(
        self,
        database: AccountDatabase,
        *,
        account_auth: AccountAuthService,
        code_secret: bytes,
        repository: AccountRegistrationRepository | None = None,
        now: Callable[[], datetime] | None = None,
        bcrypt_rounds: int = 12,
    ) -> None:
        if len(code_secret) < 32:
            raise ValueError("registration code secret must be at least 32 bytes")
        if not 12 <= bcrypt_rounds <= 16:
            raise ValueError("bcrypt rounds must be between 12 and 16")
        self._database = database
        self._account_auth = account_auth
        self._repository = repository or AccountRegistrationRepository()
        self._auth_repository = AccountAuthRepository()
        self._code_secret = code_secret
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._bcrypt_rounds = bcrypt_rounds

    @staticmethod
    def _normalize_username(username: str) -> str:
        return normalize_username(username)

    @staticmethod
    def _normalize_email(email: str | None) -> str | None:
        if email is None or not email.strip():
            return None
        value = email.strip().lower()
        if len(value) > 254 or value.count("@") != 1 or any(character.isspace() for character in value):
            raise AccountAuthError("invalid_request", "邮箱格式无效。", status=400)
        local, domain = value.split("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise AccountAuthError("invalid_request", "邮箱格式无效。", status=400)
        return value

    @staticmethod
    def _validate_password(password: str) -> None:
        validate_password(password)

    @staticmethod
    def _normalize_code(code: str | None) -> str | None:
        if code is None or not code.strip():
            return None
        value = code.strip()
        if len(value) > 128 or any(character.isspace() for character in value):
            raise AccountAuthError("invalid_request", "注册代码格式无效。", status=400)
        return value

    def _admission_hmac(self, code: str) -> bytes:
        return hmac.new(self._code_secret, b"openclaw-admission\0" + code.encode("utf-8"), hashlib.sha256).digest()

    def _admission_encryption_key(self) -> bytes:
        return hmac.new(
            self._code_secret,
            b"openclaw-admission-encryption\0",
            hashlib.sha256,
        ).digest()

    def _encrypt_admission_code(self, code: str, batch_id: UUID, code_id: UUID) -> bytes:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._admission_encryption_key()).encrypt(
            nonce,
            code.encode("utf-8"),
            batch_id.bytes + code_id.bytes,
        )
        return nonce + ciphertext

    def _decrypt_admission_code(self, ciphertext: bytes, batch_id: UUID, code_id: UUID) -> str:
        if len(ciphertext) < 29:
            raise AccountContractError("account_database_unavailable", "stored admission code ciphertext is invalid")
        try:
            plaintext = AESGCM(self._admission_encryption_key()).decrypt(
                ciphertext[:12],
                ciphertext[12:],
                batch_id.bytes + code_id.bytes,
            )
            code = plaintext.decode("utf-8")
        except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
            raise AccountContractError(
                "account_database_unavailable",
                "stored admission code ciphertext cannot be decrypted",
            ) from exc
        return code

    @staticmethod
    def _profile(row: AffiliateProfileRow) -> AffiliateProfile:
        return AffiliateProfile(
            user_id=row.user_id,
            username=row.username,
            invite_code=row.invite_code,
            signup_enabled=row.signup_enabled,
            signup_quota=row.signup_quota,
            signup_used=row.signup_used,
            signup_expires_at=row.signup_expires_at,
        )

    @staticmethod
    def _reason(reason: str) -> str:
        value = reason.strip()
        if not 1 <= len(value) <= 500:
            raise AccountAuthError("invalid_request", "请输入有效的操作原因。", status=400)
        return value

    @staticmethod
    def _page(page: int, page_size: int) -> tuple[int, int]:
        if page < 1 or not 1 <= page_size <= 100:
            raise AccountAuthError("invalid_request", "分页参数无效。", status=400)
        return page_size, (page - 1) * page_size

    def registration_mode(self) -> str:
        try:
            with self._database.connect() as connection:
                return self._repository.registration_mode(connection)
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def register(
        self,
        *,
        username: str,
        password: str,
        email: str | None,
        admission_code: str | None = None,
        affiliate_code: str | None = None,
        tenant_type: str = "personal",
        workspace_mode: str | None = None,
        body_authority: str | None = None,
        display_name: str | None = None,
        organization_name: str | None = None,
    ) -> RegistrationResult:
        normalized_username = self._normalize_username(username)
        normalized_email = self._normalize_email(email)
        self._validate_password(password)
        tenant_type = tenant_type.strip().lower()
        if tenant_type not in {"personal", "organization"}:
            raise AccountAuthError("invalid_request", "租户类型无效。", status=400)
        normalized_display_name = (display_name or username).strip()
        if not 1 <= len(normalized_display_name) <= 80:
            raise AccountAuthError("invalid_request", "显示名称长度无效。", status=400)
        normalized_organization_name = (organization_name or "").strip() or None
        if tenant_type == "organization" and not normalized_organization_name:
            raise AccountAuthError("invalid_request", "机构注册必须填写机构名称。", status=400)
        expected_workspace = "organization_lark" if tenant_type == "organization" else "personal_web"
        expected_authority = "lark" if tenant_type == "organization" else "internal"
        if workspace_mode not in {None, expected_workspace} or body_authority not in {None, expected_authority}:
            raise AccountAuthError("invalid_request", "租户工作模式与类型不匹配。", status=400)
        platform_code = self._normalize_code(admission_code)
        inviter_code = self._normalize_code(affiliate_code)
        if platform_code and inviter_code:
            raise AccountAuthError("multiple_admission_sources", "一次注册只能使用一种准入代码。", status=400)
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt(rounds=self._bcrypt_rounds)
        ).decode("ascii")
        try:
            with self._database.connect() as connection:
                mode = self._repository.registration_mode_for_registration(connection)
                if mode == "controlled" and not (platform_code or inviter_code):
                    raise AccountAuthError("admission_required", "当前注册需要有效的准入代码。", status=403)
                if mode == "open" and platform_code:
                    raise AccountAuthError("admission_not_allowed", "开放注册不接受平台准入码。", status=400)

                admission = None
                affiliate = None
                if platform_code:
                    admission = self._repository.admission_code_for_update(
                        connection, self._admission_hmac(platform_code)
                    )
                    if admission is None or admission.status != "active":
                        raise AccountAuthError("admission_unavailable", "平台注册准入码无效或已使用。", status=403)
                elif inviter_code:
                    affiliate = self._repository.affiliate_source_for_update(connection, inviter_code.upper())
                    if (
                        affiliate is None
                        or not affiliate.signup_enabled
                        or affiliate.user_status != "active"
                        or affiliate.signup_used >= affiliate.signup_quota
                        or (
                            affiliate.signup_expires_at is not None
                            and affiliate.signup_expires_at <= self._now()
                        )
                    ):
                        raise AccountAuthError("affiliate_unavailable", "用户裂变码无效、已过期或名额已用完。", status=403)

                user_id = uuid4()
                tenant_id = uuid4()
                self._repository.create_account(
                    connection,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    wallet_id=uuid4(),
                    username=normalized_username,
                    email=normalized_email,
                    password_hash=password_hash,
                    invite_code=secrets.token_hex(10).upper(),
                    display_name=normalized_display_name,
                    tenant_type=tenant_type,
                    workspace_mode=expected_workspace,
                    body_authority=expected_authority,
                    organization_name=normalized_organization_name,
                )
                inviter_user_id = None
                if admission is not None:
                    self._repository.consume_admission_code(connection, admission.code_id, user_id)
                if affiliate is not None:
                    inviter_user_id = affiliate.user_id
                    self._repository.create_affiliate_edge(
                        connection,
                        edge_id=uuid4(),
                        inviter_user_id=affiliate.user_id,
                        invitee_user_id=user_id,
                    )
                    self._repository.consume_affiliate_quota(connection, affiliate.user_id)
                login = self._account_auth.issue_session_for_account(
                    connection,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    username=normalized_username,
                    email=normalized_email,
                    role="user",
                )
                return RegistrationResult(user_id, tenant_id, normalized_username, inviter_user_id, login)
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            constraint = str(getattr(getattr(exc, "diag", None), "constraint_name", "") or "")
            if getattr(exc, "sqlstate", None) == "23505" and constraint in {
                "users_username_key",
                "users_email_unique_when_present",
            }:
                raise AccountAuthError("account_exists", "用户名或邮箱已被使用。", status=409) from exc
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def admin_set_registration_policy(
        self,
        *,
        actor_user_id: UUID,
        actor_session_id: UUID,
        mode: str,
        reason: str,
    ) -> str:
        if mode not in {"controlled", "open"}:
            raise AccountAuthError("invalid_request", "注册模式无效。", status=400)
        normalized_reason = self._reason(reason)
        try:
            with self._database.connect() as connection:
                self._repository.require_admin(connection, actor_user_id)
                self._repository.set_registration_policy(
                    connection, mode=mode, actor_user_id=actor_user_id, reason=normalized_reason
                )
                self._auth_repository.write_admin_audit(
                    connection,
                    audit_id=uuid4(),
                    actor_user_id=actor_user_id,
                    actor_session_id=actor_session_id,
                    action="registration_policy_update",
                    target_user_id=None,
                    reason=normalized_reason,
                    metadata=json.dumps({"mode": mode}, separators=(",", ":")),
                )
            return mode
        except PermissionError as exc:
            raise AccountAuthError("admin_required", "需要平台管理员权限。", status=403) from exc
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def admin_create_admission_batch(
        self,
        *,
        actor_user_id: UUID,
        actor_session_id: UUID,
        name: str,
        code_count: int,
        reason: str,
    ) -> AdmissionBatchIssue:
        normalized_name = name.strip()
        normalized_reason = self._reason(reason)
        if not 1 <= len(normalized_name) <= 120 or not 1 <= code_count <= 1000:
            raise AccountAuthError("invalid_request", "准入码批次参数无效。", status=400)
        batch_id = uuid4()
        plaintext_codes = tuple(f"OC-{secrets.token_urlsafe(24)}" for _ in range(code_count))
        code_rows = []
        for code in plaintext_codes:
            code_id = uuid4()
            code_rows.append(
                (
                    code_id,
                    self._admission_hmac(code),
                    self._encrypt_admission_code(code, batch_id, code_id),
                )
            )
        try:
            with self._database.connect() as connection:
                self._repository.require_admin(connection, actor_user_id)
                self._repository.create_admission_batch(
                    connection,
                    batch_id=batch_id,
                    name=normalized_name,
                    code_count=code_count,
                    actor_user_id=actor_user_id,
                    reason=normalized_reason,
                    codes=code_rows,
                )
                self._auth_repository.write_admin_audit(
                    connection,
                    audit_id=uuid4(),
                    actor_user_id=actor_user_id,
                    actor_session_id=actor_session_id,
                    action="admission_batch_create",
                    target_user_id=None,
                    reason=normalized_reason,
                    metadata=json.dumps({"batchId": str(batch_id), "codeCount": code_count}, separators=(",", ":")),
                )
            return AdmissionBatchIssue(batch_id, plaintext_codes)
        except PermissionError as exc:
            raise AccountAuthError("admin_required", "需要平台管理员权限。", status=403) from exc
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def admin_disable_admission_batch(
        self,
        *,
        actor_user_id: UUID,
        actor_session_id: UUID,
        batch_id: UUID,
        reason: str,
    ) -> None:
        normalized_reason = self._reason(reason)
        try:
            with self._database.connect() as connection:
                self._repository.require_admin(connection, actor_user_id)
                if not self._repository.disable_admission_batch(
                    connection,
                    batch_id=batch_id,
                    actor_user_id=actor_user_id,
                    reason=normalized_reason,
                ):
                    raise AccountAuthError("resource_not_found", "准入码批次不存在或已禁用。", status=404)
                self._auth_repository.write_admin_audit(
                    connection,
                    audit_id=uuid4(),
                    actor_user_id=actor_user_id,
                    actor_session_id=actor_session_id,
                    action="admission_batch_disable",
                    target_user_id=None,
                    reason=normalized_reason,
                    metadata=json.dumps({"batchId": str(batch_id)}, separators=(",", ":")),
                )
        except PermissionError as exc:
            raise AccountAuthError("admin_required", "需要平台管理员权限。", status=403) from exc
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def admin_update_affiliate_profile(
        self,
        *,
        actor_user_id: UUID,
        actor_session_id: UUID,
        target_user_id: UUID,
        signup_enabled: bool,
        signup_quota: int,
        signup_expires_at: datetime | None,
        reason: str,
    ) -> AffiliateProfile:
        normalized_reason = self._reason(reason)
        if not 0 <= signup_quota <= 1_000_000:
            raise AccountAuthError("invalid_request", "裂变名额无效。", status=400)
        if signup_expires_at is not None and signup_expires_at.tzinfo is None:
            raise AccountAuthError("invalid_request", "裂变有效期必须包含时区。", status=400)
        try:
            with self._database.connect() as connection:
                self._repository.require_admin(connection, actor_user_id)
                row = self._repository.update_affiliate_profile(
                    connection,
                    target_user_id=target_user_id,
                    signup_enabled=signup_enabled,
                    signup_quota=signup_quota,
                    signup_expires_at=signup_expires_at,
                )
                if row is None:
                    raise AccountAuthError(
                        "resource_not_found",
                        "用户不存在，或新名额少于已使用名额。",
                        status=404,
                    )
                self._auth_repository.write_admin_audit(
                    connection,
                    audit_id=uuid4(),
                    actor_user_id=actor_user_id,
                    actor_session_id=actor_session_id,
                    action="affiliate_profile_update",
                    target_user_id=target_user_id,
                    reason=normalized_reason,
                    metadata=json.dumps(
                        {
                            "signupEnabled": signup_enabled,
                            "signupQuota": signup_quota,
                            "signupExpiresAt": None if signup_expires_at is None else signup_expires_at.isoformat(),
                        },
                        separators=(",", ":"),
                    ),
                )
                return self._profile(row)
        except PermissionError as exc:
            raise AccountAuthError("admin_required", "需要平台管理员权限。", status=403) from exc
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def affiliate_profile(self, user_id: UUID) -> AffiliateProfile:
        try:
            with self._database.connect() as connection:
                row = self._repository.affiliate_profile(connection, user_id)
                if row is None:
                    raise AccountAuthError("resource_not_found", "邀请资料不存在。", status=404)
                return self._profile(row)
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def invitees(self, user_id: UUID, *, page: int, page_size: int) -> InviteePage:
        limit, offset = self._page(page, page_size)
        try:
            with self._database.connect() as connection:
                rows, total = self._repository.invitees(connection, user_id, limit=limit, offset=offset)
            return InviteePage(tuple(Invitee(*row) for row in rows), page, page_size, total)
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc

    def admin_admission_batches(self, actor_user_id: UUID, *, page: int, page_size: int) -> dict[str, object]:
        limit, offset = self._page(page, page_size)
        try:
            with self._database.connect() as connection:
                self._repository.require_admin(connection, actor_user_id)
                rows, total = self._repository.admission_batches(connection, limit=limit, offset=offset)
                code_rows = self._repository.admission_codes_for_batches(
                    connection,
                    [row[0] for row in rows],
                )
        except PermissionError as exc:
            raise AccountAuthError("admin_required", "需要平台管理员权限。", status=403) from exc
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc
        codes_by_batch: dict[UUID, list[dict[str, object]]] = {}
        for code_id, batch_id, code_hmac, ciphertext, status, consumed_at in code_rows:
            code = self._decrypt_admission_code(bytes(ciphertext), batch_id, code_id)
            if not hmac.compare_digest(self._admission_hmac(code), bytes(code_hmac)):
                raise AccountContractError("account_database_unavailable", "stored admission code integrity check failed")
            codes_by_batch.setdefault(batch_id, []).append(
                {
                    "code": code,
                    "status": status,
                    "consumedAt": None if consumed_at is None else consumed_at.isoformat(),
                }
            )
        return {
            "items": [
                {
                    "batchId": str(row[0]), "name": row[1], "status": row[2],
                    "codeCount": row[3], "consumedCount": row[4],
                    "createdAt": row[5].isoformat(),
                    "disabledAt": None if row[6] is None else row[6].isoformat(),
                    "codes": codes_by_batch.get(row[0], []),
                }
                for row in rows
            ],
            "page": page,
            "pageSize": page_size,
            "total": total,
        }

    def admin_affiliate_users(
        self,
        actor_user_id: UUID,
        *,
        search: str,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        limit, offset = self._page(page, page_size)
        normalized_search = search.strip()[:120]
        try:
            with self._database.connect() as connection:
                self._repository.require_admin(connection, actor_user_id)
                rows, total = self._repository.affiliate_users(
                    connection, search=normalized_search, limit=limit, offset=offset
                )
        except PermissionError as exc:
            raise AccountAuthError("admin_required", "需要平台管理员权限。", status=403) from exc
        except (AccountAuthError, AccountContractError):
            raise
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "canonical account database is unavailable") from exc
        return {
            "items": [self.profile_projection(self._profile(row)) for row in rows],
            "page": page,
            "pageSize": page_size,
            "total": total,
        }

    @staticmethod
    def profile_projection(profile: AffiliateProfile) -> dict[str, object]:
        return {
            "userId": str(profile.user_id),
            "username": profile.username,
            "inviteCode": profile.invite_code,
            "signupEnabled": profile.signup_enabled,
            "signupQuota": profile.signup_quota,
            "signupUsed": profile.signup_used,
            "signupRemaining": profile.signup_quota - profile.signup_used,
            "signupExpiresAt": None if profile.signup_expires_at is None else profile.signup_expires_at.isoformat(),
        }
