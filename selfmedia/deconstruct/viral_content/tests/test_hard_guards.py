from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest

from selfmedia.request_constraints import parse_request_constraints
from selfmedia.deconstruct.viral_content.src import media_parts, prompt, runner
from selfmedia.deconstruct.viral_content.src.config import ConfigError, ViralDeconstructConfig
from selfmedia.deconstruct.viral_content.src.evidence import modality_dag
from selfmedia.deconstruct.viral_content.src.feishu_writer import (
    _external_post_id,
    _platform_from_url,
    build_attachment_plan,
    source_asset_attachment_inputs,
    write_deconstruction,
)
import common.llm_client as common_llm_client
from common.model_transport_context import ModelTransportError
from selfmedia.deconstruct.viral_content.src.llm_client import generate_json
from selfmedia.deconstruct.viral_content.src.schemas import (
    DeconstructResult,
    PRODUCTION_ROUTE_VALUES,
    RecreateResult,
    SchemaError,
    validate_evidence_asset_ids,
    validate_schema,
    validate_video_storyboard_granularity,
)
from selfmedia.deconstruct.viral_content.src.trigger import WorkflowMode, route_mode
from _fakes import SseResponse, recording_post
from _fixtures import multi_signal_contract_payload as _multi_signal_contract_payload


def _test_config(**overrides) -> ViralDeconstructConfig:
    params = {
        "model": "model",
        "base_url": "https://example.com/v1",
        "api_key": "key",
        "timeout": 1,
        "source_assets_url": "",
        "material_deconstructions_url": "",
        "feishu_doc_folder_token": "",
        "feishu_wiki_parent_node_token": "",
        "feishu_deconstruct_parent_node_token": "",
        "feishu_recreate_parent_node_token": "",
        "part1_path": runner.ROOT,
    }
    params.update(overrides)
    return ViralDeconstructConfig(**params)


def _required_deconstruct_v2_fields() -> dict[str, object]:
    return {
        "request_constraints": parse_request_constraints("【拆解】 https://example.com/video").to_dict(),
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
        "attention_elements": ["红光暗房", "近景自拍", "关系问题"],
        "viral_migration": "迁移关系留白结构，替换人物身份、场景和文案。",
        "creative_upgrade_suggestion": "把暧昧提问升级成观众审判局，让评论区承担第二叙事层。",
    }


def _minimal_evidence_dag(asset_id: str = "frame_001") -> dict[str, object]:
    asset_manifest = {
        "schema_version": "asset_manifest_v1",
        "source_url": "https://example.com/video",
        "media_type": "video",
        "source_path": "/tmp/source.mp4",
        "work_dir": "/tmp",
        "video_path": "/tmp/source.mp4",
        "image_paths": [],
        "audio_path": "/tmp/audio.mp3",
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
                "visual_hook": {"media_kind": "video", "primary_asset_ids": [asset_id]},
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
            "evidence_manifest": {asset_id: {"type": "visual", "asset_id": asset_id, "kind": "keyframe"}},
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
                "why_better": "不只问能不能纠缠，而是把关系选择权交给评论区，天然引发站队。",
                "learn_from_reference": ["低成本红光暗房", "近距离自拍", "关系问题留白"],
                "must_transform": ["换成用户自己的关系困境", "不要复用原句", "不要照搬原人设和视觉组合"],
                "execution_angle": "主角只抛一个暧昧问题，剪辑把观众推到裁判位置。",
            },
            "backup_variants": [
                {
                    "title": "前任视角反问版",
                    "difference": "从自我拉扯改成前任旁白，评论区更容易补故事。",
                    "best_for": "账号有人设口播或情绪独白素材时使用。",
                    "risk": "容易像卖惨，需要保留幽默反讽。",
                },
                {
                    "title": "朋友审讯室版",
                    "difference": "把红光暗房改成朋友逼问，降低暧昧擦边感。",
                    "best_for": "需要更安全、更生活化的拍摄版本。",
                    "risk": "戏剧性会下降，必须靠剪辑节奏补足。",
                },
            ],
        },
        "production_route_plan": {
            "route_policy": "优先真实素材剪辑，缺少红光自拍时再补拍；Remotion 只做字幕动效，FFmpeg 只做压制交付。",
            "shot_route_table": [
                {
                    "segment_id": "0-2s",
                    "story_purpose": "用红光近景抛出关系问题",
                    "route": "需要补拍",
                    "needed_material": "暗房、红色小夜灯、主角正脸近景",
                    "execution_note": "第一句只问一个问题，不解释前因后果。",
                    "risk_or_manual_check": "不能复用原视频同款句子和表情节奏。",
                },
                {
                    "segment_id": "2-7s",
                    "story_purpose": "让观众意识到自己正在替主角判案",
                    "route": "动效字幕",
                    "needed_material": "两三句短字幕和停顿镜头",
                    "execution_note": "字幕用审判/站队感，不堆剧情。",
                    "risk_or_manual_check": "字幕不要攻击现实人物。",
                },
                {
                    "segment_id": "交付",
                    "story_purpose": "批量压制竖屏版本",
                    "route": "FFmpeg",
                    "needed_material": "成片和封面帧",
                    "execution_note": "输出 1080x1920，保留暗部但不过度压黑。",
                    "risk_or_manual_check": "检查字幕不遮脸。",
                },
            ],
            "final_assembly": {
                "remotion_usage": "用于批量生成裁判票型字幕模板；本条也可手工完成。",
                "ffmpeg_usage": "用于竖屏压制、响度统一和封面帧导出。",
                "delivery_note": "先交一个主方案成片，再保留两个备选文案方便二次剪。",
            },
        },
        "reusable_high_like_comment": {
            "comment_text": "他问的是能不能纠缠，评论区答的其实是自己当年有没有被放过。",
            "sharp_angle": "把暧昧问题改成观众自我审判，角度刁钻但不点名攻击真人。",
            "why_it_can_get_likes": "观众既能站队，也能把自己的经历投射进去。",
            "reuse_instruction": "可作为置顶评论或首条引导评论，配合视频里的关系问题使用。",
            "risk_boundary": "不要引导网暴、不要暗示具体前任身份、不要引用原评论区内容。",
        },
        "operation_plan": {
            "platform_fit": "适合小红书和抖音情绪短视频：小红书用标题承接关系讨论，抖音用首 3 秒问题和评论区站队承接。",
            "opening_3s_hook": "第一帧红光怼脸，字幕只留一句“你说，纠缠到第几次才算自尊掉线？”",
            "audience_trigger": "刺中正在暧昧拉扯、分手后还会回头看聊天框的人。",
            "comment_area_design": "评论区置顶刁钻评论后，引导观众用“我选放过/我选再问一次”二选一回复。",
            "publish_timing": "晚 22:30-23:30 发，承接睡前情绪和关系复盘场景。",
            "success_metric": "前 2 小时评论率和收藏率高于账号近 7 条均值；评论里出现自述故事就进入复投。",
            "republish_or_iteration": "若评论区偏站队，第二条改成朋友审讯室版；若收藏高但评论弱，改标题强化二选一问题。",
        },
        "material_checklist": {
            "must_have": ["红色小夜灯", "主角近景", "一个原创关系问题"],
            "better_to_have": ["手持轻微晃动", "停顿反应镜头"],
            "can_rescue_without": ["没有红光可用暖色台灯替代"],
            "must_not_fabricate": ["原作品同款文案", "真实前任身份", "不存在的评论证据"],
        },
        "risk_controls": [
            {
                "risk": "像搬运原暧昧短句",
                "control": "只保留关系留白结构，问题、场景、人物身份全部换成用户自己的。",
                "applies_to": "final_script",
            },
            {
                "risk": "评论种子过度攻击某一方",
                "control": "评论只打观众心理，不点名、不骂人、不引导站队攻击。",
                "applies_to": "reusable_high_like_comment",
            },
        ],
    }


def _docx_table_response(body: dict[str, object], rows: int, cols: int) -> dict[str, object]:
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


def test_route_modes_are_code_defined() -> None:
    assert route_mode("普通素材 https://example.com") == WorkflowMode.ORGANIZE_ONLY
    assert route_mode("【拆解】 https://example.com") == WorkflowMode.DECONSTRUCT_ONLY
    assert route_mode("【拆解】【旧拆解到创作交接】 https://example.com") == WorkflowMode.DECONSTRUCT_ONLY
    assert route_mode("【旧拆解到创作交接】 https://example.com") == WorkflowMode.ORGANIZE_ONLY


