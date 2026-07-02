from __future__ import annotations

import json
from pathlib import Path

import pytest

from selfmedia.deconstruct.viral_content.src.evidence.modality_dag import build_evidence_store, prepare_asset_manifest
from selfmedia.deconstruct.viral_content.src.evidence.ocr import build_ocr_evidence
from selfmedia.deconstruct.viral_content.src.evidence.speech import build_speech_evidence
from selfmedia.deconstruct.viral_content.src.artifact_v2 import validate_llm_deconstruction_v2_payload
from selfmedia.deconstruct.viral_content.src.schemas import DeconstructResult


def test_speech_evidence_uses_timestamp_sidecar(tmp_path: Path) -> None:
    audio = tmp_path / "audio.mp3"
    transcript = tmp_path / "transcript.txt"
    sidecar = tmp_path / "speech_segments.json"
    audio.write_bytes(b"audio")
    transcript.write_text("第一句\n第二句\n", encoding="utf-8")
    sidecar.write_text(
        json.dumps(
            {
                "sentences": [
                    {"begin_time": 0, "end_time": 1200, "text": "第一句", "confidence": 0.91},
                    {"begin_time": 1200, "end_time": 2400, "text": "第二句", "confidence": 0.93},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    evidence = build_speech_evidence(str(audio), transcript_path=str(transcript))

    assert evidence["status"] == "success"
    assert [item["segment_id"] for item in evidence["segments"]] == ["sp_001", "sp_002"]
    assert evidence["segments"][0]["start"] == 0
    assert evidence["segments"][0]["end"] == 1.2


def test_transcript_only_does_not_fabricate_segments(tmp_path: Path) -> None:
    audio = tmp_path / "audio.mp3"
    transcript = tmp_path / "transcript.txt"
    audio.write_bytes(b"audio")
    transcript.write_text("只有逐字稿，没有时间戳。", encoding="utf-8")

    evidence = build_speech_evidence(str(audio), transcript_path=str(transcript))

    assert evidence["status"] == "transcript_only"
    assert evidence["segments"] == []


def test_ocr_evidence_ignores_unstructured_text_sidecar(tmp_path: Path) -> None:
    frame = tmp_path / "frame_001.jpg"
    ocr_path = tmp_path / "ocr.txt"
    frame.write_bytes(b"not-a-real-image")
    ocr_path.write_text("## 01 image-01.jpg\n把任意视频\n拆成 可复刻 SOP\n", encoding="utf-8")

    evidence = build_ocr_evidence(
        [{"asset_id": "frame_001", "path": str(frame), "kind": "first5s_frame"}],
        ocr_path=str(ocr_path),
    )

    assert evidence["status"] == "no_visible_text"
    assert evidence["visible_text_segments"] == []
    assert evidence["text_tracks"] == []
    assert evidence["reason"] == "no_reliable_text"


def _minimal_v2_payload() -> dict[str, object]:
    return {
        "content_summary": "表达力复盘",
        "source_summary": "用真实表达卡点讲练习方法。",
        "viral_mechanism": "真实卡点前置，给出练习承诺。",
        "video_storyboard": [{"shot_no": 1, "duration": "0-3s", "visual": "会议发言前停顿", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_001"}],
        "image_post_script": [{"page_no": 1, "image_prompt": "会议发言前停顿", "evidence_asset_id": "frame_001"}],
        "avoid_plagiarism_notes": "重写为自己的会议经历。",
        "production_checklist": ["准备真实会议素材"],
        "viral_reuse_assessment": {
            "observed_virality": {"level": "unknown", "reason": "无平台数据"},
            "mechanism_strength": {"level": "strong", "reason": "真实卡点明确", "evidence_ids": ["sp_001"]},
            "account_fit": {"level": "high", "reason": "适合职场账号"},
            "production_feasibility": {"level": "easy", "reason": "可复拍"},
            "reuse_risk": {"level": "medium", "reason": "需改写原句"},
            "final_label": "strong_reuse_candidate",
            "confidence": 0.8,
            "human_review_required": True,
        },
        "pacing_profile": {"llm_interpretation": {"edit_recommendations": ["前 3 秒保留卡点"]}},
        "reuse_guardrails": {
            "allowed_reuse": [{"item": "真实卡点前置", "evidence_ids": ["sp_001"]}],
            "required_transformations": [{"source_part": "开头文案", "required_change": "改成自己的经历"}],
            "prohibited_reuse": [{"element": "原视频原句", "reason": "表达复制风险"}],
            "own_account_mapping": {"own_persona": "职场账号"},
            "similarity_risk": {"overall": "medium"},
            "originality_requirements": ["加入自己的真实素材"],
            "human_review_required": True,
        },
        "human_readable_brief": {"recommended_script_directions": ["用自己的会议卡点改写"]},
        "confidence": 0.8,
    }


def test_v2_payload_validator_rejects_invalid_evidence_id() -> None:
    evidence_store = {"evidence_manifest": {"frame_001": {"type": "visual"}, "sp_001": {"type": "speech"}}}
    payload = _minimal_v2_payload()
    payload["viral_reuse_assessment"]["mechanism_strength"]["evidence_ids"] = ["sp_BAD"]  # type: ignore[index]

    with pytest.raises(Exception, match="非法 evidence 引用"):
        validate_llm_deconstruction_v2_payload(payload, evidence_store)  # type: ignore[arg-type]


def test_deconstruct_result_rejects_removed_asr_ocr_function_fields() -> None:
    payload = {
        "speech_function_lines": [
            {"function": "opening_hook", "segment_id": "sp_001", "start": 0.0, "end": 1.2, "text": "第一句", "function_reason": "钩子"}
        ],
        "screen_text_function_lines": [],
    }
    payload.update(_minimal_v2_payload())

    with pytest.raises(Exception, match="已移除字段"):
        DeconstructResult.parse_obj(payload)


@pytest.mark.parametrize(
    "media_dir",
    [
        Path("/home/ubuntu/selfmedia-tools/selfmedia/ingest/content_flow/downloads/xhs-6a29593d000000001503e593"),
        Path("/home/ubuntu/selfmedia-tools/selfmedia/ingest/content_flow/downloads/douyin-7649332165372677403"),
        Path("/home/ubuntu/selfmedia-tools/selfmedia/ingest/content_flow/downloads/douyin-7649061784112362610"),
    ],
)
def test_selfmedia_knowledge_fixture_files_are_readable(media_dir: Path) -> None:
    if not media_dir.exists():
        pytest.skip(f"fixture missing: {media_dir}")
    for name in ("video.mp4", "audio.mp3", "transcript.txt", "analysis.json"):
        path = media_dir / name
        assert path.is_file() and path.stat().st_size > 0, str(path)
    json.loads((media_dir / "analysis.json").read_text(encoding="utf-8"))


def test_build_evidence_store_keeps_raw_and_llm_layers_separate(tmp_path: Path) -> None:
    audio = tmp_path / "audio.mp3"
    transcript = tmp_path / "transcript.txt"
    frame = tmp_path / "frame_001.jpg"
    audio.write_bytes(b"audio")
    transcript.write_text("只有逐字稿。", encoding="utf-8")
    frame.write_bytes(b"frame")
    asset_manifest = prepare_asset_manifest(
        source_url="https://example.com/video",
        media_type="image_post",
        source_path=str(frame),
        work_dir=str(tmp_path),
        video_path="",
        image_paths=[str(frame)],
        audio_path=str(audio),
        visual_assets=[{"asset_id": "frame_001", "path": str(frame), "kind": "first5s_frame"}],
        media_stats={"platform_asset_id": "fixture1"},
    )
    store = build_evidence_store(
        asset_manifest=asset_manifest,
        modality_facts={
            "visual_assets": {
                "schema_version": "modality_facts_v1",
                "fact_type": "visual_assets",
                "status": "success",
                "source_refs": ["frame_001"],
                "facts": {"assets": [{"asset_id": "frame_001", "path": str(frame), "kind": "first5s_frame"}]},
            },
            "speech": {
                "schema_version": "modality_facts_v1",
                "fact_type": "speech",
                "status": "success",
                "source_refs": [],
                "facts": {"speech_transcript": {"status": "transcript_only"}, "speech_timeline": []},
            },
            "ocr": {
                "schema_version": "modality_facts_v1",
                "fact_type": "ocr",
                "status": "success",
                "source_refs": ["ocr_001"],
                "facts": {
                    "visible_text_segments": [
                        {"text_segment_id": "ocr_001", "asset_id": "frame_001", "text": "封面标题"}
                    ]
                },
            },
        },
    )

    assert store["schema_version"] == "evidence_store_v1"
    assert "speech_function_lines" not in store["modality_facts"]["speech"]["facts"]
    assert store["evidence_manifest"]["frame_001"]["type"] == "visual"
    assert store["evidence_manifest"]["ocr_001"]["type"] == "ocr"
