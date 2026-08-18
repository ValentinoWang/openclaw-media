from __future__ import annotations

import hashlib
import json
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import requests

from common.model_transport_context import ModelTransportError, bind_model_transport

from .retail_billing import RetailBillingError, RetailBillingService, parse_usage
from .stock_usage_reconciliation import StockUsageReconciler
from .upstream_gateway_credentials import PlatformCredentialService


class TenantModelTransportError(ModelTransportError):
    pass


def _canonical_tenant_id(value: str) -> str:
    try:
        tenant_id = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise TenantModelTransportError("invalid_tenant", "租户身份无效。") from exc
    if tenant_id != value:
        raise TenantModelTransportError("invalid_tenant", "租户身份无效。")
    return tenant_id


class _TenantModelCall:
    def __init__(self, transport: "TenantRequestModelTransport", endpoint: str, request_id: str) -> None:
        self._transport = transport
        self.endpoint = endpoint
        self.request_id = request_id
        self._terminal = False
        self._response: requests.Response | None = None
        self._operation_id: uuid.UUID | None = None

    def post(
        self,
        endpoint: str,
        *,
        json_body: dict[str, Any],
        timeout: Any,
        stream: bool = False,
    ) -> requests.Response:
        if endpoint != self.endpoint or self._terminal or self._operation_id is not None:
            raise TenantModelTransportError("model_call_state_conflict", "模型调用状态冲突。")
        bounded_body = dict(json_body)
        token_field = "max_output_tokens" if endpoint == "/responses" else "max_tokens"
        requested_limit = bounded_body.get(token_field)
        if not isinstance(requested_limit, int) or isinstance(requested_limit, bool) or requested_limit <= 0:
            bounded_body[token_field] = self._transport.max_output_tokens
        else:
            bounded_body[token_field] = min(requested_limit, self._transport.max_output_tokens)
        model = bounded_body.get("model")
        if not isinstance(model, str) or not model.strip():
            raise TenantModelTransportError("model_request_rejected", "模型名称无效。")
        fingerprint = hashlib.sha256(
            json.dumps(
                {"endpoint": endpoint, "body": bounded_body},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        try:
            reservation = self._transport.billing.reserve(
                tenant_id=self._transport.tenant_id,
                scope=self._transport.task_id,
                idempotency_key=self.request_id,
                request_fingerprint=fingerprint,
                model=model.strip(),
                correlation_key=self.request_id,
                max_input_tokens=self._transport.max_input_tokens,
                max_output_tokens=int(bounded_body[token_field]),
            )
        except RetailBillingError as exc:
            raise TenantModelTransportError(exc.code, exc.detail) from exc
        self._operation_id = reservation.operation_id
        try:
            response = requests.post(
                self._transport.base_url + endpoint,
                headers={
                    "Authorization": f"Bearer {self._transport.api_key}",
                    "Content-Type": "application/json",
                    "X-Client-Request-ID": self.request_id,
                    "X-Request-ID": self.request_id,
                },
                json=bounded_body,
                timeout=timeout,
                stream=stream,
            )
            self._response = response
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as exc:
            response = exc.response
            status = int(response.status_code) if response is not None else 0
            if status and status < 500:
                self._release("model_request_rejected")
                code = "model_quota_rejected" if self._is_quota_rejection(response) else "model_request_rejected"
                raise TenantModelTransportError(code, "模型网关拒绝了本次请求。") from exc
            self._mark_unknown(response)
            raise TenantModelTransportError("model_settlement_unknown", "模型调用结果需要对账。") from exc
        except requests.exceptions.RequestException as exc:
            self._mark_unknown(self._response)
            raise TenantModelTransportError("model_settlement_unknown", "模型调用结果需要对账。") from exc

    @staticmethod
    def _is_quota_rejection(response: requests.Response | None) -> bool:
        if response is None:
            return False
        if int(response.status_code) in {402, 429}:
            return True
        try:
            payload = response.json()
        except (ValueError, requests.exceptions.RequestException):
            return False
        error = payload.get("error") if isinstance(payload, dict) else None
        values = error.values() if isinstance(error, dict) else ()
        return any(str(value).strip().lower() == "billing_error" for value in values)

    def complete(self, response: requests.Response, payload: dict[str, Any] | None = None) -> None:
        if self._terminal or self._operation_id is None:
            raise TenantModelTransportError("model_call_state_conflict", "模型调用状态冲突。")
        try:
            usage = parse_usage(payload)
            self._transport.billing.settle(
                self._operation_id,
                usage=usage,
                upstream_request_id=self._upstream_request_id(response),
                upstream_model=str((payload or {}).get("model") or "").strip() or None,
            )
        except RetailBillingError as exc:
            if exc.code in {"invalid_usage", "usage_reconciliation_pending"}:
                self._mark_unknown(response)
                return
            raise TenantModelTransportError(exc.code, exc.detail) from exc
        self._terminal = True

    def uncertain(self, response: requests.Response | None = None) -> None:
        if not self._terminal:
            self._mark_unknown(response or self._response)

    def _release(self, error_code: str) -> None:
        if self._operation_id is None or self._terminal:
            raise TenantModelTransportError("model_call_state_conflict", "模型调用状态冲突。")
        try:
            self._transport.billing.release(self._operation_id, error_code=error_code)
        except RetailBillingError as exc:
            raise TenantModelTransportError(exc.code, exc.detail) from exc
        self._terminal = True

    def _mark_unknown(self, response: requests.Response | None) -> None:
        if self._operation_id is None or self._terminal:
            raise TenantModelTransportError("model_call_state_conflict", "模型调用状态冲突。")
        try:
            self._transport.billing.mark_unknown(
                self._operation_id,
                upstream_request_id=self._upstream_request_id(response),
            )
        except RetailBillingError as exc:
            raise TenantModelTransportError(exc.code, exc.detail) from exc
        self._terminal = True

    @staticmethod
    def _upstream_request_id(response: requests.Response | None) -> str | None:
        if response is None:
            return None
        value = str(
            response.headers.get("X-Client-Request-ID")
            or response.headers.get("X-Request-ID")
            or ""
        ).strip()
        return value or None


class TenantRequestModelTransport:
    def __init__(
        self,
        *,
        tenant_id: str,
        task_id: str,
        request_root: str,
        api_key: str,
        base_url: str,
        billing: RetailBillingService,
        max_input_tokens: int,
        max_output_tokens: int,
    ) -> None:
        self.tenant_id = _canonical_tenant_id(tenant_id)
        self.task_id = task_id
        self.request_root = request_root
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") + "/v1"
        self.billing = billing
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self._counter = 0
        self._counter_lock = threading.Lock()

    def begin_call(self, endpoint: str) -> _TenantModelCall:
        if endpoint not in {"/chat/completions", "/responses"}:
            raise TenantModelTransportError("model_endpoint_rejected", "模型接口不在允许范围内。")
        with self._counter_lock:
            self._counter += 1
            call_index = self._counter
        digest = hashlib.sha256(f"{self.request_root}:{call_index}".encode("ascii")).hexdigest()[:32]
        return _TenantModelCall(self, endpoint, f"ocm_{digest}")


class TenantModelGateway:
    def __init__(
        self,
        credential_service: PlatformCredentialService,
        billing: RetailBillingService,
        usage_reconciler: StockUsageReconciler,
        *,
        sub2api_base_url: str,
        max_input_tokens: int = 200_000,
        max_output_tokens: int = 8192,
    ) -> None:
        self.credential_service = credential_service
        self.billing = billing
        self.usage_reconciler = usage_reconciler
        self.sub2api_base_url = sub2api_base_url.rstrip("/")
        if not 1 <= max_input_tokens <= 2_000_000:
            raise ValueError("tenant model max input tokens must be between 1 and 2000000")
        if not 1 <= max_output_tokens <= 32768:
            raise ValueError("tenant model max output tokens must be between 1 and 32768")
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens

    def prepare(self) -> None:
        self.credential_service.health()

    def credential_health(self) -> dict[str, object]:
        return self.credential_service.health()

    def rotate_credential(self) -> dict[str, object]:
        credential = self.credential_service.rotate_from_staged(self._credential_healthcheck)
        return {"provider": credential.provider, "status": credential.status, "version": credential.version}

    def revoke_credential(self) -> dict[str, object]:
        credential = self.credential_service.revoke()
        return {"provider": credential.provider, "status": credential.status, "version": credential.version}

    def _credential_healthcheck(self, api_key: str) -> bool:
        try:
            response = requests.get(
                self.sub2api_base_url + "/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException:
            return False
        return True

    def task_calls(self, tenant_id: str, task_id: str) -> list[dict[str, Any]]:
        return self.billing.task_calls(_canonical_tenant_id(tenant_id), task_id)

    def balance(self, tenant_id: str) -> dict[str, str]:
        return self.billing.balance(_canonical_tenant_id(tenant_id))

    def usage(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.billing.usage(_canonical_tenant_id(tenant_id), limit=limit)

    def reconciliation_queue(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.billing.reconciliation_queue(limit=limit)

    def reconcile_operation(self, operation_id: str) -> dict[str, Any]:
        operation, request_id = self.billing.reconciliation_target(operation_id)
        reconciled = self.usage_reconciler.resolve(request_id)
        charge = self.billing.settle(
            operation,
            usage=reconciled.usage,
            upstream_request_id=reconciled.request_id,
            upstream_model=reconciled.upstream_model,
            actual_cost=reconciled.actual_cost,
        )
        return {
            "operationId": str(operation),
            "status": "succeeded",
            "charge": str(charge),
        }

    @contextmanager
    def bind(self, tenant_id: str, task_id: str, request_root: str) -> Iterator[None]:
        transport = TenantRequestModelTransport(
            tenant_id=_canonical_tenant_id(tenant_id),
            task_id=task_id,
            request_root=request_root,
            api_key=self.credential_service.resolve(),
            base_url=self.sub2api_base_url,
            billing=self.billing,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=self.max_output_tokens,
        )
        with bind_model_transport(transport, required=True):
            yield
