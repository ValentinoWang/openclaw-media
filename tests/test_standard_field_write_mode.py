from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.standard_fields import (
    DEFAULT_STANDARD_FIELD_WRITE_MODE,
    select_fields_for_write,
    standard_field_write_mode,
)


class StandardFieldWriteModeTests(unittest.TestCase):
    def test_default_write_mode_is_standard(self) -> None:
        old = os.environ.get("STANDARD_FIELD_WRITE_MODE")
        try:
            os.environ.pop("STANDARD_FIELD_WRITE_MODE", None)
            self.assertEqual(standard_field_write_mode(), DEFAULT_STANDARD_FIELD_WRITE_MODE)
        finally:
            if old is not None:
                os.environ["STANDARD_FIELD_WRITE_MODE"] = old

    def test_select_fields_for_write_standard_mode_preserves_requested_legacy(self) -> None:
        fields = {
            "原标题": "旧标题",
            "平台名称": "小红书",
            "封面图/前五秒": [{"file_token": "file_1"}],
        }
        selected = select_fields_for_write(fields, preserve_legacy_fields={"封面图/前五秒"})
        self.assertEqual(selected["标题"], "旧标题")
        self.assertEqual(selected["平台"], "小红书")
        self.assertEqual(selected["封面图/前五秒"], [{"file_token": "file_1"}])
        self.assertNotIn("原标题", selected)

    def test_select_fields_for_write_dual_mode_keeps_both(self) -> None:
        fields = {"原标题": "旧标题"}
        selected = select_fields_for_write(fields, mode="dual")
        self.assertEqual(selected["原标题"], "旧标题")
        self.assertEqual(selected["标题"], "旧标题")


if __name__ == "__main__":
    unittest.main()