def test_partial_deconstruct_reuses_prepared_evidence_and_omits_storyboard(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = SimpleNamespace(
        parts=[{"text": "视觉证据 asset_id=frame_001"}],
        evidence_paths=["/tmp/frame_001.jpg"],
        evidence_assets=[{"asset_id": "frame_001", "path": "/tmp/frame_001.jpg", "kind": "keyframe"}],
        cleanup_paths=["/tmp/temp_frame.jpg"],
        audio_path="/tmp/audio.mp3",
        preview_path="/tmp/preview.jpg",
    )
    prepared = {
        "cleaned_url": "https://example.com/video",
        "media": SimpleNamespace(media_type="video", caption="原文案", title="标题", stats={"video_id": "vid1"}),
        "detected_media_type": "video",
        "source_path": "/tmp/source.mp4",
        "work_dir": "/tmp",
        "evidence": evidence,
        "media_stats": {"video_id": "vid1"},
        **_minimal_evidence_dag("frame_001"),
        "valid_asset_ids": {"frame_001"},
    }
    calls: dict[str, object] = {}
    monkeypatch.setattr(runner, "_prepare_deconstruct_inputs", lambda text, max_frames=6: prepared)
    monkeypatch.setattr(runner, "cleanup_temp_files", lambda paths: calls.setdefault("cleanup", paths))

    def fake_call_llm(parts, schema, post_validate=None):
        calls["schema"] = schema.__name__
        payload = {
            "content_summary": "BGM卡点参考",
            "source_summary": "用节奏和首屏标题吸引停留",
            "opening_hook": "首屏标题加最强画面",
            "bgm_or_rhythm": "待剪映搜索同节奏替代",
            "visual_order": [{"segment": "0-2s", "evidence_asset_id": "frame_001", "reusable_point": "强画面开头"}],
            "title_cover_pattern": "短标题压首屏",
            "lightweight_edit_card": ["0-2s 强画面", "2-6s 跟鼓点切素材"],
            "material_fill_suggestions": ["用本地 batch_id 的高情绪画面填空"],
            "avoid_plagiarism_notes": "只借节奏，不照搬原句和身份",
            "production_checklist": ["检查音乐可用", "检查封面可读"],
            "target_audience": ["校园运动受众"],
            "pain_or_pleasure_points": ["速度感"],
            "track_tags": ["#短跑"],
            "evidence_asset_ids": ["frame_001"],
            "confidence": 0.82,
        }
        return post_validate(payload) if post_validate else payload

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)

    result = runner.partial_deconstruct("【拆解】 https://example.com/video\n模式：轻量反抄 / BGM 卡点")

    assert result["mode"] == "partial_deconstruct"
    assert calls["schema"] == "PartialDeconstructResult"
    assert calls["cleanup"] == ["/tmp/temp_frame.jpg"]
    assert "lightweight_edit_card" in result
    assert "video_storyboard" not in result
    assert result["evidence_asset_ids"] == ["frame_001"]


def test_doc_titles_use_content_theme_and_short_id() -> None:
    source = {
        "source_url": "https://v.douyin.com/fKD3JbS5aXk/",
        "source_caption": "我的发 #田径",
        "content_summary": "田径金牌转场",
        "source_summary": "丑效果转场到田径金牌",
        "stats": {"video_id": "video123"},
    }
    recreate = {"doc_title": "田径服露腹肌金牌转场", "creative_positioning": "position"}

    assert runner.deconstruct_doc_title(source, "20260504153001") == "爆款拆解文档｜田径金牌转场｜20260504153001"
    assert (
        runner.recreate_doc_title(
            "【创作】从丑效果转场到跑10秒80，会怎么样？",
            recreate,
            source,
            "20260504153001",
        )
        == "创作交接｜田径金牌转场｜o123｜20260504153001"
    )
    assert (
        runner.recreate_doc_title(
            "【创作】计划 2026-05-08 19:30 发",
            recreate,
            source,
            "20260504153001",
        )
        == "创作交接｜田径金牌转场｜o123｜20260504153001"
    )


def test_no_real_media_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    media = SimpleNamespace(
        video_path=None,
        audio_path=None,
        image_paths=[],
        caption="",
        stats={},
        media_type="unknown",
    )

    monkeypatch.setattr(runner, "_load_content_ingest_modules", lambda: (lambda: object(), lambda url, settings: media))
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    with pytest.raises(media_parts.NoRealMediaError):
        runner.deconstruct("【拆解】 https://example.com")


def test_video_frames_are_cleaned_after_analysis_failure(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    frame_dir = tmp_path / "frames"
    frame = frame_dir / "frame_001.jpg"
    audio = tmp_path / "audio.mp3"

    def fake_extract_frames(video_path: str, out_dir: str, max_frames: int = 8) -> list[str]:
        frame_dir.mkdir()
        frame.write_bytes(b"frame")
        return [str(frame)]

    def fake_extract_audio(video_path: str, out_dir: str, max_duration_sec: int = 60) -> str:
        audio.write_bytes(b"audio")
        return str(audio)

    media = SimpleNamespace(
        video_path=str(video),
        audio_path=None,
        image_paths=[],
        caption="",
        stats={},
        media_type="video",
    )
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
    monkeypatch.setattr(runner, "_load_content_ingest_modules", lambda: (lambda: object(), lambda url, settings: media))
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("llm failed")))

    with pytest.raises(RuntimeError, match="llm failed"):
        runner.deconstruct("【拆解】 https://example.com")
    assert not frame.exists()


