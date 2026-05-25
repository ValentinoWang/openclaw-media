from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.standard_fields import (
    STANDARD_ALIAS_MAP,
    choose_primary_value,
    merge_json_group,
    normalize_standard_field_name,
    normalize_standard_fields,
    standard_field_specs,
)


class StandardFieldsTests(unittest.TestCase):
    def test_normalize_standard_field_name_uses_default_aliases(self) -> None:
        self.assertEqual(normalize_standard_field_name("原标题"), "标题")
        self.assertEqual(normalize_standard_field_name("平台名称"), "平台")
        self.assertEqual(normalize_standard_field_name("平台ID"), "平台ID")
        self.assertEqual(normalize_standard_field_name("未知字段"), "未知字段")

    def test_choose_primary_value_skips_empty_values(self) -> None:
        self.assertEqual(choose_primary_value(["", None, "标题"]), "标题")
        self.assertEqual(choose_primary_value([None, {}, []]), "")

    def test_merge_json_group_merges_dicts_and_lists(self) -> None:
        merged = merge_json_group(
            {"activity_time": "2026-05-01", "items": ["a"]},
            {"activity_time_start": "2026-05-01", "items": ["b"]},
        )
        self.assertEqual(merged["activity_time"], "2026-05-01")
        self.assertEqual(merged["activity_time_start"], "2026-05-01")
        self.assertEqual(merged["items"], ["a", "b"])

    def test_normalize_standard_fields_merges_aliases_into_json_groups(self) -> None:
        normalized = normalize_standard_fields(
            {
                "原标题": "表达力爆款",
                "标题": "后来的标题不会覆盖",
                "平台名称": "小红书",
                "activity_time": "2026-05-01 至 2026-05-10",
                "activity_time_start": "2026-05-01",
                "activity_time_end": "2026-05-10",
                "参考链接": "https://example.com/post",
                "原链接": "https://example.com/post-2",
                "爆点拆解": "强反差开场",
                "核心价值": "给方法",
            }
        )
        self.assertEqual(normalized["标题"], "表达力爆款")
        self.assertEqual(normalized["平台"], "小红书")
        self.assertEqual(
            normalized["活动时间JSON"],
            {
                "activity_time": "2026-05-01 至 2026-05-10",
                "activity_time_start": "2026-05-01",
                "activity_time_end": "2026-05-10",
            },
        )
        self.assertEqual(normalized["来源链接"], "https://example.com/post")
        self.assertEqual(
            normalized["爆点分析JSON"],
            {"爆点拆解": "强反差开场", "核心价值": "给方法"},
        )

    def test_normalize_standard_fields_keeps_creator_identity_fields(self) -> None:
        normalized = normalize_standard_fields(
            {
                "平台ID": "93130816637",
                "博主IP": "清华AI小王冲一级",
                "院校背景": "清华大学",
                "粉丝数": 37000,
            }
        )
        self.assertEqual(normalized["平台ID"], "93130816637")
        self.assertNotIn("平台账号ID", normalized)
        self.assertEqual(normalized["博主IP"], "清华AI小王冲一级")
        self.assertEqual(normalized["院校背景"], "清华大学")
        self.assertEqual(normalized["粉丝数"], 37000)

    def test_standard_field_specs_can_merge_extra_specs(self) -> None:
        specs = standard_field_specs({"自定义字段": 1})
        self.assertIn("标题", specs)
        self.assertEqual(specs["自定义字段"], 1)
        self.assertEqual(STANDARD_ALIAS_MAP["原标题"], "标题")


if __name__ == "__main__":
    unittest.main()
