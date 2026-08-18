from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from selfmedia.ingest.content_flow.src import transcriber


def _settings(**overrides):
    values = {
        "asr_provider": "dashscope",
        "dashscope_api_key": "test-key",
        "dashscope_asr_model": "fun-asr",
        "dashscope_asr_mode": "batch",
        "dashscope_diarization_enabled": False,
        "dashscope_speaker_count": 0,
        "dashscope_poll_interval": 1.0,
        "dashscope_timeout": 60.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_transcribe_audio_evidence_uses_dashscope_batch_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")

    monkeypatch.setattr(transcriber, "_submit_dashscope_batch", lambda file_path, settings: "task-123")
    monkeypatch.setattr(
        transcriber,
        "_poll_dashscope_batch",
        lambda task_id, settings, progress=None, progress_range=(45, 70): {
            "output": {"results": [{"transcription_url": "https://example.test/result.json"}]}
        },
    )
    monkeypatch.setattr(
        transcriber,
        "_download_dashscope_batch_result",
        lambda result_url, settings: [
            {"text": "第一句", "speaker": "", "start": 0.0, "end": 1.2},
            {"text": "第二句", "speaker": "", "start": 1.2, "end": 2.4},
        ],
    )

    result = transcriber.transcribe_audio_evidence(str(audio_path), _settings(), raise_errors=True)

    assert result["provider"] == "dashscope"
    assert result["asr_mode"] == "batch"
    assert result["task_id"] == "task-123"
    assert result["transcript"] == "第一句\n第二句"
    assert len(result["segments"]) == 2


def test_rejects_non_dashscope_provider(tmp_path: Path):
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")

    with pytest.raises(RuntimeError, match="ASR_PROVIDER 只能是 dashscope"):
        transcriber.transcribe_audio(str(audio_path), _settings(asr_provider="codex"), raise_errors=True)


def test_transcriber_has_no_codex_or_openai_audio_path():
    source = Path(transcriber.__file__).read_text(encoding="utf-8").lower()
    blocked_tokens = [
        "audio_part_from_path",
        "generate_json_from_parts",
        "input_audio",
        "codex",
        "openai",
        "whisper",
    ]

    assert [token for token in blocked_tokens if token in source] == []
