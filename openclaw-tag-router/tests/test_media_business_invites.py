from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

from openclaw_app.services.media_business.foundation import TenantContext, error_status
from openclaw_app.services.media_business.invites import (
    InvitesForbidden,
    InvitesInternalError,
    InvitesInvalidRequest,
    InvitesNotFound,
    InvitesService,
)


TENANT_A = "00000000-0000-0000-0000-00000000000a"
TENANT_B = "00000000-0000-0000-0000-00000000000b"
USER_A = "10000000-0000-0000-0000-00000000000a"
USER_B = "10000000-0000-0000-0000-00000000000b"
CREATED = datetime(2026, 8, 5, 1, 2, 3, tzinfo=timezone.utc)
EXPIRES = datetime(2026, 9, 5, 1, 2, 3, tzinfo=timezone.utc)
PROFILE = ("ABCDEF1234567890ABCD", True, 2, 2, EXPIRES, CREATED)


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return list(self.rows)


class FakeConnection:
    def __init__(self, *, invitee_rows: list[Any] | None = None, cursor_rows: list[Any] | None = None) -> None:
        self.invitee_rows = invitee_rows or []
        self.cursor_rows = cursor_rows if cursor_rows is not None else self.invitee_rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "profile.invite_code" in query:
            return FakeResult([PROFILE])
        if "COUNT(edge.invitee_user_id)" in query:
            return FakeResult([(CREATED, len(self.invitee_rows), CREATED if self.invitee_rows else None)])
        if "FROM openclaw_account.affiliate_edges" in query:
            return FakeResult(self.cursor_rows if "edge.created_at <" in query else self.invitee_rows)
        raise AssertionError(f"unexpected query: {query}")


def service(connection: FakeConnection) -> InvitesService:
    @contextmanager
    def factory() -> Any:
        yield connection

    return InvitesService(
        factory,
        public_id_secret=b"b09-test-public-id-secret",
        cursor_secret=b"b09-test-cursor-secret",
    )


def context(tenant_id: str = TENANT_A, user_id: str = USER_A) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, user_public_id=user_id)


def invitee(user_id: str, name: str, status: str, joined_at: datetime = CREATED) -> tuple[Any, ...]:
    return (user_id, name, status, joined_at)


def test_profile_projects_exact_if2_dto_and_preserves_expiry_and_quota() -> None:
    response = service(FakeConnection()).get_affiliate_profile(context())

    assert set(response) == {"schemaVersion", "revision", "profile"}
    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["revision"] == response["profile"]["revision"]
    assert response["profile"] == {
        "affiliateCode": "ABCDEF1234567890ABCD",
        "enabled": True,
        "quota": 2,
        "used": 2,
        "expiresAt": "2026-09-05T01:02:03Z",
        "revision": response["revision"],
    }


def test_empty_invitee_list_is_success_not_an_error_or_fabricated_count() -> None:
    response = service(FakeConnection()).list_invitees(context(), page_size=30)

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["items"] == []
    assert response["nextCursor"] is None
    assert response["revision"] > 0


def test_invitee_cursor_is_opaque_and_bound_to_tenant_and_user() -> None:
    rows = [
        invitee("20000000-0000-0000-0000-000000000001", "First", "registered"),
        invitee("20000000-0000-0000-0000-000000000002", "Second", "pending"),
    ]
    connection = FakeConnection(invitee_rows=rows, cursor_rows=[rows[1]])
    first = service(connection).list_invitees(context(), page_size=1)

    cursor = first["nextCursor"]
    assert isinstance(cursor, str)
    assert TENANT_A not in cursor
    assert USER_A not in cursor
    assert first["items"][0]["status"] == "registered"

    second = service(connection).list_invitees(context(), cursor=cursor, page_size=1)
    assert [item["displayName"] for item in second["items"]] == ["Second"]
    assert second["nextCursor"] is None

    with pytest.raises(InvitesInvalidRequest, match="cursor"):
        service(connection).list_invitees(context(TENANT_B), cursor=cursor, page_size=1)

    with pytest.raises(InvitesInvalidRequest, match="cursor"):
        service(connection).list_invitees(context(user_id=USER_B), cursor=cursor, page_size=1)


def test_query_scope_uses_current_user_and_tenant_without_caller_target_fields() -> None:
    connection = FakeConnection()
    service(connection).get_affiliate_profile(context(TENANT_B, USER_B))

    profile_call = next(params for query, params in connection.calls if "profile.invite_code" in query)
    assert profile_call == (UUID(USER_B), UUID(TENANT_B))
    assert all("targetTenant" not in query for query, _ in connection.calls)


def test_query_scope_accepts_active_tenant_members_without_owner_only_joins() -> None:
    connection = FakeConnection(invitee_rows=[invitee(USER_B, "Member", "active")])

    service(connection).get_affiliate_profile(context())
    service(connection).list_invitees(context(), page_size=30)

    profile_query = next(query for query, _ in connection.calls if "profile.invite_code" in query)
    state_query = next(query for query, _ in connection.calls if "COUNT(edge.invitee_user_id)" in query)
    invitees_query = next(query for query, _ in connection.calls if "FROM openclaw_account.affiliate_edges" in query)
    assert "openclaw_account.tenant_members AS member" in profile_query
    assert "openclaw_account.tenant_members AS member" in state_query
    assert "member.status = 'active'" in profile_query
    assert "member.status = 'active'" in state_query
    assert "primary_user_id" not in profile_query
    assert "primary_user_id" not in state_query
    assert "invitee_tenant" not in invitees_query


def test_malformed_invitee_row_fails_closed_and_forbidden_context_has_stable_error() -> None:
    connection = FakeConnection(invitee_rows=[invitee(USER_B, "", "registered")])
    with pytest.raises(InvitesInternalError):
        service(connection).list_invitees(context(), page_size=1)

    with pytest.raises(InvitesForbidden):
        service(connection).get_affiliate_profile(None)  # type: ignore[arg-type]


def test_error_payload_keeps_if2_code_and_field_shape() -> None:
    error = InvitesInvalidRequest("pageSize is invalid", field="pageSize")
    assert error_status(error) == 400
    assert InvitesService.error_response(error) == {
        "error": {
            "code": "invalid_request",
            "message": "pageSize is invalid",
            "field": "pageSize",
        }
    }
    assert InvitesService.error_response(InvitesNotFound()) == {
        "error": {
            "code": "resource_not_found",
            "message": "invite profile was not found",
            "field": None,
        }
    }
