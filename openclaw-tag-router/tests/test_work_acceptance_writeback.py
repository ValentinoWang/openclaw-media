from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from media_vault import MediaVault
from openclaw_app.models.message import Message
from openclaw_app.router.work_acceptance import WorkAcceptanceMixin


TENANT_ID = "00000000-0000-4000-8000-000000000101"


class WorkAcceptanceHarness(WorkAcceptanceMixin):
    def _maybe_apply_content_os_work_acceptance(self, *_args: object, **_kwargs: object) -> dict[str, str]:
        return {}


class WorkAcceptanceWritebackTests(unittest.TestCase):
    def test_persists_acceptance_only_in_the_authenticated_creation_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": directory}, clear=False
        ):
            vault = MediaVault(tenant_id=TENANT_ID)
            vault.write_creation_run_artifacts("run_acceptance", request={"request": {}}, draft_output={})
            message = Message(
                entry_tag="作品验收",
                raw_text="【作品验收】 创作记录ID=run_acceptance",
                body="作品正文",
                metadata={"tenant_id": TENANT_ID},
            )
            result = WorkAcceptanceHarness()._persist_creation_run_acceptance(
                message,
                verdict="通过",
                result={"summary": "满足要求", "next_actions": ["发布"]},
                items=[{"requirement": "开头明确", "judgment": "满足", "evidence": "首句", "gap": "", "fix": ""}],
                pass_count=1,
                fail_count=0,
                uncertain_count=0,
            )

            saved = (vault.creation_run_dir("run_acceptance") / "acceptance.json").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "persisted")
        self.assertIn('"verdict":"通过"', saved)
        self.assertIn('"passed":1', saved)

    def test_missing_creation_record_id_is_explicit(self) -> None:
        message = Message(entry_tag="作品验收", raw_text="【作品验收】正文", body="正文", metadata={"tenant_id": TENANT_ID})

        result = WorkAcceptanceHarness()._persist_creation_run_acceptance(
            message,
            verdict="通过",
            result={},
            items=[],
            pass_count=0,
            fail_count=0,
            uncertain_count=0,
        )

        self.assertEqual(result["status"], "creation_record_id_required")
        self.assertIn("创作记录ID", result["reply"])


if __name__ == "__main__":
    unittest.main()
