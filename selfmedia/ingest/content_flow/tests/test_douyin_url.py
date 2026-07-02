from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from selfmedia.ingest.content_flow.src.downloader import (
    append_unique_douyin_aweme_image_url,
    append_unique_url,
    clean_douyin_url,
    is_douyin_aweme_image_url,
)


class CleanDouyinUrlTest(unittest.TestCase):
    def test_short_link_keeps_douyin_video_entry_point(self) -> None:
        response = Mock()
        response.url = "https://www.douyin.com/video/1234567890"
        response.status_code = 200
        response.history = [Mock(url="https://v.douyin.com/abc/")]

        with patch("selfmedia.ingest.content_flow.src.downloader.requests.get", return_value=response):
            cleaned = clean_douyin_url("https://v.douyin.com/abc/")

        self.assertEqual(cleaned, "https://www.douyin.com/video/1234567890")

    def test_note_short_link_keeps_note_entry_point(self) -> None:
        response = Mock()
        response.url = "https://www.douyin.com/note/9876543210"
        response.status_code = 200
        response.history = [Mock(url="https://v.douyin.com/noteabc/")]

        with patch("selfmedia.ingest.content_flow.src.downloader.requests.get", return_value=response):
            cleaned = clean_douyin_url("https://v.douyin.com/noteabc/")

        self.assertEqual(cleaned, "https://www.douyin.com/note/9876543210")

    def test_non_douyin_url_is_returned_unchanged(self) -> None:
        self.assertEqual(clean_douyin_url("https://example.com/a"), "https://example.com/a")

    def test_douyin_aweme_image_url_matches_original_reflow_images(self) -> None:
        self.assertTrue(
            is_douyin_aweme_image_url(
                "https://p3-sign.douyinpic.com/tos-cn-i-0813/image.webp"
                "?s=PackSourceEnum_DOUYIN_REFLOW&biz_tag=aweme_images"
            )
        )
        self.assertFalse(
            is_douyin_aweme_image_url(
                "https://p3-sign.douyinpic.com/tos-cn-i-0813/related.webp"
                "?s=PackSourceEnum_IMAGE_RELATED_FEED&biz_tag=aweme_images"
            )
        )
        self.assertFalse(
            is_douyin_aweme_image_url(
                "https://p3-sign.douyinpic.com/tos-cn-i-0813/avatar.jpeg?from=327834062"
            )
        )

    def test_append_unique_url_keeps_first_occurrence(self) -> None:
        urls: list[str] = []

        append_unique_url(urls, " https://example.com/a.webp ")
        append_unique_url(urls, "https://example.com/a.webp")
        append_unique_url(urls, "")

        self.assertEqual(urls, ["https://example.com/a.webp"])

    def test_append_unique_douyin_aweme_image_url_dedupes_resized_variants(self) -> None:
        urls: list[str] = []

        append_unique_douyin_aweme_image_url(
            urls,
            "https://p3-sign.douyinpic.com/tos-cn-i-0813/image-a"
            "~tplv-dy-shrink:480:1038.webp?s=PackSourceEnum_DOUYIN_REFLOW&biz_tag=aweme_images",
        )
        append_unique_douyin_aweme_image_url(
            urls,
            "https://p3-sign.douyinpic.com/tos-cn-i-0813/image-a"
            "~tplv-dy-resize-walign-adapt-aq:540:q75.webp"
            "?s=PackSourceEnum_DOUYIN_REFLOW&biz_tag=aweme_images",
        )
        append_unique_douyin_aweme_image_url(
            urls,
            "https://p3-sign.douyinpic.com/tos-cn-i-0813/image-b"
            "~tplv-dy-shrink:480:1038.webp?s=PackSourceEnum_DOUYIN_REFLOW&biz_tag=aweme_images",
        )

        self.assertEqual(len(urls), 2)


if __name__ == "__main__":
    unittest.main()
