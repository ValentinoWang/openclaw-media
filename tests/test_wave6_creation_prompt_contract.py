from __future__ import annotations

import pytest

from selfmedia.creation.llm_generator import build_creation_prompt, validate_llm_draft_payload
from test_creation_anti_pattern_validation import _payload, _request


def test_prompt_consolidates_duplicate_direction_requirements() -> None:
    prompt = build_creation_prompt(
        _request(),
        activity_candidates=[],
        viral_candidates=[],
        inspiration_candidates=[],
        business_candidates=[],
        reference_docs=[],
        media_context={},
    )

    assert prompt.count("至少 2 个") == 1
    assert "模型输出的核心字段为" in prompt
    assert "report_mode 由程序注入，不要输出" in prompt
    assert "总分由程序求和，不要输出 score" in prompt


@pytest.mark.parametrize("field", ("title", "final_copy", "hook_3s", "voiceover"))
@pytest.mark.parametrize("phrase", ("总之", "综上"))
def test_prompt_declared_short_template_phrases_are_rejected(field: str, phrase: str) -> None:
    payload = _payload()
    payload["script_options"][0][field] = f"{phrase}，这段表达需要重写。"  # type: ignore[index]

    with pytest.raises(ValueError, match=phrase):
        validate_llm_draft_payload(payload, _request())


def test_prompt_declared_enumeration_sequence_is_rejected_unless_preserved() -> None:
    payload = _payload()
    text = "首先看呼吸，其次看步频，最后再提速。"
    payload["script_options"][0]["voiceover"] = text  # type: ignore[index]

    with pytest.raises(ValueError, match="首先/其次/最后"):
        validate_llm_draft_payload(payload, _request())

    draft = validate_llm_draft_payload(payload, _request(), must_keep=(text,))
    assert draft["voiceover"] == text
