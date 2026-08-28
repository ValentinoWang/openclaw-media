from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from selfmedia.deconstruct.viral_content.src import cli, media_parts, runner
from selfmedia.deconstruct.viral_content.src.evidence import modality_dag
from selfmedia.deconstruct.viral_content.src.feishu_doc_writer import DocRef


def _docx_table_response(body: dict[str, object], rows: int = 2, cols: int = 5) -> dict[str, object]:
    children = body.get("children")
    if isinstance(children, list) and any(isinstance(item, dict) and item.get("block_type") == 31 for item in children):
        return {
            "code": 0,
            "data": {
                "children": [
                    {"block_id": "heading_block", "block_type": 4},
                    {
                        "block_id": "table_block",
                        "block_type": 31,
                        "table": {"cells": [f"cell_{idx}" for idx in range(rows * cols)]},
                    },
                ]
            },
        }
    return {"code": 0, "data": {}}


def test_cli_run_uses_current_workflow_signature(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fake_run_workflow(
        text: str,
        *,
        tenant_id: str = "",
        write_feishu: bool = False,
        stage_dir: str | None = None,
        resume_stage_json: str | None = None,
    ) -> dict[str, object]:
        assert text == "【拆解】 https://example.com/video"
        assert tenant_id == ""
        assert write_feishu is False
        assert stage_dir == "/tmp/deconstruct-stage"
        assert resume_stage_json is None
        return {"ok": True}

    monkeypatch.setattr(cli, "run_workflow", fake_run_workflow)
    monkeypatch.setattr(
        "sys.argv",
        [
            "cli.py",
            "【拆解】 https://example.com/video",
            "--no-write",
            "--stage-dir",
            "/tmp/deconstruct-stage",
        ],
    )

    cli.main()
    assert '"ok": true' in capsys.readouterr().out


def _deconstruct_payload(asset_id: str = "frame_001") -> dict[str, object]:
    return {
        "content_summary": "内容总结",
        "source_summary": "summary",
        "viral_mechanism": "mechanism",
        "video_storyboard": [
            {
                "shot_no": index + 1,
                "duration": duration,
                "visual": f"画面{index + 1}",
                "subtitle": "",
                "voiceover": "",
                "evidence_asset_id": asset_id,
            }
            for index, duration in enumerate(["0-1s", "1-2s", "2-3s", "3-4s", "4-5s"])
        ],
        "image_post_script": [{"page_no": 1, "image_prompt": "图", "evidence_asset_id": asset_id}],
        "avoid_plagiarism_notes": "notes",
        "production_checklist": ["check"],
        "viral_reuse_assessment": {
            "observed_virality": "unknown",
            "mechanism_strength": "medium",
            "account_fit": "medium",
            "production_feasibility": "high",
            "reuse_risk": "low",
            "final_label": "weak_reuse_candidate",
            "confidence": 0.72,
            "human_review_required": True,
        },
        "pacing_profile": {"llm_interpretation": "节奏可复用"},
        "reuse_guardrails": {
            "allowed_reuse": ["结构"],
            "required_transformations": ["换成人设"],
            "prohibited_reuse": ["原句"],
            "own_account_mapping": "迁移到当前账号",
            "similarity_risk": "low",
            "originality_requirements": ["换素材"],
            "human_review_required": True,
        },
        "human_readable_brief": {"usable_patterns": ["开头先给冲突"]},
        "cover_opening_hook": "首帧用红光近景和关系问题制造停留。",
        "core_data_summary": "互动证据不足，需人工复核热度。",
        "top_comment_insight": "评论证据不足，不能冒充原评论区高赞观点。",
        "target_audience": ["暧昧关系受众", "情绪短视频受众"],
        "pain_or_pleasure_points": ["关系拉扯", "评论区替主角判案"],
        "attention_elements": ["红光暗房", "近景自拍", "关系问题"],
        "viral_migration": "迁移关系留白结构，替换人物身份、场景和文案。",
        "creative_upgrade_suggestion": "把暧昧提问升级成观众审判局，让评论区承担第二叙事层。",
    }


def _multi_signal_contract_payload(asset_id: str = "frame_001") -> dict[str, object]:
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


def _prepared_evidence_dag(asset_id: str = "frame_001", media_type: str = "video") -> dict[str, object]:
    asset_manifest = {
        "schema_version": "asset_manifest_v1",
        "source_url": "https://example.com/video",
        "media_type": media_type,
        "source_path": "/tmp/video.mp4" if media_type == "video" else "/tmp/image_001.jpg",
        "work_dir": "/tmp",
        "video_path": "/tmp/video.mp4" if media_type == "video" else "",
        "image_paths": [] if media_type == "video" else ["/tmp/image_001.jpg"],
        "audio_path": "/tmp/audio.mp3" if media_type == "video" else "",
        "platform_asset_id": "vid1",
        "stats": {"video_id": "vid1"},
        "assets": [],
    }
    modality_facts = {
        "visual_assets": {
            "schema_version": "modality_facts_v1",
            "fact_type": "visual_assets",
            "status": "success",
            "source_refs": [asset_id],
            "facts": {
                "assets": [{"asset_id": asset_id, "path": f"/tmp/{asset_id}.jpg", "kind": "keyframe", "role": "visual"}],
                "visual_hook": {"media_kind": media_type, "primary_asset_ids": [asset_id]},
            },
        }
    }
    return {
        "asset_manifest": asset_manifest,
        "modality_facts": modality_facts,
        "evidence_store": {
            "schema_version": "evidence_store_v1",
            "asset_manifest": asset_manifest,
            "modality_facts": modality_facts,
            "evidence_manifest": {asset_id: {"type": "visual", "asset_id": asset_id}},
            "llm_input_compact": {"available_evidence_ids": [asset_id]},
            "missing_evidence_report": [],
        },
        "evidence_dag_artifact_paths": {},
    }


def _required_recreate_part2_fields() -> dict[str, object]:
    return {
        "editorial_plan": {
            "section_title": "千万年薪编导会怎么把这条改出彩？",
            "primary_plan": {
                "title": "把红光暧昧改成观众审判局",
                "why_better": "让观众替主角判案，而不是单纯复述暧昧拉扯。",
                "learn_from_reference": ["红光暗房", "近景自拍", "关系问题留白"],
                "must_transform": ["换原创问题", "换人设", "换字幕节奏"],
                "execution_angle": "把观众推到裁判位置，评论区自然站队。",
            },
            "backup_variants": [
                {"title": "前任视角反问版", "difference": "改成旁白反问", "best_for": "情绪独白账号", "risk": "容易卖惨"},
                {"title": "朋友审讯室版", "difference": "改成朋友逼问", "best_for": "生活化账号", "risk": "戏剧性下降"},
            ],
        },
        "production_route_plan": {
            "route_policy": "真实素材优先，Remotion 做字幕动效，FFmpeg 做压制交付。",
            "shot_route_table": [
                {
                    "segment_id": "0-2s",
                    "story_purpose": "抛出关系问题",
                    "route": "需要补拍",
                    "needed_material": "红光近景",
                    "execution_note": "只问一个原创问题",
                    "risk_or_manual_check": "不能复用原句",
                }
            ],
            "final_assembly": {
                "remotion_usage": "用于字幕模板；本条可不用。",
                "ffmpeg_usage": "用于 1080x1920 压制。",
                "delivery_note": "交主方案和两个备选文案。",
            },
        },
        "reusable_high_like_comment": {
            "comment_text": "他问的是能不能纠缠，评论区答的是自己当年有没有被放过。",
            "sharp_angle": "用观众自我审判承接暧昧话题。",
            "why_it_can_get_likes": "容易让观众代入自己的关系经历。",
            "reuse_instruction": "作为置顶评论测试。",
            "risk_boundary": "不点名、不网暴、不冒充原评论。",
        },
        "operation_plan": {
            "platform_fit": "适合小红书和抖音情绪短视频，靠关系议题和评论区站队承接。",
            "opening_3s_hook": "第一帧红光近景，字幕抛出一个原创关系问题。",
            "audience_trigger": "刺中暧昧拉扯和分手后反复回看的用户。",
            "comment_area_design": "置顶刁钻评论，引导用户用二选一回复站队。",
            "publish_timing": "晚 22:30-23:30 发，承接睡前情绪复盘。",
            "success_metric": "前 2 小时评论率和收藏率高于账号近 7 条均值。",
            "republish_or_iteration": "评论强就复投朋友审讯室版，收藏强就强化标题二选一。",
        },
        "material_checklist": {
            "must_have": ["红光近景", "原创关系问题"],
            "better_to_have": ["停顿反应镜头"],
            "can_rescue_without": ["无红光可用暖灯"],
            "must_not_fabricate": ["原句", "真实前任身份"],
        },
        "risk_controls": [
            {"risk": "像搬运", "control": "只学留白结构，换主体和文案。", "applies_to": "final_script"},
            {"risk": "评论攻击真人", "control": "评论只写心理洞察，不点名。", "applies_to": "reusable_high_like_comment"},
        ],
    }


def _recreate_payload() -> dict[str, object]:
    return {
        **_required_recreate_part2_fields(),
        "doc_title": "拆解-再创文档",
        "creative_positioning": "new angle",
        "final_script": "script",
        "video_storyboard": [
            {
                "shot_no": 1,
                "duration": "1s",
                "visual": "新画面",
                "subtitle": "",
                "voiceover": "",
            }
        ],
        "image_post_script": [{"page_no": 1, "image_prompt": "新图"}],
        "titles": ["title"],
        "hashtags": ["tag"],
        "production_notes": ["note"],
        "anti_copy_notes": "anti",
    }


def test_acceptance_deconstruct_video_full_order(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.mp3"
    frame = tmp_path / "frames" / "frame_001.jpg"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    events: list[str] = []
    captured_doc_bodies: list[dict[str, object]] = []

    media = SimpleNamespace(
        video_path=str(video),
        audio_path=None,
        image_paths=[],
        caption="caption",
        stats={"likes": 1},
        media_type="video",
        title="title",
    )
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: events.append("llm_precheck"))
    monkeypatch.setattr(
        runner,
        "_load_content_ingest_modules",
        lambda: (lambda: object(), lambda url, settings: events.append("part1") or media),
    )

    def fake_extract_frames(video_path: str, out_dir: str, max_frames: int = 8) -> list[str]:
        events.append("extract_frames")
        frame.parent.mkdir()
        frame.write_bytes(b"frame")
        return [str(frame)]

    def fake_extract_audio(video_path: str, out_dir: str, max_duration_sec: int = 60) -> str:
        events.append("extract_audio")
        return str(audio)

    monkeypatch.setattr(media_parts, "extract_video_frames", fake_extract_frames)
    monkeypatch.setattr(media_parts, "extract_first_frame", lambda video_path, out_dir: "")
    monkeypatch.setattr(media_parts, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(
        modality_dag,
        "generate_json",
        lambda *args, **kwargs: {
            "keyframe_observations": [{"asset_id": "frame_001", "observations": ["画面证据"]}]
        },
    )
    monkeypatch.setattr(
        runner,
        "build_multi_signal_contract",
        lambda result, user_intent="": events.append("multi_signal_contract") or _multi_signal_contract_payload("frame_001"),
    )

    def fake_call_llm(parts, schema, post_validate=None):
        events.append("llm_deconstruct")
        assert "asset_id=frame_001" in str(parts)
        payload = _deconstruct_payload("frame_001")
        return post_validate(payload) if post_validate else payload

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)

    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer
    import selfmedia.deconstruct.viral_content.src.feishu_writer as bitable_writer

    class Response:
        status_code = 200
        text = ""
        payload: dict[str, object]

        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def json(self) -> dict[str, object]:
            return self.payload

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int) -> Response:
        captured_doc_bodies.append(json)
        if isinstance(json.get("children"), list) and json["children"] == [{"block_type": 27, "image": {}}]:
            return Response({"code": 0, "data": {"children": [{"block_id": "image_block", "block_type": 27}]}})
        return Response(_docx_table_response(json))

    monkeypatch.setattr(doc_writer.requests, "post", fake_post)
    monkeypatch.setattr(doc_writer.requests, "patch", lambda *args, **kwargs: Response({"code": 0, "data": {}}))
    monkeypatch.setattr(doc_writer, "upload_feishu_doc_image", lambda document_id, file_path, token, feishu_base=None, parent_node=None: "frame_token")

    def fake_doc(title, content, folder_token=None, doc_kind="deconstruct"):
        events.append(f"doc_{doc_kind}")
        assert doc_kind == "deconstruct"
        assert content["evidence_assets"][0]["asset_id"] == "frame_001"
        doc_writer.append_blocks("doc_deconstruct", content, "token", doc_kind="deconstruct")
        return DocRef("doc_deconstruct", "https://feishu/doc_deconstruct")

    def fake_write(result, source_text, *, tenant_id=""):
        events.append("bitable")
        assert tenant_id == ""
        assert "doc_deconstruct" in result["deconstruct_doc_url"]
        assert "video_storyboard" in result  # full result may exist here, writer owns field filtering.
        return "rec1"

    monkeypatch.setattr(doc_writer, "create_checked_doc", fake_doc)
    monkeypatch.setattr(doc_writer, "sync_deconstruct_parent_index", lambda source_records=None: events.append("sync_index"))
    monkeypatch.setattr(bitable_writer, "build_attachment_plan", lambda result: events.append("attachments") or [])
    monkeypatch.setattr(bitable_writer, "write_deconstruction", fake_write)

    result = runner.run_workflow("【拆解】 https://example.com/video", write_feishu=True)
    assert result["feishu_record_id"] == "rec1"
    assert result["deconstruct"]["multi_signal_contract"]["shot_adaptation_notes"][0]["note_id"] == "shot_note_001"
    assert not frame.exists()
    body_text = str(captured_doc_bodies)
    assert "证据附录" in body_text
    assert not any(
        item.get("block_type") == 27 and item.get("image") == {}
        for body in captured_doc_bodies
        for item in body.get("children", [])
    )
    assert events.index("part1") < events.index("extract_frames") < events.index("llm_deconstruct")
    assert events.index("part1") < events.index("extract_audio") < events.index("llm_deconstruct")
    assert events.index("llm_deconstruct") < events.index("multi_signal_contract") < events.index("doc_deconstruct") < events.index("bitable")


