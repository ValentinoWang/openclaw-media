from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import selfmedia.ingest.content_flow.src.analyzer as analyzer


class AnalyzerEvidenceContractTest(unittest.TestCase):
    def _captured_parts(self, user_content: str) -> list[dict[str, object]]:
        captured: dict[str, list[dict[str, object]]] = {}

        def fake_generate_json_from_parts(
            parts: list[dict[str, object]], settings: object, **kwargs: object
        ) -> dict[str, str]:
            captured["parts"] = parts
            return {"title": "已捕获证据"}

        with (
            patch.object(
                analyzer,
                "load_profile_llm_settings",
                return_value=SimpleNamespace(model="test-model"),
            ),
            patch.object(analyzer, "generate_json_from_parts", side_effect=fake_generate_json_from_parts),
        ):
            analyzer.analyze_with_openclaw_agent(user_content, object())

        return captured["parts"]

    def test_text_only_call_marks_visual_and_engagement_unavailable_without_media_paths(self) -> None:
        user_content = analyzer._build_analysis_user_content(
            transcript="这是可供分析的逐字稿。",
            url="https://example.com/video",
            video_path="/private/media/source.mp4",
            image_paths=None,
            caption="这是文案。",
            image_ocr="",
            media_type="video",
        )

        parts = self._captured_parts(user_content)
        message = str(parts[0]["text"])

        self.assertEqual(len(parts), 1)
        self.assertIn("- 视觉画面: unavailable", message)
        self.assertIn("- 互动数据: unavailable", message)
        self.assertIn("visual_cues 必须为空字符串", message)
        self.assertNotIn("/private/media/source.mp4", message)
        self.assertNotIn("本地视频文件", message)
        self.assertNotIn("以图片内容为主", message)

    def test_available_image_evidence_is_attached_to_the_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "evidence.jpg"
            image_path.write_bytes(b"attached-image-evidence")
            user_content = analyzer._build_analysis_user_content(
                transcript="",
                url="https://example.com/image",
                video_path=None,
                image_paths=[str(image_path)],
                caption="图文文案",
                image_ocr="OCR 文本",
                media_type="image",
            )

            parts = self._captured_parts(user_content)

        self.assertIn("- 视觉画面: available", str(parts[0]["text"]))
        self.assertEqual(len(parts), 2)
        self.assertIn("image_data", parts[1])
        image_data = parts[1]["image_data"]
        assert isinstance(image_data, dict)
        self.assertEqual(image_data["mime_type"], "image/jpeg")
        self.assertTrue(str(image_data["data"]))

    def test_missing_image_evidence_is_not_sent_as_a_path_or_visual_input(self) -> None:
        missing_path = "/private/media/missing-image.jpg"
        user_content = analyzer._build_analysis_user_content(
            transcript="",
            url="https://example.com/image",
            video_path=None,
            image_paths=[missing_path],
            caption="仅有文案",
            image_ocr="",
            media_type="image",
        )

        parts = self._captured_parts(user_content)
        message = str(parts[0]["text"])

        self.assertEqual(len(parts), 1)
        self.assertIn("- 视觉画面: unavailable", message)
        self.assertNotIn(missing_path, message)
        self.assertNotIn("本地图片文件", message)


if __name__ == "__main__":
    unittest.main()
