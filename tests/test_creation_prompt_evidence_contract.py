from selfmedia.creation.llm_generator import (
    _compact_candidates,
    _validate_insight_card_reference_boundary,
)
from selfmedia.creation.platform_fit import _truncate_nested


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
