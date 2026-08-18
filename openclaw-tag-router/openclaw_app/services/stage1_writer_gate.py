"""Fail-closed boundary for the Stage 1 AI document writer.

Stage 1 exposes resource discovery and read mirrors only.  Keeping this gate
callable lets a future route reject a writer request before it reaches any
legacy Feishu writer or credential-bearing service.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, NoReturn


WRITER_CLOSED_ERROR_CODE = "capability_unavailable_until_writer_migration"
WRITER_CLOSED_STATUS = 503
WRITER_CLOSED_MESSAGE = "AI document writing is unavailable until WriterRouter migration"


class WriterClosedError(RuntimeError):
    """Stable API-shaped error raised for every Stage 1 writer attempt."""

    def __init__(self, message: str = WRITER_CLOSED_MESSAGE) -> None:
        self.code = WRITER_CLOSED_ERROR_CODE
        self.message = message
        self.detail = message
        self.status = WRITER_CLOSED_STATUS
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }


class WriterClosed:
    """An immutable, credential-free callable gate whose only result is denial."""

    __slots__ = ()

    state = "closed"
    enabled = False
    invocation_count = 0
    external_write_calls = 0
    credentials = None
    writer_credentials = None
    contract = MappingProxyType(
        {
            "state": "closed",
            "enabled": False,
            "error_code": WRITER_CLOSED_ERROR_CODE,
            "invocation_count": 0,
            "external_write_calls": 0,
            "credentials": None,
            "writer_credentials": None,
        }
    )

    def __call__(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        """Reject direct calls without evaluating a supplied writer or payload."""

        self.reject()

    def reject(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        """Reject any direct or indirect writer invocation."""

        raise WriterClosedError()

    def reject_direct_invocation(
        self,
        writer: Callable[..., Any] | None = None,
        *_args: Any,
        **_kwargs: Any,
    ) -> NoReturn:
        """Guard a future route before it can call its legacy writer."""

        del writer
        self.reject()

    def reject_stale_task_replay(
        self,
        task: Mapping[str, Any] | None = None,
        *_args: Any,
        **_kwargs: Any,
    ) -> NoReturn:
        """Reject queued, stale, or replayed writer work in the closed stage."""

        del task
        self.reject()


WRITER_CLOSED = WriterClosed()


def guard_writer_call(
    writer: Callable[..., Any] | None = None,
    *_args: Any,
    **_kwargs: Any,
) -> NoReturn:
    """Small route hook that denies before a writer callable is reached."""

    WRITER_CLOSED.reject_direct_invocation(writer, *_args, **_kwargs)


def guard_stale_writer_task(
    task: Mapping[str, Any] | None = None,
    *_args: Any,
    **_kwargs: Any,
) -> NoReturn:
    """Small worker hook for old or replayed writer tasks."""

    WRITER_CLOSED.reject_stale_task_replay(task, *_args, **_kwargs)


__all__ = [
    "WRITER_CLOSED",
    "WRITER_CLOSED_ERROR_CODE",
    "WRITER_CLOSED_MESSAGE",
    "WRITER_CLOSED_STATUS",
    "WriterClosed",
    "WriterClosedError",
    "guard_stale_writer_task",
    "guard_writer_call",
]
