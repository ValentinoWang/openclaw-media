from __future__ import annotations

import tempfile
import textwrap
import unittest
import json
from pathlib import Path

from openclaw_app.services.reminder_service import ReminderService


class ReminderServiceTest(unittest.TestCase):
    def test_add_returns_error_on_subprocess_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "slow.py"
            script.write_text(
                textwrap.dedent(
                    """
                    import time
                    time.sleep(3)
                    """
                ).strip(),
                encoding="utf-8",
            )
            service = ReminderService(
                enabled=True,
                command="/usr/bin/python3",
                script=str(script),
                timeout_seconds=1,
            )
            result = service.add(
                kind="自媒体知识",
                title="测试",
                text="测试",
                due_at=None,
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["timeout"])
        self.assertIn("写入超时", result["error"])

    def test_update_invokes_update_record_with_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "echo_args.py"
            script.write_text(
                textwrap.dedent(
                    """
                    import json
                    import sys
                    print(json.dumps({"argv": sys.argv[1:]}, ensure_ascii=False))
                    """
                ).strip(),
                encoding="utf-8",
            )
            service = ReminderService(
                enabled=True,
                command="/usr/bin/python3",
                script=str(script),
                timeout_seconds=1,
            )

            result = service.update(
                record_id="rec-dev",
                record_type="待办-开发",
                fields={"match_status": "matched", "详细任务文档路径": "/tmp/detail.md"},
            )

        self.assertTrue(result["ok"])
        argv = result["data"]["argv"]
        self.assertEqual(argv[:5], ["update-record", "--record-id", "rec-dev", "--type", "待办-开发"])
        self.assertIn("--extra-fields", argv)
        extra = json.loads(argv[argv.index("--extra-fields") + 1])
        self.assertEqual(extra["match_status"], "matched")
        self.assertEqual(extra["详细任务文档路径"], "/tmp/detail.md")


if __name__ == "__main__":
    unittest.main()
