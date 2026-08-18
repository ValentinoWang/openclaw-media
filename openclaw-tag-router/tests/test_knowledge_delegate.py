from __future__ import annotations

import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from openclaw_app.models.message import Message
from openclaw_app.models.task import TaskResult
from openclaw_app.router.knowledge_delegate import KnowledgeDelegateMixin
from openclaw_app.router.tag_router import TagRouter


class KnowledgeRouteHarness(TagRouter):
    def __init__(self) -> None:
        self.source = "feishu"
        self.chat_type = "private"
        self.timezone = "Asia/Shanghai"
        self.captured_thinking_level = ""

    def _delegate_to_knowledge_bot(self, message: Message, *, thinking_level: str) -> TaskResult:
        self.captured_thinking_level = thinking_level
        return TaskResult(ok=True, status="captured", reply="ok", task_id="")


class KnowledgeDelegateThinkingTest(unittest.TestCase):
    def test_explicit_tag_thinking_metadata_cannot_override_profile_tier(self) -> None:
        message = Message(
            entry_tag="补全",
            raw_text="【补全^xhigh】内容",
            body="内容",
            created_at=datetime(2026, 1, 1),
            metadata={"tag_thinking": "xhigh"},
        )

        self.assertEqual(KnowledgeDelegateMixin()._knowledge_thinking_level(message), "high")

    def test_completion_route_uses_profile_thinking(self) -> None:
        router = KnowledgeRouteHarness()

        result = router.route("补全", "内容", metadata={"tag_thinking": "xhigh"})

        self.assertTrue(result.ok)
        self.assertEqual(router.captured_thinking_level, "high")

    def test_delegate_always_uses_knowledge_delegate_profile(self) -> None:
        message = Message(
            entry_tag="补全",
            raw_text="【补全】内容",
            body="内容",
            created_at=datetime(2026, 1, 1),
            metadata={},
        )
        captured: list[str] = []
        runtime = SimpleNamespace(
            bin="/tmp/openclaw",
            agent="knowledge",
            timeout=1,
            cwd="/tmp",
            codex_home="/tmp/codex-home",
            model="openai/gpt-5.6-sol",
            thinking="medium",
        )

        def fake_profile_config(profile_name: str) -> dict[str, str]:
            captured.append(profile_name)
            return {"provider": "openclaw_codex"}

        with patch("openclaw_app.router.knowledge_delegate.profile_config", side_effect=fake_profile_config), patch(
            "openclaw_app.router.knowledge_delegate.profile_runtime", return_value=runtime
        ), patch(
            "openclaw_app.router.knowledge_delegate.run_media_subprocess_with_watchdog",
            return_value=SimpleNamespace(returncode=0, stdout=json.dumps({"reply": "done"}), stderr=""),
        ):
            result = KnowledgeDelegateMixin()._delegate_to_knowledge_bot(message, thinking_level="high")

        self.assertTrue(result.ok)
        self.assertEqual(captured, ["knowledge_delegate"])

    def test_cognition_route_delegates_to_knowledge_bot(self) -> None:
        router = KnowledgeRouteHarness()

        result = router.route("认知", "今天意识到短期反馈不能代表长期能力")

        self.assertTrue(result.ok)
        self.assertEqual(router.captured_thinking_level, "high")

    def test_delegate_message_does_not_reenter_tag_router(self) -> None:
        message = Message(
            entry_tag="补全",
            raw_text="【补全】一段口语转写内容",
            body="一段口语转写内容",
            created_at=datetime(2026, 1, 1),
            metadata={},
        )

        delegated = KnowledgeDelegateMixin()._knowledge_delegate_user_message(message)

        self.assertFalse(delegated.startswith("【"))
        self.assertIn("不要调用 tag-router bridge", delegated)
        self.assertIn("不要再次执行标签路由", delegated)
        self.assertIn("原始标签：补全", delegated)
        self.assertIn("一段口语转写内容", delegated)

    def test_delegate_command_passes_internal_message_to_openclaw(self) -> None:
        message = Message(
            entry_tag="补全",
            raw_text="【补全】一段口语转写内容",
            body="一段口语转写内容",
            created_at=datetime(2026, 1, 1),
            metadata={},
        )
        captured: dict[str, list[str]] = {}

        def fake_run(cmd, **_kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout=json.dumps({"reply": "done"}), stderr="")

        runtime = SimpleNamespace(
            bin="/tmp/openclaw",
            agent="knowledge",
            timeout=1,
            cwd="/tmp",
            codex_home="/tmp/codex-home",
            model="openai/gpt-5.6-sol",
            thinking="medium",
        )
        with patch("openclaw_app.router.knowledge_delegate.profile_config", return_value={"provider": "openclaw_codex"}), patch(
            "openclaw_app.router.knowledge_delegate.profile_runtime",
            return_value=runtime,
        ), patch("openclaw_app.router.knowledge_delegate.run_media_subprocess_with_watchdog", side_effect=fake_run):
            result = KnowledgeDelegateMixin()._delegate_to_knowledge_bot(message, thinking_level="high")

        self.assertTrue(result.ok)
        self.assertNotIn("--model", captured["cmd"])
        self.assertNotIn("--thinking", captured["cmd"])
        self.assertTrue(captured["cmd"][captured["cmd"].index("--session-id") + 1].startswith("knowledge-delegate-"))
        delegated = captured["cmd"][captured["cmd"].index("--message") + 1]
        self.assertFalse(delegated.startswith("【"))
        self.assertIn("不要调用 tag-router bridge", delegated)
        self.assertIn("原始标签：补全", delegated)

    def test_cognition_delegate_message_keeps_original_label(self) -> None:
        message = Message(
            entry_tag="认知",
            raw_text="【认知】今天意识到短期反馈不能代表长期能力",
            body="今天意识到短期反馈不能代表长期能力",
            created_at=datetime(2026, 1, 1),
            metadata={},
        )

        delegated = KnowledgeDelegateMixin()._knowledge_delegate_user_message(message)

        self.assertFalse(delegated.startswith("【"))
        self.assertIn("原始标签：认知", delegated)
        self.assertIn("今天意识到短期反馈不能代表长期能力", delegated)


if __name__ == "__main__":
    unittest.main()
