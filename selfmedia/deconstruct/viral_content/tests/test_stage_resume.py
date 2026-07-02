from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from selfmedia.deconstruct.viral_content.src import runner
from selfmedia.deconstruct.viral_content.src.media_parts import MediaEvidence


def _core_payload() -> dict[str, Any]:
    return {
        "content_summary": "图文拆解",
        "viral_reuse_assessment": {"final_label": "weak_reuse_candidate"},
        "pacing_profile": {"llm_interpretation": {"hook": "首图钩子"}},
        "reuse_guardrails": {
            "allowed_reuse": ["结构"],
            "required_transformations": ["换主体"],
            "prohibited_reuse": ["照搬图片"],
            "similarity_risk": "medium",
            "originality_requirements": ["换场景"],
        },
        "human_readable_brief": {"summary": "可复用结构"},
        "image_post_script": [{"evidence_asset_id": "image_001", "visual": "首图"}],
    }


def _multi_payload() -> dict[str, Any]:
    return {
        "contract_version": "multi_signal_contract.v1",
        "source_signal_dimensions": [
            {
                "dimension_id": "visual",
                "status": "available",
                "source_refs": ["image_001"],
                "observations": ["首图事实"],
                "summary": "首图钩子",
                "reusable_signal": "先给结果",
                "transform_rule": "换主体",
                "risk_boundary": "不照搬",
                "confidence": 0.8,
                "insufficient_evidence": [],
                "conflict_notes": [],
            }
        ],
        "shot_adaptation_notes": [
            {
                "note_id": "shot_note_001",
                "source_refs": ["image_001"],
                "source_dimension_ids": ["visual"],
                "learnable_pattern": "先给结果",
                "adaptation_rule": "换主体",
                "do_not_copy": ["不照搬"],
                "confidence": 0.8,
            }
        ],
        "evidence_store_summary": {"available_evidence_ids": ["image_001"]},
        "aggregation_report": {
            "dimension_count": 1,
            "available_dimensions": ["visual"],
            "insufficient_dimensions": [],
            "failed_dimensions": [],
            "source_ref_failures": [],
        },
        "conflict_notes": [],
        "open_questions": [],
        "validation": {"source_refs_status": "validated", "multi_signal_contract_status": "validated", "warnings": []},
    }


def _prepared() -> dict[str, Any]:
    evidence = MediaEvidence(
        media_type="image_post",
        parts=[{"text": "视觉证据 asset_id=image_001"}],
        evidence_paths=["/tmp/image_001.jpg"],
        evidence_assets=[{"asset_id": "image_001", "path": "/tmp/image_001.jpg", "kind": "cover_image", "phase": "图文首图"}],
        cleanup_paths=[],
        audio_path="",
        preview_path="/tmp/image_001.jpg",
    )
    asset_manifest = {
        "schema_version": "asset_manifest_v1",
        "source_url": "https://example.com/note",
        "media_type": "image_post",
        "source_path": "/tmp/image_001.jpg",
        "work_dir": "/tmp",
        "video_path": "",
        "image_paths": ["/tmp/image_001.jpg"],
        "audio_path": "",
        "platform_asset_id": "note1",
        "stats": {},
        "assets": [],
    }
    modality_facts = {
        "visual_assets": {
            "schema_version": "modality_facts_v1",
            "fact_type": "visual_assets",
            "status": "success",
            "source_refs": ["image_001"],
            "facts": {
                "assets": [{"asset_id": "image_001", "path": "/tmp/image_001.jpg", "kind": "cover_image", "phase": "图文首图"}],
                "visual_hook": {"media_kind": "image_post", "primary_asset_ids": ["image_001"]},
            },
        }
    }
    return {
        "cleaned_url": "https://example.com/note",
        "media": type(
            "Media",
            (),
            {
                "video_path": "",
                "image_paths": ["/tmp/image_001.jpg"],
                "media_type": "image_post",
                "caption": "caption",
                "title": "title",
                "published_at": "",
                "publish_time": "",
                "stats": {},
            },
        )(),
        "detected_media_type": "image_post",
        "source_path": "/tmp/image_001.jpg",
        "work_dir": "/tmp",
        "evidence": evidence,
        "media_stats": {},
        "asset_manifest": asset_manifest,
        "modality_facts": modality_facts,
        "evidence_store": {
            "schema_version": "evidence_store_v1",
            "asset_manifest": asset_manifest,
            "modality_facts": modality_facts,
            "evidence_manifest": {"image_001": {"type": "visual", "asset_id": "image_001"}},
            "llm_input_compact": {"available_evidence_ids": ["image_001"]},
            "missing_evidence_report": [],
        },
        "evidence_dag_artifact_paths": {},
        "valid_asset_ids": {"image_001"},
    }


