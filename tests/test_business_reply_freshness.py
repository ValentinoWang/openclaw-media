from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from selfmedia.business import id_business


class BusinessReplyFreshnessTest(unittest.TestCase):
    def test_historical_month_labels_normalize_to_current_quote_question(self) -> None:
        august_2026 = datetime(2026, 8, 28, 9, 0, tzinfo=id_business.LOCAL_TZ)
        fields, pending = id_business.extract_labeled_fields(
            "4月份报备图文价格：1200\n是否可保价5月："
        )

        self.assertEqual(fields, {"图文报价": "1200"})
        self.assertEqual(pending, ["本月下单是否保价次月执行"])

        defaults = {
            "schema_version": id_business.BUSINESS_REPLY_DEFAULTS_SCHEMA_VERSION,
            "updated_at": "2026-08-28T09:00:00+08:00",
            "source": {"type": "user_confirmed", "scope": "global"},
            "current_month": "2026-08",
            "fields": {"报备返点": "先按25%沟通，可谈"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "id_business_reply_defaults.json"
            path.write_text(json.dumps(defaults, ensure_ascii=False), encoding="utf-8")
            question = id_business.build_creator_question_text(
                {"作者ID": "创作者"},
                ["图文报价", "本月下单是否保价次月执行", "报备返点"],
                now=august_2026,
                defaults_path=path,
            )

        self.assertIn("8月图文报价是多少", question)
        self.assertIn("8月下单是否可以保价至9月执行", question)
        self.assertIn("先按25%沟通，可谈", question)
        self.assertNotIn("4月", question)
        self.assertNotIn("5月", question)
        self.assertNotIn("30%", question)

    def test_stale_month_configuration_never_claims_a_specific_month_or_rebate_anchor(self) -> None:
        august_2026 = datetime(2026, 8, 28, 9, 0, tzinfo=id_business.LOCAL_TZ)
        defaults = {
            "schema_version": id_business.BUSINESS_REPLY_DEFAULTS_SCHEMA_VERSION,
            "updated_at": "2026-07-24T07:20:28+08:00",
            "source": {"type": "user_confirmed", "scope": "global"},
            "current_month": "2026-07",
            "fields": {"报备返点": "先按25%沟通，可谈"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "id_business_reply_defaults.json"
            path.write_text(json.dumps(defaults, ensure_ascii=False), encoding="utf-8")
            question = id_business.build_creator_question_text(
                {"作者ID": "创作者"},
                ["图文报价", "本月下单是否保价次月执行", "报备返点"],
                now=august_2026,
                defaults_path=path,
            )
            fields: dict[str, str] = {}
            lookup = id_business.apply_business_reply_defaults(fields, path=path, now=august_2026)

        self.assertIn("最新图文报价是多少", question)
        self.assertIn("本次下单是否可以按报价保价至执行月", question)
        self.assertNotIn("7月", question)
        self.assertNotIn("8月", question)
        self.assertNotIn("先按25%沟通", question)
        self.assertNotIn("报备返点", fields)
        self.assertFalse(lookup["month_context"]["is_current"])
        self.assertIn("报备返点", lookup["stale_fields"])

    def test_current_configuration_preserves_explicit_rebate_and_price_protection(self) -> None:
        august_2026 = datetime(2026, 8, 28, 9, 0, tzinfo=id_business.LOCAL_TZ)
        defaults = {
            "schema_version": id_business.BUSINESS_REPLY_DEFAULTS_SCHEMA_VERSION,
            "updated_at": "2026-08-28T09:00:00+08:00",
            "source": {"type": "user_confirmed", "scope": "global"},
            "current_month": "2026-08",
            "fields": {
                "报备返点": "先按25%沟通，可谈",
                "保价政策": "8月下单可保价至9月执行",
            },
        }
        fields = {
            "报备返点": "品牌确认20%",
            "保价政策": "品牌确认不保价，按执行月价格",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "id_business_reply_defaults.json"
            path.write_text(json.dumps(defaults, ensure_ascii=False), encoding="utf-8")
            lookup = id_business.apply_business_reply_defaults(fields, path=path, now=august_2026)

        self.assertEqual(fields["报备返点"], "品牌确认20%")
        self.assertEqual(fields["保价政策"], "品牌确认不保价，按执行月价格")
        self.assertEqual(lookup["applied_fields"], [])
        self.assertEqual(set(lookup["skipped_existing_fields"]), {"报备返点", "保价政策"})


if __name__ == "__main__":
    unittest.main()