def test_attachment_classification_is_strict(tmp_path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.mp3"
    image = tmp_path / "image.jpg"
    screenshot = tmp_path / "interaction-screenshot.png"
    keyframe = tmp_path / "frame_001.jpg"
    for path in (video, audio, image, screenshot, keyframe):
        path.write_bytes(b"x")

    plan = build_attachment_plan(
        {
            "source_preview_path": str(image),
            "source_video_path": str(video),
            "source_audio_path": str(audio),
            "source_image_paths": [str(image)],
            "interaction_screenshot_path": str(screenshot),
            "evidence_assets": [{"asset_id": "frame_001", "path": str(keyframe), "kind": "keyframe"}],
        }
    )
    assert ("preview", str(image)) in {(item.kind, item.path) for item in plan}
    assert ("original_video", str(video)) in {(item.kind, item.path) for item in plan}
    assert ("original_audio", str(audio)) in {(item.kind, item.path) for item in plan}
    assert ("interaction_screenshot", str(screenshot)) in {(item.kind, item.path) for item in plan}
    assert ("keyframe", str(keyframe)) not in {(item.kind, item.path) for item in plan}

    with pytest.raises(ValueError, match="证据文件不存在或为空"):
        build_attachment_plan({"source_video_path": str(tmp_path / "missing.mp4")})


def test_source_asset_attachment_inputs_prefers_cover_and_defers_large_video(tmp_path) -> None:
    cover = tmp_path / "cover.jpg"
    preview = tmp_path / "preview.jpg"
    video = tmp_path / "video.mp4"
    cover.write_bytes(b"cover")
    preview.write_bytes(b"preview")
    with video.open("wb") as handle:
        handle.truncate(20 * 1024 * 1024 + 1)

    selected, status = source_asset_attachment_inputs(
        build_attachment_plan(
            {
                "cover_path": str(cover),
                "source_preview_path": str(preview),
                "source_video_path": str(video),
            }
        )
    )

    assert selected == {"cover_attachment": str(cover)}
    assert status == {
        "cover_attachment": "planned",
        "video_attachment": "deferred_oversize",
    }


def test_source_asset_facts_use_structured_ids_and_url_hosts() -> None:
    assert _external_post_id({"stats": {"platform_asset_id": "698561f"}}) == "698561f"
    assert _external_post_id({"video_id": "7634755"}) == "7634755"
    assert _platform_from_url("https://www.iesdouyin.com/share/video/7634755") == "抖音"
    assert _platform_from_url("https://www.xiaohongshu.com/discovery/item/698561f") == "小红书"
    assert _platform_from_url("https://example.com/?next=douyin.com") == ""


def test_deconstruct_platform_detection_uses_canonical_host_classifier() -> None:
    assert runner._platform_from_url("https://www.douyin.com/video/7634755") == "抖音"
    assert modality_dag._platform_from_url("https://www.xiaohongshu.com/explore/698561f") == "小红书"
    assert runner._platform_from_url("https://example.com/?next=douyin.com") == "未抓取"
    assert modality_dag._platform_from_url("https://example.com/?next=xiaohongshu.com") == "未抓取"


def test_list_like_text_is_written_without_python_brackets() -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    list_text = "['可以借的结构：晴天校园操场开场', '不能抄的内容：不要照搬原文案']"
    blocks = doc_writer._value_blocks(list_text)
    rendered = str(blocks)
    assert "1. 可以借的结构：晴天校园操场开场" in rendered
    assert "2. 不能抄的内容：不要照搬原文案" in rendered
    assert "['" not in rendered
    assert "']" not in rendered


def test_deconstruct_guardrails_render_as_nested_headings() -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    blocks = doc_writer._deconstruct_doc_blocks(
        {
            "content_summary": "内容总结",
            "reuse_guardrails": {
                "allowed_reuse": ["可以学习开场即给强视觉异常"],
                "required_transformations": ["换成人设和场景"],
                "prohibited_reuse": ["不得照搬原字幕"],
                "human_review_required": True,
            },
        },
        include_evidence_appendix=False,
    )
    text = json.dumps(blocks, ensure_ascii=False)
    assert "复用护栏" in text
    assert "1. 可以学" in text
    assert "2. 必须改" in text
    assert "3. 禁止碰" in text
    assert "可以学：可以学习开场即给强视觉异常" not in text


def test_schema_normalizes_list_fields_before_json_backup() -> None:
    payload = {
        "content_summary": "内容总结",
        "source_summary": "summary",
        "viral_mechanism": ["机制一", "机制二"],
        "video_storyboard": [
            {
                "shot_no": 1,
                "duration": "1s",
                "visual": "画面",
                "subtitle": "",
                "voiceover": "",
                "evidence_asset_id": "frame_001",
            }
        ],
        "image_post_script": [{"page_no": 1, "image_prompt": "图", "evidence_asset_id": "frame_001"}],
        "avoid_plagiarism_notes": "['建议一', '建议二']",
        "production_checklist": ["check"],
        "target_audience": "校园青春受众、毕业季拍摄人群",
        "pain_or_pleasure_points": "['心动爽点', '青春遗憾痛点']",
        "track_tags": ["#校园感", "毕业季"],
        **_required_deconstruct_v2_fields(),
    }
    result = validate_schema(payload, DeconstructResult)
    assert result["content_summary"] == "内容总结"
    assert result["viral_mechanism"] == "机制一\n机制二"
    assert result["avoid_plagiarism_notes"] == "建议一\n建议二"
    assert "republish_copy" not in result
    assert result["target_audience"] == ["校园青春受众", "毕业季拍摄人群"]
    assert result["pain_or_pleasure_points"] == ["心动爽点", "青春遗憾痛点"]
    assert result["track_tags"] == ["#校园感", "毕业季"]


def test_video_storyboard_granularity_accepts_first5_each_second_then_3s() -> None:
    payload = {
        "media_type": "video",
        "video_storyboard": [
            {"shot_no": index + 1, "duration": duration, "visual": "画面", "subtitle": "", "voiceover": ""}
            for index, duration in enumerate(["0-1s", "1-2s", "2-3s", "3-4s", "4-5s", "5-8s", "8-11s"])
        ],
    }

    assert validate_video_storyboard_granularity(payload, media_type="video", target_duration_sec=11) is payload


def test_video_storyboard_granularity_uses_nonzero_analysis_time_range() -> None:
    payload = {
        "media_type": "video",
        "request_constraints": {"analysis_time_range": "12-15s,15-18s"},
        "video_storyboard": [
            {"shot_no": 1, "duration": "12-15s", "visual": "第一段", "subtitle": "", "voiceover": ""},
            {"shot_no": 2, "duration": "15-18s", "visual": "第二段", "subtitle": "", "voiceover": ""},
        ],
    }

    assert validate_video_storyboard_granularity(payload, media_type="video", target_duration_sec=18) is payload


def test_video_storyboard_granularity_rejects_rows_before_nonzero_analysis_time_range() -> None:
    payload = {
        "media_type": "video",
        "request_constraints": {"analysis_time_range": "12-15s,15-18s"},
        "video_storyboard": [
            {"shot_no": 1, "duration": "0-1s", "visual": "窗口外画面", "subtitle": "", "voiceover": ""},
        ],
    }

    with pytest.raises(SchemaError, match="已定义的证据采样区间"):
        validate_video_storyboard_granularity(
            payload,
            media_type="video",
            target_duration_sec=18,
            allow_partial_coverage=True,
        )


def test_video_storyboard_granularity_rejects_single_time_with_error_code() -> None:
    payload = {
        "media_type": "video",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "画面", "subtitle": "", "voiceover": ""}],
    }

    with pytest.raises(SchemaError, match="E_STORYBOARD_GRANULARITY"):
        validate_video_storyboard_granularity(payload, media_type="video", target_duration_sec=5)


def test_deconstruct_storyboard_allows_partial_evidence_and_marks_manual_review() -> None:
    payload = {
        "media_type": "video",
        "video_storyboard": [
            {"shot_no": 1, "duration": "0-1s", "visual": "首帧", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_001"},
            {"shot_no": 2, "duration": "5-8s", "visual": "关键帧", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_002"},
        ],
        "viral_reuse_assessment": {"human_review_required": False},
        "reuse_guardrails": {"human_review_required": False},
    }

    result = validate_video_storyboard_granularity(
        payload,
        media_type="video",
        target_duration_sec=8,
        allow_partial_coverage=True,
    )

    assert result["validation"]["storyboard_coverage_status"] == "partial_evidence"
    assert result["validation"]["storyboard_missing_ranges"] == ["1-2s", "2-3s", "3-4s", "4-5s"]
    assert result["viral_reuse_assessment"]["human_review_required"] is True
    assert result["reuse_guardrails"]["human_review_required"] is True


def test_deconstruct_storyboard_partial_evidence_rejects_reused_frame_padding() -> None:
    payload = {
        "media_type": "video",
        "video_storyboard": [
            {"shot_no": 1, "duration": "0-1s", "visual": "首帧", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_001"},
            {"shot_no": 2, "duration": "1-2s", "visual": "重复帧", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_001"},
        ],
    }

    with pytest.raises(SchemaError, match="不可重复使用同一 evidence_asset_id"):
        validate_video_storyboard_granularity(
            payload,
            media_type="video",
            target_duration_sec=5,
            allow_partial_coverage=True,
        )


def test_video_storyboard_granularity_rejects_rows_after_60s() -> None:
    payload = {
        "media_type": "video",
        "video_storyboard": [
            {"shot_no": index + 1, "duration": duration, "visual": "画面", "subtitle": "", "voiceover": ""}
            for index, duration in enumerate(
                [
                    "0-1s",
                    "1-2s",
                    "2-3s",
                    "3-4s",
                    "4-5s",
                    "5-8s",
                    "8-11s",
                    "11-14s",
                    "14-17s",
                    "17-20s",
                    "20-23s",
                    "23-26s",
                    "26-29s",
                    "29-32s",
                    "32-35s",
                    "35-38s",
                    "38-41s",
                    "41-44s",
                    "44-47s",
                    "47-50s",
                    "50-53s",
                    "53-56s",
                    "56-59s",
                    "59-62s",
                ]
            )
        ],
    }

    with pytest.raises(SchemaError, match="长视频只允许拆解前 60 秒"):
        validate_video_storyboard_granularity(payload, media_type="video", target_duration_sec=62)


def test_storyboard_sampling_timestamps_match_contract() -> None:
    assert media_parts.storyboard_sample_timestamps(12) == [0, 1, 2, 3, 4, 5, 8, 11]
    assert media_parts.storyboard_sample_timestamps(60)[:7] == [0, 1, 2, 3, 4, 5, 8]
    assert media_parts.storyboard_sample_timestamps(60)[-1] == 59


def test_deconstruct_prompt_no_longer_requests_direct_recreation_script() -> None:
    assert "把原作品拆成用户可以直接复刻生产的执行稿" not in prompt.DECONSTRUCT_PROMPT
    assert "可执行复刻版" not in prompt.DECONSTRUCT_PROMPT
    assert "直接给 AI 生图、剪辑、拍摄执行" not in prompt.DECONSTRUCT_PROMPT
    assert "供后续创作/拍摄链路另行生成用户自己的脚本" in prompt.DECONSTRUCT_PROMPT
    assert "0-1s、1-2s、2-3s、3-4s、4-5s" in prompt.DECONSTRUCT_PROMPT
    assert "5-8s、8-11s、11-14s" in prompt.DECONSTRUCT_PROMPT
    assert "长视频只拆解前 60 秒" in prompt.DECONSTRUCT_PROMPT


def test_recreate_prompt_does_not_require_missing_contract_dimensions() -> None:
    assert "维度数量由已提供合同中的证据决定" in prompt.RECREATE_PROMPT
    assert "不得要求、假定或补造合同中没有的第 7、8 个维度" in prompt.RECREATE_PROMPT
    assert "可以是 7 维、8 维或更多" not in prompt.RECREATE_PROMPT


def test_main_deconstruct_runner_keeps_nonzero_time_window_boundary() -> None:
    source = inspect.getsource(runner.run_main_deconstruction_llm)

    assert "analysis_time_range 的交集" in source
    assert "不能补写窗口之前的分镜" in source
    assert "0-5s 必须按" not in source


def test_deconstruct_schema_allows_no_execution_scripts() -> None:
    payload = {
        "content_summary": "内容总结",
        "source_summary": "summary",
        "viral_mechanism": "mechanism",
        "video_storyboard": [],
        "image_post_script": [],
        "avoid_plagiarism_notes": "notes",
        "production_checklist": ["check"],
        **_required_deconstruct_v2_fields(),
    }
    result = validate_schema(payload, DeconstructResult)
    assert result["video_storyboard"] == []
    assert result["image_post_script"] == []


def test_doc_inaccessible_stops_before_bitable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    image = tmp_path / "image.jpg"
    image.write_bytes(b"img")
    deconstruct_result = {
        "content_summary": "内容总结",
        "source_summary": "summary",
        "viral_mechanism": "mechanism",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "v"}],
        "image_post_script": [{"page_no": 1, "image_prompt": "p"}],
        "avoid_plagiarism_notes": "notes",
        "production_checklist": ["check"],
        "source_url": "https://example.com",
        "source_video_path": "",
        "source_audio_path": "",
        "source_image_paths": [str(image)],
        "source_preview_path": str(image),
        "evidence_assets": [{"asset_id": "image_001", "path": str(image), "kind": "source_image"}],
    }

    monkeypatch.setattr(runner, "deconstruct", lambda text, **_kwargs: dict(deconstruct_result))
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)

    def fail_doc(*args, **kwargs):
        raise RuntimeError("doc inaccessible")

    def fail_write(*args, **kwargs):
        raise AssertionError("不应写多维表格")

    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer
    import selfmedia.deconstruct.viral_content.src.feishu_writer as bitable_writer

    monkeypatch.setattr(doc_writer, "create_checked_doc", fail_doc)
    monkeypatch.setattr(bitable_writer, "write_deconstruction", fail_write)

    with pytest.raises(RuntimeError, match="doc inaccessible"):
        runner.run_workflow("【拆解】 https://example.com", write_feishu=True)


def test_storyboard_image_cell_uses_image_block_not_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    captured: list[dict[str, object]] = []

    class Response:
        status_code = 200
        text = ""
        payload: dict[str, object]

        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def json(self) -> dict[str, object]:
            return self.payload

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int) -> Response:
        captured.append(json)
        if json.get("children") == [{"block_type": 27, "image": {}}]:
            return Response({"code": 0, "data": {"children": [{"block_id": "image_block", "block_type": 27}]}})
        return Response(_docx_table_response(json, 2, 5))

    monkeypatch.setattr(doc_writer.requests, "post", fake_post)
    patch_bodies: list[dict[str, object]] = []
    upload_calls: list[dict[str, object]] = []

    def fake_patch(*args, **kwargs):
        patch_bodies.append(kwargs.get("json", {}))
        return Response({"code": 0, "data": {}})

    def fake_upload(document_id, file_path, token, feishu_base=None, parent_node=None):
        upload_calls.append({"file_path": file_path, "parent_node": parent_node})
        return "img_token"

    monkeypatch.setattr(doc_writer.requests, "patch", fake_patch)
    monkeypatch.setattr(doc_writer, "upload_feishu_doc_image", fake_upload)
    doc_writer.append_storyboard_table(
        "doc123",
        [{"shot_no": 1, "duration": "1s", "visual": "本地路径不能写进画面图"}],
        "token",
        [{"shot_no": "1", "path": "/tmp/storyboard_01.png", "file_token": "img_token"}],
    )

    assert any(
        item.get("block_type") == 27 and item.get("image") == {}
        for body in captured
        for item in body.get("children", [])
    )
    assert upload_calls == [{"file_path": "/tmp/storyboard_01.png", "parent_node": "image_block"}]
    assert patch_bodies == [{"replace_image": {"token": "img_token"}}]
    assert "/tmp/storyboard_01.png" not in str(captured)


