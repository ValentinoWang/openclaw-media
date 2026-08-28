from __future__ import annotations

import json

import pytest

from common.llm_client import DEFAULT_JSON_OUTPUT_INSTRUCTIONS
from selfmedia.creation import backwash
from selfmedia.creation.llm_generator import (
    _creation_role_instructions,
    build_creation_prompt,
    validate_llm_draft_payload,
)
from selfmedia.creation.platform_validator import validate_platform_draft
from selfmedia.creation.request_parser import CreationRequest
from test_creation_anti_pattern_validation import _payload, _request


def _backwash_context_json(prompt: str) -> str:
    return prompt.split("账号与创作上下文：\n", 1)[1].split("\n\n当前结构化执行单：", 1)[0]


def test_ai_phrase_guard_preserves_a_complete_must_keep_sentence() -> None:
    payload = _payload()
    payload["script_options"][0]["title"] = "为跑步训练赋能"  # type: ignore[index]

    draft = validate_llm_draft_payload(
        payload,
        _request(),
        must_keep=("品牌名必须保留：为跑步训练赋能。",),
    )

    assert draft["title"] == "为跑步训练赋能"


def test_ai_phrase_guard_rejects_an_unpreserved_template_phrase() -> None:
    payload = _payload()
    payload["script_options"][0]["title"] = "为跑步训练赋能"  # type: ignore[index]

    with pytest.raises(ValueError, match="推荐稿 title 包含通用模板表达：赋能"):
        validate_llm_draft_payload(payload, _request(), must_keep=("保留品牌名",))


def test_tags_bounds_and_prompt_contract_agree_for_xiaohongshu_and_douyin() -> None:
    xhs_prompt = build_creation_prompt(
        CreationRequest(platform="小红书", content_type="图文", track="体育", topic="跑步", publish_time=""),
        activity_candidates=[],
        viral_candidates=[],
        inspiration_candidates=[],
        business_candidates=[],
        reference_docs=[],
        media_context={},
    )
    douyin_prompt = build_creation_prompt(
        CreationRequest(platform="抖音", content_type="视频", track="体育", topic="跑步", publish_time=""),
        activity_candidates=[],
        viral_candidates=[],
        inspiration_candidates=[],
        business_candidates=[],
        reference_docs=[],
        media_context={},
    )
    douyin_video = {
        "title": "跑步热身",
        "hook_3s": "先别急着加速",
        "storyboard": ["先慢跑热身"],
        "voiceover": "先热身，再加速。",
        "subtitles": ["先热身，再加速。"],
    }

    assert "tags 必须给 3-10 个" in xhs_prompt
    assert "tags 必须给 2-5 个" in douyin_prompt
    assert validate_platform_draft(
        "小红书",
        "图文",
        {"title": "跑步热身", "tags": ["跑步", "热身", "训练"], "carousel": ["封面", "动作拆解"]},
    ).ok
    assert not validate_platform_draft(
        "小红书",
        "图文",
        {"title": "跑步热身", "tags": [str(index) for index in range(11)], "carousel": ["封面"]},
    ).ok
    assert validate_platform_draft("抖音", "视频", {**douyin_video, "tags": ["跑步", "热身"]}).ok
    assert not validate_platform_draft(
        "抖音",
        "视频",
        {**douyin_video, "tags": [str(index) for index in range(6)]},
    ).ok


def test_creation_roles_and_default_json_protocol_do_not_use_engine_personas() -> None:
    assert "引擎" not in DEFAULT_JSON_OUTPUT_INSTRUCTIONS
    assert "输出协议" in DEFAULT_JSON_OUTPUT_INSTRUCTIONS
    for contract, role in (
        ("selfmedia.creation.request_inference.v1", "需求解析员"),
        ("selfmedia.creation.consultation.v1", "创作咨询同事"),
        ("selfmedia.creation.shooting_plan.v1", "拍摄导演"),
        ("selfmedia.creation.shooting_backwash_review.v1", "审稿编辑"),
        ("selfmedia.creation.draft.v1", "中文自媒体主编"),
    ):
        instructions = _creation_role_instructions(contract)
        assert role in instructions
        assert "JSON 输出引擎" not in instructions


def test_backwash_prompt_contexts_remain_valid_json_when_bounded() -> None:
    media_context = {"account_profile": {"bio": "账号语言样本" * 2_000}}
    narrative_prompt = backwash._narrative_plan_prompt({}, "按事实调整", media_context)
    revision_prompt = backwash._revision_prompt({}, "按事实调整", media_context, {})

    for prompt in (narrative_prompt, revision_prompt):
        encoded_context = _backwash_context_json(prompt)
        assert "上下文字段已截断" in encoded_context
        assert isinstance(json.loads(encoded_context), dict)
