from selfmedia.creation.llm_generator import (
    _compact_candidates,
    _creation_role_instructions,
    _validate_insight_card_reference_boundary,
    validate_llm_draft_payload,
)
from selfmedia.creation.platform_fit import _truncate_nested
from selfmedia.creation.request_parser import CreationRequest
from test_creation_v1 import _multi_option_payload, _script_option


def test_viral_candidate_compaction_keeps_shot_and_production_evidence() -> None:
    compacted = _compact_candidates(
        [
            {
                "id": "viral-1",
                "reference_shots": [{"shot_id": "shot-1", "framing": "近景"}],
                "reference_production_summary": "先用近景展示错误动作，再切全景纠正。",
            }
        ],
        10,
    )

    assert compacted[0]["reference_shots"][0]["shot_id"] == "shot-1"
    assert "近景" in compacted[0]["reference_production_summary"]


def test_insight_card_boundary_accepts_explicit_source_fact_disclaimer() -> None:
    draft = {
        "selected_inspiration_ids": ["insight_card:被理解感"],
        "usable_material_brief": {
            "note": "insight-card reference；public_content_only；它不是源视频事实。",
        },
        "inspiration_reference": {},
        "creator_report": {},
        "script_options": [],
        "candidate_match_assessments": {"inspiration": []},
    }

    _validate_insight_card_reference_boundary(draft)


def test_platform_fit_truncation_reports_omitted_key_count() -> None:
    payload = {f"field_{index}": index for index in range(35)}

    compacted = _truncate_nested(payload, 100)

    assert compacted["_truncated_keys"] == 5
    assert "field_29" in compacted
    assert "field_30" not in compacted


def test_scores_are_derived_from_breakdowns_instead_of_model_arithmetic() -> None:
    payload = _multi_option_payload([_script_option(score=91), _script_option("opt_2", score=88)])
    payload["script_options"][0]["score"] = 1
    payload["candidate_match_assessments"]["viral"][0]["score"] = 1
    request = CreationRequest(platform="抖音", content_type="视频", track="体育", topic="跑步", publish_time="2026-08-29 20:00")

    validated = validate_llm_draft_payload(
        payload,
        request,
        candidate_ids={
            "selected_activity_ids": {"act1"},
            "selected_viral_ids": {"vir1"},
            "selected_inspiration_ids": {"ins1"},
            "selected_business_ids": set(),
        },
    )

    assert validated["script_options"][0]["score"] == 91
    assert validated["candidate_match_assessments"]["viral"][0]["score"] == 84


def test_creation_roles_follow_validation_contract_responsibility() -> None:
    request_role = _creation_role_instructions("selfmedia.creation.request_inference.v1")
    shooting_role = _creation_role_instructions("selfmedia.creation.shooting_plan.v1")
    review_role = _creation_role_instructions("selfmedia.creation.shooting_backwash_review.v1")

    assert "需求解析员" in request_role
    assert "拍摄导演" in shooting_role
    assert "审稿编辑" in review_role
    assert len({request_role, shooting_role, review_role}) == 3
