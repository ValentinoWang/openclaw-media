from __future__ import annotations

import json
import os
import unittest
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message
from openclaw_app.router.activity_daily import ActivityDailyMixin
from openclaw_app.router.content_os_utils import ContentOSUtilsMixin
from openclaw_app.router.recreation import RecreationMixin
from openclaw_app.router.social_archive import SocialArchiveMixin
from openclaw_app.router.tag_capabilities import TAG_LABELS


TZ = ZoneInfo("Asia/Shanghai")


class FakeArchiveService:
    def __init__(self):
        self.calls: list[dict] = []

    def save_archive(self, message, title, sections, extra_frontmatter=None):
        self.calls.append(
            {
                "message": message,
                "title": title,
                "sections": sections,
                "extra_frontmatter": extra_frontmatter or {},
            }
        )
        return SimpleNamespace(frontmatter={"id": "archive-id"}, local_path="/tmp/archive.md")


class ForbiddenReminderService:
    def add(self, **_kwargs):
        raise AssertionError("activity AI-clean failure must not write generated record")


class FakeContentFlowClient:
    def __init__(self, *, profile_result: dict | None = None, activity_result: dict | None = None):
        self.profile_result = profile_result or {}
        self.activity_result = activity_result or {}
        self.profile_calls: list[dict] = []

    def clean_activity_brief(self, *_args, **_kwargs):
        return self.activity_result

    def _call_profile_provider_json(self, profile_name: str, prompt: str, user_content: str, stage: str) -> dict:
        self.profile_calls.append(
            {
                "profile_name": profile_name,
                "prompt": prompt,
                "user_content": user_content,
                "stage": stage,
            }
        )
        return self.profile_result


class ActivityHarness(ActivityDailyMixin):
    def __init__(self):
        self.content_flow_client = FakeContentFlowClient(activity_result={"status": "pending_manual", "reason": "LLM down"})
        self.archive_service = FakeArchiveService()
        self.reminder_service = ForbiddenReminderService()


class SocialHarness(SocialArchiveMixin):
    def __init__(self, result: dict):
        self.content_flow_client = FakeContentFlowClient(profile_result=result)

    def _conversation_context_prompt(self, _message):
        return ""


class RecreationHarness(RecreationMixin):
    def __init__(self, result: dict):
        self.content_flow_client = FakeContentFlowClient(profile_result=result)

    def _conversation_context_prompt(self, _message):
        return ""


class RecreationHandleHarness(RecreationMixin):
    def __init__(self, result: dict):
        self.content_flow_client = FakeContentFlowClient(profile_result=result)
        self.archive_service = FakeArchiveService()

    def _conversation_context_prompt(self, _message):
        return ""

    def _conversation_context(self, _message):
        return {"loaded_count": 0}

    def _sync_recreation_entry_to_feishu(self, *_args, **_kwargs):
        return {"doc": "https://example.feishu.cn/doc", "entry_doc_name": "拆解-再创｜清华毕业卡点再创｜demo"}

    def _unified_now_iso(self):
        return "2026-06-27T16:29:20+08:00"

    def _sync_unified_creation_record(self, *_args, **_kwargs):
        return {"record_id": "rec-demo"}

    def _maybe_create_content_os_task_from_recreation(self, *_args, **_kwargs):
        return {}


class RecreationQueueHarness(RecreationHandleHarness, ContentOSUtilsMixin):
    pass


def partial_deconstruct_completed() -> SimpleNamespace:
    inner = {
        "mode": "partial_deconstruct",
        "partial_deconstruct": {
            "bgm_or_audio": "待剪映搜索同节奏替代",
            "rhythm_reference": "0-2s 标题钩子，2-8s 按鼓点切素材",
            "analysis_evidence_count": 2,
        },
    }
    outer = {"ok": True, "stdout": json.dumps(inner, ensure_ascii=False), "stderr": ""}
    return SimpleNamespace(returncode=0, stdout=json.dumps(outer, ensure_ascii=False), stderr="")


def full_deconstruct_completed() -> SimpleNamespace:
    inner = {
        "ok": True,
        "source_asset": {"title": "爆款毕业卡点", "doc_url": "https://example.feishu.cn/wiki/full"},
        "material_deconstruction": {"opening_hook": "开头强身份标题", "rhythm": "快切卡点"},
        "recreation_notes": {"anti_copy_notes": "只迁移结构，不复刻原片表达"},
    }
    outer = {"ok": True, "stdout": json.dumps(inner, ensure_ascii=False), "stderr": ""}
    return SimpleNamespace(returncode=0, stdout=json.dumps(outer, ensure_ascii=False), stderr="")