def test_storyboard_table_header_uses_visual_description(monkeypatch: pytest.MonkeyPatch) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    texts: list[str] = []

    monkeypatch.setattr(doc_writer, "_create_docx_table", lambda *args, **kwargs: [f"cell_{idx}" for idx in range(10)])
    monkeypatch.setattr(doc_writer, "_append_image_file_to_cell", lambda *args, **kwargs: None)

    def fake_append_cell_blocks(document_id, cell_id, blocks, token, error_label):
        for block in blocks:
            for element in block.get("text", {}).get("elements", []):
                content = element.get("text_run", {}).get("content")
                if content:
                    texts.append(content)

    monkeypatch.setattr(doc_writer, "_append_cell_blocks", fake_append_cell_blocks)
    doc_writer.append_storyboard_table(
        "doc123",
        [{"shot_no": 1, "duration": "1s", "visual": "画面内容", "subtitle": "上屏文字", "voiceover": ""}],
        "token",
        [],
    )

    assert texts[:5] == ["时间", "画面", "字幕/口播", "声音/拍摄注意", "画面图"]
    assert "画面内容" in texts
    assert "上屏文字" in texts


def test_deconstruct_storyboard_uses_uploaded_evidence_asset_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    captured: list[dict[str, object]] = []

    class Response:
        status_code = 200
        text = ""
        payload: dict[str, object]

        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def json(self) -> dict[str, object]:
            return self.payload

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int) -> Response:
        captured.append(json)
        if json.get("children") == [{"block_type": 27, "image": {}}]:
            return Response({"code": 0, "data": {"children": [{"block_id": "image_block", "block_type": 27}]}})
        return Response(_docx_table_response(json, 2, 5))

    patch_bodies: list[dict[str, object]] = []
    monkeypatch.setattr(doc_writer.requests, "post", fake_post)
    monkeypatch.setattr(
        doc_writer.requests,
        "patch",
        lambda *args, **kwargs: patch_bodies.append(kwargs.get("json", {})) or Response({"code": 0, "data": {}}),
    )
    monkeypatch.setattr(doc_writer, "upload_feishu_doc_image", lambda document_id, file_path, token, feishu_base=None, parent_node=None: "uploaded_frame_token")
    doc_writer.append_storyboard_table(
        "doc123",
        [{"shot_no": 1, "duration": "1s", "visual": "画面", "evidence_asset_id": "frame_001"}],
        "token",
        [{"asset_id": "frame_001", "path": "/tmp/frame_001.jpg", "file_token": "uploaded_frame_token"}],
        strict_images=True,
    )

    assert patch_bodies == [{"replace_image": {"token": "uploaded_frame_token"}}]
    assert "/tmp/frame_001.jpg" not in str(captured)
    assert "frame_001.jpg" not in str(captured)


def test_video_deconstruct_doc_skips_execution_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    events: list[str] = []

    monkeypatch.setattr(doc_writer, "tenant_access_token", lambda: "token")
    monkeypatch.setattr(
        doc_writer,
        "load_config",
        lambda: SimpleNamespace(feishu_wiki_parent_node_token="", feishu_doc_folder_token=""),
    )
    monkeypatch.setattr(
        doc_writer.requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            text="",
            raise_for_status=lambda: None,
            json=lambda: {"code": 0, "data": {"document": {"document_id": "doc123"}}},
        ),
    )
    def fake_append_blocks(*args, **kwargs):
        events.append(("blocks", kwargs.get("include_evidence_appendix")))

    monkeypatch.setattr(doc_writer, "append_blocks", fake_append_blocks)
    monkeypatch.setattr(doc_writer, "append_storyboard_table", lambda *args, **kwargs: events.append("storyboard_table"))
    monkeypatch.setattr(doc_writer, "append_image_post_table", lambda *args, **kwargs: events.append("image_post_table"))
    monkeypatch.setattr(doc_writer, "append_evidence_appendix", lambda *args, **kwargs: events.append("evidence_appendix"))

    doc_writer.create_doc(
        "title",
        {
            "media_type": "video",
            "source_video_path": "/tmp/video.mp4",
            "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "v", "evidence_asset_id": "frame_001"}],
            "image_post_script": [{"page_no": 1, "image_prompt": "p", "evidence_asset_id": "frame_001"}],
            "evidence_assets": [{"asset_id": "frame_001", "path": "/tmp/frame_001.jpg", "kind": "keyframe"}],
            "content_summary": "内容总结",
            "source_summary": "summary",
        },
        doc_kind="deconstruct",
    )

    assert events == [("blocks", False), "evidence_appendix"]


