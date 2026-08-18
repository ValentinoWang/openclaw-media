from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from openclaw_app import retail_batch_cli


def test_batch_cli_uses_plan_mapping_as_the_only_product_authority(monkeypatch, capsys) -> None:
    calls: dict[str, object] = {}

    class FakeSettings:
        @staticmethod
        def from_environment(environment: object) -> str:
            calls["environment"] = environment
            return "settings"

    class FakeService:
        def __init__(self, database: object, *, code_secret: bytes, export_root: str) -> None:
            calls["database"] = database
            calls["code_secret"] = code_secret
            calls["export_root"] = export_root

        def create_batch(self, **kwargs: object) -> object:
            calls["create_batch"] = kwargs
            return SimpleNamespace(
                batch_id="10000000-0000-4000-8000-000000000001",
                code_count=1,
                export_path=Path("/private/export.txt"),
            )

    monkeypatch.setattr(retail_batch_cli, "AccountDatabaseSettings", FakeSettings)
    monkeypatch.setattr(retail_batch_cli, "AccountDatabase", lambda settings: ("database", settings))
    monkeypatch.setattr(retail_batch_cli, "RetailFulfillmentService", FakeService)
    monkeypatch.setattr(retail_batch_cli, "load_auth_environment", lambda path: ("auth", path))
    monkeypatch.setattr(retail_batch_cli, "load_redemption_secret", lambda path: b"secret")
    monkeypatch.setattr(
        "sys.argv",
        [
            "retail-batch-cli",
            "--auth-env",
            "/private/auth.env",
            "--redemption-hmac-secret-file",
            "/private/redemption.secret",
            "--export-root",
            "/private/exports",
            "--actor-user-id",
            "10000000-0000-4000-8000-000000000002",
            "--plan-code",
            "mediaclaw-cny-1",
            "--count",
            "1",
            "--idempotency-key",
            "replacement-1",
        ],
    )

    assert retail_batch_cli.main() == 0
    assert calls["create_batch"] == {
        "actor_user_id": "10000000-0000-4000-8000-000000000002",
        "plan_code": "mediaclaw-cny-1",
        "count": 1,
        "idempotency_key": "replacement-1",
    }
    assert json.loads(capsys.readouterr().out) == {
        "batchId": "10000000-0000-4000-8000-000000000001",
        "codeCount": 1,
        "exportPath": "/private/export.txt",
    }
