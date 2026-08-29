from __future__ import annotations

from selfmedia.creation.llm_generator import build_creation_prompt
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
