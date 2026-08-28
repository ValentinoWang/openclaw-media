from __future__ import annotations

from selfmedia.growth.service import GROWTH_CAPABILITY_PROMPTS


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
