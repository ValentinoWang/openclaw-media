from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID

import requests

from common.model_transport_context import bind_model_transport, current_model_transport
from openclaw_app.services.retail_billing import OperationReservation, RetailBillingError, Usage
from openclaw_app.services.tenant_model_transport import (
    TenantModelGateway,
    TenantModelTransportError,
    TenantRequestModelTransport,
)
from openclaw_app.services.upstream_gateway_credentials import UpstreamCredentialError


TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"
OPERATION = UUID("60000000-0000-4000-8000-000000000010")
REQUEST_REF = UUID("60000000-0000-4000-8000-000000000011")


class _Response:
    def __init__(self, status_code: int = 200, request_id: str = "stock-request-1") -> None:
        self.status_code = status_code
        self.headers = {"X-Client-Request-ID": request_id}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            response.headers.update(self.headers)
            raise requests.exceptions.HTTPError(response=response)


class _Billing:
    def __init__(self) -> None:
        self.reservations: list[dict[str, object]] = []
        self.settlements: list[tuple[UUID, Usage, str | None]] = []
        self.releases: list[tuple[UUID, str]] = []
        self.unknown: list[tuple[UUID, str | None]] = []

    def reserve(self, **kwargs):
        self.reservations.append(kwargs)
        return OperationReservation(OPERATION, REQUEST_REF, Decimal("1.00000000"))

    def settle(self, operation_id, *, usage, upstream_request_id, upstream_model):
        self.settlements.append((operation_id, usage, upstream_request_id))
        return Decimal("0.01000000")

    def release(self, operation_id, *, error_code):
        self.releases.append((operation_id, error_code))

    def mark_unknown(self, operation_id, *, upstream_request_id=None):
        self.unknown.append((operation_id, upstream_request_id))

    def task_calls(self, tenant_id, scope):
        return []


class _Credential:
    @staticmethod
    def resolve() -> str:
        return "platform-secret"

    @staticmethod
    def health() -> dict[str, object]:
        return {"provider": "sub2api", "status": "active", "version": 2}


class _RevokedCredential:
    @staticmethod
    def resolve() -> str:
        raise UpstreamCredentialError("active platform credential is unavailable")


