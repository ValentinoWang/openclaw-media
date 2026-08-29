from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from openclaw_app.services.media_business.foundation import TenantContext
from openclaw_app.services.media_business.tracks import (
    TrackForbidden,
    TrackInternalError,
    TrackInvalidRequest,
    TrackNotFound,
    TrackMonitorUnavailable,
    TracksService,
)


TENANT_A = "00000000-0000-0000-0000-00000000000a"
TENANT_B = "00000000-0000-0000-0000-00000000000b"
TRACK_ID = "track_123456"
PARENT_ID = "parent_123456"
CREATOR_ID = "creator_123456"
ACCOUNT_ID = "account_123456"
CREATED = datetime(2026, 8, 5, 1, 2, 3, tzinfo=timezone.utc)
UPDATED = datetime(2026, 8, 5, 2, 2, 3, tzinfo=timezone.utc)


def track_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "track_name": "力量训练",
        "description": "长内容描述 " * 20,
        "parent_track_id": PARENT_ID,
        "status": "active",
        "platform_scope": ["xiaohongshu", "douyin"],
        "alias_names": ["力量", "训练"],
        "artifact_count": 4,
    }
    data.update(overrides)
    return data


def creator_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "account_name": "长内容博主",
        "platform": "xiaohongshu",
        "creator_role": "external_creator",
        "identity_tags": ["训练", "生活方式"],
        "expertise_domains": ["strength"],
        "profile_url": "https://example.test/creator/creator_123456",
        "avatar_url": "https://example.test/avatar/creator_123456.jpg",
    }
    data.update(overrides)
    return data


def membership_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "track_id": TRACK_ID,
        "creator_profile_id": CREATOR_ID,
        "role": "primary_creator",
        "fit_score": 0.91,
        "fit_reason": "explicit reviewed membership",
        "status": "confirmed",
        "last_evaluated_at": UPDATED,
    }
    data.update(overrides)
    return data


def account_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "platform": "xiaohongshu",
        "account_name": "我的账号",
        "operational_status": "active",
        "responsible_person": "王思尧",
        "team_name": "内容运营组",
        "account_positioning": "面向校园人群的运动训练账号",
        "data_source": "feishu_creator_profile",
        "author_id": "platform-account-123456",
        "profile_url": None,
        "avatar_url": "https://example.test/avatar/account_123456.jpg",
        "public_track_ids": [TRACK_ID],
        "last_synced_at": UPDATED,
    }
    data.update(overrides)
    return data


def strategy_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "public_account_id": ACCOUNT_ID,
        "target_public_track_ids": [TRACK_ID],
        "evidence_refs": [
            {
                "kind": "review",
                "label": "人工审核",
                "publicUrl": "https://example.test/evidence/strategy_123456",
                "capturedAt": UPDATED,
                "qualityStatus": "verified",
            }
        ],
        "recommendations": ["保持每周两次"],
        "human_status": "pending",
    }
    data.update(overrides)
    return data


TRACK_ROW = (TRACK_ID, 3, track_data(), None, CREATED, UPDATED)
TRACK_WITH_PARENT_ROW = (TRACK_ID, 3, track_data(), PARENT_ID, CREATED, UPDATED)
CREATOR_ROW = (CREATOR_ID, 2, creator_data(), CREATED, UPDATED)
RELATION_ROW = ("rel_123456", 1, membership_data(), CREATED, UPDATED, TRACK_ID, CREATOR_ID)
ACCOUNT_ROW = (ACCOUNT_ID, 1, account_data(), CREATED, UPDATED)
STRATEGY_ROW = ("strategy_123456", 2, strategy_data(), ACCOUNT_ID, UPDATED)


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return list(self.rows)


