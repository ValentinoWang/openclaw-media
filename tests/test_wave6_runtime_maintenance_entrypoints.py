from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.maintenance.backfills import (
    backfill_activity_boost_date,
    backfill_activity_missing_main_status,
    backfill_activity_platform_name_multiselect,
)
from runtime.maintenance.deploy import sync_openclaw_agent_models


class RuntimeMaintenanceEntrypointTests(unittest.TestCase):
    def test_backfills_fail_with_recovery_guidance_when_reminder_script_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing_script = Path(directory) / "missing-reminder.py"
            for module in (
                backfill_activity_boost_date,
                backfill_activity_missing_main_status,
                backfill_activity_platform_name_multiselect,
            ):
                with self.subTest(module=module.__name__), patch.object(module, "REMINDER_PATH", missing_script):
                    with self.assertRaisesRegex(SystemExit, "OPENCLAW_FEISHU_REMINDER_SCRIPT"):
                        module.load_reminder()

    def test_backfills_fail_with_recovery_guidance_when_activity_config_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing_config = Path(directory) / "missing-activity.json"
            with patch.object(backfill_activity_missing_main_status, "ACTIVITY_CONFIG_PATH", missing_config):
                with self.assertRaisesRegex(SystemExit, "OPENCLAW_ACTIVITY_CONFIG_PATH"):
                    backfill_activity_missing_main_status.load_activity_config()
            with self.assertRaisesRegex(SystemExit, "OPENCLAW_ACTIVITY_CONFIG_PATH"):
                backfill_activity_boost_date.load_json(
                    missing_config,
                    env_name="OPENCLAW_ACTIVITY_CONFIG_PATH",
                )
            with self.assertRaisesRegex(SystemExit, "OPENCLAW_ACTIVITY_CONFIG_PATH"):
                backfill_activity_platform_name_multiselect.load_json(
                    missing_config,
                    env_name="OPENCLAW_ACTIVITY_CONFIG_PATH",
                )

    def test_model_sync_fails_with_recovery_guidance_for_missing_external_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing_openai_env = Path(directory) / "missing-openai.env"
            missing_config = Path(directory) / "missing-openclaw-bots.json"
            with patch.object(sync_openclaw_agent_models, "OPENAI_ENV", missing_openai_env):
                with self.assertRaisesRegex(SystemExit, "OPENCLAW_OPENAI_ENV"):
                    sync_openclaw_agent_models.canonical_openai_base_url()
            with patch.object(sync_openclaw_agent_models, "REPO_CONFIG", missing_config):
                with self.assertRaisesRegex(SystemExit, "OPENCLAW_BOTS_CONFIG"):
                    sync_openclaw_agent_models.load_payload()


if __name__ == "__main__":
    unittest.main()