def test_run_workflow_writes_stage_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "load_config", lambda: object())
    monkeypatch.setattr(runner, "_prepare_deconstruct_inputs", lambda text, max_frames=8: _prepared())
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: _core_payload())
    monkeypatch.setattr(runner, "build_multi_signal_contract", lambda result, user_intent="": _multi_payload())

    result = runner.run_workflow("【拆解】 https://example.com/note", write_feishu=False, stage_dir=tmp_path)

    assert result["deconstruct"]["multi_signal_contract"]["contract_version"] == "multi_signal_contract.v1"
    assert result["deconstruct"]["multi_signal_contract"]["shot_adaptation_notes"][0]["note_id"] == "shot_note_001"
    for name in (
        "01_prepared.json",
        "02_deconstruct_core.json",
        "03_multi_signal_contract.json",
        "05_deconstruct_final.json",
        "99_workflow_output.json",
    ):
        assert (tmp_path / name).is_file()
    assert not (tmp_path / "03_shot_adaptation_notes.json").exists()
    core_stage = json.loads((tmp_path / "02_deconstruct_core.json").read_text(encoding="utf-8"))
    assert "multi_signal_contract" not in core_stage["deconstruct"]


def test_resume_stage_json_skips_core_llm(monkeypatch, tmp_path: Path) -> None:
    core = _core_payload()
    core.update(
        {
            "schema_version": "deconstruction.v2",
            "source_url": "https://example.com/note",
            "media_type": "image_post",
            "evidence_manifest": {"image_001": {"type": "visual"}},
            "validation": {"evidence_reference_status": "validated"},
        }
    )
    source = tmp_path / "02_deconstruct_core.json"
    source.write_text(json.dumps({"stage": "02_deconstruct_core", "deconstruct": core}, ensure_ascii=False), encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "load_config", lambda: object())
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("core LLM reran")))
    monkeypatch.setattr(runner, "build_multi_signal_contract", lambda result, user_intent="": calls.append("multi") or _multi_payload())

    result = runner.run_workflow(
        "【拆解】 https://example.com/note",
        write_feishu=False,
        stage_dir=tmp_path / "resume",
        resume_stage_json=source,
    )

    assert calls == ["multi"]
    assert result["deconstruct"]["multi_signal_contract"]["shot_adaptation_notes"][0]["note_id"] == "shot_note_001"
    assert (tmp_path / "resume" / "05_deconstruct_final.json").is_file()


def test_resume_from_prepared_stage_rebuilds_image_parts(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "image_001.jpg"
    image_path.write_bytes(base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2w=="))
    prepared = _prepared()
    prepared["evidence"].evidence_paths[0] = str(image_path)
    prepared["evidence"].evidence_assets[0]["path"] = str(image_path)
    stage_payload = runner._prepared_stage_payload("【拆解】 https://example.com/note", prepared, max_frames=8)
    source = tmp_path / "01_prepared.json"
    source.write_text(json.dumps({"stage": "01_prepared", **stage_payload}, ensure_ascii=False), encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_call_llm(parts, *args, **kwargs):
        captured["has_image"] = any("image_data" in part for part in parts)
        return _core_payload()

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)
    monkeypatch.setattr(runner, "build_multi_signal_contract", lambda result, user_intent="": _multi_payload())

    result = runner.resume_deconstruct_from_stage(source, stage_dir=tmp_path / "resume_prepared")

    assert captured["has_image"] is True
    assert result["multi_signal_contract"]["contract_version"] == "multi_signal_contract.v1"


def test_run_workflow_resume_from_recreate_stage_skips_recreate_llm(monkeypatch, tmp_path: Path) -> None:
    deconstruct_payload = _core_payload()
    deconstruct_payload.update(
        {
            "schema_version": "deconstruction.v2",
            "source_url": "https://example.com/note",
            "media_type": "image_post",
            "evidence_manifest": {"image_001": {"type": "visual"}},
            "multi_signal_contract": _multi_payload(),
        }
    )
    recreate_payload = {"media_type": "image_post", "image_post_script": [{"page_no": 1}], "video_storyboard": []}
    source = tmp_path / "06_recreate.json"
    source.write_text(
        json.dumps({"stage": "06_recreate", "deconstruct": deconstruct_payload, "recreate": recreate_payload}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "load_config", lambda: object())
    monkeypatch.setattr(runner, "recreate", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("recreate reran")))

    result = runner.run_workflow(
        "【拆解-再创】 https://example.com/note",
        write_feishu=False,
        stage_dir=tmp_path / "resume_recreate",
        resume_stage_json=source,
    )

    assert result["recreate"] == recreate_payload
