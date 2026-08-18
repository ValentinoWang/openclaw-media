import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from openclaw_app.services.deepmath_people_runtime import (
    DeepMathPeopleRuntimeTransport,
    load_people_capability_base_id,
)
from openclaw_app.services.deepmath_resources import DeepMathResourceConfig


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class Session:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs.get("params") or {}))
        return Response(self.payloads.pop(0))


def resource():
    return DeepMathResourceConfig(
        tenant_key="deepmath",
        base_name="DeepMath CEO Thinking",
        tasklist_name="DeepMath CEO Actions",
        calendar_name="DeepMath CEO Calendar",
        timezone="Asia/Shanghai",
        base_id="appThinking",
        tasklist_id="tasklistDeepMath",
        calendar_id="calendarDeepMath",
        base_url="https://example.feishu.cn/base/appThinking",
        tenant_proof="tenant-proof",
    )


class DeepMathPeopleRuntimeTest(unittest.TestCase):
    def test_settings_has_one_required_binding(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.yaml"
            path.write_text(
                "deepmath_ceo_thinking:\n  people_capability_base_id: appCapability123\n",
                encoding="utf-8",
            )
            self.assertEqual(load_people_capability_base_id(path), "appCapability123")

    def test_four_sources_are_get_only_and_capability_is_independent(self):
        session = Session([
            {"code": 0, "data": {"items": [{"open_id": "user-a", "name": "甲", "department_ids": ["dep-a"]}], "has_more": False}},
            {"code": 0, "data": {"items": [{"name": "成员能力与容量", "table_id": "table-a"}], "has_more": False}},
            {"code": 0, "data": {"items": [{"fields": {
                "成员": [{"id": "user-a"}], "职责范围": "研究", "核心技能": "证明",
                "可承担角色": "DRI", "技能证据": "人工确认", "未来7天可分配工时": "4",
                "负荷确认时间": 1785772800000, "负荷有效至": 1786377600000,
                "记录状态": "有效", "维护人": [{"id": "user-a"}],
            }}], "has_more": False}},
            {"code": 0, "data": {"items": [], "has_more": False}},
            {"code": 0, "data": {"items": [], "has_more": False}},
        ])
        transport = DeepMathPeopleRuntimeTransport(
            capability_app_token="appCapability123",
            resource=resource(),
            access_token="access-token",
            session=session,
            clock=lambda: datetime(2026, 8, 4, tzinfo=timezone.utc),
        )
        directory = transport.get_directory_page(None)
        capabilities = transport.get_capability_records()
        tasks = transport.get_tasks_snapshot()
        calendar = transport.get_calendar_snapshot()

        self.assertEqual(directory.records, [{"directory_id": "user-a", "name": "甲", "department": ["dep-a"]}])
        self.assertNotIn("capability", directory.records[0])
        self.assertEqual(capabilities[0]["directory_id"], "user-a")
        self.assertEqual(capabilities[0]["status"], "有效")
        self.assertEqual(capabilities[0]["declared_hours"], 4.0)
        self.assertEqual(tasks, [])
        self.assertEqual(calendar, [])
        self.assertTrue(session.calls)
        self.assertEqual({call[0] for call in session.calls}, {"GET"})


if __name__ == "__main__":
    unittest.main()
