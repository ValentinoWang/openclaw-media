from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.media_context import (
    build_media_context,
    looks_like_media_review,
    record_creation_memory,
    record_review_memory,
)
from tools.creation.request_parser import parse_creation_request


class MediaContextTests(unittest.TestCase):
    def test_review_updates_account_profile_and_future_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = record_review_memory(
                "【复盘】平台=小红书 账号=主账号 主题=表达力 点赞=1200 收藏=500 结论=封面直接写痛点有效，下一条继续保留强痛点首图",
                root=tmp,
            )
            self.assertEqual(result["status"], "recorded")
            self.assertTrue(Path(result["profile"]["path"]).exists())

            context = build_media_context(platform="小红书", account="主账号", topic="表达力", root=tmp)
            self.assertTrue(context["loaded"]["account_profile"])
            self.assertEqual(context["loaded"]["recent_reviews"], 1)
            self.assertIn("封面直接写痛点有效", context["prompt"])

    def test_creation_memory_is_loaded_by_account_and_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            req = parse_creation_request("【创作-小红书】赛道=职场成长 类型=图文 主体=表达力 账号=主账号 发布时间=今晚8点")
            result = record_creation_memory(
                req,
                draft={"title": "表达力这样练", "tags": ["职场成长", "表达力"], "positioning_analysis": {"positioning": "职场成长账号的表达训练栏目"}},
                root=tmp,
            )
            self.assertEqual(result["status"], "recorded")

            context = build_media_context(platform="小红书", account="主账号", topic="表达力", root=tmp)
            self.assertEqual(context["loaded"]["recent_creations"], 1)
            self.assertIn("职场成长账号", context["prompt"])

    def test_media_review_detection_is_conservative(self) -> None:
        self.assertTrue(looks_like_media_review("平台=抖音 账号=主账号 播放=3000 点赞=120 结论=前5秒留存低"))
        self.assertFalse(looks_like_media_review("今天会议复盘：沟通顺序需要调整"))


if __name__ == "__main__":
    unittest.main()
