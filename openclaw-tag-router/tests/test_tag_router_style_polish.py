from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys


TAG_ROUTER_ROOT = Path(__file__).resolve().parents[1]
SELFMEDIA_ROOT = TAG_ROUTER_ROOT.parents[0]
for path in (SELFMEDIA_ROOT, TAG_ROUTER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from openclaw_app.models.message import Message
from openclaw_app.router.style_polish import STYLE_POLISH_TAGS, StylePolishMixin
from openclaw_app.router.tag_capabilities import TAG_CAPABILITIES


TENANT_ID = "00000000-0000-4000-8000-000000000101"


class StylePolishHarness(StylePolishMixin):
    pass


class StylePolishRouterTests(unittest.TestCase):
    def test_style_polish_alias_capabilities_share_one_handler_and_capability(self) -> None:
        capabilities = {item.label: item for item in TAG_CAPABILITIES}
        self.assertEqual(STYLE_POLISH_TAGS, {"润色", "网感", "文案优化", "改标题", "去AI味", "小红书文案", "抖音文案"})
        for label in STYLE_POLISH_TAGS:
            with self.subTest(label=label):
                self.assertIn(label, capabilities)
                self.assertEqual(capabilities[label].capability, "style_polish")
                self.assertEqual(capabilities[label].handler, "handle_style_polish")

    def test_style_polish_handler_returns_only_the_publishable_copy(self) -> None:
        message = Message(
            entry_tag="网感",
            raw_text="【网感】平台：抖音\n必须保留：训练不是靠鸡血\n原文：在当今时代，训练不是靠鸡血，而是靠复盘和稳定执行。",
            body="平台：抖音\n必须保留：训练不是靠鸡血\n原文：在当今时代，训练不是靠鸡血，而是靠复盘和稳定执行。",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={"tenant_id": TENANT_ID},
        )
        payload = {
            "run_id": "style_polish_test",
            "artifact_uri": "media://style_polish_runs/style_polish_test/result.json",
            "diagnosis": ["原文太书面。"],
            "versions": [
                {
                    "name": "自然表达版",
                    "text": "训练不是靠鸡血。对我来说，真正有用的是每次练完都复盘，再把该做的事稳定做下去。",
                }
            ],
            "recommended_version": "自然表达版",
            "source_trace": [{"source_type": "platform_mechanism", "loaded": True, "source": "xiaohongshu.json"}],
            "risk_notes": [],
            "creation_run_binding": {"bound": False},
            "feedback_record": {"creative_pattern_promotion": "manual_only"},
        }
        fake_result = SimpleNamespace(run_id="style_polish_test", to_dict=lambda: payload)
        with patch("openclaw_app.router.style_polish.run_style_polish", return_value=fake_result):
            result = StylePolishHarness().handle_style_polish(message)

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "style_polish_done")
            self.assertEqual(
                result.reply,
                "训练不是靠鸡血。对我来说，真正有用的是每次练完都复盘，再把该做的事稳定做下去。",
            )
            self.assertNotIn("run_id", result.reply)
            self.assertNotIn("artifact", result.reply)
            self.assertNotIn("source_trace", result.reply)
            self.assertNotIn("诊断", result.reply)
            self.assertFalse(result.extra["creation_run_binding"]["bound"])
            self.assertEqual(result.extra["feedback_record"]["creative_pattern_promotion"], "manual_only")

    def test_style_polish_docx_link_requires_modify_without_vault_artifact(self) -> None:
        message = Message(
            entry_tag="润色",
            raw_text="【润色】请润色这个文档：https://example.feishu.cn/docx/AbCdEfGhIjKlMnOp",
            body="请润色这个文档：https://example.feishu.cn/docx/AbCdEfGhIjKlMnOp",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={},
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": tmp}):
            with patch("openclaw_app.router.style_polish.run_style_polish") as run_style_polish:
                result = StylePolishHarness().handle_style_polish(message)

            run_style_polish.assert_not_called()
            self.assertFalse(result.ok)
            self.assertEqual(result.status, "style_polish_requires_modify")
            self.assertIn("请改用【修改】", result.reply)
            self.assertFalse((Path(tmp) / "style_polish_runs").exists())

    def test_style_polish_reply_doc_metadata_requires_modify_without_vault_artifact(self) -> None:
        message = Message(
            entry_tag="去AI味",
            raw_text="【去AI味】这段改得自然点",
            body="这段改得自然点",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={
                "parent_id": "om_doc_message",
                "conversation_context": {
                    "items": [
                        {
                            "message_id": "om_doc_message",
                            "message_type": "docx",
                            "text": "创作稿",
                            "url": "https://example.feishu.cn/wiki/AbCdEfGhIjKlMnOp",
                        }
                    ]
                },
            },
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": tmp}):
            with patch("openclaw_app.router.style_polish.run_style_polish") as run_style_polish:
                result = StylePolishHarness().handle_style_polish(message)

            run_style_polish.assert_not_called()
            self.assertFalse(result.ok)
            self.assertEqual(result.status, "style_polish_requires_modify")
            self.assertIn("style_polish_runs", result.reply)
            self.assertFalse((Path(tmp) / "style_polish_runs").exists())


if __name__ == "__main__":
    unittest.main()
