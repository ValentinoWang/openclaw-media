"""Shared test data builders local to this suite.

Parallel to _fakes.py (fake service/response objects) -- this module holds
plain data-builder fixtures instead.
"""

from __future__ import annotations


def multi_signal_contract_payload(asset_id: str = "frame_001") -> dict[str, object]:
    """A valid multi_signal_contract.v1 payload referencing ``asset_id``.

    Promoted from test_hard_guards.py's ``_multi_signal_contract_payload``
    (byte-identical to the copy that used to live in
    test_acceptance_workflow.py). test_multi_signal_artifact_render.py had
    a third variant, ``_multi_signal_payload(ref)``, that dropped the
    parameter for ``evidence_manifest_refs`` -- it stayed hardcoded to
    ``["frame_001"]`` instead of tracking ``ref`` the way ``source_refs``
    correctly did in the same fixture. This version threads ``asset_id``
    through both places, matching the two suites that already agreed on
    the correct shape.
    """

    return {
        "contract_version": "multi_signal_contract.v1",
        "evidence_manifest_refs": [asset_id],
        "source_signal_dimensions": [
            {
                "dimension_id": "visual",
                "status": "available",
                "source_refs": [asset_id],
                "observations": ["画面以强视觉钩子开场"],
                "summary": "视觉维度可迁移的是首屏冲突和近景停留。",
                "reusable_signal": "用自己的主体和场景重建首屏停留。",
                "transform_rule": "保留开头强钩子结构，替换人物、场景、文案和视觉组合。",
                "risk_boundary": "不能复用原画面组合、原句或真实人物身份。",
                "confidence": 0.8,
                "insufficient_evidence": [],
                "conflict_notes": [],
            }
        ],
        "shot_adaptation_notes": [
            {
                "note_id": "shot_note_001",
                "source_refs": [asset_id],
                "source_dimension_ids": ["visual"],
                "learnable_pattern": "用自己的主体和场景重建首屏停留。",
                "adaptation_rule": "保留开头强钩子结构，替换人物、场景、文案和视觉组合。",
                "do_not_copy": ["不能复用原画面组合、原句或真实人物身份。"],
                "confidence": 0.8,
            }
        ],
        "evidence_store_summary": {"schema_version": "evidence_store_summary_v1"},
        "aggregation_report": {
            "dimension_count": 1,
            "available_dimensions": ["visual"],
            "insufficient_dimensions": [],
            "failed_dimensions": [],
            "source_ref_failures": [],
        },
        "conflict_notes": [],
        "open_questions": [],
        "validation": {
            "source_refs_status": "validated",
            "multi_signal_contract_status": "validated",
            "warnings": [],
        },
    }
