from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from selfmedia.ingest.content_flow.src.downloader import (
    append_unique_douyin_aweme_image_url,
    append_unique_url,
    cached_media_type_prefers_images,
    clean_douyin_url,
    extract_router_data,
    find_caption_in_render_data,
    find_images_in_render_data,
    is_douyin_aweme_image_url,
    reconcile_caption_with_page_metadata,
    should_prefer_douyin_note_images,
)
from selfmedia.ingest.content_flow.src.utils import detect_platform, is_xiaohongshu_url


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

    def test_xhslink_cn_short_link_uses_xiaohongshu_redirect_path(self) -> None:
        response = Mock()
        response.url = "https://www.xiaohongshu.com/explore/1234567890abcdef"

        with patch("selfmedia.ingest.content_flow.src.downloader.requests.get", return_value=response) as request:
            cleaned = clean_douyin_url("http://xhslink.cn/o/2L1gituNZCn")

        self.assertEqual(cleaned, response.url)
        request.assert_called_once()
        self.assertTrue(is_xiaohongshu_url("http://xhslink.cn/o/2L1gituNZCn"))
        self.assertEqual(detect_platform("http://xhslink.cn/o/2L1gituNZCn"), "小红书")
        self.assertFalse(is_xiaohongshu_url("https://xhslink.cn.example.test/o/spoofed"))

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

    def test_router_data_exposes_note_caption_and_images(self) -> None:
        html = """
        <html><head></head><body>
        <script>window._ROUTER_DATA = {"loaderData":{"note_(id)/page":{"videoInfoRes":{"item_list":[{"desc":"完整图文正文，包含很多平台文案。","images":[{"url_list":["https://p3-sign.douyinpic.com/tos-cn-i-0813/image-a~tplv.webp?s=PackSourceEnum_DOUYIN_REFLOW&biz_tag=aweme_images"]}],"video":{"play_addr":{"url_list":["https://www.iesdouyin.com/aweme/v1/playwm/?video_id=https://sf11-cdn-tos.example/audio"]}}}]}}}};</script>
        </body></html>
        """

        payload = extract_router_data(html)

        self.assertIsNotNone(payload)
        self.assertEqual(find_caption_in_render_data(payload), "完整图文正文，包含很多平台文案。")
        self.assertEqual(
            find_images_in_render_data(payload),
            [
                "https://p3-sign.douyinpic.com/tos-cn-i-0813/image-a~tplv.webp"
                "?s=PackSourceEnum_DOUYIN_REFLOW&biz_tag=aweme_images"
            ],
        )

    def test_note_page_images_win_over_play_addr_candidate(self) -> None:
        self.assertTrue(
            should_prefer_douyin_note_images(
                "https://v.douyin.com/J-Z72L8hiro/",
                "https://www.iesdouyin.com/share/note/7659313340270923008/",
                ["https://p3-sign.douyinpic.com/tos-cn-i-0813/image-a.webp"],
            )
        )
        self.assertFalse(
            should_prefer_douyin_note_images(
                "https://www.douyin.com/video/7659313340270923008/",
                "",
                ["https://p3-sign.douyinpic.com/tos-cn-i-0813/cover.webp"],
            )
        )
        self.assertTrue(cached_media_type_prefers_images("图文"))
        self.assertFalse(cached_media_type_prefers_images("video"))

    def test_render_data_image_extraction_dedupes_resized_variants(self) -> None:
        payload = {
            "images": [
                {
                    "url_list": [
                        "https://p3-sign.douyinpic.com/tos-cn-i-0813/image-a"
                        "~tplv-dy-shrink:480:1038.webp?s=PackSourceEnum_DOUYIN_REFLOW&biz_tag=aweme_images"
                    ]
                }
            ],
            "nested": {
                "images": [
                    {
                        "url_list": [
                            "https://p3-sign.douyinpic.com/tos-cn-i-0813/image-a"
                            "~tplv-dy-resize-walign-adapt-aq:540:q75.webp"
                            "?s=PackSourceEnum_DOUYIN_REFLOW&biz_tag=aweme_images"
                        ]
                    },
                    {"url_list": ["https://p3-sign.douyinpic.com/tos-cn-i-0813/image-b.webp"]},
                ]
            },
        }

        self.assertEqual(len(find_images_in_render_data(payload)), 2)

    def test_image_cache_caption_is_trusted_without_page_title(self) -> None:
        self.assertEqual(
            reconcile_caption_with_page_metadata(
                "完整图文正文",
                {"caption_source": "image_cache.caption"},
            ),
            "完整图文正文",
        )


if __name__ == "__main__":
    unittest.main()
