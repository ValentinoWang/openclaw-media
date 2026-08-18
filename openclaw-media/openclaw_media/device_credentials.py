"""Keychain-only credentials for the Media Agent.

Device and optional owner-session credentials have distinct keyring entries.
The persistent agent state stores only these references, never their values.
"""

from __future__ import annotations

from dataclasses import dataclass
import platform
import re
from typing import Protocol


class DeviceCredentialError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class KeyringBackend(Protocol):
    def set_password(self, service_name: str, username: str, password: str) -> None: ...
    def get_password(self, service_name: str, username: str) -> str | None: ...
    def delete_password(self, service_name: str, username: str) -> None: ...


_DEVICE_ID = re.compile(r"\Adev_[A-Za-z0-9_-]{1,120}\Z")


@dataclass(frozen=True, slots=True)
class CredentialRefs:
    device: str
    session: str

    @classmethod
    def for_device(cls, device_id: str) -> "CredentialRefs":
        if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id):
            raise DeviceCredentialError("invalid_device_id")
        return cls(
            device=f"device:{device_id}:credential",
            session=f"device:{device_id}:session",
        )


@dataclass(slots=True)
class DeviceCredentialStore:
    """A narrow adapter whose only backing store is the platform keyring."""

    service_name: str = "openclaw-media-agent"
    backend: KeyringBackend | None = None

    def _keyring(self) -> KeyringBackend:
        if self.backend is not None:
            return self.backend
        if platform.system().lower() != "darwin":
            raise DeviceCredentialError("macos_required")
        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise DeviceCredentialError("credential_store_unavailable") from exc
        try:
            from keyring.backends.macOS import Keyring as MacOSKeychain
            backend = keyring.get_keyring()
        except Exception as exc:
            raise DeviceCredentialError("credential_store_unavailable") from exc
        if not isinstance(backend, MacOSKeychain):
            raise DeviceCredentialError("keychain_required")
        return backend

    @staticmethod
    def refs(device_id: str) -> CredentialRefs:
        return CredentialRefs.for_device(device_id)

    @staticmethod
    def _secret(value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise DeviceCredentialError("invalid_credential")
        return value

    def put_device(self, device_id: str, credential: str) -> CredentialRefs:
        refs = self.refs(device_id)
        try:
            self._keyring().set_password(self.service_name, refs.device, self._secret(credential))
        except DeviceCredentialError:
            raise
        except Exception as exc:
            raise DeviceCredentialError("credential_write_failed") from exc
        return refs

    def get_device(self, device_id: str) -> str:
        refs = self.refs(device_id)
        try:
            value = self._keyring().get_password(self.service_name, refs.device)
        except DeviceCredentialError:
            raise
        except Exception as exc:
            raise DeviceCredentialError("credential_read_failed") from exc
        if not value:
            raise DeviceCredentialError("credential_not_found")
        return self._secret(value)

    def delete_device(self, device_id: str) -> None:
        refs = self.refs(device_id)
        try:
            self._keyring().delete_password(self.service_name, refs.device)
        except DeviceCredentialError:
            raise
        except Exception as exc:
            raise DeviceCredentialError("credential_delete_failed") from exc

    def put_session(self, device_id: str, credential: str) -> CredentialRefs:
        refs = self.refs(device_id)
        try:
            self._keyring().set_password(self.service_name, refs.session, self._secret(credential))
        except DeviceCredentialError:
            raise
        except Exception as exc:
            raise DeviceCredentialError("session_write_failed") from exc
        return refs

    def get_session(self, device_id: str) -> str:
        refs = self.refs(device_id)
        try:
            value = self._keyring().get_password(self.service_name, refs.session)
        except DeviceCredentialError:
            raise
        except Exception as exc:
            raise DeviceCredentialError("session_read_failed") from exc
        if not value:
            raise DeviceCredentialError("session_not_found")
        return self._secret(value)

    def delete_session(self, device_id: str) -> None:
        refs = self.refs(device_id)
        try:
            self._keyring().delete_password(self.service_name, refs.session)
        except DeviceCredentialError:
            raise
        except Exception as exc:
            raise DeviceCredentialError("session_delete_failed") from exc


KeychainDeviceCredentialStore = DeviceCredentialStore

__all__ = [
    "CredentialRefs",
    "DeviceCredentialError",
    "DeviceCredentialStore",
    "KeychainDeviceCredentialStore",
]
