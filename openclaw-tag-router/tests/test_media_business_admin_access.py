from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from openclaw_app.services.media_business.admin_access import (
    AdminAccessContext,
    AdminAccessForbidden,
    AdminAccessIdempotencyConflict,
    AdminAccessInvalidRequest,
    AdminAccessRevisionConflict,
    AdminAccessService,
)


UTC = timezone.utc
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000001")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
BATCH_ID = UUID("00000000-0000-0000-0000-000000000004")
CREATED_BATCH_ID = UUID("00000000-0000-0000-0000-000000000005")


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeStorage:
    def __init__(self):
        self.now = datetime(2026, 8, 5, 4, 0, tzinfo=UTC)
        self.user_row = (
            USER_ID,
            "alice",
            True,
            10,
            2,
            "active",
            self.now,
            self.now,
        )
        self.batch_row = (
            BATCH_ID,
            "spring",
            "active",
            4,
            1,
            self.now,
            None,
        )
        self.policy_row = ("controlled", self.now)
        self.created_batch_row = None
        self.idempotency = {}
        self.audits = []
        self.mutations = 0
        self.revoked_sessions = 0
        self.require_admin_calls = 0

    def require_admin(self, connection, context, now):
        self.require_admin_calls += 1
        if context.actor_user_id != ADMIN_ID or context.actor_session_id != SESSION_ID:
            raise AdminAccessForbidden()

    def find_idempotency(self, connection, actor_user_id, operation, key):
        return self.idempotency.get((actor_user_id, operation, key))

    def save_audit(self, connection, **record):
        self.audits.append(record)
        metadata = record["metadata"]
        if "idempotencyKey" in metadata:
            self.idempotency[(record["actorUserId"], record["operation"], metadata["idempotencyKey"])] = metadata

    def affiliate_users(self, connection, *, search, position, limit):
        if search and search not in self.user_row[1]:
            return []
        return [self.user_row][:limit]

    def affiliate_user(self, connection, user_id, *, lock):
        return self.user_row if user_id == USER_ID else None

    def update_affiliate_user(self, connection, *, user_id, affiliate_enabled, invitation_quota):
        assert user_id == USER_ID
        self.mutations += 1
        self.user_row = (
            USER_ID,
            "alice",
            affiliate_enabled,
            invitation_quota,
            self.user_row[4],
            "active",
            self.now.replace(microsecond=self.now.microsecond + 1),
            self.user_row[7],
        )
        return self.user_row

    def admission_batches(self, connection, *, position, limit):
        rows = [row for row in (self.created_batch_row, self.batch_row) if row is not None]
        return rows[:limit]

    def admission_batch(self, connection, batch_id, *, lock):
        if batch_id == CREATED_BATCH_ID:
            return self.created_batch_row
        return self.batch_row if batch_id == BATCH_ID else None

    def update_admission_batch_disabled(self, connection, *, batch_id):
        assert batch_id == BATCH_ID
        self.mutations += 1
        self.batch_row = (
            BATCH_ID,
            "spring",
            "disabled",
            4,
            1,
            self.now,
            self.now.replace(microsecond=self.now.microsecond + 1),
        )
        return self.batch_row

    def registration_policy(self, connection, *, lock):
        return self.policy_row

    def update_registration_policy(self, connection, *, mode, actor_user_id, reason):
        assert actor_user_id == ADMIN_ID
        assert reason
        self.mutations += 1
        stored_mode = "controlled" if mode == "invite_only" else mode
        self.policy_row = (stored_mode, self.now.replace(microsecond=self.now.microsecond + 1))
        return self.policy_row

    def revoke_user_sessions(self, connection, *, user_id):
        assert user_id == USER_ID
        self.revoked_sessions += 2
        return self.revoked_sessions


class FakeRegistrationService:
    def __init__(self, storage):
        self.storage = storage
        self.calls = 0

    def admin_create_admission_batch(self, **kwargs):
        self.calls += 1
        self.storage.created_batch_row = (
            CREATED_BATCH_ID,
            kwargs["name"],
            "active",
            kwargs["code_count"],
            0,
            self.storage.now,
            None,
        )
        return SimpleNamespace(batch_id=CREATED_BATCH_ID)


