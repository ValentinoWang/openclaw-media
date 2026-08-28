from __future__ import annotations

import sys
import tempfile
import unittest
import inspect
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from selfmedia.creation.adapters import ActivityAdapter, BusinessAdapter, CreationInspirationAdapter, ViralContentAdapter
from selfmedia.creation import backwash
from selfmedia.creation.field_contract import CREATION_OUTPUT_TABLE_CONTRACT, CREATION_SOURCE_TABLE_CONTRACTS, CanonicalMediaRecord
from selfmedia.creation.matcher import RankedRecord, rank_activities, rank_businesses, rank_inspirations, rank_virals
from selfmedia.creation.platform_fit import (
    generate_platform_mechanism_fit,
    load_platform_mechanism_config,
    parse_platform_mechanism_note,
    validate_platform_mechanism_fit_payload,
)
from selfmedia.creation.platform_validator import validate_platform_draft
from selfmedia.creation.llm_generator import CREATOR_BRIEF_REPORT_MODE, build_creation_prompt, validate_llm_draft_payload
from selfmedia.creation.request_inference import parse_creation_request_with_llm
from selfmedia.creation.request_parser import CreationRequest, parse_creation_request
from selfmedia.creation.shooting_execution import (
    ShootingExecutionRequest,
    generate_shooting_execution_plan,
    parse_shooting_execution_request,
)
from selfmedia.creation.consultation import handle_creation_consultation_command, parse_consultation_request, request_needs_activity_candidates
from selfmedia.creation.workflow import _deconstruct_activity_example_links, _record_candidate_payload, _run_viral_deconstruct, handle_creation_command
from selfmedia.creation.writer import _creation_doc_blocks, _find_wiki_child_doc, _shooting_execution_doc_blocks
from media_vault.vault import MediaVault


class _JsonResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


def _write_deconstruction_v2_artifact(root: Path, deconstruction_id: str = "vir1") -> str:
    vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=root)
    artifact = {
        "schema_version": "deconstruction.v2",
        "deconstruction_id": deconstruction_id,
        "source_asset_id": "asset1",
        "created_at": "2026-06-27T00:00:00Z",
        "model_info": {"deconstruction_model": "test"},
        "evidence_manifest": {
            "frame_001": {"type": "visual", "asset_id": "frame_001"},
            "asr_001": {"type": "speech", "segment_id": "asr_001", "text": "表达力卡住的真实瞬间。"},
            "ocr_001": {"type": "ocr", "text_segment_id": "ocr_001", "text": "表达力这样练"},
        },
        "speech_transcript": {"status": "success", "full_text": "表达力卡住的真实瞬间。"},
        "speech_timeline": [{"segment_id": "asr_001", "start": 0.0, "end": 2.0, "text": "表达力卡住的真实瞬间。"}],
        "visible_text_segments": [{"text_segment_id": "ocr_001", "asset_id": "frame_001", "text": "表达力这样练"}],
        "content_summary": {"summary": "职场表达力真实复盘。", "viral_mechanism": "真实卡点前置，给出可执行练习。"},
        "viral_reuse_assessment": {
            "observed_virality": {"level": "unknown", "reason": "测试数据无平台指标"},
            "mechanism_strength": {"level": "strong", "reason": "真实会议卡点和练习承诺明确", "evidence_ids": ["asr_001", "ocr_001"]},
            "account_fit": {"level": "high", "reason": "适合职场表达账号"},
            "production_feasibility": {"level": "easy", "reason": "可用真实会议场景复拍"},
            "reuse_risk": {"level": "medium", "reason": "必须重写原开头文案"},
            "final_label": "strong_reuse_candidate",
            "confidence": 0.82,
            "human_review_required": True,
        },
        "pacing_profile": {
            "python_facts": {"duration_sec": 30.0, "opening_3s_frame_change_score": 0.7},
            "llm_interpretation": {"edit_recommendations": ["前 3 秒保留真实卡点和练习承诺"]},
        },
        "reuse_guardrails": {
            "allowed_reuse": [{"item": "真实卡点前置结构", "reuse_level": "structure", "evidence_ids": ["asr_001"]}],
            "required_transformations": [{"source_part": "开头文案", "required_change": "改成当前账号自己的会议经历"}],
            "prohibited_reuse": [{"element": "原视频原句", "reason": "表达复制风险"}],
            "own_account_mapping": {"own_persona": "职场表达账号"},
            "similarity_risk": {"overall": "medium"},
            "originality_requirements": ["必须加入自己的真实会议素材"],
            "human_review_required": True,
        },
        "human_readable_brief": {"recommended_script_directions": ["用自己的会议卡点改写"]},
        "validation": {"warnings": []},
    }
    written = vault.write_json_artifact(
        vault.deconstruction_dir(deconstruction_id),
        "deconstruction.json",
        artifact,
        owner_type="MaterialDeconstruction",
        owner_id=deconstruction_id,
        artifact_type="material_deconstruction",
    )
    return str(written["uri"])


def _score_breakdown(score: int) -> dict[str, int]:
    limits = {
        "evidence_grounding": 20,
        "platform_fit": 15,
        "audience_pain": 15,
        "creative_angle": 15,
        "execution_completeness": 15,
        "reference_integration": 15,
        "risk_control": 5,
    }
    remaining = score
    breakdown: dict[str, int] = {}
    for key, limit in limits.items():
        value = min(limit, max(remaining, 0))
        breakdown[key] = value
        remaining -= value
    return breakdown


def _script_option(option_id: str = "opt_1", *, score: int = 94, activity_id: str = "act1", viral_id: str = "vir1", inspiration_id: str = "ins1") -> dict[str, object]:
    return {
        "option_id": option_id,
        "score": score,
        "score_breakdown": _score_breakdown(score),
        "title": "毕业后再上跑道",
        "angle": "把毕业季身份转变和田径比赛起跑前 0.5 秒结合。",
        "score_reason": "活动承接自然，运动画面明确，脚本可执行。",
        "selected_activity_ids": [activity_id] if activity_id else [],
        "selected_viral_ids": [viral_id] if viral_id else [],
        "selected_inspiration_ids": [inspiration_id] if inspiration_id else [],
        "selected_business_ids": [],
        "activity_fit_reason": "毕业季活动需要真实经历，本稿能从赛场告别切入。",
        "viral_reference_reason": "只迁移开头冲突和节奏。",
        "inspiration_reference_reason": "使用田径比赛和身份转变的真实场景。",
        "risk_level": "low",
        "risks_or_missing_info": [],
        "tags": ["田径", "毕业季", "高考", "体育", "成长"],
        "final_copy": "毕业不是离开跑道，是换一种身份继续起跑。",
        "image_script": [],
        "carousel": [],
        "hook_3s": "毕业后，我又站上了跑道。",
        "storyboard": [{"scene": "起跑前 0.5 秒", "visual": "发令前压低身体", "subtitle": "毕业后，我又站上了跑道"}],
        "voiceover": "发令枪响之前，我才意识到毕业不是告别赛场。",
        "subtitles": ["毕业后，我又站上了跑道", "不是告别，是换一种身份起跑"],
        "production_checklist": ["准备起跑、冲刺、成绩画面"],
        "review_plan": ["发布后看完播率和毕业季评论问题"],
    }


def _creator_report() -> dict[str, object]:
    return {
        "overview": {
            "recommended_topic": "毕业前后，我又站上了 100 米起点",
            "core_sentence": "毕业不是告别赛场，只是换一种身份继续跑。",
            "platform": "抖音",
            "content_type": "视频",
            "suitable_activity": "毕业季活动；推荐子方向：#那就好好告个别吧",
            "strongly_recommend_activity": "建议参与，但只挂一个自然贴合的毕业季子方向。",
            "biggest_risk": "成绩和计时牌不清晰时不能写死跑进 11 秒。",
        },
        "opening_3s": {
            "visual_0_0_5": "直接给起跑或冲线动作。",
            "caption_or_voice_0_5_3": "毕业前后，我又站上了 100 米起点。",
            "do_not_open_like_this": "不要先列活动、爆款和数据库匹配理由。",
        },
        "mainline": {
            "conflict": "毕业身份转换和赛场重新起跑之间的拉扯。",
            "evidence": "号码布、钉鞋、检录、起跑、冲线或成绩画面。",
            "emotional_payoff": "毕业不是告别赛场，只是换一种身份继续跑。",
            "audience_resonance": "每个毕业的人都在确认自己还能不能继续热爱原来的事。",
        },
        "storyboard": [
            {
                "time": "0-0.5s",
                "visual": "起跑或冲线动作",
                "subtitle": "毕业前后，我又站上了 100 米起点。",
                "sound": "现场声",
                "shooting_note": "画面先于解释出现。",
            }
        ],
        "publishing_pack": {
            "title_1": "毕业前后，我又站上了100米起点",
            "title_2": "清华研究生还能跑回11秒吗",
            "cover_text": "毕业后还能跑回11秒吗",
            "body_copy": "毕业不是告别赛场，只是换一种身份继续跑。",
            "hashtags": ["毕业季", "田径", "100米", "清华研究生", "青春"],
            "pinned_comment": "你毕业后还保留了哪件热爱的事？",
            "comment_prompt": "你觉得毕业是一场告别，还是一次重新起跑？",
            "first_hour_action": "发布后置顶提问，1 小时内优先回复前 3 条具体经历，并持续回复前十条有效评论，观察评论是否围绕毕业与坚持。",
        },
        "material_checklist": {
            "must_have": ["起跑", "冲刺", "成绩或赛后反应"],
            "better_to_have": ["号码布", "钉鞋", "检录"],
            "can_rescue_without": ["没有计时牌就改成冲击 11 秒"],
            "must_not_fabricate": ["不能虚构成绩", "不能虚构活动要求"],
        },
        "risk_controls": [
            {"condition": "如果成绩没有跑进 11 秒", "rewrite_or_action": "文案改成接近 11 秒或想跑回 11 秒。"},
            {"condition": "如果没有清晰计时牌", "rewrite_or_action": "用赛后反应和跑道动作承接，不写死成绩。"},
        ],
        "evidence_appendix": {
            "activities": [],
            "viral_refs": [],
            "inspiration_refs": [],
            "business_info": "无商务信息。",
            "scoring_and_record_ids": [],
        },
    }


