from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import media_parts, runner
from src.config import ConfigError, Part2Config
from src.feishu_writer import (
    AttachmentItem,
    _record_fields,
    build_attachment_plan,
    ensure_fields,
    remap_alias_fields,
    validate_attachment_item,
    validate_bitable_record,
)
from src.llm_client import generate_json
from src.llm_client import generate_native_video_observation
from src.schemas import DeconstructResult, validate_evidence_asset_ids
from src.trigger import WorkflowMode, route_mode


def test_route_modes_are_code_defined() -> None:
    assert route_mode("普通素材 https://example.com") == WorkflowMode.ORGANIZE_ONLY
    assert route_mode("【拆解】 https://example.com") == WorkflowMode.DECONSTRUCT_ONLY
    assert route_mode("【拆解】【再创作】 https://example.com") == WorkflowMode.DECONSTRUCT_AND_RECREATE
    assert route_mode("【再创作】 https://example.com") == WorkflowMode.INVALID_RECREATE_ONLY


def test_recreate_only_stops_before_part1(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_load_part1():
        raise AssertionError("不应加载 Part1")

    monkeypatch.setattr(runner, "_load_part1_modules", fail_load_part1)
    with pytest.raises(RuntimeError, match="不下载、不分析、不建文档、不写多维表格"):
        runner.run_workflow("【再创作】 https://example.com", write_feishu=False)


def test_no_real_media_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    media = SimpleNamespace(
        video_path=None,
        audio_path=None,
        image_paths=[],
        caption="",
        stats={},
        media_type="unknown",
    )

    monkeypatch.setattr(runner, "_load_part1_modules", lambda: (lambda: object(), lambda url, settings: media))
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
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

    def fake_extract_audio(video_path: str, out_dir: str) -> str:
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
    monkeypatch.setattr(runner, "_load_part1_modules", lambda: (lambda: object(), lambda url, settings: media))
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("llm failed")))

    with pytest.raises(RuntimeError, match="llm failed"):
        runner.deconstruct("【拆解】 https://example.com")
    assert not frame.exists()


def test_bitable_forbidden_long_script_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="禁止写入多维表格"):
        validate_bitable_record({"原标题": "ok", "final_script": "long script"})

    with pytest.raises(ValueError, match="白名单"):
        validate_bitable_record({"原标题": "ok", "自定义长脚本": "long script"})


def test_attachment_classification_is_strict(tmp_path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.mp3"
    image = tmp_path / "image.jpg"
    screenshot = tmp_path / "interaction-screenshot.png"
    for path in (video, audio, image, screenshot):
        path.write_bytes(b"x")

    plan = build_attachment_plan(
        {
            "source_preview_path": str(image),
            "source_video_path": str(video),
            "source_audio_path": str(audio),
            "source_image_paths": [str(image)],
            "interaction_screenshot_path": str(screenshot),
        }
    )
    assert ("封面图/前五秒", "first_frame") in {(item.field_name, item.kind) for item in plan}
    assert ("原文件", "original_video") in {(item.field_name, item.kind) for item in plan}
    assert ("原音频", "original_audio") in {(item.field_name, item.kind) for item in plan}
    assert ("作品截图", "interaction_screenshot") in {(item.field_name, item.kind) for item in plan}

    with pytest.raises(ValueError, match="归类错误"):
        validate_attachment_item(AttachmentItem("原音频", str(video), "original_video"))


def test_bitable_core_stats_and_top_comments_are_compact() -> None:
    fields = _record_fields(
        {
            "source_url": "https://v.douyin.com/example/",
            "source_title": "title",
            "stats": {
                "like_count": 528000,
                "collect_count": 13000,
                "comment_count": 1964,
                "share_count": 30000,
                "interaction_status": "fallback_douyin_webpage_visible_text_pending_review",
                "visible_interaction_text": "52.8万 | 1964 | 1.3万 | 3.0万 | 举报",
                "interaction_screenshot_path": "/tmp/interaction-screenshot.png",
                "top_comments": [{"author": "阿寺", "text": "怎么说服她们陪你闹的", "like_count": 51968}],
            },
        },
        "source",
    )

    assert "点赞: 528000" in fields["核心数据"]
    assert "收藏: 13000" in fields["核心数据"]
    assert "转发: 30000" in fields["核心数据"]
    assert "阿寺（51968赞）" in fields["高赞评论"]


def test_doc_inaccessible_stops_before_bitable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    image = tmp_path / "image.jpg"
    image.write_bytes(b"img")
    deconstruct_result = {
        "source_summary": "summary",
        "viral_mechanism": "mechanism",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "v"}],
        "image_post_script": [{"page_no": 1, "image_prompt": "p"}],
        "republish_copy": {"titles": ["t"]},
        "avoid_plagiarism_notes": "notes",
        "production_checklist": ["check"],
        "source_url": "https://example.com",
        "source_video_path": "",
        "source_audio_path": "",
        "source_image_paths": [str(image)],
        "source_preview_path": str(image),
        "evidence_assets": [{"asset_id": "image_001", "path": str(image), "kind": "source_image"}],
    }

    monkeypatch.setattr(runner, "deconstruct", lambda text: dict(deconstruct_result))
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)

    def fail_doc(*args, **kwargs):
        raise RuntimeError("doc inaccessible")

    def fail_write(*args, **kwargs):
        raise AssertionError("不应写多维表格")

    import src.feishu_doc_writer as doc_writer
    import src.feishu_writer as bitable_writer

    monkeypatch.setattr(doc_writer, "create_checked_doc", fail_doc)
    monkeypatch.setattr(bitable_writer, "write_deconstruction", fail_write)

    with pytest.raises(RuntimeError, match="doc inaccessible"):
        runner.run_workflow("【拆解】 https://example.com", write_feishu=True)


