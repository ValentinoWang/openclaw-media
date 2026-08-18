from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


def load_sync_module():
    path = Path("/home/ubuntu/selfmedia-tools/runtime/maintenance/sync/daily_todo_checklist_sync.py")
    spec = importlib.util.spec_from_file_location("daily_todo_checklist_sync", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DailyTodoChecklistSyncTest(unittest.TestCase):
    def test_syncs_only_checked_feishu_records_once(self) -> None:
        sync = load_sync_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Archieve"
            root.mkdir()
            weekly = root / "20260622-20260628.md"
            weekly.write_text(
                "\n".join(
                    [
                        "# 待办",
                        "- [x] 购买杠铃杆 <!-- openclaw:feishu_record=rec1;sync=todo_complete_v1 -->",
                        "- [ ] 购买起泡器 <!-- openclaw:feishu_record=rec2;sync=todo_complete_v1 -->",
                        "- [x] 整理购买清单",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            files = sync.recent_weekly_files(root, date(2026, 6, 28), 7)
            candidates = sync.find_checked_feishu_items(files)
            calls: list[str] = []
            state = {}

            synced = sync.sync_candidates(candidates, state, lambda record_id: calls.append(record_id))
            synced_again = sync.sync_candidates(candidates, state, lambda record_id: calls.append(record_id))

            self.assertEqual(calls, ["rec1"])
            self.assertEqual([item["record_id"] for item in synced], ["rec1"])
            self.assertEqual(synced_again, [])
            self.assertIn("rec1", state)
            self.assertNotIn("rec2", state)

    def test_runner_loads_env_files_for_complete_record(self) -> None:
        sync = load_sync_module()
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "feishu.env"
            env_file.write_text("FEISHU_APP_ID=cli_app\nFEISHU_APP_SECRET=cli_secret\n", encoding="utf-8")
            env = sync.load_env_files([str(env_file)])
            captured = {}

            def fake_run(*args, **kwargs):
                captured["args"] = args
                captured["kwargs"] = kwargs
                return None

            with patch.object(sync.subprocess, "run", side_effect=fake_run):
                runner = sync.reminder_complete_runner("/usr/bin/python3", "/tmp/reminder.py", env)
                runner("rec1")

            self.assertEqual(captured["kwargs"]["env"]["FEISHU_APP_ID"], "cli_app")
            self.assertEqual(captured["kwargs"]["env"]["FEISHU_APP_SECRET"], "cli_secret")
            self.assertEqual(captured["args"][0][-2:], ["--record-id", "rec1"])


if __name__ == "__main__":
    unittest.main()
