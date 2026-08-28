import unittest
import os
import tempfile
from unittest.mock import patch

from selfmedia.creation.field_contract import normalize_platform
from selfmedia.creation.llm_generator import CREATOR_BRIEF_REPORT_MODE
from selfmedia.creation.platform_fit import _normalize_activity_strategy
from selfmedia.creation import platform_fit
from selfmedia.creation.request_parser import parse_creation_request
from selfmedia.creation.shooting_execution import _bounded_context_json
from selfmedia.creation.platform_fit import PlatformMechanismConfigError, load_platform_mechanism_config
from selfmedia.creation.platform_validator import validate_platform_draft


class CreationP2ContractTests(unittest.TestCase):
    def test_bilibili_is_reachable_from_creation_request(self) -> None:
        request = parse_creation_request(
            "【创作>B站】类型=视频 赛道=知识 主体=实验记录",
        )
        self.assertEqual(request.platform, "B站")
        self.assertEqual(normalize_platform("哔哩哔哩"), "B站")

    def test_report_mode_is_injected_by_code(self) -> None:
        self.assertEqual(CREATOR_BRIEF_REPORT_MODE["report_mode"], "creator_brief")

    def test_context_truncation_keeps_json_and_marks_cut_fields(self) -> None:
        encoded = _bounded_context_json({"account_profile": "x" * 4000})
        self.assertIn("上下文字段已截断", encoded)
        self.assertEqual(type(__import__("json").loads(encoded)), dict)

    def test_activity_strategy_does_not_fabricate_missing_risk_judgement(self) -> None:
        with self.assertRaisesRegex(ValueError, "hard_fit_risk"):
            _normalize_activity_strategy({"matched_activities": []}, {})

    def test_bilibili_draft_has_reachable_platform_contract(self) -> None:
        result = validate_platform_draft(
            "B站", "视频", {"title": "测试", "tags": ["知识", "实验"], "hook_3s": "开头", "storyboard": ["镜头"], "voiceover": "口播", "subtitles": ["字幕"]}
        )
        self.assertTrue(result.ok)

    def test_corrupt_explicit_mechanism_config_is_observable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "xiaohongshu.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{broken")
            with patch.dict(os.environ, {"SELFMEDIA_PLATFORM_MECHANISM_CONFIG_DIR": directory}):
                with self.assertRaises(PlatformMechanismConfigError):
                    load_platform_mechanism_config("小红书")

    def test_retired_platform_fit_fallback_helpers_are_absent(self) -> None:
        for name in ("_build_activity_strategy", "_activity_hard_fit_risk", "_source_type_risk", "_missing_info"):
            self.assertFalse(hasattr(platform_fit, name), name)


if __name__ == "__main__":
    unittest.main()
