from __future__ import annotations

import stat
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import requests

from .retail_billing import RetailBillingError, Usage


@dataclass(frozen=True)
class ReconciledUsage:
    request_id: str
    usage: Usage
    actual_cost: Decimal
    upstream_model: str | None


class StockUsageReconciler:
    def __init__(self, base_url: str, admin_token_file: str | Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token_file = Path(admin_token_file)

    def resolve(self, request_id: str) -> ReconciledUsage:
        canonical_request_id = request_id if request_id.startswith("client:") else f"client:{request_id}"
        token = self._admin_token()
        try:
            response = requests.get(
                self.base_url + "/api/v1/admin/usage",
                params={"request_id": canonical_request_id},
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.exceptions.RequestException, ValueError) as exc:
            raise RetailBillingError("usage_reconciliation_pending", "上游用量暂不可读。") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        items = data.get("items") if isinstance(data, dict) else None
        matches = [item for item in items or [] if isinstance(item, dict) and item.get("request_id") == canonical_request_id]
        if len(matches) != 1:
            raise RetailBillingError("usage_reconciliation_pending", "上游用量尚未形成唯一记录。")
        item = matches[0]
        values = (item.get("input_tokens"), item.get("cache_read_tokens", 0), item.get("output_tokens"))
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise RetailBillingError("usage_reconciliation_pending", "上游用量记录无效。")
        if values[1] > values[0]:
            raise RetailBillingError("usage_reconciliation_pending", "上游缓存用量记录无效。")
        try:
            actual_cost = Decimal(str(item.get("actual_cost")))
        except Exception as exc:
            raise RetailBillingError("usage_reconciliation_pending", "上游成本记录无效。") from exc
        if actual_cost < 0:
            raise RetailBillingError("usage_reconciliation_pending", "上游成本记录无效。")
        model = str(item.get("upstream_model") or item.get("model") or "").strip() or None
        return ReconciledUsage(
            canonical_request_id,
            Usage(values[0], values[1], values[2]),
            actual_cost,
            model,
        )

    def _admin_token(self) -> str:
        try:
            metadata = self.admin_token_file.lstat()
        except FileNotFoundError as exc:
            raise RetailBillingError("usage_reconciliation_pending", "上游对账凭据不可用。") from exc
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RetailBillingError("usage_reconciliation_pending", "上游对账凭据不可用。")
        token = self.admin_token_file.read_text(encoding="utf-8")
        if not token or token != token.strip() or "\n" in token or "\r" in token:
            raise RetailBillingError("usage_reconciliation_pending", "上游对账凭据不可用。")
        return token