class FakeConnection:
    def __init__(
        self,
        *,
        tracks: list[Any] | None = None,
        creators: list[Any] | None = None,
        relationships: list[Any] | None = None,
        accounts: list[Any] | None = None,
        strategy: list[Any] | None = None,
    ) -> None:
        self.tracks = tracks if tracks is not None else [TRACK_ROW]
        self.creators = creators if creators is not None else [CREATOR_ROW]
        self.relationships = relationships if relationships is not None else [RELATION_ROW]
        self.accounts = accounts if accounts is not None else [ACCOUNT_ROW]
        self.strategy = strategy if strategy is not None else [STRATEGY_ROW]
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "FROM media_product.tracks AS t" in query and "COUNT(*)" in query:
            return FakeResult([(len(self.tracks), 3 if self.tracks else 0, UPDATED if self.tracks else None)])
        if "FROM media_product.tracks AS t" in query and "canonical_data::text" in query:
            return FakeResult(self.tracks)
        if "FROM media_product.tracks AS t" in query:
            return FakeResult(self.tracks[:1])
        if "FROM media_product.creator_profiles AS c" in query and "COUNT(*)" in query:
            return FakeResult([(len(self.creators), 2 if self.creators else 0, UPDATED if self.creators else None)])
        if "FROM media_product.creator_profiles AS c" in query and "canonical_data::text" in query:
            return FakeResult(self.creators)
        if "FROM media_product.creator_profiles AS c" in query:
            return FakeResult(self.creators[:1])
        if "FROM media_product.track_creator_memberships AS m" in query and "COUNT(*)" in query:
            return FakeResult([(len(self.relationships), 1 if self.relationships else 0, UPDATED if self.relationships else None)])
        if "FROM media_product.track_creator_memberships AS m" in query:
            return FakeResult(self.relationships)
        if "FROM media_product.owned_media_accounts AS a" in query and "COUNT(*)" in query:
            return FakeResult([(len(self.accounts), 1 if self.accounts else 0, UPDATED if self.accounts else None)])
        if "FROM media_product.owned_media_accounts AS a" in query:
            return FakeResult(self.accounts[:1])
        if "FROM media_product.account_track_strategies AS s" in query:
            return FakeResult(self.strategy)
        raise AssertionError(f"unexpected query: {query}")


def service(connection: FakeConnection) -> TracksService:
    @contextmanager
    def factory() -> Any:
        yield connection

    return TracksService(factory, cursor_secret=b"b02-test-cursor-secret")


def context(tenant_id: str = TENANT_A) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, user_public_id="user_123456")


def test_list_tracks_projects_explicit_fields_and_orphan_parent_as_null() -> None:
    connection = FakeConnection()
    response = service(connection).list_tracks(context(), page_size=20, search="力量")

    assert response["items"] == [
        {
            "publicTrackId": TRACK_ID,
            "name": "力量训练",
            "description": "长内容描述 " * 20,
            "parentPublicTrackId": None,
            "status": "active",
            "platforms": ["xiaohongshu", "douyin"],
            "aliases": ["力量", "训练"],
            "artifactCount": 4,
            "updatedAt": "2026-08-05T02:02:03Z",
        }
    ]
    query, params = next((q, p) for q, p in connection.calls if "canonical_data::text" in q)
    assert "t.tenant_id = %s" in query
    assert "parent.tenant_id = t.tenant_id" in query
    assert params[:4] == (TENANT_A, "力量", "%力量%", "%力量%")


def test_list_tracks_keeps_existing_parent_id_from_explicit_join() -> None:
    response = service(FakeConnection(tracks=[TRACK_WITH_PARENT_ROW])).list_tracks(context())
    assert response["items"][0]["parentPublicTrackId"] == PARENT_ID


def test_list_creators_returns_typed_summary_and_detail() -> None:
    connection = FakeConnection()
    response = service(connection).list_creators(context(), search="博主")
    assert response["items"][0]["publicCreatorId"] == CREATOR_ID
    assert response["items"][0]["profileUrl"].startswith("https://")
    assert response["items"][0]["avatarUrl"] == "https://example.test/avatar/creator_123456.jpg"
    detail = service(FakeConnection()).get_creator(context(), CREATOR_ID)
    assert detail["item"]["creatorRole"] == "external_creator"
    assert detail["revision"] == 2


def test_list_creators_preserves_missing_profile_url_as_null() -> None:
    row = (CREATOR_ID, 2, creator_data(profile_url=None), CREATED, UPDATED)
    response = service(FakeConnection(creators=[row])).list_creators(context())

    assert response["items"][0]["profileUrl"] is None


