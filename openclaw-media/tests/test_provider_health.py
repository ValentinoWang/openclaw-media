from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ConfigDict

from openclaw_media import (
    ProviderAdapterError,
    ProviderConfig,
    ProviderHealth,
    StructuredResult,
    TextResult,
    VisionResult,
    check_provider_health,
)


TOKEN = "sk-health-canary-secret"
ENDPOINT = "https://private-provider.example/v1"
CHECKED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class _Credentials:
    def get(self, ref):
        return TOKEN

    def put(self, ref, secret):
        raise AssertionError("health check must not mutate credentials")

    def delete(self, ref):
        raise AssertionError("health check must not mutate credentials")


def _config():
    return ProviderConfig(
        config_id="health-local",
        base_url=ENDPOINT,
        model="confirmed-model",
        model_label="本地模型",
        credential_ref="provider:health-local:0123456789abcdef0123456789abcdef",
    )


class _Adapter:
    def __init__(self, config, credentials, *, max_attempts):
        self.config = config
        self.credentials = credentials
        self.max_attempts = max_attempts
        self.calls = []

    def complete_text(self, prompt):
        self.calls.append(("text", prompt))
        return TextResult(content="ok", model_label=self.config.model_label)

    def complete_vision(self, prompt, images):
        self.calls.append(("vision", prompt, tuple(images)))
        return VisionResult(content="ok", model_label=self.config.model_label)

    def complete_structured(self, prompt, schema):
        self.calls.append(("structured", prompt, schema))
        return StructuredResult(
            value=schema(ok=True), model_label=self.config.model_label
        )


class _Factory:
    def __init__(self, adapter_type=_Adapter):
        self.adapter_type = adapter_type
        self.instances = []

    def __call__(self, *args, **kwargs):
        instance = self.adapter_type(*args, **kwargs)
        self.instances.append(instance)
        return instance


def _serialized(receipt):
    return receipt.model_dump_json()


def test_healthy_receipt_runs_all_capabilities_through_one_adapter():
    factory = _Factory()
    config = _config()
    original = config.model_dump_json()

    receipt = check_provider_health(
        config, _Credentials(), checked_at=CHECKED_AT, adapter_factory=factory
    )

    assert receipt.health is ProviderHealth.HEALTHY
    assert receipt.provider_type == "openai_compatible"
    assert receipt.model_label == "本地模型"
    assert receipt.checked_at == CHECKED_AT
    assert [check.capability for check in receipt.checks] == [
        "text",
        "vision",
        "structured",
    ]
    assert all(check.passed and check.code == "ok" for check in receipt.checks)
    assert receipt.receipt_id.startswith("sha256:")
    assert len(factory.instances) == 1
    assert factory.instances[0].max_attempts == 1
    assert [call[0] for call in factory.instances[0].calls] == [
        "text",
        "vision",
        "structured",
    ]
    assert config.model_dump_json() == original


def test_receipt_is_deterministic_immutable_and_content_free():
    first = check_provider_health(
        _config(), _Credentials(), checked_at=CHECKED_AT, adapter_factory=_Factory()
    )
    second = check_provider_health(
        _config(), _Credentials(), checked_at=CHECKED_AT, adapter_factory=_Factory()
    )

    assert first == second
    with pytest.raises(Exception):
        first.health = ProviderHealth.UNAVAILABLE
    payload = _serialized(first)
    assert "prompt" not in payload
    assert "content" not in payload


@pytest.mark.parametrize(
    ("capability", "code"),
    [
        ("text", "credential_unavailable"),
        ("vision", "provider_unavailable"),
        ("structured", "invalid_structured_response"),
    ],
)
def test_sanitized_provider_failures_are_recorded(capability, code):
    class FailingAdapter(_Adapter):
        def _maybe_fail(self, name):
            if name == capability:
                raise ProviderAdapterError(code)

        def complete_text(self, prompt):
            self._maybe_fail("text")
            return super().complete_text(prompt)

        def complete_vision(self, prompt, images):
            self._maybe_fail("vision")
            return super().complete_vision(prompt, images)

        def complete_structured(self, prompt, schema):
            self._maybe_fail("structured")
            return super().complete_structured(prompt, schema)

    receipt = check_provider_health(
        _config(),
        _Credentials(),
        checked_at=CHECKED_AT,
        adapter_factory=_Factory(FailingAdapter),
    )

    failed = next(check for check in receipt.checks if check.capability == capability)
    assert receipt.health is ProviderHealth.UNAVAILABLE
    assert failed.passed is False
    assert failed.code == code
    assert len(receipt.checks) == 3


