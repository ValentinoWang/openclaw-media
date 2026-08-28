from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from common import bot_llm_config


ROOT = Path(__file__).resolve().parents[1]
INGEST_ENV_EXAMPLE = ROOT / "selfmedia" / "ingest" / "content_flow" / ".env.example"
PLATFORM_CONFIGS = {
    "xiaohongshu": ROOT / "config" / "platform_mechanisms" / "xiaohongshu.json",
    "douyin": ROOT / "config" / "platform_mechanisms" / "douyin.json",
    "bilibili": ROOT / "config" / "platform_mechanisms" / "bilibili.json",
}


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_bot_loader_rejects_invalid_json_and_cross_references(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_BOTS_CONFIG", str(invalid))
    bot_llm_config.clear_bot_llm_config_cache()
    with pytest.raises(bot_llm_config.BotLLMConfigError, match="JSON 无效"):
        bot_llm_config.load_bot_llm_config()

    invalid_reference = tmp_path / "invalid-reference.json"
    payload = json.loads(bot_llm_config.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["profiles"]["media_creation"]["provider"] = "missing_provider"
    invalid_reference.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_BOTS_CONFIG", str(invalid_reference))
    bot_llm_config.clear_bot_llm_config_cache()
    with pytest.raises(bot_llm_config.BotLLMConfigError, match=r"providers\.missing_provider"):
        bot_llm_config.load_bot_llm_config()


def test_openclaw_runtime_rejects_deploy_owned_pseudo_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.loads(bot_llm_config.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["openclaw_runtime"]["heartbeat_every"] = "30m"
    invalid = tmp_path / "pseudo-runtime.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_BOTS_CONFIG", str(invalid))
    bot_llm_config.clear_bot_llm_config_cache()

    with pytest.raises(bot_llm_config.BotLLMConfigError, match="部署常量"):
        bot_llm_config.load_bot_llm_config()


def test_ingest_example_has_no_dead_cleaner_provider_or_host_path() -> None:
    values = _env_values(INGEST_ENV_EXAMPLE)

    assert values["TOP_COMMENTS_LIMIT"] == "3"
    assert not {key for key in values if key.startswith("SELFMEDIA_CLEAN_LLM_")}
    assert all("/home/ubuntu" not in value for value in values.values())
    assert values["DOUYIN_COOKIES_JSON_PATH"].startswith("./")
    assert values["XIAOHONGSHU_COOKIES_JSON_PATH"].startswith("./")


def test_platform_mechanism_configs_have_expiring_review_contracts() -> None:
    for slug, path in PLATFORM_CONFIGS.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["status"] == "active"
        assert re.fullmatch(rf"{slug}_v[1-9][0-9]*", payload["mechanism_version"])

        reviewed_at = date.fromisoformat(payload["reviewed_at"])
        review_after_days = payload["review_after_days"]
        assert isinstance(review_after_days, int) and 1 <= review_after_days <= 180
        age_days = (date.today() - reviewed_at).days
        assert 0 <= age_days <= review_after_days, f"{path.name} requires a reviewed mechanism update"


def test_product_contract_has_one_repository_owned_source() -> None:
    canonical = ROOT / "docs" / "ai-harness" / "openclaw-media-product-contract.json"
    legacy_duplicate = ROOT / "media-agent-cli" / "contracts" / canonical.name
    generator = ROOT / "media-agent-cli" / "generate_product_clients.py"

    assert json.loads(canonical.read_text(encoding="utf-8"))["contract_id"] == "openclaw_media_product_v1"
    assert not legacy_duplicate.exists()
    assert "docs/ai-harness/openclaw-media-product-contract.json" in generator.read_text(encoding="utf-8")
