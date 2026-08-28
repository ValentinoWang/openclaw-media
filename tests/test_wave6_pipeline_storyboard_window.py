from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from selfmedia.deconstruct.viral_content.src import media_parts, prompt, runner
from selfmedia.deconstruct.viral_content.src.evidence import modality_dag
from selfmedia.deconstruct.viral_content.src.evidence.modality_dag import (
    prepare_asset_manifest,
    run_speech_audio_pipeline,
    run_visual_asset_pipeline,
)
from selfmedia.deconstruct.viral_content.src.schemas import SchemaError, validate_video_storyboard_granularity


def _storyboard(duration: str) -> dict[str, object]:
    return {"shot_no": 1, "duration": duration, "visual": "画面", "subtitle": "", "voiceover": ""}


def test_explicit_late_storyboard_window_uses_requested_intervals() -> None:
    payload = {
        "media_type": "video",
        "request_constraints": {"analysis_time_range": "60-66s"},
        "video_storyboard": [_storyboard("60-63s"), {**_storyboard("63-66s"), "shot_no": 2}],
    }

    assert validate_video_storyboard_granularity(payload, media_type="video", target_duration_sec=120) is payload


def test_default_storyboard_window_still_rejects_late_rows() -> None:
    payload = {"media_type": "video", "video_storyboard": [_storyboard("60-63s")]}

    with pytest.raises(SchemaError, match="长视频只允许拆解前 60 秒"):
        validate_video_storyboard_granularity(payload, media_type="video", target_duration_sec=120)


def test_explicit_window_rejects_storyboard_rows_outside_requested_range() -> None:
    payload = {
        "media_type": "video",
        "request_constraints": {"analysis_time_range": "60-66s"},
        "video_storyboard": [
            _storyboard("60-63s"),
            {**_storyboard("63-66s"), "shot_no": 2},
            {**_storyboard("66-69s"), "shot_no": 3},
        ],
    }

    with pytest.raises(SchemaError, match="请求窗口外"):
        validate_video_storyboard_granularity(payload, media_type="video", target_duration_sec=120)


def test_explicit_late_window_samples_no_early_video_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    observed: list[int] = []

    def fake_extract(video_path: str, out_dir: Path, timestamp_sec: int) -> str:
        observed.append(timestamp_sec)
        return str(tmp_path / f"frame_t{timestamp_sec:06d}.jpg")

    monkeypatch.setattr(media_parts, "_extract_frame_at", fake_extract)

    media_parts.extract_video_frames(str(video), str(tmp_path / "frames"), analysis_time_range="60-66s")

    assert observed == [60, 63]


def test_visual_pipeline_passes_explicit_window_to_frame_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    captured: dict[str, object] = {}

    def fake_extract(video_path: str, out_dir: str, max_frames: int = 8, *, analysis_time_range: str = "") -> list[str]:
        captured["analysis_time_range"] = analysis_time_range
        frame_paths: list[str] = []
        for timestamp in (60, 63):
            frame = tmp_path / "frames" / f"frame_t{timestamp:06d}.jpg"
            frame.parent.mkdir(exist_ok=True)
            frame.write_bytes(b"frame")
            frame_paths.append(str(frame))
        return frame_paths

    monkeypatch.setattr(media_parts, "extract_video_frames", fake_extract)
    monkeypatch.setattr(media_parts, "extract_first_frame", lambda video_path, out_dir: "")
    asset_manifest = prepare_asset_manifest(
        source_url="https://example.com/video/late-window",
        media_type="video",
        source_path=str(video),
        work_dir=str(tmp_path),
        video_path=str(video),
        image_paths=[],
        media_stats={},
    )

    facts = run_visual_asset_pipeline(asset_manifest=asset_manifest, analysis_time_range="60-66s")

    assets = facts["visual_assets"]["facts"]["assets"]
    assert captured["analysis_time_range"] == "60-66s"
    assert [item["timestamp_sec"] for item in assets] == [60, 63]
    assert all(item["analysis_time_range"] == "60-66s" for item in assets)


def test_explicit_window_audio_extraction_does_not_reuse_early_audio_or_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("窗口外逐字稿", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_extract_audio(
        video_path: str,
        out_dir: str,
        max_duration_sec: int = 60,
        *,
        start_seconds: float = 0.0,
    ) -> str:
        captured["video_path"] = video_path
        captured["max_duration_sec"] = max_duration_sec
        captured["start_seconds"] = start_seconds
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"audio")
        return str(audio)

    def fake_speech(audio_path: str | None, transcript_path: str | None = None) -> dict[str, object]:
        captured["audio_path"] = audio_path
        captured["transcript_path"] = transcript_path
        return {"status": "no_audio", "provider": "", "transcript": "", "segments": [], "reason": "test"}

    monkeypatch.setattr(media_parts, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(modality_dag, "build_speech_evidence", fake_speech)
    facts = run_speech_audio_pipeline(
        asset_manifest={"media_type": "video", "video_path": str(video), "work_dir": str(tmp_path)},
        transcript_path=str(transcript),
        analysis_time_range="60-66s",
    )

    assert captured["max_duration_sec"] == 6
    assert captured["start_seconds"] == 60.0
    assert captured["transcript_path"] is None
    assert facts["speech"]["facts"]["speech_transcript"]["analysis_time_range"] == "60-66s"


def test_prompt_and_runner_distinguish_default_and_explicit_windows() -> None:
    assert "未明确 request_constraints.analysis_time_range 时，长视频只拆解前 60 秒" in prompt.DECONSTRUCT_PROMPT
    assert "明确时间窗口时，视频分镜只覆盖该窗口" in prompt.DECONSTRUCT_PROMPT
    source = inspect.getsource(runner.run_main_deconstruction_llm)
    assert "不得套用“前 60 秒与 analysis_time_range 的交集”规则" in source
