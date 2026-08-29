from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from selfmedia.context import (
    build_media_context,
    looks_like_media_review,
    record_creation_memory,
    record_review_memory,
    render_context_for_prompt,
)
from selfmedia.context.media_context import MEDIA_CONTEXT_RULES_ROOT_ENV, merge_creator_profile_identity
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

    def test_creator_profile_error_is_visible_to_prompt(self) -> None:
        prompt = render_context_for_prompt({"creator_profile_error": "字段契约不可用"})

        self.assertIn("达人档案加载失败：字段契约不可用", prompt)
        self.assertIn("人设未注入", prompt)

    def test_explicit_review_patterns_do_not_depend_on_single_character_rating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = record_review_memory(
                "【复盘】平台=小红书 账号=主账号 主题=表达力 结论=跳出率高但收藏低",
                tenant_id="00000000-0000-4000-8000-000000000101",
                root=tmp,
                analysis={
                    "effective_patterns": ["冲突式开头"],
                    "failure_reasons": ["信息密度过高"],
                },
            )

            profile = json.loads(Path(result["profile"]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(profile["proven_patterns"], ["冲突式开头"])
            self.assertEqual(profile["avoid_patterns"], ["信息密度过高"])

    def test_context_consumes_tenant_daily_metrics_and_comments(self) -> None:
        tenant_id = "00000000-0000-4000-8000-000000000101"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": tmp}, clear=False):
            daily_root = Path(tmp) / "tenants" / tenant_id / "account_daily_runs"
            daily_root.mkdir(parents=True)
            (daily_root / "account_daily_20260828.json").write_text(
                json.dumps(
                    {
                        "tenant_id": tenant_id,
                        "accounts": [{"record_id": "acc_1", "account_name": "主账号", "platform": "小红书"}],
                        "summaries": [{"account_name": "主账号", "platform": "小红书", "captured_at": "2026-08-28T09:00:00+08:00", "post_count": 2, "total_interactions": 66, "best_post_url": "https://example.test/best"}],
                        "rows": {"acc_1": [{"top_comments": [{"text": "求这个训练方案"}]}]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            context = build_media_context(platform="小红书", account="主账号", tenant_id=tenant_id, root=tmp)

        self.assertEqual(context["loaded"]["recent_daily_metrics"], 1)
        self.assertEqual(context["top_comments"], ["求这个训练方案"])
        self.assertIn("最近自有作品日报指标", context["prompt"])
        self.assertIn("最近自有作品高价值评论原话（日报采集）", context["prompt"])
        self.assertIn("求这个训练方案", context["prompt"])

    def test_review_patterns_require_structured_rating_and_remain_exclusive(self) -> None:
        tenant_id = "00000000-0000-4000-8000-000000000101"
        with tempfile.TemporaryDirectory() as tmp:
            record_review_memory(
                "平台=小红书 账号=主账号 结论=播放量低但收藏高的封面结构仍值得沿用",
                tenant_id=tenant_id,
                analysis={"performance_level": "高价值延续"},
                root=tmp,
            )
            record_review_memory(
                "平台=小红书 账号=主账号 结论=看似表现好但评论区反复追问的结构不能沿用",
                tenant_id=tenant_id,
                analysis={"performance_level": "不建议延续"},
                root=tmp,
            )
            record_review_memory(
                "平台=小红书 账号=主账号 结论=播放量高低并存，只记录待验证经验",
                tenant_id=tenant_id,
                root=tmp,
            )

            context = build_media_context(platform="小红书", account="主账号", tenant_id=tenant_id, root=tmp)

        profile = context["account_profile"]
        self.assertEqual(profile["proven_patterns"], ["播放量低但收藏高的封面结构仍值得沿用"])
        self.assertEqual(profile["avoid_patterns"], ["看似表现好但评论区反复追问的结构不能沿用"])
        self.assertTrue(set(profile["proven_patterns"]).isdisjoint(profile["avoid_patterns"]))

    def test_rules_root_is_configurable_and_creator_profile_failure_is_visible(self) -> None:
        tenant_id = "00000000-0000-4000-8000-000000000101"
        with tempfile.TemporaryDirectory() as tmp:
            rules_root = Path(tmp) / "rules"
            rules_root.mkdir()
            (rules_root / "USER.md").write_text("- 小红书创作必须保留真实评论原话\n", encoding="utf-8")
            with patch.dict(os.environ, {MEDIA_CONTEXT_RULES_ROOT_ENV: str(rules_root)}, clear=False):
                context = build_media_context(platform="小红书", account="主账号", tenant_id=tenant_id, root=tmp)

        self.assertEqual(context["global_rules"], ["- 小红书创作必须保留真实评论原话"])
        self.assertIn("媒体 Bot 长期规则摘要", context["prompt"])
        failure_prompt = render_context_for_prompt(
            {
                "creator_profile_error": "CreatorProfile 字段契约不可用",
            }
        )
        self.assertIn("账号档案加载失败：CreatorProfile 字段契约不可用（人设未注入）", failure_prompt)
        self.assertEqual(failure_prompt.count("CreatorProfile 字段契约不可用"), 1)


if __name__ == "__main__":
    unittest.main()
