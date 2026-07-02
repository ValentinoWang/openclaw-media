from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from selfmedia.deconstruct.viral_content.src import runner
from selfmedia.deconstruct.viral_content.src import media_parts
from selfmedia.deconstruct.viral_content.src.evidence.modality_dag import (
    _media_evidence_from_facts,
    build_evidence_store,
    evidence_store_prompt,
    prepare_asset_manifest,
    run_modality_pipelines,
    run_visual_asset_pipeline,
)
from selfmedia.deconstruct.viral_content.src.evidence.schemas import validate_evidence_store


def _asset_manifest(tmp_path) -> dict[str, Any]:
    image = tmp_path / "image_001.jpg"
    image.write_bytes(b"image")
    return prepare_asset_manifest(
        source_url="https://www.douyin.com/note/123",
        media_type="image_post",
        source_path=str(image),
        work_dir=str(tmp_path),
        video_path="",
        image_paths=[str(image)],
        audio_path="",
        preview_path="",
        visual_assets=[],
        media_stats={
            "like_count": 12,
            "top_comments": [{"text": "想看后续"}, {"text": "太真实了"}, {"text": "收藏"}],
            "interaction_screenshot_path": "/tmp/interaction.png",
        },
        source_caption="标题 #护肤 #测评",
        source_title="标题",
        published_at="2026-06-30",
    )


def test_modality_dag_builds_evidence_store_for_image_post(tmp_path) -> None:
    asset_manifest = _asset_manifest(tmp_path)
    facts = run_modality_pipelines(asset_manifest=asset_manifest)

    store = build_evidence_store(asset_manifest=asset_manifest, modality_facts=facts)

    assert store["schema_version"] == "evidence_store_v1"
    assert store["modality_facts"]["copy_metadata"]["facts"]["hashtags"] == ["护肤", "测评"]
    assert store["modality_facts"]["comments"]["status"] == "success"
    assert store["llm_input_compact"]["facts"]["visual_assets"]["source_refs"] == ["image_001"]
    assert "parallel_fact_branches" not in evidence_store_prompt(store)


def test_evidence_store_rejects_invalid_fact_refs() -> None:
    asset_manifest = prepare_asset_manifest(
        source_url="https://www.douyin.com/note/123",
        media_type="image_post",
        source_path="/tmp/image_001.jpg",
        work_dir="/tmp",
        video_path="",
        image_paths=["/tmp/image_001.jpg"],
        audio_path="",
        preview_path="",
        visual_assets=[],
        media_stats={},
    )
    facts = {
        "visual_assets": {
            "schema_version": "modality_facts_v1",
            "fact_type": "visual_assets",
            "status": "success",
            "source_refs": ["missing_asset"],
            "facts": {},
        }
    }

    with pytest.raises(ValueError, match="source_refs 非法"):
        validate_evidence_store(
            {
                "schema_version": "evidence_store_v1",
                "asset_manifest": asset_manifest,
                "modality_facts": facts,
                "evidence_manifest": {"image_001": {"type": "visual"}},
                "llm_input_compact": {},
                "missing_evidence_report": [],
            }
        )


