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
    write_deconstruction,
)
from src.llm_client import generate_json
from src.llm_client import generate_native_video_observation
from src.schemas import DeconstructResult, validate_evidence_asset_ids, validate_schema
from src.trigger import WorkflowMode, route_mode


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
    assert route_mode("【拆解】【再创作】 https://example.com") == WorkflowMode.DECONSTRUCT_AND_RECREATE
    assert route_mode("【再创作】 https://example.com") == WorkflowMode.INVALID_RECREATE_ONLY


def test_doc_titles_use_time_theme_and_source_id() -> None:
    source = {
        "source_url": "https://v.douyin.com/fKD3JbS5aXk/",
        "source_caption": "我的发 #田径",
        "content_summary": "田径金牌转场",
        "source_summary": "丑效果转场到田径金牌",
        "stats": {"video_id": "video123"},
    }
    recreate = {"doc_title": "田径服露腹肌金牌转场", "creative_positioning": "position"}

    assert runner.deconstruct_doc_title(source, "202605041530") == "202605041530｜田径金牌转场｜video123"
    assert (
        runner.recreate_doc_title(
            "【再创作】从丑效果转场到跑10秒80，会怎么样？",
            recreate,
            source,
            "202605041530",
        )
        == "202605041530｜田径金牌转场｜由video123二创"
    )
    assert (
        runner.recreate_doc_title(
            "【再创作】计划 2026-05-08 19:30 发",
            recreate,
            source,
            "202605041530",
        )
        == "202605081930｜田径金牌转场｜由video123二创"
    )


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
    assert ("封面图/前五秒", "first_frame") in {(item.field_name, item.kind) for item in plan}
    assert ("原文件", "original_video") in {(item.field_name, item.kind) for item in plan}
    assert ("原音频", "original_audio") in {(item.field_name, item.kind) for item in plan}
    assert ("作品截图", "interaction_screenshot") in {(item.field_name, item.kind) for item in plan}
    assert ("关键帧", "keyframe") not in {(item.field_name, item.kind) for item in plan}

    with pytest.raises(ValueError, match="归类错误"):
        validate_attachment_item(AttachmentItem("原音频", str(video), "original_video"))


def test_bitable_attachment_fields_skip_keyframes_and_upload_failures_degrade(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import src.feishu_writer as writer

    cover = tmp_path / "cover.jpg"
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.mp3"
    screenshot = tmp_path / "interaction-screenshot.png"
    keyframe = tmp_path / "frame_001.jpg"
    for path in (cover, video, audio, screenshot, keyframe):
        path.write_bytes(b"x")

    existing = {
        "原标题",
        "参考链接",
        "平台",
        "爆点拆解",
        "爆点迁移",
        "核心价值",
        "吸睛元素",
        "痛点/爽点",
        "目标受众",
        "核心数据",
        "高赞评论",
        "关联ID",
        "创建时间",
    }
    created: list[tuple[str, int]] = []
    record_fields: dict[str, object] = {}

    monkeypatch.setattr(writer, "tenant_access_token", lambda: "tenant-token")
    monkeypatch.setattr(writer, "parse_feishu_bitable_url", lambda url: ("app", "table"))
    monkeypatch.setattr(writer, "list_fields", lambda app_token, table_id, token: [{"field_name": name} for name in existing])

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int):
        if url.endswith("/fields"):
            name = str(json["field_name"])
            existing.add(name)
            created.append((name, int(json["type"])))
            return SimpleNamespace(status_code=200, text="", raise_for_status=lambda: None, json=lambda: {"code": 0, "data": {}})
        if url.endswith("/records"):
            record_fields.update(json["fields"])
            return SimpleNamespace(
                status_code=200,
                text="",
                raise_for_status=lambda: None,
                json=lambda: {"code": 0, "data": {"record": {"record_id": "rec1"}}},
            )
        raise AssertionError(url)

    def fake_upload(app_token: str, table_id: str, field_name: str, file_path: str, token: str) -> str:
        if field_name == "原文件":
            return ""
        return f"{field_name}_token"

    monkeypatch.setattr(writer.requests, "post", fake_post)
    monkeypatch.setattr(writer, "upload_attachment", fake_upload)

    record_id = write_deconstruction(
        {
            "source_url": "https://example.com/video",
            "source_title": "title",
            "source_preview_path": str(cover),
            "source_video_path": str(video),
            "source_audio_path": str(audio),
            "interaction_screenshot_path": str(screenshot),
            "evidence_assets": [{"asset_id": "frame_001", "path": str(keyframe), "kind": "keyframe"}],
        },
        "【拆解】 https://example.com/video",
        "https://example.feishu.cn/wiki/wikiToken?table=tbl",
    )

    assert record_id == "rec1"
    assert ("关键帧", 17) not in created
    assert ("附件写入说明", 1) not in created
    assert ("总结", 1) in created
    assert record_fields["封面图/前五秒"] == [{"file_token": "封面图/前五秒_token"}]
    assert record_fields["原音频"] == [{"file_token": "原音频_token"}]
    assert record_fields["作品截图"] == [{"file_token": "作品截图_token"}]
    assert "关键帧" not in record_fields
    assert "原文件" not in record_fields
    assert "附件写入说明" not in record_fields


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


