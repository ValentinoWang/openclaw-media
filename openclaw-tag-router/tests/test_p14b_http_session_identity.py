from __future__ import annotations

import logging
import re
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from http import HTTPStatus
from uuid import UUID

from openclaw_app.account import AccountSession
from openclaw_app.adapters.http_api import AuthConfig, OpenClawHttpHandler


class _SessionAuth:
    def __init__(self, session: AccountSession) -> None:
        self.session = session

    def resolve_session(self, token: str | None) -> AccountSession | None:
        return self.session if token == "session-token" else None


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _session() -> AccountSession:
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    tenant_id = UUID("00000000-0000-4000-8000-000000000101")

    return AccountSession(
        user_id,
        user_id,
        tenant_id,
        "user-101",
        None,
        "user",
        datetime.now(timezone.utc) + timedelta(hours=1),
    )


class P14BHttpSessionIdentityTests(unittest.TestCase):
    def test_asset_context_uses_account_session_user_id(self) -> None:
        handler = object.__new__(OpenClawHttpHandler)
        handler.auth_config = AuthConfig(session_secret=b"s" * 48, cookie_secure=False)
        handler.account_auth = _SessionAuth(_session())
        handler.headers = Message()
        handler.headers["Cookie"] = "openclaw_session=session-token"

        context = handler._asset_context()

        self.assertIsNotNone(context)
        self.assertEqual(context.tenant_id, "00000000-0000-4000-8000-000000000101")
        self.assertEqual(context.user_public_id, "11111111-1111-4111-8111-111111111111")

    def test_internal_error_keeps_masking_and_logs_safe_correlation_id(self) -> None:
        handler = object.__new__(OpenClawHttpHandler)
        handler.path = "/media/api/assets/asset_123456/preview?token=must-not-log"
        handler._request_path = lambda: "/media/api/assets/asset_123456/preview"
        handler._do_GET = lambda: (_ for _ in ()).throw(RuntimeError("private failure"))
        sent: dict[str, object] = {}
        handler._send_json = lambda status, payload, *, headers=None: sent.update(
            status=status,
            payload=payload,
            headers=headers or {},
        )
        logger = logging.getLogger("openclaw_app.adapters.http_api")
        capture = _CaptureHandler()
        logger.addHandler(capture)
        try:
            handler.do_GET()
        finally:
            logger.removeHandler(capture)

        self.assertEqual(sent["status"], HTTPStatus.INTERNAL_SERVER_ERROR)
        self.assertEqual(sent["payload"]["error"]["code"], "internal_error")
        request_id = sent["headers"]["X-Request-ID"]
        self.assertIsInstance(request_id, str)
        self.assertRegex(request_id, re.compile(r"^[0-9a-f]{32}$"))
        self.assertEqual(len(capture.records), 1)
        record = capture.records[0]
        self.assertEqual(record.request_id, request_id)
        self.assertEqual(record.path, "/media/api/assets/asset_123456/preview")
        self.assertNotIn("must-not-log", record.path)


if __name__ == "__main__":
    unittest.main()
