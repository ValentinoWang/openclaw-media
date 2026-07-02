from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import openclaw_app.services.content_flow_client as content_flow_client_module
from openclaw_app.router.content_os_bridge import ContentOSBridgeMixin
from openclaw_app.router.content_os_utils import ContentOSUtilsMixin
from openclaw_app.services.completion_guard import CompletionGuard
from openclaw_app.services.content_flow_client import ContentFlowClient
from openclaw_app.models.message import Message
from openclaw_app.router.media_creation import MediaCreationMixin
from openclaw_app.router.media_knowledge_fields import MediaKnowledgeFieldsMixin
from openclaw_app.router.content_os_renderers import ContentOSRenderersMixin
from openclaw_app.router.transcription_formatters import TranscriptionFormattersMixin
from openclaw_app.services.transcription_postprocess_contract import validate_transcription_final_note_contract


class KnowledgeFieldHarness(MediaCreationMixin, MediaKnowledgeFieldsMixin):
    def _extract_first_url(self, text: str) -> str:
        match = re.search(r"https?://\S+", text or "")
        return match.group(0) if match else ""


class CreationPersistenceHarness(ContentOSBridgeMixin, ContentOSUtilsMixin, ContentOSRenderersMixin):
    def _maybe_advance_content_os_status(self, **kwargs: object) -> str:
        return ""


class TranscriptionFormatterHarness(TranscriptionFormattersMixin):
    pass