class TenantModelTransportTests(TestCase):
    def setUp(self) -> None:
        self.billing = _Billing()

    def _transport(self, tenant_id: str) -> TenantRequestModelTransport:
        return TenantRequestModelTransport(
            tenant_id=tenant_id,
            actor_user_id=USER_A if tenant_id == TENANT_A else USER_B,
            task_id=f"task-{tenant_id}",
            request_root=f"mreq-{tenant_id}",
            api_key="platform-secret",
            base_url="https://sub2api.test",
            billing=self.billing,  # type: ignore[arg-type]
            max_input_tokens=200_000,
            max_output_tokens=2048,
        )

    @patch("openclaw_app.services.tenant_model_transport.requests.post")
    def test_two_tenants_hold_before_using_one_server_credential(self, post) -> None:
        post.side_effect = [_Response(request_id="request-a"), _Response(request_id="request-b")]
        for tenant in (TENANT_A, TENANT_B):
            call = self._transport(tenant).begin_call("/responses")
            response = call.post(
                "/responses",
                json_body={"model": "gpt-5.6-sol", "input": "test", "max_output_tokens": 99999},
                timeout=5,
            )
            call.complete(
                response,
                {
                    "model": "gpt-5.6-sol",
                    "usage": {
                        "input_tokens": 100,
                        "input_tokens_details": {"cached_tokens": 40},
                        "output_tokens": 10,
                    },
                },
            )
        self.assertEqual([item["tenant_id"] for item in self.billing.reservations], [TENANT_A, TENANT_B])
        self.assertEqual([item["actor_user_id"] for item in self.billing.reservations], [USER_A, USER_B])
        self.assertTrue(all(call.kwargs["headers"]["Authorization"] == "Bearer platform-secret" for call in post.call_args_list))
        self.assertTrue(all(call.kwargs["json"]["max_output_tokens"] == 2048 for call in post.call_args_list))
        self.assertEqual(self.billing.settlements[0][1], Usage(100, 40, 10))

    @patch("openclaw_app.services.tenant_model_transport.requests.post")
    def test_timeout_keeps_hold_for_reconciliation(self, post) -> None:
        post.side_effect = requests.exceptions.ReadTimeout("redacted")
        call = self._transport(TENANT_A).begin_call("/responses")
        with self.assertRaises(TenantModelTransportError) as raised:
            call.post("/responses", json_body={"model": "gpt-5.6-sol", "input": "test"}, timeout=5)
        self.assertEqual(raised.exception.code, "model_settlement_unknown")
        self.assertEqual(self.billing.unknown, [(OPERATION, None)])
        self.assertEqual(self.billing.releases, [])

    @patch("openclaw_app.services.tenant_model_transport.requests.post")
    def test_client_rejection_releases_hold(self, post) -> None:
        post.return_value = _Response(status_code=429)
        call = self._transport(TENANT_A).begin_call("/chat/completions")
        with self.assertRaises(TenantModelTransportError) as raised:
            call.post("/chat/completions", json_body={"model": "gpt-5.6-sol", "messages": []}, timeout=5)
        self.assertEqual(raised.exception.code, "model_quota_rejected")
        self.assertEqual(self.billing.releases, [(OPERATION, "model_request_rejected")])

    @patch("openclaw_app.services.tenant_model_transport.requests.post")
    def test_success_without_actual_usage_keeps_hold_for_reconciliation(self, post) -> None:
        post.return_value = _Response()
        call = self._transport(TENANT_A).begin_call("/responses")
        response = call.post(
            "/responses", json_body={"model": "gpt-5.6-sol", "input": "test"}, timeout=5
        )
        call.complete(response, {"model": "gpt-5.6-sol"})
        self.assertEqual(self.billing.unknown, [(OPERATION, "stock-request-1")])
        self.assertEqual(self.billing.settlements, [])

    @patch("openclaw_app.services.tenant_model_transport.requests.post")
    def test_stream_interruption_keeps_hold_for_reconciliation(self, post) -> None:
        post.return_value = _Response(request_id="stream-request")
        call = self._transport(TENANT_A).begin_call("/responses")
        response = call.post(
            "/responses",
            json_body={"model": "gpt-5.6-sol", "input": "test"},
            timeout=5,
            stream=True,
        )
        call.uncertain(response)
        self.assertEqual(self.billing.unknown, [(OPERATION, "stream-request")])
        self.assertEqual(self.billing.releases, [])

    def test_gateway_rejects_retired_numeric_tenant_identity(self) -> None:
        gateway = TenantModelGateway(  # type: ignore[arg-type]
            _Credential(), self.billing, None, sub2api_base_url="https://sub2api.test"
        )
        with self.assertRaises(TenantModelTransportError) as raised:
            gateway.task_calls("101", "task-retired-tenant")
        self.assertEqual(raised.exception.code, "invalid_tenant")

    def test_billing_authorization_status_is_preserved_for_the_http_boundary(self) -> None:
        def reject(**_kwargs):
            raise RetailBillingError("billing_actor_forbidden", "actor is no longer active")

        self.billing.reserve = reject  # type: ignore[method-assign]
        call = self._transport(TENANT_A).begin_call("/responses")
        with self.assertRaises(TenantModelTransportError) as raised:
            call.post(
                "/responses",
                json_body={"model": "gpt-5.6-sol", "input": "test"},
                timeout=5,
            )
        self.assertEqual(raised.exception.code, "billing_actor_forbidden")
        self.assertEqual(raised.exception.status, 403)

    def test_revoked_credential_fails_before_creating_hold(self) -> None:
        gateway = TenantModelGateway(  # type: ignore[arg-type]
            _RevokedCredential(), self.billing, None, sub2api_base_url="https://sub2api.test"
        )
        with self.assertRaises(UpstreamCredentialError):
            with gateway.bind(TENANT_A, USER_A, "task-a", "request-root-a"):
                self.fail("revoked credential must not bind a model transport")
        self.assertEqual(self.billing.reservations, [])

    def test_required_media_scope_has_no_static_provider_fallback(self) -> None:
        with bind_model_transport(None, required=True):
            with self.assertRaisesRegex(RuntimeError, "tenant model transport is unavailable"):
                current_model_transport()
