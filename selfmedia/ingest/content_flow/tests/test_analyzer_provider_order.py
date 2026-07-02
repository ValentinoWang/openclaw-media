from __future__ import annotations

import contextlib
import io
import unittest

import selfmedia.ingest.content_flow.src.analyzer as analyzer


class AnalyzerProviderOrderTest(unittest.TestCase):
    def test_codex_responses_result_is_used(self) -> None:
        calls: list[str] = []
        original_codex = analyzer.analyze_with_codex_responses

        def fake_codex(user_content: str, settings: object) -> dict:
            calls.append("codex")
            return {
                "title": "Codex 分析结果",
                "summary": ["ok"],
                "analysis_provider": "codex_responses",
                "analysis_runtime": "codex_responses",
            }

        try:
            analyzer.analyze_with_codex_responses = fake_codex  # type: ignore[assignment]
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
            analyzer.analyze_with_codex_responses = original_codex

        self.assertEqual(calls, ["codex"])
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["analysis_provider"], "codex_responses")

    def test_codex_responses_failure_marks_incomplete_without_local_semantics(self) -> None:
        original_codex = analyzer.analyze_with_codex_responses

        try:
            analyzer.analyze_with_codex_responses = lambda user_content, settings: None  # type: ignore[assignment]
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
            analyzer.analyze_with_codex_responses = original_codex

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["analysis_status"], "needs_model_rerun")
        self.assertEqual(result["incomplete_reason"], "primary_analysis_unavailable")
        self.assertEqual(result["summary"], [])
        self.assertEqual(result["tags"], [])


if __name__ == "__main__":
    unittest.main()
