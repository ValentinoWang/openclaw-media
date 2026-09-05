from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
import threading
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, ContextManager, Iterator, Literal, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

import bcrypt

from .csrf import PERSONAL_CSRF_DOMAIN, derive_csrf_token
from .errors import AccountAuthError, AccountContractError
from .password_policy import validate_password
from .username import canonicalize_username, normalize_username


AccountStatus = Literal["PENDING_EMAIL_VERIFICATION", "ACTIVE", "SUSPENDED"]
TokenPurpose = Literal["email_verification", "password_recovery"]

PENDING_EMAIL_VERIFICATION: AccountStatus = "PENDING_EMAIL_VERIFICATION"
ACTIVE: AccountStatus = "ACTIVE"
SUSPENDED: AccountStatus = "SUSPENDED"
VERIFICATION_TTL_SECONDS = 24 * 60 * 60
RECOVERY_TTL_SECONDS = 30 * 60
SESSION_TTL_SECONDS = 8 * 60 * 60
TOKEN_BYTES = 32
PUBLIC_VERIFICATION_MESSAGE = "如果账号符合条件，我们会向邮箱发送验证邮件。"
PUBLIC_RECOVERY_MESSAGE = "如果账号符合条件，我们会向邮箱发送找回邮件。"
GENERIC_INVALID_CREDENTIALS = "用户名或密码不正确。"

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return an aware datetime")
    return value.astimezone(timezone.utc)


