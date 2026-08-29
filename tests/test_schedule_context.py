from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from selfmedia.business import id_business
from selfmedia.business.schedule import LOCAL_TZ, is_expired_schedule_value, project_reminder_schedule, upcoming_schedule_entries
from selfmedia.context import build_media_context
from selfmedia.creation.shooting_execution import ShootingExecutionRequest, generate_shooting_execution_plan


TENANT_ID = "00000000-0000-4000-8000-000000000101"


class ScheduleContextTest(unittest.TestCase):
    def test_relative_and_boundary_windows_use_injected_clock(self) -> None:
        december_end = datetime(2026, 12, 31, 10, tzinfo=LOCAL_TZ)

        self.assertFalse(is_expired_schedule_value("下月上旬", now=december_end))
        self.assertFalse(is_expired_schedule_value("2026-12-31 至 2027-01-02", now=datetime(2027, 1, 1, tzinfo=LOCAL_TZ)))
        self.assertTrue(is_expired_schedule_value("2026-12-31 至 2027-01-02", now=datetime(2027, 1, 3, tzinfo=LOCAL_TZ)))
        self.assertFalse(is_expired_schedule_value("2026年12月31日至1月2日", now=datetime(2027, 1, 1, tzinfo=LOCAL_TZ)))
        self.assertTrue(is_expired_schedule_value("2026年12月31日至1月2日", now=datetime(2027, 1, 3, tzinfo=LOCAL_TZ)))
        self.assertFalse(is_expired_schedule_value("2026-08-10", now=datetime(2026, 8, 10, tzinfo=LOCAL_TZ)))
        self.assertTrue(is_expired_schedule_value("2026-08-10", now=datetime(2026, 8, 11, tzinfo=LOCAL_TZ)))
        self.assertTrue(is_expired_schedule_value("8月10日", now=datetime(2026, 8, 11, tzinfo=LOCAL_TZ)))
        self.assertTrue(is_expired_schedule_value("昨天", now=datetime(2026, 8, 28, tzinfo=LOCAL_TZ)))
        self.assertFalse(is_expired_schedule_value("明天", now=datetime(2026, 8, 28, tzinfo=LOCAL_TZ)))

    def test_expired_schedule_forces_pending_and_creator_confirmation(self) -> None:
        fields = {
            "具体档期": "8月10日",
            "待补充字段": "视频报价",
            "需反问博主字段": "视频报价",
        }
        parsed = {"pending_fields": ["视频报价"], "confirmation_fields": ["视频报价"]}

        remaining = id_business.refresh_pending_fields_from_values(
            fields,
            parsed,
            now=datetime(2026, 8, 11, tzinfo=LOCAL_TZ),
        )

        self.assertNotIn("具体档期", fields)
        self.assertEqual(remaining, ["视频报价", "具体档期"])
        self.assertEqual(parsed["confirmation_fields"], ["视频报价", "具体档期"])
        self.assertEqual(fields["需反问博主字段"], "视频报价、具体档期")

        id_business.apply_business_reply_result(
            fields,
            {"status": "done", "reply": "档期已确认", "missing_fields": []},
            required_confirmation_fields=parsed["confirmation_fields"],
            now=datetime(2026, 8, 11, tzinfo=LOCAL_TZ),
        )

        self.assertEqual(fields["反问博主状态"], "pending")
        self.assertIn("具体档期", fields["需反问博主字段"])
        self.assertIn("具体档期", fields["反问博主话术"])

    def test_local_snapshot_enters_context_without_calendar_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tenants" / TENANT_ID / "schedule_snapshots.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "tenant_id": TENANT_ID,
                                "platform": "小红书",
                                "account": "主账号",
                                "title": "品牌初稿确认",
                                "starts_at": "2026-12-31T18:00:00+08:00",
                                "ends_at": "2026-12-31T19:00:00+08:00",
                            },
                            {
                                "tenant_id": TENANT_ID,
                                "platform": "小红书",
                                "account": "主账号",
                                "title": "已取消事项",
                                "starts_at": "2027-01-01T09:00:00+08:00",
                                "status": "cancelled",
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            context = build_media_context(
                tenant_id=TENANT_ID,
                platform="小红书",
                account="主账号",
                root=directory,
                now=datetime(2026, 12, 31, 9, tzinfo=LOCAL_TZ),
            )

        self.assertEqual(context["loaded"]["schedule"], 1)
        self.assertEqual(context["schedule"][0]["title"], "品牌初稿确认")
        self.assertIn("未来7天已确认档期（本地快照）", context["prompt"])
        self.assertIn("品牌初稿确认", context["prompt"])

    def test_schedule_adapter_filters_cross_tenant_and_past_entries(self) -> None:
        entries = upcoming_schedule_entries(
            [
                {"tenant_id": TENANT_ID, "title": "已结束", "starts_at": "2026-08-01T09:00:00+08:00"},
                {"tenant_id": "00000000-0000-4000-8000-000000000102", "title": "其他租户", "starts_at": "2026-08-29T09:00:00+08:00"},
                {"tenant_id": TENANT_ID, "title": "可用档期", "starts_at": "2026-08-29T09:00:00+08:00"},
            ],
            tenant_id=TENANT_ID,
            now=datetime(2026, 8, 28, 9, tzinfo=LOCAL_TZ),
        )

        self.assertEqual(entries, [{"title": "可用档期", "starts_at": "2026-08-29T09:00+08:00", "ends_at": "2026-08-29T09:00+08:00", "status": "confirmed"}])

    def test_commercial_reminder_projects_to_context_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reminder = {"ref_id": "delivery-1-draft", "due_at": "2026-08-29T18:00:00+08:00", "title": "商单初稿"}
            first = project_reminder_schedule(tenant_id=TENANT_ID, reminders=[reminder], platform="小红书", account="主账号", root=directory)
            second = project_reminder_schedule(tenant_id=TENANT_ID, reminders=[reminder], platform="小红书", account="主账号", root=directory)
            context = build_media_context(tenant_id=TENANT_ID, platform="小红书", account="主账号", root=directory, now=datetime(2026, 8, 29, 9, tzinfo=LOCAL_TZ))
        self.assertEqual(first[0]["status"], "recorded")
        self.assertEqual(second[0]["status"], "deduped")
        self.assertEqual(context["loaded"]["schedule"], 1)
        self.assertEqual(context["schedule"][0]["title"], "商单初稿")

    def test_shooting_prompt_protects_known_schedule_windows(self) -> None:
        request = ShootingExecutionRequest(
            platform="小红书",
            content_type="视频",
            track="训练",
            topic="起跑训练",
            shooting_goal="完成训练日视频",
            locations=["操场"],
            people=["博主"],
        )
        captured: list[str] = []
        draft = {
            "shooting_goal": {},
            "route_map": [{}],
            "must_shot_list": [{"priority": "P0"}],
            "branch_plans": [{"priority": "P1"}],
            "storyboard": [{}],
            "onsite_checklist": ["核对档期"],
            "publishing_pack": {"first_hour_action": "回复评论"},
            "evidence_appendix": [{"source_status": "confirmed"}],
        }

        with patch("selfmedia.creation.shooting_execution.call_creation_json", side_effect=lambda prompt, **_kwargs: captured.append(prompt) or draft):
            generate_shooting_execution_plan(
                request,
                media_context={"schedule": [{"title": "品牌初稿确认", "starts_at": "2026-12-31T18:00+08:00"}]},
            )

        self.assertIn("route_map 不得与其冲突", captured[0])
        self.assertIn("品牌初稿确认", captured[0])


if __name__ == "__main__":
    unittest.main()
