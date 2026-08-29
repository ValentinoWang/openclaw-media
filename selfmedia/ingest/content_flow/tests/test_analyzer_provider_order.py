from __future__ import annotations

import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import selfmedia.ingest.content_flow.src.analyzer as analyzer


class AnalyzerProviderOrderTest(unittest.TestCase):
    def test_system_prompt_uses_editorial_judgment_instead_of_course_templates(self) -> None:
        prompt = analyzer.ANALYST_SYSTEM_PROMPT

        self.assertIn("中文内容分析与运营编辑", prompt)
        self.assertIn("可迁移参考指数", prompt)
        self.assertIn("前 5 秒", prompt)
        self.assertIn("所有自然语言字段使用自然、具体的中文编辑口吻", prompt)
        self.assertIn("不要用“高流量”“爆款”等假设作为依据", prompt)
        self.assertIn("不要为了凑条数重复同一个判断", prompt)
        self.assertIn("可用一段连贯说明或少量要点", prompt)
        self.assertNotIn("拥有千万粉丝", prompt)
        self.assertNotIn("拒绝正确的废话", prompt)
        self.assertNotIn("黄金三秒", prompt)
        self.assertNotIn("万能结构公式", prompt)
        self.assertNotIn('必须按照 "1. 2. 3." 的格式', prompt)

    def test_openclaw_provider_instructions_define_content_editor_role(self) -> None:
        captured: dict[str, object] = {}
        llm_settings = SimpleNamespace(model="test-model")

        def fake_generate_json_from_parts(
            parts: list[dict[str, str]], settings: object, **kwargs: object
        ) -> dict[str, object]:
            captured["parts"] = parts
            captured["settings"] = settings
            captured["kwargs"] = kwargs
            return {"title": "内容洞察"}

        with (
            patch.object(analyzer, "load_profile_llm_settings", return_value=llm_settings) as load_settings,
            patch.object(analyzer, "generate_json_from_parts", side_effect=fake_generate_json_from_parts),
        ):
            result = analyzer.analyze_with_openclaw_agent("测试内容", object())

        self.assertEqual(result, {
            "title": "内容洞察",
            "analysis_provider": "openclaw_codex",
            "analysis_runtime": "openclaw_agent",
            "analysis_model": "test-model",
            "analysis_status": "complete",
        })
        load_settings.assert_called_once_with("media_analysis")
        self.assertIs(captured["settings"], llm_settings)
        kwargs = captured["kwargs"]
        assert isinstance(kwargs, dict)
        self.assertEqual(kwargs["max_retries"], 1)
        self.assertIs(
            kwargs["validation_contract"],
            analyzer.CONTENT_ANALYSIS_VALIDATION_CONTRACT,
        )
        instructions = kwargs["instructions"]
        assert isinstance(instructions, str)
        self.assertTrue(instructions.startswith("你是一名中文内容分析与运营编辑。"))
        self.assertIn("为创作者提供内容洞察", instructions)
        self.assertIn("输出协议：", instructions)
        self.assertIn("只输出合法 JSON object", instructions)
        self.assertNotIn("JSON 引擎", instructions)
        self.assertNotIn("JSON engine", instructions)

    def test_openclaw_oauth_result_is_used(self) -> None:
        calls: list[str] = []
        original_openclaw = analyzer.analyze_with_openclaw_agent

        def fake_openclaw(user_content: str, settings: object) -> dict:
            calls.append("openclaw")
            return {
                "title": "OpenClaw 分析结果",
                "summary": ["ok"],
                "analysis_provider": "openclaw_codex",
                "analysis_runtime": "openclaw_agent",
            }

        try:
            analyzer.analyze_with_openclaw_agent = fake_openclaw  # type: ignore[assignment]
            result = analyzer._analyze_transcript_impl(
                "逐字稿",
                "https://example.com/video",
                None,
                None,
                "文案",
                "video",
                object(),  # type: ignore[arg-type]
            )
        finally:
            analyzer.analyze_with_openclaw_agent = original_openclaw

        self.assertEqual(calls, ["openclaw"])
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["analysis_provider"], "openclaw_codex")
        self.assertEqual(result["semantic_persistence_version"], "llm_cleaned_user_fields_v1")

    def test_model_categories_are_bounded_to_shared_vocabulary(self) -> None:
        with patch.object(
            analyzer,
            "generate_json_from_parts",
            return_value={"primary_category": "自由分类", "secondary_category": ["自造分类"]},
        ):
            result = analyzer.analyze_with_openclaw_agent("测试内容", SimpleNamespace(model="test-model"))

        assert result is not None
        self.assertEqual(result["primary_category"], "其他")
        self.assertEqual(result["secondary_category"], ["未细分"])

    def test_openclaw_oauth_failure_marks_incomplete_without_local_semantics(self) -> None:
        original_openclaw = analyzer.analyze_with_openclaw_agent

        try:
            analyzer.analyze_with_openclaw_agent = lambda user_content, settings: None  # type: ignore[assignment]
            with contextlib.redirect_stdout(io.StringIO()):
                result = analyzer._analyze_transcript_impl(
                    "",
                    "https://example.com/video",
                    None,
                    None,
                    "只有文案",
                    "video",
                    object(),  # type: ignore[arg-type]
                )
        finally:
            analyzer.analyze_with_openclaw_agent = original_openclaw

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["analysis_status"], "needs_model_rerun")
        self.assertEqual(result["incomplete_reason"], "primary_analysis_unavailable")
        self.assertEqual(result["summary"], [])
        self.assertEqual(result["tags"], [])

    def test_analysis_validator_rejects_course_template_and_english_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "固定课程模板话术"):
            analyzer._validate_content_analysis_payload(
                {"action_plan": "万能结构公式：开头+中间+结尾"},
                {"visual_evidence_available": False},
            )
        with self.assertRaisesRegex(ValueError, "必须使用中文"):
            analyzer._validate_content_analysis_payload(
                {"title": "A generic English title"},
                {"visual_evidence_available": False},
            )

    def test_analysis_validator_rejects_unavailable_visual_claims_and_numbered_plan(self) -> None:
        with self.assertRaisesRegex(ValueError, "visual_cues 必须为空"):
            analyzer._validate_content_analysis_payload(
                {"visual_cues": "镜头切到白板"},
                {"visual_evidence_available": False},
            )
        with self.assertRaisesRegex(ValueError, "不得假设镜头或画面"):
            analyzer._validate_content_analysis_payload(
                {"hooks": "用镜头推进制造反差"},
                {"visual_evidence_available": False},
            )
        with self.assertRaisesRegex(ValueError, "不得强制使用"):
            analyzer._validate_content_analysis_payload(
                {"action_plan": "1. 保留冲突\n2. 更换案例"},
                {"visual_evidence_available": True},
            )


if __name__ == "__main__":
    unittest.main()
