from __future__ import annotations

import unittest
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message
from openclaw_app.router.activity_daily import ActivityDailyMixin
from openclaw_app.services.obsidian_daily_checklist_service import ObsidianDailyChecklistService


TZ = ZoneInfo("Asia/Shanghai")


class ForbiddenScheduleService:
    def parse(self, *_args, **_kwargs):
        raise AssertionError("daily task extraction must use LLM, not schedule_service.parse")


class FakeContentFlowClient:
    def __init__(self, result: dict | list[dict], *, activity_result: dict | None = None, analyze_result: dict | None = None):
        self.result = result
        self.results = list(result) if isinstance(result, list) else None
        self.activity_result = activity_result or {}
        self.analyze_result = analyze_result or {}
        self.calls: list[dict] = []

    def _call_profile_provider_json(self, profile_name: str, prompt: str, user_content: str, stage: str) -> dict:
        self.calls.append(
            {
                "profile_name": profile_name,
                "prompt": prompt,
                "user_content": user_content,
                "stage": stage,
            }
        )
        if self.results is not None:
            if not self.results:
                raise AssertionError("unexpected extra LLM call")
            return self.results.pop(0)
        return self.result

    def clean_activity_brief(self, text: str, **kwargs) -> dict:
        self.calls.append({"profile_name": "activity_cleaning", "text": text, "kwargs": kwargs})
        return self.activity_result

    def analyze(self, url: str, **kwargs) -> dict:
        self.calls.append({"profile_name": "content_flow_analysis", "url": url, "kwargs": kwargs})
        return self.analyze_result

    @staticmethod
    def _platform_from_url(url: str) -> str:
        return "小红书" if "xhslink.com" in url or "xiaohongshu.com" in url else ""


class FakeArchiveService:
    def __init__(self):
        self.calls: list[dict] = []

    def save_archive(self, message: Message, title: str, sections: list[tuple[str, str]], extra_frontmatter: dict | None = None):
        self.calls.append(
            {
                "message": message,
                "title": title,
                "sections": sections,
                "extra_frontmatter": extra_frontmatter or {},
            }
        )
        return SimpleNamespace(frontmatter={"id": "archive-id"}, local_path="/tmp/archive.md")


class FakeReminderService:
    bitable_url = "https://bitable.default"
    config_paths: dict[str, str] = {}

    def __init__(self):
        self.calls: list[dict] = []

    def add(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        due_at: datetime | None,
        remind_at: datetime | None = None,
        source: str = "",
        ref_id: str = "",
        local_path: str = "",
        extra_fields: dict | None = None,
        omit_management_fields: bool = False,
        config_path_key: str | None = None,
    ) -> dict:
        self.calls.append(
            {
                "kind": kind,
                "title": title,
                "text": text,
                "due_at": due_at,
                "remind_at": remind_at,
                "source": source,
                "ref_id": ref_id,
                "local_path": local_path,
                "extra_fields": extra_fields,
                "omit_management_fields": omit_management_fields,
                "config_path_key": config_path_key,
            }
        )
        return {
            "ok": True,
            "data": {
                "record_id": "rec-test",
                "table_url": "https://bitable.test",
                "calendar": {"ok": True, "event_id": "evt-test", "app_link": "https://calendar.test"},
            },
        }


