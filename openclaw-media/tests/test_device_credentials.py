from __future__ import annotations

import pytest

import openclaw_media.device_credentials as device_credentials
from openclaw_media.device_credentials import DeviceCredentialError, DeviceCredentialStore


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def test_device_and_session_refs_are_separate_and_values_never_enter_state():
    backend = FakeKeyring()
    store = DeviceCredentialStore(backend=backend)
    refs = store.put_device("dev_abc", "device-secret")
    store.put_session("dev_abc", "session-secret")
    assert refs.device != refs.session
    assert store.get_device("dev_abc") == "device-secret"
    assert store.get_session("dev_abc") == "session-secret"
    assert set(backend.values) == {
        ("openclaw-media-agent", refs.device),
        ("openclaw-media-agent", refs.session),
    }
    store.delete_device("dev_abc")
    assert store.get_session("dev_abc") == "session-secret"


def test_invalid_id_and_missing_secret_fail_closed():
    store = DeviceCredentialStore(backend=FakeKeyring())
    with pytest.raises(DeviceCredentialError) as raised:
        store.get_device("/tmp/device")
    assert raised.value.code == "invalid_device_id"
    with pytest.raises(DeviceCredentialError) as raised:
        store.get_session("dev_missing")
    assert raised.value.code == "session_not_found"


def test_production_store_requires_macos(monkeypatch):
    monkeypatch.setattr(device_credentials.platform, "system", lambda: "Linux")
    with pytest.raises(DeviceCredentialError) as raised:
        DeviceCredentialStore().get_device("dev_abc")
    assert raised.value.code == "macos_required"


def test_darwin_production_store_rejects_non_keychain_backend(monkeypatch):
    import keyring

    class NonKeychainBackend(FakeKeyring):
        pass

    monkeypatch.setattr(device_credentials.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(keyring, "get_keyring", lambda: NonKeychainBackend())
    with pytest.raises(DeviceCredentialError) as raised:
        DeviceCredentialStore().get_device("dev_abc")
    assert raised.value.code == "keychain_required"


def test_explicit_injected_backend_is_allowed_for_tests_on_linux(monkeypatch):
    monkeypatch.setattr(device_credentials.platform, "system", lambda: "Linux")
    store = DeviceCredentialStore(backend=FakeKeyring())
    store.put_session("dev_abc", "session-secret")
    assert store.get_session("dev_abc") == "session-secret"
