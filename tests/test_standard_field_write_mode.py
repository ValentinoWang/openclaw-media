from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.standard_fields import (
    DEFAULT_STANDARD_FIELD_WRITE_MODE,
    WRITE_MODE_STANDARD,
    select_fields_for_write,
)


class StandardFieldWriteModeTests(unittest.TestCase):
    def test_default_write_mode_constant_is_standard(self) -> None:
        self.assertEqual(DEFAULT_STANDARD_FIELD_WRITE_MODE, WRITE_MODE_STANDARD)

    def test_select_fields_for_write_uses_standard_names_only(self) -> None:
        fields = {
            "原标题": "旧标题",
            "平台名称": "小红书",
            "封面图/前五秒": [{"file_token": "file_1"}],
        }
        selected = select_fields_for_write(fields)
        self.assertEqual(selected["标题"], "旧标题")
        self.assertEqual(selected["平台"], "小红书")
        self.assertEqual(selected["预览附件"], [{"file_token": "file_1"}])
        self.assertNotIn("原标题", selected)
        self.assertNotIn("封面图/前五秒", selected)


if __name__ == "__main__":
    unittest.main()