def _token_digest(token: str) -> bytes:
    if not isinstance(token, str):
        return b""
    try:
        raw = token.encode("ascii")
    except UnicodeEncodeError:
        return b""
    return hashlib.sha256(raw).digest()


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise AccountAuthError("invalid_request", "邮箱格式无效。", status=400)
    normalized = value.strip().casefold()
    if (
        not 3 <= len(normalized) <= 254
        or normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        raise AccountAuthError("invalid_request", "邮箱格式无效。", status=400)
    local, domain = normalized.split("@", 1)
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise AccountAuthError("invalid_request", "邮箱格式无效。", status=400)
    return normalized


def _normalize_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise AccountAuthError("invalid_credentials", GENERIC_INVALID_CREDENTIALS, status=401)
    stripped = value.strip()
    normalized = stripped.casefold() if "@" in stripped else canonicalize_username(stripped)
    if not 3 <= len(normalized) <= 254 or any(character.isspace() for character in normalized):
        raise AccountAuthError("invalid_credentials", GENERIC_INVALID_CREDENTIALS, status=401)
    return normalized


def _normalize_public_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    normalized = stripped.casefold() if "@" in stripped else canonicalize_username(stripped)
    if not 3 <= len(normalized) <= 254 or any(character.isspace() for character in normalized):
        return None
    return normalized


def _public_lookup_key(value: object, normalized: str | None) -> str:
    if normalized is not None:
        material = normalized.encode("utf-8")
    elif isinstance(value, str):
        material = value.encode("utf-8", "surrogatepass")
    else:
        material = type(value).__qualname__.encode("utf-8")
    return "lookup:" + hashlib.sha256(material).hexdigest()


def _hash_password(password: str, rounds: int) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("ascii")


@dataclass(frozen=True)
class PersonalAccountRecord:
    account_id: UUID
    username: str
    email: str
    password_hash: str
    status: AccountStatus
    email_verified_at: datetime | None
    legacy_email_unverified: bool = False


@dataclass(frozen=True)
class PersonalWorkspaceRecord:
    workspace_id: UUID
    account_id: UUID
    created_at: datetime


@dataclass(frozen=True)
class OneTimeTokenRecord:
    token_digest: bytes
    purpose: TokenPurpose
    account_id: UUID
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class PersonalSessionRecord:
    session_id: UUID
    token_digest: bytes
    csrf_digest: bytes
    account_id: UUID
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    expired_at: datetime | None = None


class PersonalAuthRepository(Protocol):
    """Persistence boundary for the personal authentication lifecycle."""

    def transaction(self) -> ContextManager["PersonalAuthRepository"]: ...

    def account_for_username(self, username: str) -> PersonalAccountRecord | None: ...

    def account_for_email(self, email: str) -> PersonalAccountRecord | None: ...

    def account_by_id(self, account_id: UUID) -> PersonalAccountRecord | None: ...

    def create_account(self, account: PersonalAccountRecord) -> None: ...

    def update_account(self, account: PersonalAccountRecord) -> None: ...

    def issue_token(self, token: OneTimeTokenRecord) -> None: ...

    def token_for_digest(self, token_digest: bytes) -> OneTimeTokenRecord | None: ...

    def consume_token(
        self,
        token_digest: bytes,
        purpose: TokenPurpose,
        now: datetime,
    ) -> OneTimeTokenRecord | None: ...

    def revoke_unconsumed_tokens(self, account_id: UUID, purpose: TokenPurpose, now: datetime) -> int: ...

    def ensure_personal_workspace(self, account_id: UUID, now: datetime) -> PersonalWorkspaceRecord: ...

    def workspace_for_account(self, account_id: UUID) -> PersonalWorkspaceRecord | None: ...

    def create_session(self, session: PersonalSessionRecord) -> None: ...

    def session_for_digest(self, token_digest: bytes) -> PersonalSessionRecord | None: ...

    def revoke_session(self, token_digest: bytes, now: datetime) -> bool: ...

    def expire_session(self, token_digest: bytes, now: datetime) -> bool: ...

    def revoke_account_sessions(self, account_id: UUID, now: datetime) -> int: ...

    def update_password(self, account_id: UUID, password_hash: str) -> None: ...

    def record_mail_delivery_failure(self, failure: "MailDeliveryFailure") -> None: ...


class AuthMailPort(Protocol):
    """Mail boundary. Implementations receive the raw token only for delivery."""

    def send_verification(self, *, email: str, token: str, expires_at: datetime) -> None: ...

    def send_password_recovery(self, *, email: str, token: str, expires_at: datetime) -> None: ...


@dataclass(frozen=True)
class MailDeliveryFailure:
    """Observable delivery failure without retaining a usable token."""

    purpose: TokenPurpose
    account_id: UUID
    email: str
    token_digest: bytes
    occurred_at: datetime
    error_type: str


@dataclass(frozen=True)
class VerificationEmail:
    email: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class PasswordRecoveryEmail:
    email: str
    token: str
    expires_at: datetime


class MemoryAuthMailPort:
    """Deterministic test mail port; raw tokens never enter the repository."""

    def __init__(self) -> None:
        self.verification_messages: list[VerificationEmail] = []
        self.recovery_messages: list[PasswordRecoveryEmail] = []

    def send_verification(self, *, email: str, token: str, expires_at: datetime) -> None:
        self.verification_messages.append(VerificationEmail(email, token, expires_at))

    def send_password_recovery(self, *, email: str, token: str, expires_at: datetime) -> None:
        self.recovery_messages.append(PasswordRecoveryEmail(email, token, expires_at))


class NullAuthMailPort:
    """Explicit no-op adapter for composition tests that do not deliver mail."""

    def send_verification(self, *, email: str, token: str, expires_at: datetime) -> None:
        return None

    def send_password_recovery(self, *, email: str, token: str, expires_at: datetime) -> None:
        return None


class _RepositoryConflict(RuntimeError):
    def __init__(self, field: Literal["username", "email"]) -> None:
        super().__init__(field)
        self.field = field


class InMemoryPersonalAuthRepository:
    """Transactional repository used by deterministic lifecycle and HTTP tests."""

    _STATE_FIELDS = (
        "_accounts",
        "_usernames",
        "_emails",
        "_tokens",
        "_workspaces",
        "_sessions",
        "_mail_delivery_failures",
    )

    def __init__(self) -> None:
        self._accounts: dict[UUID, PersonalAccountRecord] = {}
        self._usernames: dict[str, UUID] = {}
        self._emails: dict[str, UUID] = {}
        self._tokens: dict[bytes, OneTimeTokenRecord] = {}
        self._workspaces: dict[UUID, PersonalWorkspaceRecord] = {}
        self._sessions: dict[bytes, PersonalSessionRecord] = {}
        self._mail_delivery_failures: list[MailDeliveryFailure] = []
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self) -> Iterator["InMemoryPersonalAuthRepository"]:
        with self._lock:
            snapshot = {name: copy.deepcopy(getattr(self, name)) for name in self._STATE_FIELDS}
            try:
                yield self
            except BaseException:
                for name, value in snapshot.items():
                    setattr(self, name, value)
                raise

    def account_for_username(self, username: str) -> PersonalAccountRecord | None:
        account_id = self._usernames.get(username)
        return None if account_id is None else self._accounts.get(account_id)

    def account_for_email(self, email: str) -> PersonalAccountRecord | None:
        account_id = self._emails.get(email)
        return None if account_id is None else self._accounts.get(account_id)

    def account_by_id(self, account_id: UUID) -> PersonalAccountRecord | None:
        return self._accounts.get(account_id)

    def create_account(self, account: PersonalAccountRecord) -> None:
        if account.username in self._usernames:
            raise _RepositoryConflict("username")
        if account.email in self._emails:
            raise _RepositoryConflict("email")
        self._accounts[account.account_id] = account
        self._usernames[account.username] = account.account_id
        self._emails[account.email] = account.account_id

    def update_account(self, account: PersonalAccountRecord) -> None:
        if account.account_id not in self._accounts:
            raise KeyError("account does not exist")
        self._accounts[account.account_id] = account

    def issue_token(self, token: OneTimeTokenRecord) -> None:
        self._tokens[token.token_digest] = token

    def token_for_digest(self, token_digest: bytes) -> OneTimeTokenRecord | None:
        return self._tokens.get(token_digest)

    def consume_token(
        self,
        token_digest: bytes,
        purpose: TokenPurpose,
        now: datetime,
    ) -> OneTimeTokenRecord | None:
        record = self._tokens.get(token_digest)
        if (
            record is None
            or record.purpose != purpose
            or record.consumed_at is not None
            or record.revoked_at is not None
            or record.expires_at <= now
        ):
            return None
        consumed = replace(record, consumed_at=now)
        self._tokens[token_digest] = consumed
        return consumed

    def revoke_unconsumed_tokens(self, account_id: UUID, purpose: TokenPurpose, now: datetime) -> int:
        revoked = 0
        for digest, record in tuple(self._tokens.items()):
            if (
                record.account_id == account_id
                and record.purpose == purpose
                and record.consumed_at is None
                and record.revoked_at is None
            ):
                self._tokens[digest] = replace(record, revoked_at=now)
                revoked += 1
        return revoked

    def ensure_personal_workspace(self, account_id: UUID, now: datetime) -> PersonalWorkspaceRecord:
        existing = self._workspaces.get(account_id)
        if existing is not None:
            return existing
        workspace = PersonalWorkspaceRecord(uuid4(), account_id, now)
        self._workspaces[account_id] = workspace
        return workspace

    def workspace_for_account(self, account_id: UUID) -> PersonalWorkspaceRecord | None:
        return self._workspaces.get(account_id)

    def create_session(self, session: PersonalSessionRecord) -> None:
        if session.token_digest in self._sessions:
            raise _RepositoryConflict("username")
        self._sessions[session.token_digest] = session

    def session_for_digest(self, token_digest: bytes) -> PersonalSessionRecord | None:
        return self._sessions.get(token_digest)

    def revoke_session(self, token_digest: bytes, now: datetime) -> bool:
        record = self._sessions.get(token_digest)
        if record is None or record.revoked_at is not None or record.expired_at is not None:
            return False
        self._sessions[token_digest] = replace(record, revoked_at=now)
        return True

    def expire_session(self, token_digest: bytes, now: datetime) -> bool:
        record = self._sessions.get(token_digest)
        if record is None or record.revoked_at is not None or record.expired_at is not None:
            return False
        self._sessions[token_digest] = replace(record, expired_at=now)
        return True

    def revoke_account_sessions(self, account_id: UUID, now: datetime) -> int:
        revoked = 0
        for digest, record in tuple(self._sessions.items()):
            if record.account_id == account_id and record.revoked_at is None and record.expired_at is None:
                self._sessions[digest] = replace(record, revoked_at=now)
                revoked += 1
        return revoked

    def update_password(self, account_id: UUID, password_hash: str) -> None:
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError("account does not exist")
        self._accounts[account_id] = replace(account, password_hash=password_hash)

    def record_mail_delivery_failure(self, failure: MailDeliveryFailure) -> None:
        self._mail_delivery_failures.append(failure)

    def mail_delivery_failures(self) -> tuple[MailDeliveryFailure, ...]:
        return tuple(self._mail_delivery_failures)

    def token_records(self, purpose: TokenPurpose | None = None) -> tuple[OneTimeTokenRecord, ...]:
        values = tuple(self._tokens.values())
        return values if purpose is None else tuple(item for item in values if item.purpose == purpose)

    def session_records(self) -> tuple[PersonalSessionRecord, ...]:
        return tuple(self._sessions.values())

    def account_records(self) -> tuple[PersonalAccountRecord, ...]:
        return tuple(self._accounts.values())