def test_no_write_deconstruct_builds_multi_signal_contract_without_feishu_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    evidence = SimpleNamespace(
        parts=[{"text": "视觉证据 asset_id=frame_001"}],
        evidence_paths=["/tmp/frame_001.jpg"],
        evidence_assets=[{"asset_id": "frame_001", "path": "/tmp/frame_001.jpg", "kind": "keyframe"}],
        cleanup_paths=["/tmp/frame_001.jpg"],
        audio_path="/tmp/audio.mp3",
        preview_path="/tmp/frame_001.jpg",
    )
    prepared = {
        "cleaned_url": "https://example.com/video",
        "media": SimpleNamespace(
            video_path="/tmp/video.mp4",
            image_paths=[],
            media_type="video",
            caption="caption",
            title="title",
            stats={"video_id": "vid1"},
        ),
        "detected_media_type": "video",
        "source_path": "/tmp/video.mp4",
        "work_dir": "/tmp",
        "evidence": evidence,
        "media_stats": {"video_id": "vid1"},
        **_prepared_evidence_dag("frame_001"),
        "valid_asset_ids": {"frame_001"},
    }
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: events.append("llm_precheck"))
    monkeypatch.setattr(runner, "_prepare_deconstruct_inputs", lambda text, max_frames=8: events.append("prepare") or prepared)
    monkeypatch.setattr(runner, "_evidence_parts_for_llm", lambda prepared_evidence: events.append("evidence_parts") or prepared_evidence.parts)
    monkeypatch.setattr(runner, "cleanup_temp_files", lambda paths: events.append("cleanup"))
    monkeypatch.setattr(
        runner,
        "build_multi_signal_contract",
        lambda result, user_intent="": events.append("multi_signal_contract") or _multi_signal_contract_payload("frame_001"),
    )

    def fake_call_llm(parts, schema, post_validate=None):
        events.append("llm_deconstruct")
        payload = _deconstruct_payload("frame_001")
        return post_validate(payload) if post_validate else payload

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)

    result = runner.run_workflow("【拆解】 https://example.com/video", write_feishu=False)

    assert result["mode"] == "deconstruct_only"
    assert result["deconstruct"]["multi_signal_contract"]["contract_version"] == "multi_signal_contract.v1"
    assert result["deconstruct"]["multi_signal_contract"]["shot_adaptation_notes"][0]["note_id"] == "shot_note_001"
    assert "deconstruct_doc_id" not in result["deconstruct"]
    assert "feishu_record_id" not in result
    assert events == ["llm_precheck", "prepare", "evidence_parts", "llm_deconstruct", "cleanup", "multi_signal_contract"]


