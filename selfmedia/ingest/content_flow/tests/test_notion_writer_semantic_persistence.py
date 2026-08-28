from __future__ import annotations

import unittest
from types import SimpleNamespace

from selfmedia.ingest.content_flow.src.notion_writer import (
    _build_children,
    _build_properties,
    _normalize_text,
    write_to_notion,
)


class NotionWriterSemanticPersistenceTest(unittest.TestCase):
    @staticmethod
    def _analysis() -> dict:
        return {
            "analysis_provider": "codex_responses",
            "analysis_status": "complete",
            "semantic_persistence_version": "llm_cleaned_user_fields_v1",
            "title": "LLM 清洗后的标题",
            "caption": "原始平台文案",
            "work_copy": "LLM 清洗后的平台文案",
            "full_content": "LLM 清洗后的完整内容",
            "summary": "LLM 摘要",
        }

    def test_children_use_only_llm_cleaned_user_fields(self) -> None:
        children = _build_children(self._analysis(), "https://example.com/post")
        rendered = str(children)

        self.assertIn("LLM 清洗后的平台文案", rendered)
        self.assertIn("LLM 清洗后的完整内容", rendered)
        self.assertNotIn("原始平台文案", rendered)
        self.assertNotIn("原始逐字稿", rendered)

    def test_writer_stops_before_notion_call_without_llm_cleaned_fields(self) -> None:
        settings = SimpleNamespace(notion_token="token", notion_database_id="database")

        result = write_to_notion(
            "https://example.com/post",
            "原始逐字稿",
            "原始平台文案",
            {"analysis_provider": "codex_responses", "analysis_status": "complete"},
            settings,
        )

        self.assertIsNone(result)

    def test_structured_user_fields_are_rendered_as_readable_lines(self) -> None:
        rendered = _normalize_text({"开头": "先给结论", "步骤": [{"动作": "展示前后对比"}]})

        self.assertIn("开头：先给结论", rendered)
        self.assertIn("步骤：动作：展示前后对比", rendered)
        self.assertNotIn("{", rendered)
        self.assertNotIn('"开头"', rendered)

    def test_interaction_notice_hides_machine_status_path_and_exception(self) -> None:
        properties = {
            "Name": {"type": "title"},
            "互动状态": {"type": "rich_text"},
        }
        analysis = {
            **self._analysis(),
            "interaction_status": "partial_missing_douyin_aweme_detail_statistics",
            "interaction_screenshot_status": "capture_failed",
            "interaction_screenshot_path": "/Users/vsiyo/private/screenshots/interaction.png",
            "interaction_screenshot_error": "BrowserError: raw internal failure",
        }

        notion_props = _build_properties(properties, "标题", "https://example.com/post", analysis)
        rendered = notion_props["互动状态"]["rich_text"][0]["text"]["content"]

        self.assertIn("部分数据缺失，待复核", rendered)
        self.assertIn("截图失败，待复核", rendered)
        self.assertNotIn("partial_missing_douyin_aweme_detail_statistics", rendered)
        self.assertNotIn("capture_failed", rendered)
        self.assertNotIn("/Users/vsiyo", rendered)
        self.assertNotIn("BrowserError", rendered)


if __name__ == "__main__":
    unittest.main()
