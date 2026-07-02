from __future__ import annotations

from pathlib import Path

import pytest

from selfmedia.deconstruct.viral_content.src.evidence.modality_dag import build_evidence_store, prepare_asset_manifest


def _asset_manifest(tmp_path: Path) -> dict[str, object]:
    return prepare_asset_manifest(
        source_url="https://example.com/video",
        media_type="video",
        source_path=str(tmp_path / "video.mp4"),
        work_dir=str(tmp_path),
        video_path=str(tmp_path / "video.mp4"),
        image_paths=[],
        visual_assets=[],
        media_stats={"platform_asset_id": "fixture1"},
    )


def _fact(fact_type: str, refs: list[str], facts: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "modality_facts_v1",
        "fact_type": fact_type,
        "status": "success",
        "source_refs": refs,
        "facts": facts,
    }


def test_evidence_store_manifest_includes_speech_segments(tmp_path: Path) -> None:
    store = build_evidence_store(
        asset_manifest=_asset_manifest(tmp_path),
        modality_facts={
            "speech": _fact(
                "speech",
                ["sp_001"],
                {
                    "speech_transcript": {"status": "success"},
                    "speech_timeline": [{"segment_id": "sp_001", "start": 0.0, "end": 1.2, "text": "第一句"}],
                },
            )
        },
    )

    manifest = store["evidence_manifest"]

    assert manifest["sp_001"]["type"] == "speech"
    assert store["modality_facts"]["speech"]["facts"]["speech_timeline"][0]["segment_id"] == "sp_001"


def test_evidence_store_manifest_includes_scene_and_keyobs(tmp_path: Path) -> None:
    frame1 = tmp_path / "frame1.jpg"
    frame2 = tmp_path / "frame2.jpg"
    frame1.write_bytes(b"frame1")
    frame2.write_bytes(b"frame2")

    store = build_evidence_store(
        asset_manifest=_asset_manifest(tmp_path),
        modality_facts={
            "visual_assets": _fact(
                "visual_assets",
                ["frame_001", "frame_002"],
                {
                    "assets": [
                        {"asset_id": "frame_001", "path": str(frame1), "kind": "first5s_frame", "phase": "前5秒"},
                        {"asset_id": "frame_002", "path": str(frame2), "kind": "keyframe", "phase": "5秒后"},
                    ]
                },
            ),
            "pacing": _fact(
                "pacing",
                ["scene_001", "scene_002", "frame_001", "frame_002"],
                {
                    "scene_segments": [
                        {"scene_id": "scene_001", "source_frame_refs": ["frame_001"]},
                        {"scene_id": "scene_002", "source_frame_refs": ["frame_002"]},
                    ]
                },
            ),
            "keyframe_observations": _fact(
                "keyframe_observations",
                ["keyobs_001", "frame_001"],
                {
                    "keyframe_observations": [
                        {
                            "observation_id": "keyobs_001",
                            "asset_id": "frame_001",
                            "source_frame_refs": ["frame_001"],
                            "observations": ["画面主体在室内移动"],
                            "source": "codex_responses",
                        }
                    ]
                },
            ),
        },
    )

    manifest = store["evidence_manifest"]

    assert manifest["scene_001"]["type"] == "scene"
    assert manifest["scene_002"]["type"] == "scene"
    assert manifest["keyobs_001"]["type"] == "visual_observation"
    assert manifest["keyobs_001"]["source_frame_refs"] == ["frame_001"]
    assert manifest["keyobs_001"]["source"] == "codex_responses"


def test_evidence_store_manifest_rejects_duplicate_ids(tmp_path: Path) -> None:
    frame1 = tmp_path / "frame1.jpg"
    frame2 = tmp_path / "frame2.jpg"
    frame1.write_bytes(b"frame1")
    frame2.write_bytes(b"frame2")

    with pytest.raises(ValueError, match="重复"):
        build_evidence_store(
            asset_manifest=_asset_manifest(tmp_path),
            modality_facts={
                "visual_assets": _fact(
                    "visual_assets",
                    ["frame_001"],
                    {
                        "assets": [
                            {"asset_id": "frame_001", "path": str(frame1), "kind": "first5s_frame"},
                            {"asset_id": "frame_001", "path": str(frame2), "kind": "keyframe"},
                        ]
                    },
                )
            },
        )
