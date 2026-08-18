from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message
from openclaw_app.router.selfmedia_cognition import SelfmediaCognitionMixin


class FakeContentFlowClient:
    def __init__(self, results: list[dict]):
        self.results = list(results)
        self.calls = 0

    @staticmethod
    def _content_flow_env() -> dict:
        return {}

    def _call_postprocess_json(self, *_args, **_kwargs) -> dict:
        self.calls += 1
        if not self.results:
            raise AssertionError("unexpected extra LLM call")
        return self.results.pop(0)


class FakeFeishuService:
    def __init__(self):
        self.write_calls = 0

    @staticmethod
    def list_knowledge_child_nodes(_parent_node_token: str) -> list[dict[str, str]]:
        return []

    def replace_child_entry_under_node_blocks(self, *_args, **_kwargs):
        self.write_calls += 1
        raise AssertionError("pending cognition must not write Feishu")


class CognitionHarness(SelfmediaCognitionMixin):
    def __init__(self, results: list[dict]):
        self.content_flow_client = FakeContentFlowClient(results)
        self.feishu_service = FakeFeishuService()

    @staticmethod
    def _conversation_context_prompt(_message: Message) -> str:
        return ""


def make_message() -> Message:
    return Message(
        entry_tag="自媒体-认知",
        raw_text="【自媒体-认知】正文未提供",
        body="主题：Web 能力验收\n正文：未提供，请返回必填项",
        source="web",
        chat_type="private",
        created_at=datetime(2026, 7, 29, 6, 40, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


class SelfmediaCognitionTest(unittest.TestCase):
    def test_non_done_plan_stops_before_merge_and_write(self) -> None:
        harness = CognitionHarness(
            [
                {
                    "status": "missing_required_content",
                    "summary": "正文未提供，无法提炼可归档的自媒体认知。",
                    "data_gaps": ["缺少认知正文、判断依据或案例信息。"],
                }
            ]
        )

        result = harness.handle_selfmedia_cognition(make_message())

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "selfmedia_cognition_pending_manual")
        self.assertIn("已停止写入", result.reply)
        self.assertEqual(harness.content_flow_client.calls, 1)
        self.assertEqual(harness.feishu_service.write_calls, 0)

    def test_non_done_merge_stops_before_write(self) -> None:
        harness = CognitionHarness(
            [
                {
                    "status": "done",
                    "track": "通用",
                    "theme": "反馈边界需要真实样本",
                    "target_title": "自媒体认知｜通用｜反馈边界需要真实样本",
                },
                {
                    "status": "missing_required_content",
                    "content": "缺少必填项。",
                    "reason": "无可整合的认知正文。",
                },
            ]
        )

        result = harness.handle_selfmedia_cognition(make_message())

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "selfmedia_cognition_pending_manual")
        self.assertIn("无可整合的认知正文", result.reply)
        self.assertEqual(harness.content_flow_client.calls, 2)
        self.assertEqual(harness.feishu_service.write_calls, 0)


if __name__ == "__main__":
    unittest.main()
