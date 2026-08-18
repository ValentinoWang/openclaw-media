from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from openclaw_app.account import AccountSession
from openclaw_app.adapters.http_api import AuthConfig, HttpAuthorityConfig, make_server
from openclaw_app.services.media_business.assets import AssetInternalError, AssetNotFound, AssetPreview
from openclaw_app.services.tenant_projection import (
    ProjectionRead,
    RunOwnerFact,
    RunSummaryPage,
    TenantProjectionService,
)

TENANT_USER = "00000000-0000-4000-8000-000000000101"
TENANT_OTHER = "00000000-0000-4000-8000-000000000202"


class _AccountAuth:
    def __init__(self) -> None:
        self.sessions = {
            "opaque-user-session-token": self._session(
                "11111111-1111-4111-8111-111111111111", "101", "user"
            ),
            "opaque-admin-session-token": self._session(
                "77777777-7777-4777-8777-777777777777", "7", "admin"
            ),
        }

    @staticmethod
    def _session(user_id: str, tenant_suffix: str, role: str) -> AccountSession:
        tenant_id = UUID(f"00000000-0000-4000-8000-{int(tenant_suffix):012d}")
        return AccountSession(
            UUID(user_id), UUID(user_id), tenant_id, f"user-{tenant_suffix}", None, role,
            datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def resolve_session(self, token: str | None) -> AccountSession | None:
        return self.sessions.get(token or "")

    @staticmethod
    def csrf_token(token: str) -> str:
        return f"csrf-{token}"

    @staticmethod
    def verify_csrf(token: str, supplied: str) -> bool:
        return supplied == f"csrf-{token}"


class _Owner:
    def resolve_run_owner(self, public_run_id: str) -> RunOwnerFact | None:
        return {
            "run_a": RunOwnerFact(TENANT_USER, "rev-a"),
            "run_b": RunOwnerFact(TENANT_OTHER, "rev-b"),
        }.get(public_run_id)


class _Reader:
    def dashboard_summary(self, tenant_id: str) -> ProjectionRead:
        return ProjectionRead({"label": f"dashboard-{tenant_id}"}, f"dash-{tenant_id}", 1)

    def list_run_summaries(self, tenant_id: str, *, cursor, page_size: int, search: str) -> RunSummaryPage:
        return RunSummaryPage(
            ({"publicRunId": "run_a" if tenant_id == TENANT_USER else "run_b", "title": tenant_id, "status": "ready"},),
            None,
            f"runs-{tenant_id}",
            1,
        )

    def run_base_detail(self, tenant_id: str, public_run_id: str) -> ProjectionRead:
        revision = "rev-a" if tenant_id == TENANT_USER else "rev-b"
        return ProjectionRead({"title": f"{tenant_id}:{public_run_id}"}, revision, 1)

    def run_section(self, tenant_id: str, public_run_id: str, section: str) -> ProjectionRead:
        revision = "rev-a" if tenant_id == TENANT_USER else "rev-b"
        return ProjectionRead({"items": [f"{tenant_id}:{section}"]}, revision, 1)


class _Assets:
    def __init__(self) -> None:
        self.contexts: list[str] = []

    def list_assets(self, context, *, cursor, page_size: int, search):
        self.contexts.append(context.tenant_id)
        if context.tenant_id != TENANT_USER:
            raise AssetNotFound()
        return {
            "schemaVersion": "media_web_business_pages_v2",
            "revision": 1,
            "items": [{"publicAssetId": "asset_123456", "thumbnail": {"status": "available", "url": "/openclaw/media/api/assets/asset_123456/preview"}}],
            "nextCursor": None,
        }

    def get_asset(self, context, public_asset_id: str):
        self.contexts.append(context.tenant_id)
        if context.tenant_id != TENANT_USER or public_asset_id != "asset_123456":
            raise AssetNotFound()
        return {
            "schemaVersion": "media_web_business_pages_v2",
            "revision": 1,
            "item": {"previewDescriptor": {"status": "available", "url": "/openclaw/media/api/assets/asset_123456/preview"}},
        }


class _AssetPreviews:
    def __init__(self) -> None:
        self.contexts: list[str] = []

    def get_preview(self, context, public_asset_id: str) -> AssetPreview:
        self.contexts.append(context.tenant_id)
        if context.tenant_id != TENANT_USER:
            raise AssetNotFound()
        if public_asset_id == "asset_fail":
            raise AssetInternalError("asset preview is unavailable")
        if public_asset_id != "asset_123456":
            raise AssetNotFound()
        return AssetPreview(body=b"image-bytes", content_type="image/jpeg", filename="cover.jpg")


class TenantProjectionHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.config = AuthConfig(
            session_secret=b"s" * 48,
            cookie_secure=False,
        )
        self.account_auth = _AccountAuth()
        self.user_cookie = f"{self.config.cookie_name}=opaque-user-session-token"
        self.admin_cookie = f"{self.config.cookie_name}=opaque-admin-session-token"
        self.assets = _Assets()
        self.previews = _AssetPreviews()
        projections = TenantProjectionService(_Reader(), _Owner())
        self.server = make_server(
            "127.0.0.1",
            0,
            None,
            auth_config=self.config,
            account_auth=self.account_auth,  # type: ignore[arg-type]
            tenant_projection_service=projections,
            assets_service=self.assets,  # type: ignore[arg-type]
            asset_preview_service=self.previews,  # type: ignore[arg-type]
            authority_config=HttpAuthorityConfig("http://127.0.0.1"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.temporary.cleanup()

    def _get(self, path: str, *, cookie: str = "", headers: dict[str, str] | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        request_headers = dict(headers or {})
        if cookie:
            request_headers["Cookie"] = cookie
        connection.request("GET", path, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = {name.lower(): value for name, value in response.getheaders()}
        connection.close()
        return response.status, json.loads(raw) if raw else None, response_headers

    def _get_raw(self, path: str, *, cookie: str = ""):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.request("GET", path, headers={"Cookie": cookie} if cookie else {})
        response = connection.getresponse()
        raw = response.read()
        response_headers = {name.lower(): value for name, value in response.getheaders()}
        connection.close()
        return response.status, raw, response_headers

    def test_all_projection_routes_require_authentication_and_old_full_route_is_gone(self) -> None:
        for path in (
            "/media/api/dashboard",
            "/media/api/runs",
            "/media/api/runs/run_a",
            "/media/api/runs/run_a/sources",
        ):
            status, body, _ = self._get(path)
            self.assertEqual(status, 401, (path, body))
        status, body, _ = self._get("/media/api/creation-runs/run_a", cookie=self.user_cookie)
        self.assertEqual(status, 404, body)

    def test_normal_user_is_always_scoped_to_session_tenant(self) -> None:
        status, body, _ = self._get(f"/media/api/dashboard?targetTenantId={TENANT_OTHER}", cookie=self.user_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["summary"]["label"], f"dashboard-{TENANT_USER}")

        status, body, _ = self._get("/media/api/runs?pageSize=10&search=x", cookie=self.user_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["items"][0]["publicRunId"], "run_a")

        status, body, _ = self._get("/media/api/runs/run_b", cookie=self.user_cookie)
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "resource_not_found")

    def test_assets_list_detail_and_preview_are_one_authenticated_runtime_path(self) -> None:
        status, body, _ = self._get("/media/api/assets?search=cover", cookie=self.user_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["items"][0]["thumbnail"]["url"], "/openclaw/media/api/assets/asset_123456/preview")

        status, body, _ = self._get("/media/api/assets/asset_123456", cookie=self.user_cookie)
        self.assertEqual(status, 200, body)
        self.assertNotIn("file_token", json.dumps(body))

        status, raw, headers = self._get_raw("/openclaw/media/api/assets/asset_123456/preview", cookie=self.user_cookie)
        self.assertEqual(status, 200, raw)
        self.assertEqual(raw, b"image-bytes")
        self.assertEqual(headers["content-type"], "image/jpeg")
        self.assertEqual(headers["content-length"], str(len(raw)))
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(self.assets.contexts, [TENANT_USER, TENANT_USER])
        self.assertEqual(self.previews.contexts, [TENANT_USER])

    def test_asset_preview_masks_cross_tenant_and_fails_closed(self) -> None:
        status, raw, _ = self._get_raw("/media/api/assets/asset_123456/preview", cookie=self.admin_cookie)
        self.assertEqual(status, 404, raw)
        self.assertNotIn(b"file_token", raw)

        status, raw, _ = self._get_raw("/media/api/assets/asset_fail/preview", cookie=self.user_cookie)
        self.assertEqual(status, 500, raw)
        self.assertNotIn(b"file_token", raw)

    def test_admin_requires_live_admin_role_and_explicit_target_tenant(self) -> None:
        status, body, _ = self._get(f"/media/api/admin/runs?targetTenantId={TENANT_OTHER}", cookie=self.user_cookie)
        self.assertEqual(status, 403, body)

        status, body, _ = self._get("/media/api/admin/runs", cookie=self.admin_cookie)
        self.assertEqual(status, 400, body)
        self.assertEqual(body["error"]["code"], "target_tenant_required")

        status, body, _ = self._get(f"/media/api/admin/runs?targetTenantId={TENANT_OTHER}", cookie=self.admin_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["items"][0]["publicRunId"], "run_b")

    def test_base_and_section_etags_and_instrumentation_are_separate(self) -> None:
        status, body, headers = self._get("/media/api/runs/run_a", cookie=self.user_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(headers["x-openclaw-projection-queries"], "2")
        self.assertLessEqual(int(headers["x-openclaw-projection-gzip-bytes"]), 100 * 1024)

        status, body, section_headers = self._get(
            "/media/api/runs/run_a/sources",
            cookie=self.user_cookie,
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["section"], "sources")
        self.assertLessEqual(int(section_headers["x-openclaw-projection-queries"]), 3)

        status, body, cached_headers = self._get(
            "/media/api/runs/run_a/sources",
            cookie=self.user_cookie,
            headers={"If-None-Match": section_headers["etag"]},
        )
        self.assertEqual(status, 304, body)
        self.assertEqual(cached_headers["x-openclaw-projection-cache"], "HIT")
