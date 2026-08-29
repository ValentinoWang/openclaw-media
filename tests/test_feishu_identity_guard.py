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