def test_bitable_hot_fields_and_hash_tags_are_populated() -> None:
    fields = _record_fields(
        {
            "source_url": "https://v.douyin.com/example/",
            "source_title": "title",
            "content_summary": "校园青春回忆杀",
            "source_caption": "某天你想起我#清纯男高 #毕业季",
            "republish_copy": {"hashtags": ["#校园感", "青春感"]},
            "stats": {},
        },
        "source",
    )

    assert fields["热榜字段"] == "未抓取热榜字段"
    assert fields["总结"] == "校园青春回忆杀"
    assert fields["赛道/标签"] == "#清纯男高、#毕业季、#校园感、#青春感"

    ranked = _record_fields(
        {
            "source_url": "https://v.douyin.com/example/",
            "stats": {"hot_rank": 3, "hot_score": 9988, "hot_list_name": "抖音热点榜"},
        },
        "source",
    )
    assert "热榜排名: 3" in ranked["热榜字段"]
    assert "热度值: 9988" in ranked["热榜字段"]
    assert "榜单: 抖音热点榜" in ranked["热榜字段"]


def test_bitable_target_audience_multiselect_and_storyboard_link_are_populated() -> None:
    fields = _record_fields(
        {
            "source_url": "https://v.douyin.com/example/",
            "deconstruct_doc_url": "https://feishu/docx/doc123",
            "target_audience": ["校园青春受众", "毕业季拍摄人群", "校园青春受众"],
            "pain_or_pleasure_points": ["青春回忆爽点", "朋友起哄评论点"],
        },
        "source",
    )

    assert fields["目标受众"] == ["校园青春受众", "毕业季拍摄人群"]
    assert fields["分镜脚本"] == {"text": "分镜脚本", "link": "https://feishu/docx/doc123"}
    assert fields["痛点/爽点"] == "青春回忆爽点\n朋友起哄评论点"


def test_list_like_text_is_written_without_python_brackets() -> None:
    import src.feishu_doc_writer as doc_writer

    list_text = "['可以借的结构：晴天校园操场开场', '不能抄的内容：不要照搬原文案']"
    fields = _record_fields({"source_url": "https://example.com", "viral_mechanism": list_text}, "source")
    assert fields["爆点拆解"] == "可以借的结构：晴天校园操场开场\n不能抄的内容：不要照搬原文案"

    blocks = doc_writer._value_blocks(list_text)
    rendered = str(blocks)
    assert "1. 可以借的结构：晴天校园操场开场" in rendered
    assert "2. 不能抄的内容：不要照搬原文案" in rendered
    assert "['" not in rendered
    assert "']" not in rendered


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
        "republish_copy": {"titles": ["t"], "body": "b", "hashtags": ["h"]},
        "avoid_plagiarism_notes": "['建议一', '建议二']",
        "production_checklist": ["check"],
        "target_audience": "校园青春受众、毕业季拍摄人群",
        "pain_or_pleasure_points": "['心动爽点', '青春遗憾痛点']",
        "track_tags": ["#校园感", "毕业季"],
    }
    result = validate_schema(payload, DeconstructResult)
    assert result["content_summary"] == "内容总结"
    assert result["viral_mechanism"] == "机制一\n机制二"
    assert result["avoid_plagiarism_notes"] == "建议一\n建议二"
    assert result["target_audience"] == ["校园青春受众", "毕业季拍摄人群"]
    assert result["pain_or_pleasure_points"] == ["心动爽点", "青春遗憾痛点"]
    assert result["track_tags"] == ["#校园感", "毕业季"]