def make_service(storage: FakeStorage | None = None) -> tuple[AdminAccessService, FakeStorage]:
    storage = storage or FakeStorage()
    registration_service = FakeRegistrationService(storage)
    service = AdminAccessService(
        lambda: FakeConnection(),
        public_id_secret=b"public-id-secret-0123456789",
        cursor_secret=b"cursor-secret-0123456789",
        storage=storage,
        registration_service=registration_service,
        now=lambda: storage.now,
    )
    service.registration_service_for_test = registration_service
    return service, storage


def admin_context() -> AdminAccessContext:
    return AdminAccessContext(actor_user_id=ADMIN_ID, actor_session_id=SESSION_ID)


def test_admin_lists_project_opaque_ids_and_rejects_tampered_cursor():
    service, _ = make_service()

    response = service.list_admin_affiliate_users(admin_context(), page_size=1)

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["items"][0]["publicUserId"] != str(USER_ID)
    assert response["items"][0]["displayName"] == "alice"
    assert response["items"][0]["affiliateEnabled"] is True
    assert response["items"][0]["invitationQuota"] == 10
    assert response["items"][0]["usedQuota"] == 2
    assert response["nextCursor"] is None

    with pytest.raises(AdminAccessInvalidRequest):
        service.list_admin_affiliate_users(admin_context(), cursor="tampered", page_size=1)


def test_non_admin_context_is_rejected_before_database_access():
    service, storage = make_service()
    context = AdminAccessContext(
        actor_user_id=ADMIN_ID,
        actor_session_id=SESSION_ID,
        role="user",
    )

    with pytest.raises(AdminAccessForbidden):
        service.list_admin_affiliate_users(context)

    assert storage.require_admin_calls == 0


def test_update_requires_reason_revision_and_replays_idempotently():
    service, storage = make_service()
    context = admin_context()
    initial = service.list_admin_affiliate_users(context)
    public_user_id = initial["items"][0]["publicUserId"]
    expected_revision = initial["revision"]

    with pytest.raises(AdminAccessInvalidRequest):
        service.update_admin_affiliate_user(
            context,
            public_user_id,
            affiliate_enabled=False,
            invitation_quota=12,
            reason=" ",
            expected_revision=expected_revision,
            idempotency_key="admin-user-update-1",
        )

    result = service.update_admin_affiliate_user(
        context,
        public_user_id,
        affiliate_enabled=False,
        invitation_quota=12,
        reason="运营策略调整",
        expected_revision=expected_revision,
        idempotency_key="admin-user-update-1",
    )
    assert result["user"]["affiliateEnabled"] is False
    assert result["user"]["invitationQuota"] == 12
    assert len(storage.audits) == 1

    replay = service.update_admin_affiliate_user(
        context,
        public_user_id,
        affiliate_enabled=False,
        invitation_quota=12,
        reason="运营策略调整",
        expected_revision=expected_revision,
        idempotency_key="admin-user-update-1",
    )
    assert replay == result
    assert storage.mutations == 1

    with pytest.raises(AdminAccessIdempotencyConflict):
        service.update_admin_affiliate_user(
            context,
            public_user_id,
            affiliate_enabled=True,
            invitation_quota=12,
            reason="运营策略调整",
            expected_revision=expected_revision,
            idempotency_key="admin-user-update-1",
        )


