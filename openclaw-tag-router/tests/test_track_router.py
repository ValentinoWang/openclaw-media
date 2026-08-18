from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from openclaw_app.models.message import Message
from openclaw_app.router.media_growth import MediaGrowthMixin
from selfmedia.growth.track_repository import TrackRepository


TRACK_URL = "https://example.test/base/app?table=tracks"
MEMBERSHIP_URL = "https://example.test/base/app?table=memberships"
PROFILE_URL = "https://example.test/base/app?table=profiles"
TENANT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def message(tag: str, body: str, *, is_maintainer: bool = False) -> Message:
    return Message(
        entry_tag=tag,
        raw_text=f"【{tag}】{body}",
        body=body,
        source="web",
        chat_type="private",
        created_at=datetime(2026, 7, 29, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        metadata={
            "channel": "media_web",
            "account_id": "media",
            "tenant_id": TENANT_ID,
            "is_maintainer": is_maintainer,
        },
    )


class TrackHarness(MediaGrowthMixin):
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, dict]] = []
        self.records = {
            TRACK_URL: [
                {
                    "fields": {
                        "赛道ID": "track_campus_sports",
                        "赛道名称": "校园体育",
                        "适用平台": ["小红书", "抖音"],
                        "状态": "active",
                        "赛道别名": ["高校体育"],
                    }
                }
            ],
            MEMBERSHIP_URL: [],
            PROFILE_URL: [
                {
                    "fields": {
                        "达人档案ID": "creator_1",
                        "平台": "抖音",
                        "作者ID": "author_1",
                        "账号名称": "示例跑者",
                        "租户ID": TENANT_ID,
                    }
                }
            ],
        }

    def _track_repository(self, tenant_id: str) -> TrackRepository:
        class FakeRegistry:
            @staticmethod
            def list_all_by_tenant(actual_tenant_id: str, *, resource_type: str, **_kwargs) -> list[object]:
                assert actual_tenant_id == TENANT_ID
                ids = ["creator_1"] if resource_type == "media.creator_profile" else []
                return [SimpleNamespace(canonical_resource_id=item) for item in ids]

        class FakeOwnerService:
            registry = FakeRegistry()

            @staticmethod
            def assert_projection_read(resource_type: str, resource_id: str, *, session_tenant_id: str, fields: dict, projection_source: str) -> dict:
                assert resource_type and resource_id and projection_source
                assert session_tenant_id == TENANT_ID
                assert fields.get("租户ID") == TENANT_ID
                return fields

        def loader(url: str, **_kwargs) -> list[dict]:
            return list(self.records[url])

        def upserter(entity: str, url: str, payload: dict) -> dict:
            self.writes.append((entity, url, dict(payload)))
            return {"mode": "test_upsert", "entity": entity}

        return TrackRepository(
            tenant_id=tenant_id,
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


def test_track_query_reads_only_registered_rows() -> None:
    harness = TrackHarness()
    result = harness.handle_track_registry(message("赛道", "动作：查询\n赛道名称：高校体育"))

    assert result.ok is True
    assert result.status == "track_registry_listed"
    assert result.task_id == "track_campus_sports"
    assert harness.writes == []


def test_track_registration_rejects_non_maintainer_write_to_global_catalog() -> None:
    harness = TrackHarness()
    result = harness.handle_track_registry(
        message("赛道", "动作：注册\n赛道名称：跑步训练\n适用平台：小红书、抖音\n别名：短跑训练")
    )

    assert result.ok is False
    assert result.status == "track_operation_failed"
    assert harness.writes == []


def test_track_registration_allows_maintainer_and_reuses_global_catalog_writer() -> None:
    harness = TrackHarness()
    result = harness.handle_track_registry(
        message(
            "赛道",
            "动作：注册\n赛道名称：跑步训练\n适用平台：小红书、抖音\n别名：短跑训练",
            is_maintainer=True,
        )
    )

    assert result.ok is True
    assert result.status == "track_registry_upserted"
    assert len(harness.writes) == 1
    entity, url, payload = harness.writes[0]
    assert (entity, url) == ("TrackRegistry", TRACK_URL)
    assert payload["track_id"].startswith("track_")
    assert payload["track_name"] == "跑步训练"


def test_membership_preview_never_writes_without_explicit_confirmation() -> None:
    harness = TrackHarness()
    result = harness.handle_track_registry(
        message(
            "赛道-关系",
            "动作：关系预览\n赛道ID：track_campus_sports\n达人档案ID：creator_1\n角色：标杆账号\n匹配分：92\n匹配理由：主页内容明确包含校园短跑训练\n证据引用：https://example.test/evidence/1",
        ),
        canonical_capability_id="track_creator_membership_query",
    )

    assert result.ok is False
    assert result.status == "track_creator_membership_pending_manual"
    assert harness.writes == []


def test_membership_confirmation_writes_evidence_backed_relation() -> None:
    harness = TrackHarness()
    result = harness.handle_track_registry(
        message(
            "赛道-关系",
            "动作：关系确认\n赛道ID：track_campus_sports\n达人档案ID：creator_1\n角色：标杆账号\n匹配分：92\n匹配理由：主页内容明确包含校园短跑训练\n证据引用：https://example.test/evidence/1\n确认：是",
        ),
        canonical_capability_id="track_creator_membership_query",
    )

    assert result.ok is True
    assert result.status == "track_creator_membership_confirmed"
    assert len(harness.writes) == 1
    entity, url, payload = harness.writes[0]
    assert (entity, url) == ("TrackCreatorMembership", MEMBERSHIP_URL)
    assert payload["evidence_refs"] == "https://example.test/evidence/1"
    assert payload["source_capability"] == "track_creator_membership_query"
