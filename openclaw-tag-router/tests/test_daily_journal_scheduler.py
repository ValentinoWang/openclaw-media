from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from openclaw_app.router.daily_journal_contract import DAILY_JOURNAL_TEMPLATE
from scripts import daily_journal_scheduler as scheduler


class DailyJournalSchedulerTest(unittest.TestCase):
    def test_latest_daily_delivery_target_reads_session_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions.json"
            path.write_text(
                json.dumps(
                    {
                        "old": {
                            "updatedAt": 1,
                            "deliveryContext": {"channel": "feishu", "accountId": "daily", "to": "user:old"},
                        },
                        "latest": {
                            "updatedAt": 2,
                            "deliveryContext": {"channel": "feishu", "accountId": "daily", "to": "user:latest"},
                        },
                        "other": {
                            "updatedAt": 3,
                            "deliveryContext": {"channel": "feishu", "accountId": "media", "to": "user:media"},
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(scheduler.latest_daily_delivery_target(path), "user:latest")

    def test_daily_prompt_dry_run_sends_contract_template(self) -> None:
        settings = {
            "workspace_root": "/tmp/openclaw",
            "daily_journal": {
                "notification_target": "user:test",
                "notification_account": "daily",
                "notification_channel": "feishu",
            },
        }
        calls: list[dict[str, object]] = []

        def fake_send(settings_arg: dict, target: str, text: str, *, dry_run: bool) -> dict:
            calls.append({"settings": settings_arg, "target": target, "text": text, "dry_run": dry_run})
            return {"ok": True, "result": {"dryRun": True}}

        with patch.object(scheduler, "send_feishu_message", side_effect=fake_send):
            result = scheduler.daily_prompt(
                settings,
                now=datetime(2026, 7, 3, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                dry_run=True,
                force=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(calls[0]["target"], "user:test")
        self.assertEqual(calls[0]["text"], DAILY_JOURNAL_TEMPLATE)
        self.assertTrue(calls[0]["dry_run"])

    def test_weekly_summary_dry_run_uses_explicit_week_and_delivery_dry_run(self) -> None:
        settings = {
            "timezone": "Asia/Shanghai",
            "workspace_root": "/tmp/openclaw",
            "daily_journal": {
                "notification_target": "user:test",
                "notification_account": "daily",
                "notification_channel": "feishu",
            },
        }
        calls: list[dict[str, object]] = []

        def fake_send(settings_arg: dict, target: str, text: str, *, dry_run: bool) -> dict:
            calls.append({"settings": settings_arg, "target": target, "text": text, "dry_run": dry_run})
            return {"ok": True, "result": {"dryRun": True}}

        with patch.object(scheduler, "send_feishu_message", side_effect=fake_send):
            result = scheduler.weekly_summary(
                settings,
                Path("/tmp/settings.yaml"),
                now=datetime(2026, 7, 5, 23, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
                dry_run=True,
                force=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["week"], "20260629-20260705")
        self.assertEqual(result["scheduledText"], "【周记】20260629-20260705")
        self.assertIn("【周记】20260629-20260705", calls[0]["text"])
        self.assertTrue(calls[0]["dry_run"])

    def test_send_feishu_message_uses_resolved_openclaw_binary_and_augmented_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            openclaw_bin = bin_dir / "openclaw"
            openclaw_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            settings = {
                "daily_journal": {
                    "openclaw_bin": str(openclaw_bin),
                    "notification_account": "daily",
                    "notification_channel": "feishu",
                }
            }
            captured: dict[str, object] = {}

            def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                captured["cmd"] = cmd
                captured["env"] = kwargs.get("env")
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"ok": True}), stderr="")

            with patch.object(scheduler.subprocess, "run", side_effect=fake_run):
                result = scheduler.send_feishu_message(settings, "user:test", "hello", dry_run=True)

        self.assertTrue(result["ok"])
        self.assertEqual(captured["cmd"][0], str(openclaw_bin))
        env = captured["env"]
        self.assertIsInstance(env, dict)
        self.assertEqual(str(env["PATH"]).split(":")[0], str(bin_dir))


if __name__ == "__main__":
    unittest.main()
