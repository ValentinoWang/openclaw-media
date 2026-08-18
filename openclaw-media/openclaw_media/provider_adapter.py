"""Canonical in-process LiteLLM adapter for local BYOK providers."""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .credentials import CredentialStore, CredentialStoreError
from .provider_config import ProviderConfig
from .safe_transport import SafeEndpointTransport, SafeTransportError


class ProviderAdapterError(RuntimeError):
    """Stable public failure with no provider payload or secret text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class VisionImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    data: bytes = Field(min_length=1, repr=False)


class TextResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content: str
    model_label: str


class VisionResult(TextResult):
    pass


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class StructuredResult(BaseModel, Generic[SchemaT]):
    model_config = ConfigDict(extra="forbid", frozen=True)
    value: SchemaT
    model_label: str


class _SafeBridge(httpx.BaseTransport):
    """Non-network HTTPX bridge; SafeEndpointTransport owns every socket."""

    def __init__(
        self, transport: SafeEndpointTransport, credential: str, base_url: str
    ) -> None:
        self._transport = transport
        self._credential = credential
        self._base_path = urlsplit(base_url).path.rstrip("/")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() not in {"authorization", "proxy-authorization", "host"}
        }
        target = request.url.raw_path.decode("ascii")
        if self._base_path and (
            target == self._base_path or target.startswith(self._base_path + "/")
        ):
            target = target[len(self._base_path) :] or "/"
        if request.url.query:
            target += "?" + request.url.query.decode("ascii")
        response = self._transport.request(
            request.method,
            target,
            headers=headers,
            content=request.read(),
            credential=self._credential,
        )
        try:
            content = response.read()
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=content,
                extensions=response.extensions,
            )
        finally:
            response.close()

    def close(self) -> None:
        self._transport.close()


class ProviderAdapter:
    """One confirmed ProviderConfig, model, endpoint, and LiteLLM route."""

    def __init__(
        self,
        config: ProviderConfig,
        credentials: CredentialStore,
        *,
        max_attempts: int = 2,
        transport_factory: Callable[..., SafeEndpointTransport] = SafeEndpointTransport,
    ) -> None:
        if config.provider_type != "openai_compatible":
            raise ProviderAdapterError("unsupported_provider")
        if max_attempts not in (1, 2):
            raise ProviderAdapterError("invalid_retry_policy")
        self._config = config.model_copy(deep=True)
        self._credentials = credentials
        self._max_attempts = max_attempts
        self._transport_factory = transport_factory

    def complete_text(self, prompt: str) -> TextResult:
        content = self._complete(self._text_messages(prompt))
        return TextResult(content=content, model_label=self._config.model_label)

    def complete_vision(
        self, prompt: str, images: Sequence[VisionImage]
    ) -> VisionResult:
        if not images:
            raise ProviderAdapterError("invalid_input")
        content: list[dict[str, Any]] = [{"type": "text", "text": self._prompt(prompt)}]
        for image in tuple(images):
            encoded = base64.b64encode(image.data).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{image.media_type};base64,{encoded}"}}
            )
        result = self._complete([{"role": "user", "content": content}])
        return VisionResult(content=result, model_label=self._config.model_label)

    def complete_structured(
        self, prompt: str, schema: type[SchemaT]
    ) -> StructuredResult[SchemaT]:
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise ProviderAdapterError("invalid_schema")
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "strict": True, "schema": schema.model_json_schema()},
        }
        content = self._complete(self._text_messages(prompt), response_format=response_format)
        try:
            value = schema.model_validate_json(content, strict=True)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ProviderAdapterError("invalid_structured_response") from exc
        return StructuredResult[schema](value=value, model_label=self._config.model_label)

    def _text_messages(self, prompt: str) -> list[dict[str, str]]:
        return [{"role": "user", "content": self._prompt(prompt)}]

    @staticmethod
    def _prompt(prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderAdapterError("invalid_input")
        return prompt

    def _complete(self, messages: list[dict[str, Any]], **extra: Any) -> str:
        try:
            credential = self._credentials.get(self._config.credential_ref)
        except Exception as exc:
            raise ProviderAdapterError("credential_unavailable") from exc
        try:
            import litellm
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderAdapterError("adapter_unavailable") from exc
        for name in ("callbacks", "input_callback", "success_callback", "failure_callback", "service_callback"):
            setattr(litellm, name, [])
        litellm.telemetry = False
        litellm.turn_off_message_logging = True
        litellm.suppress_debug_info = True
        last_error: Exception | None = None
        for _ in range(self._max_attempts):
            safe = None
            client = None
            try:
                safe = self._transport_factory(
                    self._config.base_url,
                    local_endpoint_enabled=self._config.local_endpoint_enabled,
                )
                http_client = httpx.Client(
                    transport=_SafeBridge(safe, credential, self._config.base_url),
                    trust_env=False,
                    follow_redirects=False,
                )
                client = OpenAI(
                    api_key=credential,
                    base_url=self._config.base_url,
                    http_client=http_client,
                    max_retries=0,
                )
                response = litellm.completion(
                    model=self._config.model,
                    messages=messages,
                    custom_llm_provider="openai",
                    api_base=self._config.base_url,
                    api_key=credential,
                    client=client,
                    max_retries=0,
                    stream=False,
                    **{"no-log": True},
                    **extra,
                )
                content = response.choices[0].message.content
                if not isinstance(content, str) or not content:
                    raise ProviderAdapterError("invalid_response")
                return content
            except ProviderAdapterError:
                raise
            except (SafeTransportError, Exception) as exc:
                last_error = exc
            finally:
                if client is not None:
                    client.close()
                elif safe is not None:
                    safe.close()
        raise ProviderAdapterError("provider_unavailable") from last_error


__all__ = [
    "ProviderAdapter", "ProviderAdapterError", "StructuredResult", "TextResult", "VisionImage", "VisionResult"
]
