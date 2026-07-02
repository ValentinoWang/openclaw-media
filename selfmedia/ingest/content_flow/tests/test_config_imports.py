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
