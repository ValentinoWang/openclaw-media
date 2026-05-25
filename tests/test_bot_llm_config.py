from __future__ import annotations

from common.bot_llm_config import bot_runtime, display_openclaw_model, load_bot_llm_config, profile_runtime


def test_all_feishu_bots_have_openclaw_runtime() -> None:
    config = load_bot_llm_config()
    assert set(config["bots"]) == {"main", "daily", "knowledge", "media", "social"}
    for bot_name in config["bots"]:
        runtime = bot_runtime(bot_name)
        assert runtime.bin.endswith("/openclaw")
        assert runtime.agent == f"feishu-{bot_name}"
        assert runtime.model.startswith("openai-codex/")
        assert runtime.thinking
        assert runtime.timeout > 0
        assert runtime.cwd.endswith(f"/{bot_name}")
        assert runtime.codex_home.endswith("/codex-home")


def test_profiles_are_the_single_source_for_openclaw_use_cases() -> None:
    assert display_openclaw_model(profile_runtime("system_guide").model) == "gpt-5.3-codex-spark"
    assert profile_runtime("knowledge_delegate").agent == "feishu-knowledge"
    assert profile_runtime("knowledge_delegate").thinking == "high"
    assert profile_runtime("knowledge_research").thinking == "xhigh"
    assert profile_runtime("media_analysis").agent == "feishu-media"
    assert profile_runtime("media_creation").agent == "feishu-media"
    assert profile_runtime("social_vision").agent == "feishu-social"