def test_reused_feishu_doc_is_rewritten_without_supplement_record(monkeypatch: pytest.MonkeyPatch) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    events: list[str] = []
    monkeypatch.setattr(doc_writer, "tenant_access_token", lambda: "token")
    monkeypatch.setattr(
        doc_writer,
        "load_config",
        lambda: SimpleNamespace(
            feishu_wiki_parent_node_token="parent",
            feishu_deconstruct_parent_node_token="parent",
            feishu_recreate_parent_node_token="",
            feishu_doc_folder_token="",
        ),
    )
    monkeypatch.setattr(doc_writer, "_get_parent_space", lambda parent_node, token: "space")
    monkeypatch.setattr(doc_writer, "_find_child_doc", lambda space_id, parent_node, title, token: ("doc_existing", "node_existing"))
    monkeypatch.setattr(doc_writer, "_clear_document_blocks", lambda document_id, token: events.append(f"clear:{document_id}"))
    monkeypatch.setattr(doc_writer, "append_blocks", lambda *args, **kwargs: events.append(("blocks", kwargs.get("include_evidence_appendix"))))
    monkeypatch.setattr(doc_writer, "append_storyboard_table", lambda *args, **kwargs: events.append("storyboard_table"))
    monkeypatch.setattr(doc_writer, "append_image_post_table", lambda *args, **kwargs: events.append("image_post_table"))
    monkeypatch.setattr(doc_writer, "append_evidence_appendix", lambda *args, **kwargs: events.append("evidence_appendix"))
    monkeypatch.setattr(
        doc_writer,
        "_post_docx_children",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应追加补充记录")),
    )

    document_id = doc_writer.create_doc(
        "title",
        {
            "media_type": "video",
            "source_video_path": "/tmp/video.mp4",
            "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "v", "evidence_asset_id": "frame_001"}],
            "image_post_script": [],
            "evidence_assets": [{"asset_id": "frame_001", "path": "/tmp/frame_001.jpg", "kind": "keyframe"}],
            "content_summary": "内容总结",
            "source_summary": "summary",
        },
        doc_kind="deconstruct",
    )

    assert document_id == "doc_existing"
    assert events == ["clear:doc_existing", ("blocks", False), "evidence_appendix"]


def test_llm_invalid_evidence_asset_id_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def payload(asset_id: str) -> dict[str, object]:
        return {
            "content_summary": "内容总结",
            "source_summary": "summary",
            "viral_mechanism": "mechanism",
            "video_storyboard": [
                {
                    "shot_no": 1,
                    "duration": "1s",
                    "visual": "画面",
                    "subtitle": "",
                    "voiceover": "",
                    "evidence_asset_id": asset_id,
                }
            ],
            "image_post_script": [{"page_no": 1, "image_prompt": "图", "evidence_asset_id": asset_id}],
            "avoid_plagiarism_notes": "notes",
            "production_checklist": ["check"],
            **_required_deconstruct_v2_fields(),
        }

    def fake_generate_once(parts, config, **_kwargs):
        calls["count"] += 1
        return payload("bad_id" if calls["count"] == 1 else "frame_001")

    monkeypatch.setattr(common_llm_client, "generate_json_once", fake_generate_once)
    config = _test_config()
    result = generate_json(
        [{"text": "prompt"}],
        config,
        schema=DeconstructResult,
        post_validate=lambda item: validate_evidence_asset_ids(item, {"frame_001"}),
    )
    assert calls["count"] == 2
    assert result["video_storyboard"][0]["evidence_asset_id"] == "frame_001"


def test_llm_transport_error_is_not_retried_and_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """ModelTransportError is documented as a terminal transport outcome that
    callers must not hide or auto-retry (common/model_transport_context.py).
    This used to be asserted backwards: `_generate_json_once` translated every
    RuntimeError -- ModelTransportError included, since it is a RuntimeError
    subclass -- into ConfigError, and the outer retry loop then retried that
    ConfigError like an ordinary JSON/schema validation failure, silently
    turning a terminal error into a retried one. generate_json() now re-raises
    ModelTransportError unchanged and does not retry it.
    """

    calls = {"count": 0}

    def fake_generate_once(parts, config, **_kwargs):
        calls["count"] += 1
        raise ModelTransportError("transport_watchdog_timeout", "Codex Responses SSE watchdog timeout")

    monkeypatch.setattr(common_llm_client, "generate_json_once", fake_generate_once)
    config = _test_config()

    with pytest.raises(ModelTransportError, match="Codex Responses SSE watchdog timeout"):
        generate_json(
            [{"text": "prompt"}],
            config,
            schema=DeconstructResult,
            post_validate=lambda item: validate_evidence_asset_ids(item, {"frame_001"}),
        )

    assert calls["count"] == 1


def test_v2_writer_exposes_only_v2_source_and_payload_args() -> None:
    signature = inspect.signature(write_deconstruction)
    assert list(signature.parameters) == ["result", "source_text", "tenant_id"]
    assert signature.parameters["tenant_id"].kind is inspect.Parameter.KEYWORD_ONLY


