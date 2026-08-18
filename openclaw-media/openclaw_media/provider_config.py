"""Canonical local ProviderConfig model and persistence service."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import json
import os
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .credentials import CredentialStore, CredentialStoreError


_CONFIG_ID = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,63}\Z")


class ProviderConfigError(RuntimeError):
    """A public-safe provider configuration failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProviderHealth(str, Enum):
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"


class ProviderConfig(BaseModel):
    """Local provider configuration; never contains an API key."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    config_id: str
    provider_type: Literal["openai_compatible"] = "openai_compatible"
    base_url: str
    model: str = Field(min_length=1, max_length=256)
    model_label: str = Field(min_length=1, max_length=128)
    credential_ref: str
    local_endpoint_enabled: bool = False
    health: ProviderHealth = ProviderHealth.UNAVAILABLE
    last_health_check_at: datetime | None = None

    @field_validator("config_id")
    @classmethod
    def validate_config_id(cls, value: str) -> str:
        if not _CONFIG_ID.fullmatch(value):
            raise ValueError("invalid_config_id")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("invalid_base_url") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or port is None and ":" in parsed.netloc.rsplit("]", 1)[-1]
        ):
            raise ValueError("invalid_base_url")
        return value.rstrip("/")

    @field_validator("credential_ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        from .credentials import validate_credential_ref

        try:
            return validate_credential_ref(value)
        except CredentialStoreError as exc:
            raise ValueError(exc.code) from exc


class ProviderHealthProjection(BaseModel):
    """Only provider metadata allowed to leave the local CLI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_type: Literal["openai_compatible"]
    model_label: str
    health: ProviderHealth
    last_health_check_at: datetime | None


class ProviderConfigRepository:
    """Persist secret-free provider configurations as owner-only JSON."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, config_id: str) -> Path:
        if not isinstance(config_id, str) or not _CONFIG_ID.fullmatch(config_id):
            raise ProviderConfigError("invalid_config_id")
        return self.root / f"{config_id}.json"

    def save(self, config: ProviderConfig) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(config.config_id)
        temporary = path.with_suffix(f".json.{uuid4().hex}.tmp")
        payload = config.model_dump_json(indent=2) + "\n"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ProviderConfigError("config_write_failed") from exc

    def load(self, config_id: str) -> ProviderConfig:
        path = self._path(config_id)
        try:
            payload = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ProviderConfigError("config_not_found") from exc
        except OSError as exc:
            raise ProviderConfigError("config_read_failed") from exc
        try:
            return ProviderConfig.model_validate_json(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderConfigError("config_corrupt") from exc

    def list(self) -> tuple[ProviderConfig, ...]:
        if not self.root.exists():
            return ()
        configs = [self.load(path.stem) for path in sorted(self.root.glob("*.json"))]
        return tuple(configs)

    def delete(self, config_id: str) -> None:
        path = self._path(config_id)
        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise ProviderConfigError("config_not_found") from exc
        except OSError as exc:
            raise ProviderConfigError("config_delete_failed") from exc


class ProviderConfigService:
    """Coordinate secret writes with secret-free config persistence."""

    def __init__(
        self, repository: ProviderConfigRepository, credentials: CredentialStore
    ) -> None:
        self.repository = repository
        self.credentials = credentials

    def configure(
        self,
        *,
        config_id: str,
        base_url: str,
        model: str,
        model_label: str,
        api_key: str,
        provider_type: str = "openai_compatible",
        local_endpoint_enabled: bool = False,
    ) -> ProviderConfig:
        if not isinstance(api_key, str) or not api_key:
            raise ProviderConfigError("invalid_credential")
        if not isinstance(config_id, str) or not _CONFIG_ID.fullmatch(config_id):
            raise ProviderConfigError("invalid_config")
        previous: ProviderConfig | None
        try:
            previous = self.repository.load(config_id)
        except ProviderConfigError as exc:
            if exc.code != "config_not_found":
                raise
            previous = None

        credential_ref = f"provider:{config_id}:{uuid4().hex}"
        try:
            config = ProviderConfig(
                config_id=config_id,
                provider_type=provider_type,
                base_url=base_url,
                model=model,
                model_label=model_label,
                credential_ref=credential_ref,
                local_endpoint_enabled=local_endpoint_enabled,
            )
        except ValueError as exc:
            raise ProviderConfigError("invalid_config") from exc

        self.credentials.put(credential_ref, api_key)
        try:
            self.repository.save(config)
        except Exception:
            try:
                self.credentials.delete(credential_ref)
            except CredentialStoreError:
                pass
            raise
        if previous is not None:
            self.credentials.delete(previous.credential_ref)
        return config

    def delete(self, config_id: str) -> None:
        config = self.repository.load(config_id)
        self.credentials.delete(config.credential_ref)
        self.repository.delete(config_id)

    def projection(self, config_id: str) -> ProviderHealthProjection:
        config = self.repository.load(config_id)
        return ProviderHealthProjection(
            provider_type=config.provider_type,
            model_label=config.model_label,
            health=config.health,
            last_health_check_at=config.last_health_check_at,
        )


__all__ = [
    "ProviderConfig",
    "ProviderConfigError",
    "ProviderConfigRepository",
    "ProviderConfigService",
    "ProviderHealth",
    "ProviderHealthProjection",
]
