from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.creation.adapters import ActivityAdapter, BusinessAdapter, CreationInspirationAdapter, ViralContentAdapter
from tools.creation.matcher import rank_activities, rank_businesses, rank_virals
from tools.creation.platform_fit import (
    fallback_platform_mechanism_fit,
    generate_platform_mechanism_fit,
    load_platform_mechanism_config,
    parse_platform_mechanism_note,
    validate_platform_mechanism_fit_payload,
)
from tools.creation.platform_validator import validate_platform_draft
from tools.creation.request_inference import parse_creation_request_with_llm
from tools.creation.request_parser import CreationRequest, parse_creation_request
from tools.creation.workflow import handle_creation_command


class CreationV1Tests(unittest.TestCase):
    def test_parse_type_as_content_type(self) -> None:
        req = parse_creation_request(
            "【创作-小红书】赛道=职场成长 类型=图文 主体=表达力 发布时间=今晚8点 品牌=某品牌",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertEqual(req.platform, "小红书")
        self.assertEqual(req.content_type, "图文")
        self.assertEqual(req.track, "职场成长")
        self.assertEqual(req.topic, "表达力")
        self.assertEqual(req.brand, "某品牌")
        self.assertIn("20:00", req.publish_time)

    def test_missing_fields_use_llm_inference(self) -> None:
        with patch(
            "tools.creation.request_inference._call_openclaw_json",
            return_value={
                "platform": "小红书",
                "content_type": "图文",
                "track": "职场成长",
                "topic": "表达力",
                "keywords": ["职场成长", "表达力"],
            },
        ) as infer:
            req = parse_creation_request_with_llm(
                "【创作】小红书 赛道=职场成长 主体=表达力 发布时间=今晚8点",
                now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            )
        self.assertTrue(infer.called)
        self.assertEqual(req.platform, "小红书")
        self.assertEqual(req.content_type, "图文")
        self.assertEqual(req.track, "职场成长")

    def test_llm_failure_surfaces_directly(self) -> None:
        with patch("tools.creation.request_inference._call_openclaw_json", side_effect=RuntimeError("llm unavailable")):
            with self.assertRaisesRegex(RuntimeError, "llm unavailable"):
                parse_creation_request_with_llm(
                    "【创作】小红书 赛道=职场成长 主体=表达力 发布时间=今晚8点",
                    now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                )

    def test_llm_infers_freeform_creation_request_fields(self) -> None:
        with patch(
            "tools.creation.request_inference._call_openclaw_json",
            return_value={
                "platform": "抖音",
                "content_type": "视频",
                "track": "体育",
                "topic": "100米/400米比赛本身",
                "user_idea": "开头0.5秒必须让观众看懂是在比赛，素材只放检录、起跑、冲刺、喘气、成绩或赛后反应。",
                "keywords": ["田径", "100米", "400米", "比赛"],
            },
        ) as infer:
            req = parse_creation_request_with_llm(
                "【创作】请对于https://tcnwueberajc.feishu.cn/wiki/K4mTwUL40itnKmkf26Wcisoqn8c中比赛篇 "
                "主题聚焦100米/400米比赛本身。开头0.5秒必须让观众看懂是在比赛，字幕可写：毕业后，我又站上了大学的跑道。",
                now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            )
        self.assertTrue(infer.called)
        self.assertEqual(req.platform, "抖音")
        self.assertEqual(req.content_type, "视频")
        self.assertEqual(req.track, "体育")
        self.assertEqual(req.topic, "100米/400米比赛本身")
        self.assertIn("100米", req.keywords or [])

    def test_adapters_map_fields_to_canonical_record(self) -> None:
        viral = ViralContentAdapter().to_record(
            {
                "record_id": "rec1",
                "fields": {
                    "原标题": "嘴笨女生表达力",
                    "平台": "小红书",
                    "内容类型": "图文",
                    "赛道": "职场成长",
                    "主题": "表达力",
                    "赛道/标签": "表达力、职场",
                    "拆解文档链接": {"text": "拆解文档", "link": "https://tcnwueberajc.feishu.cn/docx/doc1"},
                },
            }
        )
        self.assertEqual(viral.record_type, "爆款样本")
        self.assertEqual(viral.title, "嘴笨女生表达力")
        self.assertEqual(viral.doc_links["decomposition"], "https://tcnwueberajc.feishu.cn/docx/doc1")
        self.assertIn("表达力", viral.tags)

        activity = ActivityAdapter().to_record(
            {
                "record_id": "act1",
                "fields": {
                    "标题": "成长活动",
                    "平台名称": "小红书",
                    "内容类型要求": "不限",
                    "赛道": "职场成长",
                    "主话题": "#表达力",
                    "投稿截止时间": 1778428800000,
                },
            }
        )
        self.assertEqual(activity.platform, "小红书")
        self.assertEqual(activity.content_type_requirement, "不限")
        self.assertEqual(activity.topic, "#表达力")
        self.assertTrue(activity.deadline)

        inspiration = CreationInspirationAdapter().to_record(
            {
                "record_id": "ins1",
                "fields": {
                    "标题": "被质疑后的表达力反思",
                    "记录类型": "创作记录",
                    "内容": "一次被质疑后的复盘，可以写成表达力素材。",
                    "平台": "小红书",
                    "内容类型": "图文",
                    "赛道": "职场成长",
                    "主题": "表达力",
                    "关键词标签": "创作-灵感、表达力",
                    "核心观点": "被质疑时先复盘错位点，再提炼观点。",
                    "素材来源类型": "对话",
                    "素材信号类型": "不舒服",
                    "可复用角度": "个人故事、复盘、方法论",
                },
            }
        )
        self.assertEqual(inspiration.record_type, "创作灵感")
        self.assertEqual(inspiration.source_record_id, "ins1")
        self.assertEqual(inspiration.core_value, "被质疑时先复盘错位点，再提炼观点。")
        self.assertIn("表达力", inspiration.tags)

    def test_activity_and_viral_ranking_are_separate(self) -> None:
        req = parse_creation_request(
            "【创作-小红书】赛道=职场成长 类型=图文 主体=表达力 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        activity = ActivityAdapter().to_record(
            {
                "record_id": "act1",
                "fields": {
                    "标题": "表达力活动",
                    "平台": "小红书",
                    "内容类型要求": "不限",
                    "赛道": "职场成长",
                    "主题": "表达力",
                    "状态": "进行中",
                    "活动开始时间": "2026-05-01 00:00",
                    "投稿截止时间": "2026-05-20 23:59",
                    "活动级别": "A",
                },
            }
        )
        viral = ViralContentAdapter().to_record(
            {
                "record_id": "vir1",
                "fields": {
                    "原标题": "表达力爆款",
                    "平台": "小红书",
                    "内容类型": "图文",
                    "赛道": "职场成长",
                    "主题": "表达力",
                    "核心数据": "点赞 10000",
                    "拆解文档链接": "https://tcnwueberajc.feishu.cn/docx/doc1",
                },
            }
        )
        self.assertGreater(rank_activities([activity], req)[0].score, 0)
        self.assertGreater(rank_virals([viral], req)[0].score, 0)

    def test_business_adapter_and_ranking_require_business_context(self) -> None:
        business = BusinessAdapter().to_record(
            {
                "record_id": "biz1",
                "fields": {
                    "作者ID": "小王",
                    "账号名称": "小王成长号",
                    "平台": "小红书",
                    "品牌": "某品牌",
                    "产品": "表达力课程",
                    "项目": "5月种草",
                    "Brief链接": {"text": "brief", "link": "https://example.com/brief"},
                    "主页链接": "https://example.com/home",
                    "图文报价": "8000",
                    "给品牌方信息": "适合图文合作",
                },
            }
        )
        self.assertEqual(business.record_type, "商务")
        self.assertEqual(business.content_type_requirement, "图文")
        self.assertEqual(business.doc_links["brief"], "https://example.com/brief")

        no_business_req = parse_creation_request(
            "【创作-小红书】赛道=职场成长 类型=图文 主体=表达力 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertEqual(rank_businesses([business], no_business_req), [])

        business_req = parse_creation_request(
            "【创作-小红书】赛道=职场成长 类型=图文 主体=表达力 发布时间=2026-05-10 20:00 品牌=某品牌 产品=表达力课程",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        ranked = rank_businesses([business], business_req)
        self.assertEqual(ranked[0].record.source_record_id, "biz1")
        self.assertIn("品牌匹配", ranked[0].reasons)

    def test_platform_validation(self) -> None:
        xhs = validate_platform_draft(
            "小红书",
            "图文",
            {"title": "嘴笨女生这样练", "tags": [str(i) for i in range(10)], "image_script": ["封面"]},
        )
        self.assertTrue(xhs.ok)
        douyin = validate_platform_draft(
            "抖音",
            "视频",
            {
                "title": "孩子拖延写作业",
                "tags": ["亲子", "教育", "拖延", "作业", "方法"],
                "hook_3s": "先别催",
                "storyboard": [{"scene": "开头"}],
                "voiceover": "先拆场景",
                "subtitles": ["先别催"],
            },
        )
        self.assertTrue(douyin.ok)

    def test_platform_mechanism_fit_baseline_is_creation_stage_strategy(self) -> None:
        req = parse_creation_request(
            "【创作-小红书】赛道=职场 类型=图文 主体=表达力 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        fit = fallback_platform_mechanism_fit(
            req,
            activity_candidates=[{"id": "act1", "title": "表达力活动"}],
            viral_candidates=[{"id": "vir1", "title": "表达力爆款"}],
            inspiration_candidates=[{"id": "ins1", "title": "真实表达卡住"}],
            business_candidates=[],
            reference_docs=[],
            media_context={"recent_reviews": [{"title": "表达力复盘"}], "loaded": {"account_profile": 1}},
        )

        self.assertTrue(fit["platform_mechanism_version"].startswith("xiaohongshu_"))
        self.assertIn("不是平台真实算法", fit["mechanism_claim_boundary"])
        self.assertIn("platform_strategy", fit)
        self.assertIn("activity_strategy", fit)
        self.assertIn("creation_reverse_plan", fit)
        self.assertIn("validation_targets", fit)
        self.assertIn("act1", fit["activity_strategy"]["candidate_activity_ids"])
        self.assertEqual(fit["activity_strategy"]["hard_fit_risk"], "low")
        self.assertTrue(fit["activity_strategy"]["natural_fit"])
        self.assertEqual(fit["platform_fit_meta"]["fallback_used"], True)
        self.assertEqual(fit["platform_fit_meta"]["mechanism_version"], "xiaohongshu_2026_05_v1")
        self.assertEqual(fit["platform_fit_meta"]["mechanism_source"], "config")
        self.assertIn("mechanism_config", fit["platform_fit_meta"]["fit_source"])
        self.assertIn("activity_table", fit["platform_fit_meta"]["fit_source"])
        self.assertIn("review_data", fit["platform_fit_meta"]["fit_source"])

    def test_platform_mechanism_config_is_preferred_when_present(self) -> None:
        config = load_platform_mechanism_config("小红书")
        self.assertEqual(config["mechanism_version"], "xiaohongshu_2026_05_v1")

        req = parse_creation_request(
            "【创作-小红书】赛道=自媒体 类型=图文 主体=选题方法 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        fit = fallback_platform_mechanism_fit(req, media_context={})
        self.assertEqual(fit["platform_mechanism_version"], "xiaohongshu_2026_05_v1")
        self.assertEqual(fit["mechanism_source"], "config")
        self.assertEqual(fit["platform_fit_meta"]["mechanism_source"], "config")

    def test_platform_mechanism_fit_falls_back_when_llm_fails(self) -> None:
        req = parse_creation_request(
            "【创作-小红书】赛道=职场 类型=图文 主体=表达力 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        with patch("tools.creation.platform_fit._call_openclaw_json", side_effect=RuntimeError("llm_json_parse_failed")):
            fit = generate_platform_mechanism_fit(
                req,
                activity_candidates=[],
                viral_candidates=[],
                inspiration_candidates=[],
                business_candidates=[],
                reference_docs=[],
                media_context={},
            )

        self.assertTrue(fit["platform_fit_meta"]["fallback_used"])
        self.assertEqual(fit["platform_fit_meta"]["fallback_reason"], "llm_json_parse_failed")
        self.assertEqual(fit["generation"]["provider"], "deterministic_baseline")

    def test_platform_mechanism_fit_unknown_platform_uses_generic_baseline(self) -> None:
        req = CreationRequest(
            platform="公众号",
            content_type="图文",
            track="自媒体",
            topic="选题方法",
            publish_time="",
            keywords=["自媒体", "选题"],
        )
        fit = fallback_platform_mechanism_fit(req, media_context={})

        self.assertTrue(fit["platform_mechanism_version"].startswith("platform_"))
        self.assertEqual(fit["platform_fit_meta"]["mechanism_source"], "fallback")
        self.assertIn("platform_strategy", fit)
        self.assertTrue(fit["validation_targets"]["two_hour"])

    def test_platform_mechanism_fit_no_activity_does_not_force_activity(self) -> None:
        req = parse_creation_request(
            "【创作-小红书】赛道=自媒体 类型=图文 主体=选题方法 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        fit = fallback_platform_mechanism_fit(req, activity_candidates=[], media_context={})
        activity_strategy = fit["activity_strategy"]

        self.assertFalse(activity_strategy["natural_fit"])
        self.assertEqual(activity_strategy["hard_fit_risk"], "low")
        self.assertEqual(activity_strategy["matched_activities"], [])
        self.assertIn("不要为了活动流量临时改写主题。", activity_strategy["do_not_force"])

    def test_platform_mechanism_fit_rejects_algorithm_myth_claims(self) -> None:
        req = parse_creation_request(
            "【创作-小红书】赛道=自媒体 类型=图文 主体=选题方法 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        fallback = fallback_platform_mechanism_fit(req, media_context={})
        payload = {
            "platform_mechanism_version": fallback["platform_mechanism_version"],
            "mechanism_claim_boundary": "这是机制拟合假设，不是平台真实算法或权重结论。",
            "mechanism_evidence_level": "C",
            "source_weights": {},
            "platform_strategy": {"summary": "保证爆款"},
            "activity_strategy": fallback["activity_strategy"],
            "traffic_hypothesis": fallback["traffic_hypothesis"],
            "creation_reverse_plan": fallback["creation_reverse_plan"],
            "validation_targets": fallback["validation_targets"],
            "post_publish_correction": fallback["post_publish_correction"],
            "risks_or_missing_info": [],
        }
        with self.assertRaisesRegex(ValueError, "算法神化"):
            validate_platform_mechanism_fit_payload(payload, req, fallback=fallback)

    def test_parse_platform_mechanism_note_defaults_creator_test_to_c_level(self) -> None:
        parsed = parse_platform_mechanism_note(
            "小红书",
            "知识型图文更依赖收藏理由和搜索长尾，前两页要给收藏理由。",
            source_type="creator_test",
            use_llm=False,
        )

        self.assertEqual(parsed["source_type"], "creator_test")
        self.assertEqual(parsed["evidence_level"], "C")
        self.assertEqual(parsed["hypotheses"][0]["evidence_level"], "C")
        self.assertIn("收藏率", parsed["hypotheses"][0]["validation_metrics"])
        self.assertIn("搜索来源占比", parsed["hypotheses"][0]["validation_metrics"])
        self.assertEqual(parsed["hypotheses"][0]["status"], "candidate")

    def test_platform_mechanism_observation_can_persist_and_feed_fit(self) -> None:
        req = parse_creation_request(
            "【创作-小红书】赛道=自媒体 类型=图文 主体=选题方法 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"SELFMEDIA_PLATFORM_MECHANISM_CONFIG_DIR": tmp}):
                parsed = parse_platform_mechanism_note(
                    "小红书",
                    "知识型图文更依赖收藏理由和搜索长尾。",
                    source_type="creator_test",
                    persist=True,
                    use_llm=False,
                )
                fit = fallback_platform_mechanism_fit(req, media_context={})

        observed = fit["platform_strategy"]["mechanism_observation_hypotheses"]
        self.assertEqual(parsed["evidence_level"], "C")
        self.assertTrue(observed)
        self.assertEqual(observed[0]["evidence_level"], "C")
        self.assertIn("mechanism_observation_actions", fit["creation_reverse_plan"])

    def test_creation_workflow_uses_llm_draft_without_template_fallback(self) -> None:
        platform_fit = {
            "platform_mechanism_version": "xiaohongshu_2026_05_v1",
            "mechanism_claim_boundary": "这是机制拟合假设，不是平台真实算法或权重结论。",
            "platform_fit_meta": {
                "mechanism_version": "xiaohongshu_2026_05_v1",
                "fallback_used": False,
                "fit_source": ["llm", "activity_table", "hot_content_table"],
                "confidence": "medium",
                "evidence_level": "B",
                "generated_at": "2026-05-23T00:00:00+08:00",
            },
            "platform_strategy": {"fit_summary": "封面点击、收藏和评论要明确设计"},
            "activity_strategy": {"fit": "活动自然适配", "hard_fit_risk": "low"},
            "traffic_hypothesis": {"click_reason": "真实会议场景"},
            "creation_reverse_plan": {"title": ["写具体场景"]},
            "validation_targets": {"two_hour": ["看收藏和评论"]},
        }
        llm_draft = {
            "platform": "小红书",
            "content_type": "图文",
            "title": "表达力这样练",
            "tags": ["小红书", "职场", "表达力", "沟通", "成长", "干货", "方法", "练习", "行动", "复盘"],
            "topic": "表达力",
            "final_copy": "用一个真实会议场景开头，再拆三个表达动作。",
            "inspiration": ["LLM 选择活动与爆款后生成，不使用模板兜底。"],
            "activity_constraint": {"matched": True},
            "viral_reference": {"matched": True},
            "business_reference": {"matched": False},
            "account_context": {"used": True},
            "positioning_analysis": {"positioning": "职场表达练习"},
            "platform_strategy": {"fit_summary": "封面点击、收藏和评论要明确设计"},
            "activity_strategy": {"fit": "活动自然适配"},
            "traffic_hypothesis": {"click_reason": "真实会议场景"},
            "creation_reverse_plan": {"title": ["写具体场景"]},
            "validation_targets": {"two_hour": ["看收藏和评论"]},
            "selected_activity_ids": ["act1"],
            "selected_viral_ids": ["vir1"],
            "selected_inspiration_ids": ["ins1"],
            "selected_business_ids": [],
            "image_script": ["封面：表达力卡住的真实瞬间", "第1页：会议发言前的心理动作"],
            "carousel": ["封面：表达力卡住的真实瞬间", "第1页：会议发言前的心理动作"],
            "hook_3s": "",
            "storyboard": [],
            "voiceover": "",
            "subtitles": [],
            "production_checklist": ["准备一个真实会议例子"],
            "review_plan": ["发布后 2 小时看收藏和评论问题"],
            "risks_or_missing_info": [],
        }
        with (
            patch("tools.creation.workflow.load_rows_for_creation") as load_rows,
            patch("tools.creation.workflow.load_business_rows_for_creation", return_value=[]),
            patch("tools.creation.workflow.load_inspiration_rows_for_creation") as load_inspirations,
            patch("tools.creation.workflow.read_reference_docs", return_value=[]),
            patch("tools.creation.workflow.generate_platform_mechanism_fit", return_value=platform_fit) as fit_generator,
            patch("tools.creation.workflow.generate_openclaw_creation_draft", return_value=llm_draft) as generate,
        ):
            load_rows.return_value = (
                [
                    {
                        "record_id": "vir1",
                        "fields": {
                            "原标题": "表达力爆款",
                            "平台": "小红书",
                            "内容类型": "图文",
                            "赛道": "职场",
                            "主题": "表达力",
                        },
                    }
                ],
                [
                    {
                        "record_id": "act1",
                        "fields": {
                            "标题": "表达力活动",
                            "平台": "小红书",
                            "内容类型要求": "不限",
                            "赛道": "职场",
                            "主题": "表达力",
                        },
                    }
                ],
            )
            load_inspirations.return_value = [
                {
                    "record_id": "ins1",
                    "fields": {
                        "标题": "表达力灵感",
                        "平台": "小红书",
                        "内容类型": "图文",
                        "赛道": "职场",
                        "主题": "表达力",
                        "内容": "一次真实表达卡住后的复盘。",
                    },
                }
            ]
            result = handle_creation_command(
                "【创作-小红书】赛道=职场 类型=图文 主体=表达力 账号=主账号 发布时间=今晚8点",
                no_write=True,
            )
        self.assertTrue(generate.called)
        self.assertTrue(fit_generator.called)
        self.assertEqual(result["generation_mode"], "openclaw_llm_first")
        self.assertEqual(result["platform_fit"]["platform_mechanism_version"], "xiaohongshu_2026_05_v1")
        self.assertEqual(generate.call_args.kwargs["platform_fit"]["platform_strategy"]["fit_summary"], "封面点击、收藏和评论要明确设计")
        self.assertEqual(result["draft"]["title"], "表达力这样练")
        self.assertEqual(result["activities"][0]["source_record_id"], "act1")
        self.assertEqual(result["virals"][0]["source_record_id"], "vir1")
        self.assertEqual(result["inspirations"][0]["source_record_id"], "ins1")


if __name__ == "__main__":
    unittest.main()
