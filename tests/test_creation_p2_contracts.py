import unittest
import os
import tempfile
from unittest.mock import patch

from selfmedia.creation.field_contract import normalize_platform
from selfmedia.creation.llm_generator import CREATOR_BRIEF_REPORT_MODE
from selfmedia.creation.platform_fit import (
    SemanticPersistenceRequiredError,
    _normalize_activity_strategy,
    build_platform_mechanism_prompt,
    fallback_platform_mechanism_fit,
    validate_platform_mechanism_fit_payload,
)
from selfmedia.creation import platform_fit
from selfmedia.creation import workflow
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

    def test_platform_fit_prompt_and_validator_define_evidence_contract(self) -> None:
        request = parse_creation_request("【创作>小红书】类型=图文 赛道=职场 主体=表达力")
        prompt = build_platform_mechanism_prompt(
            request,
            activity_candidates=[],
            viral_candidates=[],
            inspiration_candidates=[],
            business_candidates=[],
            reference_docs=[],
            media_context={},
        )
        self.assertIn("mechanism_evidence_level 只能是 S/A/B/C/D", prompt)
        self.assertIn("source_weights 必须是 object", prompt)

        payload = {
            "platform_mechanism_version": "test-v1",
            "mechanism_claim_boundary": "这是机制拟合假设，不是平台真实算法。",
            "mechanism_evidence_level": "unknown",
            "source_weights": {"账号复盘": "high"},
            "platform_strategy": {"summary": "test"},
            "activity_strategy": {"hard_fit_risk": "low", "risk_reason": "test", "do_not_force": ["不硬蹭"]},
            "traffic_hypothesis": {"summary": "test"},
            "creation_reverse_plan": {"title": ["test"]},
            "validation_targets": {"two_hour": ["test"]},
            "post_publish_correction": {"if_low_click": "test"},
            "risks_or_missing_info": ["test"],
        }
        with self.assertRaisesRegex(ValueError, "mechanism_evidence_level"):
            validate_platform_mechanism_fit_payload(payload, request)

        payload["mechanism_evidence_level"] = "B"
        with self.assertRaisesRegex(ValueError, "source_weights"):
            validate_platform_mechanism_fit_payload(payload, request)

    def test_creation_workflow_uses_platform_baseline_after_semantic_fit_failure(self) -> None:
        request = parse_creation_request("【创作>小红书】类型=图文 赛道=职场 主体=表达力")
        fallback = {"fallback_used": True, "risks_or_missing_info": ["拟合失败，待人工复核"]}

        class DraftReached(Exception):
            pass

        captured: dict[str, object] = {}

        def draft(*_args: object, **kwargs: object) -> dict[str, object]:
            captured["platform_fit"] = kwargs["platform_fit"]
            raise DraftReached()

        with (
            patch.object(workflow, "parse_creation_request_with_llm", return_value=request),
            patch.object(workflow, "build_media_context_for_request", return_value={}),
            patch.object(workflow, "load_rows_for_creation", return_value=([], [])),
            patch.object(workflow, "load_inspiration_rows_for_creation", return_value=[]),
            patch.object(workflow, "load_insight_card_records", return_value=[]),
            patch.object(workflow, "read_reference_docs", return_value=[]),
            patch.object(
                workflow,
                "generate_platform_mechanism_fit",
                side_effect=SemanticPersistenceRequiredError("LLM_SEMANTIC_PERSISTENCE_REQUIRED:platform_mechanism_fit:llm_failed"),
            ),
            patch.object(workflow, "fallback_platform_mechanism_fit", return_value=fallback) as fallback_builder,
            patch.object(workflow, "generate_creation_draft", side_effect=draft),
        ):
            with self.assertRaises(DraftReached):
                workflow.handle_creation_command(
                    "【创作>小红书】类型=图文 赛道=职场 主体=表达力",
                    tenant_id="00000000-0000-4000-8000-000000000101",
                    no_write=True,
                )

        fallback_builder.assert_called_once()
        self.assertEqual(captured["platform_fit"], fallback)

    def test_platform_fit_fallback_is_marked_and_retains_risk_information(self) -> None:
        request = parse_creation_request("【创作>小红书】类型=图文 赛道=职场 主体=表达力")

        fallback = fallback_platform_mechanism_fit(
            request,
            failure_reason="LLM_SEMANTIC_PERSISTENCE_REQUIRED:platform_mechanism_fit:llm_failed",
            activity_candidates=[],
            viral_candidates=[],
            inspiration_candidates=[],
            business_candidates=[],
            reference_docs=[],
            media_context={},
        )

        self.assertTrue(fallback["fallback_used"])
        self.assertEqual(fallback["mechanism_evidence_level"], "D")
        self.assertEqual(fallback["source_weights"], {"platform_mechanism_baseline": 1.0})
        self.assertIn("LLM_SEMANTIC_PERSISTENCE_REQUIRED", fallback["risks_or_missing_info"][0])
        self.assertEqual(fallback["platform_fit_meta"]["mechanism_source"], "baseline_fallback")

    def test_creation_workflow_does_not_hide_nonsemantic_fit_failure(self) -> None:
        request = parse_creation_request("【创作>小红书】类型=图文 赛道=职场 主体=表达力")

        with (
            patch.object(workflow, "parse_creation_request_with_llm", return_value=request),
            patch.object(workflow, "build_media_context_for_request", return_value={}),
            patch.object(workflow, "load_rows_for_creation", return_value=([], [])),
            patch.object(workflow, "load_inspiration_rows_for_creation", return_value=[]),
            patch.object(workflow, "load_insight_card_records", return_value=[]),
            patch.object(workflow, "read_reference_docs", return_value=[]),
            patch.object(workflow, "generate_platform_mechanism_fit", side_effect=RuntimeError("transport_failed")),
            patch.object(workflow, "fallback_platform_mechanism_fit") as fallback_builder,
            patch.object(workflow, "generate_creation_draft") as draft,
        ):
            with self.assertRaisesRegex(RuntimeError, "transport_failed"):
                workflow.handle_creation_command(
                    "【创作>小红书】类型=图文 赛道=职场 主体=表达力",
                    tenant_id="00000000-0000-4000-8000-000000000101",
                    no_write=True,
                )

        fallback_builder.assert_not_called()
        draft.assert_not_called()


if __name__ == "__main__":
    unittest.main()
