import pytest

from selfmedia.creation.llm_generator import (
    _compact_candidates,
    _creation_role_instructions,
    _validate_insight_card_reference_boundary,
    normalize_comment_evidence_for_prompt,
    validate_llm_draft_payload,
)
from selfmedia.creation.field_contract import CanonicalMediaRecord
from selfmedia.creation.platform_fit import _truncate_nested, build_platform_mechanism_prompt
from selfmedia.creation.request_parser import CreationRequest
from selfmedia.creation.workflow import _record_candidate_payload
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
            "source_mapping": [{
                "source": "insight_card:被理解感",
                "reference_type": "insight_card",
                "evidence_boundary": "public_content_only",
                "note": "它不是源视频事实。",
            }],
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


def test_platform_fit_candidate_compaction_keeps_adaptation_evidence_after_metadata() -> None:
    candidate = {f"metadata_{index}": index for index in range(35)}
    candidate.update(
        {
            "id": "viral-1",
            "cover_opening_hook": "先给结果，再展示过程。",
            "viral_migration": "把冲突迁移到训练前的犹豫。",
            "reference_shots": [{"shot_id": "shot-1", "framing": "近景"}],
            "reference_production_summary": "近景展示动作，随后用全景交代环境。",
        }
    )
    request = CreationRequest(platform="抖音", content_type="视频", track="体育", topic="跑步", publish_time="")

    prompt = build_platform_mechanism_prompt(
        request,
        activity_candidates=[],
        viral_candidates=[candidate],
        inspiration_candidates=[],
        business_candidates=[],
        reference_docs=[],
        media_context={},
    )

    assert "先给结果，再展示过程。" in prompt
    assert "把冲突迁移到训练前的犹豫。" in prompt
    assert '"shot_id": "shot-1"' in prompt
    assert "近景展示动作，随后用全景交代环境。" in prompt
    assert '"_truncated_keys"' in prompt


def test_platform_fit_candidate_compaction_keeps_activity_constraints() -> None:
    request = CreationRequest(platform="抖音", content_type="视频", track="体育", topic="跑步", publish_time="")
    prompt = build_platform_mechanism_prompt(
        request,
        activity_candidates=[
            {
                "id": "activity-1",
                "activity_brief": "投稿需在活动截止前完成，并使用指定话题。",
                "participation_requirement": "必须提交完整视频和报名信息。",
            }
        ],
        viral_candidates=[],
        inspiration_candidates=[],
        business_candidates=[],
        reference_docs=[],
        media_context={},
    )

    assert "投稿需在活动截止前完成，并使用指定话题。" in prompt
    assert "必须提交完整视频和报名信息。" in prompt


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


def test_comment_evidence_keeps_long_insight_multiple_quotes_and_provenance() -> None:
    long_insight = "评论洞察" * 120
    record = CanonicalMediaRecord(
        source_table="02B_MaterialDeconstructions_素材拆解",
        source_record_id="viral-1",
        relation_id="viral-1",
        record_type="爆款素材",
        detail_json={
            "top_comment_insight": long_insight,
            "comment_evidence": {
                "status": "verified_three_comments",
                "comments": [
                    {"comment_id": "c-low", "text": "低互动原话", "like_count": 2, "source_method": "xiaohongshu.web"},
                    {"comment_id": "c-high", "text": "高互动原话", "like_count": 88, "source_method": "xiaohongshu.api"},
                    {"comment_id": "c-mid", "text": "中互动原话", "like_count": 32, "source_method": "xiaohongshu.api"},
                ],
            },
        },
    )

    compacted = _compact_candidates([_record_candidate_payload(record)], 1)[0]

    assert compacted["top_comment_insight"] == long_insight
    assert [item["comment_id"] for item in compacted["comment_evidence"]["comments"]] == ["c-high", "c-mid", "c-low"]
    assert compacted["comment_evidence"]["comments"][0]["interaction"]["like_count"] == 88
    assert compacted["comment_evidence"]["comments"][0]["evidence_source"] == "xiaohongshu.api"
    assert compacted["comment_evidence"]["fact_status"] == "not_verified_as_fact"


def test_comment_evidence_requires_separate_refs_or_explicit_insufficiency() -> None:
    request = CreationRequest(platform="抖音", content_type="视频", track="体育", topic="跑步", publish_time="2026-08-29 20:00")
    candidate_ids = {
        "selected_activity_ids": {"act1"},
        "selected_viral_ids": {"vir1"},
        "selected_inspiration_ids": {"ins1"},
        "selected_business_ids": set(),
    }
    available = normalize_comment_evidence_for_prompt(
        {"comments": [{"comment_id": "comment-1", "text": "我也遇到这个问题", "like_count": 12, "source_method": "douyin.web"}]}
    )
    payload = _multi_option_payload([_script_option(score=91), _script_option("opt_2", score=88)])
    publishing_pack = payload["creator_report"]["publishing_pack"]
    publishing_pack.update(
        {
            "comment_evidence_status": "available",
            "pinned_comment_evidence_refs": ["vir1:comment_001"],
            "comment_prompt_evidence_refs": ["vir1:comment_001"],
        }
    )

    validate_llm_draft_payload(payload, request, candidate_ids=candidate_ids, comment_evidence_by_viral={"vir1": available})

    publishing_pack["comment_prompt_evidence_refs"] = []
    with pytest.raises(ValueError, match="comment_prompt_evidence_refs"):
        validate_llm_draft_payload(payload, request, candidate_ids=candidate_ids, comment_evidence_by_viral={"vir1": available})

    insufficient = normalize_comment_evidence_for_prompt({"status": "no_comments", "reason": "no_top_comments_captured", "comments": []})
    assert insufficient["status"] == "insufficient_evidence"
    assert insufficient["fact_status"] == "not_verified_as_fact"
    publishing_pack.update(
        {
            "comment_evidence_status": "insufficient_evidence",
            "pinned_comment_evidence_refs": [],
            "comment_prompt_evidence_refs": [],
        }
    )
    validate_llm_draft_payload(payload, request, candidate_ids=candidate_ids, comment_evidence_by_viral={"vir1": insufficient})
