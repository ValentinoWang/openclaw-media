from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.cli import selfmedia


TENANT_ID = "00000000-0000-4000-8000-000000000101"


class DailyPollTenantFlowTests(unittest.TestCase):
    def test_daily_poll_writes_only_to_the_requested_tenant_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"OPENCLAW_MEDIA_VAULT_ROOT": directory},
            clear=False,
        ), patch.object(selfmedia, "feishu_list_records", return_value=[]):
            payload = selfmedia.daily_poll(
                SimpleNamespace(
                    monitor_url="https://bitable.example.test/monitor",
                    report_url="",
                    view_id="",
                    limit=0,
                    require_feishu=False,
                    dry_run=True,
                    tenant_id=TENANT_ID,
                )
            )
            self.assertTrue(Path(payload["json_path"]).is_file())

        self.assertEqual(payload["account_count"], 0)
        self.assertIn(f"tenants/{TENANT_ID}/account_daily_runs", payload["json_path"])

    def test_install_cron_uses_current_python_and_script_with_tenant(self) -> None:
        captured: list[list[str]] = []
        runtime = SimpleNamespace(bin="openclaw", agent="media")
        with patch.dict(os.environ, {"FEISHU_ACCOUNT_REPORT_URL": "https://bitable.example.test/report"}, clear=False), patch.object(
            selfmedia, "bot_runtime", return_value=runtime
        ), patch.object(
            selfmedia, "run_command", side_effect=lambda command, *_args, **_kwargs: captured.append(command) or {"ok": True}
        ):
            result = selfmedia.install_cron(
                SimpleNamespace(
                    name="daily-test",
                    cron="0 8 * * *",
                    tz="Asia/Shanghai",
                    timeout_seconds=60,
                    monitor_url="https://bitable.example.test/monitor",
                    report_url="",
                    disabled=False,
                    tenant_id=TENANT_ID,
                )
            )

        self.assertTrue(result["ok"])
        message = captured[0][captured[0].index("--message") + 1]
        self.assertIn(sys.executable, message)
        self.assertIn(str(Path(selfmedia.__file__).resolve()), message)
        self.assertIn(f"--tenant-id {TENANT_ID}", message)
        self.assertNotIn("/home/ubuntu/openclaw-agents", message)

    def test_install_cron_rejects_missing_report_target(self) -> None:
        with patch.dict(os.environ, {"FEISHU_ACCOUNT_REPORT_URL": ""}, clear=False):
            with self.assertRaisesRegex(SystemExit, "refusing to register"):
                selfmedia.install_cron(
                    SimpleNamespace(
                        name="daily-test",
                        cron="0 8 * * *",
                        tz="Asia/Shanghai",
                        timeout_seconds=60,
                        monitor_url="https://bitable.example.test/monitor",
                        report_url="",
                        disabled=False,
                        tenant_id=TENANT_ID,
                    )
                )


if __name__ == "__main__":
    unittest.main()
