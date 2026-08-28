from __future__ import annotations

from copy import deepcopy
import unittest

from selfmedia.creation.llm_generator import CREATOR_BRIEF_REPORT_MODE, validate_llm_draft_payload
from selfmedia.creation.request_parser import CreationRequest
from selfmedia.style.context_loader import load_anti_patterns


def _request() -> CreationRequest:
    return CreationRequest(
        platform="抖音",
        content_type="视频",
        track="运动",
        topic="跑步训练",
        publish_time="2026-08-28 12:00",
    )


def _score_breakdown() -> dict[str, int]:
    return {
        "evidence_grounding": 20,
        "platform_fit": 15,
        "audience_pain": 15,
        "creative_angle": 15,
        "execution_completeness": 15,
        "reference_integration": 15,
        "risk_control": 0,
    }


def _option(option_id: str) -> dict[str, object]:
    return {
        "option_id": option_id,
        "score": 95,
        "score_breakdown": _score_breakdown(),
        "title": "跑步训练的一个小调整",
        "angle": "从热身动作切入训练节奏。",
        "score_reason": "场景具体，能够直接拍摄。",
        "selected_activity_ids": [],
        "selected_viral_ids": [],
        "selected_inspiration_ids": [],
        "selected_business_ids": [],
        "activity_fit_reason": "没有活动约束。",
        "viral_reference_reason": "没有引用爆款素材。",
        "inspiration_reference_reason": "没有引用灵感素材。",
        "risk_level": "low",
        "risks_or_missing_info": [],
        "tags": ["跑步", "训练", "运动"],
        "final_copy": "先跑慢一点，再把呼吸找回来。",
        "image_script": [],
        "carousel": [],
        "hook_3s": "你跑步时，先别急着加速。",
        "storyboard": [{"scene": "操场", "visual": "慢跑热身"}],
        "voiceover": "今天只练一件事，把呼吸和步频对齐。",
        "subtitles": ["先把呼吸找回来"],
        "production_checklist": ["拍摄热身动作"],
        "review_plan": ["观察完播反馈"],
    }


def _creator_report() -> dict[str, object]:
    return {
        "overview": {
            "recommended_topic": "跑步训练的一个小调整",
            "core_sentence": "先找回呼吸，再加速度。",
            "platform": "抖音",
            "content_type": "视频",
            "suitable_activity": "无",
            "strongly_recommend_activity": "不参与活动。",
            "biggest_risk": "不要夸大训练效果。",
        },
        "opening_3s": {
            "visual_0_0_5": "操场慢跑热身。",
            "caption_or_voice_0_5_3": "先别急着加速。",
            "do_not_open_like_this": "不要先讲训练理论。",
        },
        "mainline": {
            "conflict": "想加速和呼吸没跟上之间的矛盾。",
            "evidence": "热身和慢跑动作。",
            "emotional_payoff": "身体找回节奏。",
            "audience_resonance": "跑步时容易急。",
        },
        "storyboard": [
            {
                "time": "0-3s",
                "visual": "操场慢跑热身。",
                "subtitle": "先别急着加速。",
                "sound": "脚步声。",
                "shooting_note": "镜头跟随脚步。",
            }
        ],
        "publishing_pack": {
            "title_1": "跑步训练的一个小调整",
            "title_2": "跑步前先找回呼吸",
            "cover_text": "先找回呼吸",
            "body_copy": "先跑慢一点，再把呼吸找回来。",
            "hashtags": ["跑步", "训练", "运动"],
            "pinned_comment": "你跑步时最容易急在哪一步？",
            "comment_prompt": "聊聊你的热身习惯。",
            "first_hour_action": "回复前十条有效评论。",
        },
        "material_checklist": {
            "must_have": ["操场画面"],
            "better_to_have": ["脚步特写"],
            "can_rescue_without": ["没有特写就用全景"],
            "must_not_fabricate": ["不要写训练数据"],
        },
        "risk_controls": [{"condition": "没有训练数据", "rewrite_or_action": "不写训练效果。"}],
        "evidence_appendix": {
            "activities": [],
            "viral_refs": [],
            "inspiration_refs": [],
            "business_info": "无",
            "scoring_and_record_ids": [],
        },
    }


def _payload() -> dict[str, object]:
    return {
        "platform": "抖音",
        "content_type": "视频",
        "topic": "跑步训练",
        "inspiration": ["从热身动作开始。"],
        "activity_constraint": {"summary": "无"},
        "viral_reference": {"summary": "无"},
        "inspiration_reference": {"summary": "无"},
        "business_reference": {"summary": "无"},
        "account_context": {"summary": "无"},
        "positioning_analysis": {"positioning": "跑步训练"},
        "content_core": {
            "content_promise": "帮助跑者找回热身节奏。",
            "viewer_problem": "跑步前容易着急。",
            "specific_scene": "操场慢跑。",
            "memorable_point": "先找回呼吸。",
            "must_show": ["慢跑动作"],
        },
        "topic_strategy": {
            "target_audience": "初跑者",
            "pain_point": "起跑太急。",
            "content_angle": "热身节奏。",
            "single_problem": "怎么进入跑步节奏。",
            "self_check": "画面有真实动作。",
        },
        "usable_material_brief": {
            "execution_brief": "拍热身动作。",
            "source_mapping": ["训练场景"],
            "usage_boundaries": ["不写训练数据"],
        },
        "platform_strategy": {"summary": "动作前置"},
        "activity_strategy": {"summary": "无"},
        "traffic_hypothesis": {"summary": "真实动作提高停留"},
        "creation_reverse_plan": {"summary": "先拍热身"},
        "validation_targets": {"summary": "观察完播"},
        "script_options": [_option("recommended"), _option("alternate")],
        "recommended_option_id": "recommended",
        "editor_pass": {
            "recommended_option_id": "recommended",
            "blandness_risks": [],
            "revisions_applied": [],
            "final_recommendation_reason": "动作清楚。",
        },
        "candidate_match_assessments": {"viral": [], "inspiration": []},
        "report_mode": dict(CREATOR_BRIEF_REPORT_MODE),
        "creator_report": _creator_report(),
    }


class CreationAntiPatternValidationTests(unittest.TestCase):
    def test_rejects_configured_phrase_in_each_recommended_user_visible_field(self) -> None:
        phrase = "赋能"
        self.assertIn(phrase, load_anti_patterns())
        for field in ("title", "final_copy", "hook_3s", "voiceover"):
            with self.subTest(field=field):
                payload = _payload()
                payload["script_options"][0][field] = f"这句话包含{phrase}"  # type: ignore[index]
                with self.assertRaisesRegex(ValueError, rf"{field}.*{phrase}"):
                    validate_llm_draft_payload(payload, _request())

    def test_allows_a_phrase_explicitly_preserved_by_must_keep(self) -> None:
        payload = _payload()
        payload["script_options"][0]["title"] = "为跑步训练赋能"  # type: ignore[index]

        draft = validate_llm_draft_payload(payload, _request(), must_keep=("赋能",))

        self.assertEqual(draft["title"], "为跑步训练赋能")

    def test_ignores_an_anti_pattern_in_a_non_recommended_option(self) -> None:
        payload = _payload()
        payload["script_options"][1]["voiceover"] = "这段口播只给跑步赋能"  # type: ignore[index]

        draft = validate_llm_draft_payload(payload, _request())

        self.assertEqual(draft["recommended_option_id"], "recommended")


if __name__ == "__main__":
    unittest.main()
