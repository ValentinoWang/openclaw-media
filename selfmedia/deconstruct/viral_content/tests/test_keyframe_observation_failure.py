from __future__ import annotations

from typing import Any

import pytest

from selfmedia.deconstruct.viral_content.src.evidence import modality_dag


def _visual_facts(*assets: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {"visual_assets": {"facts": {"assets": list(assets)}}}


def _frame_asset() -> dict[str, str]:
    return {"asset_id": "frame_001", "kind": "keyframe"}


def _keyframe_fact(facts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return facts["keyframe_observations"]


def _asset_manifest() -> dict[str, Any]:
    return modality_dag.prepare_asset_manifest(
        source_url="https://www.douyin.com/video/123",
        media_type="video",
        source_path="/tmp/source.mp4",
        work_dir="/tmp",
        video_path="/tmp/source.mp4",
        image_paths=[],
        media_stats={},
    )


def test_keyframe_observation_without_frame_assets_is_not_applicable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modality_dag, "generate_json", lambda *args, **kwargs: pytest.fail("LLM must not run without frame assets"))

    fact = _keyframe_fact(
        modality_dag.run_keyframe_observation_facts_pipeline(
            visual_facts=_visual_facts({"asset_id": "image_001", "path": "/tmp/image_001.jpg", "kind": "cover_image"})
        )
    )

    assert fact["status"] == "not_applicable"
    assert fact["missing_reason"] == "no_keyframe_observations"


def test_keyframe_observation_selection_cannot_hide_frame_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modality_dag, "_select_llm_visual_assets", lambda assets: [])

    fact = _keyframe_fact(
        modality_dag.run_keyframe_observation_facts_pipeline(visual_facts=_visual_facts(_frame_asset()))
    )

    assert fact["status"] == "failed"
    assert fact["missing_reason"] == "keyframe_observation_empty_result"


@pytest.mark.parametrize(
    "response",
    [RuntimeError("provider quota exhausted: secret-token"), {"keyframe_observations": "not-a-list"}, []],
)
def test_keyframe_observation_generation_failures_are_observable(
    monkeypatch: pytest.MonkeyPatch, response: object
) -> None:
    def fake_generate_json(*args: object, **kwargs: object) -> object:
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(modality_dag, "generate_json", fake_generate_json)
    monkeypatch.setattr(modality_dag, "load_config", lambda: object())

    fact = _keyframe_fact(modality_dag.run_keyframe_observation_facts_pipeline(visual_facts=_visual_facts(_frame_asset())))

    assert fact["status"] == "failed"
    assert fact["missing_reason"] == "keyframe_observation_generation_failed"
    assert "secret-token" not in fact["missing_reason"]


def test_keyframe_observation_generation_failure_is_preserved_in_evidence_store(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_generate_json(*args: object, **kwargs: object) -> object:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(modality_dag, "generate_json", fake_generate_json)
    monkeypatch.setattr(modality_dag, "load_config", lambda: object())

    fact = _keyframe_fact(
        modality_dag.run_keyframe_observation_facts_pipeline(visual_facts=_visual_facts(_frame_asset()))
    )
    store = modality_dag.build_evidence_store(
        asset_manifest=_asset_manifest(),
        modality_facts={"keyframe_observations": fact},
    )

    assert store["modality_facts"]["keyframe_observations"]["status"] == "failed"
    assert (
        store["llm_input_compact"]["facts"]["keyframe_observations"]["missing_reason"]
        == "keyframe_observation_generation_failed"
    )
    assert store["missing_evidence_report"] == [
        {
            "fact_type": "keyframe_observations",
            "status": "failed",
            "missing_reason": "keyframe_observation_generation_failed",
        }
    ]


@pytest.mark.parametrize(
    "observations",
    [[], [{"asset_id": "unknown_frame", "observations": ["unusable"]}], [{"asset_id": "frame_001", "observations": []}]],
)
def test_keyframe_observation_empty_normalized_result_is_failed(
    monkeypatch: pytest.MonkeyPatch, observations: list[dict[str, object]]
) -> None:
    monkeypatch.setattr(modality_dag, "generate_json", lambda *args, **kwargs: {"keyframe_observations": observations})
    monkeypatch.setattr(modality_dag, "load_config", lambda: object())

    fact = _keyframe_fact(modality_dag.run_keyframe_observation_facts_pipeline(visual_facts=_visual_facts(_frame_asset())))

    assert fact["status"] == "failed"
    assert fact["missing_reason"] == "keyframe_observation_empty_result"
    assert fact["facts"]["keyframe_observations"] == []
