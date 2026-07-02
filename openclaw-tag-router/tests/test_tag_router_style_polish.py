from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
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

    def test_style_polish_handler_writes_vault_artifact(self) -> None:
        message = Message(
            entry_tag="网感",
            raw_text="【网感】平台：抖音\n必须保留：训练不是靠鸡血\n原文：在当今时代，训练不是靠鸡血，而是靠复盘和稳定执行。",
            body="平台：抖音\n必须保留：训练不是靠鸡血\n原文：在当今时代，训练不是靠鸡血，而是靠复盘和稳定执行。",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={},
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": tmp}):
            result = StylePolishHarness().handle_style_polish(message)
            self.assertTrue(result.ok)
            self.assertEqual(result.status, "style_polish_done")
            self.assertIn("artifact：media://style_polish_runs/", result.reply)
            self.assertIn("source_trace：", result.reply)
            self.assertTrue((Path(tmp) / "style_polish_runs" / result.task_id / "result.json").exists())
            self.assertFalse(result.extra["creation_run_binding"]["bound"])
            self.assertEqual(result.extra["feedback_record"]["creative_pattern_promotion"], "manual_only")


if __name__ == "__main__":
    unittest.main()
