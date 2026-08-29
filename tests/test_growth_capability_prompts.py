from __future__ import annotations

from selfmedia.growth.capability_registry import capability_creator_field_mappings, capability_consumes
from selfmedia.growth.service import GROWTH_CAPABILITY_PROMPTS
from selfmedia.growth.llm_runner import GROWTH_JSON_INSTRUCTIONS


def test_growth_system_instructions_require_natural_chinese_creator_copy() -> None:
    assert "所有创作者可见字段必须使用自然、具体的中文" in GROWTH_JSON_INSTRUCTIONS
    assert "禁止英文句式直译或机器腔" in GROWTH_JSON_INSTRUCTIONS
    assert "JSON 键名保持既有合同" in GROWTH_JSON_INSTRUCTIONS


def test_growth_capability_prompts_require_chinese_creator_copy() -> None:
    assert set(GROWTH_CAPABILITY_PROMPTS) == {
        "external_research_brief",
        "commercial_brief",
        "creation_decision_brief",
        "publishing_pack_build",
    }

    for prompt in GROWTH_CAPABILITY_PROMPTS.values():
        assert prompt.startswith("请")
        assert "所有面向创作者显示的文字均使用中文" in prompt
        assert "JSON 键名保持既有合同，不要翻译或新增字段" in prompt
        assert "Fill a " not in prompt
        assert "Fill an " not in prompt
        assert "Return JSON fields" not in prompt


def test_publishing_pack_prompt_requires_natural_spoken_chinese() -> None:
    prompt = GROWTH_CAPABILITY_PROMPTS["publishing_pack_build"]

    assert "可直接口播" in prompt
    assert "避免书面套话、空泛承诺和英文平台术语" in prompt
    assert "不得声称已经自动发布" in prompt
    assert "title 对齐主创作链 title_1" in prompt
    assert "caption 对齐 body_copy" in prompt


def test_growth_prompts_share_main_creation_topic_vocabulary() -> None:
    prompt = GROWTH_CAPABILITY_PROMPTS["creation_decision_brief"]

    assert "pain_point" in prompt
    assert "账号画像和复盘结论" in prompt
    assert "audience_pain 会由系统兼容映射" in prompt


def test_registry_declares_only_loaded_review_evidence_and_field_mappings() -> None:
    assert capability_consumes("post_review_signal") == ()
    assert capability_consumes("creation_decision_brief")[-1] == "ReviewSignal"
    assert capability_creator_field_mappings("creation_decision_brief") == {
        "topic_candidates[].pain_point": (
            "topic_candidates[].pain_point",
            "topic_candidates[].audience_pain",
        ),
    }
    assert capability_creator_field_mappings("publishing_pack_build")["body_copy"] == ("caption",)
