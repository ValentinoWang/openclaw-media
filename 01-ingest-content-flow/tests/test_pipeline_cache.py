from __future__ import annotations

import unittest

from src.pipeline import _cached_analysis_needs_rerun


class PipelineCacheTest(unittest.TestCase):
    def test_needs_model_rerun_cache_is_not_treated_as_final(self) -> None:
        self.assertTrue(
            _cached_analysis_needs_rerun(
                {
                    "analysis_status": "needs_model_rerun",
                    "fallback_reason": "primary_analysis_unavailable",
                }
            )
        )

    def test_complete_cache_can_be_reused(self) -> None:
        self.assertFalse(
            _cached_analysis_needs_rerun(
                {
                    "analysis_status": "complete",
                    "analysis_provider": "qwen",
                }
            )
        )

    def test_local_analysis_fallback_cache_is_not_treated_as_final(self) -> None:
        self.assertTrue(
            _cached_analysis_needs_rerun(
                {
                    "fallback_reason": "primary_analysis_unavailable",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
