from __future__ import annotations

import pytest

from common.bot_llm_config import (
    bot_runtime,
    load_bot_llm_config,
    openclaw_subprocess_env,
    profile_config,
    profile_provider_runtime,
    provider_runtime,
    resolve_provider_base_url,
    normalize_openclaw_thinking,
)
from common import llm_client
from common.llm_settings import API_TYPE_CODEX_RESPONSES, API_TYPE_OPENCLAW_AGENT, LLMProviderSettings, load_profile_llm_settings


OPENCLAW_OAUTH_PROFILES = {
    "system_guide",
    "knowledge_delegate",
    "transcription_postprocess",
    "media_analysis",
    "media_creation",
    "activity_cleaning",
    "daily_task_extraction",
    "deepmath_ceo_thinking_structure",
    "deepmath_people_recommendation",
    "daily_hierarchy_records_extraction",
    "social_vision",
    "content_cleaner",
}


def test_openclaw_bots_keep_runtime_shell_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_AGENTS_ROOT", "/srv/openclaw/agents")
    monkeypatch.setenv("OPENCLAW_CODEX_HOME", "/srv/openclaw/codex")
    config = load_bot_llm_config()
    assert config["defaults"] == {}
    assert config["model_tiers"] == {
        "L": {"model": "gpt-5.6-luna", "reasoning": "low"},
        "A": {"model": "gpt-5.6-terra", "reasoning": "medium"},
        "B": {"model": "gpt-5.6-terra", "reasoning": "high"},
        "C": {"model": "gpt-5.6-sol", "reasoning": "medium"},
    }
    assert set(config["bots"]) == {"main", "daily", "deepmath", "knowledge", "media", "social"}
    assert {name: config["bots"][name]["model_tier"] for name in config["bots"]} == {
        "main": "B",
        "daily": "A",
        "deepmath": "A",
        "knowledge": "B",
        "media": "C",
        "social": "B",
    }
    assert config["agent_overrides"] == {
        "openclaw-maintenance": {"model_tier": "C"},
    }
    assert config["openclaw_runtime"]["codex_app_server"]["command"] == "codex"
    assert config["providers"]["openclaw_codex"]["bin"] == "openclaw"
    for bot_name in config["bots"]:
        runtime = bot_runtime(bot_name)
        assert runtime.provider == "openclaw_codex"
        assert runtime.bin == "openclaw"
        assert runtime.agent == ("deepmath-office" if bot_name == "deepmath" else f"feishu-{bot_name}")
        assert runtime.thinking
        assert runtime.timeout > 0
        assert runtime.cwd == f"/srv/openclaw/agents/{bot_name}"
        assert runtime.codex_home == "/srv/openclaw/codex"
        assert runtime.model.startswith("codex/gpt-5.6-")

    assert bot_runtime("knowledge").thinking == "high"
    assert bot_runtime("media").model == "codex/gpt-5.6-sol"


def test_all_profiles_use_canonical_openclaw_oauth_provider() -> None:
    config = load_bot_llm_config()
    assert config["policy"]["default_provider"] == "openclaw_codex"
    assert set(config["profiles"]) == OPENCLAW_OAUTH_PROFILES
    for profile_name in OPENCLAW_OAUTH_PROFILES:
        assert profile_config(profile_name)["provider"] == "openclaw_codex"
        provider = profile_provider_runtime(profile_name)
        assert provider.api_type == "openclaw_agent"
        assert provider.base_url == "openclaw://agent"
        llm_settings = load_profile_llm_settings(profile_name)
        assert llm_settings.api_type == "openclaw_agent"
        assert llm_settings.agent.startswith("feishu-") or llm_settings.agent == "deepmath-office"
        assert llm_settings.bin == "openclaw"
        assert llm_settings.model.startswith("codex/gpt-5.6-")

    assert load_profile_llm_settings("transcription_postprocess").model == "codex/gpt-5.6-terra"
    assert load_profile_llm_settings("media_creation").model == "codex/gpt-5.6-terra"


