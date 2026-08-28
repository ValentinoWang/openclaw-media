from __future__ import annotations

import pytest

from selfmedia.creation import deconstruction_artifact
from selfmedia.creation.field_contract import CanonicalMediaRecord
from selfmedia.creation.llm_generator import build_creation_prompt
from selfmedia.creation.request_parser import CreationRequest
from selfmedia.creation.matcher import RankedRecord
from selfmedia.creation.workflow import _explicit_source_asset_virals, _record_candidate_payload, _require_deconstruction_artifacts
from selfmedia.deconstruct.viral_content.src import multi_signal_contract, runner


def _ready_contract(ref: str = "frame_001") -> dict[str, object]:
    return {
        "contract_version": "multi_signal_contract.v1",
        "evidence_manifest_refs": [ref],
        "source_signal_dimensions": [
            {
                "dimension_id": "visual",
                "status": "available",
                "source_refs": [ref],
                "observations": ["首屏有明确的动作冲突"],
                "summary": "首屏用动作冲突建立停留。",
                "reusable_signal": "用自己的场景重建首屏冲突。",
                "transform_rule": "保留冲突递进，替换人物、场景和文案。",
                "risk_boundary": "不得复用原画面组合或原句。",
                "confidence": 0.8,
                "insufficient_evidence": [],
                "conflict_notes": [],
            }
        ],
        "shot_adaptation_notes": [
            {
                "note_id": "shot_001",
                "source_refs": [ref],
                "source_dimension_ids": ["visual"],
                "learnable_pattern": "先给冲突，再给解决动作。",
                "adaptation_rule": "改成自己的运动场景和动作。",
                "do_not_copy": ["不得使用原画面或原句。"],
                "confidence": 0.8,
            }
        ],
        "evidence_store_summary": {},
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


def _artifact(contract: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "deconstruction.v2",
        "evidence_manifest": {"frame_001": {"asset_id": "frame_001", "type": "visual"}},
        "multi_signal_contract": contract,
        "content_summary": {"summary": "legacy compact must never reach the creation prompt"},
        "reuse_guardrails": {"legacy": "must never reach the creation prompt"},
    }


def _record() -> CanonicalMediaRecord:
    return CanonicalMediaRecord(
        source_table="02B_MaterialDeconstructions_素材拆解",
        source_record_id="decon_001",
        relation_id="asset_001",
        record_type="素材拆解",
        title="旧拆解标题",
        content="legacy compact must never reach the creation prompt",
        detail_json={"source_asset_id": "source_asset_001", "evidence_uri": "vault://evidence.json"},
        doc_links={"evidence": "vault://evidence.json", "deconstruction": "https://example.com/deconstruction"},
    )


def test_deconstruction_without_handoff_defers_contract_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        multi_signal_contract,
        "generate_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no creative handoff must not call contract LLM")),
    )

    result = runner.finalize_deconstruction_contract(
        {"evidence_manifest": {"frame_001": {"asset_id": "frame_001", "type": "visual"}}}
    )

    contract = result["multi_signal_contract"]
    assert contract["validation"]["multi_signal_contract_status"] == multi_signal_contract.MULTI_SIGNAL_CONTRACT_DEFERRED_STATUS
    assert contract["source_signal_dimensions"][0]["status"] == "insufficient_evidence"


def test_explicit_creation_handoff_consumes_contract_without_compact_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    deferred = multi_signal_contract.deferred_multi_signal_contract(_artifact({}))
    artifact = _artifact(deferred)
    monkeypatch.setattr(deconstruction_artifact, "load_deconstruction_artifact", lambda *args, **kwargs: artifact)
    monkeypatch.setattr(deconstruction_artifact, "distilled_usable_material_brief", lambda _artifact: {})

    with pytest.raises(deconstruction_artifact.DeconstructionArtifactUnavailable, match="creative_handoff_not_requested"):
        deconstruction_artifact.attach_deconstruction_artifact_brief(
            _record(),
            tenant_id="00000000-0000-4000-8000-000000000101",
            require_creative_handoff=True,
        )

    calls: list[str] = []
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: calls.append("provider"))
    monkeypatch.setattr(
        runner,
        "build_multi_signal_contract",
        lambda source, user_intent="": calls.append(user_intent) or _ready_contract(),
    )
    explicit = _explicit_source_asset_virals([_record()], "source_asset_001")
    assert [item.record.source_record_id for item in explicit] == ["decon_001"]
    accepted, rejected = _require_deconstruction_artifacts(
        [RankedRecord(record=_record(), score=80, reasons={"test": 80})],
        tenant_id="00000000-0000-4000-8000-000000000101",
        request=CreationRequest(
            platform="抖音",
            content_type="视频",
            track="运动",
            topic="跑步",
            publish_time="",
            source_asset_id="source_asset_001",
            raw_text="【创作】source_asset_id=source_asset_001 做成运动短视频",
        ),
    )

    assert rejected == []
    candidate = _record_candidate_payload(accepted[0].record)
    assert set(candidate) == {"id", "source_record_id", "relation_id", "source_table", "record_type", "multi_signal_contract"}
    prompt = build_creation_prompt(
        CreationRequest(platform="抖音", content_type="视频", track="运动", topic="跑步", publish_time=""),
        activity_candidates=[],
        viral_candidates=[candidate],
        inspiration_candidates=[],
        business_candidates=[],
        reference_docs=[],
        media_context={},
    )
    assert calls == ["provider", "【创作】source_asset_id=source_asset_001 做成运动短视频"]
    assert "保留冲突递进，替换人物、场景和文案。" in prompt
    assert "legacy compact must never reach the creation prompt" not in prompt
    assert "不得绕回任何非合同的拆解摘要" in prompt


def test_unrequested_creation_candidate_stays_identity_only_without_contract_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _artifact(multi_signal_contract.deferred_multi_signal_contract(_artifact({})))
    monkeypatch.setattr(deconstruction_artifact, "load_deconstruction_artifact", lambda *args, **kwargs: artifact)
    monkeypatch.setattr(deconstruction_artifact, "distilled_usable_material_brief", lambda _artifact: {})
    monkeypatch.setattr(
        runner,
        "build_multi_signal_contract",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unrequested candidate must not call contract LLM")),
    )

    accepted, rejected = _require_deconstruction_artifacts(
        [RankedRecord(record=_record(), score=80, reasons={"test": 80})],
        tenant_id="00000000-0000-4000-8000-000000000101",
        request=CreationRequest(platform="抖音", content_type="视频", track="运动", topic="跑步", publish_time=""),
    )

    assert rejected == []
    candidate = _record_candidate_payload(accepted[0].record)
    assert set(candidate) == {"id", "source_record_id", "relation_id", "source_table", "record_type"}


def test_creation_handoff_rejects_contract_with_unknown_evidence_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = _ready_contract(ref="untrusted_001")
    artifact = _artifact(invalid)
    monkeypatch.setattr(deconstruction_artifact, "load_deconstruction_artifact", lambda *args, **kwargs: artifact)
    monkeypatch.setattr(deconstruction_artifact, "distilled_usable_material_brief", lambda _artifact: {})

    with pytest.raises(deconstruction_artifact.DeconstructionArtifactUnavailable, match="evidence_manifest_refs|source_refs"):
        deconstruction_artifact.attach_deconstruction_artifact_brief(
            _record(),
            tenant_id="00000000-0000-4000-8000-000000000101",
            require_creative_handoff=True,
        )
