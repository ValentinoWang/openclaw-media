from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openclaw_app.services.completion_guard import CompletionGuard
from openclaw_app.services.content_flow_client import ContentFlowClient
from openclaw_app.router.media_knowledge_fields import MediaKnowledgeFieldsMixin


class KnowledgeFieldHarness(MediaKnowledgeFieldsMixin):
    def _extract_first_url(self, text: str) -> str:
        return "http://xhslink.com/o/example" if "xhslink.com" in text else ""


class ContentFlowClientCompletionTest(unittest.TestCase):
    def test_parse_json_payload_accepts_fenced_model_reply(self) -> None:
        payload = ContentFlowClient._parse_json_payload(
            '整理结果如下：\n```json\n{"title":"体育训练软件定位讨论","summary":"内容整理"}\n```\n后续说明 {非 JSON}'
        )

        self.assertEqual(payload["title"], "体育训练软件定位讨论")

    def test_parse_json_payload_prefers_structured_object_among_multiple_objects(self) -> None:
        payload = ContentFlowClient._parse_json_payload(
            '{"debug": "ignored"}\n正文：{"title":"体育训练软件定位讨论","pending_questions":[]}'
        )

        self.assertEqual(payload["title"], "体育训练软件定位讨论")

    def test_loads_analysis_json_after_job_payload_has_no_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            analysis_path = media_dir / "analysis.json"
            analysis_path.write_text(
                json.dumps(
                    {
                        "title": "开源动捕工具把专业设备降到摄像头",
                        "summary": ["普通摄像头可以生成3D人体骨骼数据。"],
                        "primary_category": "AI/工具",
                        "secondary_category": "AI工具应用",
                        "action_plan": "1. 展示工具。2. 展示场景。3. 展示结果。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            client = ContentFlowClient("", workspace_root=tmp)
            payload = client.complete_analysis_payload(
                "http://xhslink.com/o/example",
                {"status": "done", "media_dir": str(media_dir), "analysis_path": str(analysis_path)},
                wait=False,
            )

        self.assertEqual(payload["analysis"]["title"], "开源动捕工具把专业设备降到摄像头")

    def test_falls_back_from_caption_when_structured_analysis_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = ContentFlowClient("", workspace_root=tmp)
            payload = client.complete_analysis_payload(
                "http://xhslink.com/o/example",
                {
                    "status": "done",
                    "caption": "开源3D精准动捕工具，能导出多种格式\n#AI工具[话题]# #开源[话题]#",
                    "video_path": "/tmp/video.mp4",
                    "media_type": "video",
                },
                wait=False,
            )

        self.assertEqual(payload["analysis"]["analysis_provider"], "tag-router-fallback")
        self.assertEqual(payload["analysis"]["primary_category"], "AI/工具")
        self.assertIn("AI工具", payload["analysis"]["tags"])

    def test_completion_guard_routes_all_media_analysis_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            guard = CompletionGuard(ContentFlowClient("", workspace_root=tmp))
            for kind in ("content_flow_analysis", "内容素材", "自媒体知识"):
                payload = guard.complete_external_result(
                    kind=kind,
                    body="http://xhslink.com/o/example",
                    result={
                        "status": "done",
                        "caption": "开源3D精准动捕工具，能导出多种格式\n#AI工具[话题]#",
                        "video_path": "/tmp/video.mp4",
                        "media_type": "video",
                    },
                    wait=False,
                )
                self.assertEqual(payload["analysis"]["analysis_provider"], "tag-router-fallback")

    def test_image_knowledge_stores_images_in_original_file_attachment_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "note.jpg"
            image_path.write_bytes(b"image")
            payload = {
                "status": "done",
                "caption": "用 AI 做自媒体选题，不要只说帮我想 10 个标题",
                "image_ocr": "## 01 image-01.jpg\nAl 自媒体\n用Al做选题\n误区 €D\n第1页：先拆人群、痛点、角度\n€D",
                "image_paths": [str(image_path)],
                "media_type": "image",
                "analysis": {
                    "title": "AI 自媒体选题方法",
                    "summary": "先拆人群痛点，再产出标题。",
                    "platform": "小红书",
                    "media_type": "image",
                    "target_audience": "AI 小白",
                    "pain_point": "标题同质化",
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("http://xhslink.com/o/example", payload, allow_body_fallback=False)

        self.assertEqual(fields["内容类型"], "图文")
        self.assertIn("全部文案", fields)
        self.assertEqual(fields["全部文案"], "用 AI 做自媒体选题，不要只说帮我想 10 个标题")
        self.assertIn("全部内容", fields)
        self.assertNotIn("## 01 image-01.jpg", fields["全部内容"])
        self.assertNotIn("€D", fields["全部内容"])
        self.assertIn("AI 自媒体", fields["全部内容"])
        self.assertIn("用AI做选题", fields["全部内容"])
        self.assertIn("误区", fields["全部内容"])
        self.assertIn("第1页：先拆人群、痛点、角度", fields["全部内容"])
        self.assertEqual(fields["目标人群"], "AI 小白")
        self.assertEqual(fields["核心痛点"], "标题同质化")
        self.assertEqual(fields["_attachment_fields"], {"原文件": [str(image_path)]})

    def test_caption_wins_for_work_copy_when_model_returns_cleaned_content(self) -> None:
        payload = {
            "status": "done",
            "caption": "原始平台文案",
            "image_ocr": "## 01 image-01.jpg\nAl 噪声",
            "media_type": "image",
            "analysis": {
                "title": "AI 自媒体选题方法",
                "summary": "先拆人群痛点，再产出标题。",
                "platform": "小红书",
                "media_type": "image",
                "work_copy": "模型清洗后的正文",
            },
        }
        harness = KnowledgeFieldHarness()
        fields = harness._knowledge_extra_fields("http://xhslink.com/o/example", payload, allow_body_fallback=False)

        self.assertEqual(fields["全部文案"], "原始平台文案")
        self.assertIn("AI 噪声", fields["全部内容"])

    def test_video_transcript_uses_full_content_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            video_path = media_dir / "video.mp4"
            transcript_path = media_dir / "transcript.txt"
            video_path.write_bytes(b"video")
            transcript_path.write_text(
                "[音乐]\n嗯嗯 然后 这是视频语音转写内容\n这是视频语音转写内容\n<|nospeech|>",
                encoding="utf-8",
            )
            payload = {
                "status": "done",
                "media_dir": str(media_dir),
                "video_path": str(video_path),
                "transcript_path": str(transcript_path),
                "caption": "这是平台文案",
                "media_type": "video",
                "analysis": {
                    "title": "视频内容方法论",
                    "summary": "视频说明了一个方法。",
                    "platform": "抖音",
                    "media_type": "video",
                    "tags": ["模型标签"],
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("http://example.com/video", payload, allow_body_fallback=False)

        self.assertEqual(fields["内容类型"], "短视频")
        self.assertEqual(fields["全部文案"], "这是平台文案")
        self.assertNotIn("模型标签", fields["全部文案"])
        self.assertIn("视频语音转写（已清洗）", fields["全部内容"])
        self.assertIn("这是视频语音转写内容", fields["全部内容"])
        self.assertNotIn("这是视频语音转写内容", fields["全部文案"])
        self.assertNotIn("[音乐]", fields["全部内容"])
        self.assertNotIn("<|nospeech|>", fields["全部内容"])
        self.assertEqual(fields["全部内容"].count("这是视频语音转写内容"), 1)
        self.assertNotIn("全部视频脚本", fields)
        self.assertEqual(fields["_attachment_fields"], {"原文件": [str(video_path)]})

    def test_fallback_analysis_is_not_treated_as_structured_for_knowledge_archive(self) -> None:
        harness = KnowledgeFieldHarness()

        self.assertFalse(
            harness._knowledge_has_structured_analysis(
                {
                    "analysis_provider": "tag-router-fallback",
                    "analysis_status": "fallback_from_downloaded_assets",
                    "summary": ["这是兜底分析"],
                }
            )
        )

    def test_completion_issue_blocks_archive_when_only_fallback_analysis_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            video_path = media_dir / "video.mp4"
            transcript_path = media_dir / "transcript.txt"
            video_path.write_bytes(b"video")
            transcript_path.write_text("正式逐字稿", encoding="utf-8")
            harness = KnowledgeFieldHarness()

            issue = harness._knowledge_completion_issue(
                {
                    "status": "done",
                    "media_dir": str(media_dir),
                    "video_path": str(video_path),
                    "transcript_path": str(transcript_path),
                    "caption": "平台文案",
                    "media_type": "video",
                    "analysis": {
                        "analysis_provider": "tag-router-fallback",
                        "analysis_status": "fallback_from_downloaded_assets",
                        "summary": ["这是兜底分析"],
                        "work_copy": "平台文案",
                        "full_content": "正式逐字稿",
                    },
                },
                require_video=True,
            )

        self.assertIn("兜底分析", issue)


if __name__ == "__main__":
    unittest.main()
