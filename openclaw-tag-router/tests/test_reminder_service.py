from __future__ import annotations

import tempfile
import textwrap
import unittest
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


if __name__ == "__main__":
    unittest.main()
