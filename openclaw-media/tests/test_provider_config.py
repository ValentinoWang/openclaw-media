from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from openclaw_media.credentials import CredentialStoreError, KeyringCredentialStore
from openclaw_media.provider_config import (
    ProviderConfig,
    ProviderConfigError,
    ProviderConfigRepository,
    ProviderConfigService,
)


class FakeCredentials:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def put(self, credential_ref: str, secret: str) -> None:
        self.values[credential_ref] = secret

    def get(self, credential_ref: str) -> str:
        try:
            return self.values[credential_ref]
        except KeyError as exc:
            raise CredentialStoreError("credential_not_found") from exc

    def delete(self, credential_ref: str) -> None:
        if credential_ref not in self.values:
            raise CredentialStoreError("credential_not_found")
        del self.values[credential_ref]


def service(tmp_path: Path) -> tuple[ProviderConfigService, FakeCredentials]:
    credentials = FakeCredentials()
    return (
        ProviderConfigService(ProviderConfigRepository(tmp_path), credentials),
        credentials,
    )


def configure(instance: ProviderConfigService, api_key: str = "sk-secret") -> ProviderConfig:
    return instance.configure(
        config_id="primary",
        base_url="https://models.example.test/v1/",
        model="vision-model",
        model_label="主视觉模型",
        api_key=api_key,
    )


def test_create_read_list_and_public_projection_are_secret_free(tmp_path: Path) -> None:
    instance, credentials = service(tmp_path)
    config = configure(instance)

    assert config.base_url == "https://models.example.test/v1"
    assert credentials.get(config.credential_ref) == "sk-secret"
    assert instance.repository.load("primary") == config
    assert instance.repository.list() == (config,)
    persisted = (tmp_path / "primary.json").read_text()
    projection = instance.projection("primary").model_dump(mode="json")
    assert "sk-secret" not in persisted
    assert "api_key" not in persisted
    assert "credential_ref" not in projection
    assert "base_url" not in projection
    assert "model" not in projection
    assert projection == {
        "provider_type": "openai_compatible",
        "model_label": "主视觉模型",
        "health": "unavailable",
        "last_health_check_at": None,
    }


def test_rotation_commits_new_reference_then_removes_old_secret(tmp_path: Path) -> None:
    instance, credentials = service(tmp_path)
    original = configure(instance, "first-secret")
    rotated = configure(instance, "second-secret")

    assert rotated.credential_ref != original.credential_ref
    assert original.credential_ref not in credentials.values
    assert credentials.get(rotated.credential_ref) == "second-secret"
    assert instance.repository.load("primary") == rotated
    assert "first-secret" not in (tmp_path / "primary.json").read_text()
    assert "second-secret" not in (tmp_path / "primary.json").read_text()


def test_delete_removes_credential_and_config(tmp_path: Path) -> None:
    instance, credentials = service(tmp_path)
    config = configure(instance)
    instance.delete("primary")

    assert config.credential_ref not in credentials.values
    assert not (tmp_path / "primary.json").exists()
    with pytest.raises(ProviderConfigError, match="config_not_found"):
        instance.repository.load("primary")


@pytest.mark.parametrize(
    ("overrides", "forbidden"),
    [
        ({"provider_type": "anthropic"}, "anthropic"),
        ({"base_url": "https://user:pass@example.test/v1"}, "user:pass"),
        ({"base_url": "file:///tmp/model"}, "/tmp/model"),
        ({"config_id": "../escape"}, "../escape"),
    ],
)
def test_invalid_configs_have_explicit_secret_free_outcomes(
    tmp_path: Path, overrides: dict[str, str], forbidden: str
) -> None:
    instance, credentials = service(tmp_path)
    values = {
        "config_id": "primary",
        "base_url": "https://models.example.test/v1",
        "model": "model",
        "model_label": "Model",
        "api_key": "never-print-this-key",
        **overrides,
    }
    with pytest.raises(ProviderConfigError) as captured:
        instance.configure(**values)

    assert captured.value.code == "invalid_config"
    assert str(captured.value) == "invalid_config"
    assert "never-print-this-key" not in repr(captured.value)
    assert forbidden not in repr(captured.value)
    assert credentials.values == {}


def test_missing_and_corrupt_config_have_explicit_outcomes(tmp_path: Path) -> None:
    repository = ProviderConfigRepository(tmp_path)
    with pytest.raises(ProviderConfigError, match="config_not_found"):
        repository.load("missing")

    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "broken.json").write_text('{"api_key":"leaked-value"')
    with pytest.raises(ProviderConfigError) as captured:
        repository.load("broken")
    assert captured.value.code == "config_corrupt"
    assert "leaked-value" not in str(captured.value)
    assert "leaked-value" not in repr(captured.value)


def test_config_is_frozen_and_rejects_secret_fields() -> None:
    config = ProviderConfig(
        config_id="primary",
        base_url="https://models.example.test/v1",
        model="model",
        model_label="Model",
        credential_ref="provider:primary:0123456789abcdef0123456789abcdef",
    )
    with pytest.raises(ValidationError):
        config.model = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError) as captured:
        ProviderConfig.model_validate(
            {**config.model_dump(), "api_key": "should-not-appear"}
        )
    assert "should-not-appear" not in str(captured.value)


class ExplodingKeyring:
    def set_password(self, service: str, account: str, secret: str) -> None:
        raise RuntimeError(f"backend exposed {secret}")

    def get_password(self, service: str, account: str) -> str:
        raise RuntimeError("backend read failed")

    def delete_password(self, service: str, account: str) -> None:
        raise RuntimeError("backend delete failed")


def test_keyring_failures_are_stable_and_do_not_leak_secrets() -> None:
    store = KeyringCredentialStore(backend=ExplodingKeyring())
    credential_ref = "provider:primary:0123456789abcdef0123456789abcdef"
    with pytest.raises(CredentialStoreError) as captured:
        store.put(credential_ref, "never-print-this-key")
    assert captured.value.code == "credential_write_failed"
    assert str(captured.value) == "credential_write_failed"
    assert "never-print-this-key" not in repr(captured.value)


def test_production_provider_keyring_is_macos_only(monkeypatch) -> None:
    monkeypatch.setattr("openclaw_media.credentials.platform.system", lambda: "Linux")
    with pytest.raises(CredentialStoreError) as captured:
        KeyringCredentialStore().get("provider:primary:0123456789abcdef0123456789abcdef")
    assert captured.value.code == "macos_required"


def test_repository_json_contains_only_declared_config_fields(tmp_path: Path) -> None:
    instance, _ = service(tmp_path)
    config = configure(instance)
    payload = json.loads((tmp_path / "primary.json").read_text())
    assert payload == config.model_dump(mode="json")
