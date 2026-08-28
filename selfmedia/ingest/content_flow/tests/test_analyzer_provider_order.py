from __future__ import annotations

import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import selfmedia.ingest.content_flow.src.analyzer as analyzer


class AnalyzerProviderOrderTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
