from __future__ import annotations

import io
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import yaml

from openclaw_app.app import OpenClawApp
from openclaw_app.services.utils import parse_tag_message, parse_tag_message_with_metadata


def load_bridge_module():
    bridge_path = Path(__file__).resolve().parents[1] / "bridge.py"
    spec = importlib.util.spec_from_file_location("openclaw_tag_router_bridge", bridge_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BridgeProtocolTest(unittest.TestCase):
    def test_app_uses_daily_checklist_archive_root_independent_from_schedule_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = {
                "workspace_root": str(root / "workspace"),
                "source": "feishu",
                "chat_type": "private",
                "timezone": "Asia/Shanghai",
                "feishu": {"local_docs_dir": str(root / "docs")},
                "content_flow": {"base_url": ""},
                "mac_agent": {
                    "mode": "local",
                    "queue_dir": str(root / "queue"),
                    "obsidian_root": str(root / "obsidian" / "日程"),
                    "local_obsidian_root": str(root / "obsidian" / "日程"),
                },
                "daily_checklist": {"archive_root": str(root / "obsidian" / "Archieve")},
                "feishu_reminder": {"enabled": False},
            }
            settings_path = root / "settings.yaml"
            settings_path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")

            app = OpenClawApp(settings_path)

            service = app.router.obsidian_daily_checklist_service
            self.assertEqual(service.archive_root, root / "obsidian" / "Archieve")

    def test_normalizes_native_openclaw_timestamp_prefix_before_tag(self) -> None:
        bridge = load_bridge_module()

        text = bridge._normalize_tag_protocol_text("[Fri 2026-05-29 04:09 GMT+8] 【说明】")

        self.assertEqual(text, "【说明】")

    def test_leaves_plain_non_tag_text_untouched(self) -> None:
        bridge = load_bridge_module()

        text = bridge._normalize_tag_protocol_text("普通聊天")

        self.assertEqual(text, "普通聊天")

    def test_bridge_progress_writes_to_stderr_only(self) -> None:
        bridge = load_bridge_module()
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            bridge._bridge_progress("route_start", mode="ingest", text_preview="【说明】")

        self.assertIn("[tag-router-bridge] stage=route_start", stderr.getvalue())
        self.assertIn("mode=ingest", stderr.getvalue())

    def test_legacy_tag_aliases_normalize_before_routing(self) -> None:
        self.assertEqual(parse_tag_message("【帮助】media")[0], "说明")
        self.assertEqual(parse_tag_message("【自媒体】https://xhslink.com/xxx")[0], "自媒体知识")

    def test_business_author_tag_routes_to_id_business(self) -> None:
        tag, body = parse_tag_message("【商务>小王】辛苦填下")

        self.assertEqual(tag, "商务>ID")
        self.assertEqual(body, "作者ID：小王\n辛苦填下")

    def test_retired_business_tags_do_not_normalize(self) -> None:
        self.assertEqual(parse_tag_message("【商务-ID】主页链接")[0], "商务-ID")
        self.assertEqual(parse_tag_message("【ID+商务】主页链接")[0], "ID+商务")
        self.assertEqual(parse_tag_message("【商务-ID>小王】辛苦填下")[0], "商务-ID>小王")
        self.assertEqual(parse_tag_message("【商务>ID>小王】辛苦填下")[0], "商务>ID>小王")
        self.assertEqual(parse_tag_message("【商务-小王】辛苦填下")[0], "商务-小王")


    def test_creator_profile_tags_route_directly(self) -> None:
        self.assertEqual(parse_tag_message("【博主】")[0], "博主")
        self.assertEqual(parse_tag_message("【博主-入库】平台ID：123")[0], "博主-入库")

    def test_recreation_depth_tags_route_directly(self) -> None:
        self.assertEqual(parse_tag_message("【拆解-再创】爆款链接")[0], "拆解-再创")
        self.assertEqual(parse_tag_message("【拆解-再创-简略】爆款链接")[0], "拆解-再创-简略")
        self.assertEqual(parse_tag_message("【拆解-再创-详细】爆款链接")[0], "拆解-再创-详细")

    def test_transcription_text_tag_routes_directly(self) -> None:
        tag, body = parse_tag_message("【转写-文字】文字稿：今天讨论了项目安排")

        self.assertEqual(tag, "转写-文字")
        self.assertEqual(body, "文字稿：今天讨论了项目安排")

    def test_tag_thinking_suffix_is_metadata_not_route_tag(self) -> None:
        tag, body, metadata = parse_tag_message_with_metadata("【归档^high】一段资料")

        self.assertEqual(tag, "归档")
        self.assertEqual(body, "一段资料")
        self.assertEqual(metadata["raw_entry_tag"], "归档^high")
        self.assertEqual(metadata["tag_thinking_suffix"], "high")
        self.assertEqual(metadata["tag_thinking"], "high")

    def test_xhigh_tag_thinking_suffix_maps_to_supported_high(self) -> None:
        tag, body, metadata = parse_tag_message_with_metadata("【学习^xhigh】API")

        self.assertEqual(tag, "学习")
        self.assertEqual(body, "API")
        self.assertEqual(metadata["tag_thinking_suffix"], "xhigh")
        self.assertEqual(metadata["tag_thinking"], "high")

    def test_hyphen_is_no_longer_tag_thinking_suffix(self) -> None:
        tag, body, metadata = parse_tag_message_with_metadata("【归档-high】一段资料")

        self.assertEqual(tag, "归档-high")
        self.assertEqual(body, "一段资料")
        self.assertNotIn("tag_thinking", metadata)

    def test_codex_trigger_is_detected_anywhere(self) -> None:
        bridge = load_bridge_module()

        self.assertTrue(bridge._contains_codex_trigger("【codex】修复路由"))
        self.assertTrue(bridge._contains_codex_trigger("请处理【Codex】这个问题"))
        self.assertFalse(bridge._contains_codex_trigger("蒸馏 #codex 内容"))

    def test_ingest_codex_trigger_delegates_before_tag_routing(self) -> None:
        bridge = load_bridge_module()
        payload = {"text": "前缀内容【codex】修复标签路由"}
        stdout = io.StringIO()

        with (
            patch.object(sys, "argv", ["bridge.py", "ingest", "/tmp/openclaw-test", "/tmp/missing-settings.yaml"]),
            patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
            patch.object(bridge, "_delegate_to_codex_maintenance", return_value={"ok": True, "status": "delegated_to_codex_maintenance", "reply": "done"}),
            redirect_stderr(io.StringIO()),
            patch("sys.stdout", stdout),
        ):
            exit_code = bridge._main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "delegated_to_codex_maintenance")


if __name__ == "__main__":
    unittest.main()
