from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import sleep
from typing import Any

from openclaw_app.services import feishu_service
from openclaw_app.services.feishu_service import FeishuService


class _ImageResponse:
    status_code = 200
    headers = {"Content-Type": "image/png", "Content-Length": "3"}

    def iter_content(self, chunk_size: int) -> list[bytes]:
        assert chunk_size == 64 * 1024
        return [b"png"]

    def close(self) -> None:
        return None


class _TokenResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"code": 0, "tenant_access_token": "shared-token", "expire": 3600}


def test_concurrent_requests_share_one_access_token_refresh(monkeypatch: Any, tmp_path: Any) -> None:
    service = FeishuService(
        "local_markdown",
        str(tmp_path),
        app_id="app-id",
        app_secret="app-secret",
    )
    callers_ready = Barrier(7)
    count_lock = Lock()
    refresh_count = 0

    def fake_post(*args: Any, **kwargs: Any) -> _TokenResponse:
        nonlocal refresh_count
        with count_lock:
            refresh_count += 1
        sleep(0.02)
        return _TokenResponse()

    monkeypatch.setattr(feishu_service.requests, "post", fake_post)

    def load_token() -> str:
        callers_ready.wait()
        return service._get_tenant_access_token()

    with ThreadPoolExecutor(max_workers=7) as executor:
        tokens = list(executor.map(lambda _index: load_token(), range(7)))

    assert tokens == ["shared-token"] * 7
    assert refresh_count == 1


def test_bitable_attachment_download_returns_binary_without_provider_url(monkeypatch: Any, tmp_path: Any) -> None:
    seen: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> _ImageResponse:
        seen["url"] = url
        seen["stream"] = kwargs["stream"]
        return _ImageResponse()

    monkeypatch.setattr(feishu_service.requests, "get", fake_get)
    service = FeishuService("local_markdown", str(tmp_path))
    service._request = lambda method, path, **kwargs: {  # type: ignore[method-assign]
        "data": {
            "tmp_download_urls": [
                {
                    "file_token": "file-token",
                    "tmp_download_url": "https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download",
                }
            ]
        }
    }

    payload = service.download_bitable_attachment("base", "table", "record", "file-token")

    assert payload == {"body": b"png", "contentType": "image/png"}
    assert seen["url"] == "https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download"
    assert seen["stream"] is True


def test_bitable_attachment_download_rejects_missing_or_insecure_temporary_url(tmp_path: Any) -> None:
    service = FeishuService("local_markdown", str(tmp_path))
    service._request = lambda method, path, **kwargs: {  # type: ignore[method-assign]
        "data": {
            "tmp_download_urls": [
                {"file_token": "file-token", "tmp_download_url": "http://example.invalid/image.png"}
            ]
        }
    }

    try:
        service.download_bitable_attachment("base", "table", "record", "file-token")
    except RuntimeError as exc:
        assert str(exc) == "Feishu attachment download failed"
    else:
        raise AssertionError("insecure temporary URL must be rejected")
