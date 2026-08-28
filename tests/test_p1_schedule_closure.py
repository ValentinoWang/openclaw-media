from __future__ import annotations

import json
import tempfile
from datetime import datetime
from unittest.mock import patch

from selfmedia.business import id_business
from selfmedia.business.schedule import (
    LOCAL_TZ,
    append_schedule_snapshot,
    parse_schedule_window,
    schedule_snapshot_path,
)
from selfmedia.context import build_media_context
from selfmedia.creation.adapters import BusinessAdapter
from selfmedia.creation.shooting_execution import (
    ShootingExecutionRequest,
    generate_shooting_execution_plan,
    validate_shooting_execution_plan,
)


TENANT_ID = "00000000-0000-4000-8000-000000000201"
OTHER_TENANT_ID = "00000000-0000-4000-8000-000000000202"


def _draft(time_slot: str) -> dict[str, object]:
    return {
        "shooting_goal": {},
        "route_map": [{"time_slot": time_slot, "location": "棚拍", "shooting_task": "拍摄", "people": "博主", "backup": "补拍"}],
        "must_shot_list": [{"priority": "P0"}],
        "branch_plans": [{"priority": "P1"}],
        "storyboard": [{}],
        "onsite_checklist": ["核对器材"],
        "publishing_pack": {"first_hour_action": "回复评论"},
        "evidence_appendix": [{"source_status": "confirmed"}],
    }


def _request(*, publish_time: str = "") -> ShootingExecutionRequest:
    return ShootingExecutionRequest(
        platform="小红书",
        content_type="视频",
        track="训练",
        topic="起跑训练",
        shooting_goal="完成训练日视频",
        locations=["棚拍"],
        people=["博主"],
        publish_time=publish_time,
    )


def test_schedule_parser_accepts_concrete_windows_and_rejects_ambiguous_or_expired() -> None:
    now = datetime(2026, 8, 29, 9, tzinfo=LOCAL_TZ)
    assert parse_schedule_window("2026-09-10", now=now) == {
        "valid_from": "2026-09-10",
        "valid_until": "2026-09-10",
        "schedule": "2026-09-10",
    }
    assert parse_schedule_window("2026年12月31日至1月2日", now=now) == {
        "valid_from": "2026-12-31",
        "valid_until": "2027-01-02",
        "schedule": "2026年12月31日至1月2日",
    }
    assert parse_schedule_window("8月10日", now=now) is None
    assert parse_schedule_window("9月2日至2026年9月3日", now=now) is None
    assert parse_schedule_window("2026-08-28", now=now) is None
    assert parse_schedule_window("8月上旬", now=now) is None


def test_snapshot_is_tenant_isolated_idempotent_and_consumed_by_context() -> None:
    with tempfile.TemporaryDirectory() as directory:
        entry = {
            "platform": "小红书",
            "account": "主账号",
            "title": "品牌商单",
            "starts_at": "2026-09-02T00:00:00+08:00",
            "ends_at": "2026-09-02T23:59:00+08:00",
        }
        first = append_schedule_snapshot(
            tenant_id=TENANT_ID,
            root=directory,
            entries=[entry],
            source_type="business_opportunity",
            source_id="opp-1",
            source_time="2026-08-29T09:00:00+08:00",
            dedupe_key="opp-1:2026-09-02",
            provenance={"record_id": "rec-1"},
        )
        replay = append_schedule_snapshot(
            tenant_id=TENANT_ID,
            root=directory,
            entries=[entry],
            source_type="business_opportunity",
            source_id="opp-1",
            source_time="2026-08-29T09:00:00+08:00",
            dedupe_key="opp-1:2026-09-02",
        )
        append_schedule_snapshot(
            tenant_id=OTHER_TENANT_ID,
            root=directory,
            entries=[entry],
            source_type="business_opportunity",
            source_id="opp-other",
            source_time="2026-08-29T09:00:00+08:00",
        )
        assert first["persisted"] is True
        assert replay["status"] == "deduped"
        assert len(schedule_snapshot_path(tenant_id=TENANT_ID, root=directory).read_text(encoding="utf-8").splitlines()) == 1
        context = build_media_context(
            tenant_id=TENANT_ID,
            platform="小红书",
            account="主账号",
            root=directory,
            now=datetime(2026, 8, 29, 9, tzinfo=LOCAL_TZ),
        )
        assert context["schedule"][0]["title"] == "品牌商单"
        assert build_media_context(
            tenant_id=OTHER_TENANT_ID,
            platform="小红书",
            account="主账号",
            root=directory,
            now=datetime(2026, 8, 29, 9, tzinfo=LOCAL_TZ),
        )["schedule"][0]["title"] == "品牌商单"


