from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import threading
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from uuid import UUID

from openclaw_app.account import (
    AccountAuthError,
    AccountAuthService,
    AccountContractError,
    AccountLogin,
    AccountSession,
    AdmissionBatchIssue,
    AffiliateProfile,
    Invitee,
    InviteePage,
    MediaFeishuIdentity,
    MediaFeishuLoginStart,
    RegistrationResult,
)
from openclaw_app.adapters.http_api import (
    AuthConfig,
    HttpAuthorityConfig,
    MutationIdempotencyBindings,
    OpenClawHttpHandler,
    load_auth_environment,
    make_server,
)
from openclaw_app.services.capability_registry import CAPABILITY_REGISTRY
from openclaw_app.services.guidance_plan import GuidancePlanService
from openclaw_app.services.media_web_tasks import MediaWebTaskService


USER_A = UUID("11111111-1111-4111-8111-111111111111")
TENANT_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
TENANT_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ADMIN = UUID("33333333-3333-4333-8333-333333333333")
ADMIN_TENANT = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def _auth_environment() -> dict[str, str]:
    return {
        "OPENCLAW_ACCOUNT_DATABASE_URL": "postgresql://account.test/openclaw",
        "OPENCLAW_ACCOUNT_SESSION_SECRET": "s" * 48,
        "OPENCLAW_ACCOUNT_SESSION_TTL_SECONDS": "3600",
        "OPENCLAW_BOT_CENTER_COOKIE_PATH": "/openclaw/",
        "OPENCLAW_BOT_CENTER_COOKIE_SECURE": "false",
    }