def make_message(tag: str, body: str) -> Message:
    return Message(
        entry_tag=tag,
        raw_text=f"【{tag}】{body}",
        body=body,
        source="feishu",
        chat_type="private",
        created_at=datetime(2026, 5, 29, 13, 30, tzinfo=TZ),
    )


class LlmRequiredRoutesTest(unittest.TestCase):
    def test_activity_ai_clean_failure_does_not_use_rule_generated_fields(self) -> None:
        harness = ActivityHarness()

        result = harness.handle_活动(make_message("活动", "小红书活动 Brief 链接：https://example.com"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "activity_ai_clean_pending_manual")
        self.assertIn("不会用规则生成", result.reply)
        self.assertEqual(harness.archive_service.calls[0]["extra_frontmatter"]["postprocess_status"], "pending_manual")

    def test_social_metadata_uses_llm_profile(self) -> None:
        harness = SocialHarness(
            {
                "person": "Jessica",
                "gender": "女",
                "relationship_category": "异性关系",
                "confidence": 0.9,
                "missing_fields": [],
                "evidence": "对象：Jessica；性别：女；关系：异性关系",
                "reason": "字段明确",
            }
        )

        result = harness._extract_social_metadata_with_llm(make_message("社交", "对象：Jessica\n性别：女\n关系：异性关系"), archive_kind="社交", forced_category="")

        self.assertTrue(result["ok"])
        self.assertEqual(result["person"], "Jessica")
        self.assertEqual(result["gender"], "女")
        self.assertEqual(result["relationship_category"], "异性关系")
        self.assertEqual(harness.content_flow_client.profile_calls[0]["profile_name"], "content_cleaner")

    def test_social_metadata_defaults_to_female_heterosexual_when_person_is_known(self) -> None:
        harness = SocialHarness(
            {
                "person": "赵紫薇",
                "gender": "女",
                "relationship_category": "异性关系",
                "confidence": 0.8,
                "missing_fields": [],
                "evidence": "对象：赵紫薇",
                "reason": "对象明确，用户未特殊说明，按默认女性和异性关系处理",
            }
        )

        result = harness._extract_social_metadata_with_llm(make_message("社交", "对象：赵紫薇 这张图说明什么"), archive_kind="社交", forced_category="")

        self.assertTrue(result["ok"])
        self.assertEqual(result["person"], "赵紫薇")
        self.assertEqual(result["gender"], "女")
        self.assertEqual(result["relationship_category"], "异性关系")

    def test_social_archive_prefers_downloaded_image_input_over_text_stub(self) -> None:
        harness = SocialHarness({})
        media_root = Path("/home/ubuntu/.openclaw/media/inbound")
        media_root.mkdir(parents=True, exist_ok=True)
        image_path = media_root / "social-route-test.jpg"
        image_path.write_bytes(b"fake-image")
        self.addCleanup(lambda: image_path.unlink(missing_ok=True))
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as text_file:
            message = make_message("社交", "对象：赵紫薇 这张图说明什么")
            message.metadata = {"downloaded_paths": [str(image_path)]}

            selected = harness._social_person_archive_input_path(message, Path(text_file.name))

        self.assertEqual(selected, image_path.resolve())

    def test_social_archive_reply_summary_uses_latest_material_content(self) -> None:
        harness = SocialHarness({})
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = Path(tmp_dir) / "archive.md"
            archive_path.write_text(
                """
## 001｜【人物照片】2026-06-13｜旧记录

> 待归入本表的提纯材料如下。后续编辑时应拆成逐行聊天记录、事实摘要和分析证据；原始音频/截图/图片不进入档案。

旧内容

| 日期/时间 | 发言人 | 内容 | 备注 |

## 002｜【人物照片】2026-06-13｜新记录

> 待归入本表的提纯材料如下。后续编辑时应拆成逐行聊天记录、事实摘要和分析证据；原始音频/截图/图片不进入档案。

图中主体可见，画面重点是穿搭和姿态；可判断项有限。

| 日期/时间 | 发言人 | 内容 | 备注 |
""".strip(),
                encoding="utf-8",
            )
            message = make_message("社交", "对象：赵紫薇 这张图说明什么")

            summary = harness._social_archive_reply_summary(
                message,
                {"archive_path": str(archive_path), "input_path": "/home/ubuntu/.openclaw/media/inbound/current.jpg"},
            )

        self.assertIn("图中主体可见", summary)
        self.assertNotIn("旧内容", summary)

    def test_recreation_task_card_body_comes_from_llm(self) -> None:
        harness = RecreationHarness(
            {
                "title": "赛事转场开头",
                "source_url": "https://example.com/video",
                "intent": "把原素材的转场机制迁移到训练视频",
                "target": "抖音 400 米训练短视频",
                "transferable_points": ["动作接转场", "字幕钩子"],
                "recreation_direction": ["用起跑动作接入训练片段"],
                "suggested_outputs": ["短视频脚本", "分镜清单"],
                "pending_items": ["账号定位", "素材路径"],
                "next_steps": ["补齐素材后生成脚本"],
                "confidence": 0.88,
                "missing_fields": [],
                "evidence": "转到 400 米训练视频",
                "reason": "目标和迁移机制明确",
            }
        )

        task_card = harness._recreation_task_card_with_llm(make_message("拆解-再创", "https://example.com/video 转到 400 米训练视频"))
        sections = dict(harness._recreation_sections_from_task_card(make_message("拆解-再创", "body"), task_card))

        self.assertTrue(task_card["ok"])
        self.assertEqual(task_card["title"], "赛事转场开头")
        self.assertIn("动作接转场", sections["可迁移点"])
        self.assertIn("短视频脚本", sections["建议产物"])
        self.assertEqual(harness.content_flow_client.profile_calls[0]["profile_name"], "content_cleaner")

    def test_lightweight_recreation_task_card_keeps_partial_deconstruct_contract(self) -> None:
        harness = RecreationHarness(
            {
                "title": "BGM卡点返校",
                "source_url": "https://example.com/video",
                "intent": "复用爆款的 BGM 卡点和情绪氛围",
                "target": "抖音返校短视频",
                "mode": "轻量反抄_BGM卡点",
                "deconstruction_depth": "partial",
                "local_batch_id": "20260627_清华毕业典礼",
                "bgm_plan": "待剪映搜索同节奏替代",
                "transferable_points": ["开头标题", "BGM卡点", "情绪氛围"],
                "recreation_direction": ["用本地返校素材按鼓点填空"],
                "suggested_outputs": ["轻量剪辑卡", "BGM/节奏参考", "素材填空建议"],
                "lightweight_edit_card": ["0-2s 最强画面加标题", "2-8s 按鼓点切换素材"],
                "pending_items": ["确认本地素材批次是否已放入 Mac Inbox"],
                "next_steps": ["调用部分拆解后进剪映卡点"],
                "confidence": 0.86,
                "missing_fields": [],
                "evidence": "模式：轻量反抄 / BGM 卡点",
                "reason": "用户明确要求不生成完整 Storyboard 和 EDL",
            }
        )

        message = make_message(
            "拆解-再创",
            "模式：轻量反抄 / BGM 卡点\n爆款视频链接：https://example.com/video\n本地素材批次ID：20260627_清华毕业典礼",
        )
        task_card = harness._recreation_task_card_with_llm(message)
        sections = dict(harness._recreation_sections_from_task_card(message, task_card))

        self.assertTrue(task_card["ok"])
        self.assertEqual(task_card["mode"], "轻量反抄_BGM卡点")
        self.assertEqual(task_card["deconstruction_depth"], "partial")
        self.assertEqual(task_card["local_batch_id"], "20260627_清华毕业典礼")
        self.assertIn("待剪映搜索", sections["BGM计划"])
        self.assertIn("0-2s 最强画面", sections["轻量剪辑卡"])
        self.assertNotIn("完整 Storyboard", sections["建议产物"])
        self.assertNotIn("完整 EDL", sections["建议产物"])
        prompt = harness.content_flow_client.profile_calls[0]["prompt"]
        self.assertIn("deconstruction_depth 输出 \"partial\"", prompt)

    def test_lightweight_recreation_runs_partial_deconstruct_evidence(self) -> None:
        harness = RecreationHarness(
            {
                "title": "BGM卡点返校",
                "source_url": "https://example.com/video",
                "intent": "复用爆款的 BGM 卡点和情绪氛围",
                "target": "抖音返校短视频",
                "mode": "轻量反抄_BGM卡点",
                "deconstruction_depth": "partial",
                "transferable_points": ["开头标题", "BGM卡点"],
                "recreation_direction": ["用本地返校素材按鼓点填空"],
                "suggested_outputs": ["轻量剪辑卡", "BGM/节奏参考"],
                "lightweight_edit_card": ["0-2s 最强画面加标题"],
                "pending_items": ["确认素材批次"],
                "next_steps": ["调用部分拆解"],
                "confidence": 0.86,
                "missing_fields": [],
                "evidence": "模式：轻量反抄 / BGM 卡点",
                "reason": "用户明确要求轻量再创作",
            }
        )
        message = make_message("拆解-再创", "模式：轻量反抄 / BGM 卡点\n爆款视频链接：https://example.com/video")
        task_card = harness._recreation_task_card_with_llm(message)

        with patch("openclaw_app.router.recreation.run_media_subprocess_with_watchdog", return_value=partial_deconstruct_completed()) as run:
            partial = harness._maybe_partial_deconstruct_for_lightweight_recreation(message, task_card)

        self.assertEqual(partial["status"], "done")
        self.assertEqual(partial["mode"], "partial_deconstruct")
        self.assertIn("deconstruct_result", partial)
        command = run.call_args.args[0]
        self.assertIn("--partial", command)
        self.assertIn("--no-write", command)
        self.assertIn("【拆解】https://example.com/video", command)

    def test_lightweight_recreation_with_batch_id_dispatches_mac_queue_task(self) -> None:
        harness = RecreationQueueHarness(
            {
                "title": "清华毕业卡点再创",
                "source_url": "https://www.douyin.com/jingxuan/search/demo",
                "intent": "参考爆款毕业季视频的开头标题、情绪氛围、BGM节奏和卡点方式。",
                "target": "转化为抖音平台的清华毕业典礼第一视角体验内容。",
                "mode": "轻量反抄_BGM卡点",
                "deconstruction_depth": "partial",
                "local_batch_id": "20260627_清华毕业典礼",
                "bgm_plan": "待剪映搜索",
                "transferable_points": ["第一视角现场代入感", "毕业季强身份标签"],
                "recreation_direction": ["用本地素材批次中的真实清华毕业典礼画面重组"],
                "suggested_outputs": ["轻量剪辑卡", "BGM/节奏参考", "发布文案初稿"],
                "lightweight_edit_card": ["前3秒高密度切清华标识、黄领近景和典礼现场"],
                "pending_items": ["确认原视频BGM名称", "读取本地素材批次具体镜头"],
                "next_steps": ["确认同款BGM", "筛选本地素材"],
                "confidence": 0.72,
                "missing_fields": [],
                "evidence": "模式：轻量反抄 / BGM 卡点",
                "reason": "主体字段完整，需要 Mac 读取本地批次。",
            }
        )
        message = make_message(
            "拆解-再创",
            "爆款视频链接：https://www.douyin.com/jingxuan/search/demo\n模式：轻量反抄 / BGM 卡点\n本地素材批次ID：20260627_清华毕业典礼",
        )
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"CONTENT_OS_VAULT_ROOT": tmpdir}), patch(
            "openclaw_app.router.recreation.run_media_subprocess_with_watchdog", return_value=partial_deconstruct_completed()
        ):
            result = harness.handle_再创作(message)
            task = result.extra["local_batch_task"]
            self.assertEqual(task["status"], "created")
            task_text = Path(task["task_path"]).read_text(encoding="utf-8")
            self.assertIn("openclaw_queue_dispatch", task_text)
            self.assertIn("20260627_清华毕业典礼", task_text)
            self.assertIn("mac_reads_local_inbox_batch: true", task_text)
            self.assertNotIn("/Users/", task_text)
            self.assertIn("Mac 本地素材读取任务", result.reply)

    def test_recreation_depth_tags_are_registered(self) -> None:
        self.assertIn("拆解-再创", TAG_LABELS)
        self.assertIn("拆解-再创-简略", TAG_LABELS)
        self.assertIn("拆解-再创-详细", TAG_LABELS)

    def test_recreation_depth_contract(self) -> None:
        harness = RecreationHarness({
            "title": "清华毕业再创",
            "intent": "复用爆款结构",
            "target": "抖音毕业视频",
            "transferable_points": ["节奏"],
            "recreation_direction": ["用本地素材重组"],
            "suggested_outputs": ["轻量剪辑卡"],
            "pending_items": ["确认素材"],
            "next_steps": ["剪映搜索 BGM"],
            "confidence": 0.8,
        })
        self.assertEqual(harness._recreation_depth(make_message("拆解-再创", "爆款视频链接：https://example.com/v"), {}), "brief")
        self.assertEqual(harness._recreation_depth(make_message("拆解-再创-简略", "爆款视频链接：https://example.com/v"), {}), "brief")
        self.assertEqual(harness._recreation_depth(make_message("拆解-再创-详细", "爆款视频链接：https://example.com/v"), {}), "detailed")
        self.assertEqual(harness._recreation_depth(make_message("拆解-再创", "爆款视频链接：https://example.com/v\n目标：完整拆解 + Storyboard + EDL"), {}), "detailed")

    def test_detailed_recreation_runs_full_deconstruct_without_partial_flags(self) -> None:
        harness = RecreationHandleHarness(
            {
                "title": "清华毕业深度再创",
                "source_url": "https://www.douyin.com/jingxuan/search/demo",
                "intent": "完整拆解爆款毕业季视频并迁移结构。",
                "target": "转化为抖音平台的清华毕业典礼第一视角体验内容。",
                "recreation_depth": "detailed",
                "mode": "详细再创作",
                "deconstruction_depth": "full",
                "local_batch_id": "20260627_清华毕业典礼",
                "bgm_plan": "待剪映搜索",
                "transferable_points": ["身份开头", "节奏推进", "情绪收束"],
                "recreation_direction": ["用本地素材重建叙事结构"],
                "suggested_outputs": ["完整爆款拆解", "发布脚本", "视频分镜", "素材需求清单"],
                "video_storyboard": ["0-3s 清华标识强钩子", "3-12s 毕业现场快切"],
                "material_requirements": ["校门", "毕业服", "典礼现场"],
                "anti_copy_notes": "只迁移结构，不复刻原文案。",
                "pending_items": ["确认成片时长"],
                "next_steps": ["完整拆解后筛选本地素材"],
                "confidence": 0.84,
                "missing_fields": [],
                "evidence": "【拆解-再创-详细】",
                "reason": "用户明确要求完整拆解。",
            }
        )
        message = make_message("拆解-再创-详细", "爆款视频链接：https://www.douyin.com/jingxuan/search/demo\n目标：完整拆解 + 生成自己的发布脚本 + 素材匹配准备")

        with patch("openclaw_app.router.recreation.run_media_subprocess_with_watchdog", return_value=full_deconstruct_completed()) as run:
            result = harness.handle_再创作(message)

        command = run.call_args.args[0]
        self.assertNotIn("--partial", command)
        self.assertNotIn("--no-write", command)
        self.assertIn("【拆解】https://www.douyin.com/jingxuan/search/demo", command)
        self.assertEqual(result.extra["recreation_depth"], "detailed")
        self.assertEqual(result.extra["full_deconstruct"]["status"], "done")
        self.assertIn("再创作深度：详细", result.reply)
        self.assertIn("完整拆解：done", result.reply)
        sections = dict(harness.archive_service.calls[0]["sections"])
        self.assertIn("完整拆解结果", sections)
        self.assertIn("发布脚本", sections)

    def test_recreation_task_card_accepts_complete_low_confidence_llm_card(self) -> None:
        harness = RecreationHarness(
            {
                "title": "清华毕业卡点再创",
                "source_url": "https://www.douyin.com/jingxuan/search/demo",
                "intent": "参考爆款毕业季视频的开头标题、情绪氛围、BGM节奏和卡点方式。",
                "target": "转化为抖音平台的清华毕业典礼第一视角体验内容。",
                "mode": "轻量反抄_BGM卡点",
                "deconstruction_depth": "partial",
                "local_batch_id": "20260627_清华毕业典礼",
                "bgm_plan": "待剪映搜索",
                "transferable_points": ["第一视角现场代入感", "毕业季强身份标签", "轻量卡点机制"],
                "recreation_direction": ["用本地素材批次中的真实清华毕业典礼画面重组"],
                "suggested_outputs": ["轻量剪辑卡", "BGM/节奏参考", "发布文案初稿"],
                "lightweight_edit_card": ["前3秒高密度切清华标识、黄领近景和典礼现场"],
                "pending_items": ["确认原视频BGM名称", "读取本地素材批次具体镜头"],
                "next_steps": ["确认同款BGM", "筛选本地素材", "生成15-30秒剪辑结构"],
                "confidence": 0.62,
                "missing_fields": ["原视频BGM名称未知", "本地素材批次具体镜头未读取"],
                "evidence": "模式：轻量反抄 / BGM 卡点；本地素材批次ID：20260627_清华毕业典礼",
                "reason": "主体字段完整，但原视频细节和本地素材清单尚未确认。",
            }
        )

        task_card = harness._recreation_task_card_with_llm(
            make_message(
                "拆解-再创",
                "爆款视频链接：https://www.douyin.com/jingxuan/search/demo\n模式：轻量反抄 / BGM 卡点\n本地素材批次ID：20260627_清华毕业典礼",
            )
        )
        sections = dict(harness._recreation_sections_from_task_card(make_message("拆解-再创", "body"), task_card))

        self.assertTrue(task_card["ok"])
        self.assertEqual(task_card["confidence"], 0.62)
        self.assertIn("原视频BGM名称未知", task_card["missing_fields"])
        self.assertIn("LLM标记的信息缺口", sections["LLM整理依据"])
        self.assertIn("本地素材批次具体镜头未读取", sections["LLM整理依据"])

    def test_recreation_handle_generates_complete_low_confidence_task_card(self) -> None:
        harness = RecreationHandleHarness(
            {
                "title": "清华毕业卡点再创",
                "source_url": "https://www.douyin.com/jingxuan/search/demo",
                "intent": "参考爆款毕业季视频的开头标题、情绪氛围、BGM节奏和卡点方式。",
                "target": "转化为抖音平台的清华毕业典礼第一视角体验内容。",
                "mode": "轻量反抄_BGM卡点",
                "deconstruction_depth": "partial",
                "local_batch_id": "20260627_清华毕业典礼",
                "bgm_plan": "待剪映搜索",
                "transferable_points": ["第一视角现场代入感", "毕业季强身份标签"],
                "recreation_direction": ["用本地素材批次中的真实清华毕业典礼画面重组"],
                "suggested_outputs": ["轻量剪辑卡", "BGM/节奏参考", "发布文案初稿"],
                "lightweight_edit_card": ["前3秒高密度切清华标识、黄领近景和典礼现场"],
                "pending_items": ["确认原视频BGM名称", "读取本地素材批次具体镜头"],
                "next_steps": ["确认同款BGM", "筛选本地素材", "生成15-30秒剪辑结构"],
                "confidence": 0.62,
                "missing_fields": ["原视频BGM名称未知", "本地素材批次具体镜头未读取"],
                "evidence": "模式：轻量反抄 / BGM 卡点",
                "reason": "主体字段完整，但原视频细节和本地素材清单尚未确认。",
            }
        )

        with patch("openclaw_app.router.recreation.run_media_subprocess_with_watchdog", return_value=partial_deconstruct_completed()):
            result = harness.handle_再创作(
                make_message("拆解-再创", "爆款视频链接：https://www.douyin.com/jingxuan/search/demo\n模式：轻量反抄 / BGM 卡点")
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "archived")
        self.assertIn("已生成再创作任务卡", result.reply)
        self.assertEqual(harness.archive_service.calls[0]["extra_frontmatter"]["llm_task_card_status"], "done")

    def test_recreation_task_card_still_fails_when_required_body_fields_are_missing(self) -> None:
        harness = RecreationHarness(
            {
                "title": "清华毕业卡点再创",
                "reason": "只返回标题和理由，不足以生成任务卡主体。",
                "confidence": 0.9,
                "missing_fields": [],
            }
        )

        task_card = harness._recreation_task_card_with_llm(make_message("拆解-再创", "模式：轻量反抄 / BGM 卡点"))

        self.assertFalse(task_card["ok"])
        self.assertEqual(task_card["status"], "pending_manual")
        self.assertIn("intent", task_card["missing_fields"])
        self.assertIn("recreation_direction", task_card["missing_fields"])

    def test_recreation_doc_title_uses_creation_recreation_prefix(self) -> None:
        harness = RecreationHarness({})
        message = make_message("拆解-再创", "转到 400 米训练视频")

        doc_name = harness._recreation_entry_doc_name("run-001", message, [("转化目标", "抖音 400 米训练短视频")], "赛事转场开头")

        self.assertTrue(doc_name.startswith("拆解-再创｜赛事转场开头｜"))
        self.assertNotIn("再创作｜", doc_name)


if __name__ == "__main__":
    unittest.main()