def test_visual_asset_pipeline_keeps_storyboard_frame_timestamps(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    frames_dir = tmp_path / "frames"
    frame0 = frames_dir / "frame_t000000.jpg"
    frame8 = frames_dir / "frame_t000008.jpg"
    first_frame = tmp_path / "preview" / "first_frame.jpg"

    def fake_extract_video_frames(video_path: str, out_dir: str, max_frames: int = 8) -> list[str]:
        frames_dir.mkdir(parents=True, exist_ok=True)
        frame0.write_bytes(b"frame0")
        frame8.write_bytes(b"frame8")
        return [str(frame0), str(frame8)]

    def fake_extract_first_frame(video_path: str, out_dir: str) -> str:
        first_frame.parent.mkdir(parents=True, exist_ok=True)
        first_frame.write_bytes(b"preview")
        return str(first_frame)

    monkeypatch.setattr(media_parts, "extract_video_frames", fake_extract_video_frames)
    monkeypatch.setattr(media_parts, "extract_first_frame", fake_extract_first_frame)
    asset_manifest = prepare_asset_manifest(
        source_url="https://www.douyin.com/video/123",
        media_type="video",
        source_path=str(video),
        work_dir=str(tmp_path),
        video_path=str(video),
        image_paths=[],
        audio_path="",
        preview_path="",
        visual_assets=[],
        media_stats={},
    )

    facts = run_visual_asset_pipeline(asset_manifest=asset_manifest)
    assets = facts["visual_assets"]["facts"]["assets"]

    assert [item["timestamp_sec"] for item in assets] == [0, 8]
    assert assets[0]["sampling_reason"] == "opening_1s_storyboard_frame"
    assert assets[1]["sampling_reason"] == "post5_3s_storyboard_frame"
    assert assets[0]["analysis_window_sec"] == 60


def test_media_evidence_keeps_full_60s_storyboard_sample_window(tmp_path) -> None:
    assets = []
    for index in range(24):
        frame = tmp_path / f"frame_{index + 1:03d}.jpg"
        frame.write_bytes(b"frame")
        assets.append(
            {
                "asset_id": f"frame_{index + 1:03d}",
                "path": str(frame),
                "kind": "first5s_frame" if index < 6 else "keyframe",
                "phase": "分镜代表帧",
            }
        )
    evidence = _media_evidence_from_facts(
        "video",
        {
            "visual_assets": {
                "facts": {
                    "assets": assets,
                    "evidence_paths": [item["path"] for item in assets],
                    "cleanup_paths": [],
                    "preview_path": assets[0]["path"],
                }
            }
        },
    )

    assert len([part for part in evidence.parts if "image_data" in part]) == 24


def test_runner_main_deconstruction_uses_evidence_store_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    captured: dict[str, str] = {}
    asset_manifest = _asset_manifest(tmp_path)
    facts = run_modality_pipelines(asset_manifest=asset_manifest)
    store = build_evidence_store(asset_manifest=asset_manifest, modality_facts=facts)
    evidence = SimpleNamespace(
        parts=[{"text": "视觉证据 asset_id=image_001"}],
        evidence_paths=[str(tmp_path / "image_001.jpg")],
        evidence_assets=facts["visual_assets"]["facts"]["assets"],
        cleanup_paths=[],
        audio_path="",
        preview_path=str(tmp_path / "image_001.jpg"),
    )
    prepared = {
        "cleaned_url": "https://www.douyin.com/note/123",
        "media": SimpleNamespace(video_path="", image_paths=["/tmp/image_001.jpg"], media_type="image_post", caption="标题", title="标题", stats={}),
        "detected_media_type": "image_post",
        "source_path": "/tmp/image_001.jpg",
        "work_dir": "/tmp",
        "evidence": evidence,
        "media_stats": {},
        "asset_manifest": asset_manifest,
        "modality_facts": facts,
        "evidence_store": store,
        "valid_asset_ids": {"image_001"},
    }

    def fake_call_llm(parts, schema, post_validate=None):
        captured["prompt"] = "\n".join(str(part.get("text") or "") for part in parts)
        payload = {
            "content_summary": "图文",
            "viral_reuse_assessment": {"final_label": "weak_reuse_candidate"},
            "pacing_profile": {"llm_interpretation": {"hook": "首图"}},
            "reuse_guardrails": {
                "allowed_reuse": ["结构"],
                "required_transformations": ["换主体"],
                "prohibited_reuse": ["照搬"],
                "similarity_risk": "medium",
                "originality_requirements": ["原创素材"],
            },
            "human_readable_brief": {"summary": "brief"},
            "image_post_script": [{"evidence_asset_id": "image_001", "visual": "首图"}],
        }
        return post_validate(payload) if post_validate else payload

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)
    monkeypatch.setattr(runner, "finalize_deconstruction_contract", lambda result, stage_dir=None, user_intent="": result)

    result = runner._deconstruct_from_prepared("【拆解】 https://www.douyin.com/note/123", prepared)

    assert result["evidence_store"]["schema_version"] == "evidence_store_v1"
    assert "canonical evidence_store" in captured["prompt"]
    assert "并行事实支路处理结果" not in captured["prompt"]
    assert "原文案摘要：" not in captured["prompt"]
