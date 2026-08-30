from __future__ import annotations

from types import SimpleNamespace

import pytest

from selfmedia.request_constraints import parse_request_constraints
from selfmedia.deconstruct.viral_content.src.artifact_v2 import DeconstructionArtifactError, build_deconstruction_artifact
from selfmedia.deconstruct.viral_content.src.feishu_doc_writer import append_blocks

from _fixtures import multi_signal_contract_payload as _multi_signal_payload


def _deconstruction_result(ref: str = "frame_001") -> dict[str, object]:
    return {
        "schema_version": "deconstruction.v2",
        "evidence_manifest": {"frame_001": {"type": "visual", "asset_id": "frame_001", "kind": "keyframe"}},
        "speech_transcript": {},
        "speech_timeline": [],
        "visible_text_segments": [],
        "content_summary": "内容总结",
        "source_summary": "summary",
        "viral_mechanism": "mechanism",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "v", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_001"}],
        "image_post_script": [{"page_no": 1, "image_prompt": "p", "evidence_asset_id": "frame_001"}],
        "viral_reuse_assessment": {"final_label": "weak_reuse_candidate"},
        "pacing_profile": {"llm_interpretation": "节奏"},
        "reuse_guardrails": {
            "allowed_reuse": ["结构"],
            "required_transformations": ["换主体"],
            "prohibited_reuse": ["原句"],
            "similarity_risk": "low",
            "originality_requirements": ["换素材"],
        },
        "human_readable_brief": {"usable_patterns": ["开头"]},
        "multi_signal_contract": _multi_signal_payload(ref),
        "request_constraints": parse_request_constraints("【拆解】 https://example.com").to_dict(),
    }


def test_build_deconstruction_artifact_keeps_contract_shot_adaptation_notes() -> None:
    artifact = build_deconstruction_artifact(
        result=_deconstruction_result(),
        deconstruction_id="dec1",
        source_asset_id="asset1",
        source_asset_evidence_uri="media://asset1",
        source_text="【拆解】 https://example.com",
    )

    assert artifact["multi_signal_contract"]["shot_adaptation_notes"][0]["note_id"] == "shot_note_001"


def test_build_deconstruction_artifact_rejects_contract_note_missing_ref() -> None:
    with pytest.raises(DeconstructionArtifactError):
        build_deconstruction_artifact(
            result=_deconstruction_result("frame_BAD"),
            deconstruction_id="dec1",
            source_asset_id="asset1",
            source_asset_evidence_uri="media://asset1",
            source_text="【拆解】 https://example.com",
        )


def test_append_blocks_does_not_render_independent_shot_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    bodies: list[dict[str, object]] = []

    def fake_post(url, headers, json, timeout):
        bodies.append(json)
        return SimpleNamespace(status_code=200, text="", json=lambda: {"code": 0})

    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    monkeypatch.setattr(doc_writer.requests, "post", fake_post)
    append_blocks(
        "doc1",
        {
            "media_type": "video",
            "content_summary": "内容总结",
            "multi_signal_contract": _multi_signal_payload(),
            "evidence_manifest": {"frame_001": {"type": "visual", "asset_id": "frame_001", "kind": "keyframe"}},
        },
        "token",
    )

    body_text = str(bodies)
    assert "参考镜头结构" not in body_text
    assert "镜头明细" not in body_text
    assert "shot_note_001" not in body_text


def test_deconstruct_doc_blocks_do_not_dump_machine_or_execution_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    bodies: list[dict[str, object]] = []

    def fake_post(url, headers, json, timeout):
        bodies.append(json)
        return SimpleNamespace(status_code=200, text="", json=lambda: {"code": 0})

    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    monkeypatch.setattr(doc_writer.requests, "post", fake_post)
    append_blocks(
        "doc1",
        {
            "media_type": "image_post",
            "content_summary": "内容总结",
            "source_summary": "summary",
            "viral_mechanism": "mechanism",
            "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "v", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_001"}],
            "image_post_script": [{"page_no": 1, "image_prompt": "复刻原图提示词", "evidence_asset_id": "frame_001"}],
            "viral_reuse_assessment": {"final_label": "weak_reuse_candidate", "confidence": 0.7, "reuse_risk": {"level": "medium", "reason": "相似"}},
            "pacing_profile": {"python_facts": {"cut_count": 12}, "llm_interpretation": {"summary": "前 3 秒强钩子"}},
            "reuse_guardrails": {
                "allowed_reuse": ["结构"],
                "required_transformations": ["换主体"],
                "prohibited_reuse": ["原句和身份标签"],
                "similarity_risk": {"overall": "medium"},
                "originality_requirements": ["换场景"],
                "human_review_required": True,
            },
            "human_readable_brief": {"usable_patterns": ["冲突前置"]},
            "speech_transcript": {"status": "no_audio", "reason": "fixture"},
            "visible_text_segments": [{"text_segment_id": "ocr_001", "asset_id": "frame_001", "text": "=. Ce Ks i en", "confidence": 0.2}],
            "evidence_manifest": {
                "frame_001": {"type": "visual", "asset_id": "frame_001", "kind": "keyframe"},
                "ocr_001": {"type": "ocr", "asset_id": "frame_001", "text": "=. Ce Ks i en", "confidence": 0.2},
            },
            "multi_signal_contract": _multi_signal_payload(),
        },
        "token",
    )

    body_text = str(bodies)
    assert "python_facts" not in body_text
    assert "cut_count" not in body_text
    assert "图文脚本" not in body_text
    assert "视频分镜" not in body_text
    assert "复刻原图提示词" not in body_text
    assert "=. Ce Ks i en" not in body_text
    assert "低置信或不可读，原文不进入正文" in body_text
    assert body_text.count("证据附录") == 1
    assert "证据引用表" not in body_text
    assert "创作复用建议" not in body_text
