from __future__ import annotations

import unittest
from datetime import datetime

from openclaw_app.models.message import Message
from openclaw_app.router.system_routes import SystemRoutesMixin
from openclaw_app.router.tag_capabilities import TAG_CAPABILITIES
from openclaw_app.router.tag_router_common import BOT_CAPABILITY_IDENTITIES


class SystemRoutesHarness(SystemRoutesMixin):
    pass


FORBIDDEN_DESCRIPTION_TERMS = (
    "路由事实",
    "权限事实",
    "标签能力单一事实",
    "单一事实",
    "兼容",
    "回退",
    "fallback",
)
UNIFIED_CAPABILITY_FIELDS = (
    "  - 能实现什么：",
    "  - 输入格式：",
)
VALID_CAPABILITY_BOTS = {"任意 Bot", *BOT_CAPABILITY_IDENTITIES.values()}


class SystemRoutesTest(unittest.TestCase):
    def _capability_reply(self, account_id: str) -> str:
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={"account_id": account_id},
        )
        result = SystemRoutesHarness().handle_说明(message)
        self.assertTrue(result.ok)
        return result.reply

    def test_capability_bot_uses_feishu_account_id_metadata(self) -> None:
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={"account_id": "daily"},
        )

        bot_label = SystemRoutesHarness()._current_capability_bot(message)

        self.assertEqual(bot_label, "Daily bot")

    def test_capability_bot_rejects_compatibility_alias(self) -> None:
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={"account_id": "feishu-knowledge"},
        )

        bot_label = SystemRoutesHarness()._current_capability_bot(message)

        self.assertEqual(bot_label, "")

    def test_capability_description_requires_identity(self) -> None:
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={},
        )

        result = SystemRoutesHarness().handle_说明(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "missing_bot_identity")

    def test_capability_description_does_not_infer_identity_from_source(self) -> None:
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="daily",
            chat_type="private",
            created_at=datetime.now(),
            metadata={},
        )

        result = SystemRoutesHarness().handle_说明(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "missing_bot_identity")

    def test_capability_description_uses_unified_format(self) -> None:
        reply = self._capability_reply("daily")

        self.assertIn("当前 Bot：", reply)
        self.assertIn("基础规则：", reply)
        self.assertIn("能力标签：", reply)
        self.assertIn("- `【待办】`", reply)
        self.assertIn("  - 输入格式：`【整理】正文内容`", reply)
        for field in UNIFIED_CAPABILITY_FIELDS:
            self.assertIn(field, reply)
        self.assertNotIn("  - 用途：", reply)
        self.assertNotIn("  - 结果：", reply)
        self.assertNotIn("  - 示例：", reply)
        for term in FORBIDDEN_DESCRIPTION_TERMS:
            self.assertNotIn(term, reply)

    def test_capability_catalog_is_valid_for_description_generation(self) -> None:
        labels = [capability.label for capability in TAG_CAPABILITIES]
        self.assertEqual(len(labels), len(set(labels)))
        for capability in TAG_CAPABILITIES:
            self.assertIn(capability.bot, VALID_CAPABILITY_BOTS)
            self.assertTrue(capability.label.strip())
            self.assertTrue(capability.purpose.strip())
            self.assertTrue(capability.result.strip())
            self.assertTrue(capability.example.strip())
            for term in FORBIDDEN_DESCRIPTION_TERMS:
                self.assertNotIn(term, capability.purpose)
                self.assertNotIn(term, capability.result)
                self.assertNotIn(term, capability.example)

    def test_all_bot_descriptions_render_every_capability_with_unified_fields(self) -> None:
        harness = SystemRoutesHarness()
        for account_id, bot_label in BOT_CAPABILITY_IDENTITIES.items():
            with self.subTest(account_id=account_id):
                reply = self._capability_reply(account_id)
                lines = reply.splitlines()
                capabilities = harness._bot_capabilities(bot_label)
                for capability in capabilities:
                    marker = f"- `【{capability.label}】`"
                    self.assertIn(marker, lines)
                    index = lines.index(marker)
                    for offset, field in enumerate(UNIFIED_CAPABILITY_FIELDS, start=1):
                        self.assertLess(index + offset, len(lines))
                        self.assertTrue(lines[index + offset].startswith(field))
                for term in FORBIDDEN_DESCRIPTION_TERMS:
                    self.assertNotIn(term, reply)

    def test_bot_descriptions_include_domain_specific_guidance(self) -> None:
        expected = {
            "media": ("Content OS 工作流", "  - 适合场景：需要逐镜头看开头、转场、节奏、结构、文案和可复刻点。"),
            "daily": ("管理待办、日程、开发任务和今日执行清单", "  - 适合场景：需要未来某个时间提醒你处理，但不一定占用日历。"),
            "knowledge": ("把知识沉淀成可复用资产", "  - 适合场景：概念解释、知识拆解、课程笔记、文章重点理解。"),
            "social": ("沉淀人物交互、关系状态、人脉合作和社交复盘", "  - 适合场景：整理某个人的聊天记录、互动状态、关系判断、风险点和下一步行动。"),
            "main": ("统一入口说明", "  - 适合场景：不知道该发给哪个 Bot 或不知道某个标签怎么写。"),
        }
        for account_id, markers in expected.items():
            with self.subTest(account_id=account_id):
                reply = self._capability_reply(account_id)
                for marker in markers:
                    self.assertIn(marker, reply)


if __name__ == "__main__":
    unittest.main()