def test_unknown_backend_failure_is_normalized_and_does_not_stop_matrix():
    class BrokenAdapter(_Adapter):
        def complete_text(self, prompt):
            raise RuntimeError(f"socket exploded {TOKEN} {ENDPOINT}")

    factory = _Factory(BrokenAdapter)
    receipt = check_provider_health(
        _config(), _Credentials(), checked_at=CHECKED_AT, adapter_factory=factory
    )

    assert receipt.checks[0].code == "provider_unavailable"
    assert [call[0] for call in factory.instances[0].calls] == [
        "vision",
        "structured",
    ]
    assert TOKEN not in repr(receipt)
    assert ENDPOINT not in repr(receipt)


def test_adapter_construction_failure_produces_complete_safe_receipt():
    def broken_factory(*args, **kwargs):
        raise RuntimeError(f"wrong key {TOKEN} at {ENDPOINT}")

    receipt = check_provider_health(
        _config(), _Credentials(), checked_at=CHECKED_AT, adapter_factory=broken_factory
    )

    assert receipt.health is ProviderHealth.UNAVAILABLE
    assert [check.code for check in receipt.checks] == [
        "provider_unavailable",
        "provider_unavailable",
        "provider_unavailable",
    ]
    assert TOKEN not in _serialized(receipt)
    assert ENDPOINT not in _serialized(receipt)


def test_receipt_and_log_capture_do_not_leak_token_endpoint_or_exception(caplog):
    class NoisyAdapter(_Adapter):
        def complete_vision(self, prompt, images):
            raise ValueError(f"{TOKEN} {ENDPOINT} backend traceback")

    receipt = check_provider_health(
        _config(),
        _Credentials(),
        checked_at=CHECKED_AT,
        adapter_factory=_Factory(NoisyAdapter),
    )
    combined = _serialized(receipt) + repr(receipt) + caplog.text

    assert TOKEN not in combined
    assert ENDPOINT not in combined
    assert "traceback" not in combined


def test_default_factory_is_resolved_at_call_time(monkeypatch):
    factory = _Factory()
    monkeypatch.setattr("openclaw_media.provider_health.ProviderAdapter", factory)

    receipt = check_provider_health(_config(), _Credentials(), checked_at=CHECKED_AT)

    assert receipt.health is ProviderHealth.HEALTHY
    assert len(factory.instances) == 1


@pytest.mark.parametrize(
    "checked_at",
    [datetime(2026, 8, 1, 12, 0), "2026-08-01T12:00:00Z", None],
)
def test_explicit_invalid_check_time_is_rejected(checked_at):
    kwargs = {} if checked_at is None else {"checked_at": checked_at}
    if checked_at is None:
        receipt = check_provider_health(
            _config(), _Credentials(), adapter_factory=_Factory(), **kwargs
        )
        assert receipt.checked_at.tzinfo is not None
    else:
        with pytest.raises(ValueError, match="invalid_checked_at"):
            check_provider_health(
                _config(), _Credentials(), adapter_factory=_Factory(), **kwargs
            )


def test_health_schema_forbids_coercion_from_provider_payload():
    class LooseResult(BaseModel):
        model_config = ConfigDict(extra="allow")
        ok: str

    class WrongStructuredAdapter(_Adapter):
        def complete_structured(self, prompt, schema):
            return StructuredResult(
                value=LooseResult(ok="true"), model_label=self.config.model_label
            )

    receipt = check_provider_health(
        _config(),
        _Credentials(),
        checked_at=CHECKED_AT,
        adapter_factory=_Factory(WrongStructuredAdapter),
    )

    assert receipt.health is ProviderHealth.UNAVAILABLE
    assert receipt.checks[2].code == "invalid_response"