def _multi_option_payload(options: list[dict[str, object]], recommended: str = "opt_1") -> dict[str, object]:
    viral_ids = sorted({str(item) for option in options for item in option.get("selected_viral_ids", []) if str(item)})
    inspiration_ids = sorted({str(item) for option in options for item in option.get("selected_inspiration_ids", []) if str(item)})
    return {
        "platform": "抖音",
        "content_type": "视频",
        "topic": "西安田径分区邀请赛",
        "inspiration": ["从候选中生成多个高分方案。"],
        "activity_constraint": {"matched": True},
        "viral_reference": {"matched": True},
        "inspiration_reference": {"matched": True},
        "business_reference": {"matched": False},
        "account_context": {"used": False},
        "positioning_analysis": {"positioning": "体育毕业季表达"},
        "content_core": {
            "content_promise": "用一场 100 米说明毕业不是告别赛场。",
            "viewer_problem": "毕业后还要不要继续坚持热爱的事。",
            "specific_scene": "起跑前 0.5 秒和冲线后的反应。",
            "memorable_point": "毕业不是离开跑道，是换一种身份继续起跑。",
            "must_show": ["起跑", "冲线", "赛后反应"],
        },
        "topic_strategy": {
            "target_audience": "毕业季学生和体育爱好者",
            "pain_point": "毕业后热爱是否还值得继续",
            "content_angle": "用比赛瞬间回答毕业身份变化",
            "single_problem": "毕业后还要不要继续跑",
            "self_check": "每段都能看到赛场动作，不空讲道理",
        },
        "usable_material_brief": {
            "execution_brief": "先用起跑/冲线画面承接毕业身份变化，再把活动话题放到发布包装。",
            "source_mapping": [
                {"source": "ins1", "transfer": "真实赛场场景", "placement": "opening_3s/storyboard"},
                {"source": "vir1", "transfer": "开头冲突节奏", "placement": "hook_3s"},
            ],
            "usage_boundaries": ["不虚构成绩", "活动只约束话题和发布"],
        },
        "platform_strategy": {"summary": "前 0.5 秒看懂比赛"},
        "activity_strategy": {"summary": "毕业季自然承接"},
        "traffic_hypothesis": {"summary": "赛场画面抓停留"},
        "creation_reverse_plan": {"title": ["毕业身份转变"]},
        "validation_targets": {"two_hour": ["完播"]},
        "script_options": options,
        "recommended_option_id": recommended,
        "rejected_option_summaries": [{"angle": "泛泛讲毕业", "score": 82, "reject_reason": "缺少比赛画面。"}],
        "editor_pass": {
            "recommended_option_id": recommended,
            "blandness_risks": ["不能写成泛毕业感悟"],
            "revisions_applied": ["把推荐方案收紧到起跑前 0.5 秒"],
            "final_recommendation_reason": "推荐方案画面最具体，风险可控。",
        },
        "candidate_match_assessments": _candidate_match_assessments(viral_ids=viral_ids, inspiration_ids=inspiration_ids),
        "report_mode": dict(CREATOR_BRIEF_REPORT_MODE),
        "creator_report": _creator_report(),
    }


def _candidate_match_assessments(*, viral_ids: list[str] | None = None, inspiration_ids: list[str] | None = None) -> dict[str, list[dict[str, object]]]:
    return {
        "viral": [
            {
                "id": item,
                "score": 84,
                "score_breakdown": {
                    "request_fit": 34,
                    "content_value": 16,
                    "transferability": 22,
                    "evidence_completeness": 12,
                },
                "selection_reason": "开头钩子和情绪推进可迁移到本次内容结构。",
            }
            for item in (viral_ids or [])
        ],
        "inspiration": [
            {
                "id": item,
                "score": 82,
                "score_breakdown": {
                    "request_fit": 30,
                    "inspiration_quality": 21,
                    "transferability": 20,
                    "evidence_and_risk": 11,
                },
                "selection_reason": "真实场景和可迁移点适合本次主题。",
            }
            for item in (inspiration_ids or [])
        ],
    }


def _xhs_graph_option(activity_ids: list[str] | None = None, viral_ids: list[str] | None = None, inspiration_ids: list[str] | None = None) -> dict[str, object]:
    return {
        "option_id": "opt_1",
        "score": 94,
        "score_breakdown": _score_breakdown(94),
        "title": "表达力这样练",
        "angle": "用真实会议卡住的瞬间切入表达练习。",
        "score_reason": "真实场景、平台格式和活动适配都完整。",
        "selected_activity_ids": activity_ids or [],
        "selected_viral_ids": viral_ids or [],
        "selected_inspiration_ids": inspiration_ids or [],
        "selected_business_ids": [],
        "activity_fit_reason": "能自然承接活动对真实经历的要求。",
        "viral_reference_reason": "迁移爆款结构，不复刻原文。",
        "inspiration_reference_reason": "使用真实表达卡住后的复盘。",
        "risk_level": "low",
        "risks_or_missing_info": [],
        "tags": ["小红书", "职场", "表达力", "沟通", "成长", "干货", "方法", "练习", "行动", "复盘"],
        "final_copy": "用一个真实会议场景开头，再拆三个表达动作。",
        "image_script": ["封面：表达力卡住的真实瞬间", "第1页：会议发言前的心理动作"],
        "carousel": ["封面：表达力卡住的真实瞬间", "第1页：会议发言前的心理动作"],
        "hook_3s": "",
        "storyboard": [],
        "voiceover": "",
        "subtitles": [],
        "production_checklist": ["准备一个真实会议例子"],
        "review_plan": ["发布后 2 小时看收藏和评论问题"],
    }


