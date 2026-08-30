"""Shared test fakes local to this suite.

This suite's conftest.py only puts the repo root on sys.path (not the root
``tests/`` directory itself), so files here cannot resolve
``from _fakes.http import ...`` the way files directly under the repo's
``tests/`` do. Keep this file's fakes in sync by hand with their
counterparts in tests/_fakes/http.py when their behavior changes.
"""

from __future__ import annotations


class SseResponse:
    """Fake response for llm_client's raw SSE (`iter_content`) parsing path.

    See tests/_fakes/http.py::SseResponse for the full contract this
    mirrors -- frames are yielded from ``iter_content`` exactly as given.
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


def recording_post(response, captured: dict[str, object] | None = None):
    """Build a stand-in for ``requests.post`` that records its call args.

    See tests/_fakes/http.py::recording_post for the full contract this
    mirrors.
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
