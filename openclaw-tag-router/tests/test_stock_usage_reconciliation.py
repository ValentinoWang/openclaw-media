from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from openclaw_app.services.retail_billing import RetailBillingError, Usage
from openclaw_app.services.stock_usage_reconciliation import StockUsageReconciler


class _Response:
    def raise_for_status(self) -> None:
        return None

    @staticmethod
    def json():
        return {
            "data": {
                "items": [
                    {
                        "request_id": "client:request-a",
                        "input_tokens": 100,
                        "cache_read_tokens": 40,
                        "output_tokens": 10,
                        "actual_cost": 0.0001,
                        "upstream_model": "gpt-5.6-sol",
                        "api_key_id": 77,
                        "api_key": {"id": 77, "name": "must-not-propagate"},
                    }
                ]
            }
        }


def _token(root: Path) -> Path:
    path = root / "admin-token"
    path.write_text("admin-token-value", encoding="utf-8")
    path.chmod(0o600)
    return path


@patch("openclaw_app.services.stock_usage_reconciliation.requests.get")
def test_reconciler_extracts_only_usage_and_cost(get) -> None:
    get.return_value = _Response()
    with tempfile.TemporaryDirectory() as root:
        result = StockUsageReconciler("https://stock.test", _token(Path(root))).resolve("request-a")
    assert result.request_id == "client:request-a"
    assert result.usage == Usage(100, 40, 10)
    assert str(result.actual_cost) == "0.0001"
    assert set(result.__dict__) == {"request_id", "usage", "actual_cost", "upstream_model"}


def test_reconciler_rejects_non_regular_or_permissive_token_file() -> None:
    with tempfile.TemporaryDirectory() as root:
        base = Path(root)
        token = _token(base)
        token.chmod(0o640)
        with pytest.raises(RetailBillingError):
            StockUsageReconciler("https://stock.test", token).resolve("request-a")

        token.unlink()
        target = base / "target"
        target.write_text("admin-token-value", encoding="utf-8")
        target.chmod(0o600)
        token.symlink_to(target)
        with pytest.raises(RetailBillingError):
            StockUsageReconciler("https://stock.test", token).resolve("request-a")