def test_storyboard_image_cell_uses_image_block_not_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.feishu_doc_writer as doc_writer

    captured: dict[str, object] = {}

    class Response:
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {"code": 0, "data": {}}

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int) -> Response:
        captured["body"] = json
        return Response()

    monkeypatch.setattr(doc_writer.requests, "post", fake_post)
    doc_writer.append_storyboard_table(
        "doc123",
        [{"shot_no": 1, "duration": "1s", "visual": "本地路径不能写进画面图"}],
        "token",
        [{"shot_no": "1", "path": "/tmp/storyboard_01.png", "file_token": "img_token"}],
    )

    body = captured["body"]
    assert isinstance(body, dict)
    descendants = body["descendants"]
    assert any(item.get("block_type") == 27 and item.get("image", {}).get("token") == "img_token" for item in descendants)
    assert "/tmp/storyboard_01.png" not in str(body)


def test_deconstruct_storyboard_uses_uploaded_evidence_asset_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.feishu_doc_writer as doc_writer

    captured: dict[str, object] = {}

    class Response:
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {"code": 0, "data": {}}

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int) -> Response:
        captured["body"] = json
        return Response()

    monkeypatch.setattr(doc_writer.requests, "post", fake_post)
    doc_writer.append_storyboard_table(
        "doc123",
        [{"shot_no": 1, "duration": "1s", "visual": "画面", "evidence_asset_id": "frame_001"}],
        "token",
        [{"asset_id": "frame_001", "path": "/tmp/frame_001.jpg", "file_token": "uploaded_frame_token"}],
        strict_images=True,
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert "uploaded_frame_token" in str(body)
    assert "/tmp/frame_001.jpg" not in str(body)
    assert "frame_001.jpg" not in str(body)


def test_llm_invalid_evidence_asset_id_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.llm_client as llm_client

    calls = {"count": 0}

    def payload(asset_id: str) -> dict[str, object]:
        return {
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
            "republish_copy": {"titles": ["t"], "body": "b", "hashtags": ["h"]},
            "avoid_plagiarism_notes": "notes",
            "production_checklist": ["check"],
        }

    def fake_generate_once(parts, config):
        calls["count"] += 1
        return payload("bad_id" if calls["count"] == 1 else "frame_001")

    monkeypatch.setattr(llm_client, "_generate_json_once", fake_generate_once)
    config = Part2Config("model", "https://example.com/v1", "key", 1, "", "", "", runner.ROOT)
    result = generate_json(
        [{"text": "prompt"}],
        config,
        schema=DeconstructResult,
        post_validate=lambda item: validate_evidence_asset_ids(item, {"frame_001"}),
    )
    assert calls["count"] == 2
    assert result["video_storyboard"][0]["evidence_asset_id"] == "frame_001"


def test_alias_doc_fields_do_not_create_duplicate_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.feishu_writer as writer

    created: list[str] = []
    monkeypatch.setattr(
        writer,
        "list_fields",
        lambda app_token, table_id, token: [{"field_name": "拆解文档"}, {"field_name": "再创作文档"}],
    )

    def fake_post(*args, **kwargs):
        created.append(kwargs.get("json", {}).get("field_name", ""))
        raise AssertionError("不应创建重复文档链接字段")

    monkeypatch.setattr(writer.requests, "post", fake_post)
    ensure_fields("app", "table", {"拆解文档链接": 15, "再创作文档链接": 15}, "token")
    remapped = remap_alias_fields(
        {"拆解文档链接": {"link": "d"}, "再创作文档链接": {"link": "r"}},
        {"拆解文档", "再创作文档"},
    )
    assert remapped == {"拆解文档": {"link": "d"}, "再创作文档": {"link": "r"}}
    assert created == []


def test_missing_llm_key_fails_fast_before_part1(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Part2Config("model", "https://example.com/v1", "", 1, "", "", "", runner.ROOT)
    monkeypatch.setattr(runner, "load_config", lambda: config)
    monkeypatch.setattr(runner, "_load_part1_modules", lambda: (_ for _ in ()).throw(AssertionError("不应下载素材")))
    with pytest.raises(ConfigError):
        runner.run_workflow("【拆解】 https://example.com", write_feishu=True)


def test_llm_missing_fields_stops_before_doc_and_bitable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "deconstruct", lambda text: (_ for _ in ()).throw(RuntimeError("LLM 输出 JSON 校验失败")))

    import src.feishu_doc_writer as doc_writer
    import src.feishu_writer as bitable_writer

    monkeypatch.setattr(doc_writer, "create_checked_doc", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应建文档")))
    monkeypatch.setattr(bitable_writer, "write_deconstruction", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应写表")))

    with pytest.raises(RuntimeError, match="LLM 输出 JSON 校验失败"):
        runner.run_workflow("【拆解】 https://example.com", write_feishu=True)


def test_schema_requires_subtitle_voiceover_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.llm_client as llm_client

    def fake_generate_once(parts, config):
        return {
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
            "republish_copy": {"titles": ["t"], "body": "b", "hashtags": ["h"]},
            "avoid_plagiarism_notes": "notes",
            "production_checklist": ["check"],
        }

    monkeypatch.setattr(llm_client, "_generate_json_once", fake_generate_once)
    config = Part2Config("model", "https://example.com/v1", "key", 1, "", "", "", runner.ROOT)
    with pytest.raises(RuntimeError, match="LLM 输出 JSON 校验失败"):
        generate_json(
            [{"text": "prompt"}],
            config,
            schema=DeconstructResult,
            post_validate=lambda item: validate_evidence_asset_ids(item, {"frame_001"}),
            max_retries=0,
        )


def test_hybrid_native_video_observation_fallback_is_added_to_prompt(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.mp3"
    frame = tmp_path / "frame.jpg"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    frame.write_bytes(b"frame")
    media = SimpleNamespace(video_path=str(video), audio_path=None, image_paths=[], caption="caption", stats={}, media_type="video")
    config = Part2Config(
        "model",
        "https://example.com/v1",
        "key",
        1,
        "",
        "",
        "",
        runner.ROOT,
        video_understanding_provider="hybrid",
    )
    monkeypatch.setattr(runner, "load_config", lambda: config)
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "_load_part1_modules", lambda: (lambda: object(), lambda url, settings: media))
    monkeypatch.setattr(media_parts, "extract_video_frames", lambda *args, **kwargs: [str(frame)])
    monkeypatch.setattr(media_parts, "extract_first_frame", lambda *args, **kwargs: "")
    monkeypatch.setattr(media_parts, "extract_audio", lambda *args, **kwargs: str(audio))
    monkeypatch.setattr(runner, "_native_video_observation", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("qwen down")))

    def fake_call_llm(parts, schema, post_validate=None):
        assert "Qwen-Omni 原生视频观察结果" in str(parts)
        assert "已回退到本地抽帧证据包" in str(parts)
        payload = {
            "source_summary": "summary",
            "viral_mechanism": "mechanism",
            "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "画面", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_001"}],
            "image_post_script": [{"page_no": 1, "image_prompt": "图", "evidence_asset_id": "frame_001"}],
            "republish_copy": {"titles": ["t"], "body": "b", "hashtags": ["h"]},
            "avoid_plagiarism_notes": "notes",
            "production_checklist": ["check"],
        }
        return post_validate(payload) if post_validate else payload

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)
    result = runner.deconstruct("【拆解】 https://example.com")
    assert result["native_video_observation"]["fallback_reason"] == "qwen down"


