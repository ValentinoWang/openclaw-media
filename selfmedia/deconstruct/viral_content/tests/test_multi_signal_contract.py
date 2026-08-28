from __future__ import annotations

import pytest

from selfmedia.deconstruct.viral_content.src import multi_signal_contract
from selfmedia.deconstruct.viral_content.src.multi_signal_contract import MULTI_SIGNAL_CONTRACT_VERSION, _contract_prompt_parts, _normalize_multi_signal_contract_payload
from selfmedia.deconstruct.viral_content.src.multi_signal_schema import MultiSignalContractSchemaError, validate_dimension_analysis_payload


def _deconstruction() -> dict[str, object]:
    return {
        "schema_version": "deconstruction.v2",
        "source_url": "https://example.com/video",
        "platform": "抖音",
        "content_summary": "内容总结",
        "source_summary": "原作品总结",
        "evidence_manifest": {
            "frame_001": {"type": "visual", "asset_id": "frame_001"},
            "sp_001": {"type": "speech", "text": "真实口播"},
            "comment_001": {"type": "comment", "text": "高赞评论"},
            "metric_like_count": {"type": "metric", "text": "点赞数"},
        },
        "visual_hook": {"status": "available"},
        "engagement": {"like_count": 10},
        "comments": {"status": "verified_three_comments"},
    }


def _dimension_payload(dimension_id: str, ref: str = "frame_001") -> dict[str, object]:
    return {
        "dimension_id": dimension_id,
        "status": "available",
        "source_refs": [ref],
        "observations": ["有证据支持的观察"],
        "summary": "本维度摘要",
        "reusable_signal": "可迁移信号",
        "transform_rule": "迁移时必须换主体和表达",
        "risk_boundary": "不能复用原句和真实身份",
        "confidence": 0.8,
        "insufficient_evidence": [],
        "conflict_notes": [],
    }


def test_dimension_analysis_rejects_non_manifest_ref() -> None:
    with pytest.raises(MultiSignalContractSchemaError, match="source_refs 非法"):
        validate_dimension_analysis_payload(_dimension_payload("visual", ref="missing_001"), {"frame_001"})


def _contract_payload(*dimensions: dict[str, object]) -> dict[str, object]:
    return {
        "contract_version": MULTI_SIGNAL_CONTRACT_VERSION,
        "evidence_manifest_refs": ["frame_001"],
        "source_signal_dimensions": list(dimensions),
        "shot_adaptation_notes": [
            {
                "note_id": "shot_note_001",
                "source_refs": ["frame_001"],
                "source_dimension_ids": ["visual"],
                "learnable_pattern": "可迁移信号",
                "adaptation_rule": "迁移时必须换主体和表达",
                "do_not_copy": ["不能复用原句和真实身份"],
                "confidence": 0.8,
            }
        ],
        "evidence_store_summary": {"schema_version": "evidence_store_summary_v1"},
        "aggregation_report": {
            "dimension_count": len(dimensions),
            "available_dimensions": [],
            "insufficient_dimensions": [],
            "failed_dimensions": [],
            "source_ref_failures": [],
        },
        "conflict_notes": [],
        "open_questions": [],
        "validation": {"source_refs_status": "validated", "multi_signal_contract_status": "validated", "warnings": []},
    }


def test_build_multi_signal_contract_validates_single_contract_payload() -> None:
    result = _normalize_multi_signal_contract_payload(
        _deconstruction(),
        _contract_payload(
            _dimension_payload("visual", "frame_001"),
            _dimension_payload("comments", "comment_001"),
        ),
    )

    assert result["contract_version"] == "multi_signal_contract.v1"
    assert [item["dimension_id"] for item in result["source_signal_dimensions"]] == ["visual", "comments"]
    assert result["aggregation_report"]["dimension_count"] == 2
    assert result["validation"]["multi_signal_contract_status"] == "validated"
    assert result["shot_adaptation_notes"][0]["source_refs"] == ["frame_001"]
    assert result["shot_adaptation_notes"][0]["learnable_pattern"] == "可迁移信号"