def test_doc_inaccessible_stops_before_bitable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    image = tmp_path / "image.jpg"
    image.write_bytes(b"img")
    deconstruct_result = {
        "content_summary": "内容总结",
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
    import src.feishu_doc_writer as doc_writer

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

    assert texts[:5] == ["画面图", "画面描述", "字幕", "口播", "运镜"]
    assert "画面内容" in texts
    assert "上屏文字" in texts


def test_deconstruct_storyboard_uses_uploaded_evidence_asset_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.feishu_doc_writer as doc_writer

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


def test_video_deconstruct_doc_skips_image_post_table(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.feishu_doc_writer as doc_writer

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
    monkeypatch.setattr(doc_writer, "append_blocks", lambda *args, **kwargs: events.append("blocks"))
    monkeypatch.setattr(doc_writer, "append_storyboard_table", lambda *args, **kwargs: events.append("storyboard_table"))
    monkeypatch.setattr(doc_writer, "append_image_post_table", lambda *args, **kwargs: events.append("image_post_table"))

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

    assert events == ["blocks", "storyboard_table"]


def test_llm_invalid_evidence_asset_id_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.llm_client as llm_client

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
        "republish_copy": {"titles": ["t"], "body": "b", "hashtags": ["h"]},
        "avoid_plagiarism_notes": "notes",
        "production_checklist": ["check"],
    }
    result = validate_schema(payload, DeconstructResult)
    assert result["video_storyboard"][0]["subtitle"] == ""
    assert result["video_storyboard"][0]["voiceover"] == ""


def _recreate_payload_with_both_scripts() -> dict[str, object]:
    return {
        "creative_positioning": "new angle",
        "final_script": "script",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "视频画面", "subtitle": "", "voiceover": ""}],
        "image_post_script": [{"page_no": 1, "image_prompt": "图文画面"}],
        "titles": ["title"],
        "hashtags": ["tag"],
        "production_notes": ["note"],
        "anti_copy_notes": "anti",
    }


def test_recreate_video_prunes_image_post_script(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_parts: list[dict[str, object]] = []
    source = {
        "media_type": "video",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "原画面", "subtitle": "", "voiceover": ""}],
    }
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "load_config", lambda: Part2Config("model", "https://example.com/v1", "key", 1, "", "", "", runner.ROOT))

    def fake_call_llm(parts, schema, post_validate=None):
        captured_parts.extend(parts)
        return _recreate_payload_with_both_scripts()

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)
    result = runner.recreate("【再创作】做转场短视频", source)
    assert "本次再创作交付类型：video" in str(captured_parts)
    assert result["media_type"] == "video"
    assert result["video_storyboard"]
    assert result["image_post_script"] == []
    assert result["generate_storyboard_images"] is False


def test_recreate_generates_storyboard_images_only_when_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    source = {
        "media_type": "video",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "原画面", "subtitle": "", "voiceover": ""}],
    }
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "load_config", lambda: Part2Config("model", "https://example.com/v1", "key", 1, "", "", "", runner.ROOT))
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: _recreate_payload_with_both_scripts())

    result = runner.recreate("【再创作】做转场短视频，生成分镜图", source)
    assert result["generate_storyboard_images"] is True


def test_recreate_image_post_prunes_video_script(monkeypatch: pytest.MonkeyPatch) -> None:
    source = {
        "media_type": "video",
        "video_storyboard": [{"shot_no": 1, "duration": "1s", "visual": "原画面", "subtitle": "", "voiceover": ""}],
    }
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "load_config", lambda: Part2Config("model", "https://example.com/v1", "key", 1, "", "", "", runner.ROOT))
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: _recreate_payload_with_both_scripts())

    result = runner.recreate("【再创作】改成小红书图文", source)
    assert result["media_type"] == "image_post"
    assert result["video_storyboard"] == []
    assert result["image_post_script"]


def test_recreate_doc_uses_generated_images_in_storyboard_table(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.feishu_doc_writer as doc_writer

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
    import src.feishu_doc_writer as doc_writer

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
    import src.feishu_doc_writer as doc_writer

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
            "content_summary": "内容总结",
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