class FailingReminderService(FakeReminderService):
    def add(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {"ok": False, "error": "feishu unavailable"}


class DailyHarness(ActivityDailyMixin):
    def __init__(self, llm_result: dict, *, activity_result: dict | None = None, analyze_result: dict | None = None):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.timezone = "Asia/Shanghai"
        self.content_flow_client = FakeContentFlowClient(llm_result, activity_result=activity_result, analyze_result=analyze_result)
        self.archive_service = FakeArchiveService()
        self.reminder_service = FakeReminderService()
        self.schedule_service = ForbiddenScheduleService()
        self.obsidian_daily_checklist_service = ObsidianDailyChecklistService(Path(self._tmpdir.name) / "Archieve")

    def _conversation_context_prompt(self, _message: Message) -> str:
        return ""

    def _configured_bitable_url(self, _kind: str) -> str:
        return "https://bitable.configured"


def make_message(tag: str, body: str) -> Message:
    return Message(
        entry_tag=tag,
        raw_text=f"【{tag}】{body}",
        body=body,
        source="feishu",
        chat_type="private",
        created_at=datetime(2026, 5, 29, 13, 30, tzinfo=TZ),
    )


class ActivityDailyLlmTest(unittest.TestCase):
    def test_activity_xhs_link_reuses_content_flow_analysis_before_activity_cleaning(self) -> None:
        xhs_url = "https://xhslink.com/m/1IY0IeXnk0W"
        harness = DailyHarness(
            {},
            analyze_result={
                "status": "done",
                "media_dir": "/tmp/xhs",
                "analysis_path": "/tmp/xhs/analysis.json",
                "caption": "#校园生活[话题]# 参加校园创作活动，投稿需带主话题。",
                "image_ocr": "活动时间：2026-06-01 至 2026-06-30\n奖励：流量扶持",
                "analysis": {
                    "platform": "小红书",
                    "title": "校园生活创作活动",
                    "summary": ["围绕校园生活发布图文或视频。"],
                    "work_copy": "参加校园创作活动，投稿需带主话题。",
                    "full_content": "活动时间：2026-06-01 至 2026-06-30\n提交要求：发布笔记并带 #校园生活。",
                    "tags": ["校园生活", "创作活动"],
                },
            },
            activity_result={
                "status": "done",
                "title": "校园生活创作活动",
                "platform": "小红书",
                "brief_summary": "围绕校园生活发布图文或视频。",
                "activity_time": "2026-06-01 至 2026-06-30",
                "activity_time_start": "2026-06-01",
                "activity_time_end": "2026-06-30",
                "main_topic": "#校园生活",
                "activity_level": "",
                "reward": "流量扶持",
                "participation_method": "发布小红书笔记参与。",
                "participation_form": "图文或视频",
                "filling_points": "",
                "submission_requirements": "发布笔记并带 #校园生活。",
                "subtopic_directions": ["校园日常"],
                "source_links": [{"label": "活动链接", "url": xhs_url}],
                "activity_status": "进行中",
                "parse_status": "已解析",
                "missing_info": [],
            },
        )

        result = harness.handle_活动(make_message("活动", f"活动链接：{xhs_url}"))

        self.assertTrue(result.ok)
        self.assertIn("链接提取：已提取 1/1 个小红书链接", result.reply)
        self.assertEqual(harness.content_flow_client.calls[0]["profile_name"], "content_flow_analysis")
        self.assertGreaterEqual(harness.content_flow_client.calls[0]["kwargs"]["poll_attempts"], 300)
        clean_call = harness.content_flow_client.calls[1]
        self.assertEqual(clean_call["profile_name"], "activity_cleaning")
        self.assertIn("【链接内容提取】", clean_call["text"])
        self.assertIn("校园生活创作活动", clean_call["text"])
        self.assertIn("活动时间：2026-06-01 至 2026-06-30", clean_call["text"])
        reminder_call = harness.reminder_service.calls[0]
        self.assertEqual(reminder_call["kind"], "活动")
        self.assertEqual(reminder_call["extra_fields"]["主状态"], "进行中")
        self.assertEqual(reminder_call["extra_fields"]["平台名称"], ["小红书"])
        self.assertEqual(reminder_call["extra_fields"]["活动开始时间"], "2026-06-01")
        self.assertEqual(reminder_call["extra_fields"]["活动结束时间"], "2026-06-30")
        self.assertIn(xhs_url, reminder_call["extra_fields"]["Brief链接"])
        self.assertEqual(reminder_call["extra_fields"]["冲榜日期"], "")
        self.assertNotIn("活动文档链接", reminder_call["extra_fields"])
        self.assertNotIn("返稿链接", reminder_call["extra_fields"])
        self.assertNotIn("爆款示范链接", reminder_call["extra_fields"])
        self.assertEqual(result.extra["source_extractions"][0]["analysis_path"], "/tmp/xhs/analysis.json")

    def test_activity_xhs_publish_entry_is_skipped_before_content_flow(self) -> None:
        xhs_url = "https://fe.xiaohongshu.com/ditto/vincent/2d73971cda2d4e0b91c6b21288d60f63"
        harness = DailyHarness(
            {},
            activity_result={
                "status": "done",
                "title": "户外涂鸦小人活动",
                "platform": "小红书",
                "brief_summary": "上传照片生成涂鸦分身并发布笔记。",
                "activity_time": "",
                "activity_time_start": "",
                "activity_time_end": "",
                "main_topic": "#户外涂鸦小人",
                "activity_level": "",
                "reward": "流量扶持",
                "participation_method": "通过发布入口使用模板。",
                "participation_form": "小红书模板",
                "filling_points": "",
                "submission_requirements": "发布时携带话题。",
                "subtopic_directions": ["户外照片涂鸦分身"],
                "source_links": [{"label": "发布入口", "url": xhs_url}],
                "activity_status": "进行中",
                "parse_status": "已解析",
                "missing_info": [],
            },
        )

        result = harness.handle_活动(make_message("活动", f"发布入口：{xhs_url}"))

        self.assertTrue(result.ok)
        self.assertNotIn("content_flow_analysis", [call["profile_name"] for call in harness.content_flow_client.calls])
        self.assertIn("链接提取：已跳过 1/1 个小红书链接", result.reply)
        self.assertIn("小红书发布入口/模板页，不是笔记正文链接", result.reply)
        self.assertEqual(result.extra["source_extractions"][0]["status"], "skipped")
        self.assertEqual(result.extra["source_extractions"][0]["source_kind"], "xiaohongshu_publish_entry")
        clean_call = harness.content_flow_client.calls[0]
        self.assertEqual(clean_call["profile_name"], "activity_cleaning")
        self.assertNotIn("【链接内容提取】", clean_call["text"])

    def test_activity_source_url_decision_classifies_actions(self) -> None:
        cases = [
            ("https://xhslink.com/m/1IY0IeXnk0W", "analyze", "xiaohongshu_shortlink"),
            ("https://www.xiaohongshu.com/explore/665ef5cb6ba34db6a3287a741e5a9d5e", "analyze", "xiaohongshu_page"),
            ("https://fe.xiaohongshu.com/ditto/vincent/2d73971cda2d4e0b91c6b21288d60f63", "skip", "xiaohongshu_publish_entry"),
            ("https://doc.weixin.qq.com/forms/ANAAyQcbAAgAUYAugZpADwCN25nzeeuCf", "ignore", "unsupported_url"),
        ]

        for url, action, kind in cases:
            with self.subTest(url=url):
                decision = DailyHarness({})._activity_source_url_decision(url)
                self.assertEqual(decision["action"], action)
                self.assertEqual(decision["kind"], kind)

    def test_activity_links_remain_in_brief_link_field(self) -> None:
        harness = DailyHarness({})
        links = [
            {"label": "爆款示范笔记", "url": "https://www.douyin.com/note/7649248814721009306"},
            {"label": "返稿报名表", "url": "https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb"},
            {"label": "活动文档", "url": "https://bytedance.larkoffice.com/wiki/Ixs9wp88vioGt0kVrhHcZmkgnZg"},
        ]

        rendered = harness._activity_render_links(links)

        self.assertIn("爆款示范笔记：https://www.douyin.com/note/7649248814721009306", rendered)
        self.assertIn("返稿报名表：https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb", rendered)
        self.assertIn("活动文档：https://bytedance.larkoffice.com/wiki/Ixs9wp88vioGt0kVrhHcZmkgnZg", rendered)
        split = harness._activity_split_link_fields(links)
        self.assertEqual(split["爆款示范链接"], "爆款示范笔记：https://www.douyin.com/note/7649248814721009306")
        self.assertEqual(split["返稿链接"], "返稿报名表：https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb")
        self.assertEqual(split["活动文档链接"], "活动文档：https://bytedance.larkoffice.com/wiki/Ixs9wp88vioGt0kVrhHcZmkgnZg")

    def test_activity_legacy_brief_link_text_remains_renderable(self) -> None:
        harness = DailyHarness({})
        legacy_text = (
            "抖音爆款示范：https://www.douyin.com/note/7649248814721009306\n"
            "抖音「请回答2026高考」返稿报名表：https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb\n"
            "更多活动详情：https://bytedance.larkoffice.com/wiki/Ixs9wp88vioGt0kVrhHcZmkgnZg"
        )

        rendered = harness._activity_render_links(legacy_text)

        self.assertIn("https://www.douyin.com/note/7649248814721009306", rendered)
        self.assertIn("https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb", rendered)
        self.assertIn("https://bytedance.larkoffice.com/wiki/Ixs9wp88vioGt0kVrhHcZmkgnZg", rendered)
        split = harness._activity_split_link_fields(legacy_text)
        self.assertIn("https://www.douyin.com/note/7649248814721009306", split["爆款示范链接"])
        self.assertIn("https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb", split["返稿链接"])
        self.assertIn("https://bytedance.larkoffice.com/wiki/Ixs9wp88vioGt0kVrhHcZmkgnZg", split["活动文档链接"])

    def test_activity_link_text_fragment_unwraps_to_single_target_url(self) -> None:
        harness = DailyHarness({})
        wrapped_url = (
            "https://douyin.bytedance.net/egrowth/im/douyinIM#:~:text="
            "https%3A//bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb%3Fsheet%3DjQ9oYC"
        )
        links = [
            {"label": "抖音「请回答2026高考」返稿报名表", "url": wrapped_url},
            {"label": "返稿报名表", "url": "https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb?sheet=jQ9oYC"},
        ]

        rendered = harness._activity_render_links(links)

        self.assertEqual(
            rendered,
            "抖音「请回答2026高考」返稿报名表：https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb?sheet=jQ9oYC",
        )
        self.assertNotIn("douyin.bytedance.net/egrowth/im/douyinIM", rendered)

    def test_activity_boost_date_creates_previous_day_schedule(self) -> None:
        harness = DailyHarness(
            {},
            activity_result={
                "status": "done",
                "title": "毕业季有问必答",
                "platform": "抖音",
                "brief_summary": "毕业季话题活动。",
                "activity_time": "2026-06-01 至 2026-06-30",
                "activity_time_start": "2026-06-01",
                "activity_time_end": "2026-06-30",
                "boost_date": "2026-06-20",
                "main_topic": "#毕业季有问必答",
                "activity_level": "平台",
                "reward": "流量扶持",
                "participation_method": "发布图文或短视频参与。",
                "participation_form": "图文或短视频",
                "filling_points": "填写返稿表",
                "submission_requirements": "带话题并填表。",
                "subtopic_directions": ["毕业经验"],
                "source_links": [{"label": "返稿报名表", "url": "https://bytedance.larkoffice.com/sheets/form"}],
                "activity_status": "进行中",
                "parse_status": "已解析",
                "missing_info": [],
            },
        )

        result = harness.handle_活动(make_message("活动", "【活动】毕业季活动，冲榜日期 2026-06-20，返稿报名表：https://bytedance.larkoffice.com/sheets/form"))

        self.assertTrue(result.ok)
        self.assertEqual([call["kind"] for call in harness.reminder_service.calls], ["活动", "日程"])
        activity_call, schedule_call = harness.reminder_service.calls
        self.assertEqual(activity_call["extra_fields"]["冲榜日期"], "2026-06-20")
        self.assertEqual(activity_call["extra_fields"]["返稿链接"], "返稿报名表：https://bytedance.larkoffice.com/sheets/form")
        self.assertNotIn("爆款示范链接", activity_call["extra_fields"])
        self.assertNotIn("活动文档链接", activity_call["extra_fields"])
        self.assertEqual(schedule_call["title"], "冲榜提醒：毕业季有问必答")
        self.assertEqual(schedule_call["due_at"].strftime("%y%m%d %H:%M"), "260619 09:00")
        self.assertEqual(schedule_call["remind_at"].strftime("%y%m%d %H:%M"), "260619 09:00")
        self.assertEqual(schedule_call["ref_id"], "rec-test-boost")
        self.assertFalse(schedule_call["extra_fields"])
        self.assertIn("冲榜日期：2026-06-20", schedule_call["text"])
        self.assertIn("活动记录ID：rec-test", schedule_call["text"])

    def test_activity_multiple_creation_directions_create_child_activity_records(self) -> None:
        harness = DailyHarness(
            {},
            activity_result={
                "status": "done",
                "title": "毕业旅行前最该问清楚的事",
                "platform": "抖音",
                "brief_summary": "围绕毕业旅行问答做毕业季内容。",
                "activity_time": "2026-06-18 至 2026-06-30",
                "activity_time_start": "2026-06-18",
                "activity_time_end": "2026-06-30",
                "boost_date": "",
                "main_topic": "#毕业旅行有问必答",
                "activity_level": "平台",
                "reward": "流量扶持",
                "participation_method": "发布图文或短视频参与。",
                "participation_form": "图文或短视频",
                "filling_points": "填写返稿表",
                "submission_requirements": "带话题并填表。",
                "subtopic_directions": [
                    "毕业旅行前最该问清楚的事",
                    "高考后第一次和朋友出远门会踩哪些坑",
                    "预算有限怎么安排一场毕业旅行",
                ],
                "source_links": [{"label": "返稿报名表", "url": "https://bytedance.larkoffice.com/sheets/form"}],
                "activity_status": "进行中",
                "parse_status": "已解析",
                "missing_info": [],
            },
        )

        result = harness.handle_活动(make_message("活动", "抖音请回答2026高考｜毕业旅行有问必答"))

        self.assertTrue(result.ok)
        self.assertEqual([call["kind"] for call in harness.reminder_service.calls], ["活动", "活动", "活动", "活动"])
        parent_call, *child_calls = harness.reminder_service.calls
        self.assertEqual(parent_call["title"], "毕业旅行前最该问清楚的事")
        self.assertNotIn("父记录", parent_call["extra_fields"])
        self.assertEqual(parent_call["extra_fields"]["子话题方向"].count("- "), 3)
        self.assertEqual([call["title"] for call in child_calls], [
            "毕业旅行前最该问清楚的事",
            "高考后第一次和朋友出远门会踩哪些坑",
            "预算有限怎么安排一场毕业旅行",
        ])
        for child_call in child_calls:
            self.assertEqual(child_call["extra_fields"]["父记录"], "rec-test")
            self.assertEqual(child_call["extra_fields"]["类型说明"], "创作方向子记录")
            self.assertEqual(child_call["extra_fields"]["冲榜日期"], "")
            self.assertEqual(child_call["extra_fields"]["子话题方向"], f"- {child_call['title']}")
            self.assertIn(f"创作方向：{child_call['title']}", child_call["extra_fields"]["活动Brief"])
        self.assertIn("方向子记录：已创建 3/3 条", result.reply)

    def test_todo_uses_llm_extracted_deadline_and_default_reminder(self) -> None:
        harness = DailyHarness(
            [
                {
                    "mode": "reminder_backed",
                    "items": [],
                    "confidence": 0.95,
                    "missing_fields": [],
                    "evidence": "第一批统计截止到 5 月 31 日中午 12:00",
                    "reason": "原文明确说明截止时间",
                },
                {
                    "type": "待办",
                    "title": "毕业典礼报名第一批统计截止",
                    "due_at": "2026-05-31T12:00:00+08:00",
                    "remind_at": "",
                    "confidence": 0.92,
                    "missing_fields": [],
                    "evidence": "第一批统计截止到 5 月 31 日中午 12:00",
                    "reason": "原文明确说明截止时间",
                },
            ]
        )
        message = make_message("待办", "我收到了这条毕业典礼报名待办：第一批统计截止到 5 月 31 日中午 12:00。")

        result = harness.handle_待办(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "archived")
        self.assertEqual([call["stage"] for call in harness.content_flow_client.calls], ["待办清单与提醒分流", "日程待办自然语言抽取"])
        self.assertIn("我收到了这条毕业典礼报名待办", harness.content_flow_client.calls[1]["user_content"])
        reminder_call = harness.reminder_service.calls[0]
        self.assertEqual(reminder_call["kind"], "待办")
        self.assertEqual(reminder_call["title"], "毕业典礼报名第一批统计截止")
        self.assertEqual(reminder_call["due_at"].strftime("%y%m%d %H:%M"), "260531 12:00")
        self.assertEqual(reminder_call["remind_at"].strftime("%y%m%d %H:%M"), "260531 11:30")
        archive_call = harness.archive_service.calls[0]
        self.assertEqual(archive_call["extra_frontmatter"]["due_at"], "260531 12:00")
        self.assertEqual(archive_call["extra_frontmatter"]["remind_at"], "260531 11:30")
        checklist_path = Path(result.reply.split("Obsidian：", 1)[1].splitlines()[0])
        self.assertTrue(checklist_path.is_file())
        self.assertIn("openclaw:feishu_record=rec-test", checklist_path.read_text(encoding="utf-8"))

    def test_todo_feishu_failure_writes_plain_obsidian_checklist_without_record_id(self) -> None:
        harness = DailyHarness(
            [
                {
                    "mode": "reminder_backed",
                    "items": [],
                    "confidence": 0.95,
                    "missing_fields": [],
                    "evidence": "20260628 18:00 前买杠铃杆",
                    "reason": "原文明确说明截止时间",
                },
                {
                    "type": "待办",
                    "title": "买杠铃杆",
                    "due_at": "2026-06-28T18:00:00+08:00",
                    "remind_at": "",
                    "confidence": 0.92,
                    "missing_fields": [],
                    "evidence": "20260628 18:00 前买杠铃杆",
                    "reason": "原文明确说明截止时间",
                },
            ]
        )
        harness.reminder_service = FailingReminderService()
        message = make_message("待办", "20260628 18:00 前买杠铃杆")

        result = harness.handle_待办(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "pending_manual")
        self.assertIn("飞书提醒写入失败", result.reply)
        checklist_path = Path(result.reply.split("Obsidian：", 1)[1].splitlines()[0])
        content = checklist_path.read_text(encoding="utf-8")
        self.assertIn("- [ ] 买杠铃杆", content)
        self.assertNotIn("feishu_record", content)

    def test_todo_accepts_media_material_as_explicit_checklist_item(self) -> None:
        harness = DailyHarness(
            [
                {
                    "mode": "checklist_only",
                    "items": ["跟进陈小杨 AI4Math 资源，用于博主宣传和 vibecoding 素材"],
                    "checklist_tree": [],
                    "confidence": 0.9,
                    "missing_fields": [],
                    "evidence": "同济大学陈小杨有 AI4Math 的资源；博主宣传；vibecoding 的素材",
                    "reason": "用户显式使用【待办】，原文是一条可跟进事项，且没有截止或提醒诉求",
                }
            ]
        )
        message = make_message("待办", "同济大学陈小杨有 AI4Math 的资源，可以用来做博主宣传做 vibecoding 的素材。")

        result = harness.handle_待办(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "obsidian_checklist_archived")
        self.assertEqual(harness.reminder_service.calls, [])
        self.assertEqual(len(harness.content_flow_client.calls), 1)
        self.assertIn("不要因为内容领域跨到 media 就拒绝或改路由", harness.content_flow_client.calls[0]["prompt"])
        self.assertIn("已写入 Obsidian 当日待办清单", result.reply)
        obsidian_path = Path(result.extra["obsidian_path"])
        content = obsidian_path.read_text(encoding="utf-8")
        self.assertIn("- [ ] 跟进陈小杨 AI4Math 资源，用于博主宣传和 vibecoding 素材", content)
        self.assertNotIn("feishu_record", content)

    def test_todo_knowledge_record_review_stays_checklist_only(self) -> None:
        harness = DailyHarness(
            [
                {
                    "mode": "checklist_only",
                    "items": ["查看清北光环创业泥潭是否相关"],
                    "checklist_tree": [],
                    "confidence": 0.9,
                    "missing_fields": [],
                    "evidence": "查看做题家清北光环为何难穿越创业泥潭否 跟自己有关；原链接 http://xhslink.com/o/16704LMMFPp",
                    "reason": "用户显式使用【待办】，正文是查看并判断某条知识记录是否相关，没有提醒、截止或读取知识库诉求",
                }
            ]
        )
        message = make_message(
            "待办",
            "查看做题家清北光环为何难穿越创业泥潭否 跟自己有关\n"
            "做题家清北光环为何难穿越创业泥潭\n"
            "原链接\n"
            "http://xhslink.com/o/16704LMMFPp\n"
            "来源平台\n"
            "小红书\n"
            "内容类型\n"
            "图文\n"
            "一级分类\n"
            "财经/投资\n"
            "二级分类\n"
            "投资认知\n"
            "查看记录详情",
        )

        result = harness.handle_待办(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "obsidian_checklist_archived")
        self.assertEqual(harness.reminder_service.calls, [])
        self.assertEqual(len(harness.content_flow_client.calls), 1)
        prompt = harness.content_flow_client.calls[0]["prompt"]
        self.assertIn("不要打开或读取知识库/Base/表格/文档", prompt)
        self.assertIn("不要请求飞书用户授权", prompt)
        self.assertIn("不要改判为知识、学习、调研或自媒体知识入口", prompt)
        self.assertIn("http://xhslink.com/o/16704LMMFPp", harness.content_flow_client.calls[0]["user_content"])
        obsidian_path = Path(result.extra["obsidian_path"])
        content = obsidian_path.read_text(encoding="utf-8")
        self.assertIn("- [ ] [查看清北光环创业泥潭是否相关](http://xhslink.com/o/16704LMMFPp)", content)
        self.assertNotIn("feishu_record", content)

    def test_todo_plain_purchase_checklist_writes_obsidian_without_feishu(self) -> None:
        harness = DailyHarness(
            {
                "mode": "checklist_only",
                "items": ["整理购买清单", "购买杠铃杆", "购买起泡器"],
                "confidence": 0.95,
                "missing_fields": [],
                "evidence": "购买；1. 整理；2. 杠铃杆；3. 起泡器",
                "reason": "原文是购物清单，没有提醒或截止诉求",
            }
        )
        message = make_message("待办", "购买\n1. 整理\n2. 杠铃杆\n3. 起泡器")

        result = harness.handle_待办(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "obsidian_checklist_archived")
        self.assertEqual(len(harness.content_flow_client.calls), 1)
        self.assertEqual(harness.content_flow_client.calls[0]["stage"], "待办清单与提醒分流")
        self.assertEqual(harness.reminder_service.calls, [])
        self.assertIn("已写入 Obsidian 当日待办清单", result.reply)
        obsidian_path = Path(result.extra["obsidian_path"])
        self.assertTrue(obsidian_path.is_file())
        content = obsidian_path.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("# 待办\n"))
        self.assertIn("- [ ] 整理购买清单", content)
        self.assertIn("- [ ] 购买杠铃杆", content)
        self.assertIn("- [ ] 购买起泡器", content)
        self.assertNotIn("feishu_record", content)

    def test_todo_structured_purchase_checklist_writes_feishu_parent_children_and_indented_obsidian(self) -> None:
        harness = DailyHarness(
            {
                "mode": "structured_checklist",
                "items": [],
                "checklist_tree": [
                    {
                        "text": "购买",
                        "children": [
                            {"text": "整理购买清单", "children": []},
                            {"text": "购买杠铃杆", "children": []},
                            {"text": "购买起泡器", "children": []},
                        ],
                    }
                ],
                "confidence": 0.95,
                "missing_fields": [],
                "evidence": "购买；1. 整理；2. 杠铃杆；3. 起泡器",
                "reason": "原文是购买任务组下面列出多个子事项，需要保留父子层级",
            }
        )
        message = make_message("待办", "购买\n1. 整理\n2. 杠铃杆\n3. 起泡器")

        result = harness.handle_待办(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "structured_checklist_archived")
        self.assertEqual(len(harness.content_flow_client.calls), 1)
        self.assertEqual(harness.content_flow_client.calls[0]["stage"], "待办清单与提醒分流")
        self.assertEqual([call["kind"] for call in harness.reminder_service.calls], ["待办", "待办", "待办", "待办"])
        parent_call, *child_calls = harness.reminder_service.calls
        self.assertEqual(parent_call["title"], "购买")
        self.assertTrue(parent_call["omit_management_fields"])
        self.assertNotIn("父记录", parent_call["extra_fields"])
        self.assertEqual(parent_call["extra_fields"]["类型说明"], "待办父记录")
        for child_call in child_calls:
            self.assertTrue(child_call["omit_management_fields"])
            self.assertEqual(child_call["extra_fields"]["父记录"], "rec-test")
            self.assertEqual(child_call["extra_fields"]["类型说明"], "待办子记录")
        obsidian_path = Path(result.extra["obsidian_path"])
        content = obsidian_path.read_text(encoding="utf-8")
        self.assertIn("- [ ] 购买", content)
        self.assertIn("  - [ ] 整理购买清单", content)
        self.assertIn("  - [ ] 购买杠铃杆", content)
        self.assertIn("飞书记录：", result.reply)

    def test_todo_structured_purchase_checklist_reports_feishu_failure_without_success_claim(self) -> None:
        harness = DailyHarness(
            {
                "mode": "structured_checklist",
                "items": [],
                "checklist_tree": [{"text": "购买", "children": [{"text": "购买2.2m 20kg杠铃杆", "children": []}]}],
                "confidence": 0.95,
                "missing_fields": [],
                "evidence": "购买：2.2m, 20kg杠铃杆",
                "reason": "原文是购买任务组",
            }
        )
        harness.reminder_service = FailingReminderService()
        message = make_message("待办", "购买：2.2m, 20kg杠铃杆")

        result = harness.handle_待办(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "partial_failed")
        self.assertIn("飞书父子待办创建失败", result.reply)
        self.assertNotIn("已创建飞书父子待办", result.reply)
        self.assertIn("feishu unavailable", result.reply)
        self.assertIn("表格里不会出现对应记录", result.reply)
        self.assertFalse(harness.archive_service.calls[0]["extra_frontmatter"]["feishu_synced"])

    def test_todo_completion_deadline_phrase_uses_llm_extracted_deadline(self) -> None:
        harness = DailyHarness(
            [
                {
                    "mode": "reminder_backed",
                    "items": [],
                    "confidence": 0.95,
                    "missing_fields": [],
                    "evidence": "2026-06-01 前完成关于租房的小红书帖子",
                    "reason": "原文明确说明截止诉求",
                },
                {
                    "type": "待办",
                    "title": "完成租房小红书帖子",
                    "due_at": "2026-06-01T23:59:00+08:00",
                    "remind_at": "",
                    "confidence": 0.9,
                    "missing_fields": [],
                    "evidence": "2026-06-01 前完成关于租房的小红书帖子",
                    "reason": "原文明确说明需要在 2026-06-01 前完成该帖子",
                },
            ]
        )
        message = make_message("待办", "2026-06-01 前完成关于租房的小红书帖子")

        result = harness.handle_待办(message)

        self.assertTrue(result.ok)
        self.assertIn("前完成", harness.content_flow_client.calls[1]["prompt"])
        reminder_call = harness.reminder_service.calls[0]
        self.assertEqual(reminder_call["title"], "完成租房小红书帖子")
        self.assertEqual(reminder_call["due_at"].strftime("%y%m%d %H:%M"), "260601 23:59")
        self.assertEqual(reminder_call["remind_at"].strftime("%y%m%d %H:%M"), "260601 23:29")

    def test_schedule_uses_llm_extracted_time_and_default_reminder(self) -> None:
        harness = DailyHarness(
            {
                "type": "日程",
                "title": "旁听机器人仿真汇报",
                "due_at": "2026-05-29T13:30:00+08:00",
                "remind_at": "",
                "confidence": 0.9,
                "missing_fields": [],
                "evidence": "5 月 29 日 13:30，到深圳学思楼 C3-202 教室旁听",
                "reason": "原文明确说明日程时间和地点",
            }
        )
        message = make_message("日程", "5 月 29 日 13:30，到深圳学思楼 C3-202 教室旁听《机器人与仿生学》的机器人仿真汇报。")

        result = harness.handle_日程(message)

        self.assertTrue(result.ok)
        reminder_call = harness.reminder_service.calls[0]
        self.assertEqual(reminder_call["kind"], "日程")
        self.assertEqual(reminder_call["title"], "旁听机器人仿真汇报")
        self.assertEqual(reminder_call["due_at"].strftime("%y%m%d %H:%M"), "260529 13:30")
        self.assertEqual(reminder_call["remind_at"].strftime("%y%m%d %H:%M"), "260529 12:30")

    def test_schedule_numeric_datetime_uses_llm_not_fast_path(self) -> None:
        harness = DailyHarness(
            {
                "type": "日程",
                "title": "电动车充电",
                "due_at": "2026-06-28T12:00:00+08:00",
                "remind_at": "",
                "confidence": 0.95,
                "missing_fields": [],
                "evidence": "2026-06-28 12:00 电动车充电",
                "reason": "原文包含完整日期时间和事项",
            }
        )
        message = make_message("日程", "2026-06-28 12:00 电动车充电")

        result = harness.handle_日程(message)

        self.assertTrue(result.ok)
        self.assertEqual(len(harness.content_flow_client.calls), 1)
        self.assertEqual(harness.content_flow_client.calls[0]["stage"], "日程待办自然语言抽取")
        reminder_call = harness.reminder_service.calls[0]
        self.assertEqual(reminder_call["kind"], "日程")
        self.assertEqual(reminder_call["title"], "电动车充电")
        self.assertEqual(reminder_call["due_at"].strftime("%y%m%d %H:%M"), "260628 12:00")
        self.assertEqual(reminder_call["remind_at"].strftime("%y%m%d %H:%M"), "260628 11:00")

    def test_tagged_robotics_report_todo_creates_without_confirmation(self) -> None:
        harness = DailyHarness(
            [
                {
                    "mode": "reminder_backed",
                    "items": [],
                    "confidence": 0.95,
                    "missing_fields": [],
                    "evidence": "上课时间：5 月 29 日13:30",
                    "reason": "原文明确包含具体时间",
                },
                {
                    "type": "待办",
                    "title": "旁听机器人仿真汇报",
                    "due_at": "2026-05-29T13:30:00+08:00",
                    "remind_at": "",
                    "confidence": 0.91,
                    "missing_fields": [],
                    "evidence": "上课时间：5 月 29 日13:30，上课地点：深圳学思楼C3-202教室",
                    "reason": "原文明确给出上课时间和地点",
                },
            ]
        )
        message = make_message(
            "待办",
            "思尧，明天下午去 C 楼 教室吧，学生做机器人仿真的汇报，李老师邀请你旁听一下。"
            "《机器人与仿生学》上课时间：5 月 29 日13:30，上课地点：深圳学思楼C3-202教室。",
        )

        result = harness.handle_待办(message)

        self.assertTrue(result.ok)
        self.assertNotIn("如果", result.reply)
        self.assertNotIn("要我", result.reply)
        reminder_call = harness.reminder_service.calls[0]
        self.assertEqual(reminder_call["kind"], "待办")
        self.assertEqual(reminder_call["due_at"].strftime("%y%m%d %H:%M"), "260529 13:30")
        self.assertEqual(reminder_call["remind_at"].strftime("%y%m%d %H:%M"), "260529 13:00")

    def test_todo_reports_parser_error_when_llm_misses_explicit_class_time(self) -> None:
        harness = DailyHarness(
            [
                {
                    "mode": "reminder_backed",
                    "items": [],
                    "confidence": 0.95,
                    "missing_fields": [],
                    "evidence": "上课时间：5 月 29 日13:30",
                    "reason": "原文明确包含具体时间",
                },
                {
                    "type": "待办",
                    "title": "旁听机器人仿真汇报",
                    "due_at": "",
                    "remind_at": "",
                    "confidence": 0.91,
                    "missing_fields": ["due_at", "具体时间"],
                    "evidence": "用户邀请旁听汇报",
                    "reason": "用户邀请旁听汇报，但未抽取到具体时间",
                },
            ]
        )
        message = make_message(
            "待办",
            "思尧，明天下午去 C 楼 教室吧，学生做机器人仿真的汇报，李老师邀请你旁听一下。"
            "《机器人与仿生学》上课时间：5 月 29 日13:30，上课地点：深圳学思楼C3-202教室。",
        )

        result = harness.handle_待办(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "parser_error")
        self.assertIn("系统解析错误", result.reply)
        self.assertIn("不需要补时间", result.reply)
        self.assertEqual(harness.archive_service.calls, [])
        self.assertEqual(harness.reminder_service.calls, [])

    def test_structured_graduation_notice_creates_parent_and_children(self) -> None:
        harness = DailyHarness(
            {
                "status": "hierarchy",
                "confidence": 0.94,
                "parent": {
                    "type": "活动",
                    "title": "清华大学深圳国际研究生院2026年毕业典礼",
                    "summary": "2026届毕业生参加学院毕业典礼，需通过问卷报名确认。",
                    "status": "进行中",
                    "fields": {
                        "平台": "清华大学深圳国际研究生院",
                        "活动开始时间": "2026-06-26",
                        "活动结束时间": "2026-06-26",
                        "地点": "深圳大学城国际会议中心千人礼堂",
                        "地点拆解JSON": {
                            "城市": "深圳",
                            "区域": "大学城",
                            "场馆": "深圳大学城国际会议中心",
                            "房间": "千人礼堂",
                        },
                        "参与方式": "填写问卷报名确认",
                        "参与形式": "线下",
                        "提交要求": "第一批统计截止到2026-05-31 12:00，毕业生需及时完成问卷确认",
                        "主话题": "毕业典礼",
                        "活动级别": "学院",
                        "Brief链接": "https://v.wjx.cn/vm/Q0Rf163.aspx#",
                    },
                },
                "children": [
                    {
                        "type": "日程",
                        "title": "参加2026年毕业典礼",
                        "due_at": "2026-06-26T10:00:00+08:00",
                        "remind_at": "",
                        "location": "深圳大学城国际会议中心千人礼堂",
                        "location_parts": {
                            "城市": "深圳",
                            "区域": "大学城",
                            "场馆": "深圳大学城国际会议中心",
                            "房间": "千人礼堂",
                        },
                        "source_link": "https://v.wjx.cn/vm/Q0Rf163.aspx#",
                        "fields": {
                            "事项类型": "典礼当天",
                            "说明": "毕业典礼包括暖场表演、师生校友代表发言、院长讲话、毕业合影等环节。",
                        },
                    },
                    {
                        "type": "待办",
                        "title": "毕业典礼第一批报名统计截止",
                        "due_at": "2026-05-31T12:00:00+08:00",
                        "remind_at": "",
                        "location": "",
                        "location_parts": {},
                        "source_link": "https://v.wjx.cn/vm/Q0Rf163.aspx#",
                        "fields": {"事项类型": "报名截止", "说明": "完成问卷确认。"},
                    },
                ],
                "missing_fields": [],
                "evidence": "活动时间 2026年6月26日上午10:00；活动地点 深圳大学城国际会议中心千人礼堂；第一批统计截止到5月31日中午12:00",
                "reason": "原文包含毕业典礼本体和报名统计截止两个层级节点",
            }
        )
        message = make_message(
            "待办",
            "【关于举行我院2026年毕业典礼的预通知】\n"
            "学院拟定于2026年6月26日举行清华大学深圳国际研究生院2026年毕业典礼。\n\n"
            "一、活动时间\n"
            "2026年6月26日（周五）上午10:00\n\n"
            "二、活动地点\n"
            "深圳大学城国际会议中心千人礼堂\n\n"
            "毕业典礼主要包括暖场表演、师生校友代表发言、院长讲话、毕业合影等环节。\n"
            "请同学们填写链接或扫描二维码报名：\n"
            "https://v.wjx.cn/vm/Q0Rf163.aspx#\n\n"
            "注：第一批统计截止到5月31日（周日）中午12：00，请各位毕业生积极报名，及时完成问卷确认。",
        )

        result = harness.handle_待办(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "archived")
        self.assertIn("已拆出层级结构", result.reply)
        self.assertEqual(harness.content_flow_client.calls[0]["profile_name"], "daily_hierarchy_records_extraction")
        self.assertEqual(len(harness.content_flow_client.calls), 1)
        self.assertEqual([call["kind"] for call in harness.reminder_service.calls], ["日程", "日程", "待办"])
        parent_call, schedule_call, todo_call = harness.reminder_service.calls
        self.assertEqual(parent_call["title"], "清华大学深圳国际研究生院2026年毕业典礼")
        self.assertEqual(parent_call["due_at"].strftime("%y%m%d %H:%M"), "260626 10:00")
        self.assertEqual(parent_call["remind_at"].strftime("%y%m%d %H:%M"), "260626 09:00")
        self.assertNotIn("活动时间", parent_call["extra_fields"])
        self.assertNotIn("活动开始时间", parent_call["extra_fields"])
        self.assertNotIn("活动结束时间", parent_call["extra_fields"])
        self.assertEqual(parent_call["extra_fields"]["地点"], "广东省 深圳市 大学城 深圳大学城国际会议中心 千人礼堂")
        self.assertIn("类型说明", parent_call["extra_fields"])
        self.assertNotIn("未填写原因", parent_call["extra_fields"])
        self.assertNotIn("需人工补充", parent_call["extra_fields"])
        self.assertNotIn("地点拆解JSON", parent_call["extra_fields"])
        self.assertNotIn("Brief链接", parent_call["extra_fields"])
        self.assertNotIn("返稿链接", parent_call["extra_fields"])
        self.assertNotIn("主状态", parent_call["extra_fields"])
        self.assertFalse(parent_call["omit_management_fields"])
        self.assertIsNone(parent_call["config_path_key"])
        self.assertNotIn("记录类型", parent_call["extra_fields"])
        self.assertNotIn("状态", parent_call["extra_fields"])
        self.assertNotIn("优先级", parent_call["extra_fields"])
        self.assertEqual(schedule_call["due_at"].strftime("%y%m%d %H:%M"), "260626 10:00")
        self.assertEqual(schedule_call["remind_at"].strftime("%y%m%d %H:%M"), "260626 09:00")
        self.assertTrue(schedule_call["omit_management_fields"])
        self.assertEqual(schedule_call["extra_fields"]["父记录"], "rec-test")
        self.assertEqual(schedule_call["extra_fields"]["地点"], "广东省 深圳市 大学城 深圳大学城国际会议中心 千人礼堂")
        self.assertNotIn("详情JSON", schedule_call["extra_fields"])
        self.assertNotIn("地点拆解JSON", schedule_call["extra_fields"])
        self.assertNotIn("记录类型", schedule_call["extra_fields"])
        self.assertNotIn("状态", schedule_call["extra_fields"])
        self.assertNotIn("优先级", schedule_call["extra_fields"])
        self.assertEqual(todo_call["due_at"].strftime("%y%m%d %H:%M"), "260531 12:00")
        self.assertEqual(todo_call["remind_at"].strftime("%y%m%d %H:%M"), "260531 11:30")
        self.assertTrue(todo_call["omit_management_fields"])
        self.assertEqual(todo_call["extra_fields"]["父记录"], "rec-test")
        self.assertNotIn("详情JSON", todo_call["extra_fields"])
        self.assertNotIn("记录类型", todo_call["extra_fields"])
        self.assertNotIn("状态", todo_call["extra_fields"])
        self.assertNotIn("优先级", todo_call["extra_fields"])

    def test_hierarchy_child_location_parts_are_required_for_bare_venue(self) -> None:
        harness = DailyHarness(
            {
                "status": "hierarchy",
                "confidence": 0.92,
                "parent": {
                    "title": "参加研究生毕业典礼及学位授予仪式",
                    "summary": "包括毕业典礼和学位授予仪式两个环节。",
                    "fields": {"活动开始时间": "2026-06-28", "活动结束时间": "2026-06-28"},
                },
                "children": [
                    {
                        "type": "日程",
                        "title": "参加研究生学位授予仪式",
                        "due_at": "2026-06-28T09:00:00+08:00",
                        "location": "综合体育馆",
                        "location_parts": {},
                        "fields": {"说明": "参加研究生学位授予仪式。"},
                    }
                ],
                "missing_fields": [],
                "evidence": "09:00 综合体育馆学位授予仪式",
            }
        )
        message = make_message(
            "日程",
            "参加研究生毕业典礼及学位授予仪式。\n\n"
            "一、整体安排：2026届研究生毕业典礼及学位授予仪式分两个环节举行。\n"
            "二、毕业典礼：2026-06-28 08:00，在东大操场参加毕业典礼。\n"
            "三、学位授予仪式：2026-06-28 09:00，在综合体育馆参加学位授予仪式。\n"
            "备注：两个环节都需要提前到场，地点字段必须写成省市区加具体地点。",
        )

        result = harness.handle_日程(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "parser_error")
        self.assertIn("children[1].location_parts", result.reply)
        self.assertEqual(harness.reminder_service.calls, [])

    def test_hierarchy_child_location_formats_tsinghua_gymnasium(self) -> None:
        harness = DailyHarness(
            {
                "status": "hierarchy",
                "confidence": 0.92,
                "parent": {
                    "title": "参加研究生毕业典礼及学位授予仪式",
                    "summary": "包括毕业典礼和学位授予仪式两个环节。",
                    "fields": {"活动开始时间": "2026-06-28", "活动结束时间": "2026-06-28"},
                },
                "children": [
                    {
                        "type": "日程",
                        "title": "参加研究生学位授予仪式",
                        "due_at": "2026-06-28T09:00:00+08:00",
                        "location": "综合体育馆",
                        "location_parts": {
                            "城市": "北京",
                            "区域": "海淀区",
                            "校区/园区": "清华大学",
                            "场馆": "综合体育馆",
                        },
                        "fields": {"说明": "参加研究生学位授予仪式。"},
                    }
                ],
                "missing_fields": [],
                "evidence": "09:00 综合体育馆学位授予仪式",
            }
        )
        message = make_message(
            "日程",
            "参加研究生毕业典礼及学位授予仪式。\n\n"
            "一、整体安排：2026届研究生毕业典礼及学位授予仪式分两个环节举行。\n"
            "二、毕业典礼：2026-06-28 08:00，在东大操场参加毕业典礼。\n"
            "三、学位授予仪式：2026-06-28 09:00，在综合体育馆参加学位授予仪式。\n"
            "备注：两个环节都需要提前到场，地点字段必须写成省市区加具体地点。",
        )

        result = harness.handle_日程(message)

        self.assertTrue(result.ok)
        _parent_call, child_call = harness.reminder_service.calls
        self.assertEqual(child_call["extra_fields"]["地点"], "北京市 海淀区 清华大学 综合体育馆")

    def test_low_confidence_or_missing_time_does_not_create_reminder(self) -> None:
        harness = DailyHarness(
            [
                {
                    "mode": "reminder_backed",
                    "items": [],
                    "confidence": 0.9,
                    "missing_fields": [],
                    "evidence": "到时候提醒我",
                    "reason": "用户要求提醒但时间不明确",
                },
                {
                    "type": "待办",
                    "title": "毕业典礼报名",
                    "due_at": "",
                    "remind_at": "",
                    "confidence": 0.45,
                    "missing_fields": ["due_at"],
                    "evidence": "毕业典礼报名",
                    "reason": "没有明确日期和时间",
                },
            ]
        )
        message = make_message("待办", "毕业典礼报名到时候提醒我。")

        result = harness.handle_待办(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "pending_time_confirmation")
        self.assertIn("待办没有创建", result.reply)
        self.assertEqual(harness.archive_service.calls, [])
        self.assertEqual(harness.reminder_service.calls, [])


if __name__ == "__main__":
    unittest.main()
