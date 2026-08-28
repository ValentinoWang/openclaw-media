from __future__ import annotations

from datetime import datetime, timezone
import unittest

from openclaw_app.models.message import Message
from openclaw_app.router.content_os_renderers import ContentOSRenderersMixin
from openclaw_app.router.content_os_utils import ContentOSUtilsMixin


class RendererHarness(ContentOSRenderersMixin, ContentOSUtilsMixin):
    pass


class ContentOSBridgePresentationTests(unittest.TestCase):
    @staticmethod
    def _message() -> Message:
        return Message(
            entry_tag="内容创作",
            raw_text="项目ID：internal_project_001\n用户原始要求",
            body="用户原始要求",
            source="test",
            chat_type="group",
            created_at=datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc),
            metadata={},
        )

    @staticmethod
    def _parsed() -> dict[str, object]:
        return {
            "creation_record_id": "creation_internal_001",
            "doc_link": "https://example.feishu.cn/docx/internal",
            "internal_only": {"runner": "cloud", "lease": "hidden"},
            "draft": {
                "title": "主标题：毕业典礼第一视角",
                "script_options": [{"title": "候选标题：把清华毕业典礼拍成一条片", "angle": "结果先行"}],
                "final_copy": "完整成稿：我终于站到了毕业典礼现场。",
                "hook_3s": "3 秒钩子：第一眼看到这个画面，我愣住了。",
                "voiceover": "口播：我原以为只是旁观，结果成了故事里的人。",
                "storyboard": [
                    {
                        "time": "0-3 秒",
                        "visual": "礼堂门打开",
                        "subtitle": "我真的毕业了",
                        "sound": "门响和欢呼",
                        "shooting_note": "镜头从低处推入",
                    }
                ],
                "image_script": [{"page": "第 1 页", "visual": "毕业帽特写", "caption": "原来这一刻真的会来"}],
                "next_actions": ["确认封面后由发布负责人发布"],
                "creator_report": {
                    "publishing_pack": {
                        "cover_text": "我真的毕业了",
                        "body_copy": "发布正文：这一刻比想象中更快。",
                        "pinned_comment": "你最想回到哪一天？",
                        "comment_prompt": "评论区说说你的毕业瞬间",
                        "first_hour_action": "发布后首小时回复前三十条评论",
                        "hashtags": ["#毕业", "#第一视角"],
                    }
                },
            },
        }

    def test_creation_script_renders_execution_fields_before_traceability_appendix(self) -> None:
        document = RendererHarness()._render_content_os_creation_script_section(
            self._message(),
            self._parsed(),
            "生成说明仅用于追溯。",
            "https://example.feishu.cn/docx/internal",
            "creation_internal_001",
        )

        expected = (
            "主标题：毕业典礼第一视角",
            "候选标题：把清华毕业典礼拍成一条片",
            "完整成稿：我终于站到了毕业典礼现场。",
            "3 秒钩子：第一眼看到这个画面，我愣住了。",
            "口播：我原以为只是旁观，结果成了故事里的人。",
            "礼堂门打开",
            "毕业帽特写",
            "发布后首小时回复前三十条评论",
            "确认封面后由发布负责人发布",
        )
        for value in expected:
            self.assertIn(value, document)

        headings = (
            "## 标题",
            "## 标题候选",
            "## 成稿",
            "## 3 秒钩子",
            "## 口播",
            "## 镜头脚本",
            "## 图文脚本",
            "## 发布动作",
            "## 下一步",
            "## 追溯附录",
        )
        positions = [document.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        appendix_start = document.index("## 追溯附录")
        for metadata in ("creation_internal_001", "https://example.feishu.cn/docx/internal", "internal_only"):
            self.assertGreater(document.index(metadata), appendix_start)

        publish_document = RendererHarness()._render_content_os_publish_pack_section(
            self._message(),
            self._parsed(),
            "生成说明仅用于追溯。",
            "https://example.feishu.cn/docx/internal",
            "creation_internal_001",
        )
        publish_appendix = publish_document.index("## 追溯附录")
        self.assertLess(publish_document.index("发布后首小时回复前三十条评论"), publish_appendix)
        self.assertLess(publish_document.index("确认封面后由发布负责人发布"), publish_appendix)
        self.assertGreater(publish_document.index("creation_internal_001"), publish_appendix)

    def test_initial_script_renders_bridge_fields_without_dict_representations(self) -> None:
        document = RendererHarness()._render_content_os_initial_script(
            project_id="internal_project_001",
            idea_id="idea_internal_001",
            title="毕业典礼第一视角",
            result={
                "title_options": [{"title": "候选标题", "angle": "结果先行"}],
                "hook_options": ["开头 3 秒先给结果"],
                "final_copy": "已经映射的成稿",
                "voiceover": "已经映射的口播",
                "storyboard": [{"time": "0-3 秒", "visual": "镜头画面", "subtitle": "字幕"}],
                "image_script": [{"page": "第 1 页", "visual": "图文画面", "caption": "图文文案"}],
                "publishing_pack": {"first_hour_action": "发布后回复评论"},
                "next_actions": ["下一步确认发布"],
            },
            platform="抖音",
            created_date="20260829",
            record_text="record_id=internal_record_001",
        )

        for value in ("候选标题", "已经映射的成稿", "已经映射的口播", "镜头画面", "图文画面", "发布后回复评论", "下一步确认发布"):
            self.assertIn(value, document)
        self.assertNotIn("{'title': '候选标题'", document)
        self.assertIn("非创作桥生成的口播", document)
        self.assertGreater(document.index("internal_record_001"), document.index("## 追溯附录"))

    def test_missing_creation_fields_are_explicit_and_not_substituted(self) -> None:
        document = RendererHarness()._render_content_os_creation_script_section(
            self._message(),
            {"draft": {"title": "仅有标题"}},
            "",
            "",
            "",
        )

        for missing in ("创作桥未提供成稿。", "创作桥未提供 3 秒钩子。", "创作桥未提供口播。", "创作桥未提供镜头脚本。", "创作桥未提供图文脚本。", "创作桥未提供发布动作。", "创作桥未提供下一步。"):
            self.assertIn(missing, document)
        self.assertNotIn("开头：用一句话抛出悬念。", document)

    def test_review_moves_metadata_after_conclusion_and_next_actions(self) -> None:
        document = RendererHarness()._render_content_os_data_review_section(
            self._message(),
            {
                "record_id": "review_internal_001",
                "doc_link": "https://example.feishu.cn/docx/review",
                "next_actions": ["下一步复盘动作"],
            },
            "复盘结论：保留开头镜头。",
        )

        appendix_start = document.index("## 追溯附录")
        self.assertLess(document.index("复盘结论：保留开头镜头。"), appendix_start)
        self.assertLess(document.index("下一步复盘动作"), appendix_start)
        self.assertGreater(document.index("review_internal_001"), appendix_start)
        self.assertGreater(document.index("https://example.feishu.cn/docx/review"), appendix_start)


if __name__ == "__main__":
    unittest.main()
