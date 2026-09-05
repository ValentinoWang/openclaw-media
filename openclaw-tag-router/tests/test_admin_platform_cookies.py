from __future__ import annotations

from openclaw_app.services.media_business.admin_platform_cookies import (
    AdminPlatformCookiesService,
)


def test_platform_cookie_status_is_redacted_and_reports_validation(tmp_path):
    cookie_path = tmp_path / "douyin-cookies.json"
    cookie_path.write_text('{"cookies":[{"name":"sid","value":"COOKIE-PLAINTEXT"}]}')

    service = AdminPlatformCookiesService(
        loader=lambda platform: (
            [{"name": "sid", "value": "COOKIE-PLAINTEXT"}]
            if platform == "douyin"
            else []
        ),
        candidate_paths=lambda platform: [cookie_path] if platform == "douyin" else [],
    )

    response = service.get_admin_platform_cookies()
    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["platforms"][0]["validationStatus"] == "valid"
    assert response["platforms"][0]["configured"] is True
    assert response["platforms"][1]["validationStatus"] == "missing"
    assert all(set(item) == {"platform", "configured", "updatedAt", "validationStatus", "errorCode"} for item in response["platforms"])
    assert "COOKIE-PLAINTEXT" not in repr(response)
    assert "value" not in repr(response).lower()


def test_platform_cookie_status_distinguishes_invalid_file(tmp_path):
    cookie_path = tmp_path / "xiaohongshu-cookies.json"
    cookie_path.write_text("not-json")

    service = AdminPlatformCookiesService(
        loader=lambda platform: [],
        candidate_paths=lambda platform: [cookie_path] if platform == "xiaohongshu" else [],
    )

    item = service.get_admin_platform_cookies()["platforms"][1]
    assert item["configured"] is True
    assert item["validationStatus"] == "invalid"
    assert item["errorCode"] == "cookie_invalid"