def test_only_canonical_openclaw_provider_lives_in_config() -> None:
    config = load_bot_llm_config()
    cleaner = profile_config("content_cleaner")
    assert "main_llm" not in config["providers"]
    assert all("deepseek" not in str(value).lower() for value in config["providers"].values())
    assert set(config["providers"]) == {"openclaw_codex"}
    assert cleaner["provider"] == "openclaw_codex"
    openclaw = provider_runtime("openclaw_codex")
    assert openclaw.model == "gpt-5.6-terra"
    assert openclaw.base_url == "openclaw://agent"
    assert openclaw.api_type == "openclaw_agent"


def test_openclaw_thinking_levels_match_gateway_model_support() -> None:
    assert normalize_openclaw_thinking("xhigh") == "high"
    assert normalize_openclaw_thinking("max") == "high"
    assert normalize_openclaw_thinking("medium") == "medium"
    assert normalize_openclaw_thinking("unsupported") == ""


def test_openclaw_subprocess_env_discovers_node_bin_without_a_host_specific_path(tmp_path) -> None:
    node_bin = tmp_path / "nvm/versions/node/v99.0.0/bin"
    node_bin.mkdir(parents=True)
    (node_bin / "node").touch()
    env = openclaw_subprocess_env(
        "/tmp/codex-home",
        base_env={"HOME": "/srv/openclaw", "NVM_DIR": str(tmp_path / "nvm"), "PATH": "/usr/bin:/bin"},
    )

    parts = env["PATH"].split(":")
    assert parts[0] == str(node_bin)
    assert "/srv/openclaw/bin" in parts
    assert "/srv/openclaw/.local/bin" in parts
    assert all("/home/ubuntu" not in part for part in parts)
    assert env["HOME"] == "/srv/openclaw"
    assert env["CODEX_HOME"] == "/tmp/codex-home"


def test_common_json_client_routes_openclaw_agent_through_codex_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    config = LLMProviderSettings(
        model="codex/gpt-5.6-terra",
        base_url="openclaw://agent",
        api_key="codex_auth_file",
        api_type=API_TYPE_OPENCLAW_AGENT,
        timeout=1,
        thinking="high",
        bin="/bin/openclaw",
        agent="feishu-media",
        cwd="/home/ubuntu/openclaw-agents/media",
        codex_home="/home/ubuntu/.codex",
    )
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        captured["prompt"] = __import__("pathlib").Path(command[command.index("--message-file") + 1]).read_text(encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": '{"result":{"payloads":[{"text":"{\\"ok\\":true}"}]}}', "stderr": ""})()

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)
    monkeypatch.setattr(llm_client, "openclaw_subprocess_env", lambda codex_home: {"CODEX_HOME": codex_home})

    result = llm_client.generate_json_once([{"text": "return json"}], config)

    assert result == {"ok": True}
    command = captured["command"]
    assert command[:4] == ["/bin/openclaw", "agent", "--agent", "feishu-media"]
    assert "--model" not in command
    assert command[command.index("--session-key") + 1].startswith("agent:feishu-media:structured-json:")
    assert "return json" in captured["prompt"]


def test_openai_compatible_v1_responses_backend_forces_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            yield 'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}\n'
            yield "data: [DONE]\n"

    def fake_post(url, headers, json, timeout, stream=False):
        captured["url"] = url
        captured["body_stream"] = json["stream"]
        captured["stream"] = stream
        return Response()

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="gpt-5.6-terra",
        base_url="https://example.com/v1",
        api_key="provider-key",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    assert llm_client.generate_json_once([{"text": "return json"}], config) == {"ok": True}
    assert captured["url"] == "https://example.com/v1/responses"
    assert captured["body_stream"] is True
    assert captured["stream"] is True
    with pytest.raises(RuntimeError, match="must end with /v1"):
        llm_client.codex_responses_url("https://chatgpt.com/backend-api/codex")


