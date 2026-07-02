from __future__ import annotations

import unittest

from selfmedia.ingest.content_flow.src.pipeline import _cached_analysis_needs_rerun


class PipelineCacheTest(unittest.TestCase):
    def test_needs_model_rerun_cache_is_not_treated_as_final(self) -> None:
        self.assertTrue(
            _cached_analysis_needs_rerun(
                {
                    "analysis_status": "needs_model_rerun",
                    "incomplete_reason": "primary_analysis_unavailable",
                }
            )
        )

    def test_complete_cache_can_be_reused(self) -> None:
        self.assertFalse(
            _cached_analysis_needs_rerun(
                {
                    "analysis_status": "complete",
                    "analysis_provider": "codex_responses",
                }
            )
        )

    def test_incomplete_analysis_without_status_is_not_treated_as_cache_control(self) -> None:
        self.assertFalse(_cached_analysis_needs_rerun({"incomplete_reason": "primary_analysis_unavailable"}))


if __name__ == "__main__":
    unittest.main()
