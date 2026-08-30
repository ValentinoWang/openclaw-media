from __future__ import annotations

from selfmedia.creation.llm_generator import MATCH_ASSESSMENT_LIMITS, build_creation_prompt
from selfmedia.creation.request_parser import CreationRequest


def test_creation_prompt_keeps_execution_and_evidence_contracts() -> None:
    request = CreationRequest(
        platform="抖音",
        content_type="视频",
        track="运动",
        topic="跑步训练",
        publish_time="2026-08-29 12:00",
    )

    prompt = build_creation_prompt(
        request,
        activity_candidates=[],
        viral_candidates=[],
        inspiration_candidates=[],
        business_candidates=[],
        reference_docs=[],
        media_context={"recent_reviews": [{"summary": "上一轮开头过长"}]},
    )

    for anchor in (
        "creator_report 必须分两层",
        "证据附录只能放在最后",
        "复盘必须回流",
        "商单必须落到执行",
        "first_hour_action",
        "综上",
    ):
        assert anchor in prompt


def test_creation_prompt_match_assessment_weights_derive_from_the_single_source_of_truth() -> None:
    # prompt-c6-score-weights: the prompt's constraint clause and its example
    # structure are generated from MATCH_ASSESSMENT_LIMITS (the constant the
    # code-side cap check actually consumes) rather than hand-copied, so this
    # pins that every field/weight pair the constant declares shows up in the
    # prompt text, and that the example values never exceed their limit.
    request = CreationRequest(
        platform="抖音",
        content_type="视频",
        track="运动",
        topic="跑步训练",
        publish_time="2026-08-29 12:00",
    )

    prompt = build_creation_prompt(
        request,
        activity_candidates=[],
        viral_candidates=[],
        inspiration_candidates=[],
        business_candidates=[],
        reference_docs=[],
        media_context={},
    )

    for fields in MATCH_ASSESSMENT_LIMITS.values():
        for field, weight in fields.items():
            assert f"{field}({weight})" in prompt

    import json
    import re

    match = re.search(r"candidate_match_assessments 示例结构：(\{.*?\})。", prompt)
    assert match, "prompt must contain the candidate_match_assessments example structure"
    example = json.loads(match.group(1))
    for kind, fields in MATCH_ASSESSMENT_LIMITS.items():
        example_breakdown = example[kind][0]["score_breakdown"]
        for field, weight in fields.items():
            assert 0 < example_breakdown[field] <= weight
