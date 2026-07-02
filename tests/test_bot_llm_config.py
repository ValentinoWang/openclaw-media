from __future__ import annotations

import pytest

from common.bot_llm_config import (
    OPENCLAW_NODE_BIN_DIR,
    bot_runtime,
    load_bot_llm_config,
    openclaw_subprocess_env,
    profile_config,
    profile_provider_runtime,
    provider_runtime,
    normalize_openclaw_thinking,
)
from common import llm_client
from common.llm_settings import API_TYPE_CODEX_RESPONSES, API_TYPE_OPENCLAW_AGENT, LLMProviderSettings, load_profile_llm_settings


DIRECT_RESPONSE_PROFILES = {
    "transcription_postprocess",
    "media_analysis",
    "media_creation",
    "activity_cleaning",
    "daily_task_extraction",
    "daily_hierarchy_records_extraction",
    "content_cleaner",
}


def test_openclaw_bots_keep_runtime_shell_configuration() -> None:
    config = load_bot_llm_config()
    assert config["defaults"] == {}
    assert set(config["bots"]) == {"main", "daily", "knowledge", "media", "social"}
    for bot_name in config["bots"]:
        runtime = bot_runtime(bot_name)
        assert runtime.provider == "openclaw_codex"
        assert runtime.bin.endswith("/openclaw")
        assert runtime.agent == f"feishu-{bot_name}"
        assert runtime.thinking
        assert runtime.timeout > 0
        assert runtime.cwd.endswith(f"/{bot_name}")
        assert runtime.codex_home == "/home/ubuntu/.codex"


def test_media_and_postprocess_profiles_use_direct_codex_responses() -> None:
    config = load_bot_llm_config()
    assert config["policy"]["default_provider"] == "codex_responses"
    for profile_name in DIRECT_RESPONSE_PROFILES:
        assert profile_config(profile_name)["provider"] == "codex_responses"
        provider = profile_provider_runtime(profile_name)
        assert provider.api_type == "openai_codex_responses"
        assert provider.base_url.rstrip("/").endswith("/codex")
        llm_settings = load_profile_llm_settings(profile_name)
        assert llm_settings.api_type == "openai_codex_responses"
        assert not llm_settings.agent
        assert not llm_settings.bin


def test_only_direct_provider_and_declared_bot_shell_providers_live_in_config() -> None:
    config = load_bot_llm_config()
    cleaner = profile_config("content_cleaner")
    assert "main_llm" not in config["providers"]
    assert all("deepseek" not in str(value).lower() for value in config["providers"].values())
    assert cleaner["provider"] == "codex_responses"
    codex = provider_runtime("codex_responses")
    assert codex.model
    assert codex.api_type == "openai_codex_responses"
    assert codex.api_key == "codex_auth_file"
    openclaw = provider_runtime("openclaw_codex")
    assert openclaw.base_url == "openclaw://agent"
    assert openclaw.api_type == "openclaw_agent"


def test_openclaw_thinking_levels_match_gateway_model_support() -> None:
    assert normalize_openclaw_thinking("xhigh") == "high"
    assert normalize_openclaw_thinking("max") == "high"
    assert normalize_openclaw_thinking("medium") == "medium"
    assert normalize_openclaw_thinking("unsupported") == ""


def test_openclaw_subprocess_env_prepends_node_bin_to_existing_path() -> None:
    env = openclaw_subprocess_env(
        "/tmp/codex-home",
        base_env={"PATH": f"/usr/bin:{OPENCLAW_NODE_BIN_DIR}:/bin"},
    )

    parts = env["PATH"].split(":")
    assert parts[0] == OPENCLAW_NODE_BIN_DIR
    assert parts.count(OPENCLAW_NODE_BIN_DIR) == 1
    assert env["HOME"] == "/home/ubuntu"
    assert env["CODEX_HOME"] == "/tmp/codex-home"


def test_common_json_client_rejects_openclaw_agent_api_type() -> None:
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
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
    with pytest.raises(RuntimeError, match="direct LLM client 不支持"):
        llm_client.generate_json_once([{"text": "return json"}], config)


def test_codex_responses_defaults_to_non_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"output": [{"content": [{"text": "{\"ok\":true}"}]}]}

    def fake_post(url, headers, json, timeout, stream=False):
        captured["body_stream"] = json["stream"]
        captured["timeout"] = timeout
        captured["stream"] = stream
        return Response()

    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_CONNECT_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_TOTAL_TIMEOUT_SECONDS", "11")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://example.com/backend-api",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    assert llm_client.generate_json_once([{"text": "return json"}], config) == {"ok": True}
    assert captured["body_stream"] is False
    assert captured["stream"] is False
    assert captured["timeout"] == (3.0, 11.0)


def test_chatgpt_codex_responses_backend_forces_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            yield 'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}\n'
            yield "data: [DONE]\n"

    def fake_post(url, headers, json, timeout, stream=False):
        captured["body_stream"] = json["stream"]
        captured["stream"] = stream
        return Response()

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    assert llm_client.generate_json_once([{"text": "return json"}], config) == {"ok": True}
    assert captured["body_stream"] is True
    assert captured["stream"] is True


def test_chatgpt_codex_responses_backend_stream_requirement_ignores_false_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
            yield 'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}\n'
            yield "data: [DONE]\n"

    def fake_post(url, headers, json, timeout, stream=False):
        captured["body_stream"] = json["stream"]
        captured["stream"] = stream
        return Response()

    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_STREAM", "0")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    assert llm_client.generate_json_once([{"text": "return json"}], config) == {"ok": True}
    assert captured["body_stream"] is True
    assert captured["stream"] is True


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
    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_STREAM", "1")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
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
    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_STREAM", "1")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
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
    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_STREAM", "1")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
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
    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_STREAM", "1")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
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
    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_STREAM", "1")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: next(times))
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
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
    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_STREAM", "1")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: next(times))
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
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

    monkeypatch.setenv("OPENCLAW_CODEX_RESPONSES_STREAM", "1")
    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    config = LLMProviderSettings(
        model="openai-codex/gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="codex-token",
        api_type=API_TYPE_CODEX_RESPONSES,
        timeout=1800,
        thinking="high",
    )

    with pytest.raises(RuntimeError, match="completed without output text"):
        llm_client.generate_json_once([{"text": "return json"}], config)
