from __future__ import annotations

import pytest
from types import SimpleNamespace

from selfmedia.growth.track_repository import TrackRepository, TrackRepositoryError


TRACK_URL = "https://example.test/base/app?table=tracks"
MEMBERSHIP_URL = "https://example.test/base/app?table=memberships"
PROFILE_URL = "https://example.test/base/app?table=profiles"


def make_repository(
    *,
    memberships: list[dict] | None = None,
    writes: list[tuple[str, str, dict]] | None = None,
) -> TrackRepository:
    records = {
        TRACK_URL: [
            {
                "fields": {
                    "赛道ID": "track_running",
                    "赛道名称": "跑步训练",
                    "适用平台": ["小红书", "抖音"],
                    "状态": "active",
                }
            }
        ],
        MEMBERSHIP_URL: list(memberships or []),
        PROFILE_URL: [
            {
                "fields": {
                    "达人档案ID": "creator_1",
                    "平台": "小红书",
                    "作者ID": "author_1",
                    "账号名称": "示例跑者",
                    "租户ID": "00000000-0000-4000-8000-000000000101",
                }
            }
        ],
    }
    writes = writes if writes is not None else []

    class FakeRegistry:
        def list_all_by_tenant(self, tenant_id: str, *, resource_type: str, **_kwargs) -> list[object]:
            assert tenant_id == "00000000-0000-4000-8000-000000000101"
            ids = {
                "media.creator_profile": ["creator_1"],
                "media.track_creator_membership": [
                    str(item.get("fields", {}).get("关系ID") or "")
                    for item in records[MEMBERSHIP_URL]
                    if item.get("fields", {}).get("关系ID")
                ],
            }.get(resource_type, [])
            return [SimpleNamespace(canonical_resource_id=item) for item in ids]

    class FakeOwnerService:
        registry = FakeRegistry()

        @staticmethod
        def assert_projection_read(resource_type: str, resource_id: str, *, session_tenant_id: str, fields: dict, projection_source: str) -> dict:
            assert resource_type and resource_id and projection_source
            assert session_tenant_id == "00000000-0000-4000-8000-000000000101"
            assert fields.get("租户ID") == "00000000-0000-4000-8000-000000000101"
            return fields

    def loader(url: str, **_kwargs) -> list[dict]:
        return list(records[url])

    def upserter(entity: str, url: str, payload: dict) -> dict:
        writes.append((entity, url, dict(payload)))
        return {"mode": "test_upsert", "entity": entity}

    return TrackRepository(
        tenant_id="00000000-0000-4000-8000-000000000101",
        track_table_url=TRACK_URL,
        membership_table_url=MEMBERSHIP_URL,
        creator_profile_table_url=PROFILE_URL,
        record_loader=loader,
        entity_upserter=upserter,
        global_entity_upserter=lambda entity, url, payload, authorized: (
            upserter(entity, url, payload)
            if authorized
            else (_ for _ in ()).throw(RuntimeError("unauthorized"))
        ),
        tenant_owned_resources=FakeOwnerService(),
    )


def valid_membership() -> dict:
    return {
        "track_id": "track_running",
        "creator_profile_id": "creator_1",
        "platform": "小红书",
        "author_id": "author_1",
        "account_name_snapshot": "示例跑者",
        "role": "标杆账号",
        "fit_score": 91,
        "fit_reason": "内容主题和训练证据均与赛道定义一致",
        "content_use_case": "训练结构参考",
        "business_use_case": "运动品牌合作观察",
        "evidence_refs": ["https://example.test/evidence/1", "https://example.test/evidence/2"],
        "source_capability": "media.creator-cohort.v1",
        "status": "candidate",
        "last_evaluated_at": "2026-07-29T12:00:00+08:00",
    }


def test_lists_only_persisted_track_facts() -> None:
    repository = make_repository()

    tracks = repository.list_tracks()

    assert [item.track_id for item in tracks] == ["track_running"]
    assert tracks[0].platform_scope == ("小红书", "抖音")