class ContentFlowClientCompletionTest(unittest.TestCase):
    def test_parse_json_payload_accepts_fenced_model_reply(self) -> None:
        payload = ContentFlowClient._parse_json_payload(
            '整理结果如下：\n```json\n{"title":"体育训练软件定位讨论","summary":"内容整理"}\n```\n后续说明 {非 JSON}'
        )

        self.assertEqual(payload["title"], "体育训练软件定位讨论")

    def test_profile_provider_json_rejects_openclaw_agent_runtime(self) -> None:
        client = ContentFlowClient("")
        runtime = Mock(
            api_type="openclaw_agent",
        )

        with patch.object(content_flow_client_module, "profile_config", return_value={}), patch.object(
            content_flow_client_module,
            "profile_provider_runtime",
            return_value=runtime,
        ):
            result = client._call_profile_provider_json("content_cleaner", "prompt", "{}", "再创作任务卡 LLM 生成")

        self.assertEqual(result["status"], "pending_manual")
        self.assertIn("direct Responses provider", result["reason"])

    def test_transcription_revision_missing_required_fields_remains_invalid(self) -> None:
        revised_note = {
            "title": "AI科普账号定位讨论",
            "summary": "修订后的整理",
            "speaker_notes": [],
            "labeled_transcript": [],
        }

        errors = validate_transcription_final_note_contract(revised_note)

        self.assertIn("missing required field: theme_sections", errors)
        self.assertIn("missing required field: decisions", errors)
        self.assertIn("missing required field: action_items", errors)
        self.assertIn("missing required field: pending_questions", errors)
        self.assertIn("empty required field: speaker_notes", errors)
        self.assertIn("empty required field: labeled_transcript", errors)

    def test_transcription_formatter_accepts_chunked_key_flow_labeled_transcript(self) -> None:
        harness = TranscriptionFormatterHarness()

        formatted = harness._format_labeled_transcript(
            [
                {
                    "source": "audio-01 访谈录音",
                    "key_flow": ["说话人 A 提出账号定位问题。", "speaker_b 回应内容需要结合跑步素材。"],
                    "full_transcript": "完整逐字稿见来源路径。",
                }
            ]
        )

        self.assertIn("audio-01 访谈录音：", formatted)
        self.assertIn("- 说话人 A 提出账号定位问题。", formatted)
        self.assertIn("- speaker_b 回应内容需要结合跑步素材。", formatted)
        self.assertIn("- 完整逐字稿见来源路径。", formatted)

    def test_transcription_final_note_contract_accepts_supported_labeled_transcript_shapes(self) -> None:
        base_note = {
            "title": "AI科普账号定位讨论",
            "summary": "整理内容",
            "theme_sections": [],
            "decisions": [],
            "action_items": [],
            "pending_questions": [],
            "speaker_notes": [{"speaker": "说话人 A", "note": "主讲账号定位"}],
            "labeled_transcript": [{"speaker": "说话人 A", "text": "讨论 AI 账号定位。"}],
            "sensitive_summary": "",
            "archive_macro_summary": "这次转写聚焦 AI 科普账号定位。",
            "archive_summary_bullets": ["讨论了 AI 工具体验。", "账号定位仍需继续验证。"],
        }

        self.assertEqual(validate_transcription_final_note_contract(base_note), [])

        chunked_note = {
            **base_note,
            "labeled_transcript": [
                {
                    "source": "audio-01 访谈录音",
                    "key_flow": ["说话人 A 提出账号定位问题。"],
                    "full_transcript": "完整逐字稿见来源路径。",
                }
            ],
        }

        self.assertEqual(validate_transcription_final_note_contract(chunked_note), [])

        role_thread_note = {
            **base_note,
            "labeled_transcript": [
                {
                    "source": "audio-01-chunk-01",
                    "role": "偏技术开发者一方",
                    "key_thread": "表示可以开发软件，并把讨论引向平台玩法和推广路径。",
                }
            ],
        }

        self.assertEqual(validate_transcription_final_note_contract(role_thread_note), [])

    def test_transcription_final_note_contract_rejects_missing_or_unknown_labeled_transcript_shape(self) -> None:
        invalid_note = {
            "title": "AI科普账号定位讨论",
            "summary": "整理内容",
            "theme_sections": [],
            "decisions": [],
            "action_items": [],
            "pending_questions": [],
            "speaker_notes": [{"speaker": "说话人 A", "note": "主讲账号定位"}],
            "labeled_transcript": [{"source": "audio-01", "key_flow": []}],
            "sensitive_summary": "",
            "archive_macro_summary": "这次转写聚焦 AI 科普账号定位。",
            "archive_summary_bullets": ["讨论了 AI 工具体验。"],
        }

        errors = validate_transcription_final_note_contract(invalid_note)

        self.assertIn(
            "labeled_transcript must contain at least one speaker/text, source/key_flow/full_transcript, or role/key_thread object",
            errors,
        )

    def test_parse_json_payload_prefers_structured_object_among_multiple_objects(self) -> None:
        payload = ContentFlowClient._parse_json_payload(
            '{"debug": "ignored"}\n正文：{"title":"体育训练软件定位讨论","pending_questions":[]}'
        )

        self.assertEqual(payload["title"], "体育训练软件定位讨论")

    def test_parse_json_payload_prefers_todo_intake_object(self) -> None:
        payload = ContentFlowClient._parse_json_payload(
            '{"debug": "ignored"}\n正文：{"mode":"structured_checklist","checklist_tree":[{"text":"购买","children":[{"text":"购买杠铃杆","children":[]}]}],"confidence":0.95}'
        )

        self.assertEqual(payload["mode"], "structured_checklist")
        self.assertEqual(payload["checklist_tree"][0]["text"], "购买")

    def test_activity_clean_preserves_wrapped_douyin_and_submission_form_links(self) -> None:
        client = ContentFlowClient("")
        raw_text = (
            "爆款范式参考：https://\n"
            "www.douyin.com/note/\n"
            "7644475419148913000\n"
            "填表将有机会获得官方流量扶持：抖音「请回答2026高考」返稿报名表：\n"
            "https://bytedance.larkoffice.com/\n"
            "sheets/\n"
            "Ho28s2373h4akNtWWz8cnxqZnhb"
        )
        payload = client._normalize_activity_clean_result(
            {
                "status": "done",
                "title": "毕业季有问必答话题活动",
                "source_links": [],
            },
            raw_text=raw_text,
        )

        self.assertIn(
            {"label": "爆款范式参考", "url": "https://www.douyin.com/note/7644475419148913000"},
            payload["source_links"],
        )
        self.assertIn(
            {"label": "返稿报名表", "url": "https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb"},
            payload["source_links"],
        )

    def test_activity_clean_preserves_generic_wrapped_activity_links(self) -> None:
        client = ContentFlowClient("")
        raw_text = (
            "平台活动入口：https://\n"
            "events.example.com/campaigns/\n"
            "summer-brief?from=feishu\n"
            "报名表：https://\n"
            "forms.example.com/apply/\n"
            "creator-2026"
        )
        payload = client._normalize_activity_clean_result(
            {
                "status": "done",
                "title": "夏季内容活动",
                "source_links": [],
            },
            raw_text=raw_text,
        )

        self.assertIn(
            {"label": "活动链接", "url": "https://events.example.com/campaigns/summer-brief?from=feishu"},
            payload["source_links"],
        )
        self.assertIn(
            {"label": "返稿报名表", "url": "https://forms.example.com/apply/creator-2026"},
            payload["source_links"],
        )

    def test_activity_clean_does_not_reconstruct_links_after_llm_failure(self) -> None:
        client = ContentFlowClient("")
        client._call_profile_provider_json = Mock(
            return_value={"status": "pending_manual", "reason": "LLM_TIMEOUT"}
        )

        payload = client.clean_activity_brief("报名表：https://\nforms.example.com/apply/creator-2026")

        self.assertEqual(payload, {"status": "pending_manual", "reason": "LLM_TIMEOUT"})

    def test_activity_clean_prompt_treats_publish_time_as_boost_date_evidence(self) -> None:
        client = ContentFlowClient("")
        calls = []

        def fake_clean(profile_name, prompt, user_content, stage):
            calls.append({"profile_name": profile_name, "prompt": prompt, "user_content": user_content, "stage": stage})
            return {
                "status": "done",
                "title": "毕业旅行有问必答",
                "platform": "抖音",
                "brief_summary": "活动摘要",
                "activity_time": "即日起-2026-06-30",
                "activity_time_start": "2026-06-18",
                "activity_time_end": "2026-06-30",
                "boost_date": "2026-06-18",
                "main_topic": "#毕业旅行有问必答",
                "activity_level": "平台",
                "reward": "",
                "participation_method": "发布图文或短视频",
                "participation_form": "图文或短视频",
                "filling_points": "填写返稿报名表",
                "submission_requirements": "发布时间：即日起；带话题发布并填表。",
                "subtopic_directions": [],
                "source_links": [],
                "activity_status": "进行中",
                "parse_status": "已解析",
                "missing_info": [],
            }

        client._call_profile_provider_json = fake_clean

        payload = client.clean_activity_brief("发布时间：即日起-2026年6月30日，填表后有机会获得官方流量扶持")

        self.assertEqual(calls[0]["profile_name"], "activity_cleaning")
        self.assertEqual(payload["boost_date"], "2026-06-18")
        self.assertIn("投稿时间", calls[0]["prompt"])
        self.assertIn("发布时间", calls[0]["prompt"])
        self.assertIn("抢占首波流量建议提前发布", calls[0]["prompt"])

    def test_activity_clean_prompt_extracts_creation_ready_title(self) -> None:
        client = ContentFlowClient("")
        calls = []

        def fake_clean(profile_name, prompt, user_content, stage):
            calls.append({"profile_name": profile_name, "prompt": prompt, "user_content": user_content, "stage": stage})
            return {
                "status": "done",
                "title": "毕业旅行前最该问清楚的事",
                "platform": "抖音",
                "brief_summary": "活动摘要",
                "activity_time": "",
                "activity_time_start": "",
                "activity_time_end": "",
                "boost_date": "",
                "main_topic": "#毕业旅行有问必答",
                "activity_level": "平台",
                "reward": "",
                "participation_method": "带话题发布毕业旅行问答内容",
                "participation_form": "图文或短视频",
                "filling_points": "",
                "submission_requirements": "",
                "subtopic_directions": [],
                "source_links": [],
                "activity_status": "进行中",
                "parse_status": "已解析",
                "missing_info": [],
            }

        client._call_profile_provider_json = fake_clean

        payload = client.clean_activity_brief("抖音请回答2026高考｜毕业旅行有问必答")

        self.assertEqual(calls[0]["profile_name"], "activity_cleaning")
        self.assertEqual(payload["title"], "毕业旅行前最该问清楚的事")
        self.assertIn("最适合直接创作的选题标题", calls[0]["prompt"])
        self.assertIn("抖音请回答2026高考｜毕业旅行有问必答", calls[0]["prompt"])
        self.assertIn("不要输出“毕业旅行有问必答”", calls[0]["prompt"])
        self.assertIn("subtopic_directions 作为子记录标题来源", calls[0]["prompt"])

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

    def test_structured_analysis_missing_returns_pending_manual(self) -> None:
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

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["reason"], "LLM_SEMANTIC_PERSISTENCE_REQUIRED:content_flow_structured_analysis_required")
        self.assertTrue(payload["analysis_completion_checked"])

    def test_completion_guard_does_not_wait_twice_after_analysis_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_sleep = content_flow_client_module.time.sleep
            content_flow_client_module.time.sleep = Mock(side_effect=AssertionError("unexpected second analysis wait"))
            try:
                client = ContentFlowClient("", workspace_root=tmp)
                payload = client.complete_analysis_payload(
                    "http://xhslink.com/o/example",
                    {
                        "status": "pending_manual",
                        "media_dir": tmp,
                        "analysis_completion_checked": True,
                        "caption": "平台文案",
                    },
                    wait=True,
                )
            finally:
                content_flow_client_module.time.sleep = original_sleep

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["reason"], "LLM_SEMANTIC_PERSISTENCE_REQUIRED:content_flow_structured_analysis_required")
        self.assertTrue(payload["analysis_completion_checked"])

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
                self.assertEqual(payload["status"], "pending_manual")
                self.assertEqual(payload["reason"], "LLM_SEMANTIC_PERSISTENCE_REQUIRED:content_flow_structured_analysis_required")

    def test_wechat_article_analyze_extracts_text_images_and_structured_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_response = Mock()
            article_response.text = """
            <html><head>
              <meta property="og:title" content="公众号 AI 方法论">
              <meta name="keywords" content="AI,自媒体">
              <script>var nickname = "AI指南"; var publish_time = "2026-05-27";</script>
            </head><body>
              <div id="js_content">
                <h2>方法框架</h2>
                <p>第一段：用 AI 做选题，先拆人群和痛点。</p>
                <ul><li>保留原文结构，不做再创作。</li></ul>
                <p>第二段：再把角度转成标题和内容结构。</p>
                <img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/example/0?wx_fmt=jpeg">
              </div>
            </body></html>
            """
            article_response.raise_for_status.return_value = None

            image_response = Mock()
            image_response.content = b"image"
            image_response.headers = {"Content-Type": "image/jpeg"}
            image_response.raise_for_status.return_value = None

            client = ContentFlowClient("", workspace_root=tmp)
            client.session.get = Mock(side_effect=[article_response, image_response])

            payload = client.analyze("【自媒体知识】\n链接：https://mp.weixin.qq.com/s/example")
            self.assertTrue(Path(payload["structure_path"]).is_file())

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["reason"], "LLM_SEMANTIC_PERSISTENCE_REQUIRED:wechat_article_semantic_analysis_required")
        self.assertEqual(payload["media_type"], "article")
        self.assertEqual(payload["analysis"]["platform"], "公众号")
        self.assertEqual(payload["analysis"]["analysis_provider"], "wechat-article-extractor")
        self.assertIn("第一段：用 AI 做选题", payload["caption"])
        self.assertIn("## 方法框架", payload["analysis"]["full_content"])
        self.assertIn("- 保留原文结构", payload["analysis"]["full_content"])
        self.assertEqual(len(payload["image_paths"]), 1)

    def test_run_job_recovers_video_path_from_media_dir_when_status_payload_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            video_path = media_dir / "video.mp4"
            video_path.write_bytes(b"video")

            post_response = Mock()
            post_response.json.return_value = {"job_id": "job-1"}
            post_response.raise_for_status.return_value = None

            status_response = Mock()
            status_response.json.return_value = {
                "status": "done",
                "result": {
                    "media_dir": str(media_dir),
                    "media_type": "video",
                    "caption": "平台文案",
                },
            }
            status_response.raise_for_status.return_value = None

            client = ContentFlowClient("http://content-flow.test", workspace_root=tmp)
            client.poll_attempts = 1
            client.session.post = Mock(return_value=post_response)
            client.session.get = Mock(return_value=status_response)

            payload = client._run_job("/api/download", "https://www.douyin.com/video/123")

        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["video_path"], str(video_path))
        self.assertEqual(payload["media_dir"], str(media_dir))

    def test_analyze_job_poll_budget_uses_structured_analysis_wait_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"CONTENT_FLOW_ANALYSIS_WAIT_SECONDS": "3"},
        ), patch.object(content_flow_client_module.time, "sleep") as sleep_mock:
            post_response = Mock()
            post_response.json.return_value = {"job_id": "job-structured"}
            post_response.raise_for_status.return_value = None

            status_response = Mock()
            status_response.json.return_value = {"status": "running"}
            status_response.raise_for_status.return_value = None

            client = ContentFlowClient("http://content-flow.test", poll_interval_seconds=1, poll_attempts=1, workspace_root=tmp)
            client.session.post = Mock(return_value=post_response)
            client.session.get = Mock(return_value=status_response)

            payload = client._run_job("/api/analyze", "http://xhslink.com/o/example")

        self.assertEqual(client.session.get.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 3)
        self.assertEqual(payload["status"], "pending_manual")
        self.assertIn("轮询超时 job_id=job-structured", payload["reason"])

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
                    "primary_category": "AI/工具",
                    "secondary_category": "AI工具应用",
                    "target_audience": "AI 小白",
                    "pain_point": "标题同质化",
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("http://xhslink.com/o/example", payload)

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
                    "primary_category": "AI/工具",
                    "secondary_category": "AI工具应用",
                    "work_copy": "模型清洗后的正文",
                },
        }
        harness = KnowledgeFieldHarness()
        fields = harness._knowledge_extra_fields("http://xhslink.com/o/example", payload)

        self.assertEqual(fields["全部文案"], "原始平台文案")
        self.assertIn("AI 噪声", fields["全部内容"])

    def test_analysis_full_content_writes_to_knowledge_full_content_without_raw_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "note.jpg"
            image_path.write_bytes(b"image")
            payload = {
                "status": "done",
                "caption": "平台正文只进入全部文案",
                "image_paths": [str(image_path)],
                "media_type": "图文",
                "analysis": {
                    "title": "Codex 把备课素材整理成教案",
                    "summary": "两张素材图生成可编辑教案。",
                    "platform": "小红书",
                    "media_type": "图文",
                    "primary_category": "AI/工具",
                    "secondary_category": ["AI工具应用"],
                    "target_audience": "教师",
                    "pain_point": "备课材料整理耗时",
                    "work_copy": "模型正文不应覆盖平台正文",
                    "full_content": "第 1 页：数学老师的省时备课法。\n第 2 页：教材目录 + 手写思路图。",
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("http://xhslink.com/o/example", payload)

        self.assertEqual(fields["全部文案"], "平台正文只进入全部文案")
        self.assertEqual(fields["全部内容"], "第 1 页：数学老师的省时备课法。\n第 2 页：教材目录 + 手写思路图。")
        self.assertEqual(fields["_attachment_fields"], {"原文件": [str(image_path)]})

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
                    "primary_category": "AI/工具",
                    "secondary_category": "AI工具应用",
                    "tags": ["模型标签"],
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("http://example.com/video", payload)

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
        self.assertNotIn("local_video_path=", fields.get("待验证问题", ""))

    def test_wechat_article_knowledge_fields_use_article_body_and_image_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "article.jpg"
            image_path.write_bytes(b"image")
            payload = {
                "status": "done",
                "caption": "第一段：用 AI 做选题，先拆人群和痛点。\n第二段：再把角度转成标题和内容结构。",
                "image_paths": [str(image_path)],
                "media_type": "article",
                "analysis": {
                    "title": "公众号 AI 方法论",
                    "summary": ["公众号图文正文已提取入库。"],
                    "platform": "公众号",
                    "media_type": "article",
                    "primary_category": "AI/工具",
                    "secondary_category": "AI工具应用",
                    "full_content": "## 方法框架\n\n第一段：用 AI 做选题，先拆人群和痛点。\n\n- 保留原文结构，不做再创作。\n\n第二段：再把角度转成标题和内容结构。",
                    "tags": ["AI", "自媒体"],
                    "analysis_provider": "wechat-article-extractor",
                    "analysis_status": "extracted_article",
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("https://mp.weixin.qq.com/s/example", payload)

        self.assertEqual(fields["来源平台"], "公众号")
        self.assertEqual(fields["内容类型"], "图文")
        self.assertEqual(fields["全部文案"], payload["caption"])
        self.assertIn("## 方法框架", fields["全部内容"])
        self.assertIn("- 保留原文结构", fields["全部内容"])
        self.assertIn("第二段：再把角度转成标题", fields["全部内容"])
        self.assertEqual(fields["_attachment_fields"], {"原文件": [str(image_path)]})

    def test_douyin_image_post_does_not_require_video(self) -> None:
        body = "9.28 复制打开抖音，看看【迷雾院长的图文作品】男人必懂的10个恋爱心理学。 https://v.douyin.com/example/"
        payload = {
            "status": "done",
            "caption": "男人必懂的10个恋爱心理学。",
            "media_type": "unknown",
            "analysis": {
                "title": "恋爱心理学包装下的情绪拿捏风险",
                "summary": ["用巴纳姆效应解释恋爱中“被懂”的错觉。"],
                "primary_category": "学习/认知",
                "secondary_category": ["心理认知", "关系风险", "案例拆解"],
                "platform": "抖音",
                "media_type": "unknown",
                "full_content": "男人必懂的10个恋爱心理学。",
                "analysis_provider": "openclaw",
                "analysis_status": "complete",
            },
        }
        harness = KnowledgeFieldHarness()

        self.assertFalse(harness._selfmedia_knowledge_requires_video(body, payload))
        self.assertEqual(harness._knowledge_completion_issue(payload, require_video=False), "")
        self.assertEqual(harness._knowledge_content_type(body, payload, "抖音"), "图文")
        fields = harness._knowledge_extra_fields(body, payload)
        self.assertEqual(fields["内容类型"], "图文")
        self.assertEqual(fields["二级分类"], ["心理认知", "关系风险", "案例拆解"])

    def test_knowledge_secondary_categories_use_standard_values(self) -> None:
        harness = KnowledgeFieldHarness()
        fields = harness._knowledge_category_fields(
            {
                "primary_category": "运营/管理",
                "secondary_category": ["平台机制", "内容增长", "创作者变现"],
            },
            "小红书新规让普通创作者获得流量和变现窗口",
        )

        self.assertEqual(fields["二级分类"], ["算法拆解/增长", "自媒体运营"])

    def test_incomplete_analysis_is_not_treated_as_structured_for_knowledge_archive(self) -> None:
        harness = KnowledgeFieldHarness()

        self.assertFalse(
            harness._knowledge_has_structured_analysis(
                {
                    "analysis_status": "needs_model_rerun",
                    "incomplete_reason": "primary_analysis_unavailable",
                    "summary": [],
                }
            )
        )

    def test_completion_issue_blocks_archive_when_analysis_is_incomplete(self) -> None:
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
                        "analysis_status": "needs_model_rerun",
                        "incomplete_reason": "primary_analysis_unavailable",
                        "summary": [],
                    },
                },
                require_video=True,
            )

        self.assertIn("结构化分析需要重新运行模型", issue)

    def test_selfmedia_knowledge_writes_obsidian_markdown_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            try:
                harness = KnowledgeFieldHarness()
                message = Message(
                    entry_tag="自媒体知识",
                    raw_text="【自媒体知识】 https://v.douyin.com/example/",
                    body="https://v.douyin.com/example/",
                    source="feishu",
                    created_at=datetime(2026, 6, 11, 0, 30),
                )
                result = {
                    "status": "done",
                    "media_dir": "/tmp/douyin-7649061784112362610",
                    "analysis": {
                        "title": "拆解低门槛口播智能体的赚钱逻辑",
                        "video_id": "7649061784112362610",
                        "hooks": "千万销售额制造好奇。",
                    },
                }
                local_path = harness._write_selfmedia_knowledge_markdown(
                    message=message,
                    title="拆解低门槛口播智能体的赚钱逻辑",
                    result=result,
                    extra_fields={
                        "原链接": "https://v.douyin.com/example/",
                        "来源平台": "抖音",
                        "内容类型": "短视频",
                        "一级分类": "AI/工具",
                        "二级分类": ["AI视频/自动化"],
                        "摘要": "把成熟能力打包成一键应用。",
                        "全部文案": "蒸馏 #codex",
                        "全部内容": "今天拆解了一个爆款口播视频生成智能体。",
                        "应用建议": "复刻成低门槛应用。",
                    },
                    record_text="今天拆解了一个爆款口播视频生成智能体。",
                )
                path = Path(local_path)
                self.assertTrue(path.exists())
                self.assertIn("05_素材与爆款库/自媒体知识", local_path)
                text = path.read_text(encoding="utf-8")
                self.assertIn("doc_type: selfmedia_knowledge", text)
                self.assertIn("拆解低门槛口播智能体的赚钱逻辑", text)
                self.assertIn("今天拆解了一个爆款口播视频生成智能体。", text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root

    def test_creation_without_project_id_skips_cloud_markdown_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            try:
                harness = CreationPersistenceHarness()
                message = Message(
                    entry_tag="创作",
                    raw_text="【创作】平台=抖音 类型=视频 主体=AI口播生产管道",
                    body="平台=抖音 类型=视频 主体=AI口播生产管道",
                    source="feishu",
                    created_at=datetime(2026, 6, 11, 1, 0),
                )
                result = harness._write_standalone_creation_output(
                    message,
                    {
                        "ok": True,
                        "creation_record_id": "recCreation1",
                        "doc_link": "https://example.feishu.cn/doc",
                        "draft": {"title": "把AI口播从特效玩具变成生产管道"},
                        "reply": "这是创作稿正文",
                    },
                    "这是创作稿正文",
                )
                self.assertEqual(result, {})
                self.assertFalse((Path(tmp) / "03_脚本生产").exists())
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root

    def test_creation_with_existing_material_intent_skips_cloud_project_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
            try:
                harness = CreationPersistenceHarness()
                message = Message(
                    entry_tag="创作>抖音",
                    raw_text=(
                        "【创作>抖音】\n"
                        "类型：视频\n"
                        "赛道：教育、校园\n"
                        "主体：第一视角体验清华毕业典礼\n"
                        "素材/参考：抖音口令/链接...\n"
                        "希望产出：剪辑说明，已有素材"
                    ),
                    body="第一视角体验清华毕业典礼",
                    source="feishu",
                    created_at=datetime(2026, 6, 27, 12, 0),
                )
                result = harness._maybe_create_content_os_project_from_creation(
                    message,
                    {
                        "ok": True,
                        "creation_record_id": "run_001",
                        "doc_link": "https://example.feishu.cn/wiki/creation",
                        "request": {"platform": "抖音", "content_type": "视频", "track": "教育、校园", "topic": "第一视角体验清华毕业典礼"},
                        "draft": {"title": "第一视角体验清华毕业典礼", "production_checklist": ["毕业服", "典礼现场", "走位镜头"]},
                        "reply": "云端创作稿",
                    },
                    "云端创作稿",
                )
                self.assertEqual(result, {})
                self.assertFalse((Path(tmp) / "08_内容项目").exists())
                self.assertFalse((Path(tmp) / "03_脚本生产").exists())
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_creation_with_editing_material_intent_creates_content_os_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            try:
                harness = CreationPersistenceHarness()
                message = Message(
                    entry_tag="创作>抖音",
                    raw_text=(
                        "【创作>抖音】\n"
                        "类型：视频\n"
                        "赛道：教育、校园\n"
                        "主体：第一视角体验清华毕业典礼\n"
                        "素材/参考：学业副本结算完毕 - 抖音复制口令\n"
                        "希望产出：剪辑说明，已有素材"
                    ),
                    body="第一视角体验清华毕业典礼",
                    source="feishu",
                    created_at=datetime(2026, 6, 27, 12, 0),
                )
                result = harness._maybe_create_content_os_project_from_creation(
                    message,
                    {
                        "ok": True,
                        "creation_record_id": "run_001",
                        "doc_link": "https://example.feishu.cn/wiki/creation",
                        "request": {"platform": "抖音", "content_type": "视频", "track": "教育、校园", "topic": "第一视角体验清华毕业典礼"},
                        "draft": {"title": "第一视角体验清华毕业典礼", "production_checklist": ["毕业服", "典礼现场", "走位镜头"]},
                        "reply": "云端创作稿",
                    },
                    "云端创作稿",
                )

                project_path = Path(result["project_path"])
                self.assertEqual(result["local_material_binding"], "unbound")
                self.assertTrue((project_path / "00_项目总览.md").exists())
                self.assertTrue((project_path / "04_script.md").exists())
                self.assertTrue((project_path / "09_publish_pack.md").exists())
                self.assertIn("Mac 素材未绑定", result["reply"])
                script_text = (project_path / "04_script.md").read_text(encoding="utf-8")
                self.assertIn("云端创作稿", script_text)
                self.assertIn("run_001", script_text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_creation_with_local_material_path_creates_content_os_mac_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            try:
                harness = CreationPersistenceHarness()
                local_path = "/Users/vsiyo/Movies/OpenClaw/20260627_清华毕业典礼"
                message = Message(
                    entry_tag="创作>抖音",
                    raw_text=(
                        "【创作>抖音】 类型：视频 赛道：教育 主体：第一视角体验清华毕业典礼 "
                        f"希望产出：剪辑说明，已有素材 本地素材路径：{local_path}"
                    ),
                    body="第一视角体验清华毕业典礼",
                    source="feishu",
                    created_at=datetime(2026, 6, 27, 12, 30),
                )
                result = harness._maybe_create_content_os_project_from_creation(
                    message,
                    {
                        "ok": True,
                        "creation_record_id": "run_002",
                        "request": {"platform": "抖音", "content_type": "视频", "track": "教育", "topic": "第一视角体验清华毕业典礼"},
                        "draft": {"title": "第一视角体验清华毕业典礼"},
                        "reply": "云端创作稿",
                    },
                    "云端创作稿",
                )

                self.assertEqual(result["local_material_binding"], "bound")
                self.assertIn("task_path", result)
                task_text = Path(result["task_path"]).read_text(encoding="utf-8")
                self.assertIn("task_type: local_material_match", task_text)
                self.assertIn(f"local_project_path: {json.dumps(local_path, ensure_ascii=False)}", task_text)
                self.assertIn("Mac 任务", result["reply"])
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_inspiration_project_creation_without_local_path_writes_project_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            try:
                harness = CreationPersistenceHarness()
                message = Message(
                    entry_tag="创作-灵感",
                    raw_text="【创作-灵感】请立项，生成项目包、brief 和初稿脚本。目标：毕业季田径比赛做成内容。",
                    body="请立项，生成项目包、brief 和初稿脚本。目标：毕业季田径比赛做成内容。",
                    source="feishu",
                    created_at=datetime(2026, 6, 26, 12, 0),
                )
                result = harness._maybe_create_content_os_project_from_inspiration(
                    message=message,
                    result={
                        "title": "毕业季田径比赛",
                        "theme": "把毕业季和田径比赛结合",
                        "platform": "抖音",
                        "content_type": "视频",
                        "material_requirements": ["比赛过程镜头", "人物反应镜头"],
                    },
                    record_text="创作灵感正文",
                    doc_fs={"doc": "https://example.feishu.cn/wiki/doc"},
                    unified_index={"record_id": "rec_inspiration_1"},
                )

                project_path = Path(result["project_path"])
                self.assertEqual(result["local_material_binding"], "unbound")
                self.assertNotIn("task_path", result)
                self.assertTrue((project_path / "00_项目总览.md").exists())
                self.assertTrue((project_path / "01_idea_card.md").exists())
                self.assertTrue((project_path / "02_project_brief.md").exists())
                self.assertTrue((project_path / "04_script.md").exists())
                self.assertFalse((Path(tmp) / "98_Agent任务队列" / "01_cloud_to_mac_ready").exists())
                index_text = (project_path / "00_项目总览.md").read_text(encoding="utf-8")
                brief_text = (project_path / "02_project_brief.md").read_text(encoding="utf-8")
                self.assertIn("local_material_binding: unbound", index_text)
                self.assertIn("next_owner: human", index_text)
                self.assertIn("等人在 Mac 上把素材批次和项目包绑定", index_text)
                self.assertIn("比赛过程镜头", brief_text)
                self.assertIn("不声称 Mac 本地已有这些素材", brief_text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_inspiration_project_creation_with_local_path_creates_ready_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            try:
                harness = CreationPersistenceHarness()
                local_path = "/Users/vsiyo/Desktop/照片筛选/01_Project_Workspace/20260514_400米比赛"
                message = Message(
                    entry_tag="创作-灵感",
                    raw_text=f"【创作-灵感】目标=生成项目包和初稿脚本，再交给 Mac 做素材匹配。本地素材路径：{local_path}",
                    body="生成项目包和初稿脚本，再交给 Mac 做素材匹配。",
                    source="feishu",
                    created_at=datetime(2026, 6, 26, 12, 30),
                )
                result = harness._maybe_create_content_os_project_from_inspiration(
                    message=message,
                    result={"title": "400米比赛第一视角", "theme": "400米第一视角挑战"},
                    record_text="创作灵感正文",
                    doc_fs={},
                    unified_index={},
                )

                self.assertEqual(result["local_material_binding"], "bound")
                self.assertIn("task_path", result)
                task_text = Path(result["task_path"]).read_text(encoding="utf-8")
                self.assertIn("status: ready", task_text)
                self.assertIn(f"local_project_path: {json.dumps(local_path, ensure_ascii=False)}", task_text)
                self.assertIn("script_path: 08_内容项目/", task_text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_inspiration_project_creation_with_batch_note_creates_ready_task_without_local_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            try:
                harness = CreationPersistenceHarness()
                batch_note = "00_Inbox_Mac_Intake/20260626_毕业季田径_待整理/00_批次说明.md"
                message = Message(
                    entry_tag="创作-灵感",
                    raw_text=f"【创作-灵感】目标=生成项目包和初稿脚本，并派 Mac 素材匹配。批次说明路径：{batch_note}",
                    body="生成项目包和初稿脚本，并派 Mac 素材匹配。",
                    source="feishu",
                    created_at=datetime(2026, 6, 26, 13, 0),
                )
                result = harness._maybe_create_content_os_project_from_inspiration(
                    message=message,
                    result={"title": "毕业季田径素材", "theme": "毕业季田径素材创作"},
                    record_text="创作灵感正文",
                    doc_fs={},
                    unified_index={},
                )

                self.assertEqual(result["local_material_binding"], "bound")
                task_text = Path(result["task_path"]).read_text(encoding="utf-8")
                self.assertIn(f"batch_note_path: {json.dumps(batch_note, ensure_ascii=False)}", task_text)
                self.assertIn('local_project_path: ""', task_text)
                project_text = (Path(result["project_path"]) / "00_项目总览.md").read_text(encoding="utf-8")
                self.assertIn("local_project_path: \"\"", project_text)
                self.assertIn(f"batch_note_path: {json.dumps(batch_note, ensure_ascii=False)}", project_text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md


if __name__ == "__main__":
    unittest.main()
