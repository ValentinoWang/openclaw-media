import json
import sys
import types

import httpx
import pytest
from pydantic import BaseModel, ConfigDict
from openclaw_media.provider_adapter import _SafeBridge

from openclaw_media import (
    ProviderAdapter,
    ProviderAdapterError,
    ProviderConfig,
    StructuredResult,
    TextResult,
    VisionImage,
    VisionResult,
)


class _Credentials:
    def __init__(self, value="secret-token"):
        self.value = value

    def get(self, ref):
        if self.value is None:
            raise RuntimeError("credential backend exploded secret-token")
        return self.value

    def put(self, ref, secret):
        self.value = secret

    def delete(self, ref):
        self.value = None


def _config():
    return ProviderConfig(
        config_id="local",
        base_url="https://provider.example/v1",
        model="confirmed-model",
        model_label="Confirmed Provider",
        credential_ref="provider:local:0123456789abcdef0123456789abcdef",
    )


class _Transport:
    instances = []

    def __init__(self, base_url, **kwargs):
        self.base_url = base_url
        self.kwargs = kwargs
        self.requests = []
        self.closed = False
        self.__class__.instances.append(self)

    def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        return httpx.Response(200, json={"ok": True})

    def close(self):
        self.closed = True


@pytest.fixture
def fake_sdk(monkeypatch):
    state = {"calls": [], "responses": ["hello"]}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def close(self):
            self.kwargs["http_client"].close()

    def completion(**kwargs):
        state["calls"].append(kwargs)
        value = state["responses"].pop(0)
        if isinstance(value, BaseException):
            raise value
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=value))]
        )

    litellm = types.SimpleNamespace(completion=completion, callbacks=["on"], telemetry=True)
    openai = types.SimpleNamespace(OpenAI=FakeOpenAI)
    monkeypatch.setitem(sys.modules, "litellm", litellm)
    monkeypatch.setitem(sys.modules, "openai", openai)
    return state, litellm


def _adapter(creds=None, **kwargs):
    return ProviderAdapter(
        _config(), creds or _Credentials(), transport_factory=_Transport, **kwargs
    )


def test_safe_bridge_forwards_a_path_relative_to_the_configured_base():
    transport = _Transport("https://provider.example/v1")
    client = httpx.Client(
        transport=_SafeBridge(transport, "secret-token", "https://provider.example/v1")
    )

    response = client.post("https://provider.example/v1/chat/completions", json={})

    assert response.status_code == 200
    assert transport.requests[0][0:2] == ("POST", "/chat/completions")
    assert transport.requests[0][2]["credential"] == "secret-token"
    client.close()


def test_text_is_confirmed_and_secret_free(fake_sdk):
    state, litellm = fake_sdk
    result = _adapter().complete_text("  hello  ")
    assert isinstance(result, TextResult)
    assert result.content == "hello"
    call = state["calls"][0]
    assert call["model"] == "confirmed-model"
    assert call["api_base"] == "https://provider.example/v1"
    assert call["max_retries"] == 0
    assert call["client"].kwargs["http_client"]._transport is not None
    assert litellm.telemetry is False
    assert litellm.callbacks == []
    assert "secret-token" not in repr(result)


def test_vision_shapes_immutable_images(fake_sdk):
    image = VisionImage(media_type="image/png", data=b"png")
    result = _adapter().complete_vision("describe", (image,))
    assert isinstance(result, VisionResult)
    content = fake_sdk[0]["calls"][0]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    with pytest.raises(Exception):
        image.data = b"changed"


def test_structured_schema_is_strict(fake_sdk):
    class Answer(BaseModel):
        answer: int

    fake_sdk[0]["responses"] = [json.dumps({"answer": 7})]
    result = _adapter().complete_structured("compute", Answer)
    assert isinstance(result, StructuredResult)
    assert result.value.answer == 7
    schema = fake_sdk[0]["calls"][0]["response_format"]["json_schema"]
    assert schema["strict"] is True


def test_structured_json_arrays_validate_as_strict_tuples(fake_sdk):
    class Answer(BaseModel):
        model_config = ConfigDict(strict=True)
        values: tuple[int, ...]

    fake_sdk[0]["responses"] = ['{"values":[1,2]}']

    result = _adapter().complete_structured("compute", Answer)

    assert result.value.values == (1, 2)


@pytest.mark.parametrize("method,args,code", [
    ("complete_text", ("",), "invalid_input"),
    ("complete_vision", ("x", ()), "invalid_input"),
    ("complete_structured", ("x", dict), "invalid_schema"),
])
def test_invalid_inputs_are_explicit(method, args, code):
    with pytest.raises(ProviderAdapterError) as error:
        getattr(_adapter(), method)(*args)
    assert error.value.code == code


def test_invalid_response_and_bounded_retry(fake_sdk):
    state, _ = fake_sdk
    state["responses"] = [RuntimeError("transient"), "ok"]
    result = _adapter(max_attempts=2).complete_text("retry")
    assert result.content == "ok"
    assert len(state["calls"]) == 2

    state["responses"] = ["not-json"]
    class Bad(BaseModel):
        x: int

    with pytest.raises(ProviderAdapterError) as error:
        _adapter(max_attempts=1).complete_structured("x", Bad)
    assert error.value.code == "invalid_structured_response"


def test_backend_failures_are_sanitized_and_retry_without_fallback(fake_sdk):
    state, _ = fake_sdk
    state["responses"] = [RuntimeError("endpoint=https://secret.example token=secret-token")] * 2
    with pytest.raises(ProviderAdapterError) as error:
        _adapter(max_attempts=2).complete_text("x")
    assert error.value.code == "provider_unavailable"
    assert "secret.example" not in str(error.value)
    assert "secret-token" not in str(error.value)
    assert len(state["calls"]) == 2
    assert all(c["model"] == "confirmed-model" for c in state["calls"])


def test_credential_backend_failure_is_sanitized(fake_sdk):
    credentials = _Credentials()
    credentials.value = None
    with pytest.raises(ProviderAdapterError) as error:
        _adapter(credentials).complete_text("x")
    assert error.value.code == "credential_unavailable"
    assert "secret-token" not in str(error.value)


def test_config_is_not_mutated_or_leaking_secret(fake_sdk):
    config = _config()
    _adapter().complete_text("x")
    assert config.model_dump() == _config().model_dump()
    assert "secret-token" not in repr(config)