def test_business_write_persists_structured_opportunity_and_schedule_snapshot_after_external_success() -> None:
    fields = {
        "平台": "小红书",
        "作者ID": "creator-1",
        "账号名称": "主账号",
        "品牌": "测试品牌",
        "产品": "测试产品",
        "内容类型": "视频",
        "具体档期": "2026-09-02 至 2026-09-03",
        "视频报价": "1200",
    }
    with tempfile.TemporaryDirectory() as directory:
        writes: list[tuple[str, dict[str, object]]] = []

        def fake_upsert(entity: str, _url: str, payload: dict[str, object], **_kwargs: object) -> dict[str, str]:
            writes.append((entity, payload))
            return {"record_id": "rec-1"}

        with patch.object(id_business, "table_url_from_args", return_value="https://example.test/accounts"), patch.object(
            id_business, "opportunity_table_url", return_value="https://example.test/opportunities"
        ), patch.object(
            id_business,
            "upsert_entity_record",
            side_effect=fake_upsert,
        ):
            result = id_business.write_business_model_v2(fields, {}, tenant_id=TENANT_ID, root=directory)
        opportunity = next(payload for entity, payload in writes if entity == "BusinessOpportunity")
        assert opportunity["valid_from"] == "2026-09-02"
        assert opportunity["valid_until"] == "2026-09-03"
        assert opportunity["schedule"] == "2026-09-02 至 2026-09-03"
        payload = schedule_snapshot_path(tenant_id=TENANT_ID, root=directory).read_text(encoding="utf-8")
        snapshot = json.loads(payload)
        assert snapshot["source_type"] == "business_opportunity"
        assert snapshot["provenance"]["opportunity_record_id"] == "rec-1"
        assert result["schedule_window"]["valid_from"] == "2026-09-02"
        context = build_media_context(
            tenant_id=TENANT_ID,
            platform="小红书",
            account="主账号",
            root=directory,
            now=datetime(2026, 8, 29, 9, tzinfo=LOCAL_TZ),
        )
        assert context["schedule"][0]["title"] == "测试品牌商单档期"
        adapted = BusinessAdapter().to_record(
            {
                "record_id": "rec-1",
                "opportunity_id": "opp-1",
                "brand": "测试品牌",
                "valid_from": "2026-09-02",
                "valid_until": "2026-09-03",
                "schedule": "2026-09-02 至 2026-09-03",
            }
        )
        assert adapted.start_time.startswith("2026-09-02")
        assert adapted.end_time.startswith("2026-09-03")
        assert adapted.detail_json["schedule"] == "2026-09-02 至 2026-09-03"


def test_external_business_failure_does_not_create_schedule_snapshot() -> None:
    fields = {
        "平台": "小红书",
        "作者ID": "creator-1",
        "账号名称": "主账号",
        "品牌": "测试品牌",
        "具体档期": "2026-09-10",
    }
    with tempfile.TemporaryDirectory() as directory:
        with patch.object(id_business, "table_url_from_args", return_value="https://example.test/accounts"), patch.object(
            id_business, "opportunity_table_url", return_value="https://example.test/opportunities"
        ), patch.object(id_business, "upsert_entity_record", side_effect=RuntimeError("external down")):
            try:
                id_business.write_business_model_v2(fields, {}, tenant_id=TENANT_ID, root=directory)
            except id_business.BusinessExternalRetryRequired:
                pass
        assert not schedule_snapshot_path(tenant_id=TENANT_ID, root=directory).exists()


def test_shooting_conflict_requires_manual_review_and_unstructured_time_does_not_fake_conflict() -> None:
    context = {
        "schedule": [
            {
                "title": "品牌商单",
                "starts_at": "2026-09-10T18:00:00+08:00",
                "ends_at": "2026-09-10T19:00:00+08:00",
            }
        ]
    }
    with patch("selfmedia.creation.shooting_execution.call_creation_json", return_value=_draft("2026-09-10 18:15-18:45")):
        conflicted = generate_shooting_execution_plan(_request(publish_time="2026-09-10 18:30"), media_context=context)
    assert conflicted["schedule_conflict_status"] == "needs_review"
    assert conflicted["schedule_conflicts"]
    assert validate_shooting_execution_plan(conflicted)["status"] == "needs_review"
    with patch("selfmedia.creation.shooting_execution.call_creation_json", return_value=_draft("18:15-18:45")):
        unstructured = generate_shooting_execution_plan(_request(publish_time="今晚8点"), media_context=context)
    assert "schedule_conflicts" not in unstructured