def test_membership_upsert_generates_stable_id_and_writes_safe_evidence_text() -> None:
    writes: list[tuple[str, str, dict]] = []
    repository = make_repository(writes=writes)

    first = repository.upsert_membership(valid_membership())
    second = repository.upsert_membership(valid_membership())

    first_id = first["entity_payload"]["membership_id"]
    assert first_id == second["entity_payload"]["membership_id"]
    assert writes[0][0:2] == ("TrackCreatorMembership", MEMBERSHIP_URL)
    assert writes[0][2]["evidence_refs"] == "https://example.test/evidence/1\nhttps://example.test/evidence/2"
    assert "[" not in writes[0][2]["evidence_refs"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("role", "自动猜测角色", "manual correction"),
        ("fit_score", 101, "manual correction"),
        ("evidence_refs", [], "pending_manual"),
        ("fit_reason", "", "pending_manual"),
    ],
)
def test_invalid_or_unproven_membership_is_not_written(field: str, value: object, message: str) -> None:
    writes: list[tuple[str, str, dict]] = []
    repository = make_repository(writes=writes)
    payload = valid_membership()
    payload[field] = value

    with pytest.raises(TrackRepositoryError, match=message):
        repository.upsert_membership(payload)

    assert writes == []


def test_unknown_track_and_creator_are_rejected() -> None:
    repository = make_repository()
    unknown_track = {**valid_membership(), "track_id": "track_unknown"}
    unknown_creator = {**valid_membership(), "creator_profile_id": "creator_unknown"}

    with pytest.raises(TrackRepositoryError, match="unknown TrackRegistry"):
        repository.upsert_membership(unknown_track)
    with pytest.raises(TrackRepositoryError, match="unknown CreatorProfile"):
        repository.upsert_membership(unknown_creator)


def test_duplicate_track_creator_pair_with_different_id_is_rejected() -> None:
    existing = {
        "fields": {
            "关系ID": "membership_existing",
            "赛道ID": "track_running",
            "达人档案ID": "creator_1",
            "赛道角色": "标杆账号",
            "匹配分": 80,
            "匹配理由": "已有明确证据",
            "证据引用": "https://example.test/evidence/existing",
            "来源能力": "media.creator-cohort.v1",
            "状态": "active",
            "最近评估时间": 1785307200000,
            "租户ID": "00000000-0000-4000-8000-000000000101",
        }
    }
    repository = make_repository(memberships=[existing])
    payload = {**valid_membership(), "membership_id": "membership_other"}

    with pytest.raises(TrackRepositoryError, match="duplicate track/profile relation"):
        repository.upsert_membership(payload)


def test_global_track_catalog_rejects_non_maintainer_write() -> None:
    writes: list[tuple[str, str, dict]] = []
    repository = make_repository(writes=writes)

    with pytest.raises(TrackRepositoryError, match="maintainer authorization"):
        repository.upsert_track(
            {
                "track_id": "track_running",
                "track_name": "跑步训练",
                "platform_scope": ["小红书", "抖音"],
                "status": "active",
            }
        )
    assert writes == []


def test_track_name_alias_lookup_does_not_bypass_maintainer_authorization() -> None:
    writes: list[tuple[str, str, dict]] = []
    repository = make_repository(writes=writes)

    assert repository.find_track("跑步训练").track_id == "track_running"
    with pytest.raises(TrackRepositoryError, match="maintainer authorization"):
        repository.upsert_track(
            {
                "track_name": "跑步训练",
                "platform_scope": ["小红书", "抖音"],
                "status": "active",
            }
        )
    assert writes == []


def test_maintainer_track_upsert_generates_stable_id_and_is_idempotent() -> None:
    writes: list[tuple[str, str, dict]] = []
    repository = make_repository(writes=writes)
    payload = {
        "track_name": "校园体育",
        "platform_scope": ["小红书", "抖音"],
        "status": "active",
    }

    first = repository.upsert_track(payload, maintainer_authorized=True)
    second = repository.upsert_track(payload, maintainer_authorized=True)

    assert first["entity_payload"]["track_id"] == second["entity_payload"]["track_id"]
    assert writes[0][0:2] == ("TrackRegistry", TRACK_URL)


def test_track_upsert_rejects_duplicate_name_and_unknown_parent() -> None:
    repository = make_repository()
    with pytest.raises(TrackRepositoryError, match="duplicate TrackRegistry name"):
        repository.upsert_track(
            {"track_id": "track_other", "track_name": "跑步训练", "status": "active"},
            maintainer_authorized=True,
        )
    with pytest.raises(TrackRepositoryError, match="unknown parent TrackRegistry"):
        repository.upsert_track(
            {"track_name": "校园体育", "parent_track_id": "track_missing", "status": "active"},
            maintainer_authorized=True,
        )