def test_qwen_omni_native_video_failure_stops(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    media = SimpleNamespace(video_path=str(video), audio_path=None, image_paths=[], caption="", stats={}, media_type="video")
    config = Part2Config(
        "model",
        "https://example.com/v1",
        "key",
        1,
        "",
        "",
        "",
        runner.ROOT,
        video_understanding_provider="qwen_omni",
    )
    monkeypatch.setattr(runner, "load_config", lambda: config)
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "_load_part1_modules", lambda: (lambda: object(), lambda url, settings: media))
    monkeypatch.setattr(media_parts, "prepare_media_evidence", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("wrong patch target")))
    monkeypatch.setattr(runner, "_native_video_observation", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("qwen hard fail")))

    # Avoid ffmpeg dependency by replacing the already-imported runner symbol.
    evidence = SimpleNamespace(
        parts=[],
        evidence_paths=[],
        evidence_assets=[{"asset_id": "frame_001", "path": str(video), "kind": "keyframe"}],
        cleanup_paths=[],
        audio_path=str(video),
        preview_path=str(video),
    )
    monkeypatch.setattr(runner, "prepare_media_evidence", lambda *args, **kwargs: evidence)
    with pytest.raises(RuntimeError, match="qwen hard fail"):
        runner.deconstruct("【拆解】 https://example.com")


