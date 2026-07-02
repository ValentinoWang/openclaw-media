from __future__ import annotations

import unittest

from selfmedia.ingest.content_flow.src.downloader import (
    _extract_visible_interaction_stats,
    _extract_xhs_note_from_html,
    extract_top_comments,
    extract_douyin_stats_from_html,
    extract_stats_from_aweme,
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

    def test_douyin_aweme_post_stats_are_trusted(self) -> None:
        extracted = extract_stats_from_aweme(
            {
                "statistics": {
                    "digg_count": "12",
                    "collect_count": "3",
                    "comment_count": "4",
                    "share_count": "5",
                }
            },
            "aweme_post",
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
        self.assertEqual(stats["stats_sources"]["like_count"], "aweme_post.statistics.digg_count")

    def test_douyin_visible_text_labeled_stats_are_parsed(self) -> None:
        extracted = _extract_visible_interaction_stats(
            "某天你想起我 53.3万获赞 1978评论 1.3万收藏 3.0万分享"
        )

        self.assertEqual(extracted["like_count"], 533000)
        self.assertEqual(extracted["comment_count"], 1978)
        self.assertEqual(extracted["collect_count"], 13000)
        self.assertEqual(extracted["share_count"], 30000)

    def test_douyin_share_html_statistics_are_parsed(self) -> None:
        extracted = extract_douyin_stats_from_html(
            '<script>window.DATA={"statistics":{"aweme_id":"7635607170180867493",'
            '"comment_count":1169,"digg_count":28640,"play_count":0,'
            '"share_count":1207,"collect_count":1941}}</script>'
        )

        self.assertEqual(extracted["video_id"], "7635607170180867493")
        self.assertEqual(extracted["like_count"], 28640)
        self.assertEqual(extracted["collect_count"], 1941)
        self.assertEqual(extracted["comment_count"], 1169)
        self.assertEqual(extracted["share_count"], 1207)
        self.assertEqual(
            extracted["stats_sources"]["like_count"],
            "douyin_share_html.statistics.digg_count",
        )

    def test_xhs_collect_count_aliases_are_parsed(self) -> None:
        html = """
        <script>
        window.__INITIAL_STATE__ = {
          "note": {
            "currentNoteId": "69f18cef000000003502b62f",
            "noteDetailMap": {
              "69f18cef000000003502b62f": {
                "note": {
                  "noteId": "69f18cef000000003502b62f",
                  "title": "标题",
                  "desc": "正文",
                  "interactInfo": {
                    "likedCount": "597",
                    "favoriteCount": "88",
                    "commentCount": "20",
                    "shareCount": "249"
                  }
                }
              }
            }
          }
        };
        </script>
        """

        note = _extract_xhs_note_from_html(html)

        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note["like_count"], 597)
        self.assertEqual(note["collect_count"], 88)
        self.assertEqual(note["comment_count"], 20)
        self.assertEqual(note["share_count"], 249)
        self.assertEqual(note["stats_sources"]["collect_count"], "xhs.interactInfo.favoriteCount")

    def test_extract_top_comments_supports_douyin_comments_shape(self) -> None:
        comments = extract_top_comments(
            {
                "comments": [
                    {"cid": "c1", "text": "低赞", "user": {"nickname": "A"}, "digg_count": 1},
                    {"cid": "c2", "text": "最高赞", "user": {"nickname": "B"}, "digg_count": 99},
                    {"cid": "c3", "text": "第二", "user": {"nickname": "C"}, "digg_count": 60},
                    {"cid": "c4", "text": "第三", "user": {"nickname": "D"}, "digg_count": 30},
                ]
            },
            limit=3,
        )

        self.assertEqual([item["cid"] for item in comments], ["c2", "c3", "c4"])
        self.assertEqual(comments[0]["author"], "B")
        self.assertEqual(comments[0]["source_method"], "comment_list_response")

    def test_extract_top_comments_supports_nested_xhs_comment_list_shape(self) -> None:
        comments = extract_top_comments(
            {
                "data": {
                    "comment_list": [
                        {"comment_id": "x1", "content": "小红书第三", "user_info": {"nickname": "甲"}, "liked_count": 3},
                        {"comment_id": "x2", "content": "小红书第一", "user_info": {"nickname": "乙"}, "liked_count": 30},
                        {"comment_id": "x3", "content": "小红书第二", "user_info": {"nickname": "丙"}, "liked_count": 20},
                    ]
                }
            },
            limit=3,
        )

        self.assertEqual([item["cid"] for item in comments], ["x2", "x3", "x1"])
        self.assertEqual([item["text"] for item in comments], ["小红书第一", "小红书第二", "小红书第三"])


if __name__ == "__main__":
    unittest.main()