def test_v2_writer_writes_source_asset_and_deconstruction(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_writer as writer

    tenant_id = "00000000-0000-4000-8000-000000000001"
    cover = tmp_path / "cover.jpg"
    video = tmp_path / "video.mp4"
    cover.write_bytes(b"cover")
    video.write_bytes(b"video")
    monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", str(tmp_path / "media_vault"))
    monkeypatch.setenv("MEDIA_OS_SOURCE_ASSETS_URL", "https://example.feishu.cn/base/app?table=source")
    monkeypatch.setenv("MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL", "https://example.feishu.cn/base/app?table=decon")
    monkeypatch.setattr(writer, "load_default_env_files", lambda: None)
    monkeypatch.setattr(writer, "load_env_file", lambda _path: None)
    writes: list[tuple[str, dict[str, object], dict[str, object]]] = []

    projection_calls: list[dict[str, object]] = []

    def fake_project(**kwargs):
        projection_calls.append(kwargs)

    monkeypatch.setattr(writer, "_project_canonical_source_asset", fake_project)

    def fake_upsert(entity_name: str, table_url: str, payload: dict[str, object], **kwargs):
        writes.append((entity_name, payload, kwargs))
        if entity_name == "SourceAsset":
            return {
                "record_id": "SourceAsset_record",
                "fields": {
                    "封面附件": [{"file_token": "cover_token"}],
                    "视频附件": [{"file_token": "video_token"}],
                },
            }
        return {"record_id": f"{entity_name}_record"}

    monkeypatch.setattr(writer, "upsert_entity_record", fake_upsert)

    record_id = write_deconstruction(
        {
            "schema_version": "deconstruction.v2",
            "source_url": "https://www.xiaohongshu.com/explore/post1?utm_source=test",
            "platform": "小红书",
            "source_title": "表达力复盘",
            "source_caption": "真实会议表达力复盘",
            "cover_path": str(cover),
            "source_video_path": str(video),
            "content_summary": "一次真实会议表达力卡住后的复盘。",
            "tenant_id": "attacker-tenant-must-be-ignored",
            "viral_mechanism": "用冲突开头抓住表达力痛点。",
            "production_checklist": ["封面给出卡住瞬间", "正文拆三个动作"],
            "stats": {"author_id": "author1"},
            "deconstruct_doc_url": "https://tcnwueberajc.feishu.cn/docx/doc1",
            **_minimal_evidence_dag("frame_001"),
            "evidence_manifest": {"frame_001": {"type": "visual", "asset_id": "frame_001", "kind": "keyframe"}},
            "multi_signal_contract": _multi_signal_contract_payload(),
            **_required_deconstruct_v2_fields(),
        },
        "【拆解】 https://www.xiaohongshu.com/explore/post1",
        tenant_id=tenant_id,
    )

    assert record_id == "MaterialDeconstruction_record"
    assert [item[0] for item in writes] == ["SourceAsset", "MaterialDeconstruction"]
    assert len(projection_calls) == 1
    assert projection_calls[0]["tenant_id"] == tenant_id
    assert projection_calls[0]["result"]["tenant_id"] == "attacker-tenant-must-be-ignored"
    assert projection_calls[0]["source_asset_record"]["record_id"] == "SourceAsset_record"
    assert projection_calls[0]["deconstruction_record"]["record_id"] == "MaterialDeconstruction_record"
    assert "tenant_id" not in projection_calls[0]["asset_payload"]
    source_payload = writes[0][1]
    decon_payload = writes[1][1]
    assert writes[0][2] == {
        "key_field": "asset_id",
        "session_tenant_id": tenant_id,
        "attachment_paths": {
            "cover_attachment": str(cover),
            "video_attachment": str(video),
        },
    }
    assert writes[1][2] == {
        "key_field": "deconstruction_id",
        "session_tenant_id": tenant_id,
    }
    assert source_payload["asset_id"]
    assert source_payload["source_url"] == "https://www.xiaohongshu.com/explore/post1"
    assert source_payload["source_doc_link"] == "https://tcnwueberajc.feishu.cn/docx/doc1"
    assert str(source_payload["evidence_uri"]).startswith("media://")
    assert decon_payload["asset_id"] == source_payload["asset_id"]
    assert decon_payload["deconstruction_doc_link"] == "https://tcnwueberajc.feishu.cn/docx/doc1"
    assert str(decon_payload["evidence_uri"]).startswith("media://")
    evidence_path = tmp_path / "media_vault" / str(source_payload["evidence_uri"]).removeprefix("media://")
    source_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert source_evidence["attachment_backwash"] == {
        "cover_attachment": {"status": "completed", "file_tokens": ["cover_token"]},
        "video_attachment": {"status": "completed", "file_tokens": ["video_token"]},
    }
    assert {(item["kind"], item["path"]) for item in source_evidence["attachments"]} == {
        ("cover", str(cover)),
        ("original_video", str(video)),
    }
    assert decon_payload["shot_adaptation_notes_status"] == "validated"
    assert decon_payload["shot_adaptation_note_count"] == 1
    assert decon_payload.get("recommended_production_route", "") == ""
    assert decon_payload.get("motion_type_summary", "") == ""
    assert "shot_note_001" in decon_payload["shot_adaptation_notes_summary"]
    assert evidence_path.exists()
    deconstruction_path = tmp_path / "media_vault" / str(decon_payload["evidence_uri"]).removeprefix("media://")
    assert deconstruction_path.exists()


def test_v2_writer_projection_failure_blocks_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_writer as writer

    tenant_id = "00000000-0000-4000-8000-000000000003"
    monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", str(tmp_path / "media_vault"))
    monkeypatch.setenv("MEDIA_OS_SOURCE_ASSETS_URL", "https://example.feishu.cn/base/app?table=source")
    monkeypatch.setenv("MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL", "https://example.feishu.cn/base/app?table=decon")
    monkeypatch.setattr(writer, "load_default_env_files", lambda: None)
    monkeypatch.setattr(writer, "load_env_file", lambda _path: None)
    events: list[str] = []

    def fake_upsert(entity_name: str, table_url: str, payload: dict[str, object], **kwargs):
        events.append(entity_name)
        if entity_name == "SourceAsset":
            return {"record_id": "source", "fields": {}}
        return {"record_id": "deconstruction", "fields": {}}

    def fail_projection(**kwargs):
        raise RuntimeError("canonical source projection failed")

    monkeypatch.setattr(writer, "upsert_entity_record", fake_upsert)
    monkeypatch.setattr(writer, "_project_canonical_source_asset", fail_projection)

    with pytest.raises(RuntimeError, match="canonical source projection failed"):
        write_deconstruction(
            {
                "schema_version": "deconstruction.v2",
                "source_url": "https://www.xiaohongshu.com/explore/post3",
                "platform": "小红书",
                "source_caption": "投影失败不能宣称完成",
                "content_summary": "summary",
                "viral_mechanism": "mechanism",
                "evidence_manifest": {"frame_001": {"type": "visual", "asset_id": "frame_001", "kind": "keyframe"}},
                **_minimal_evidence_dag("frame_001"),
                **_required_deconstruct_v2_fields(),
            },
            "【拆解】 https://www.xiaohongshu.com/explore/post3",
            tenant_id=tenant_id,
        )

    assert events == ["SourceAsset", "MaterialDeconstruction"]

def test_v2_writer_marks_attachment_backwash_failed_when_source_asset_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_writer as writer

    tenant_id = "00000000-0000-4000-8000-000000000002"
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", str(tmp_path / "media_vault"))
    monkeypatch.setenv("MEDIA_OS_SOURCE_ASSETS_URL", "https://example.feishu.cn/base/app?table=source")
    monkeypatch.setenv("MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL", "https://example.feishu.cn/base/app?table=decon")
    monkeypatch.setattr(writer, "load_default_env_files", lambda: None)
    monkeypatch.setattr(writer, "load_env_file", lambda _path: None)
    source_payload: dict[str, object] = {}

    def fail_upsert(entity_name: str, table_url: str, payload: dict[str, object], **kwargs):
        source_payload.update(payload)
        raise RuntimeError("bitable write rejected")

    monkeypatch.setattr(writer, "upsert_entity_record", fail_upsert)

    with pytest.raises(RuntimeError, match="bitable write rejected"):
        write_deconstruction(
            {
                "source_url": "https://www.xiaohongshu.com/explore/post2",
                "platform": "小红书",
                "source_caption": "写入失败应保留回洗失败状态",
                "cover_path": str(cover),
                "evidence_store": {"schema_version": "evidence_store_v1"},
            },
            "【拆解】 https://www.xiaohongshu.com/explore/post2",
            tenant_id=tenant_id,
        )

    evidence_path = tmp_path / "media_vault" / str(source_payload["evidence_uri"]).removeprefix("media://")
    source_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert source_evidence["attachment_backwash"] == {
        "cover_attachment": {"status": "failed"},
        "video_attachment": {"status": "source_missing"},
    }


def test_missing_llm_key_fails_fast_before_part1(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _test_config(api_key="")
    monkeypatch.setattr(runner, "load_config", lambda: config)
    monkeypatch.setattr(runner, "_load_content_ingest_modules", lambda: (_ for _ in ()).throw(AssertionError("不应下载素材")))
    with pytest.raises(ConfigError):
        runner.run_workflow("【拆解】 https://example.com", write_feishu=True)


def test_llm_missing_fields_stops_before_doc_and_bitable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "deconstruct", lambda text, **_kwargs: (_ for _ in ()).throw(RuntimeError("LLM 输出 JSON 校验失败")))

    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer
    import selfmedia.deconstruct.viral_content.src.feishu_writer as bitable_writer

    monkeypatch.setattr(doc_writer, "create_checked_doc", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应建文档")))
    monkeypatch.setattr(bitable_writer, "write_deconstruction", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应写表")))

    with pytest.raises(RuntimeError, match="LLM 输出 JSON 校验失败"):
        runner.run_workflow("【拆解】 https://example.com", write_feishu=True)


def test_schema_requires_subtitle_voiceover_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_generate_once(parts, config, **_kwargs):
        return {
            "content_summary": "内容总结",
            "source_summary": "summary",
            "viral_mechanism": "mechanism",
            "video_storyboard": [
                {
                    "shot_no": 1,
                    "duration": "1s",
                    "visual": "画面",
                    "evidence_asset_id": "frame_001",
                }
            ],
            "image_post_script": [{"page_no": 1, "image_prompt": "图", "evidence_asset_id": "frame_001"}],
            "avoid_plagiarism_notes": "notes",
            "production_checklist": ["check"],
        }

    monkeypatch.setattr(common_llm_client, "generate_json_once", fake_generate_once)
    config = _test_config()
    with pytest.raises(RuntimeError, match="LLM 输出 JSON 校验失败"):
        generate_json(
            [{"text": "prompt"}],
            config,
            schema=DeconstructResult,
            post_validate=lambda item: validate_evidence_asset_ids(item, {"frame_001"}),
            max_retries=0,
        )


def test_schema_clears_fabricated_subtitle_markers() -> None:
    payload = {
        "content_summary": "内容总结",
        "source_summary": "summary",
        "viral_mechanism": "mechanism",
        "video_storyboard": [
            {
                "shot_no": 1,
                "duration": "1s",
                "visual": "画面",
                "subtitle": "假设复刻字幕：别躲。",
                "voiceover": "假设口播：别躲。",
                "evidence_asset_id": "frame_001",
            }
        ],
        "image_post_script": [{"page_no": 1, "image_prompt": "图", "evidence_asset_id": "frame_001"}],
        "avoid_plagiarism_notes": "notes",
        "production_checklist": ["check"],
        **_required_deconstruct_v2_fields(),
    }
    result = validate_schema(payload, DeconstructResult)
    assert result["video_storyboard"][0]["subtitle"] == ""
    assert result["video_storyboard"][0]["voiceover"] == ""


def _recreate_payload_with_both_scripts() -> dict[str, object]:
    return {
        **_required_recreate_part2_fields(),
        "creative_positioning": "new angle",
        "final_script": "script",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "视频画面", "subtitle": "", "voiceover": ""}],
        "image_post_script": [{"page_no": 1, "image_prompt": "图文画面"}],
        "titles": ["title"],
        "hashtags": ["tag"],
        "production_notes": ["note"],
        "anti_copy_notes": "anti",
    }


def _doc_text(blocks: list[dict[str, object]]) -> str:
    return json.dumps(blocks, ensure_ascii=False)


def test_recreate_schema_rejects_legacy_payload_without_part2_contract() -> None:
    legacy_payload = {
        "creative_positioning": "new angle",
        "final_script": "script",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "视频画面", "subtitle": "", "voiceover": ""}],
        "image_post_script": [],
        "titles": ["title"],
        "hashtags": ["tag"],
        "production_notes": ["note"],
        "anti_copy_notes": "anti",
    }
    with pytest.raises(ValueError, match="editorial_plan"):
        validate_schema(legacy_payload, RecreateResult)


