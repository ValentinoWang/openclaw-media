"""Credential storage boundary for local provider API keys."""

from __future__ import annotations

from dataclasses import dataclass
import platform
import re
from typing import Protocol, runtime_checkable


_CREDENTIAL_REF = re.compile(r"\Aprovider:[a-z0-9][a-z0-9._-]{0,63}:[0-9a-f]{32}\Z")


class CredentialStoreError(RuntimeError):
    """A public-safe credential operation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@runtime_checkable
class CredentialStore(Protocol):
    """Minimal secret boundary used by provider configuration and adapters."""

    def put(self, credential_ref: str, secret: str) -> None: ...

    def get(self, credential_ref: str) -> str: ...

    def delete(self, credential_ref: str) -> None: ...


def validate_credential_ref(credential_ref: str) -> str:
    if not isinstance(credential_ref, str) or not _CREDENTIAL_REF.fullmatch(
        credential_ref
    ):
        raise CredentialStoreError("invalid_credential_ref")
    return credential_ref


@dataclass(slots=True)
class KeyringCredentialStore:
    """Store provider secrets in the operating system's keyring backend."""

    service_name: str = "openclaw-media"
    backend: object | None = None

    def _backend(self) -> object:
        if self.backend is not None:
            return self.backend
        if platform.system().lower() != "darwin":
            raise CredentialStoreError("macos_required")
        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - installation contract
            raise CredentialStoreError("credential_store_unavailable") from exc
        try:
            from keyring.backends.macOS import Keyring as MacOSKeychain
            backend = keyring.get_keyring()
        except Exception as exc:
            raise CredentialStoreError("credential_store_unavailable") from exc
        if not isinstance(backend, MacOSKeychain):
            raise CredentialStoreError("keychain_required")
        return backend

    def put(self, credential_ref: str, secret: str) -> None:
        validate_credential_ref(credential_ref)
        if not isinstance(secret, str) or not secret:
            raise CredentialStoreError("invalid_credential")
        try:
            self._backend().set_password(self.service_name, credential_ref, secret)
        except CredentialStoreError:
            raise
        except Exception as exc:
            raise CredentialStoreError("credential_write_failed") from exc

    def get(self, credential_ref: str) -> str:
        validate_credential_ref(credential_ref)
        try:
            secret = self._backend().get_password(self.service_name, credential_ref)
        except CredentialStoreError:
            raise
        except Exception as exc:
            raise CredentialStoreError("credential_read_failed") from exc
        if not secret:
            raise CredentialStoreError("credential_not_found")
        return secret

    def delete(self, credential_ref: str) -> None:
        validate_credential_ref(credential_ref)
        try:
            self._backend().delete_password(self.service_name, credential_ref)
        except CredentialStoreError:
            raise
        except Exception as exc:
            raise CredentialStoreError("credential_delete_failed") from exc


__all__ = [
    "CredentialStore",
    "CredentialStoreError",
    "KeyringCredentialStore",
    "validate_credential_ref",
]
