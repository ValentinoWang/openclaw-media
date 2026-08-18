from __future__ import annotations

import contextlib
import io
import unittest

import selfmedia.ingest.content_flow.src.analyzer as analyzer


class AnalyzerProviderOrderTest(unittest.TestCase):
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