def test_list_creators_preserves_missing_avatar_url_as_null() -> None:
    row = (CREATOR_ID, 2, creator_data(avatar_url=None), CREATED, UPDATED)
    response = service(FakeConnection(creators=[row])).list_creators(context())

    assert response["items"][0]["avatarUrl"] is None


def test_list_creators_accepts_http_avatar_and_nulls_invalid_avatar() -> None:
    http_row = (CREATOR_ID, 2, creator_data(avatar_url="http://example.test/avatar.jpg"), CREATED, UPDATED)
    invalid_row = (CREATOR_ID, 2, creator_data(avatar_url="javascript:alert(1)"), CREATED, UPDATED)

    assert service(FakeConnection(creators=[http_row])).list_creators(context())["items"][0]["avatarUrl"] == "http://example.test/avatar.jpg"
    assert service(FakeConnection(creators=[invalid_row])).list_creators(context())["items"][0]["avatarUrl"] is None


def test_relationships_only_project_explicit_membership_and_reject_duplicates() -> None:
    response = service(FakeConnection()).list_track_relationships(context())
    assert response["items"] == [
        {
            "publicRelationshipId": "rel_123456",
            "revision": 1,
            "publicTrackId": TRACK_ID,
            "publicCreatorId": CREATOR_ID,
            "role": "primary_creator",
            "fitScore": 0.91,
            "fitReason": "explicit reviewed membership",
            "status": "confirmed",
            "lastEvaluatedAt": "2026-08-05T02:02:03Z",
        }
    ]
    duplicate = FakeConnection(relationships=[RELATION_ROW, RELATION_ROW])
    with pytest.raises(TrackInternalError, match="duplicate"):
        service(duplicate).list_track_relationships(context())
    relationship_query = next(q for q, _ in duplicate.calls if "FROM media_product.track_creator_memberships" in q)
    assert "JOIN media_product.tracks" in relationship_query
    assert "JOIN media_product.creator_profiles" in relationship_query
    assert "identity_tags" not in relationship_query
    assert "expertise_domains" not in relationship_query


def test_cross_tenant_detail_is_masked_as_not_found() -> None:
    with pytest.raises(TrackNotFound):
        service(FakeConnection(tracks=[])).get_track(context(TENANT_B), TRACK_ID)
    with pytest.raises(TrackNotFound):
        service(FakeConnection(creators=[])).get_creator(context(TENANT_B), CREATOR_ID)


def test_cursor_is_opaque_scope_and_tenant_bound() -> None:
    second_track = (TRACK_ID.replace("123456", "234567"), 1, track_data(), None, CREATED, CREATED)
    connection = FakeConnection(tracks=[TRACK_ROW, second_track])
    first = service(connection).list_tracks(context(), page_size=1)
    assert first["nextCursor"]
    with pytest.raises(TrackInvalidRequest, match="cursor"):
        service(connection).list_creators(context(), cursor=first["nextCursor"])
    with pytest.raises(TrackInvalidRequest, match="cursor"):
        service(connection).list_tracks(context(TENANT_B), cursor=first["nextCursor"])


def test_empty_relationships_are_successful_empty_state() -> None:
    response = service(FakeConnection(relationships=[])).list_track_relationships(context())
    assert response["items"] == []
    assert response["nextCursor"] is None
    assert response["schemaVersion"] == "media_web_business_pages_v2"


def test_owned_accounts_are_not_creator_profiles_and_strategy_is_explicit() -> None:
    connection = FakeConnection()
    account_response = service(connection).list_owned_accounts(context())
    assert account_response["items"][0]["publicAccountId"] == ACCOUNT_ID
    assert account_response["items"][0]["platformAccountId"] == "platform-account-123456"
    assert account_response["items"][0]["operationalStatus"] == "active"
    assert account_response["items"][0]["responsiblePerson"] == "王思尧"
    assert account_response["items"][0]["teamName"] == "内容运营组"
    assert account_response["items"][0]["accountPositioning"] == "面向校园人群的运动训练账号"
    assert account_response["items"][0]["dataSource"] == "feishu_creator_profile"
    assert "authorizationStatus" not in account_response["items"][0]
    assert account_response["items"][0]["profileUrl"] is None
    assert account_response["items"][0]["avatarUrl"] == "https://example.test/avatar/account_123456.jpg"
    assert all("creator_profiles" not in query for query, _ in connection.calls)
    strategy = service(FakeConnection()).get_account_track_strategy(context(), ACCOUNT_ID)
    assert strategy["strategy"]["publicAccountId"] == ACCOUNT_ID
    assert strategy["strategy"]["evidenceRefs"][0]["qualityStatus"] == "verified"