def test_recreate_schema_accepts_part2_contract_from_feishu_sample_context() -> None:
    result = validate_schema(_recreate_payload_with_both_scripts(), RecreateResult)

    assert result["editorial_plan"]["primary_plan"]["title"] == "把红光暧昧改成观众审判局"
    assert len(result["editorial_plan"]["backup_variants"]) == 2
    assert result["reusable_high_like_comment"]["sharp_angle"]
    assert "评论区" in result["operation_plan"]["comment_area_design"]
    assert "前 2 小时" in result["operation_plan"]["success_metric"]
    assert result["production_route_plan"]["shot_route_table"][0]["route"] == "需要补拍"


def test_recreate_schema_rejects_invalid_production_route() -> None:
    payload = _recreate_payload_with_both_scripts()
    route_plan = dict(payload["production_route_plan"])
    rows = [dict(item) for item in route_plan["shot_route_table"]]
    rows[0]["route"] = "全自动样片门禁"
    route_plan["shot_route_table"] = rows
    payload["production_route_plan"] = route_plan

    with pytest.raises(ValueError, match="production_route_plan.route 非法"):
        validate_schema(payload, RecreateResult)


def test_recreate_doc_renders_part2_execution_sections_without_raw_json() -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    content = {
        **_recreate_payload_with_both_scripts(),
        "media_type": "video",
        "image_post_script": [],
    }
    blocks = doc_writer._recreate_doc_blocks(content)
    text = _doc_text(blocks)
    assert "千万年薪编导会怎么把这条改出彩？" in text
    assert "两个备选改法" in text
    assert "这条内容怎么生产出来" in text
    assert "可复用高赞评论" in text
    assert "刁钻角度" in text
    assert "这条内容怎么发" in text
    assert "首 3 秒钩子" in text
    assert "观察指标" in text
    assert "素材检查清单" in text
    assert "风险控制" in text
    assert "```" not in text
    assert "|---" not in text
    assert '"primary_plan"' not in text


def test_recreate_video_prunes_image_post_script(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_parts: list[dict[str, object]] = []
    source = {
        "media_type": "video",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "原画面", "subtitle": "", "voiceover": ""}],
        "multi_signal_contract": _multi_signal_contract_payload(),
    }
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    loaded_profiles: list[str] = []
    monkeypatch.setattr(runner, "load_config", lambda profile_name="media_analysis": loaded_profiles.append(profile_name) or _test_config())

    def fake_call_llm(parts, schema, post_validate=None, **kwargs):
        assert kwargs["profile_name"] == "media_creation"
        captured_parts.extend(parts)
        return _recreate_payload_with_both_scripts()

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)
    result = runner.recreate("【拆解-再创】做转场短视频", source)
    serialized_parts = json.dumps(captured_parts, ensure_ascii=False)
    assert "本次创作交接类型：video" in serialized_parts
    assert "唯一 multi_signal_contract 多维证据合同" in serialized_parts
    assert "source_signal_dimensions" in serialized_parts
    assert "storyboard_images_default" in serialized_parts
    assert "sample_gate_enabled" in serialized_parts
    assert "Remotion" in serialized_parts
    for route in PRODUCTION_ROUTE_VALUES:
        assert route in serialized_parts
    assert result["media_type"] == "video"
    assert result["video_storyboard"]
    assert result["image_post_script"] == []
    assert result["generate_storyboard_images"] is False
    assert loaded_profiles == ["media_creation"]


def test_recreate_generates_storyboard_images_only_when_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    source = {
        "media_type": "video",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "原画面", "subtitle": "", "voiceover": ""}],
        "multi_signal_contract": _multi_signal_contract_payload(),
    }
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "load_config", lambda _profile_name="media_analysis": _test_config())
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: _recreate_payload_with_both_scripts())

    result = runner.recreate("【拆解-再创】做转场短视频，生成分镜图", source)
    assert result["generate_storyboard_images"] is True


def test_recreate_image_post_prunes_video_script(monkeypatch: pytest.MonkeyPatch) -> None:
    source = {
        "media_type": "video",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "原画面", "subtitle": "", "voiceover": ""}],
        "multi_signal_contract": _multi_signal_contract_payload(),
    }
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "load_config", lambda _profile_name="media_analysis": _test_config())
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: _recreate_payload_with_both_scripts())

    result = runner.recreate("【拆解-再创】改成小红书图文", source)
    assert result["media_type"] == "image_post"
    assert result["video_storyboard"] == []
    assert result["image_post_script"]


def test_recreate_requires_multi_signal_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    source = {
        "media_type": "video",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "原画面", "subtitle": "", "voiceover": ""}],
    }
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: (_ for _ in ()).throw(AssertionError("不应调用 LLM")))

    with pytest.raises(RuntimeError, match="multi_signal_contract"):
        runner.recreate("【拆解-再创】做转场短视频", source)


def test_recreate_prompt_only_receives_multi_signal_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_parts: list[dict[str, object]] = []
    source = {
        "media_type": "video",
        "source_url": "https://example.com/video",
        "content_summary": "summary",
        "evidence_store": {"huge": "x" * 20000},
        "modality_facts": {"ocr": {"facts": {"visible_text_segments": ["x" * 20000]}}},
        "viral_reuse_assessment": {"non_contract_assessment": "不得进入再创输入"},
        "pacing_profile": {"non_contract_pacing": "不得进入再创输入"},
        "reuse_guardrails": {"non_contract_guardrail": "不得进入再创输入"},
        "human_readable_brief": {"non_contract_brief": "不得进入再创输入"},
        "multi_signal_contract": _multi_signal_contract_payload(),
    }
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "load_config", lambda _profile_name="media_analysis": _test_config())

    def fake_call_llm(parts, schema, post_validate=None, **_kwargs):
        captured_parts.extend(parts)
        return _recreate_payload_with_both_scripts()

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)

    runner.recreate("【拆解-再创】做转场短视频", source)

    serialized = json.dumps(captured_parts, ensure_ascii=False)
    assert "已有拆解信息 compact" not in serialized
    assert "visible_text_segments" not in serialized
    assert '"huge"' not in serialized
    assert "不得进入再创输入" not in serialized
    assert len(serialized) < 50000


def test_recreate_doc_uses_generated_images_in_storyboard_table(monkeypatch: pytest.MonkeyPatch) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    events: list[object] = []
    monkeypatch.setattr(doc_writer, "tenant_access_token", lambda: "token")
    monkeypatch.setattr(
        doc_writer,
        "load_config",
        lambda: SimpleNamespace(feishu_wiki_parent_node_token="", feishu_doc_folder_token=""),
    )
    monkeypatch.setattr(
        doc_writer.requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            text="",
            raise_for_status=lambda: None,
            json=lambda: {"code": 0, "data": {"document": {"document_id": "doc123"}}},
        ),
    )
    monkeypatch.setattr(
        doc_writer,
        "generate_and_upload_storyboard_images",
        lambda *args, **kwargs: [{"shot_no": "1", "path": "/tmp/shot_1.png"}],
    )
    monkeypatch.setattr(doc_writer, "append_blocks", lambda *args, **kwargs: events.append("blocks"))

    def fake_append_storyboard_table(document_id, storyboard, token, storyboard_image_assets=None, strict_images=False):
        events.append(
            {
                "document_id": document_id,
                "assets": storyboard_image_assets,
                "strict_images": strict_images,
            }
        )

    monkeypatch.setattr(doc_writer, "append_storyboard_table", fake_append_storyboard_table)
    doc_writer.create_doc(
        "title",
        {
            "media_type": "video",
            "generate_storyboard_images": True,
            "creative_positioning": "position",
            "final_script": "script",
            "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "v", "subtitle": "", "voiceover": ""}],
            "image_post_script": [],
            "titles": ["t"],
            "hashtags": ["h"],
            "production_notes": ["n"],
            "anti_copy_notes": "a",
        },
        doc_kind="recreate",
    )

    assert events[0] == "blocks"
    assert events[1] == {
        "document_id": "doc123",
        "assets": [{"shot_no": "1", "path": "/tmp/shot_1.png"}],
        "strict_images": True,
    }