def test_retired_deconstruct_recreate_entrypoint_does_not_run_llm_doc_or_bitable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: (_ for _ in ()).throw(AssertionError("不应检查 LLM")))
    monkeypatch.setattr(runner, "deconstruct", lambda text: (_ for _ in ()).throw(AssertionError("不应执行拆解")))
    monkeypatch.setattr(runner, "recreate", lambda text, source: (_ for _ in ()).throw(AssertionError("不应执行再创作")))

    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer
    import selfmedia.deconstruct.viral_content.src.feishu_writer as bitable_writer

    monkeypatch.setattr(doc_writer, "create_checked_doc", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应建文档")))
    monkeypatch.setattr(bitable_writer, "write_deconstruction", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应写表")))

    result = runner.run_workflow("【拆解-再创】 https://example.com/red-light 用户想法", write_feishu=True)

    assert result == {"skipped": True, "reason": "organize_only", "mode": "organize_only"}


def test_acceptance_no_real_media_no_llm_doc_bitable(monkeypatch: pytest.MonkeyPatch) -> None:
    media = SimpleNamespace(video_path=None, audio_path=None, image_paths=[], caption="", stats={}, media_type="unknown")
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "_load_content_ingest_modules", lambda: (lambda: object(), lambda url, settings: media))
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应让 LLM 猜内容")))
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer
    import selfmedia.deconstruct.viral_content.src.feishu_writer as bitable_writer

    monkeypatch.setattr(doc_writer, "create_checked_doc", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应创建文档")))
    monkeypatch.setattr(bitable_writer, "write_deconstruction", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应写表")))
    with pytest.raises(media_parts.NoRealMediaError):
        runner.run_workflow("【拆解】 https://example.com", write_feishu=True)


def test_empty_media_is_retried_before_deconstruction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    empty = SimpleNamespace(video_path=None, audio_path=None, image_paths=[], caption="", stats={}, media_type="unknown")
    ready = SimpleNamespace(video_path=str(video), audio_path=None, image_paths=[], caption="", stats={}, media_type="video")
    results = iter((empty, ready))
    calls: list[str] = []

    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(
        runner,
        "_load_content_ingest_modules",
        lambda: (
            lambda: object(),
            lambda value: calls.append("clean") or value,
            lambda url, settings: calls.append("resolve") or next(results),
        ),
    )
    monkeypatch.setattr(runner, "run_evidence_dag", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("evidence-ready")))
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: calls.append(f"sleep:{seconds:g}"))

    with pytest.raises(RuntimeError, match="evidence-ready"):
        runner._prepare_deconstruct_inputs("【拆解】 https://example.com/video")

    assert calls == ["clean", "resolve", "sleep:1", "clean", "resolve"]
