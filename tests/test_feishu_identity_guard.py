from __future__ import annotations

import pytest

from common import social_runtime


def test_feishu_app_id_prefix_is_stable_and_redacted() -> None:
    assert social_runtime.feishu_app_id_prefix("cli_1234567890") == "cli_1234"
    assert social_runtime.feishu_app_id_prefix("cli_") == "cli_xxxx"
    assert social_runtime.feishu_app_id_prefix("") == "未配置"
    assert "1234567890" not in social_runtime.feishu_app_id_prefix("cli_1234567890")


def test_feishu_identity_info_resolves_effective_app_id_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(social_runtime, "load_default_env_files", lambda: None)
    monkeypatch.setenv("FEISHU_APP_ID", "cli_abcdef123")
    monkeypatch.setenv("FEISHU_APP_SECRET", "super-secret-value")

    info = social_runtime.feishu_identity_preflight()

    assert info == {"app_id_prefix": "cli_abcd", "configured": True}
    assert "super-secret-value" not in repr(info)
    assert "abcdef123" not in repr(info)


def test_feishu_tenant_access_token_91403_explains_identity_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(social_runtime, "load_default_env_files", lambda: None)
    monkeypatch.setenv("FEISHU_APP_ID", "cli_1234567890")
    monkeypatch.setenv("FEISHU_APP_SECRET", "super-secret-value")

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"code": 91403, "msg": "permission denied", "tenant_access_token": "secret-token"}

    monkeypatch.setattr(social_runtime.requests, "post", lambda *args, **kwargs: Response())

    with pytest.raises(RuntimeError) as raised:
        social_runtime.feishu_tenant_access_token()

    message = str(raised.value)
    assert message == "当前身份 cli_1234 对该 Base 无权限（不等于表被删）"
    assert "super-secret-value" not in message
    assert "secret-token" not in message


def test_fetch_tenant_access_token_cache_is_keyed_by_app_id_not_a_process_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # FC-01: the cache key must be (api_base, app_id), never a single
    # process-wide slot -- e.g. the DeepMath branch's injected credentials
    # and this process's own default identity must never share a cached
    # token. Uses a unique api_base so this test can't collide with a
    # cache entry left behind by any other test in the same session.
    calls: list[tuple[str, str]] = []

    class Response:
        def __init__(self, token: str) -> None:
            self._token = token

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"code": 0, "tenant_access_token": self._token, "expire": 3600}

    def fake_post(_url: str, *, json: dict[str, str], timeout: float) -> Response:
        calls.append((json["app_id"], json["app_secret"]))
        return Response(f"token-for-{json['app_id']}")

    monkeypatch.setattr(social_runtime.requests, "post", fake_post)

    api_base = "https://fake-cache-isolation-test.example/open-apis"
    token_a1 = social_runtime.fetch_tenant_access_token("cache-test-app-a", "secret-a", api_base=api_base)
    token_b1 = social_runtime.fetch_tenant_access_token("cache-test-app-b", "secret-b", api_base=api_base)
    token_a2 = social_runtime.fetch_tenant_access_token("cache-test-app-a", "secret-a", api_base=api_base)

    assert token_a1 == "token-for-cache-test-app-a"
    assert token_b1 == "token-for-cache-test-app-b"
    assert token_a2 == token_a1
    # Exactly two HTTP round trips: the repeated app-a call must be served
    # from its own cache entry, not re-fetched and not served app-b's token.
    assert calls == [("cache-test-app-a", "secret-a"), ("cache-test-app-b", "secret-b")]

