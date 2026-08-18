from __future__ import annotations

import unittest
from types import SimpleNamespace

from selfmedia.ingest.content_flow.src.notion_writer import _build_children, write_to_notion


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


if __name__ == "__main__":
    unittest.main()
