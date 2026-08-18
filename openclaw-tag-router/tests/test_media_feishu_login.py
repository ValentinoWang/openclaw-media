from __future__ import annotations

import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from openclaw_app.account import (
    AccountAuthError,
    MEDIA_CALLBACK_PATH,
    MEDIA_LOGIN_SCOPE,
    MEDIA_STATE_PREFIX,
    MediaFeishuLoginService,
    load_media_feishu_identity,
)


class MediaFeishuLoginServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_786_700_000.0
        self.service = MediaFeishuLoginService(
            "cli_media_product_only",
            "media-secret",
            "http://106.52.146.37/openclaw/media/oauth/callback",
            clock=lambda: self.now,
        )

    @staticmethod
    def _response(payload: object) -> MagicMock:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
        return response

    def test_loads_only_media_application_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "openclaw.json"
            path.write_text(
                json.dumps(
                    {
                        "channels": {
                            "feishu": {
                                "accounts": {
                                    "media": {"appId": "cli_media_product_only", "appSecret": "media-secret"},
                                    "company": {"appId": "cli_company_product", "appSecret": "company-secret"},
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_media_feishu_identity(path), ("cli_media_product_only", "media-secret"))

    def test_start_uses_media_app_callback_scope_state_and_pkce(self) -> None:
        started = self.service.start()
        parsed = urlsplit(started.authorization_url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.hostname, "open.feishu.cn")
        self.assertEqual(query["app_id"], ["cli_media_product_only"])
        self.assertEqual(query["redirect_uri"], ["http://106.52.146.37" + MEDIA_CALLBACK_PATH])
        self.assertEqual(query["scope"], [MEDIA_LOGIN_SCOPE])
        self.assertTrue(query["state"][0].startswith(MEDIA_STATE_PREFIX))
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(started.maximum_age, 300)

    @patch("openclaw_app.account.media_feishu_login.urlopen")
    def test_callback_returns_verified_feishu_identity_once_without_email(self, mocked_urlopen: MagicMock) -> None:
        mocked_urlopen.side_effect = (
            self._response({"code": 0, "access_token": "media-access-token"}),
            self._response(
                {
                    "code": 0,
                    "data": {
                        "tenant_key": "tenant-media-a",
                        "open_id": "open-a",
                        "union_id": "union-a",
                        "user_id": "user-a",
                    },
                }
            ),
        )
        started = self.service.start()
        state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]

        identity = self.service.complete_callback(state=state, code="authorization-code")

        self.assertEqual(identity.tenant_key, "tenant-media-a")
        self.assertEqual(identity.open_id, "open-a")
        self.assertEqual(identity.union_id, "union-a")
        self.assertIsNone(identity.email)
        with self.assertRaises(AccountAuthError) as replayed:
            self.service.complete_callback(state=state, code="authorization-code")
        self.assertEqual(replayed.exception.code, "feishu_login_invalid_state")
        token_request = mocked_urlopen.call_args_list[0].args[0]
        token_payload = parse_qs(token_request.data.decode("utf-8"))
        self.assertEqual(token_request.headers["Content-type"], "application/x-www-form-urlencoded")
        self.assertEqual(token_payload["client_id"], ["cli_media_product_only"])
        self.assertEqual(
            token_payload["redirect_uri"],
            ["http://106.52.146.37" + MEDIA_CALLBACK_PATH],
        )
        self.assertTrue(token_payload["code_verifier"][0])

    @patch("openclaw_app.account.media_feishu_login.urlopen")
    def test_callback_accepts_empty_optional_user_fields(self, mocked_urlopen: MagicMock) -> None:
        mocked_urlopen.side_effect = (
            self._response({"code": 0, "access_token": "media-access-token"}),
            self._response(
                {
                    "code": 0,
                    "data": {
                        "tenant_key": "tenant-media-a",
                        "open_id": "open-a",
                        "union_id": "",
                        "user_id": "",
                        "email": "",
                        "enterprise_email": "",
                    },
                }
            ),
        )
        started = self.service.start()
        state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]

        identity = self.service.complete_callback(state=state, code="authorization-code")

        self.assertEqual(identity.tenant_key, "tenant-media-a")
        self.assertEqual(identity.open_id, "open-a")
        self.assertIsNone(identity.union_id)
        self.assertIsNone(identity.user_id)
        self.assertIsNone(identity.email)

    def test_rejects_foreign_state(self) -> None:
        with self.assertRaises(AccountAuthError) as raised:
            self.service.complete_callback(state="c_company_state", code="authorization-code")
        self.assertEqual(raised.exception.code, "feishu_login_invalid_state")

    @patch("openclaw_app.account.media_feishu_login.urlopen")
    def test_token_failure_has_stable_stage_code_and_safe_diagnostic(self, mocked_urlopen: MagicMock) -> None:
        mocked_urlopen.return_value = self._response({"code": 20014, "msg": "provider rejected request"})
        started = self.service.start()
        state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
        diagnostic = io.StringIO()

        with patch("sys.stderr", diagnostic), self.assertRaises(AccountAuthError) as raised:
            self.service.complete_callback(state=state, code="authorization-code-secret")

        self.assertEqual(raised.exception.code, "feishu_token_exchange_failed")
        payload = json.loads(diagnostic.getvalue())
        self.assertEqual(payload["stage"], "token_exchange")
        self.assertEqual(payload["provider_code"], 20014)
        self.assertNotIn("authorization-code-secret", diagnostic.getvalue())

    @patch("openclaw_app.account.media_feishu_login.urlopen")
    def test_user_info_failure_has_stable_stage_code_and_safe_diagnostic(self, mocked_urlopen: MagicMock) -> None:
        mocked_urlopen.side_effect = (
            self._response({"code": 0, "access_token": "media-access-token-secret"}),
            self._response({"code": 99999, "msg": "provider rejected request"}),
        )
        started = self.service.start()
        state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
        diagnostic = io.StringIO()

        with patch("sys.stderr", diagnostic), self.assertRaises(AccountAuthError) as raised:
            self.service.complete_callback(state=state, code="authorization-code-secret")

        self.assertEqual(raised.exception.code, "feishu_user_info_failed")
        payload = json.loads(diagnostic.getvalue())
        self.assertEqual(payload["stage"], "user_info")
        self.assertEqual(payload["provider_code"], 99999)
        self.assertNotIn("authorization-code-secret", diagnostic.getvalue())
        self.assertNotIn("media-access-token-secret", diagnostic.getvalue())

    @patch("openclaw_app.account.media_feishu_login.urlopen")
    def test_malformed_optional_user_field_has_safe_diagnostic(self, mocked_urlopen: MagicMock) -> None:
        mocked_urlopen.side_effect = (
            self._response({"code": 0, "access_token": "media-access-token-secret"}),
            self._response(
                {
                    "code": 0,
                    "data": {
                        "tenant_key": "tenant-media-a",
                        "open_id": "open-a",
                        "email": "not-an-email",
                    },
                }
            ),
        )
        started = self.service.start()
        state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
        diagnostic = io.StringIO()

        with patch("sys.stderr", diagnostic), self.assertRaises(AccountAuthError) as raised:
            self.service.complete_callback(state=state, code="authorization-code-secret")

        self.assertEqual(raised.exception.code, "feishu_user_info_failed")
        payload = json.loads(diagnostic.getvalue())
        self.assertEqual(payload["stage"], "user_info")
        self.assertEqual(payload["reason"], "invalid_email_value")
        self.assertNotIn("not-an-email", diagnostic.getvalue())
        self.assertNotIn("authorization-code-secret", diagnostic.getvalue())
        self.assertNotIn("media-access-token-secret", diagnostic.getvalue())

    def test_callback_path_cannot_point_at_another_product(self) -> None:
        with self.assertRaises(ValueError):
            MediaFeishuLoginService(
                "cli_media_product_only",
                "media-secret",
                "http://106.52.146.37/openclaw/OPC/system/oauth-return/",
            )


if __name__ == "__main__":
    unittest.main()