def test_responses_sse_decodes_utf8_bytes_without_response_charset(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            captured["decode_unicode"] = decode_unicode
            yield 'data: {"type":"response.output_text.delta","delta":"{\\"title\\":\\"研究方案\\"}"}\n'.encode("utf-8")
            yield b"data: [DONE]\n"

    assert llm_client.collect_responses_sse_text(Response()) == '{"title":"研究方案"}'
    assert captured["decode_unicode"] is False


def test_codex_responses_stream_uses_bounded_idle_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            yield 'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}\n'
            yield "data: [DONE]\n"

    def fake_post(url, headers, json, timeout, stream=False):
        captured["timeout"] = timeout
        captured["stream"] = stream
        return Response()

    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_CONNECT_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_READ_TIMEOUT_SECONDS", "7")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="codex/gpt-5.6-terra",
        base_url="https://example.com/v1",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    assert llm_client.generate_json_once([{"text": "return json"}], config) == {"ok": True}
    assert captured["stream"] is True
    assert captured["timeout"] == (3.0, 7.0)


def test_codex_responses_stream_read_timeout_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            raise llm_client.requests.exceptions.ReadTimeout("read timed out")
            yield

    def fake_post(url, headers, json, timeout, stream=False):
        return Response()

    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_READ_TIMEOUT_SECONDS", "5")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="codex/gpt-5.6-terra",
        base_url="https://example.com/v1",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    with pytest.raises(RuntimeError, match="Codex Responses SSE watchdog timeout.*5s"):
        llm_client.generate_json_once([{"text": "return json"}], config)


def test_codex_responses_stream_wrapped_read_timeout_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            raise llm_client.requests.exceptions.ConnectionError("HTTPSConnectionPool: Read timed out.")
            yield

    def fake_post(url, headers, json, timeout, stream=False):
        return Response()

    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_READ_TIMEOUT_SECONDS", "5")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="codex/gpt-5.6-terra",
        base_url="https://example.com/v1",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    with pytest.raises(RuntimeError, match="Codex Responses SSE watchdog timeout.*5s"):
        llm_client.generate_json_once([{"text": "return json"}], config)


def test_codex_responses_stream_hard_total_timeout_interrupts_blocking_read(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            while True:
                llm_client.time.sleep(1)
                yield ""

    def fake_post(url, headers, json, timeout, stream=False):
        return Response()

    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_READ_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_TOTAL_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="codex/gpt-5.6-terra",
        base_url="https://example.com/v1",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    with pytest.raises(RuntimeError, match="hard total timeout.*0.05s"):
        llm_client.generate_json_once([{"text": "return json"}], config)


def test_codex_responses_stream_progress_event_without_output_keeps_running(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([0.0, 0.5, 0.6, 1.4, 1.5])

    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            yield 'data: {"type":"response.in_progress"}\n'
            yield 'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}\ndata: [DONE]\n'

    def fake_post(url, headers, json, timeout, stream=False):
        return Response()

    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_READ_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: next(times))
    config = LLMProviderSettings(
        model="codex/gpt-5.6-terra",
        base_url="https://example.com/v1",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    assert llm_client.generate_json_once([{"text": "return json"}], config) == {"ok": True}


def test_codex_responses_stream_heartbeat_without_progress_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([0.0, 2.0])

    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            yield ": heartbeat\n"

    def fake_post(url, headers, json, timeout, stream=False):
        return Response()

    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_READ_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: next(times))
    config = LLMProviderSettings(
        model="codex/gpt-5.6-terra",
        base_url="https://example.com/v1",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    with pytest.raises(RuntimeError, match="Codex Responses SSE watchdog timeout.*1s"):
        llm_client.generate_json_once([{"text": "return json"}], config)


def test_codex_responses_completed_without_output_is_not_treated_as_running(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            yield 'data: {"type":"response.completed","response":{"output":[]}}\n'

    def fake_post(url, headers, json, timeout, stream=False):
        return Response()
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="codex/gpt-5.6-terra",
        base_url="https://example.com/v1",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    with pytest.raises(RuntimeError, match="completed without output text"):
        llm_client.generate_json_once([{"text": "return json"}], config)
