from __future__ import annotations

import json
import os
import tempfile
import unittest
from argparse import Namespace
from datetime import date
from unittest.mock import patch

from selfmedia.business import id_business
from selfmedia.business.commercial_loop import CommercialLoopLedger


TENANT_ID = "00000000-0000-4000-8000-000000000901"


class CommercialLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        self.previous_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
        os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = self.root.name

    def tearDown(self) -> None:
        if self.previous_root is None:
            os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
        else:
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = self.previous_root
        self.root.cleanup()

    def test_quote_refresh_is_persisted_without_claiming_an_external_notification(self) -> None:
        fields = {"平台": "小红书", "作者ID": "creator-1", "账号名称": "创作者"}
        plan = id_business.quote_refresh_plan(fields, today=date(2026, 8, 29))
        ledger = id_business.commercial_loop_ledger_for_fields(fields, {}, tenant_id=TENANT_ID)

        state = ledger.ensure_quote_snapshot(
            business_account_id="business_account_xhs_creator_1",
            quote_snapshot_uri="media://tenants/example/quote_snapshot.json",
            quote_refresh=plan,
        )

        self.assertEqual(state["quote_refresh"]["status"], "pending_local_runner")
        self.assertFalse(state["quote_refresh"]["due_now"])
        self.assertEqual(state["quote_refresh"]["next_check_on"], "2026-09-01")
        persisted = json.loads(open(ledger.artifact_path(), encoding="utf-8").read())
        self.assertEqual(persisted["external_status"], "not_attempted")
        self.assertNotIn("sent", json.dumps(persisted, ensure_ascii=False))

    def test_missing_external_table_configuration_leaves_quote_snapshot_and_retryable_loop(self) -> None:
        fields = {
            "平台": "小红书",
            "作者ID": "creator-1",
            "账号名称": "创作者",
            "品牌": "测试品牌",
            "产品": "测试产品",
            "图文报价": "1200",
        }
        with patch.object(id_business, "table_url_from_args", return_value=""), patch.object(
            id_business, "opportunity_table_url", return_value=""
        ):
            with self.assertRaisesRegex(RuntimeError, "missing MEDIA_OS_BUSINESS_ACCOUNTS_V2_URL"):
                id_business.write_business_model_v2(fields, {}, tenant_id=TENANT_ID)

        ledger = id_business.commercial_loop_ledger_for_fields(fields, {}, tenant_id=TENANT_ID)
        state = ledger.mark_external_retry(reason_code="external_configuration_missing")
        self.assertEqual(state["external_status"], "retry_pending")
        self.assertEqual(state["retry"]["reason_code"], "external_configuration_missing")
        self.assertTrue(state["quote_snapshot_uri"])

    def test_local_business_contract_error_is_not_reported_as_external_retry(self) -> None:
        args = Namespace(
            tenant_id=TENANT_ID,
            text="【商务>ID】测试",
            stdin=False,
            smoke=False,
            screenshot="",
            account_name="",
            profile_url="",
            brief_file=[],
            feishu_url="",
            no_screenshot=True,
            notify_confirmation=False,
            dry_run=False,
        )
        parsed = {
            "status": "done",
            "fields": {"平台": "小红书", "作者ID": "creator-1", "账号名称": "创作者"},
            "details": {},
            "urls": [],
            "profile_urls": [],
            "brief_urls": [],
            "pending_fields": [],
        }
        with patch.object(id_business, "parse_business_text", return_value=parsed), patch.object(
            id_business, "enrich_business_fields_from_history", return_value={}
        ), patch.object(id_business, "apply_business_reply_defaults", return_value={}), patch.object(
            id_business, "generate_business_reply_from_current_fields", return_value={}
        ), patch.object(id_business, "write_business_model_v2", side_effect=RuntimeError("local payload contract failed")):
            with self.assertRaisesRegex(RuntimeError, "local payload contract failed"):
                id_business.ingest(args)

    def test_confirmed_delivery_replays_without_a_second_attempt(self) -> None:
        ledger = CommercialLoopLedger(tenant_id=TENANT_ID, loop_id="delivery-1")
        first, replayed = ledger.begin_delivery(request_text="same request", links={"creation_run_id": "run-1"})
        self.assertFalse(replayed)
        self.assertEqual(first["retry"]["attempts"], 1)
        self.assertEqual(first["lifecycle_status"], "in_creation")
        ledger.confirm_delivery(doc_url="https://example.test/doc", record={"record_id": "rec-1"}, review_links={})

        confirmed, replayed = ledger.begin_delivery(request_text="same request", links={"creation_run_id": "run-1"})
        self.assertTrue(replayed)
        self.assertEqual(confirmed["lifecycle_status"], "delivered")
        self.assertEqual(confirmed["settlement_status"], "pending_manual")
        self.assertEqual(confirmed["retry"], {})
        self.assertEqual(confirmed["delivery"]["record"]["record_id"], "rec-1")


if __name__ == "__main__":
    unittest.main()
