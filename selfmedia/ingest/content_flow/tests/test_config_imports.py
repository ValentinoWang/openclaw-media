from types import SimpleNamespace

from selfmedia.ingest.content_flow.src import config


def test_selfmedia_root_points_to_common_package():
    assert (config.SELFMEDIA_ROOT / "common" / "llm_settings.py").is_file()


def test_analysis_timeout_uses_media_analysis_profile(monkeypatch):
    monkeypatch.setattr(
        config,
        "load_profile_llm_settings",
        lambda profile_name: SimpleNamespace(timeout=321),
    )

    settings = config.load_settings()

    assert settings.analysis_timeout == 321


def test_dashscope_asr_settings_are_loaded(monkeypatch):
    monkeypatch.setattr(
        config,
        "load_profile_llm_settings",
        lambda profile_name: SimpleNamespace(timeout=321),
    )
    monkeypatch.setenv("ASR_PROVIDER", "dashscope")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setenv("DASHSCOPE_ASR_MODEL", "fun-asr")
    monkeypatch.setenv("DASHSCOPE_ASR_MODE", "batch")
    monkeypatch.setenv("DASHSCOPE_TIMEOUT", "14400")
    monkeypatch.setenv("DASHSCOPE_POLL_INTERVAL", "5")
    monkeypatch.delenv("DASHSCOPE_DIARIZATION_ENABLED", raising=False)
    monkeypatch.delenv("DASHSCOPE_SPEAKER_COUNT", raising=False)

    settings = config.load_settings()

    assert settings.asr_provider == "dashscope"
    assert settings.dashscope_api_key == "dashscope-key"
    assert settings.dashscope_asr_model == "fun-asr"
    assert settings.dashscope_asr_mode == "batch"
    assert settings.dashscope_diarization_enabled is True
    assert settings.dashscope_speaker_count == 0
    assert settings.dashscope_timeout == 14400
    assert settings.dashscope_poll_interval == 5
