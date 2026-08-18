from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from selfmedia.context import (
    build_media_context,
    looks_like_media_review,
    record_creation_memory,
    record_review_memory,
    render_context_for_prompt,
)
from selfmedia.context.media_context import merge_creator_profile_identity
from selfmedia.creation.request_parser import parse_creation_request


class MediaContextTests(unittest.TestCase):
    def test_missing_account_context_does_not_create_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_media_context(platform="小红书", account="QA_NOT_FOUND", tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)

            self.assertFalse(context["loaded"]["account_profile"])
            self.assertFalse((Path(tmp) / "account_profiles").exists())

    def test_review_updates_account_profile_and_future_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = record_review_memory(
                "【复盘】平台=小红书 账号=主账号 主题=表达力 点赞=1200 收藏=500 结论=封面直接写痛点有效，下一条继续保留强痛点首图",
                tenant_id="00000000-0000-4000-8000-000000000101",
                root=tmp,
            )
            self.assertEqual(result["status"], "recorded")
            self.assertTrue(Path(result["profile"]["path"]).exists())
            self.assertIn("tenants/00000000-0000-4000-8000-000000000101", result["profile"]["path"])

            context = build_media_context(platform="小红书", account="主账号", topic="表达力", tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            self.assertTrue(context["loaded"]["account_profile"])
            self.assertEqual(context["loaded"]["recent_reviews"], 1)
            self.assertIn("封面直接写痛点有效", context["prompt"])

            other_tenant = build_media_context(
                platform="小红书",
                account="主账号",
                topic="表达力",
                tenant_id="00000000-0000-4000-8000-000000000202",
                root=tmp,
            )
            self.assertFalse(other_tenant["loaded"]["account_profile"])
            self.assertEqual(other_tenant["loaded"]["recent_reviews"], 0)

    def test_creation_memory_is_loaded_by_account_and_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            req = parse_creation_request("【创作>小红书】赛道=职场成长 类型=图文 主体=表达力 账号=主账号 发布时间=今晚8点")
            result = record_creation_memory(
                req,
                tenant_id="00000000-0000-4000-8000-000000000101",
                draft={"title": "表达力这样练", "tags": ["职场成长", "表达力"], "positioning_analysis": {"positioning": "职场成长账号的表达训练栏目"}},
                root=tmp,
            )
            self.assertEqual(result["status"], "recorded")

            context = build_media_context(platform="小红书", account="主账号", topic="表达力", tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            self.assertEqual(context["loaded"]["recent_creations"], 1)
            self.assertIn("职场成长账号", context["prompt"])

    def test_media_review_detection_is_conservative(self) -> None:
        self.assertTrue(looks_like_media_review("平台=抖音 账号=主账号 播放=3000 点赞=120 结论=前5秒留存低"))
        self.assertFalse(looks_like_media_review("今天会议复盘：沟通顺序需要调整"))

    def test_creator_profile_identity_fields_render_into_context_prompt(self) -> None:
        profile = merge_creator_profile_identity(
            {"platform": "小红书", "account": "小王"},
            {
                "identity_summary": "清华AI硕短跑博主",
                "profile_url": "https://example.com/xiaowang",
                "identity_tags": ["清华", "AI", "体育生"],
                "education_background": "清华大学AI硕士",
                "expertise_domains": ["AI科研", "短跑训练"],
                "creator_role": "校园AI运动博主",
                "public_persona_boundaries": "可说清华和短跑，不提私人联系方式",
                "story_usable_identity_points": "AI硕士冲短跑一级的反差",
            },
        )

        prompt = render_context_for_prompt({"account_profile": profile})

        self.assertIn("身份定位：清华AI硕短跑博主", prompt)
        self.assertIn("主页链接：https://example.com/xiaowang", prompt)
        self.assertIn("身份标签：清华、AI、体育生", prompt)
        self.assertIn("公开表达边界：可说清华和短跑，不提私人联系方式", prompt)
        self.assertIn("可创作身份卖点：AI硕士冲短跑一级的反差", prompt)


if __name__ == "__main__":
    unittest.main()