def test_qwen_omni_request_uses_aliyun_streaming_video_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.llm_client as llm_client

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_lines(self, decode_unicode: bool = False):
            yield 'data: {"choices":[{"delta":{"content":"{\\"timeline_summary\\":[\\"t\\"],"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"\\"visual_events\\":[\\"v\\"],\\"audio_events\\":[\\"a\\"],"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"\\"speech_summary\\":\\"s\\",\\"music_or_sound_effects\\":[\\"m\\"],"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"\\"hook_moments\\":[\\"h\\"],\\"uncertainty_notes\\":[]}"}}]}'
            yield 'data: [DONE]'

    def fake_post(url, headers, json, timeout, stream=False):
        captured["url"] = url
        captured["json"] = json
        captured["stream"] = stream
        return Response()

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = Part2Config(
        "gpt-5.5",
        "https://openai.example/v1",
        "main-key",
        1,
        "",
        "",
        "",
        runner.ROOT,
        video_understanding_provider="hybrid",
        qwen_model="qwen3.5-omni-plus",
        qwen_api_key="qwen-key",
        qwen_fps=2.0,
    )
    result = generate_native_video_observation(str(video), "caption", {"likes": 1}, config)
    body = captured["json"]
    assert captured["stream"] is True
    assert body["model"] == "qwen3.5-omni-plus"
    assert body["stream"] is True
    assert body["modalities"] == ["text"]
    video_part = body["messages"][0]["content"][1]
    assert video_part["type"] == "video_url"
    assert video_part["video_url"]["url"].startswith("data:;base64,")
    assert video_part["video_url"]["fps"] == 2.0
    assert result["timeline_summary"] == ["t"]


def test_codex_responses_sse_adapter_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.llm_client as llm_client

    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_lines(self, decode_unicode: bool = False):
            yield 'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":"}'
            yield 'data: {"type":"response.output_text.delta","delta":"true}"}'
            yield 'data: [DONE]'

    def fake_post(url, headers, json, timeout, stream=False):
        captured["url"] = url
        captured["json"] = json
        captured["stream"] = stream
        return Response()

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = Part2Config(
        "gpt-5.5",
        "https://chatgpt.com/backend-api",
        "codex-token",
        1,
        "",
        "",
        "",
        runner.ROOT,
        llm_api_type="openai_codex_responses",
    )
    result = generate_json([{"text": "return json"}], config)
    assert result == {"ok": True}
    assert captured["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert captured["stream"] is True
    assert captured["json"]["stream"] is True
    assert captured["json"]["store"] is False
    assert captured["json"]["instructions"]
