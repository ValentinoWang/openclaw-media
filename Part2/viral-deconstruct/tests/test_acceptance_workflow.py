from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import media_parts, runner
from src.feishu_doc_writer import DocRef


def _deconstruct_payload(asset_id: str = "frame_001") -> dict[str, object]:
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


def _recreate_payload() -> dict[str, object]:
    return {
        "doc_title": "再创作文档",
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
        "_load_part1_modules",
        lambda: (lambda: object(), lambda url, settings: events.append("part1") or media),
    )

    def fake_extract_frames(video_path: str, out_dir: str, max_frames: int = 8) -> list[str]:
        events.append("extract_frames")
        frame.parent.mkdir()
        frame.write_bytes(b"frame")
        return [str(frame)]

    def fake_extract_audio(video_path: str, out_dir: str) -> str:
        events.append("extract_audio")
        return str(audio)

    monkeypatch.setattr(media_parts, "extract_video_frames", fake_extract_frames)
    monkeypatch.setattr(media_parts, "extract_first_frame", lambda video_path, out_dir: "")
    monkeypatch.setattr(media_parts, "extract_audio", fake_extract_audio)

    def fake_call_llm(parts, schema, post_validate=None):
        events.append("llm_deconstruct")
        assert "asset_id=frame_001" in str(parts)
        payload = _deconstruct_payload("frame_001")
        return post_validate(payload) if post_validate else payload

    monkeypatch.setattr(runner, "_call_llm", fake_call_llm)

    import src.feishu_doc_writer as doc_writer
    import src.feishu_writer as bitable_writer

    class Response:
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {"code": 0, "data": {}}

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int) -> Response:
        captured_doc_bodies.append(json)
        return Response()

    monkeypatch.setattr(doc_writer.requests, "post", fake_post)

    def fake_doc(title, content, folder_token=None, doc_kind="deconstruct"):
        events.append(f"doc_{doc_kind}")
        assert doc_kind == "deconstruct"
        assert content["evidence_assets"][0]["asset_id"] == "frame_001"
        content["storyboard_image_assets"] = [{"asset_id": "frame_001", "file_token": "frame_token"}]
        doc_writer.append_storyboard_table("doc_deconstruct", content["video_storyboard"], "token", content["storyboard_image_assets"], strict_images=True)
        return DocRef("doc_deconstruct", "https://feishu/doc_deconstruct")

    def fake_write(result, source_text, bitable_url=None):
        events.append("bitable")
        assert "doc_deconstruct" in result["deconstruct_doc_url"]
        assert "video_storyboard" in result  # full result may exist here, writer owns field filtering.
        return "rec1"

    monkeypatch.setattr(doc_writer, "create_checked_doc", fake_doc)
    monkeypatch.setattr(bitable_writer, "build_attachment_plan", lambda result: events.append("attachments") or [])
    monkeypatch.setattr(bitable_writer, "write_deconstruction", fake_write)

    result = runner.run_workflow("【拆解】 https://example.com/video", write_feishu=True)
    assert result["feishu_record_id"] == "rec1"
    assert not frame.exists()
    assert any(item.get("block_type") == 27 and item.get("image", {}).get("token") == "frame_token" for body in captured_doc_bodies for item in body["descendants"])
    assert events.index("part1") < events.index("extract_frames") < events.index("extract_audio") < events.index("llm_deconstruct") < events.index("doc_deconstruct") < events.index("bitable")


def test_acceptance_deconstruct_recreate_order_and_image_blocks(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    events: list[str] = []

    deconstruct_result = dict(_deconstruct_payload("image_001"))
    deconstruct_result.update(
        {
            "source_url": "https://example.com/note",
            "source_video_path": "",
            "source_audio_path": "",
            "source_image_paths": [str(image)],
            "source_preview_path": str(image),
            "evidence_assets": [{"asset_id": "image_001", "path": str(image), "kind": "source_image"}],
        }
    )
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: events.append("llm_precheck"))
    monkeypatch.setattr(runner, "deconstruct", lambda text: events.append("deconstruct") or dict(deconstruct_result))
    monkeypatch.setattr(runner, "recreate", lambda text, source: events.append("recreate") or _recreate_payload())

    import src.feishu_doc_writer as doc_writer
    import src.feishu_writer as bitable_writer

    def fake_doc(title, content, folder_token=None, doc_kind="deconstruct"):
        events.append(f"doc_{doc_kind}")
        if doc_kind == "recreate":
            content["storyboard_image_assets"] = [{"shot_no": "1", "file_token": "image2_token"}]
            doc_writer.append_storyboard_table("doc_recreate", content["video_storyboard"], "token", content["storyboard_image_assets"], strict_images=True)
            return DocRef("doc_recreate", "https://feishu/doc_recreate")
        content["storyboard_image_assets"] = [{"asset_id": "image_001", "file_token": "source_image_token"}]
        doc_writer.append_storyboard_table("doc_deconstruct", content["video_storyboard"], "token", content["storyboard_image_assets"], strict_images=True)
        return DocRef("doc_deconstruct", "https://feishu/doc_deconstruct")

    monkeypatch.setattr(doc_writer, "create_checked_doc", fake_doc)
    monkeypatch.setattr(doc_writer.requests, "post", lambda *args, **kwargs: SimpleNamespace(status_code=200, text="", json=lambda: {"code": 0}))
    monkeypatch.setattr(bitable_writer, "build_attachment_plan", lambda result: events.append("attachments") or [])
    monkeypatch.setattr(bitable_writer, "write_deconstruction", lambda result, source_text, bitable_url=None: events.append("bitable") or "rec2")

    result = runner.run_workflow("【拆解】【再创作】 https://example.com/note 用户想法", write_feishu=True)
    assert result["feishu_record_id"] == "rec2"
    assert events.index("deconstruct") < events.index("doc_deconstruct") < events.index("doc_recreate") < events.index("bitable")


def test_acceptance_recreate_only_no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_load_part1_modules", lambda: (_ for _ in ()).throw(AssertionError("不应调用 Part1")))
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应调用 LLM")))
    import src.feishu_doc_writer as doc_writer
    import src.feishu_writer as bitable_writer

    monkeypatch.setattr(doc_writer, "create_checked_doc", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应创建文档")))
    monkeypatch.setattr(bitable_writer, "write_deconstruction", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应写表")))
    with pytest.raises(RuntimeError, match="不下载、不分析、不建文档、不写多维表格"):
        runner.run_workflow("【再创作】 https://example.com", write_feishu=True)


def test_acceptance_no_real_media_no_llm_doc_bitable(monkeypatch: pytest.MonkeyPatch) -> None:
    media = SimpleNamespace(video_path=None, audio_path=None, image_paths=[], caption="", stats={}, media_type="unknown")
    monkeypatch.setattr(runner, "ensure_llm_provider_available", lambda config: None)
    monkeypatch.setattr(runner, "_load_part1_modules", lambda: (lambda: object(), lambda url, settings: media))
    monkeypatch.setattr(runner, "_call_llm", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应让 LLM 猜内容")))
    import src.feishu_doc_writer as doc_writer
    import src.feishu_writer as bitable_writer

    monkeypatch.setattr(doc_writer, "create_checked_doc", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应创建文档")))
    monkeypatch.setattr(bitable_writer, "write_deconstruction", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应写表")))
    with pytest.raises(media_parts.NoRealMediaError):
        runner.run_workflow("【拆解】 https://example.com", write_feishu=True)