def test_stale_revision_does_not_write_and_policy_uses_if2_modes():
    service, storage = make_service()
    context = admin_context()
    initial = service.list_admin_affiliate_users(context)
    public_user_id = initial["items"][0]["publicUserId"]

    service.update_admin_affiliate_user(
        context,
        public_user_id,
        affiliate_enabled=False,
        invitation_quota=12,
        reason="第一次变更",
        expected_revision=initial["revision"],
        idempotency_key="admin-user-update-2",
    )
    mutations_before = storage.mutations

    with pytest.raises(AdminAccessRevisionConflict):
        service.update_admin_affiliate_user(
            context,
            public_user_id,
            affiliate_enabled=True,
            invitation_quota=14,
            reason="过期版本",
            expected_revision=initial["revision"],
            idempotency_key="admin-user-update-3",
        )
    assert storage.mutations == mutations_before

    policy = service.get_admin_registration_policy(context)
    assert policy["policy"]["mode"] == "invite_only"
    updated = service.update_admin_registration_policy(
        context,
        mode="open",
        reason="开放注册窗口",
        expected_revision=policy["revision"],
        idempotency_key="admin-policy-update-1",
    )
    assert updated["policy"]["mode"] == "open"
 
    replay = service.update_admin_registration_policy(
        context,
        mode="open",
        reason="开放注册窗口",
        expected_revision=policy["revision"],
        idempotency_key="admin-policy-update-1",
    )
 
    assert replay == updated
    assert storage.mutations == 2
 
    with pytest.raises(AdminAccessIdempotencyConflict):
        service.update_admin_registration_policy(
            context,
            mode="closed",
            reason="不同请求",
            expected_revision=policy["revision"],
            idempotency_key="admin-policy-update-1",
        )


def test_revoke_sessions_requires_opaque_target_and_audit_reason():
    service, storage = make_service()
    context = admin_context()
    public_user_id = service.list_admin_affiliate_users(context)["items"][0]["publicUserId"]

    receipt = service.revoke_admin_user_sessions(
        context,
        public_user_id,
        reason="安全事件处置",
        idempotency_key="admin-session-revoke-1",
    )

    assert receipt["ok"] is True
    assert receipt["schemaVersion"] == "media_web_business_pages_v2"
    assert storage.revoked_sessions == 2
    assert storage.audits[-1]["reason"] == "安全事件处置"
 
    replay = service.revoke_admin_user_sessions(
        context,
        public_user_id,
        reason="安全事件处置",
        idempotency_key="admin-session-revoke-1",
    )
 
    assert replay == receipt
    assert storage.revoked_sessions == 2
 
    with pytest.raises(AdminAccessIdempotencyConflict):
        service.revoke_admin_user_sessions(
            context,
            public_user_id,
            reason="不同请求",
            idempotency_key="admin-session-revoke-1",
        )


def test_create_admission_batch_reads_back_and_replays_idempotently():
    service, storage = make_service()
    registration_service = service.registration_service_for_test

    result = service.create_admin_admission_batch(
        admin_context(),
        name="summer",
        code_count=8,
        reason="合作伙伴试用",
        idempotency_key="admin-batch-create-1",
    )

    assert result["batch"]["name"] == "summer"
    assert result["batch"]["codeCount"] == 8
    assert result["batch"]["usedCount"] == 0
    assert len(storage.audits) == 1
    assert registration_service.calls == 1

    replay = service.create_admin_admission_batch(
        admin_context(),
        name="summer",
        code_count=8,
        reason="合作伙伴试用",
        idempotency_key="admin-batch-create-1",
    )

    assert replay == result
    assert registration_service.calls == 1


def test_disable_admission_batch_requires_revision_and_reads_back_status():
    service, storage = make_service()
    initial = service.list_admin_admission_batches(admin_context())
    public_batch_id = initial["items"][0]["batchId"]

    receipt = service.disable_admin_admission_batch(
        admin_context(),
        public_batch_id,
        reason="批次过期",
        expected_revision=initial["revision"],
        idempotency_key="admin-batch-disable-1",
    )

    assert receipt["ok"] is True
    assert service.list_admin_admission_batches(admin_context())["items"][0]["status"] == "disabled"
    assert storage.mutations == 1

    replay = service.disable_admin_admission_batch(
        admin_context(),
        public_batch_id,
        reason="批次过期",
        expected_revision=initial["revision"],
        idempotency_key="admin-batch-disable-1",
    )
    assert replay == receipt
    assert storage.mutations == 1
