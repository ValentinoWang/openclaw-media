from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.maintenance.backfills.backfill_standard_fields import build_backfill_payload


class BackfillStandardFieldsTests(unittest.TestCase):
    def test_build_backfill_payload_ignores_existing_standard_values(self) -> None:
        payload = build_backfill_payload(
            {
                "标题": "现有标题",
                "原标题": "旧标题",
                "平台名称": "小红书",
                "activity_time": "2026-05-01 至 2026-05-10",
                "activity_time_start": "2026-05-01",
            },
            {"标题": 1, "平台": 1, "活动时间JSON": 1},
        )
        self.assertNotIn("标题", payload)
        self.assertEqual(payload["平台"], "小红书")
        self.assertEqual(
            payload["活动时间JSON"],
            {
                "activity_time": "2026-05-01 至 2026-05-10",
                "activity_time_start": "2026-05-01",
            },
        )

    def test_build_backfill_payload_skips_null_only_grouped_json(self) -> None:
        payload = build_backfill_payload(
            {
                "商务原文": None,
                "项目": None,
                "图文报价": None,
                "最近错误": None,
            },
            {
                "原始文本JSON": 1,
                "商务需求JSON": 1,
                "报价信息JSON": 1,
                "详情JSON": 1,
            },
        )
        self.assertEqual(payload, {})


if __name__ == "__main__":
    unittest.main()
