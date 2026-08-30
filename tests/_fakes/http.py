"""Shared fake ``requests`` responses for llm_client tests.

These stand in for the real ``requests.Response`` object returned by
``requests.post`` in llm_client's Codex Responses SSE path and its chat
completions JSON path. They used to be redefined locally (with small,
inconsistent variations) 11 times across tests/test_bot_llm_config.py and
tests/test_llm_untrusted_input_isolation.py. Import from here instead of
redefining a local copy.

A twelfth copy lives in
selfmedia/deconstruct/viral_content/tests/_fakes.py: that suite's
conftest.py only adds the repo root to sys.path (not this ``tests/``
directory), so it cannot resolve ``from _fakes.http import ...`` the way
files directly under ``tests/`` can. Keep the two in sync by hand if the
SSE fake's behavior ever needs to change.
"""

from __future__ import annotations

import time
from typing import Callable


class SseResponse:
    """Fake response for llm_client's raw SSE (`iter_content`) parsing path.

    Pass whole SSE lines (e.g. ``'data: {...}\\n'``) as positional
    ``frames`` -- they are yielded from ``iter_content`` exactly as given,
    in order. A single frame string may itself contain multiple ``data:
    ...\\n`` lines to simulate several events arriving in one socket read.

    ``as_bytes=True`` utf-8-encodes each frame before yielding it, to model
    a server responding without an explicit response charset (llm_client
    must then decode based on content, not response encoding).

    ``error``, if given, is raised the first time the caller iterates
    ``iter_content`` (not when ``iter_content()`` is merely called) --
    ``iter_content`` stays a generator function even on the error path, to
    match real ``requests`` generator semantics.

    After a call, ``last_chunk_size`` / ``last_decode_unicode`` hold the
    arguments the caller passed into ``iter_content``, for tests that need
    to assert on how llm_client invoked it.
    """

    def __init__(self, *frames: str, as_bytes: bool = False, error: BaseException | None = None) -> None:
        self._frames = frames
        self._as_bytes = as_bytes
        self._error = error
        self.last_chunk_size: int | None = None
        self.last_decode_unicode: bool | None = None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
        self.last_chunk_size = chunk_size
        self.last_decode_unicode = decode_unicode
        if self._error is not None:
            raise self._error
            yield  # pragma: no cover - unreachable; keeps this a generator function
        for frame in self._frames:
            yield frame.encode("utf-8") if self._as_bytes else frame


class HangingSseResponse:
    """Fake response whose ``iter_content`` never stops on its own.

    Yields an empty chunk forever, sleeping between each -- for exercising
    a hard *total* timeout watchdog that must interrupt a genuinely
    blocking read (a real wall-clock sleep, not a fake one), as opposed to
    ``SseResponse``'s ``error=`` which models a read that raises outright.
    """

    def __init__(self, sleep_seconds: float = 1, sleep_call: Callable[[float], None] | None = None) -> None:
        self._sleep_seconds = sleep_seconds
        self._sleep = sleep_call or time.sleep

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False):
        while True:
            self._sleep(self._sleep_seconds)
            yield ""


class JsonResponse:
    """Fake response for llm_client's chat-completions JSON (`.json()`) path."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def recording_post(response, captured: dict[str, object] | None = None):
    """Build a stand-in for ``requests.post`` that records its call args.

    ``response`` is returned unconditionally. The returned callable exposes
    a ``.captured`` dict (also available as this function's ``captured``
    argument, if you passed one) filled with ``url``, ``headers``, ``json``,
    ``timeout`` and ``stream`` after each call -- callers that only care
    about a subset just read the keys they need.
    """

    if captured is None:
        captured = {}

    def fake_post(url, headers, json, timeout, stream=False):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        captured["stream"] = stream
        return response

    fake_post.captured = captured
    return fake_post