def test_build_multi_signal_contract_records_insufficient_evidence() -> None:
    insufficient = {
        **_dimension_payload("comments", "comment_001"),
        "status": "insufficient_evidence",
        "source_refs": [],
        "summary": "",
        "reusable_signal": "",
        "transform_rule": "",
        "risk_boundary": "",
        "insufficient_evidence": ["没有抓到足够评论"],
    }

    result = _normalize_multi_signal_contract_payload(_deconstruction(), _contract_payload(_dimension_payload("visual"), insufficient))

    assert result["aggregation_report"]["insufficient_dimensions"] == ["comments"]
    assert "comments: 没有抓到足够评论" in result["open_questions"]
    assert result["validation"]["multi_signal_contract_status"] == "validated_with_warnings"


def test_contract_normalizes_illegal_dimension_status_conservatively() -> None:
    dimension = {
        **_dimension_payload("visual", "frame_001"),
        "status": "available_with_caution",
    }

    result = _normalize_multi_signal_contract_payload(_deconstruction(), _contract_payload(dimension))
    normalized = result["source_signal_dimensions"][0]

    assert normalized["status"] == "insufficient_evidence"
    assert "visual" in result["aggregation_report"]["insufficient_dimensions"]
    assert any("非法维度 status=available_with_caution" in item for item in normalized["conflict_notes"])
    assert result["validation"]["multi_signal_contract_status"] == "validated_with_warnings"


def test_contract_prompt_limits_llm_status_to_evidence_states() -> None:
    prompt = multi_signal_contract.MULTI_SIGNAL_CONTRACT_PROMPT

    assert "只能从 available、insufficient_evidence 中选择" in prompt
    assert "不确定就写 insufficient_evidence" in prompt
    assert "四个字符串" not in prompt


def test_build_multi_signal_contract_uses_single_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[dict[str, object]]] = []

    def fake_generate_json(parts, config, schema=None, post_validate=None):
        calls.append(parts)
        serialized = "\n".join(str(part.get("text") or "") for part in parts)
        assert "用户【拆解-再创】意图" in serialized
        assert "evidence_store" in serialized
        assert "worker_name" not in serialized
        payload = _contract_payload(_dimension_payload("visual", "frame_001"))
        return post_validate(payload) if post_validate else payload

    monkeypatch.setattr(multi_signal_contract, "load_config", lambda: object())
    monkeypatch.setattr(multi_signal_contract, "generate_json", fake_generate_json)

    result = multi_signal_contract.build_multi_signal_contract(_deconstruction(), user_intent="改成小红书图文")

    assert len(calls) == 1
    assert result["contract_version"] == "multi_signal_contract.v1"
    assert result["shot_adaptation_notes"][0]["note_id"] == "shot_note_001"


def test_contract_prompt_uses_compact_evidence_payload() -> None:
    large_text = "很长的 OCR 文本" * 2000
    deconstruction = _deconstruction()
    deconstruction["evidence_manifest"] = {
        f"ocr_{index:03d}": {"type": "ocr", "text": large_text, "asset_id": "frame_001"}
        for index in range(180)
    }
    deconstruction["modality_facts"] = {
        "ocr": {
            "status": "success",
            "source_refs": [f"ocr_{index:03d}" for index in range(180)],
            "facts": {"visible_text_segments": [{"text": large_text, "source_ref": f"ocr_{index:03d}"} for index in range(180)]},
        }
    }
    deconstruction["evidence_store"] = {
        "schema_version": "evidence_store_v1",
        "evidence_manifest": deconstruction["evidence_manifest"],
        "modality_facts": deconstruction["modality_facts"],
        "missing_evidence_report": [],
    }

    parts = _contract_prompt_parts(deconstruction, user_intent="改成短视频")
    serialized = "\n".join(str(part.get("text") or "") for part in parts)

    assert len(serialized) < 50000
    assert "evidence_manifest_sample" in serialized
    assert "modality_fact_statuses" in serialized
    assert "visible_text_segments" not in serialized
    assert large_text not in serialized
    assert "truncated" in serialized
