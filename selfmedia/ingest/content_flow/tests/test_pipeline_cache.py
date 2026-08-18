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
                    "title": "可信标题",
                    "full_content": "可信全文",
                    "work_copy": "可信平台文案",
                    "caption": "原始平台文案",
                    "semantic_persistence_version": "llm_cleaned_user_fields_v1",
                }
            )
        )

    def test_cache_without_llm_cleaning_provenance_is_rerun(self) -> None:
        self.assertTrue(
            _cached_analysis_needs_rerun(
                {
                    "analysis_status": "complete",
                    "analysis_provider": "codex_responses",
                    "full_content": "旧缓存全文",
                    "work_copy": "旧缓存文案",
                }
            )
        )

    def test_missing_full_content_cache_is_not_treated_as_final(self) -> None:
        self.assertTrue(_cached_analysis_needs_rerun({"incomplete_reason": "primary_analysis_unavailable"}))


if __name__ == "__main__":
    unittest.main()
