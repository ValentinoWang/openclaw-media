from __future__ import annotations

import unittest

from src.downloader import (
    _extract_visible_interaction_stats,
    extract_stats_from_aweme_detail,
    finalize_interaction_stats,
    merge_stats,
)


class InteractionStatsTest(unittest.TestCase):
    def test_douyin_stats_are_kept_only_with_aweme_detail_sources(self) -> None:
        extracted = extract_stats_from_aweme_detail(
            {
                "statistics": {
                    "digg_count": "12",
                    "collect_count": "3",
                    "comment_count": "4",
                    "share_count": "5",
                }
            }
        )
        stats = {
            "like_count": None,
            "collect_count": None,
            "comment_count": None,
            "share_count": None,
        }

        merge_stats(stats, extracted)
        finalize_interaction_stats(stats, is_xhs=False)

        self.assertEqual(stats["like_count"], 12)
        self.assertEqual(stats["collect_count"], 3)
        self.assertEqual(stats["comment_count"], 4)
        self.assertEqual(stats["share_count"], 5)
        self.assertEqual(stats["interaction_status"], "verified_douyin_aweme_detail_statistics")
        self.assertEqual(stats["stats_sources"]["like_count"], "aweme_detail.statistics.digg_count")

    def test_douyin_untrusted_cached_stats_are_cleared(self) -> None:
        stats = {
            "like_count": 620,
            "collect_count": 1,
            "comment_count": 2,
            "share_count": 3,
        }

        finalize_interaction_stats(stats, is_xhs=False)

        self.assertIsNone(stats["like_count"])
        self.assertIsNone(stats["collect_count"])
        self.assertIsNone(stats["comment_count"])
        self.assertIsNone(stats["share_count"])
        self.assertEqual(stats["interaction_status"], "partial_missing_douyin_aweme_detail_statistics")
        self.assertEqual(
            set(stats["missing_interaction_fields"]),
            {
                "like_count",
                "collect_count",
                "comment_count",
                "share_count",
            },
        )

    def test_douyin_visible_text_stats_are_parsed_for_screenshot_fallback(self) -> None:
        extracted = _extract_visible_interaction_stats(
            "当一次青春男主角#成人礼 #毕业季 | "
            "52.8万 | 1964 | 1.3万 | 3.0万 | 举报 | 发布时间：2026-05-01"
        )

        self.assertEqual(extracted["like_count"], 528000)
        self.assertEqual(extracted["comment_count"], 1964)
        self.assertEqual(extracted["collect_count"], 13000)
        self.assertEqual(extracted["share_count"], 30000)
        self.assertEqual(
            extracted["stats_sources"]["like_count"],
            "douyin_webpage_visible_text.like_count",
        )


if __name__ == "__main__":
    unittest.main()
