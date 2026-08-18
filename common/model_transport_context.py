from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Protocol

import requests


class ModelTransportError(RuntimeError):
    """Terminal transport outcome that callers must not hide or auto-retry."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ModelCall(Protocol):
    def post(
        self,
        endpoint: str,
        *,
        json_body: dict[str, Any],
        timeout: Any,
        stream: bool = False,
    ) -> requests.Response: ...

    def complete(self, response: requests.Response, payload: dict[str, Any] | None = None) -> None: ...

    def uncertain(self, response: requests.Response | None = None) -> None: ...


class ModelTransport(Protocol):
    def begin_call(self, endpoint: str) -> ModelCall: ...


_TRANSPORT: ContextVar[ModelTransport | None] = ContextVar("openclaw_model_transport", default=None)
_TRANSPORT_REQUIRED: ContextVar[bool] = ContextVar("openclaw_model_transport_required", default=False)


@contextmanager
def bind_model_transport(transport: ModelTransport | None, *, required: bool = True) -> Iterator[None]:
    transport_token = _TRANSPORT.set(transport)
    required_token = _TRANSPORT_REQUIRED.set(required)
    try:
        yield
    finally:
        _TRANSPORT_REQUIRED.reset(required_token)
        _TRANSPORT.reset(transport_token)


def current_model_transport() -> ModelTransport | None:
    transport = _TRANSPORT.get()
    if transport is None and _TRANSPORT_REQUIRED.get():
        raise RuntimeError("authenticated tenant model transport is unavailable")
    return transport


def tenant_model_transport_required() -> bool:
    return _TRANSPORT_REQUIRED.get()
