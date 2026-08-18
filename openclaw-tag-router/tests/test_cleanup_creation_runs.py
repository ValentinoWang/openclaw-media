from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import cleanup_creation_runs


class CleanupCreationRunsTests(unittest.TestCase):
    def test_media_account_credentials_override_inherited_feishu_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "openclaw.json"
            config_path.write_text(
                json.dumps(
                    {
                        "channels": {
                            "feishu": {
                                "accounts": {
                                    "media": {
                                        "appId": "media_app_id",
                                        "appSecret": "media_app_secret",
                                    }
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            inherited = {
                "OPENCLAW_CONFIG": str(config_path),
                "FEISHU_APP_ID": "other_app_id",
                "FEISHU_APP_SECRET": "other_app_secret",
            }
            with patch.dict(os.environ, inherited, clear=False):
                cleanup_creation_runs.load_openclaw_feishu_account_env("media", override=True)
                self.assertEqual(os.environ["FEISHU_APP_ID"], "media_app_id")
                self.assertEqual(os.environ["FEISHU_APP_SECRET"], "media_app_secret")

    def test_discovery_does_not_delete_documents_that_only_reference_run_id(self) -> None:
        run_id = "run_20260621_190713_57e1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_directory = root / run_id
            run_directory.mkdir()
            named_artifact = root / f"artifact-{run_id}.json"
            named_artifact.write_text("{}", encoding="utf-8")
            reference_only = root / "deployment-evidence.md"
            reference_only.write_text(f"Production readback referenced {run_id}.", encoding="utf-8")

            discovered = cleanup_creation_runs.discover_local_paths(run_id, [root])

            self.assertEqual(set(discovered), {run_directory.resolve(), named_artifact.resolve()})
            self.assertNotIn(reference_only.resolve(), discovered)


if __name__ == "__main__":
    unittest.main()