class _FakeAccountAuth:
    def __init__(self) -> None:
        self._secret = b"s" * 48
        self._counter = 0
        self.sessions: dict[str, AccountSession] = {}
        self.roles = {USER_A: "user", USER_B: "user", ADMIN: "admin"}
        self.accounts = {
            "user-a": (USER_A, TENANT_A),
            "user-b": (USER_B, TENANT_B),
            "admin": (ADMIN, ADMIN_TENANT),
        }
        self.previous_tokens: list[str | None] = []
        self.database_down = False
        self.admin_revocations: list[tuple[UUID, UUID, str]] = []
        self.feishu_login_intents: list[str] = []

    def csrf_token(self, token: str) -> str:
        return hmac.new(self._secret, token.encode("ascii"), hashlib.sha256).hexdigest()

    def verify_csrf(self, token: str, supplied: str) -> bool:
        return hmac.compare_digest(self.csrf_token(token), supplied)

    def issue_test_session(self, username: str, *, previous_token: str | None = None) -> AccountLogin:
        if self.database_down:
            raise AccountContractError("account_database_unavailable", "database unavailable")
        account = self.accounts.get(username.lower())
        if account is None:
            raise AccountContractError("account_contract_invalid", "test account is not configured")
        self.previous_tokens.append(previous_token)
        if previous_token:
            self.sessions.pop(previous_token, None)
        self._counter += 1
        token = f"opaque-account-session-token-{self._counter:08d}"
        user_id, tenant_id = account
        session = AccountSession(
            session_id=UUID(int=self._counter),
            user_id=user_id,
            tenant_id=tenant_id,
            username=username.lower(),
            email=f"{username.lower()}@example.com",
            role=self.roles[user_id],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_maintainer=user_id == ADMIN,
        )
        self.sessions[token] = session
        return AccountLogin(token, self.csrf_token(token), session)

    def login_verified_feishu_identity(
        self,
        *,
        tenant_key: str,
        open_id: str | None,
        union_id: str | None,
        previous_token: str | None = None,
        workspace_intent: str = "personal_web",
    ) -> AccountLogin:
        self.feishu_login_intents.append(workspace_intent)
        if (tenant_key, open_id, union_id) != ("tenant-media-a", "open-a", "union-a"):
            raise AccountAuthError(
                "feishu_account_unlinked",
                "该飞书账号尚未绑定 MediaClaw 账户。",
                status=403,
            )
        return self.issue_test_session("user-a", previous_token=previous_token)

    def issue_registration_session(
        self,
        *,
        username: str,
        email: str | None,
        user_id: UUID,
        tenant_id: UUID,
    ) -> AccountLogin:
        self._counter += 1
        token = f"opaque-account-session-token-{self._counter:08d}"
        session = AccountSession(
            session_id=UUID(int=self._counter),
            user_id=user_id,
            tenant_id=tenant_id,
            username=username,
            email=email,
            role="user",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        self.sessions[token] = session
        return AccountLogin(token, self.csrf_token(token), session)

    def resolve_session(self, token: str | None) -> AccountSession | None:
        if self.database_down:
            raise AccountContractError("account_database_unavailable", "database unavailable")
        session = self.sessions.get(token or "")
        if session is None or session.expires_at <= datetime.now(timezone.utc):
            return None
        return replace(session, role=self.roles[session.user_id])

    def revoke_session(self, token: str | None) -> None:
        self.sessions.pop(token or "", None)

    def admin_revoke_user_sessions(self, actor_token: str, target_user_id: UUID, reason: str) -> int:
        actor = self.resolve_session(actor_token)
        if actor is None:
            raise AccountAuthError("authentication_required", "登录会话已失效。", status=401)
        if self.roles[actor.user_id] != "admin":
            raise AccountAuthError("admin_required", "需要平台管理员权限。", status=403)
        revoked = 0
        for token, session in list(self.sessions.items()):
            if session.user_id == target_user_id:
                self.sessions.pop(token)
                revoked += 1
        self.admin_revocations.append((actor.user_id, target_user_id, reason))
        return revoked


class _FakeAccountRegistration:
    def __init__(self, account_auth: _FakeAccountAuth) -> None:
        self.account_auth = account_auth
        self.mode = "controlled"
        self.registration_calls: list[dict[str, Any]] = []
        self.profile_updates: list[tuple[UUID, UUID]] = []

    def registration_mode(self) -> str:
        return self.mode

    def register(self, **kwargs: Any) -> RegistrationResult:
        self.registration_calls.append(kwargs)
        username = str(kwargs["username"]).strip().lower()
        login = self.account_auth.issue_registration_session(
            username=username,
            email=kwargs.get("email"),
            user_id=USER_B,
            tenant_id=TENANT_B,
        )
        return RegistrationResult(USER_B, TENANT_B, username, USER_A, login)

    def affiliate_profile(self, user_id: UUID) -> AffiliateProfile:
        username = "user-a" if user_id == USER_A else "admin"
        return AffiliateProfile(user_id, username, "ABCDEF0123456789ABCD", True, 5, 1, None)

    def invitees(self, user_id: UUID, *, page: int, page_size: int) -> InviteePage:
        self.profile_updates.append((user_id, user_id))
        return InviteePage(
            (Invitee(USER_B, "user-b", datetime(2026, 8, 2, tzinfo=timezone.utc)),),
            page,
            page_size,
            1,
        )

    def admin_set_registration_policy(
        self,
        *,
        actor_user_id: UUID,
        actor_session_id: UUID,
        mode: str,
        reason: str,
    ) -> str:
        self.mode = mode
        return mode

    def admin_create_admission_batch(self, **kwargs: Any) -> AdmissionBatchIssue:
        return AdmissionBatchIssue(UUID("55555555-5555-4555-8555-555555555555"), ("OC-one-time-code",))

    def admin_disable_admission_batch(self, **kwargs: Any) -> None:
        return None

    def admin_admission_batches(self, actor_user_id: UUID, *, page: int, page_size: int) -> dict[str, object]:
        return {"items": [], "page": page, "pageSize": page_size, "total": 0}

    def admin_affiliate_users(
        self,
        actor_user_id: UUID,
        *,
        search: str,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        return {"items": [], "page": page, "pageSize": page_size, "total": 0}

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
        self.profile_updates.append((actor_user_id, target_user_id))
        return AffiliateProfile(
            target_user_id,
            "user-b",
            "ABCDEF0123456789ABCD",
            signup_enabled,
            signup_quota,
            0,
            signup_expires_at,
        )

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
            "signupExpiresAt": None,
        }


class _FakeMediaFeishuLogin:
    def __init__(self) -> None:
        self.start_error: AccountAuthError | None = None
        self.start_intents: list[str] = []
        self._workspace_intent = "personal_web"
        self.callback_calls: list[tuple[str, str | None, str | None]] = []
        self.callback_identity = MediaFeishuIdentity("tenant-media-a", "open-a", "union-a")
        self.callback_error: AccountAuthError | None = None

    def start(self, *, workspace_intent: str = "personal_web") -> MediaFeishuLoginStart:
        if self.start_error is not None:
            raise self.start_error
        self.start_intents.append(workspace_intent)
        self._workspace_intent = workspace_intent
        return MediaFeishuLoginStart(
            authorization_url="https://accounts.feishu.cn/open-apis/authen/v1/authorize?state=test",
            expires_at="2026-08-14T12:05:00+00:00",
            maximum_age=300,
        )

    def complete_callback(
        self,
        *,
        state: str,
        code: str | None,
        error: str | None = None,
    ) -> MediaFeishuIdentity:
        self.callback_calls.append((state, code, error))
        if self.callback_error is not None:
            raise self.callback_error
        return replace(self.callback_identity, workspace_intent=self._workspace_intent)

class _Matcher:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def match(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "schemaVersion": "3",
            "pathStatus": "matched",
            "needSummary": "录入博主。",
            "routeExplanation": "用户提供了博主主页链接。",
            "guidancePlanId": "capplan_abcdefghijklmnop",
            "steps": [
                {
                    "order": 1,
                    "capabilityId": "creator_profile_upsert",
                    "variantId": "url_candidate",
                    "capabilityPath": ["account_content_map", "creator", "create"],
                    "extractedParams": {"profile_url": "https://xhslink.com/example"},
                    "confidence": 0.94,
                    "evidence": [
                        {"fieldKey": "profile_url", "quote": "https://xhslink.com/example", "source": "query"}
                    ],
                    "issues": [],
                }
            ],
            "copyProjection": "【博主-入库】",
        }


class _Gateway:
    def __init__(self) -> None:
        self.rotations = 0
        self.revocations = 0
        self.bindings: list[tuple[str, str, str]] = []

    @contextmanager
    def bind(self, tenant_id: str, task_id: str, request_root: str):
        self.bindings.append((tenant_id, task_id, request_root))
        yield

    @staticmethod
    def credential_health() -> dict[str, object]:
        return {"provider": "sub2api", "status": "active", "version": 1}

    def rotate_credential(self) -> dict[str, object]:
        self.rotations += 1
        return {"provider": "sub2api", "status": "active", "version": 2}

    def revoke_credential(self) -> dict[str, object]:
        self.revocations += 1
        return {"provider": "sub2api", "status": "retired", "version": 2}

    @staticmethod
    def balance(tenant_id: str) -> dict[str, str]:
        return {"available": "9.50000000", "reserved": "0E-8", "currency": "credit"}

    @staticmethod
    def usage(tenant_id: str, *, limit: int) -> list[dict[str, object]]:
        return [{"operationId": "60000000-0000-4000-8000-000000000010", "status": "succeeded"}]

    @staticmethod
    def reconciliation_queue(*, limit: int) -> list[dict[str, object]]:
        return [{"operationId": "60000000-0000-4000-8000-000000000011"}]

    @staticmethod
    def reconcile_operation(operation_id: str) -> dict[str, object]:
        return {"operationId": operation_id, "status": "succeeded", "charge": "0.01000000"}


class _Fulfillment:
    def __init__(self) -> None:
        self.redeem_calls: list[dict[str, object]] = []
        self.batch_calls: list[dict[str, object]] = []
        self.recovery_calls: list[str] = []
        self.refund_calls: list[dict[str, object]] = []

    def redeem(self, **kwargs: object):
        self.redeem_calls.append(kwargs)
        return SimpleNamespace(
            fulfillment_id=UUID("44444444-4444-4444-8444-444444444444"),
            plan_code="credit-100",
            credited_amount="100.00000000",
            affiliate_amount="10.00000000",
            status="succeeded",
        )

    def create_batch(self, **kwargs: object):
        self.batch_calls.append(kwargs)
        return SimpleNamespace(
            batch_id=UUID("55555555-5555-4555-8555-555555555555"),
            code_count=1,
        )

    def recover(self, fulfillment_id: str):
        self.recovery_calls.append(fulfillment_id)
        return SimpleNamespace(
            fulfillment_id=UUID(fulfillment_id),
            credited_amount="100.00000000",
            affiliate_amount="10.00000000",
            status="succeeded",
        )

    def refund(self, **kwargs: object):
        self.refund_calls.append(kwargs)
        return {
            "principalDebited": "100.00000000",
            "principalDebt": "0E-8",
            "affiliateDebited": "10.00000000",
            "affiliateDebt": "0E-8",
        }


class _RetailAdmin:
    def __init__(self) -> None:
        self.mapping_calls: list[dict[str, object]] = []
        self.grant_calls: list[dict[str, object]] = []

    @staticmethod
    def plans() -> list[dict[str, object]]:
        return [{"code": "mediaclaw-cny-1", "priceCny": "1.00", "creditAmount": "1.00000000", "purchaseAvailable": False, "purchaseUrl": None}]

    @staticmethod
    def admin_summary(*, limit: int) -> dict[str, object]:
        return {"plans": [], "mappings": [], "batches": [], "fulfillments": [], "grants": [], "limit": limit}

    def create_mapping(self, **kwargs: object) -> dict[str, object]:
        self.mapping_calls.append(kwargs)
        return {"mappingId": "77777777-7777-4777-8777-777777777777", "status": "active"}

    def grant(self, **kwargs: object) -> dict[str, str]:
        self.grant_calls.append(kwargs)
        return {"ledgerEntryId": "88888888-8888-4888-8888-888888888888", "amount": str(kwargs["amount"])}


class _CanonicalMediaBusinessServices:
    def __init__(
        self,
        account_registration: _FakeAccountRegistration,
        gateway: _Gateway,
        fulfillment: _Fulfillment,
        retail_admin: _RetailAdmin,
    ) -> None:
        self.account_registration = account_registration
        self.gateway = gateway
        self.fulfillment = fulfillment
        self.retail_admin = retail_admin

    def get_billing_balance(self, context: Any) -> dict[str, object]:
        return {"balance": self.gateway.balance(context.tenant_id)}

    def list_billing_balance_packs(self) -> dict[str, object]:
        return {"items": self.retail_admin.plans()}

    def list_billing_usage(self, context: Any, page_size: int = 10) -> dict[str, object]:
        return {"items": self.gateway.usage(context.tenant_id, limit=page_size)}

    def redeem_billing_code(
        self,
        context: Any,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        result = self.fulfillment.redeem(
            tenant_id=context.tenant_id,
            user_id=context.user_public_id,
            code=request["code"],
            idempotency_key=idempotency_key,
        )
        return {
            "fulfillment": {
                "fulfillmentId": str(result.fulfillment_id),
                "planCode": result.plan_code,
                "creditedAmount": str(result.credited_amount),
                "affiliateAmount": str(result.affiliate_amount),
                "status": result.status,
            }
        }

    def get_affiliate_profile(self, context: Any) -> dict[str, object]:
        profile = self.account_registration.affiliate_profile(UUID(context.user_public_id))
        return self.account_registration.profile_projection(profile)

    def list_invitees(self, context: Any, page: int = 1, page_size: int = 30) -> dict[str, object]:
        result = self.account_registration.invitees(
            UUID(context.user_public_id), page=page, page_size=page_size
        )
        return {
            "items": [
                {
                    "userId": str(item.user_id),
                    "username": item.username,
                    "createdAt": item.created_at.isoformat(),
                }
                for item in result.items
            ],
            "page": result.page,
            "pageSize": result.page_size,
            "total": result.total,
        }

    def get_admin_registration_policy(self, context: Any) -> dict[str, object]:
        return {"registrationPolicyMode": self.account_registration.registration_mode()}

    def list_admin_admission_batches(self, context: Any, page: int = 1, page_size: int = 30) -> dict[str, object]:
        return self.account_registration.admin_admission_batches(
            context.user_id, page=page, page_size=page_size
        )

    def list_admin_affiliate_users(
        self,
        context: Any,
        search: str = "",
        page: int = 1,
        page_size: int = 30,
    ) -> dict[str, object]:
        return self.account_registration.admin_affiliate_users(
            context.user_id, search=search, page=page, page_size=page_size
        )

    def update_admin_registration_policy(
        self,
        context: Any,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        mode = self.account_registration.admin_set_registration_policy(
            actor_user_id=context.user_id,
            actor_session_id=context.session_id,
            mode=str(request["registrationPolicyMode"]),
            reason=str(request["reason"]),
        )
        return {"registrationPolicyMode": mode}

    def update_admin_affiliate_user(
        self,
        context: Any,
        user_id: str,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        profile = self.account_registration.admin_update_affiliate_profile(
            actor_user_id=context.user_id,
            actor_session_id=context.session_id,
            target_user_id=UUID(user_id),
            signup_enabled=bool(request["signupEnabled"]),
            signup_quota=int(request["signupQuota"]),
            signup_expires_at=None,
            reason=str(request["reason"]),
        )
        return self.account_registration.profile_projection(profile)

    def get_admin_billing_summary(self, context: Any, limit: int = 100) -> dict[str, object]:
        return self.retail_admin.admin_summary(limit=limit)

    def create_admin_product_mapping(
        self,
        context: Any,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        result = self.retail_admin.create_mapping(
            actor_user_id=context.user_id,
            actor_session_id=context.session_id,
            plan_code=request["planCode"],
            external_product_id=request["externalProductId"],
            purchase_url=request["purchaseUrl"],
            reason=request["reason"],
            idempotency_key=idempotency_key,
        )
        return {"mapping": result}

    def create_admin_billing_grant(
        self,
        context: Any,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        result = self.retail_admin.grant(
            actor_user_id=context.user_id,
            actor_session_id=context.session_id,
            target_tenant_id=request["targetTenantId"],
            amount=request["amount"],
            reason=request["reason"],
            idempotency_key=idempotency_key,
        )
        return {"grant": result}

    def create_admin_redemption_batch(
        self,
        context: Any,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        result = self.fulfillment.create_batch(
            actor_user_id=context.user_id,
            plan_code=request["planCode"],
            count=request["count"],
            idempotency_key=idempotency_key,
        )
        return {"ok": True, "batchId": str(result.batch_id), "codeCount": result.code_count}

    def recover_admin_fulfillment(
        self,
        context: Any,
        fulfillment_id: str,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        result = self.fulfillment.recover(fulfillment_id)
        return {
            "ok": True,
            "result": {
                "fulfillmentId": str(result.fulfillment_id),
                "creditedAmount": str(result.credited_amount),
                "affiliateAmount": str(result.affiliate_amount),
                "status": result.status,
            },
        }

    def refund_admin_fulfillment(
        self,
        context: Any,
        fulfillment_id: str,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        result = self.fulfillment.refund(
            actor_user_id=context.user_id,
            fulfillment_id=fulfillment_id,
            reason=request["reason"],
            idempotency_key=idempotency_key,
        )
        return {"ok": True, "result": result}

    def get_admin_upstreams(self, context: Any) -> dict[str, object]:
        return {"credential": self.gateway.credential_health()}

    def reconcile_admin_billing_operation(
        self,
        context: Any,
        operation_id: str,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        return {"result": self.gateway.reconcile_operation(operation_id)}

    def rotate_admin_upstream_credential(
        self,
        context: Any,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        return {"credential": self.gateway.rotate_credential()}

    def revoke_admin_upstream_credential(
        self,
        context: Any,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, object]:
        return {"credential": self.gateway.revoke_credential()}


class HttpApiAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AuthConfig.from_environment(_auth_environment())
        self.account_auth = _FakeAccountAuth()
        self.account_registration = _FakeAccountRegistration(self.account_auth)
        self.matcher = _Matcher()
        self.gateway = _Gateway()
        self.fulfillment = _Fulfillment()
        self.retail_admin = _RetailAdmin()
        self.canonical_media_services = _CanonicalMediaBusinessServices(
            self.account_registration, self.gateway, self.fulfillment, self.retail_admin
        )
        self.media_business_services = {
            "overview": SimpleNamespace(),
            "tracks": SimpleNamespace(),
            "assets": SimpleNamespace(),
            "decisions": SimpleNamespace(),
            "runs": SimpleNamespace(),
            "publishing": SimpleNamespace(),
            "reviews": SimpleNamespace(),
            "usage_billing": self.canonical_media_services,
            "invites": self.canonical_media_services,
            "admin_overview": SimpleNamespace(),
            "admin_access": self.canonical_media_services,
            "admin_tenants": SimpleNamespace(),
            "admin_billing": self.canonical_media_services,
            "admin_upstreams": self.canonical_media_services,
            "admin_platform_cookies": SimpleNamespace(),
            "documents": SimpleNamespace(),
        }
        self.media_feishu_login = _FakeMediaFeishuLogin()
        self.media_task_root = tempfile.TemporaryDirectory()
        self.media_web_tasks = MediaWebTaskService(
            SimpleNamespace(),
            root=Path(self.media_task_root.name),
            start_worker=False,
        )
        self.server = make_server(
            "127.0.0.1",
            0,
            None,
            auth_config=self.config,
            account_auth=self.account_auth,  # type: ignore[arg-type]
            account_registration=self.account_registration,  # type: ignore[arg-type]
            media_feishu_login=self.media_feishu_login,  # type: ignore[arg-type]
            matcher=self.matcher,
            guidance_plan_service=GuidancePlanService(),
            media_web_tasks=self.media_web_tasks,
            tenant_model_gateway=self.gateway,  # type: ignore[arg-type]
            retail_admin_service=self.retail_admin,  # type: ignore[arg-type]
            retail_fulfillment_service=self.fulfillment,  # type: ignore[arg-type]
            media_business_services=self.media_business_services,
            authority_config=HttpAuthorityConfig(
                public_origin="http://127.0.0.1",
            ),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.media_web_tasks.close()
        self.media_task_root.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        cookie: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any] | None, dict[str, str]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        request_headers = dict(headers or {})
        body = json.dumps(payload).encode() if payload is not None else None
        if body is not None:
            request_headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        if cookie:
            request_headers["Cookie"] = cookie
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, json.loads(raw) if raw else None, response_headers

    def _issue_session_cookie(self, username: str = "user-a", *, previous_cookie: str | None = None) -> str:
        previous_token = previous_cookie.split("=", 1)[1] if previous_cookie else None
        login = self.account_auth.issue_test_session(username, previous_token=previous_token)
        return f"openclaw_session={login.token}"

    def _csrf_headers(self, cookie: str, *, key: str | None = None) -> dict[str, str]:
        token = cookie.split("=", 1)[1]
        headers = {
            "Origin": "http://127.0.0.1",
            "X-OpenClaw-CSRF": self.account_auth.csrf_token(token),
        }
        if key:
            headers["Idempotency-Key"] = key
        return headers

    def test_a_b_and_admin_test_sessions_have_distinct_uuid_tenants(self) -> None:
        for username, expected_user, expected_tenant, role in (
            ("user-a", USER_A, TENANT_A, "user"),
            ("user-b", USER_B, TENANT_B, "user"),
            ("admin", ADMIN, ADMIN_TENANT, "admin"),
        ):
            cookie = self._issue_session_cookie(username)
            status, body, _ = self._request("GET", "/openclaw/media/api/session", cookie=cookie)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["session"]["publicUserId"], str(expected_user))
            self.assertEqual(body["session"]["role"], "ordinary" if role == "user" else "admin")

    def test_legacy_session_cookie_keeps_last_value_precedence(self) -> None:
        first = self._issue_session_cookie("user-a")
        second = self._issue_session_cookie("user-b")
        status, body, _ = self._request(
            "GET",
            "/openclaw/media/api/session",
            cookie=f"{first}; {second}",
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["session"]["publicUserId"], str(USER_B))

    def test_legacy_session_cookie_keeps_simplecookie_blank_cleanup(self) -> None:
        cookie = self._issue_session_cookie("user-a")
        token = cookie.split("=", 1)[1]
        status, body, _ = self._request(
            "GET",
            "/openclaw/media/api/session",
            cookie=f"openclaw_session= {token} ",
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["session"]["publicUserId"], str(USER_A))

    def test_feishu_start_returns_only_same_browser_authorization_data(self) -> None:
        status, body, _ = self._request("POST", "/auth/feishu/start", {})
        self.assertEqual(status, 200, body)
        self.assertEqual(
            set(body),
            {"ok", "authorizationUrl", "expiresAt", "maximumAge"},
        )
        self.assertNotIn("attemptToken", body)
        self.assertNotIn("bindingToken", body)
        self.assertEqual(self.media_feishu_login.start_intents, ["personal_web"])

    def test_organization_feishu_start_binds_intent_through_callback(self) -> None:
        status, body, _ = self._request(
            "POST", "/auth/feishu/start", {"workspaceIntent": "organization_lark"}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(self.media_feishu_login.start_intents, ["organization_lark"])

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.request("GET", "/auth/feishu/callback?state=m_state&code=code")
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 303)
        connection.close()
        self.assertEqual(self.account_auth.feishu_login_intents, ["organization_lark"])

    def test_feishu_start_rejects_unknown_workspace_intent(self) -> None:
        status, body, _ = self._request("POST", "/auth/feishu/start", {"workspaceIntent": "admin"})
        self.assertEqual(status, 400, body)
        self.assertEqual(body["error"]["code"], "invalid_request")
        self.assertEqual(self.media_feishu_login.start_intents, [])

        status, body, _ = self._request("POST", "/auth/feishu/start", {"workspaceIntent": {}})
        self.assertEqual(status, 400, body)
        self.assertEqual(body["error"]["code"], "invalid_request")
        self.assertEqual(self.media_feishu_login.start_intents, [])

    def test_feishu_callback_issues_cookie_and_redirects_to_mediaclaw(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.request("GET", "/auth/feishu/callback?state=m_state&code=code")
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 303)
        self.assertEqual(response.getheader("Location"), "/openclaw/media/overview")
        cookie = response.getheader("Set-Cookie", "")
        self.assertIn("openclaw_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        connection.close()
        self.assertEqual(self.media_feishu_login.callback_calls, [("m_state", "code", None)])

    def test_feishu_callback_failure_shows_specific_code_and_no_cookie(self) -> None:
        self.media_feishu_login.callback_error = AccountAuthError(
            "feishu_account_unlinked",
            "该飞书账号尚未绑定 MediaClaw 账户。",
            status=403,
        )
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.request("GET", "/auth/feishu/callback?state=m_state&code=code")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        self.assertEqual(response.status, 403)
        self.assertIn("该飞书账号尚未绑定 MediaClaw 账户。", body)
        self.assertIn("技术参考码：feishu_account_unlinked", body)
        self.assertNotIn("错误码：", body)
        self.assertIn("该飞书账号尚未绑定 MediaClaw 账户", body)
        self.assertNotIn("Company OS", body)
        self.assertIsNone(response.getheader("Set-Cookie"))
        connection.close()

    def test_retired_feishu_polling_route_is_not_found(self) -> None:
        status, body, headers = self._request("POST", "/auth/feishu/status", {})
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "not_found")
        self.assertNotIn("set-cookie", headers)

    def test_media_feishu_unavailable_does_not_enable_password_fallback(self) -> None:
        self.media_feishu_login.start_error = AccountAuthError(
            "feishu_login_unavailable",
            "飞书登录暂时不可用，请稍后重试。",
            status=503,
        )
        status, body, _ = self._request("POST", "/auth/feishu/start", {})
        self.assertEqual(status, 503, body)
        self.assertEqual(body["error"]["code"], "feishu_login_unavailable")

        for method, path, payload in (
            ("POST", "/auth/login", {"username": "user-a", "password": "unused"}),
            ("PUT", "/auth/password", {"oldPassword": "unused", "newPassword": "unused"}),
        ):
            status, body, headers = self._request(method, path, payload)
            self.assertEqual(status, 404, body)
            self.assertEqual(body["error"]["code"], "not_found")
            self.assertNotIn("set-cookie", headers)

    def test_retired_password_login_and_database_failure_are_fail_closed(self) -> None:
        status, body, headers = self._request("POST", "/auth/login", {"username": "user-a", "password": "unused"})
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "not_found")
        self.assertNotIn("set-cookie", headers)
        self.account_auth.database_down = True
        status, body, _ = self._request("GET", "/openclaw/media/api/session", cookie="openclaw_session=opaque")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "account_database_unavailable")

    def test_direct_session_rotation_and_expiry_fail_closed(self) -> None:
        first = self._issue_session_cookie()
        second = self._issue_session_cookie(previous_cookie=first)
        status, _, _ = self._request("GET", "/openclaw/media/api/session", cookie=first)
        self.assertEqual(status, 401)
        token = second.split("=", 1)[1]
        self.account_auth.sessions[token] = replace(
            self.account_auth.sessions[token], expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        status, _, _ = self._request("GET", "/openclaw/media/api/session", cookie=second)
        self.assertEqual(status, 401)

    def test_stale_session_cookie_is_refused_after_authentication_rotation(self) -> None:
        stale_cookie = self._issue_session_cookie()
        current_cookie = self._issue_session_cookie(previous_cookie=stale_cookie)

        status, body, _ = self._request("GET", "/openclaw/media/api/session", cookie=stale_cookie)

        self.assertEqual(status, 401, body)
        self.assertEqual(body["error"]["code"], "authentication_required")
        current_status, current_body, _ = self._request(
            "GET", "/openclaw/media/api/session", cookie=current_cookie
        )
        self.assertEqual(current_status, 200, current_body)

    def test_csrf_same_origin_and_logout_revoke_are_enforced(self) -> None:
        cookie = self._issue_session_cookie()
        payload = {
            "query": "录入博主",
            "currentBot": "media",
            "catalogVersion": CAPABILITY_REGISTRY.catalog_version,
            "idempotencyKey": "match-auth-test",
        }
        status, body, _ = self._request(
            "POST", "/openclaw/media/api/capability-match", payload, cookie=cookie,
            headers={"Idempotency-Key": "match-auth-test"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "csrf_rejected")
        status, body, _ = self._request(
            "POST", "/openclaw/media/api/capability-match", payload, cookie=cookie,
            headers=self._csrf_headers(cookie, key="match-auth-test"),
        )
        self.assertEqual(status, 200, body)
        scope = "capability-match-" + hashlib.sha256(b"match-auth-test").hexdigest()[:32]
        self.assertEqual(self.gateway.bindings, [(str(TENANT_A), scope, scope)])
        status, _, _ = self._request(
            "POST", "/auth/logout", {}, cookie=cookie,
            headers=self._csrf_headers(cookie, key="logout-auth-test"),
        )
        self.assertEqual(status, 200)
        status, _, _ = self._request("GET", "/openclaw/media/api/session", cookie=cookie)
        self.assertEqual(status, 401)

    def test_deletion_preview_http_contract_and_idempotent_replay(self) -> None:
        cookie = self._issue_session_cookie()
        idempotency_key = "delete-preview-http-contract-0001"
        payload = {
            "schemaVersion": "3",
            "capabilityId": "universal_deletion",
            "variantId": "preview",
            "params": {"id": "asset_0123456789abcdef"},
            "uploadIds": [],
            "idempotencyKey": idempotency_key,
            "catalogVersion": CAPABILITY_REGISTRY.catalog_version,
            "initiation": "manual",
            "confirmationReceipt": None,
        }
        headers = self._csrf_headers(cookie, key=idempotency_key)

        first_status, first, _ = self._request(
            "POST", "/openclaw/media/api/tasks", payload, cookie=cookie, headers=headers,
        )
        replay_status, replay, _ = self._request(
            "POST", "/openclaw/media/api/tasks", payload, cookie=cookie, headers=headers,
        )

        self.assertEqual(first_status, 202, first)
        self.assertEqual(replay_status, 200, replay)
        self.assertEqual(first["taskId"], replay["taskId"])
        self.assertEqual(first["status"], "queued")

    def test_admin_role_is_reread_and_normal_user_gets_403(self) -> None:
        user_cookie = self._issue_session_cookie()
        status, body, _ = self._request(
            "GET", f"/openclaw/media/api/admin/dashboard?targetTenantId={TENANT_B}", cookie=user_cookie
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "admin_required")
        admin_cookie = self._issue_session_cookie("admin")
        self.account_auth.roles[ADMIN] = "user"
        admin_token = admin_cookie.split("=", 1)[1]
        self.account_auth.sessions[admin_token] = replace(
            self.account_auth.sessions[admin_token], is_maintainer=False
        )
        status, body, _ = self._request(
            "GET", f"/openclaw/media/api/admin/dashboard?targetTenantId={TENANT_B}", cookie=admin_cookie
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "admin_required")

    def test_upstream_credential_admin_api_is_redacted_and_csrf_protected(self) -> None:
        user_cookie = self._issue_session_cookie()
        status, body, _ = self._request("GET", "/openclaw/media/api/admin/upstreams", cookie=user_cookie)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "admin_required")

        admin_cookie = self._issue_session_cookie("admin")
        status, body, _ = self._request(
            "GET", "/openclaw/media/api/admin/upstreams", cookie=admin_cookie
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(body["credential"]), {"provider", "status", "version"})
        encoded = json.dumps(body)
        self.assertNotIn("secret", encoded.lower())
        self.assertNotIn("key", encoded.lower())

        status, body, _ = self._request(
            "POST", "/openclaw/media/api/admin/upstream-credential/rotate", {}, cookie=admin_cookie
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "csrf_rejected")
        self.assertEqual(self.gateway.rotations, 0)

        status, body, _ = self._request(
            "POST",
            "/openclaw/media/api/admin/upstream-credential/rotate",
            {},
            cookie=admin_cookie,
            headers=self._csrf_headers(admin_cookie, key="rotate-http-test"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["credential"], {"provider": "sub2api", "status": "active", "version": 2})
        self.assertEqual(self.gateway.rotations, 1)

        status, body, _ = self._request(
            "POST",
            "/openclaw/media/api/admin/upstream-credential/revoke",
            {},
            cookie=admin_cookie,
            headers=self._csrf_headers(admin_cookie, key="revoke-http-test"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["credential"]["status"], "retired")
        self.assertEqual(self.gateway.revocations, 1)

    def test_billing_reads_are_tenant_scoped_and_admin_queue_rejects_users(self) -> None:
        user_cookie = self._issue_session_cookie()
        status, body, _ = self._request("GET", "/openclaw/media/api/billing/balance", cookie=user_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(body["balance"]["currency"], "credit")
        status, body, _ = self._request("GET", "/openclaw/media/api/billing/usage?pageSize=10", cookie=user_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["items"]), 1)
        status, body, _ = self._request(
            "GET", "/openclaw/media/api/admin/billing/summary?limit=10", cookie=user_cookie
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "admin_required")
        admin_cookie = self._issue_session_cookie("admin")
        status, body, _ = self._request(
            "GET", "/openclaw/media/api/admin/billing/summary?limit=10", cookie=admin_cookie
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["limit"], 10)
        operation_id = "60000000-0000-4000-8000-000000000011"
        status, body, _ = self._request(
            "POST",
            f"/openclaw/media/api/admin/billing/reconciliation/{operation_id}",
            {},
            cookie=admin_cookie,
            headers=self._csrf_headers(admin_cookie, key="reconcile-http-test"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["status"], "succeeded")

    def test_retail_plan_and_admin_finance_api_use_canonical_contracts(self) -> None:
        user_cookie = self._issue_session_cookie()
        status, body, _ = self._request("GET", "/openclaw/media/api/billing/balance-packs", cookie=user_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["items"][0]["code"], "mediaclaw-cny-1")

        admin_cookie = self._issue_session_cookie("admin")
        status, body, _ = self._request("GET", "/openclaw/media/api/admin/billing/summary?limit=30", cookie=admin_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["limit"], 30)

        mapping = {
            "planCode": "mediaclaw-cny-1",
            "externalProductId": "liandong-product-1",
            "purchaseUrl": "https://www.ldxp.cn/goods/1",
            "reason": "publish canonical product",
        }
        status, body, _ = self._request(
            "POST", "/openclaw/media/api/admin/billing/product-mappings", mapping, cookie=admin_cookie,
            headers=self._csrf_headers(admin_cookie, key="mapping-http-test"),
        )
        self.assertEqual(status, 201, body)
        self.assertEqual(self.retail_admin.mapping_calls[0]["actor_user_id"], ADMIN)
        self.assertEqual(self.retail_admin.mapping_calls[0]["actor_session_id"], self.account_auth.resolve_session(admin_cookie.split("=", 1)[1]).session_id)

        grant = {"targetTenantId": str(TENANT_A), "amount": "10.00000000", "reason": "operator test credit"}
        status, body, _ = self._request(
            "POST", "/openclaw/media/api/admin/billing/grants", grant, cookie=admin_cookie,
            headers=self._csrf_headers(admin_cookie, key="grant-http-test"),
        )
        self.assertEqual(status, 201, body)
        self.assertEqual(self.retail_admin.grant_calls[0]["target_tenant_id"], str(TENANT_A))
        self.assertEqual(self.retail_admin.grant_calls[0]["amount"], "10.00000000")

    def test_retail_fulfillment_uses_session_subject_and_admin_controls(self) -> None:
        user_cookie = self._issue_session_cookie()
        status, body, _ = self._request(
            "POST", "/openclaw/media/api/billing/redeem", {"code": "OC-submitted-once"}, cookie=user_cookie
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "csrf_rejected")
        self.assertEqual(self.fulfillment.redeem_calls, [])

        status, body, _ = self._request(
            "POST",
            "/openclaw/media/api/billing/redeem",
            {"code": "OC-submitted-once"},
            cookie=user_cookie,
            headers=self._csrf_headers(user_cookie, key="redeem-http-test"),
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(
            self.fulfillment.redeem_calls,
            [{
                "tenant_id": str(TENANT_A),
                "user_id": str(USER_A),
                "code": "OC-submitted-once",
                "idempotency_key": "redeem-http-test",
            }],
        )
        self.assertEqual(body["fulfillment"]["status"], "succeeded")

        batch_payload = {"planCode": "mediaclaw-cny-100", "count": 1}
        status, body, _ = self._request(
            "POST", "/openclaw/media/api/admin/billing/redemption-batches", batch_payload, cookie=user_cookie,
            headers=self._csrf_headers(user_cookie, key="batch-http-test"),
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "admin_required")

        admin_cookie = self._issue_session_cookie("admin")
        status, body, _ = self._request(
            "POST", "/openclaw/media/api/admin/billing/redemption-batches", batch_payload, cookie=admin_cookie,
            headers=self._csrf_headers(admin_cookie, key="batch-http-test"),
        )
        self.assertEqual(status, 201, body)
        self.assertEqual(
            body,
            {"ok": True, "batchId": "55555555-5555-4555-8555-555555555555", "codeCount": 1},
        )
        self.assertNotIn("codes", body)
        self.assertEqual(self.fulfillment.batch_calls[0]["actor_user_id"], ADMIN)

        fulfillment_id = "44444444-4444-4444-8444-444444444444"
        status, body, _ = self._request(
            "POST", f"/openclaw/media/api/admin/billing/fulfillments/{fulfillment_id}/recover", {},
            cookie=admin_cookie, headers=self._csrf_headers(admin_cookie, key="recover-http-test"),
        )
        self.assertEqual(status, 200, body)
        status, body, _ = self._request(
            "POST", f"/openclaw/media/api/admin/billing/fulfillments/{fulfillment_id}/refund",
            {"reason": "customer refund"}, cookie=admin_cookie,
            headers=self._csrf_headers(admin_cookie, key="refund-http-test"),
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(self.fulfillment.refund_calls[0]["actor_user_id"], ADMIN)

    def test_retired_password_change_route_does_not_mutate_session(self) -> None:
        cookie = self._issue_session_cookie()
        key = "password-change-test"
        status, body, headers = self._request(
            "PUT", "/auth/password",
            {"oldPassword": "password-for-user-a", "newPassword": "new-password-for-user-a", "idempotencyKey": key},
            cookie=cookie, headers=self._csrf_headers(cookie, key=key),
        )
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "not_found")
        self.assertNotIn("set-cookie", headers)
        status, _, _ = self._request("GET", "/openclaw/media/api/session", cookie=cookie)
        self.assertEqual(status, 200)

    def test_registration_policy_and_register_use_the_only_openclaw_entrypoint(self) -> None:
        status, body, _ = self._request("GET", "/auth/registration-policy")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"registrationPolicyMode": "controlled"})
        payload = {
            "username": "new-user",
            "email": "new-user@example.com",
            "password": "new-user-password",
            "affiliateCode": "ABCDEF0123456789ABCD",
        }
        status, body, headers = self._request("POST", "/auth/register", payload)
        self.assertEqual(status, 201, body)
        self.assertTrue(body["ok"])
        self.assertEqual(body["userId"], str(USER_B))
        self.assertEqual(body["tenantId"], str(TENANT_B))
        self.assertEqual(body["inviterUserId"], str(USER_A))
        self.assertEqual(self.account_registration.registration_calls, [{
            "username": "new-user",
            "email": "new-user@example.com",
            "password": "new-user-password",
            "admission_code": None,
            "affiliate_code": "ABCDEF0123456789ABCD",
            "tenant_type": "personal",
            "workspace_mode": None,
            "body_authority": None,
            "display_name": None,
            "organization_name": None,
        }])
        cookie = headers["set-cookie"].split(";", 1)[0]
        status, session, _ = self._request("GET", "/openclaw/media/api/session", cookie=cookie)
        self.assertEqual(status, 200, session)
        self.assertEqual(session["session"]["publicUserId"], str(USER_B))

    def test_register_maps_frontend_b_and_c_tenant_fields(self) -> None:
        cases = (
            ("personal", "personal_web", "internal", "个人工作台", ""),
            ("organization", "organization_lark", "lark", "机构管理员", "示例机构"),
        )
        for tenant_type, workspace_mode, body_authority, display_name, organization_name in cases:
            with self.subTest(tenant_type=tenant_type):
                payload = {
                    "username": f"{tenant_type}-user",
                    "email": f"{tenant_type}@example.com",
                    "password": f"{tenant_type}-password",
                    "admissionCode": f"OC-{tenant_type}",
                    "affiliateCode": "",
                    "tenantType": tenant_type,
                    "workspaceMode": workspace_mode,
                    "bodyAuthority": body_authority,
                    "displayName": display_name,
                    "organizationName": organization_name,
                }
                status, body, _ = self._request("POST", "/auth/register", payload)
                self.assertEqual(status, 201, body)
                self.assertTrue(body["ok"])
                self.assertEqual(self.account_registration.registration_calls[-1], {
                    "username": payload["username"],
                    "email": payload["email"],
                    "password": payload["password"],
                    "admission_code": payload["admissionCode"],
                    "affiliate_code": "",
                    "tenant_type": tenant_type,
                    "workspace_mode": workspace_mode,
                    "body_authority": body_authority,
                    "display_name": display_name,
                    "organization_name": organization_name,
                })

    def test_invitation_reads_are_self_scoped_and_admin_reads_reject_users(self) -> None:
        user_cookie = self._issue_session_cookie()
        status, body, _ = self._request("GET", "/openclaw/media/api/account/affiliate", cookie=user_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["userId"], str(USER_A))
        status, body, _ = self._request("GET", "/openclaw/media/api/account/invitees?page=1&page_size=30", cookie=user_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["items"][0]["userId"], str(USER_B))
        for path in (
            "/openclaw/media/api/admin/registration-policy",
            "/openclaw/media/api/admin/admission-batches",
            "/openclaw/media/api/admin/affiliate-users",
        ):
            status, body, _ = self._request("GET", path, cookie=user_cookie)
            self.assertEqual(status, 403, (path, body))
            self.assertEqual(body["error"]["code"], "admin_required")

    def test_admin_registration_mutations_require_csrf_and_use_uuid_targets(self) -> None:
        admin_cookie = self._issue_session_cookie("admin")
        payload = {"registrationPolicyMode": "open", "reason": "approved rollout"}
        status, body, _ = self._request(
            "PUT", "/openclaw/media/api/admin/registration-policy", payload, cookie=admin_cookie,
            headers={"Idempotency-Key": "policy-without-csrf"},
        )
        self.assertEqual(status, 403, body)
        status, body, _ = self._request(
            "PUT", "/openclaw/media/api/admin/registration-policy", payload, cookie=admin_cookie,
            headers=self._csrf_headers(admin_cookie, key="policy-open"),
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"registrationPolicyMode": "open"})
        profile_payload = {
            "signupEnabled": True,
            "signupQuota": 2,
            "signupExpiresAt": None,
            "reason": "approved quota",
        }
        status, body, _ = self._request(
            "PUT", f"/openclaw/media/api/admin/affiliate-users/{USER_B}", profile_payload,
            cookie=admin_cookie,
            headers=self._csrf_headers(admin_cookie, key="affiliate-user-b"),
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["userId"], str(USER_B))
        self.assertEqual(self.account_registration.profile_updates[-1], (ADMIN, USER_B))

    def test_retired_identity_routes_are_not_reachable(self) -> None:
        for method, path in (
            ("POST", "/auth/login/2fa"),
            ("GET", "/media/api/account/profile"),
            ("GET", "/media/api/admin/users/7"),
        ):
            status, _, _ = self._request(method, path, {} if method == "POST" else None)
            self.assertEqual(status, 404, (method, path))

class AuthConfigTests(unittest.TestCase):
    def test_session_cookie_security_attributes_are_explicit(self) -> None:
        handler = OpenClawHttpHandler.__new__(OpenClawHttpHandler)
        handler.auth_config = AuthConfig(b"s" * 48, cookie_secure=True)

        header = handler._session_cookie("opaque-session-token", 3600)

        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Lax", header)
        self.assertIn("Secure", header)
        self.assertNotIn("Domain=", header)

    def test_qa_credentials_are_rejected_from_canonical_auth_file(self) -> None:
        invalid_lines = (
            "OPENCLAW_MEDIA_QA_EMAIL=qa@example.test\n",
            "OPENCLAW_MEDIA_QA_PASSWORD=qa-password\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            auth_path = Path(directory) / "auth.env"
            for invalid_line in invalid_lines:
                with self.subTest(invalid_line=invalid_line.split("=", 1)[0]):
                    auth_path.write_text(invalid_line, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_auth_environment(auth_path, {})

    def test_auth_file_still_rejects_undeclared_keys_and_unterminated_quotes(self) -> None:
        invalid_lines = (
            "UNDECLARED_AUTH_SETTING=value\n",
            "OPENCLAW_ACCOUNT_SESSION_SECRET='unterminated\n",
            'OPENCLAW_ACCOUNT_SESSION_SECRET="unterminated\n',
        )
        with tempfile.TemporaryDirectory() as directory:
            auth_path = Path(directory) / "auth.env"
            for invalid_line in invalid_lines:
                with self.subTest(invalid_line=invalid_line.split("=", 1)[0]):
                    auth_path.write_text(invalid_line, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_auth_environment(auth_path, {})

    def test_only_canonical_account_auth_environment_is_accepted(self) -> None:
        values = load_auth_environment(None, _auth_environment())
        config = AuthConfig.from_environment(values)
        self.assertEqual(config.cookie_name, "openclaw_session")
        for retired in (
            "OPENCLAW_BFF_SESSION_DB_PATH",
            "OPENCLAW_BFF_TOKEN_ENCRYPTION_KEY",
            "OPENCLAW_BOT_CENTER_USERNAME",
        ):
            self.assertNotIn(retired, values)

    def test_mutation_binding_rejects_payload_reuse(self) -> None:
        bindings = MutationIdempotencyBindings(maximum_entries=10, ttl_seconds=60)
        self.assertTrue(bindings.bind(str(USER_A), "password", "key", {"value": 1}))
        self.assertFalse(bindings.bind(str(USER_A), "password", "key", {"value": 2}))

    def test_session_ttl_defaults_to_twenty_eight_days_when_unset(self) -> None:
        environment = _auth_environment()
        del environment["OPENCLAW_ACCOUNT_SESSION_TTL_SECONDS"]
        config = AuthConfig.from_environment(environment)
        self.assertEqual(config.session_ttl_seconds, 28 * 24 * 60 * 60)

    def test_session_ttl_accepts_exactly_twenty_eight_days(self) -> None:
        environment = _auth_environment()
        environment["OPENCLAW_ACCOUNT_SESSION_TTL_SECONDS"] = str(28 * 24 * 60 * 60)
        config = AuthConfig.from_environment(environment)
        self.assertEqual(config.session_ttl_seconds, 28 * 24 * 60 * 60)

    def test_session_ttl_beyond_twenty_eight_days_is_rejected(self) -> None:
        environment = _auth_environment()
        environment["OPENCLAW_ACCOUNT_SESSION_TTL_SECONDS"] = str(28 * 24 * 60 * 60 + 1)
        with self.assertRaises(ValueError):
            AuthConfig.from_environment(environment)

    def test_session_ttl_prior_ceilings_no_longer_the_limit(self) -> None:
        # Regression guard: the ceiling moved 7 days -> 14 days -> 28 days
        # across successive requests; confirms both older values are still
        # accepted under the current (wider) ceiling rather than the bound
        # check having been narrowed back down by accident.
        for prior_ceiling in (7 * 24 * 60 * 60, 14 * 24 * 60 * 60):
            with self.subTest(prior_ceiling=prior_ceiling):
                environment = _auth_environment()
                environment["OPENCLAW_ACCOUNT_SESSION_TTL_SECONDS"] = str(prior_ceiling)
                config = AuthConfig.from_environment(environment)
                self.assertEqual(config.session_ttl_seconds, prior_ceiling)

    def test_organization_and_personal_feishu_logins_share_one_session_ttl(self) -> None:
        # login_verified_feishu_identity's workspace_intent only changes
        # which credential lookup/error branch runs; both "organization_lark"
        # and "personal_web" converge on the same issue_session_for_account
        # call, so there is exactly one session-duration setting to tune,
        # not two independently-drifting ones.
        config = AuthConfig.from_environment(_auth_environment())
        self.assertIn("session_ttl_seconds", AccountAuthService.__init__.__code__.co_varnames)
        service = AccountAuthService(
            object(), csrf_secret=b"s" * 32, session_ttl_seconds=config.session_ttl_seconds  # type: ignore[arg-type]
        )
        self.assertEqual(service._session_ttl_seconds, config.session_ttl_seconds)


class ProductContractResolutionTests(unittest.TestCase):
    """Regression coverage for the H11 fix to _http_product_operations().

    Before the fix, OPENCLAW_MEDIA_GENERATED_CONTRACT was silently ignored
    here (a hardcoded /home/ubuntu/... path was tried instead), so an
    override could never take effect.
    """

    def test_http_product_operations_honors_generated_contract_env_override(self) -> None:
        from openclaw_app.adapters import http_api as http_api_module

        missing_override = "/nonexistent/openclaw-media-generated-contract-override.py"
        http_api_module._http_product_operations.cache_clear()
        self.addCleanup(http_api_module._http_product_operations.cache_clear)
        previous = os.environ.get("OPENCLAW_MEDIA_GENERATED_CONTRACT")
        os.environ["OPENCLAW_MEDIA_GENERATED_CONTRACT"] = missing_override
        try:
            with self.assertRaises(RuntimeError) as raised:
                http_api_module._http_product_operations()
        finally:
            if previous is None:
                os.environ.pop("OPENCLAW_MEDIA_GENERATED_CONTRACT", None)
            else:
                os.environ["OPENCLAW_MEDIA_GENERATED_CONTRACT"] = previous

        message = str(raised.exception)
        self.assertIn(missing_override, message)
        self.assertNotIn("/home/ubuntu", message)

    def test_http_product_operations_resolves_from_repository_without_overrides(self) -> None:
        from openclaw_app.adapters import http_api as http_api_module

        http_api_module._http_product_operations.cache_clear()
        self.addCleanup(http_api_module._http_product_operations.cache_clear)
        previous = os.environ.pop("OPENCLAW_MEDIA_GENERATED_CONTRACT", None)
        try:
            operations = http_api_module._http_product_operations()
        finally:
            if previous is not None:
                os.environ["OPENCLAW_MEDIA_GENERATED_CONTRACT"] = previous

        self.assertIn("archive_commit", operations)


if __name__ == "__main__":
    unittest.main()
