from __future__ import annotations

from common.bot_llm_config import load_bot_llm_config, profile_provider_runtime


MEDIA_PROFILE_TIER_ORDER = (
    ("media_creation", "B"),
    ("media_analysis", "B"),
)


def test_media_profiles_override_the_media_bot_default_with_tier_b() -> None:
    config = load_bot_llm_config()

    assert config["bots"]["media"]["model_tier"] == "C"
    assert tuple(
        (profile_name, config["profiles"][profile_name]["model_tier"])
        for profile_name, _ in MEDIA_PROFILE_TIER_ORDER
    ) == MEDIA_PROFILE_TIER_ORDER

    for profile_name, tier_name in MEDIA_PROFILE_TIER_ORDER:
        profile = config["profiles"][profile_name]
        tier = config["model_tiers"][tier_name]
        runtime = profile_provider_runtime(profile_name)

        assert "model" not in profile
        assert "reasoning" not in profile
        assert (runtime.model, runtime.thinking) == (tier["model"], tier["reasoning"])