def test_monitor_mutations_validate_owned_account_then_fail_closed_without_adapter() -> None:
    connection = FakeConnection()
    with pytest.raises(TrackMonitorUnavailable):
        service(connection).update_account_monitor(
            context(), ACCOUNT_ID, ["https://example.test/post/1"], True, "monitor-key"
        )
    with pytest.raises(TrackMonitorUnavailable):
        service(connection).poll_account_monitor(context(), ACCOUNT_ID, "poll-key")
    assert len(connection.calls) == 2


def test_monitor_mutation_rejects_invalid_urls_before_database_access() -> None:
    connection = FakeConnection()
    with pytest.raises(TrackInvalidRequest, match="HTTP"):
        service(connection).update_account_monitor(context(), ACCOUNT_ID, ["javascript:bad"], True, "key")
    assert connection.calls == []


def test_owned_account_avatar_and_platform_identifier_are_nullable_but_explicit() -> None:
    row = (
        ACCOUNT_ID,
        1,
        account_data(
            author_id=None,
            avatar_url=None,
            operational_status=None,
            responsible_person=None,
            team_name=None,
        ),
        CREATED,
        UPDATED,
    )
    account = service(FakeConnection(accounts=[row])).list_owned_accounts(context())["items"][0]

    assert account["platformAccountId"] is None
    assert account["avatarUrl"] is None
    assert account["operationalStatus"] is None
    assert account["responsiblePerson"] is None
    assert account["teamName"] is None


def test_owned_account_invalid_avatar_is_not_projected() -> None:
    row = (
        ACCOUNT_ID,
        1,
        account_data(avatar_url="javascript:alert(1)"),
        CREATED,
        UPDATED,
    )

    account = service(FakeConnection(accounts=[row])).list_owned_accounts(context())["items"][0]

    assert account["avatarUrl"] is None


def test_owned_account_unknown_operational_status_fails_closed() -> None:
    row = (ACCOUNT_ID, 1, account_data(operational_status="awaiting_auth"), CREATED, UPDATED)

    with pytest.raises(TrackInternalError, match="operational status"):
        service(FakeConnection(accounts=[row])).list_owned_accounts(context())


def test_missing_canonical_field_fails_closed() -> None:
    malformed = (TRACK_ID, 1, track_data(artifact_count=None), None, CREATED, UPDATED)
    with pytest.raises(TrackInternalError, match="artifact count"):
        service(FakeConnection(tracks=[malformed])).list_tracks(context())


def test_invalid_request_is_rejected_before_database_access() -> None:
    connection = FakeConnection()
    with pytest.raises(TrackInvalidRequest, match="pageSize"):
        service(connection).list_tracks(context(), page_size=0)
    with pytest.raises(TrackInvalidRequest, match="search"):
        service(connection).list_creators(context(), search="x" * 161)
    with pytest.raises(TrackForbidden):
        service(connection).list_tracks(None)
    assert connection.calls == []


def test_error_payload_has_if2_shape() -> None:
    error = TrackNotFound()
    assert TracksService.error_response(error) == {
        "error": {
            "code": "resource_not_found",
            "message": "resource not found",
            "field": None,
        }
    }
    assert TracksService.error_status(error) == 404


def test_migration_is_focused_on_existing_tables_and_b02_indexes() -> None:
    migration = Path(__file__).parents[1] / "openclaw_app" / "migrations" / "014_b02_tracks.sql"
    text = migration.read_text()
    assert "CREATE TABLE" not in text.upper()
    for marker in (
        "tracks_b02_tenant_updated_public_idx",
        "creator_profiles_b02_tenant_updated_public_idx",
        "track_creator_memberships_b02_explicit_pair_uq",
        "owned_media_accounts_b02_tenant_updated_public_idx",
        "account_track_strategies_b02_tenant_account_updated_idx",
        "VALUES (14, 'b02_tracks')",
    ):
        assert marker in text
