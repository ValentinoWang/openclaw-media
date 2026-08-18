from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from .resource_owner_registry import ResourceOwnerInvalid, require_tenant_id


_SESSION_TENANT_ID: ContextVar[str | None] = ContextVar(
    "openclaw_session_tenant_id",
    default=None,
)


@contextmanager
def bind_session_tenant_id(value: str | int | None) -> Iterator[None]:
    tenant_id = require_tenant_id(value) if value is not None else None
    token = _SESSION_TENANT_ID.set(tenant_id)
    try:
        yield
    finally:
        _SESSION_TENANT_ID.reset(token)


def current_session_tenant_id(*, required: bool = True) -> str | None:
    tenant_id = _SESSION_TENANT_ID.get()
    if tenant_id is None and required:
        raise ResourceOwnerInvalid("authenticated tenant context is required")
    return tenant_id
