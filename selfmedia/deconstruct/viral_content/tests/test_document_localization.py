from __future__ import annotations

import json

from selfmedia.deconstruct.viral_content.src.feishu_doc_writer import _deconstruct_doc_blocks
from selfmedia.deconstruct.viral_content.src.feishu_writer import _shot_adaptation_bitable_index


def test_deconstruction_document_localizes_known_fields_and_values() -> None:
    blocks = _deconstruct_doc_blocks(
        {
            "human_readable_brief": {
                "source_summary": "先展示结果。",
                "why_it_may_work": "结果明确。",
                "account_fit_reason": "适合本地生活账号。",
                "usable_patterns": ["结果前置"],
                "recommended_script_directions": ["用自有门店重拍"],
                "must_transform": ["更换人物和文案"],
                "must_not_copy": ["不照搬原句"],
                "human_review_flags": ["human_review_required"],
            },
            "viral_reuse_assessment": {
                "final_label": "strong_reuse_candidate",
                "confidence": 0.82,
                "observed_virality": {"level": "unknown", "reason": "没有公开热度数据"},
                "mechanism_strength": {"level": "strong", "reason": "结果明确"},
                "human_review_required": True,
            },
            "pacing_profile": {
                "llm_interpretation": {
                    "summary": "首三秒展示结果。",
                    "rhythm_pattern": "结果、提问、过程。",
                    "edit_recommendations": ["问题后短暂停顿"],
                    "reuse_notes": "用自有制作过程承接。",
                }
            },
            "reuse_guardrails": {"human_review_required": False},
            "speech_transcript": {"status": "no_audio", "reason": "未提供音频"},
        },
        include_evidence_appendix=True,
    )

    rendered = json.dumps(blocks, ensure_ascii=False)

    for expected in (
        "素材概括：先展示结果。",
        "为什么可能有效：结果明确。",
        "账号契合原因：适合本地生活账号。",
        "可复用打法：结果前置",
        "建议脚本方向：用自有门店重拍",
        "必须改造：更换人物和文案",
        "禁止照搬：不照搬原句",
        "需人工确认：需要人工确认",
        "复用结论：强复用候选；置信度：0.82",
        "可见热度：未知；没有公开热度数据",
        "人工复核：是",
        "节奏概述：首三秒展示结果。",
        "节奏模式：结果、提问、过程。",
        "剪辑建议：问题后短暂停顿",
        "复用提示：用自有制作过程承接。",
        "状态：无音频",
    ):
        assert expected in rendered

    for internal_value in (
        "source_summary",
        "why_it_may_work",
        "recommended_script_directions",
        "human_review_required",
        "strong_reuse_candidate",
        "confidence=",
        "unknown",
        "summary",
        "rhythm_pattern",
        "edit_recommendations",
        "reuse_notes",
        "no_audio",
    ):
        assert internal_value not in rendered


def test_unknown_document_status_is_not_mislabeled_or_exposed() -> None:
    blocks = _deconstruct_doc_blocks(
        {
            "viral_reuse_assessment": {"final_label": "new_candidate_state"},
            "speech_transcript": {"status": "future_audio_state"},
        }
    )
    rendered = json.dumps(blocks, ensure_ascii=False)

    assert "复用结论：状态待确认" in rendered
    assert "状态：状态待确认" in rendered
    assert "new_candidate_state" not in rendered
    assert "future_audio_state" not in rendered


def test_bitable_shot_summary_localizes_status_and_points_to_document() -> None:
    index = _shot_adaptation_bitable_index(
        {
            "deconstruct_doc_url": "https://example.feishu.cn/docx/deconstruct-001",
            "multi_signal_contract": {
                "validation": {"multi_signal_contract_status": "validated_with_warnings"},
                "shot_adaptation_notes": [
                    {
                        "note_id": f"shot_note_{number:03d}",
                        "learnable_pattern": f"结构{number}",
                        "adaptation_rule": f"改法{number}",
                        "do_not_copy": [f"禁用{number}"],
                    }
                    for number in range(1, 10)
                ],
            },
        }
    )

    assert index["shot_adaptation_notes_status"] == "已验证，存在待确认项"
    assert "可学结构：结构1；适配方法：改法1；避免照搬：禁用1" in index["shot_adaptation_notes_summary"]
    assert "共 9 条，完整清单见拆解文档证据附录：https://example.feishu.cn/docx/deconstruct-001" in index["shot_adaptation_notes_summary"]
    assert "validated_with_warnings" not in index["shot_adaptation_notes_status"]
    assert "shot_note_001" not in index["shot_adaptation_notes_summary"]
    assert "multi_signal_contract" not in index["shot_adaptation_notes_summary"]


def test_bitable_unknown_status_is_truthfully_pending() -> None:
    index = _shot_adaptation_bitable_index(
        {"multi_signal_contract": {"validation": {"multi_signal_contract_status": "future_contract_state"}}}
    )

    assert index["shot_adaptation_notes_status"] == "状态待确认"