def test_recreate_doc_allows_partial_generated_storyboard_images(monkeypatch: pytest.MonkeyPatch) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    captured: dict[str, object] = {}
    monkeypatch.setattr(doc_writer, "tenant_access_token", lambda: "token")
    monkeypatch.setattr(
        doc_writer,
        "load_config",
        lambda: SimpleNamespace(feishu_wiki_parent_node_token="", feishu_doc_folder_token=""),
    )
    monkeypatch.setattr(
        doc_writer.requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            text="",
            raise_for_status=lambda: None,
            json=lambda: {"code": 0, "data": {"document": {"document_id": "doc123"}}},
        ),
    )
    monkeypatch.setattr(
        doc_writer,
        "generate_and_upload_storyboard_images",
        lambda *args, **kwargs: [{"shot_no": "1", "path": "/tmp/shot_1.png"}],
    )
    monkeypatch.setattr(doc_writer, "append_blocks", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        doc_writer,
        "append_storyboard_table",
        lambda document_id, storyboard, token, storyboard_image_assets=None, strict_images=False: captured.update(
            {"assets": storyboard_image_assets, "strict_images": strict_images}
        ),
    )

    doc_writer.create_doc(
        "title",
        {
            "media_type": "video",
            "generate_storyboard_images": True,
            "creative_positioning": "position",
            "final_script": "script",
            "video_storyboard": [
                {"shot_no": 1, "duration": "1s", "visual": "v1", "subtitle": "", "voiceover": ""},
                {"shot_no": 2, "duration": "1s", "visual": "v2", "subtitle": "", "voiceover": ""},
            ],
            "image_post_script": [],
            "titles": ["t"],
            "hashtags": ["h"],
            "production_notes": ["n"],
            "anti_copy_notes": "a",
        },
        doc_kind="recreate",
    )

    assert captured["assets"] == [{"shot_no": "1", "path": "/tmp/shot_1.png"}]
    assert captured["strict_images"] is False


def test_recreate_doc_does_not_generate_storyboard_images_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import selfmedia.deconstruct.viral_content.src.feishu_doc_writer as doc_writer

    events: list[str] = []
    monkeypatch.setattr(doc_writer, "tenant_access_token", lambda: "token")
    monkeypatch.setattr(
        doc_writer,
        "load_config",
        lambda: SimpleNamespace(feishu_wiki_parent_node_token="", feishu_doc_folder_token=""),
    )
    monkeypatch.setattr(
        doc_writer.requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            text="",
            raise_for_status=lambda: None,
            json=lambda: {"code": 0, "data": {"document": {"document_id": "doc123"}}},
        ),
    )
    monkeypatch.setattr(doc_writer, "generate_and_upload_storyboard_images", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应默认生成 image2")))
    monkeypatch.setattr(doc_writer, "append_blocks", lambda *args, **kwargs: events.append("blocks"))
    monkeypatch.setattr(
        doc_writer,
        "append_storyboard_table",
        lambda document_id, storyboard, token, storyboard_image_assets=None, strict_images=False: events.append(
            f"table assets={len(storyboard_image_assets or [])} strict={strict_images}"
        ),
    )

    doc_writer.create_doc(
        "title",
        {
            "media_type": "video",
            "creative_positioning": "position",
            "final_script": "script",
            "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "v", "subtitle": "", "voiceover": ""}],
            "image_post_script": [],
            "titles": ["t"],
            "hashtags": ["h"],
            "production_notes": ["n"],
            "anti_copy_notes": "a",
        },
        doc_kind="recreate",
    )

    assert events == ["blocks", "table assets=0 strict=False"]


def test_deconstruct_uses_direct_codex_keyframe_observation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.mp3"
    frame = tmp_path / "frame.jpg"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    frame.write_bytes(b"frame")
    media = SimpleNamespace(video_path=str(video), audio_path=None, image_paths=[], caption="caption", stats={}, media_type="video")
    config = _test_config()
    monkeypatch.setattr(runner, "load_config", lambda: config)
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "_load_content_ingest_modules", lambda: (lambda: object(), lambda url, settings: media))
    monkeypatch.setattr(media_parts, "extract_video_frames", lambda *args, **kwargs: [str(frame)])
    monkeypatch.setattr(media_parts, "extract_first_frame", lambda *args, **kwargs: "")
    monkeypatch.setattr(media_parts, "extract_audio", lambda *args, **kwargs: str(audio))
    import selfmedia.deconstruct.viral_content.src.evidence.modality_dag as modality_dag

    monkeypatch.setattr(modality_dag, "run_keyframe_observation_pipeline", lambda *args, **kwargs: [{"asset_id": "frame_001", "observations": ["画面可见事实"]}])

    def fake_call_llm(parts, schema, post_validate=None):
        serialized = json.dumps(parts, ensure_ascii=False)
        assert "frame_001" in serialized
        assert "keyobs_001" in serialized
        assert "image_data" in serialized
        payload = {
            "content_summary": "内容总结",
            "source_summary": "summary",
            "viral_mechanism": "mechanism",
            "video_storyboard": [
                {"shot_no": index + 1, "duration": duration, "visual": "画面", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_001"}
                for index, duration in enumerate(["0-1s", "1-2s", "2-3s", "3-4s", "4-5s"])
            ],
            "image_post_script": [{"page_no": 1, "image_prompt": "图", "evidence_asset_id": "frame_001"}],
            "avoid_plagiarism_notes": "notes",
            "production_checklist": ["check"],
            **_required_deconstruct_v2_fields(),
        }
        return post_validate(payload) if post_validate else payload

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)
    monkeypatch.setattr(runner, "finalize_deconstruction_contract", lambda result, stage_dir=None, user_intent="": result)
    result = runner.deconstruct("【拆解】 https://example.com")
    assert result["keyframe_observations"][0]["source"] == "codex_responses"


def test_codex_responses_adapter_uses_canonical_sse_v1_route(monkeypatch: pytest.MonkeyPatch) -> None:
    import common.llm_client as common_llm_client

    fake_post = recording_post(SseResponse(
        'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}\n',
        "data: [DONE]\n",
    ))

    monkeypatch.setattr(common_llm_client.requests, "post", fake_post)
    config = _test_config(
        model="gpt-5.6-terra",
        base_url="https://example.com/v1",
        api_key="codex-token",
        llm_api_type="openai_codex_responses",
    )
    result = generate_json([{"text": "return json"}], config)
    assert result == {"ok": True}
    assert fake_post.captured["url"] == "https://example.com/v1/responses"
    assert fake_post.captured["stream"] is True
    assert isinstance(fake_post.captured["timeout"], tuple)
    assert fake_post.captured["json"]["stream"] is True
    assert fake_post.captured["json"]["store"] is False
    assert fake_post.captured["json"]["instructions"]


def test_viral_deconstruct_config_uses_media_analysis_profile_by_default() -> None:
    from selfmedia.deconstruct.viral_content.src.config import load_config
    from common.llm_settings import load_profile_llm_settings

    expected = load_profile_llm_settings("media_analysis")
    config = load_config()
    assert config.llm_api_type == expected.api_type
    assert config.model == expected.model
    assert config.agent == expected.agent
    assert config.bin == expected.bin


def test_viral_recreate_config_uses_media_creation_profile() -> None:
    from selfmedia.deconstruct.viral_content.src.config import load_config
    from common.llm_settings import load_profile_llm_settings

    expected = load_profile_llm_settings("media_creation")
    config = load_config("media_creation")
    assert config.llm_api_type == expected.api_type
    assert config.model == expected.model
    assert config.agent == expected.agent
    assert config.bin == expected.bin


def test_visual_evidence_parts_are_sent_directly_to_json_llm(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import selfmedia.deconstruct.viral_content.src.runner as runner

    image_path = tmp_path / "source.webp"
    image_path.write_bytes(b"image")
    evidence = SimpleNamespace(
        parts=[
            {"text": "视觉证据 asset_id=image_001"},
            {"image_data": {"path": str(image_path), "data": "xxx", "mime_type": "image/webp"}},
        ],
        evidence_assets=[
            {
                "asset_id": "image_001",
                "path": str(image_path),
                "phase": "图文首图/封面重点分析",
            }
        ],
    )

    parts = runner._evidence_parts_for_llm(evidence)

    assert parts is evidence.parts
    assert any("image_data" in part for part in parts)
    assert "asset_id=image_001" in json.dumps(parts, ensure_ascii=False)