@dataclass(frozen=True)
class RateLimitRule:
    max_requests: int
    window_seconds: int


DEFAULT_RATE_LIMITS: Mapping[str, RateLimitRule] = {
    "login": RateLimitRule(5, 60),
    "verification_resend": RateLimitRule(3, 3600),
    "password_recovery": RateLimitRule(3, 3600),
}


class SourceAccountRateLimiter:
    """Enforces both source and account dimensions with stricter-only overrides."""

    def __init__(
        self,
        rules: Mapping[str, RateLimitRule] | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        active = dict(DEFAULT_RATE_LIMITS)
        if rules:
            for name, rule in rules.items():
                default = DEFAULT_RATE_LIMITS.get(name)
                if default is None:
                    raise ValueError(f"unknown auth rate-limit operation: {name}")
                if (
                    rule.max_requests <= 0
                    or rule.window_seconds <= 0
                    or rule.max_requests > default.max_requests
                    or rule.window_seconds < default.window_seconds
                ):
                    raise ValueError("auth rate-limit overrides may only be stricter")
                active[name] = rule
        self._rules = active
        self._clock = clock or __import__("time").monotonic
        self._events: dict[tuple[str, str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, operation: str, *, source_key: str, account_key: str) -> tuple[bool, int]:
        if operation not in self._rules:
            raise ValueError(f"unknown auth rate-limit operation: {operation}")
        rule = self._rules[operation]
        now = self._clock()
        retry_after = 0
        with self._lock:
            event_states: list[tuple[tuple[str, str, str], int]] = []
            for dimension, key in (("source", source_key), ("account", account_key)):
                event_key = (operation, dimension, key)
                events = self._events.get(event_key)
                cutoff = now - rule.window_seconds
                expired = 0
                while events is not None and expired < len(events) and events[expired] <= cutoff:
                    expired += 1
                if events is not None and len(events) - expired >= rule.max_requests:
                    retry_after = max(
                        retry_after,
                        int(rule.window_seconds - (now - events[expired]) + 0.999),
                    )
                event_states.append((event_key, expired))
            if retry_after:
                return False, max(1, retry_after)
            for event_key, expired in event_states:
                events = self._events.setdefault(event_key, deque())
                for _ in range(expired):
                    events.popleft()
                events.append(now)
        return True, 0


@dataclass(frozen=True)
class PersonalSession:
    session_id: UUID
    account_id: UUID
    username: str
    email: str
    status: AccountStatus
    issued_at: datetime
    expires_at: datetime
    personal_workspace_id: UUID | None


@dataclass(frozen=True)
class PersonalLogin:
    token: str
    csrf_token: str
    session: PersonalSession


@dataclass(frozen=True)
class PersonalRegistrationResult:
    account_id: UUID | None
    status: AccountStatus
    public_message: str = PUBLIC_VERIFICATION_MESSAGE
    email_delivery_queued: bool = True


@dataclass(frozen=True)
class VerificationResult:
    account_id: UUID
    personal_workspace_id: UUID
    login_required: bool = True


@dataclass(frozen=True)
class PasswordRecoveryResult:
    public_message: str = PUBLIC_RECOVERY_MESSAGE


@dataclass(frozen=True)
class PasswordResetResult:
    account_id: UUID
    login_required: bool = True


class PersonalAuthService:
    """Implements the phase-one personal account and session contract."""

    def __init__(
        self,
        repository: PersonalAuthRepository,
        *,
        mail_port: AuthMailPort | None = None,
        csrf_secret: bytes | None = None,
        now: Callable[[], datetime] | None = None,
        bcrypt_rounds: int = 12,
        rate_limiter: SourceAccountRateLimiter | None = None,
    ) -> None:
        if csrf_secret is not None and len(csrf_secret) < 32:
            raise ValueError("personal auth secret must be at least 32 bytes")
        if not 4 <= bcrypt_rounds <= 16:
            raise ValueError("bcrypt rounds must be between 4 and 16")
        self._repository = repository
        self._mail = mail_port or NullAuthMailPort()
        self._csrf_secret = csrf_secret or secrets.token_bytes(32)
        self._now = now or _now_utc
        self._bcrypt_rounds = bcrypt_rounds
        self._rate_limiter = rate_limiter or SourceAccountRateLimiter()
        self._dummy_hash = _hash_password("invalid-credential-dummy", bcrypt_rounds)

    @property
    def session_ttl_seconds(self) -> int:
        return SESSION_TTL_SECONDS

    @property
    def repository(self) -> PersonalAuthRepository:
        return self._repository

    def register(self, *, username: str, email: str, password: str) -> PersonalRegistrationResult:
        normalized_username = normalize_username(username)
        normalized_email = _normalize_email(email)
        validate_password(password)
        now = _aware(self._now())
        raw_token: str | None = None
        expires_at: datetime | None = None
        account_id: UUID | None = None
        with self._repository.transaction():
            if self._repository.account_for_username(normalized_username) is not None:
                raise AccountAuthError("duplicate_username", "用户名已被使用，请更换后重试。", status=409)
            if self._repository.account_for_email(normalized_email) is not None:
                # Email duplication is deliberately indistinguishable from a successful submission.
                return PersonalRegistrationResult(None, PENDING_EMAIL_VERIFICATION)
            account_id = uuid4()
            account = PersonalAccountRecord(
                account_id=account_id,
                username=normalized_username,
                email=normalized_email,
                password_hash=_hash_password(password, self._bcrypt_rounds),
                status=PENDING_EMAIL_VERIFICATION,
                email_verified_at=None,
            )
            try:
                self._repository.create_account(account)
            except _RepositoryConflict as exc:
                if exc.field == "username":
                    raise AccountAuthError("duplicate_username", "用户名已被使用，请更换后重试。", status=409) from exc
                return PersonalRegistrationResult(None, PENDING_EMAIL_VERIFICATION)
            raw_token = _new_token()
            expires_at = now + timedelta(seconds=VERIFICATION_TTL_SECONDS)
            self._repository.revoke_unconsumed_tokens(account_id, "email_verification", now)
            self._repository.issue_token(
                OneTimeTokenRecord(
                    token_digest=_token_digest(raw_token),
                    purpose="email_verification",
                    account_id=account_id,
                    issued_at=now,
                    expires_at=expires_at,
                )
            )
        assert account_id is not None and raw_token is not None and expires_at is not None
        queued = self._send_verification(
            normalized_email,
            raw_token,
            expires_at,
            account_id=account_id,
            purpose="email_verification",
            now=now,
        )
        return PersonalRegistrationResult(account_id, PENDING_EMAIL_VERIFICATION, email_delivery_queued=queued)

    def resend_verification(self, identifier: str, *, source_key: str = "local") -> PersonalRegistrationResult:
        normalized = _normalize_public_identifier(identifier)
        account = None if normalized is None else self._repository.account_for_username(normalized)
        if account is None and normalized is not None:
            account = self._repository.account_for_email(normalized)
        account_key = (
            str(account.account_id)
            if account is not None
            else _public_lookup_key(identifier, normalized)
        )
        allowed, retry_after = self._rate_limiter.check(
            "verification_resend", source_key=source_key, account_key=account_key
        )
        if not allowed:
            raise AccountAuthError(
                "rate_limited",
                "请求过于频繁，请稍后重试。",
                status=429,
            )
        raw_token: str | None = None
        expires_at: datetime | None = None
        email: str | None = None
        now = _aware(self._now())
        if account is not None and account.status == PENDING_EMAIL_VERIFICATION:
            with self._repository.transaction():
                current = self._repository.account_by_id(account.account_id)
                if current is not None and current.status == PENDING_EMAIL_VERIFICATION:
                    raw_token = _new_token()
                    expires_at = now + timedelta(seconds=VERIFICATION_TTL_SECONDS)
                    self._repository.revoke_unconsumed_tokens(current.account_id, "email_verification", now)
                    self._repository.issue_token(
                        OneTimeTokenRecord(
                            token_digest=_token_digest(raw_token),
                            purpose="email_verification",
                            account_id=current.account_id,
                            issued_at=now,
                            expires_at=expires_at,
                        )
                    )
                    email = current.email
        queued = True
        if raw_token is not None and expires_at is not None and email is not None and account is not None:
            queued = self._send_verification(
                email,
                raw_token,
                expires_at,
                account_id=account.account_id,
                purpose="email_verification",
                now=now,
            )
        return PersonalRegistrationResult(None, PENDING_EMAIL_VERIFICATION, email_delivery_queued=queued)

    def verify_email(self, token: str) -> VerificationResult:
        digest = _token_digest(token)
        now = _aware(self._now())
        with self._repository.transaction():
            record = self._repository.consume_token(digest, "email_verification", now)
            if record is None:
                raise AccountAuthError("verification_invalid", "验证链接无效或已过期。", status=400)
            account = self._repository.account_by_id(record.account_id)
            if account is None or account.status != PENDING_EMAIL_VERIFICATION:
                raise AccountAuthError("verification_invalid", "验证链接无效或已过期。", status=400)
            self._repository.update_account(
                replace(account, status=ACTIVE, email_verified_at=now, legacy_email_unverified=False)
            )
            workspace = self._repository.ensure_personal_workspace(account.account_id, now)
            return VerificationResult(account.account_id, workspace.workspace_id)

    def login(
        self,
        identifier: str,
        password: str,
        *,
        source_key: str = "local",
        previous_session_token: str | None = None,
    ) -> PersonalLogin:
        normalized = _normalize_identifier(identifier)
        if not isinstance(password, str) or len(password) > 128:
            raise AccountAuthError("invalid_credentials", GENERIC_INVALID_CREDENTIALS, status=401)
        account = self._repository.account_for_username(normalized)
        identifier_kind = "username"
        if account is None:
            candidate = self._repository.account_for_email(normalized)
            if candidate is not None and candidate.email_verified_at is not None:
                account = candidate
                identifier_kind = "email"
        account_key = str(account.account_id) if account is not None else "lookup:" + hashlib.sha256(normalized.encode()).hexdigest()
        allowed, retry_after = self._rate_limiter.check("login", source_key=source_key, account_key=account_key)
        if not allowed:
            raise AccountAuthError("rate_limited", "请求过于频繁，请稍后重试。", status=429)
        password_valid = self._verify_password(password, account)
        if account is None or not password_valid or account.status == SUSPENDED:
            raise AccountAuthError("invalid_credentials", GENERIC_INVALID_CREDENTIALS, status=401)
        if account.status == PENDING_EMAIL_VERIFICATION:
            if identifier_kind == "username":
                raise AccountAuthError(
                    "email_verification_required",
                    "请先完成邮箱验证，再登录。",
                    status=403,
                )
            raise AccountAuthError("invalid_credentials", GENERIC_INVALID_CREDENTIALS, status=401)
        if account.status != ACTIVE:
            raise AccountAuthError("invalid_credentials", GENERIC_INVALID_CREDENTIALS, status=401)
        if account.email_verified_at is None and not account.legacy_email_unverified:
            raise AccountAuthError("invalid_credentials", GENERIC_INVALID_CREDENTIALS, status=401)
        now = _aware(self._now())
        with self._repository.transaction():
            current = self._repository.account_by_id(account.account_id)
            if (
                current is None
                or not self._verify_password(password, current)
                or current.status != ACTIVE
                or (current.email_verified_at is None and not current.legacy_email_unverified)
                or (identifier_kind == "email" and current.email_verified_at is None)
            ):
                raise AccountAuthError("invalid_credentials", GENERIC_INVALID_CREDENTIALS, status=401)
            if previous_session_token:
                self._repository.revoke_session(_token_digest(previous_session_token), now)
            return self._issue_session(current, now)

    def resolve_session(self, token: str | None) -> PersonalSession | None:
        if not isinstance(token, str) or not 20 <= len(token) <= 256:
            return None
        digest = _token_digest(token)
        now = _aware(self._now())
        with self._repository.transaction():
            record = self._repository.session_for_digest(digest)
            if record is None or record.revoked_at is not None or record.expired_at is not None:
                return None
            if record.expires_at <= now:
                self._repository.expire_session(digest, now)
                return None
            account = self._repository.account_by_id(record.account_id)
            if account is None or account.status != ACTIVE:
                self._repository.revoke_session(digest, now)
                return None
            workspace = self._repository.workspace_for_account(account.account_id)
            return PersonalSession(
                session_id=record.session_id,
                account_id=account.account_id,
                username=account.username,
                email=account.email,
                status=account.status,
                issued_at=record.issued_at,
                expires_at=record.expires_at,
                personal_workspace_id=None if workspace is None else workspace.workspace_id,
            )

    def verify_csrf(self, token: str | None, supplied: str | None) -> bool:
        if not isinstance(token, str) or not isinstance(supplied, str) or not supplied:
            return False
        record = self._repository.session_for_digest(_token_digest(token))
        if record is None or record.revoked_at is not None or record.expired_at is not None:
            return False
        if record.expires_at <= _aware(self._now()):
            return False
        return hmac.compare_digest(record.csrf_digest, _token_digest(supplied))

    def csrf_token_for_session(self, token: str | None) -> str | None:
        if not isinstance(token, str):
            return None
        record = self._repository.session_for_digest(_token_digest(token))
        if (
            record is None
            or record.revoked_at is not None
            or record.expired_at is not None
            or record.expires_at <= _aware(self._now())
        ):
            return None
        return self._csrf_token(token)

    def revoke_session(self, token: str | None) -> None:
        if token:
            with self._repository.transaction():
                self._repository.revoke_session(_token_digest(token), _aware(self._now()))

    def request_password_recovery(
        self,
        identifier: str,
        *,
        source_key: str = "local",
    ) -> PasswordRecoveryResult:
        normalized = _normalize_public_identifier(identifier)
        account = None if normalized is None else self._repository.account_for_username(normalized)
        if account is None and normalized is not None:
            account = self._repository.account_for_email(normalized)
        account_key = (
            str(account.account_id)
            if account is not None
            else _public_lookup_key(identifier, normalized)
        )
        allowed, retry_after = self._rate_limiter.check(
            "password_recovery", source_key=source_key, account_key=account_key
        )
        if not allowed:
            raise AccountAuthError("rate_limited", "请求过于频繁，请稍后重试。", status=429)
        raw_token: str | None = None
        expires_at: datetime | None = None
        email: str | None = None
        now = _aware(self._now())
        if account is not None and account.status == ACTIVE and account.email_verified_at is not None:
            with self._repository.transaction():
                current = self._repository.account_by_id(account.account_id)
                if current is not None and current.status == ACTIVE and current.email_verified_at is not None:
                    raw_token = _new_token()
                    expires_at = now + timedelta(seconds=RECOVERY_TTL_SECONDS)
                    self._repository.revoke_unconsumed_tokens(current.account_id, "password_recovery", now)
                    self._repository.issue_token(
                        OneTimeTokenRecord(
                            token_digest=_token_digest(raw_token),
                            purpose="password_recovery",
                            account_id=current.account_id,
                            issued_at=now,
                            expires_at=expires_at,
                        )
                    )
                    email = current.email
        if raw_token is not None and expires_at is not None and email is not None and account is not None:
            self._send_recovery(
                email,
                raw_token,
                expires_at,
                account_id=account.account_id,
                purpose="password_recovery",
                now=now,
            )
        return PasswordRecoveryResult()

    def reset_password(self, token: str, new_password: str) -> PasswordResetResult:
        validate_password(new_password)
        digest = _token_digest(token)
        now = _aware(self._now())
        with self._repository.transaction():
            record = self._repository.consume_token(digest, "password_recovery", now)
            if record is None:
                raise AccountAuthError("recovery_invalid", "找回链接无效或已过期。", status=400)
            account = self._repository.account_by_id(record.account_id)
            if account is None or account.status != ACTIVE or account.email_verified_at is None:
                raise AccountAuthError("recovery_invalid", "找回链接无效或已过期。", status=400)
            self._repository.update_password(account.account_id, _hash_password(new_password, self._bcrypt_rounds))
            self._repository.revoke_account_sessions(account.account_id, now)
            self._repository.revoke_unconsumed_tokens(account.account_id, "password_recovery", now)
            return PasswordResetResult(account.account_id)

    def rotate_session(self, token: str) -> PersonalLogin:
        now = _aware(self._now())
        with self._repository.transaction():
            record = self._repository.session_for_digest(_token_digest(token))
            if record is None or record.revoked_at is not None or record.expired_at is not None or record.expires_at <= now:
                raise AccountAuthError("authentication_required", "登录会话已失效。", status=401)
            account = self._repository.account_by_id(record.account_id)
            if account is None or account.status != ACTIVE:
                raise AccountAuthError("authentication_required", "登录会话已失效。", status=401)
            self._repository.revoke_session(record.token_digest, now)
            return self._issue_session(account, now)

    def account(self, account_id: UUID) -> PersonalAccountRecord | None:
        return self._repository.account_by_id(account_id)

    def _issue_session(self, account: PersonalAccountRecord, now: datetime) -> PersonalLogin:
        token = _new_token()
        csrf_token = self._csrf_token(token)
        workspace = self._repository.workspace_for_account(account.account_id)
        record = PersonalSessionRecord(
            session_id=uuid4(),
            token_digest=_token_digest(token),
            csrf_digest=_token_digest(csrf_token),
            account_id=account.account_id,
            issued_at=now,
            expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
        )
        self._repository.create_session(record)
        return PersonalLogin(
            token=token,
            csrf_token=csrf_token,
            session=PersonalSession(
                session_id=record.session_id,
                account_id=account.account_id,
                username=account.username,
                email=account.email,
                status=account.status,
                issued_at=record.issued_at,
                expires_at=record.expires_at,
                personal_workspace_id=None if workspace is None else workspace.workspace_id,
            ),
        )

    def _verify_password(self, password: str, account: PersonalAccountRecord | None) -> bool:
        candidate = (
            self._dummy_hash.encode("ascii")
            if account is None
            else account.password_hash.encode("ascii")
        )
        try:
            return bool(bcrypt.checkpw(password.encode("utf-8"), candidate))
        except (UnicodeEncodeError, ValueError):
            return False

    def _csrf_token(self, token: str) -> str:
        return derive_csrf_token(self._csrf_secret, token, domain=PERSONAL_CSRF_DOMAIN)

    def _record_mail_failure(
        self,
        *,
        purpose: TokenPurpose,
        account_id: UUID,
        email: str,
        token: str,
        now: datetime,
        error: Exception,
    ) -> None:
        failure = MailDeliveryFailure(
            purpose=purpose,
            account_id=account_id,
            email=email,
            token_digest=_token_digest(token),
            occurred_at=now,
            error_type=type(error).__name__,
        )
        recorder = getattr(self._repository, "record_mail_delivery_failure", None)
        if not callable(recorder):
            raise AccountContractError("email_delivery_unavailable", "邮件投递暂时无法记录。") from error
        with self._repository.transaction():
            recorder(failure)

    def _send_verification(
        self,
        email: str,
        token: str,
        expires_at: datetime,
        *,
        account_id: UUID,
        purpose: TokenPurpose,
        now: datetime,
    ) -> bool:
        try:
            self._mail.send_verification(email=email, token=token, expires_at=expires_at)
        except Exception as exc:
            self._record_mail_failure(
                purpose=purpose,
                account_id=account_id,
                email=email,
                token=token,
                now=now,
                error=exc,
            )
            return False
        return True

    def _send_recovery(
        self,
        email: str,
        token: str,
        expires_at: datetime,
        *,
        account_id: UUID,
        purpose: TokenPurpose,
        now: datetime,
    ) -> bool:
        try:
            self._mail.send_password_recovery(email=email, token=token, expires_at=expires_at)
        except Exception as exc:
            self._record_mail_failure(
                purpose=purpose,
                account_id=account_id,
                email=email,
                token=token,
                now=now,
                error=exc,
            )
            return False
        return True


@dataclass(frozen=True)
class OrganizationIntentRecord:
    state_digest: bytes
    callback_destination: str
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None


class OrganizationIntentRepository(Protocol):
    def transaction(self) -> ContextManager["OrganizationIntentRepository"]: ...

    def create(self, record: OrganizationIntentRecord) -> None: ...

    def peek(self, state_digest: bytes) -> OrganizationIntentRecord | None: ...

    def consume(self, state_digest: bytes, now: datetime) -> OrganizationIntentRecord | None: ...


class InMemoryOrganizationIntentRepository:
    def __init__(self) -> None:
        self._records: dict[bytes, OrganizationIntentRecord] = {}
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self) -> Iterator["InMemoryOrganizationIntentRepository"]:
        with self._lock:
            snapshot = copy.deepcopy(self._records)
            try:
                yield self
            except BaseException:
                self._records = snapshot
                raise

    def create(self, record: OrganizationIntentRecord) -> None:
        if record.state_digest in self._records:
            raise RuntimeError("organization auth intent state collision")
        self._records[record.state_digest] = record

    def peek(self, state_digest: bytes) -> OrganizationIntentRecord | None:
        return self._records.get(state_digest)

    def consume(self, state_digest: bytes, now: datetime) -> OrganizationIntentRecord | None:
        record = self._records.get(state_digest)
        if record is None or record.consumed_at is not None or record.expires_at <= now:
            return None
        consumed = replace(record, consumed_at=now)
        self._records[state_digest] = consumed
        return consumed

    def records(self) -> tuple[OrganizationIntentRecord, ...]:
        return tuple(self._records.values())


@dataclass(frozen=True)
class OrganizationIntentStart:
    state: str
    callback_destination: str
    expires_at: datetime


@dataclass(frozen=True)
class OrganizationIntentStatus:
    status: Literal["CONSUMED"]
    callback_destination: str
    consumed_at: datetime
    identity_link_created: bool = False


class OrganizationAuthIntentService:
    """Stores a one-time organization handoff without linking any identity."""

    def __init__(
        self,
        repository: OrganizationIntentRepository,
        *,
        allowed_callback_destinations: Sequence[str],
        now: Callable[[], datetime] | None = None,
        ttl_seconds: int = 10 * 60,
    ) -> None:
        if not allowed_callback_destinations:
            raise ValueError("at least one organization callback destination is required")
        if not 60 <= ttl_seconds <= 24 * 60 * 60:
            raise ValueError("organization intent ttl is out of bounds")
        normalized = tuple(dict.fromkeys(destination.strip() for destination in allowed_callback_destinations))
        if any(not destination for destination in normalized):
            raise ValueError("organization callback destinations must be non-empty")
        self._repository = repository
        self._allowed_callbacks = frozenset(normalized)
        self._now = now or _now_utc
        self._ttl_seconds = ttl_seconds

    def start(self, callback_destination: str) -> OrganizationIntentStart:
        destination = self._validate_callback(callback_destination)
        state = _new_token()
        now = _aware(self._now())
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        with self._repository.transaction():
            self._repository.create(
                OrganizationIntentRecord(
                    state_digest=_token_digest(state),
                    callback_destination=destination,
                    created_at=now,
                    expires_at=expires_at,
                )
            )
        return OrganizationIntentStart(state, destination, expires_at)

    def status(self, state: str, callback_destination: str) -> OrganizationIntentStatus:
        destination = self._validate_callback(callback_destination)
        now = _aware(self._now())
        digest = _token_digest(state)
        with self._repository.transaction():
            record = self._repository.peek(digest)
            if record is not None and record.callback_destination != destination:
                raise AccountAuthError("callback_mismatch", "回调地址不在该认证意图中。", status=400)
            consumed = self._repository.consume(digest, now)
            if consumed is None:
                raise AccountAuthError("organization_intent_invalid", "组织认证意图无效或已过期。", status=400)
            return OrganizationIntentStatus("CONSUMED", consumed.callback_destination, now)

    def _validate_callback(self, callback_destination: str) -> str:
        if not isinstance(callback_destination, str):
            raise AccountAuthError("callback_mismatch", "回调地址不在允许列表中。", status=400)
        destination = callback_destination.strip()
        if destination not in self._allowed_callbacks:
            raise AccountAuthError("callback_mismatch", "回调地址不在允许列表中。", status=400)
        return destination


__all__ = [
    "ACTIVE",
    "AuthMailPort",
    "DEFAULT_RATE_LIMITS",
    "GENERIC_INVALID_CREDENTIALS",
    "InMemoryOrganizationIntentRepository",
    "InMemoryPersonalAuthRepository",
    "MemoryAuthMailPort",
    "MailDeliveryFailure",
    "NullAuthMailPort",
    "OrganizationAuthIntentService",
    "OrganizationIntentRecord",
    "OrganizationIntentStart",
    "OrganizationIntentStatus",
    "OrganizationIntentRepository",
    "PENDING_EMAIL_VERIFICATION",
    "PasswordRecoveryEmail",
    "PasswordRecoveryResult",
    "PasswordResetResult",
    "PersonalAccountRecord",
    "PersonalAuthRepository",
    "PersonalAuthService",
    "PersonalLogin",
    "PersonalRegistrationResult",
    "PersonalSession",
    "PersonalSessionRecord",
    "PersonalWorkspaceRecord",
    "RateLimitRule",
    "SESSION_TTL_SECONDS",
    "SourceAccountRateLimiter",
    "SUSPENDED",
    "TOKEN_BYTES",
    "VERIFICATION_TTL_SECONDS",
    "VerificationEmail",
    "VerificationResult",
]