def _blocks_text(blocks: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for block in blocks:
        if "heading2" in block:
            elements = block.get("heading2", {}).get("elements", [])  # type: ignore[union-attr]
        else:
            elements = block.get("text", {}).get("elements", [])  # type: ignore[union-attr]
        for element in elements:
            if isinstance(element, dict):
                text_run = element.get("text_run") or {}
                if isinstance(text_run, dict) and text_run.get("content"):
                    parts.append(str(text_run["content"]))
    return "\n".join(parts)


class CreationV1Tests(unittest.TestCase):
    def test_parse_type_as_content_type(self) -> None:
        req = parse_creation_request(
            "【创作>小红书】赛道=职场成长 类型=图文 主体=表达力 发布时间=今晚8点 品牌=某品牌",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertEqual(req.platform, "小红书")
        self.assertEqual(req.content_type, "图文")
        self.assertEqual(req.track, "职场成长")
        self.assertEqual(req.topic, "表达力")
        self.assertEqual(req.brand, "某品牌")
        self.assertIn("20:00", req.publish_time)

    def test_parse_guidance_plan_id_after_last_creation_field(self) -> None:
        req = parse_creation_request(
            "【创作>小红书】\n"
            "平台：小红书\n"
            "类型：图文\n"
            "赛道：AI科普\n"
            "主体：PR 合作招募帖\n"
            "路径续接ID：capplan_0123456789abcdef"
        )
        self.assertEqual(req.platform, "小红书")
        self.assertEqual(req.content_type, "图文")
        self.assertEqual(req.topic, "PR 合作招募帖")

    def test_parse_source_asset_id_from_growth_handoff(self) -> None:
        req = parse_creation_request(
            "【创作>抖音】类型=视频 赛道=体育 主体=400米训练 "
            "source=media://tenants/00000000-0000-4000-8000-000000000101/source_assets/source_asset_20260705_001/result.json",
            now=datetime(2026, 7, 5, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertEqual(req.source_asset_id, "source_asset_20260705_001")

    def test_parse_shooting_source_asset_id_from_growth_handoff(self) -> None:
        with patch("selfmedia.creation.shooting_execution.infer_shooting_execution_request", return_value={}):
            req = parse_shooting_execution_request(
                "【创作-拍摄执行】平台=抖音 类型=视频 赛道=体育 主体=400米训练 "
                "拍摄目标=记录间歇训练 场地=操场 人物=我 "
                "source_asset_id=source_asset_20260705_002"
            )
        self.assertEqual(req.source_asset_id, "source_asset_20260705_002")
        self.assertEqual(req.to_creation_request().source_asset_id, "source_asset_20260705_002")

    def test_parse_shooting_can_validate_explicit_fields_without_inference(self) -> None:
        with patch(
            "selfmedia.creation.shooting_execution.infer_shooting_execution_request",
            side_effect=AssertionError("explicit roundtrip must not call inference"),
        ):
            req = parse_shooting_execution_request(
                "【创作-拍摄执行】平台=抖音 主体=400米训练 "
                "拍摄目标=记录间歇训练 场地=操场 人物=我",
                infer_missing=False,
            )
        self.assertEqual(req.platform, "抖音")
        self.assertEqual(req.content_type, "视频")

        with self.assertRaisesRegex(ValueError, "人物"):
            parse_shooting_execution_request(
                "【创作-拍摄执行】平台=抖音 主体=400米训练 "
                "拍摄目标=记录间歇训练 场地=操场",
                infer_missing=False,
            )

    def test_parse_reference_output_and_audience_into_creation_context(self) -> None:
        req = parse_creation_request(
            "【创作>抖音】\n"
            "类型：视频\n"
            "赛道：教育、校园\n"
            "tags：#第一视角体验毕业典礼 #清华大学\n"
            "目标人群：大学生\n"
            "素材/参考：3.56 05/18 Njc:/ F@u.Fu :9pm 学业副本结算完毕 - 抖音 复制此链接\n"
            "希望产出：剪辑说明，已有素材\n"
            "主体：第一视角体验清华毕业典礼",
            now=datetime(2026, 6, 27, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(req.platform, "抖音")
        self.assertEqual(req.content_type, "视频")
        self.assertEqual(req.track, "教育、校园")
        self.assertEqual(req.topic, "第一视角体验清华毕业典礼")
        self.assertIn("目标人群：大学生", req.user_idea)
        self.assertIn("希望产出：剪辑说明，已有素材", req.user_idea)
        self.assertIn("素材/参考：3.56", req.user_idea)
        self.assertIn("学业副本结算完毕", req.brief)
        self.assertIn("第一视角体验毕业典礼", req.keywords or [])

    def test_missing_fields_use_llm_inference(self) -> None:
        with patch(
            "selfmedia.creation.request_inference.call_creation_json",
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
        with patch("selfmedia.creation.request_inference.call_creation_json", side_effect=RuntimeError("llm unavailable")):
            with self.assertRaisesRegex(RuntimeError, "llm unavailable"):
                parse_creation_request_with_llm(
                    "【创作】小红书 赛道=职场成长 主体=表达力 发布时间=今晚8点",
                    now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                )

    def test_llm_infers_freeform_creation_request_fields(self) -> None:
        with patch(
            "selfmedia.creation.request_inference.call_creation_json",
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
                "record_id": "decon_rec1",
                "fields": {
                    "asset_id": "asset1",
                    "deconstruction_id": "decon1",
                    "title": "嘴笨女生表达力",
                    "platform": "小红书",
                    "source_url": "https://example.com/source",
                    "summary": "表达力复盘图文。",
                    "hook": "嘴笨不是反应慢",
                    "transferable_points": "真实会议冲突开头，迁移到表达力图文结构。",
                    "封面/前2秒抓手": "封面直接放会议被问住的瞬间。",
                    "核心数据摘要": "点赞 12000，收藏 3000，评论 800。",
                    "高赞评论洞察": "大家都在问如何练习临场表达。",
                    "目标受众": "刚入职但表达卡住的女生。",
                    "痛点/爽点": "被追问时脑子空白，但想有体面回应。",
                    "吸睛元素": "会议追问和嘴笨标签形成反差。",
                    "爆点机制": "真实尴尬场景前置，再给一套练习法。",
                    "爆点迁移": "迁移到自己的会议复盘和表达训练步骤。",
                    "创新修改建议": "加入自己的录音复盘动作，减少说教感。",
                    "evidence_uri": "media://deconstructions/decon1/deconstruction.json",
                    "review_status": "未复核",
                },
            }
        )
        self.assertEqual(viral.record_type, "素材拆解")
        self.assertEqual(viral.source_table, "02B_MaterialDeconstructions_素材拆解")
        self.assertEqual(viral.title, "嘴笨女生表达力")
        self.assertEqual(viral.doc_links["evidence"], "media://deconstructions/decon1/deconstruction.json")
        self.assertTrue(any("表达力" in tag for tag in viral.tags))
        self.assertEqual(viral.audience, "刚入职但表达卡住的女生。")
        self.assertIn("脑子空白", viral.pain_points)
        self.assertIn("录音复盘", viral.core_value)
        self.assertEqual(viral.detail_json["cover_opening_hook"], "封面直接放会议被问住的瞬间。")
        self.assertEqual(viral.detail_json["core_data_summary"], "点赞 12000，收藏 3000，评论 800。")
        self.assertEqual(viral.detail_json["top_comment_insight"], "大家都在问如何练习临场表达。")
        self.assertEqual(viral.detail_json["target_audience"], "刚入职但表达卡住的女生。")
        self.assertEqual(viral.detail_json["pain_or_pleasure_points"], "被追问时脑子空白，但想有体面回应。")
        self.assertEqual(viral.detail_json["attention_elements"], "会议追问和嘴笨标签形成反差。")
        self.assertEqual(viral.detail_json["viral_mechanism"], "真实尴尬场景前置，再给一套练习法。")
        self.assertEqual(viral.detail_json["viral_migration"], "迁移到自己的会议复盘和表达训练步骤。")
        self.assertEqual(viral.detail_json["creative_upgrade_suggestion"], "加入自己的录音复盘动作，减少说教感。")
        candidate_payload = _record_candidate_payload(viral)
        self.assertEqual(candidate_payload["audience"], "刚入职但表达卡住的女生。")
        self.assertIn("脑子空白", candidate_payload["pain_points"])
        self.assertIn("viral_mechanism", candidate_payload["detail_json"])
        self.assertIn("录音复盘", candidate_payload["detail_json"]["creative_upgrade_suggestion"])
        prompt = build_creation_prompt(
            parse_creation_request("【创作>小红书】赛道=职场成长 类型=图文 主体=表达力"),
            activity_candidates=[],
            viral_candidates=[candidate_payload],
            inspiration_candidates=[],
            business_candidates=[],
            reference_docs=[],
            media_context={},
            platform_fit={},
        )
        self.assertIn("cover_opening_hook", prompt)
        self.assertIn("封面直接放会议被问住的瞬间", prompt)
        self.assertIn("creative_upgrade_suggestion", prompt)
        self.assertIn("加入自己的录音复盘动作", prompt)
        self.assertNotIn("detail_json", prompt)

        activity = ActivityAdapter().to_record(
            {
                "record_id": "act1",
                "fields": {
                    "标题": "成长活动",
                    "平台名称": "小红书",
                    "主状态": "进行中",
                    "主话题": "#表达力",
                    "子话题方向": "职场表达、真实复盘",
                    "活动Brief": "围绕表达力真实经历创作。",
                    "填写要点": "讲清楚具体场景和收获。",
                    "参与方式": "带话题发布",
                    "参与形式": "图文或视频",
                    "提交要求": "发布后返稿。",
                    "活动开始时间": "2026-05-01 00:00",
                    "活动结束时间": "2026-05-20 23:59",
                    "冲榜日期": "2026-05-19 12:00",
                    "Brief链接": {"text": "Brief", "link": "https://example.com/brief"},
                    "爆款示范链接": {"text": "示范", "link": "https://example.com/example"},
                    "返稿链接": {"text": "返稿", "link": "https://example.com/submit"},
                    "活动文档链接": {"text": "活动文档", "link": "https://example.com/activity"},
                },
            }
        )
        self.assertEqual(activity.source_table, "01_近期活动")
        self.assertEqual(activity.platform, "小红书")
        self.assertEqual(activity.topic, "#表达力")
        self.assertEqual(activity.status, "进行中")
        self.assertEqual(activity.direction, "职场表达、真实复盘")
        self.assertEqual(activity.activity_brief, "围绕表达力真实经历创作。")
        self.assertEqual(activity.submission_link, "https://example.com/submit")
        self.assertEqual(activity.doc_links["viral_example"], "https://example.com/example")

        legacy_activity = ActivityAdapter().to_record(
            {
                "record_id": "act_old",
                "fields": {
                    "状态": "进行中",
                    "平台": "小红书",
                    "主题": "表达力",
                    "投稿截止时间": "2026-05-20 23:59",
                    "方向": "旧方向",
                    "来源链接": "https://example.com/old",
                },
            }
        )
        self.assertEqual(legacy_activity.status, "")
        self.assertEqual(legacy_activity.platform, "")
        self.assertEqual(legacy_activity.topic, "")
        self.assertIsNone(legacy_activity.deadline)
        self.assertEqual(legacy_activity.source_link, "")

        inspiration = CreationInspirationAdapter().to_record(
            {
                "record_id": "ins1",
                "fields": {
                    "pattern_id": "ins1",
                    "pattern_name": "被质疑后的表达力反思",
                    "pattern_status": "validated_pattern",
                    "platform": "小红书",
                    "content_type": "图文",
                    "applicable_persona": "职场成长",
                    "applicable_scenarios": "表达力",
                    "structure_template": "被质疑时先复盘错位点，再提炼观点。",
                    "emotional_levers": "创作-灵感、表达力",
                },
            }
        )
        self.assertEqual(inspiration.record_type, "创作模式")
        self.assertEqual(inspiration.source_table, "02C_CreativePatterns_创作模式")
        self.assertEqual(inspiration.source_record_id, "ins1")
        self.assertEqual(inspiration.core_value, "被质疑时先复盘错位点，再提炼观点。")
        self.assertIn("表达力", inspiration.tags)

    def test_viral_adapter_only_carries_deconstruction_artifact_uri(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "media_vault"
            evidence_uri = _write_deconstruction_v2_artifact(root, "decon1")
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": str(root)}):
                viral = ViralContentAdapter().to_record(
                    {
                        "record_id": "decon_rec1",
                        "fields": {
                            "asset_id": "asset1",
                            "deconstruction_id": "decon1",
                            "title": "AI 拉片",
                            "summary": "把爆款拆成 SOP。",
                            "hook": "所有自媒体博主都关心",
                            "transferable_points": "先点名人群，再给 SOP。",
                            "evidence_uri": evidence_uri,
                            "review_status": "未复核",
                        },
                    }
                )

        self.assertEqual(viral.doc_links["evidence"], evidence_uri)
        self.assertEqual(viral.detail_json["evidence_uri"], evidence_uri)
        self.assertNotIn("usable_material_brief", viral.detail_json)

    def test_activity_and_viral_ranking_are_separate(self) -> None:
        req = parse_creation_request(
            "【创作>小红书】赛道=职场成长 类型=图文 主体=表达力 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        activity = ActivityAdapter().to_record(
            {
                "record_id": "act1",
                "fields": {
                    "标题": "表达力活动",
                    "平台名称": "小红书",
                    "主话题": "表达力",
                    "子话题方向": "职场成长表达力",
                    "主状态": "进行中",
                    "活动开始时间": "2026-05-01 00:00",
                    "活动结束时间": "2026-05-20 23:59",
                    "活动级别": "A",
                },
            }
        )
        viral = ViralContentAdapter().to_record(
            {
                "record_id": "vir1",
                "fields": {
                    "asset_id": "asset1",
                    "deconstruction_id": "vir1",
                    "title": "表达力爆款",
                    "platform": "小红书",
                    "source_url": "https://example.com/source",
                    "summary": "职场成长表达力复盘。",
                    "hook": "表达力卡住的真实瞬间。",
                    "transferable_points": "迁移到表达力图文结构。",
                    "evidence_uri": "media://deconstructions/vir1/deconstruction.json",
                    "confidence": 0.91,
                    "review_status": "未复核",
                },
            }
        )
        self.assertGreater(rank_activities([activity], req)[0].score, 0)
        self.assertGreater(rank_virals([viral], req)[0].score, 0)
        self.assertLessEqual(rank_activities([activity], req)[0].score, 100)
        self.assertLessEqual(rank_virals([viral], req)[0].score, 100)

        expired_activity = ActivityAdapter().to_record(
            {
                "record_id": "act_expired",
                "fields": {
                    "标题": "过期活动",
                    "平台名称": "小红书",
                    "主话题": "表达力",
                    "主状态": "已过期",
                    "活动开始时间": "2026-05-01 00:00",
                    "活动结束时间": "2026-05-20 23:59",
                },
            }
        )
        missing_window_activity = ActivityAdapter().to_record(
            {
                "record_id": "act_no_end",
                "fields": {
                    "标题": "缺少结束时间活动",
                    "平台名称": "小红书",
                    "主话题": "表达力",
                    "主状态": "进行中",
                    "活动开始时间": "2026-05-01 00:00",
                },
            }
        )
        self.assertEqual(rank_activities([expired_activity, missing_window_activity], req), [])

    def test_viral_matching_uses_real_score_and_hard_conflicts(self) -> None:
        req = parse_creation_request(
            "【创作>小红书】赛道=职场成长 类型=图文 主体=表达力 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        matched = ViralContentAdapter().to_record(
            {
                "record_id": "vir_match",
                "fields": {
                    "asset_id": "asset_match",
                    "deconstruction_id": "vir_match",
                    "title": "表达力爆款",
                    "platform": "小红书",
                    "source_url": "https://example.com/source",
                    "summary": "职场成长表达力复盘，把表达力复盘成方法。",
                    "hook": "嘴笨不是反应慢，是真实会议冲突开头。",
                    "transferable_points": "迁移到表达力图文结构。",
                    "non_transferable_points": "不能照搬原文。",
                    "evidence_uri": "media://deconstructions/vir_match/deconstruction.json",
                    "confidence": 0.93,
                    "review_status": "未复核",
                },
            }
        )
        conflict = ViralContentAdapter().to_record(
            {
                "record_id": "vir_conflict",
                "fields": {
                    "asset_id": "asset_conflict",
                    "deconstruction_id": "vir_conflict",
                    "title": "表达力视频",
                    "platform": "抖音",
                    "summary": "表达力视频。",
                    "evidence_uri": "media://deconstructions/vir_conflict/deconstruction.json",
                    "review_status": "未复核",
                },
            }
        )
        missing_optional = ViralContentAdapter().to_record(
            {
                "record_id": "vir_missing",
                "fields": {
                    "asset_id": "asset_missing",
                    "deconstruction_id": "vir_missing",
                    "title": "表达力爆款",
                    "summary": "职场成长表达力。",
                    "evidence_uri": "media://deconstructions/vir_missing/deconstruction.json",
                    "review_status": "未复核",
                },
            }
        )
        ranked = rank_virals([matched, conflict, missing_optional], req)
        ranked_ids = [item.record.source_record_id for item in ranked]
        self.assertIn("vir_match", ranked_ids)
        self.assertIn("vir_missing", ranked_ids)
        self.assertNotIn("vir_conflict", ranked_ids)
        self.assertLess(ranked[0].score, 100)
        self.assertIn("有证据artifact", ranked[0].reasons)

    def test_inspiration_matching_uses_request_fit_not_raw_inspiration_score(self) -> None:
        req = parse_creation_request(
            "【创作>小红书】赛道=跑鞋测评 类型=图文 主体=跑鞋测评 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        unrelated_high_score = CreationInspirationAdapter().to_record(
            {
                "record_id": "ins_high_unrelated",
                "fields": {
                    "pattern_id": "ins_high_unrelated",
                    "pattern_name": "情感成长模式",
                    "pattern_status": "validated_pattern",
                    "platform": "小红书",
                    "content_type": "图文",
                    "applicable_persona": "情感成长",
                    "applicable_scenarios": "亲密关系沟通",
                    "historical_performance_summary": "素材本身质量高",
                },
            }
        )
        matched = CreationInspirationAdapter().to_record(
            {
                "record_id": "ins_match",
                "fields": {
                    "pattern_id": "ins_match",
                    "pattern_name": "跑鞋测评模式",
                    "pattern_status": "validated_pattern",
                    "platform": "小红书",
                    "content_type": "图文",
                    "applicable_persona": "跑鞋测评",
                    "applicable_scenarios": "跑鞋测评图文",
                    "opening_template": "用真实训练体感开头",
                    "structure_template": "用一次训练说清跑鞋测评",
                    "visual_template": "训练前后体感对比",
                    "emotional_levers": "买鞋怕踩坑、跑鞋测评、训练",
                    "forbidden_scenarios": "不要夸大性能",
                    "historical_performance_summary": "真实训练素材清楚",
                },
            }
        )
        ranked = rank_inspirations([unrelated_high_score, matched], req)
        ranked_ids = [item.record.source_record_id for item in ranked]
        self.assertEqual(ranked_ids, ["ins_match"])
        self.assertLess(ranked[0].score, 100)
        self.assertIn("主题相似", ranked[0].reasons)

    def test_activity_viral_example_deconstructs_into_viral_candidate(self) -> None:
        activity = CanonicalMediaRecord(
            source_table="01_近期活动",
            source_record_id="act1",
            record_type="活动",
            title="表达力活动",
            viral_example_link="https://www.douyin.com/note/example",
            doc_links={"viral_example": "https://www.douyin.com/note/example"},
        )
        canonical_result = {
            "feishu_record_id": "vir_from_activity",
            "deconstruct": {
                "deconstruct_doc_title": "爆款拆解文档｜表达力",
                "deconstruct_doc_url": "https://tcnwueberajc.feishu.cn/docx/deconstruct",
                "summary": "真实会议场景开头。",
                "platform": "抖音",
                "media_type": "视频",
            },
        }
        with patch(
            "selfmedia.deconstruct.viral_content.src.runner.run_workflow",
            return_value=canonical_result,
        ) as run:
            records, results = _deconstruct_activity_example_links(
                [RankedRecord(activity, 90, {"主状态进行中": 20})],
                tenant_id="00000000-0000-4000-8000-000000000101",
                existing_virals=[],
                enabled=True,
                max_items=1,
            )
        run.assert_called_once_with(
            "【拆解】 https://www.douyin.com/note/example",
            tenant_id="00000000-0000-4000-8000-000000000101",
            write_feishu=True,
        )
        self.assertEqual(records[0].source_record_id, "vir_from_activity")
        self.assertEqual(records[0].doc_links["decomposition"], "https://tcnwueberajc.feishu.cn/docx/deconstruct")
        self.assertEqual(results[0]["record_id"], "vir_from_activity")
        self.assertNotIn("record", results[0])

        existing = CanonicalMediaRecord(
            source_table="02B_MaterialDeconstructions_素材拆解",
            source_record_id="vir_existing",
            record_type="素材拆解",
            source_link="https://www.douyin.com/note/example",
            doc_links={"decomposition": "https://tcnwueberajc.feishu.cn/docx/existing"},
        )
        with patch("selfmedia.deconstruct.viral_content.src.runner.run_workflow") as run_again:
            existing_records, existing_results = _deconstruct_activity_example_links(
                [RankedRecord(activity, 90, {"主状态进行中": 20})],
                tenant_id="00000000-0000-4000-8000-000000000101",
                existing_virals=[existing],
                enabled=True,
                max_items=1,
            )
        run_again.assert_not_called()
        self.assertEqual(existing_records[0].source_record_id, "vir_existing")
        self.assertEqual(existing_results[0]["status"], "already_indexed")

    def test_activity_example_deconstruct_is_in_process_and_fails_closed(self) -> None:
        self.assertNotIn("subprocess", inspect.getsource(_run_viral_deconstruct))
        with patch(
            "selfmedia.deconstruct.viral_content.src.runner.run_workflow",
            side_effect=RuntimeError("tenant model transport unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "tenant model transport unavailable"):
                _run_viral_deconstruct(
                    "https://www.douyin.com/note/example",
                    tenant_id="00000000-0000-4000-8000-000000000101",
                )

    def test_business_adapter_and_ranking_require_business_context(self) -> None:
        business = BusinessAdapter().to_record(
            {
                "record_id": "biz1",
                "fields": {
                    "opportunity_id": "opp1",
                    "business_account_id": "biz_account_xiaowang",
                    "brand": "某品牌",
                    "product": "表达力课程",
                    "brief_link": {"text": "brief", "link": "https://example.com/brief"},
                    "current_quote_amount": "8000",
                },
            }
        )
        self.assertEqual(business.record_type, "商务")
        self.assertEqual(business.source_table, "05B_BusinessOpportunities_商务机会")
        self.assertEqual(business.content_type_requirement, "不限")
        self.assertEqual(business.doc_links["brief"], "https://example.com/brief")

        no_business_req = parse_creation_request(
            "【创作>小红书】赛道=职场成长 类型=图文 主体=表达力 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertEqual(rank_businesses([business], no_business_req), [])

        business_req = parse_creation_request(
            "【创作>小红书】赛道=职场成长 类型=图文 主体=表达力 发布时间=2026-05-10 20:00 品牌=某品牌 产品=表达力课程",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        ranked = rank_businesses([business], business_req)
        self.assertEqual(ranked[0].record.source_record_id, "biz1")
        self.assertIn("品牌匹配", ranked[0].reasons)

    def test_creation_source_and_output_contracts_are_explicit(self) -> None:
        self.assertEqual(CREATION_SOURCE_TABLE_CONTRACTS["activity"]["table"], "01_近期活动")
        self.assertEqual(CREATION_SOURCE_TABLE_CONTRACTS["viral"]["table"], "02B_MaterialDeconstructions_素材拆解")
        self.assertIn("MEDIA_OS_SOURCE_ASSETS_URL", CREATION_SOURCE_TABLE_CONTRACTS["viral"]["env"])
        self.assertIn("MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL", CREATION_SOURCE_TABLE_CONTRACTS["viral"]["env"])
        self.assertEqual(CREATION_SOURCE_TABLE_CONTRACTS["business"]["table"], "05B_BusinessOpportunities_商务机会")
        self.assertEqual(CREATION_SOURCE_TABLE_CONTRACTS["inspiration"]["table"], "02C_CreativePatterns_创作模式")
        self.assertIn("MEDIA_OS_CREATION_RUNS_URL", CREATION_OUTPUT_TABLE_CONTRACT["env"])
        self.assertIn("run_id", CREATION_OUTPUT_TABLE_CONTRACT["fields"])
        self.assertIn("run_artifact_uri", CREATION_OUTPUT_TABLE_CONTRACT["fields"])
        self.assertIn("feishu_doc_link", CREATION_OUTPUT_TABLE_CONTRACT["fields"])

    def test_creation_doc_lookup_reuses_latest_same_title_doc(self) -> None:
        with patch("selfmedia.creation.writer.requests.get") as mock_get:
            mock_get.return_value = _JsonResponse(
                {
                    "code": 0,
                    "data": {
                        "items": [
                            {"title": "同名创作文档", "obj_type": "docx", "obj_token": "doc_old", "node_token": "node_old"},
                            {"title": "其他文档", "obj_type": "docx", "obj_token": "doc_other", "node_token": "node_other"},
                            {"title": "同名创作文档", "obj_type": "docx", "obj_token": "doc_latest", "node_token": "node_latest"},
                        ],
                        "has_more": False,
                    },
                }
            )
            self.assertEqual(_find_wiki_child_doc("space", "parent", "同名创作文档", "token"), ("doc_latest", "node_latest"))

    def test_shooting_execution_doc_puts_storyboard_first(self) -> None:
        request = SimpleNamespace(
            topic="WAIC 探展",
            time_window="130-150 秒",
            publish_time="",
            platform="抖音",
            content_type="视频",
            shooting_goal="完成第一视角探展",
        )
        draft = {
            "shooting_goal": {},
            "storyboard": [{"time": "0-2s", "visual": "结果钩子", "caption_or_voice": "开场", "sound_or_note": "现场声"}],
            "abstraction_map": [{"source_signal": "Brief", "task_layer": "脚本", "execution_meaning": "先拍钩子"}],
            "route_map": [{"time_slot": "上午", "location": "展位", "shooting_task": "拍摄", "people": "博主", "backup": "补拍"}],
            "must_shot_list": [{"priority": "P0", "location": "展位", "people": "博主", "action": "体验", "shot_size": "中景", "reference": "Brief", "usage": "正片", "reshoot_check": "清晰"}],
            "branch_plans": [{"condition": "拥挤", "plan": "先拍特写", "priority": "P1"}],
            "onsite_checklist": ["回看"],
            "publishing_pack": {
                "title_directions": ["主标题", "备选标题"],
                "cover_frame": "人物、设备和机器狗同框；封面字：脑电怎样走到执行",
                "body_copy": "完整发布文案。",
                "hashtags": ["脑机接口", "科技探展"],
                "bgm_suggestion": "克制电子乐",
                "comment_prompt": "你最想控制什么？",
            },
            "evidence_appendix": [{"source": "Brief", "source_status": "confirmed", "available_evidence": "已提供", "usage_reason": "执行依据", "risk": "无"}],
        }
        blocks = _shooting_execution_doc_blocks(
            "拍摄执行",
            request,
            draft,
            {
                "ok": False,
                "missing": ["route_map", "must_shot_list"],
                "empty_lists": ["onsite_checklist"],
            },
            media_context={"loaded": {"account_profile": True, "future_runtime_flag": True}},
        )
        rendered = _blocks_text(blocks)
        self.assertEqual(rendered.splitlines()[:2], ["拍摄执行", "分镜脚本"])
        self.assertEqual(blocks[2]["rows"][0], ["时间", "画面", "字幕/口播", "声音/拍摄注意"])
        native_tables = [block["rows"] for block in blocks if block.get("_openclaw_kind") == "_openclaw_feishu_table"]
        must_shot_table = next(rows for rows in native_tables if rows[0][0] == "优先级")
        branch_plan_table = next(rows for rows in native_tables if rows[0] == ["触发条件", "执行方案", "优先级"])
        self.assertEqual(must_shot_table[1][0], "必拍")
        self.assertEqual(branch_plan_table[1][2], "重要")
        table_text = "\n".join(cell for rows in native_tables for row in rows for cell in row)
        self.assertNotIn("P0", table_text)
        self.assertNotIn("P1", table_text)
        self.assertNotIn("P2", table_text)
        self.assertIn("必拍", rendered)
        self.assertIn("现场检查清单", rendered)
        self.assertIn("缺失字段：路线图、必拍镜头清单", rendered)
        self.assertIn("空列表字段：现场检查清单", rendered)
        self.assertIn("其他上下文已加载", rendered)
        self.assertNotIn("route_map", rendered)
        self.assertNotIn("must_shot_list", rendered)
        self.assertNotIn("onsite_checklist", rendered)
        self.assertNotIn("future_runtime_flag", rendered)
        self.assertIn("证据附录", rendered)
        self.assertIn("来源状态：已核验", rendered)
        self.assertTrue(draft["evidence_appendix"])
        publishing_index = next(index for index, block in enumerate(blocks) if "发布包" in _blocks_text([block]))
        publishing_blocks = blocks[publishing_index:]
        subheadings = [
            block["heading3"]["elements"][0]["text_run"]["content"]
            for block in publishing_blocks
            if block.get("block_type") == 5
        ]
        self.assertEqual(subheadings, ["作品标题", "封面图方案", "发布文案", "话题与互动", "声音方案"])
        self.assertIn("标题 1：主标题", _blocks_text(publishing_blocks))
        self.assertIn("完整发布文案。", _blocks_text(publishing_blocks))

    def test_shooting_prompts_do_not_direct_user_visible_machine_states(self) -> None:
        request = ShootingExecutionRequest(
            platform="抖音",
            content_type="视频",
            track="科技",
            topic="WAIC 探展",
            shooting_goal="完成第一视角探展",
            locations=["展位"],
            people=["博主"],
        )
        captured: list[str] = []
        complete_draft = {
            "shooting_goal": {},
            "route_map": [{}],
            "must_shot_list": [{"priority": "P0"}],
            "branch_plans": [{"priority": "P1"}],
            "storyboard": [{}],
            "onsite_checklist": ["回看"],
            "publishing_pack": {},
            "evidence_appendix": [{"source_status": "confirmed"}],
        }

        def fake_call(prompt: str, **_kwargs: object) -> dict[str, object]:
            captured.append(prompt)
            return complete_draft

        with patch("selfmedia.creation.shooting_execution.call_creation_json", side_effect=fake_call):
            generated = generate_shooting_execution_plan(
                request,
                media_context={
                    "deconstruction_evidence": {
                        "status": "confirmed",
                        "items": [{"source_link": "https://example.com/ref", "source_status": "confirmed"}],
                    }
                },
            )

        self.assertEqual(len(captured), 1)
        self.assertEqual(generated["must_shot_list"][0]["priority"], "必拍")
        self.assertEqual(generated["branch_plans"][0]["priority"], "重要")
        self.assertEqual(generated["evidence_appendix"][0]["source_status"], "已核验")
        self.assertIn('"priority":"必拍|重要|可选"', captured[0])
        self.assertIn("来源状态为“已核验”", captured[0])
        self.assertIn("仅凭文字描述，未看过原片", captured[0])
        self.assertIn("待人工核实", captured[0])
        self.assertNotIn("confirmed", captured[0])
        self.assertNotIn("manual_description_only", captured[0])
        self.assertNotIn("pending_manual", captured[0])

        revision_prompt = backwash._revision_prompt(
            {
                "must_shot_list": [{"priority": "P0"}],
                "branch_plans": [{"priority": "P1"}],
                "evidence_appendix": [{"source_status": "confirmed"}],
            },
            "按事实重写",
            {"deconstruction_evidence": {"status": "manual_description_only"}},
            {"strategy": "result_hook_then_chronological", "beats": [{"narrative_role": "hook_setup"}]},
        )
        self.assertIn("优先级只能写“必拍”“重要”或“可选”", revision_prompt)
        self.assertIn("来源状态只能写“已核验”“仅凭文字描述，未看过原片”或“待人工核实”", revision_prompt)
        self.assertIn("待人工核实", revision_prompt)
        self.assertIn("悬念设置/悬念回收", revision_prompt)
        self.assertNotIn("P0", revision_prompt)
        self.assertNotIn("P1", revision_prompt)
        self.assertNotIn("confirmed", revision_prompt)
        self.assertNotIn("pending_manual", revision_prompt)
        self.assertNotIn("hook_setup/hook_payoff", revision_prompt)
        self.assertNotIn("hook_setup", revision_prompt)

        narrative_prompt = backwash._narrative_plan_prompt(
            {"must_shot_list": [{"priority": "P0"}]},
            "按事实重写",
            {},
            previous={"strategy": "result_hook_then_chronological", "beats": [{"narrative_role": "hook_setup"}]},
        )
        self.assertIn("叙事角色只能是悬念设置", narrative_prompt)
        self.assertNotIn("hook_setup", narrative_prompt)
        self.assertNotIn("result_hook_then_chronological", narrative_prompt)

    def test_creation_doc_renders_creator_brief_before_evidence(self) -> None:
        req = parse_creation_request(
            "【创作>抖音】类型=视频 赛道=体育 主体=西安田径分区邀请赛",
            now=datetime(2026, 6, 18, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        candidate_ids = {
            "selected_activity_ids": {"act1"},
            "selected_viral_ids": {"vir1"},
            "selected_inspiration_ids": {"ins1"},
            "selected_business_ids": set(),
        }
        draft = validate_llm_draft_payload(
            _multi_option_payload([_script_option(score=94), _script_option("opt_2", score=91)]),
            req,
            candidate_ids=candidate_ids,
        )
        activity = RankedRecord(
            CanonicalMediaRecord(
                source_table="01_近期活动",
                source_record_id="act1",
                record_type="活动",
                title="毕业季活动",
                topic="#毕业季",
                direction="#那就好好告个别吧",
                submission_link="https://example.com/form",
            ),
            85,
            {"LLM选择活动": 100},
        )
        viral = RankedRecord(CanonicalMediaRecord(source_table="02_爆款内容积累", source_record_id="vir1", record_type="爆款样本", title="起跑爆款"), 84, {"平台一致": 10, "LLM选择原因": "迁移起跑冲突。"})
        inspiration = RankedRecord(
            CanonicalMediaRecord(
                source_table="Obsidian:人性洞察库",
                source_record_id="ins1",
                record_type="机制卡",
                title="机制卡｜被理解感",
                status="已验证",
                detail_json={
                    "insight_card_path": "/home/ubuntu/obsidian-自媒体/05_素材与爆款库/人性洞察库/机制卡/被理解感.md",
                    "insight_card_status": "已验证",
                    "evidence_boundary": "public_content_only",
                    "risk_boundary": "避免焦虑营销。",
                },
            ),
            82,
            {"主题相似": 8, "LLM选择原因": "落到毕业身份切换台词。"},
        )
        blocks = _creation_doc_blocks(
            "测试文档",
            req,
            [activity],
            [viral],
            [inspiration],
            [],
            draft,
            {"ok": True},
            platform_fit={"platform_mechanism_version": "douyin_test"},
        )
        text = _blocks_text(blocks)
        native_tables = [block for block in blocks if block.get("_openclaw_kind") == "_openclaw_feishu_table"]
        self.assertIn("创作方案总览", text)
        self.assertIn("这条内容怎么拍", text)
        self.assertEqual(len(native_tables), 2)
        self.assertEqual(native_tables[0]["rows"][0], ["时间", "画面", "字幕/口播", "声音/拍摄注意"])
        self.assertEqual(native_tables[1]["rows"][0], ["时间", "画面", "字幕/口播", "声音/拍摄注意"])
        self.assertNotIn("时间｜画面｜字幕｜声音｜拍摄注意", text)
        self.assertIn("这条内容怎么发", text)
        self.assertIn("脚本方案", text)
        self.assertIn("方案 1（推荐）", text)
        self.assertIn("方案 2", text)
        self.assertIn("方案 1 分镜脚本", text)
        self.assertIn("方案 2 分镜脚本", text)
        self.assertIn("发布后验证", text)
        self.assertIn("证据附录", text)
        main_text = text.split("证据附录", 1)[0]
        appendix_text = text.split("证据附录", 1)[1]
        # 论证信息（评分、评分理由、来源命中论证）不得进入执行区与脚本方案正文。
        self.assertNotIn("方案分数", main_text)
        self.assertNotIn("分数：94分", main_text)
        self.assertNotIn("评分理由", main_text)
        self.assertIn("94分", appendix_text)
        self.assertIn("评分理由", appendix_text)
        self.assertNotIn("匹配到的活动", main_text)
        self.assertNotIn("平台推荐拟合", main_text)
        self.assertNotIn("option_id", main_text)
        self.assertNotIn("record_id", main_text)
        self.assertNotIn("record_id", appendix_text)
        self.assertIn("来源编号", appendix_text)
        self.assertNotIn("insight-card reference", appendix_text)
        self.assertNotIn("public_content_only", appendix_text)
        self.assertIn("引用类型：洞察卡（仅公开内容）", appendix_text)
        self.assertIn("证据边界：仅公开内容", appendix_text)
        self.assertIn("避免焦虑营销", appendix_text)
        self.assertIn("被理解感.md", appendix_text)
        self.assertIn("候选方案分数", appendix_text)
        self.assertNotIn('"activity"', appendix_text)
        self.assertNotIn('"record_id"', appendix_text)

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

    def test_llm_draft_script_options_threshold_and_recommendation(self) -> None:
        req = parse_creation_request(
            "【创作>抖音】类型=视频 赛道=体育 主体=西安田径分区邀请赛 发布时间=2026-06-18 20:00",
            now=datetime(2026, 6, 18, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        candidate_ids = {
            "selected_activity_ids": {"act1"},
            "selected_viral_ids": {"vir1"},
            "selected_inspiration_ids": {"ins1"},
            "selected_business_ids": set(),
        }
        draft = validate_llm_draft_payload(_multi_option_payload([_script_option(score=91), _script_option("opt_2", score=88)]), req, candidate_ids=candidate_ids)
        self.assertEqual(draft["recommended_option_id"], "opt_1")
        self.assertEqual(draft["title"], "毕业后再上跑道")
        self.assertEqual(draft["selected_activity_ids"], ["act1"])
        self.assertEqual(draft["candidate_match_assessments"]["viral"][0]["score"], 84)
        self.assertEqual(draft["score_breakdown"] if "score_breakdown" in draft else draft["script_options"][0]["score_breakdown"]["evidence_grounding"], 20)

        below_90 = validate_llm_draft_payload(_multi_option_payload([_script_option(score=90), _script_option("opt_2", score=88)]), req, candidate_ids=candidate_ids)
        self.assertEqual([item["score"] for item in below_90["script_options"]], [90, 88])
        with self.assertRaisesRegex(ValueError, "最少 2 个"):
            validate_llm_draft_payload(_multi_option_payload([_script_option(score=90)]), req, candidate_ids=candidate_ids)
        with self.assertRaisesRegex(ValueError, "最多 5 个"):
            validate_llm_draft_payload(_multi_option_payload([_script_option(f"opt_{index}", score=91) for index in range(6)]), req, candidate_ids=candidate_ids)
        with self.assertRaisesRegex(ValueError, "recommended_option_id"):
            validate_llm_draft_payload(_multi_option_payload([_script_option(score=91), _script_option("opt_2", score=88)], recommended="missing"), req, candidate_ids=candidate_ids)
        with self.assertRaisesRegex(ValueError, "非候选 id"):
            validate_llm_draft_payload(_multi_option_payload([_script_option(score=91, activity_id="invented"), _script_option("opt_2", score=88)]), req, candidate_ids=candidate_ids)
        bad_assessment = _multi_option_payload([_script_option(score=91), _script_option("opt_2", score=88)])
        bad_assessment["candidate_match_assessments"]["viral"][0]["score_breakdown"]["request_fit"] = 99  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "candidate_match_assessments.viral.score_breakdown.request_fit"):
            validate_llm_draft_payload(bad_assessment, req, candidate_ids=candidate_ids)
        missing_report = _multi_option_payload([_script_option(score=91), _script_option("opt_2", score=88)])
        missing_report.pop("creator_report")
        with self.assertRaisesRegex(ValueError, "creator_report"):
            validate_llm_draft_payload(missing_report, req, candidate_ids=candidate_ids)
        old_score_field = _multi_option_payload([_script_option(score=91), _script_option("opt_2", score=88)])
        old_score_field["script_options"][0].pop("score_reason")  # type: ignore[index]
        old_score_field["script_options"][0]["why_over_90"] = "旧字段不再接受"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "script_options.score_reason"):
            validate_llm_draft_payload(old_score_field, req, candidate_ids=candidate_ids)
        missing_editor_pass = _multi_option_payload([_script_option(score=91), _script_option("opt_2", score=88)])
        missing_editor_pass.pop("editor_pass")
        with self.assertRaisesRegex(ValueError, "editor_pass"):
            validate_llm_draft_payload(missing_editor_pass, req, candidate_ids=candidate_ids)

    def test_llm_draft_selected_insight_card_requires_reference_boundary(self) -> None:
        req = parse_creation_request(
            "【创作>抖音】类型=视频 赛道=体育 主体=西安田径分区邀请赛 发布时间=2026-06-18 20:00",
            now=datetime(2026, 6, 18, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        insight_id = "insight_card:被理解感"
        candidate_ids = {
            "selected_activity_ids": {"act1"},
            "selected_viral_ids": {"vir1"},
            "selected_inspiration_ids": {insight_id},
            "selected_business_ids": set(),
        }
        payload = _multi_option_payload(
            [
                _script_option(score=91, inspiration_id=insight_id),
                _script_option("opt_2", score=88, inspiration_id=insight_id),
            ]
        )
        payload["inspiration_reference"] = {
            "matched": True,
            "reference_type": "insight-card reference",
            "evidence_boundary": "public_content_only",
        }
        payload["usable_material_brief"]["source_mapping"][0] = {  # type: ignore[index]
            "source": insight_id,
            "transfer": "insight-card reference: 被理解感开头句式",
            "placement": "opening_3s/storyboard",
            "evidence_boundary": "public_content_only",
        }
        payload["creator_report"]["evidence_appendix"]["inspiration_refs"] = [  # type: ignore[index]
            {
                "source_type": "insight-card reference",
                "record_id": insight_id,
                "adoption_reason": "只作为公开内容洞察参考。",
                "risk_boundary": "public_content_only",
            }
        ]
        payload["candidate_match_assessments"]["inspiration"][0]["selection_reason"] = "insight-card reference，public_content_only，只用于情绪路径参考。"  # type: ignore[index]
        for option in payload["script_options"]:  # type: ignore[union-attr]
            option["inspiration_reference_reason"] = "insight-card reference；public_content_only；只参考情绪路径和开头句式。"
        draft = validate_llm_draft_payload(payload, req, candidate_ids=candidate_ids)
        self.assertEqual(draft["selected_inspiration_ids"], [insight_id])

        bad = _multi_option_payload(
            [
                _script_option(score=91, inspiration_id=insight_id),
                _script_option("opt_2", score=88, inspiration_id=insight_id),
            ]
        )
        with self.assertRaisesRegex(ValueError, "insight-card reference"):
            validate_llm_draft_payload(bad, req, candidate_ids=candidate_ids)

    def test_creation_prompt_compacts_evidence_without_detail_json(self) -> None:
        req = parse_creation_request(
            "【创作>抖音】类型=视频 赛道=体育 主体=西安田径分区邀请赛",
            now=datetime(2026, 6, 18, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        huge_text = "毕业季活动 brief " * 2000
        candidates = [
            {
                "id": f"act{i}",
                "title": f"毕业季活动 {i}",
                "activity_brief": huge_text,
                "submission_link": "https://example.com/form",
                "viral_example_link": "https://example.com/viral",
                "detail_json": {"raw": huge_text},
            }
            for i in range(35)
        ]
        prompt = build_creation_prompt(
            req,
            activity_candidates=candidates,
            viral_candidates=candidates,
            inspiration_candidates=candidates,
            business_candidates=candidates,
            reference_docs=[{"title": "爆款拆解", "url": "https://example.com/doc", "content": huge_text} for _ in range(12)],
            media_context={
                "prompt": huge_text,
                "loaded": {"account_profile": True},
                "account_profile": {"bio": huge_text},
                "recent_creations": [{"title": "历史创作", "content": huge_text} for _ in range(20)],
                "recent_reviews": [{"title": "历史复盘", "content": huge_text} for _ in range(20)],
            },
            platform_fit={"platform_strategy": {"summary": huge_text}},
        )
        self.assertLess(len(prompt), 180_000)
        self.assertIn("act0", prompt)
        self.assertIn("submission_link", prompt)
        self.assertIn("viral_example_link", prompt)
        self.assertNotIn("detail_json", prompt)

    def test_platform_mechanism_config_is_available_as_llm_reference(self) -> None:
        config = load_platform_mechanism_config("小红书")
        self.assertEqual(config["mechanism_version"], "xiaohongshu_v1")
        self.assertIn("content_reasoning", config)

    def test_platform_mechanism_fit_uses_llm_output(self) -> None:
        req = parse_creation_request(
            "【创作>小红书】赛道=自媒体 类型=图文 主体=选题方法 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        payload = {
            "platform_mechanism_version": "xiaohongshu_v1",
            "mechanism_claim_boundary": "这是机制拟合假设，不是平台真实算法或权重结论。",
            "mechanism_evidence_level": "B",
            "source_weights": {"llm": "B"},
            "platform_strategy": {"summary": "LLM 平台策略"},
            "activity_strategy": {
                "matched_activities": [],
                "candidate_activity_ids": [],
                "natural_fit": False,
                "hard_fit_risk": "low",
                "risk_reason": "无活动候选。",
                "required_adjustments": [],
                "do_not_force": ["不要为了活动改写内容主线。"],
            },
            "traffic_hypothesis": {"summary": "LLM 流量假设"},
            "creation_reverse_plan": {"title": ["LLM 标题策略"]},
            "validation_targets": {"two_hour": ["点击"], "twenty_four_hour": ["收藏"], "seven_day": ["复盘"]},
            "post_publish_correction": {"if_low_click": "LLM 修正建议"},
            "risks_or_missing_info": ["待发布验证"],
        }
        with patch("selfmedia.creation.platform_fit.call_creation_json", return_value=payload):
            fit = generate_platform_mechanism_fit(
                req,
                activity_candidates=[],
                viral_candidates=[],
                inspiration_candidates=[],
                business_candidates=[],
                reference_docs=[],
                media_context={},
            )
        self.assertEqual(fit["platform_mechanism_version"], "xiaohongshu_v1")
        self.assertEqual(fit["generation"]["provider"], "codex_responses")
        self.assertEqual(fit["generation"]["profile"], "media_creation")
        self.assertEqual(fit["generation"]["model"], "codex/gpt-5.6-terra")
        self.assertEqual(fit["generation"]["thinking"], "high")
        self.assertEqual(fit["platform_fit_meta"]["mechanism_source"], "llm")

    def test_platform_mechanism_fit_errors_when_llm_fails(self) -> None:
        req = parse_creation_request(
            "【创作>小红书】赛道=职场 类型=图文 主体=表达力 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        with patch("selfmedia.creation.platform_fit.call_creation_json", side_effect=RuntimeError("llm_json_parse_failed")):
            with self.assertRaisesRegex(RuntimeError, "LLM_SEMANTIC_PERSISTENCE_REQUIRED:platform_mechanism_fit"):
                generate_platform_mechanism_fit(
                    req,
                    activity_candidates=[],
                    viral_candidates=[],
                    inspiration_candidates=[],
                    business_candidates=[],
                    reference_docs=[],
                    media_context={},
                )

    def test_platform_mechanism_fit_rejects_algorithm_myth_claims(self) -> None:
        req = parse_creation_request(
            "【创作>小红书】赛道=自媒体 类型=图文 主体=选题方法 发布时间=2026-05-10 20:00",
            now=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        payload = {
            "platform_mechanism_version": "xiaohongshu_v1",
            "mechanism_claim_boundary": "这是机制拟合假设，不是平台真实算法或权重结论。",
            "mechanism_evidence_level": "C",
            "source_weights": {"llm": "C"},
            "platform_strategy": {"summary": "保证爆款"},
            "activity_strategy": {"hard_fit_risk": "low", "risk_reason": "LLM", "do_not_force": ["不硬蹭"]},
            "traffic_hypothesis": {"summary": "LLM"},
            "creation_reverse_plan": {"title": ["LLM"]},
            "validation_targets": {"two_hour": ["点击"]},
            "post_publish_correction": {"if_low_click": "LLM"},
            "risks_or_missing_info": ["待验证"],
        }
        with self.assertRaisesRegex(ValueError, "算法神化"):
            validate_platform_mechanism_fit_payload(payload, req)

    def test_parse_platform_mechanism_note_requires_llm(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "LLM_SEMANTIC_PERSISTENCE_REQUIRED:platform_mechanism_note:llm_disabled"):
            parse_platform_mechanism_note(
                "小红书",
                "知识型图文更依赖收藏理由和搜索长尾，前两页要给收藏理由。",
                source_type="creator_test",
                use_llm=False,
            )

    def test_platform_mechanism_observation_can_persist_from_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"SELFMEDIA_PLATFORM_MECHANISM_CONFIG_DIR": tmp}):
                with patch(
                    "selfmedia.creation.platform_fit.call_creation_json",
                    return_value={
                        "platform": "小红书",
                        "source_type": "creator_test",
                        "evidence_level": "C",
                        "hypotheses": [
                            {
                                "claim": "知识型图文需要明确收藏理由。",
                                "evidence_level": "C",
                                "applies_to": ["图文"],
                                "creation_action": ["前两页给收藏理由。"],
                                "validation_metrics": ["收藏率"],
                                "risk": "需要发布验证。",
                                "status": "candidate",
                            }
                        ],
                    },
                ):
                    parsed = parse_platform_mechanism_note(
                        "小红书",
                        "知识型图文更依赖收藏理由和搜索长尾。",
                        source_type="creator_test",
                        persist=True,
                    )

        self.assertEqual(parsed["evidence_level"], "C")
        self.assertEqual(parsed["hypotheses"][0]["status"], "candidate")

    def test_creation_workflow_uses_llm_draft_without_template_fallback(self) -> None:
        platform_fit = {
            "platform_mechanism_version": "xiaohongshu_v1",
            "mechanism_claim_boundary": "这是机制拟合假设，不是平台真实算法或权重结论。",
            "platform_fit_meta": {
                "mechanism_version": "xiaohongshu_v1",
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
            "script_options": [_xhs_graph_option(activity_ids=["act1"], viral_ids=["vir1"], inspiration_ids=["ins1"])],
            "recommended_option_id": "opt_1",
            "rejected_option_summaries": [],
        }
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        root = Path(tmp_dir) / "media_vault"
        evidence_uri = _write_deconstruction_v2_artifact(root, "vir1")
        with (
            patch.dict(os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": str(root)}),
            patch("selfmedia.creation.workflow.load_rows_for_creation") as load_rows,
            patch("selfmedia.creation.workflow.load_business_rows_for_creation", return_value=[]),
            patch("selfmedia.creation.workflow.load_inspiration_rows_for_creation") as load_inspirations,
            patch("selfmedia.creation.workflow.read_reference_docs", return_value=[]),
            patch("selfmedia.creation.workflow.generate_platform_mechanism_fit", return_value=platform_fit) as fit_generator,
            patch("selfmedia.creation.workflow.generate_creation_draft", return_value=llm_draft) as generate,
        ):
            load_rows.return_value = (
                [
                    {
                        "record_id": "vir1",
                        "fields": {
                            "asset_id": "asset1",
                            "deconstruction_id": "vir1",
                            "title": "表达力爆款",
                            "platform": "小红书",
                            "source_url": "https://example.com/viral",
                            "summary": "职场表达力真实复盘。",
                            "hook": "表达力卡住的真实瞬间。",
                            "transferable_points": "表达力图文结构。",
                            "evidence_uri": evidence_uri,
                            "review_status": "未复核",
                        },
                    }
                ],
                [
                    {
                        "record_id": "act1",
                        "fields": {
                            "标题": "表达力活动",
                            "平台名称": "小红书",
                            "主状态": "进行中",
                            "主话题": "表达力",
                            "子话题方向": "职场表达真实经历",
                            "活动Brief": "围绕表达力的真实经历创作。",
                            "填写要点": "讲具体场景、踩坑和复盘。",
                            "活动开始时间": "2026-06-01 00:00",
                            "活动结束时间": "2026-12-30 23:59",
                            "返稿链接": {"text": "返稿", "link": "https://example.com/submit"},
                        },
                    }
                ],
            )
            load_inspirations.return_value = [
                {
                    "record_id": "ins1",
                    "fields": {
                        "pattern_id": "ins1",
                        "pattern_name": "表达力模式",
                        "pattern_status": "validated_pattern",
                        "platform": "小红书",
                        "content_type": "图文",
                        "applicable_persona": "职场",
                        "applicable_scenarios": "表达力",
                        "structure_template": "一次真实表达卡住后的复盘。",
                        "emotional_levers": "表达力、职场",
                    },
                }
            ]
            result = handle_creation_command(
                "【创作>小红书】赛道=职场 类型=图文 主体=表达力 账号=主账号 发布时间=今晚8点",
                tenant_id="00000000-0000-4000-8000-000000000101",
                no_write=True,
            )
        self.assertTrue(generate.called)
        self.assertTrue(fit_generator.called)
        self.assertEqual(result["generation_mode"], "openclaw_llm_first")
        self.assertEqual(result["platform_fit"]["platform_mechanism_version"], "xiaohongshu_v1")
        self.assertEqual(generate.call_args.kwargs["platform_fit"]["platform_strategy"]["fit_summary"], "封面点击、收藏和评论要明确设计")
        self.assertEqual(result["draft"]["title"], "表达力这样练")
        self.assertEqual(result["activities"][0]["source_record_id"], "act1")
        self.assertEqual(result["virals"][0]["source_record_id"], "vir1")
        self.assertEqual(result["inspirations"][0]["source_record_id"], "ins1")

    def test_creation_workflow_skips_business_table_without_business_context(self) -> None:
        platform_fit = {
            "platform_mechanism_version": "xiaohongshu_v1",
            "platform_strategy": {"fit_summary": "按真实场景写"},
            "activity_strategy": {},
            "traffic_hypothesis": {},
            "creation_reverse_plan": {},
            "validation_targets": {},
        }
        llm_draft = {
            "platform": "小红书",
            "content_type": "图文",
            "title": "表达力这样练",
            "tags": ["小红书", "职场", "表达力", "沟通", "成长", "干货", "方法", "练习", "行动", "复盘"],
            "topic": "表达力",
            "final_copy": "用一个真实会议场景开头。",
            "inspiration": ["从候选素材中选择真实表达卡住的场景。"],
            "activity_constraint": {},
            "viral_reference": {},
            "inspiration_reference": {},
            "business_reference": {"matched": False},
            "account_context": {},
            "positioning_analysis": {},
            "platform_strategy": {},
            "activity_strategy": {},
            "traffic_hypothesis": {},
            "creation_reverse_plan": {},
            "validation_targets": {},
            "selected_activity_ids": [],
            "selected_viral_ids": [],
            "selected_inspiration_ids": [],
            "selected_business_ids": [],
            "image_script": ["封面：表达力卡住的真实瞬间"],
            "carousel": ["封面：表达力卡住的真实瞬间"],
            "hook_3s": "",
            "storyboard": [],
            "voiceover": "",
            "subtitles": [],
            "production_checklist": ["准备一个真实会议例子"],
            "review_plan": ["发布后看收藏和评论问题"],
            "risks_or_missing_info": [],
            "script_options": [_xhs_graph_option()],
            "recommended_option_id": "opt_1",
            "rejected_option_summaries": [],
        }
        with (
            patch("selfmedia.creation.workflow.load_rows_for_creation", return_value=([], [])),
            patch("selfmedia.creation.workflow.load_business_rows_for_creation") as load_business,
            patch("selfmedia.creation.workflow.load_inspiration_rows_for_creation", return_value=[]),
            patch("selfmedia.creation.workflow.read_reference_docs", return_value=[]),
            patch("selfmedia.creation.workflow.generate_platform_mechanism_fit", return_value=platform_fit),
            patch("selfmedia.creation.workflow.generate_creation_draft", return_value=llm_draft),
        ):
            result = handle_creation_command(
                "【创作>小红书】赛道=职场 类型=图文 主体=表达力 发布时间=今晚8点",
                tenant_id="00000000-0000-4000-8000-000000000101",
                no_write=True,
            )
        load_business.assert_not_called()
        self.assertEqual(result["candidate_counts"]["businesses"], 0)

    def test_creation_write_mode_calls_media_model_v2_writeback(self) -> None:
        platform_fit = {
            "platform_mechanism_version": "xiaohongshu_v1",
            "platform_strategy": {"fit_summary": "按真实场景写"},
            "activity_strategy": {},
            "traffic_hypothesis": {},
            "creation_reverse_plan": {},
            "validation_targets": {},
        }
        llm_draft = {
            "platform": "小红书",
            "content_type": "图文",
            "title": "表达力这样练",
            "tags": ["小红书", "职场", "表达力", "沟通", "成长", "干货", "方法", "练习", "行动", "复盘"],
            "topic": "表达力",
            "final_copy": "用一个真实会议场景开头。",
            "inspiration": ["从候选素材中选择真实表达卡住的场景。"],
            "activity_constraint": {},
            "viral_reference": {},
            "inspiration_reference": {},
            "business_reference": {"matched": False},
            "account_context": {},
            "positioning_analysis": {},
            "platform_strategy": {},
            "activity_strategy": {},
            "traffic_hypothesis": {},
            "creation_reverse_plan": {},
            "validation_targets": {},
            "selected_activity_ids": [],
            "selected_viral_ids": [],
            "selected_inspiration_ids": [],
            "selected_business_ids": [],
            "image_script": ["封面：表达力卡住的真实瞬间"],
            "carousel": ["封面：表达力卡住的真实瞬间"],
            "hook_3s": "",
            "storyboard": [],
            "voiceover": "",
            "subtitles": [],
            "production_checklist": ["准备一个真实会议例子"],
            "review_plan": ["发布后看收藏和评论问题"],
            "risks_or_missing_info": [],
            "script_options": [_xhs_graph_option()],
            "recommended_option_id": "opt_1",
            "rejected_option_summaries": [],
        }
        with (
            patch("selfmedia.creation.workflow.load_rows_for_creation", return_value=([], [])),
            patch("selfmedia.creation.workflow.load_business_rows_for_creation"),
            patch("selfmedia.creation.workflow.load_inspiration_rows_for_creation", return_value=[]),
            patch("selfmedia.creation.workflow.read_reference_docs", return_value=[]),
            patch("selfmedia.creation.workflow.generate_platform_mechanism_fit", return_value=platform_fit),
            patch("selfmedia.creation.workflow.generate_creation_draft", return_value=llm_draft),
            patch("selfmedia.creation.workflow.create_creation_doc", return_value="https://example.com/doc") as create_doc,
            patch("selfmedia.creation.workflow.record_creation_memory", return_value={"ok": True}),
            patch("selfmedia.creation.workflow.write_creation_model_v2", return_value={"run_id": "run_rec_creation", "decision_trace_count": 0}) as write_v2,
        ):
            result = handle_creation_command(
                "【创作>小红书】赛道=职场 类型=图文 主体=表达力 发布时间=今晚8点",
                tenant_id="00000000-0000-4000-8000-000000000101",
            )
        self.assertTrue(create_doc.called)
        self.assertTrue(write_v2.called)
        self.assertEqual(write_v2.call_args.kwargs["creation_record_id"], "")
        self.assertEqual(result["media_model_v2"]["run_id"], "run_rec_creation")
        self.assertEqual(result["creation_record_id"], "run_rec_creation")

    def test_creation_consultation_loads_activity_only_when_question_asks(self) -> None:
        general_request = parse_consultation_request("【创作咨询】平台=小红书 问题=这个选题怎么讲更有记忆点")
        activity_request = parse_consultation_request("【创作咨询】平台=小红书 问题=这个选题适合参加哪个活动")

        self.assertFalse(request_needs_activity_candidates(general_request))
        self.assertTrue(request_needs_activity_candidates(activity_request))

        with (
            patch("selfmedia.creation.consultation.load_rows_for_creation", return_value=([], [])) as load_rows,
            patch("selfmedia.creation.consultation.load_business_rows_for_creation", return_value=[]),
            patch("selfmedia.creation.consultation.load_inspiration_rows_for_creation", return_value=[]),
            patch("selfmedia.creation.consultation.read_reference_docs", return_value=[]),
            patch("selfmedia.creation.consultation.build_media_context", return_value={}),
            patch("selfmedia.creation.consultation.generate_consultation_answer", return_value={"reply": "ok"}),
        ):
            handle_creation_consultation_command("【创作咨询】平台=小红书 问题=这个选题怎么讲更有记忆点", tenant_id="00000000-0000-4000-8000-000000000101")
            self.assertFalse(load_rows.call_args.kwargs["include_activity"])

            handle_creation_consultation_command("【创作咨询】平台=小红书 问题=这个选题适合参加哪个活动", tenant_id="00000000-0000-4000-8000-000000000101")
            self.assertTrue(load_rows.call_args.kwargs["include_activity"])

    def test_creation_consultation_parser_requires_entry_and_question(self) -> None:
        with self.assertRaisesRegex(ValueError, "不是【创作咨询】入口"):
            parse_consultation_request("问题=这个选题怎么讲")
        with self.assertRaisesRegex(ValueError, "缺少问题"):
            parse_consultation_request("【创作咨询】")

        request = parse_consultation_request("【创作咨询】\n问题：商务合作建联信息应该怎么写")
        self.assertEqual(request.question, "商务合作建联信息应该怎么写")

    def test_creation_workflow_rejects_draft_without_script_options(self) -> None:
        platform_fit = {
            "platform_mechanism_version": "xiaohongshu_v1",
            "platform_strategy": {},
            "activity_strategy": {},
            "traffic_hypothesis": {},
            "creation_reverse_plan": {},
            "validation_targets": {},
        }
        with (
            patch("selfmedia.creation.workflow.load_rows_for_creation", return_value=([], [])),
            patch("selfmedia.creation.workflow.load_business_rows_for_creation"),
            patch("selfmedia.creation.workflow.load_inspiration_rows_for_creation", return_value=[]),
            patch("selfmedia.creation.workflow.read_reference_docs", return_value=[]),
            patch("selfmedia.creation.workflow.generate_platform_mechanism_fit", return_value=platform_fit),
            patch("selfmedia.creation.workflow.generate_creation_draft", return_value={"platform": "小红书", "content_type": "图文", "title": "旧单稿"}),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing_script_options_or_recommendation"):
                handle_creation_command(
                    "【创作>小红书】赛道=职场 类型=图文 主体=表达力 发布时间=今晚8点",
                    tenant_id="00000000-0000-4000-8000-000000000101",
                    no_write=True,
                )


if __name__ == "__main__":
    unittest.main()
