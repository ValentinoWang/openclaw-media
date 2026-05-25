from __future__ import annotations

import contextlib
import io
import unittest

import src.analyzer as analyzer


class AnalyzerProviderOrderTest(unittest.TestCase):
    def test_openclaw_result_is_used(self) -> None:
        calls: list[str] = []
        original_openclaw = analyzer.analyze_with_openclaw
        original_qwen = analyzer.analyze_with_qwen

        def fake_openclaw(user_content: str, settings: object) -> dict:
            calls.append("openclaw")
            return {
                "title": "OpenClaw 分析结果",
                "summary": ["ok"],
                "analysis_provider": "openclaw",
            }

        def fake_qwen(user_content: str, settings: object) -> dict:
            calls.append("qwen")
            return {"title": "Qwen 分析结果", "summary": ["fallback"]}

        try:
            analyzer.analyze_with_openclaw = fake_openclaw  # type: ignore[assignment]
            analyzer.analyze_with_qwen = fake_qwen  # type: ignore[assignment]
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
            analyzer.analyze_with_openclaw = original_openclaw
            analyzer.analyze_with_qwen = original_qwen

        self.assertEqual(calls, ["openclaw"])
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["analysis_provider"], "openclaw")

    def test_qwen_is_not_used_when_openclaw_returns_none(self) -> None:
        calls: list[str] = []
        original_openclaw = analyzer.analyze_with_openclaw
        original_qwen = analyzer.analyze_with_qwen

        def fake_openclaw(user_content: str, settings: object) -> None:
            calls.append("openclaw")
            return None

        def fake_qwen(user_content: str, settings: object) -> dict:
            calls.append("qwen")
            return {
                "title": "Qwen 分析结果",
                "summary": ["ok"],
                "analysis_provider": "qwen",
            }

        try:
            analyzer.analyze_with_openclaw = fake_openclaw  # type: ignore[assignment]
            analyzer.analyze_with_qwen = fake_qwen  # type: ignore[assignment]
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
            analyzer.analyze_with_openclaw = original_openclaw
            analyzer.analyze_with_qwen = original_qwen

        self.assertEqual(calls, ["openclaw"])
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["analysis_status"], "needs_model_rerun")
        self.assertEqual(result["fallback_reason"], "primary_analysis_unavailable")

    def test_local_fallback_marks_cache_for_rerun(self) -> None:
        original_openclaw = analyzer.analyze_with_openclaw
        original_qwen = analyzer.analyze_with_qwen

        try:
            analyzer.analyze_with_openclaw = lambda user_content, settings: None  # type: ignore[assignment]
            analyzer.analyze_with_qwen = lambda user_content, settings: None  # type: ignore[assignment]
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
            analyzer.analyze_with_openclaw = original_openclaw
            analyzer.analyze_with_qwen = original_qwen

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["analysis_status"], "needs_model_rerun")
        self.assertEqual(result["fallback_reason"], "primary_analysis_unavailable")


if __name__ == "__main__":
    unittest.main()
