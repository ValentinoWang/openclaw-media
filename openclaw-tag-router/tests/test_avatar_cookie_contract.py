from __future__ import annotations

from datetime import datetime, timezone

import pytest

from openclaw_app.services.media_business.tracks import TracksService
from openclaw_app.services.tenant_projection import TenantProjectionError, TenantProjectionService
from openclaw_app.router.creator_profile_router import CreatorProfilesMixin
from selfmedia.creator_profiles.candidate_builder import build_candidate
from selfmedia.creator_profiles.extractor import (
    parse_douyin_embedded_profile_data,
    parse_xiaohongshu_embedded_profile_data,
    merge_profile_facts,
)


AVATAR_URL = "https://cdn.example.test/avatar/profile.jpg"
CREATED = datetime(2026, 8, 8, 1, 2, 3, tzinfo=timezone.utc)
UPDATED = datetime(2026, 8, 8, 2, 2, 3, tzinfo=timezone.utc)


def test_douyin_embedded_avatar300_url_is_normalized_to_avatar_url() -> None:
    html = r'{"uniqueId":"douyin-avatar-123","nickname":"头像测试","avatar300Url":"https:\/\/cdn.example.test\/avatar\/profile.jpg"}'

    profile = parse_douyin_embedded_profile_data(html, "douyin-avatar-123")

    assert profile["avatar_url"] == AVATAR_URL


def test_xiaohongshu_escaped_imageb_is_normalized_to_avatar_url() -> None:
    text = r'{"nickname":"小红书头像测试","imageb":"https:\/\/cdn.example.test\/avatar\/profile.jpg"}'

    profile = parse_xiaohongshu_embedded_profile_data(text)

    assert profile["avatar_url"] == AVATAR_URL


def test_candidate_payload_carries_avatar_url_and_empty_backfill_does_not_overwrite() -> None:
    resolver_result = {
        "platform": "抖音",
        "resolved_author_id": "douyin-avatar-123",
        "resolved_profile_url": "https://www.douyin.com/user/douyin-avatar-123",
        "extracted_profile": {
            "author_id": "douyin-avatar-123",
            "account_name": "头像测试",
            "avatar_url": AVATAR_URL,
        },
    }

    candidate = build_candidate(
        run_id="20260808T010203Z",
        resolver_result=resolver_result,
        evidence_uri="media://creator_profiles/douyin/douyin-avatar-123/run",
        use_llm=False,
    )
    assert candidate["candidate_payload"]["avatar_url"] == AVATAR_URL

    merged = merge_profile_facts(
        {"avatar_url": AVATAR_URL},
        {"avatar_url": ""},
    )
    assert merged["avatar_url"] == AVATAR_URL


def test_feishu_avatar_link_projects_to_canonical_avatar_url() -> None:
    projected = CreatorProfilesMixin()._creator_profile_v2_payload(
        {
            "平台": "抖音",
            "平台ID": "douyin-avatar-123",
            "账号名称": "头像测试",
            "头像链接": AVATAR_URL,
        }
    )

    assert projected["avatar_url"] == AVATAR_URL


def test_tracks_service_projects_avatar_url_as_avatarUrl() -> None:
    row = (
        "creator_123456",
        2,
        {
            "account_name": "头像测试",
            "platform": "抖音",
            "creator_role": "external_creator",
            "identity_tags": [],
            "expertise_domains": [],
            "profile_url": "https://www.douyin.com/user/douyin-avatar-123",
            "avatar_url": AVATAR_URL,
        },
        CREATED,
        UPDATED,
    )

    projected = TracksService._creator_row(row)

    assert projected["avatarUrl"] == AVATAR_URL


def test_public_projection_rejects_cookie_and_does_not_backfill_sensitive_values() -> None:
    payload = {"avatarUrl": AVATAR_URL, "cookie": "session=must-not-project"}

    with pytest.raises(TenantProjectionError, match="禁止字段"):
        TenantProjectionService._assert_public_payload(payload)

    assert payload["avatarUrl"] == AVATAR_URL
    assert payload["cookie"] == "session=must-not-project"
