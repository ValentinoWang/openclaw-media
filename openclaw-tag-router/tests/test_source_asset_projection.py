from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from openclaw_app.services.media_business.source_asset_projection import (
    AuthenticatedTenantContext,
    SourceAssetProjection,
    SourceAssetProjectionError,
    canonicalize_source_asset,
    normalize_source_identity,
    stable_public_id,
)
from openclaw_app.services.media_business.assets import AssetsService
from openclaw_app.services.resource_owner_registry import ResourceOwnerConflict


TENANT_A = "00000000-0000-0000-0000-00000000000a"
TENANT_B = "00000000-0000-0000-0000-00000000000b"


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self):
        self.row = None
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query, params=()):
        self.calls.append((query, params))
        if query.startswith("SELECT revision"):
            return Result(self.row)
        if query.startswith("SELECT 1 FROM media_product.assets"):
            return Result((1,) if self.row is not None else None)
        if query.startswith("DELETE FROM media_product.assets"):
            row = (params[1],) if self.row is not None else None
            self.row = None
            return Result(row)
        if query.startswith("INSERT INTO"):
            tenant, public_id, source_version, encoded = params
            canonical = json.loads(encoded)
            if self.row is None:
                self.row = (1, source_version, canonical)
            else:
                revision = self.row[0] + (self.row[2] != canonical)
                self.row = (revision, source_version, canonical)
            return Result((self.row[0],))
        if query.startswith("UPDATE") and "canonical_data" in query:
            source_version, encoded, _tenant, _public_id = params
            self.row = (self.row[0] + 1, source_version, json.loads(encoded))
            return Result((self.row[0],))
        if query.startswith("UPDATE"):
            source_version, _tenant, _public_id = params
            self.row = (self.row[0], source_version, self.row[2])
            return Result((self.row[0],))
        raise AssertionError(query)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


@contextmanager
def factory(connection):
    yield connection


def asset(**changes):
    value = {
        "source_identity": "HTTPS://Example.test/source/?b=2&a=1#tracking",
        "title": "Source title",
        "media_type": "video",
        "platform": "xiaohongshu",
        "captured_at": "2026-08-08T00:02:03Z",
        "original_title": "Original source title",
        "source_kind": "source_url",
        "account_ref": "account_xhs_01",
        "track_refs": ("strength_training",),
        "request_constraints": {"language": "zh-CN"},
        "published_at": "2026-08-08T01:02:03Z",
        "attachments": (
            {
                "id": "att-1",
                "name": "cover.jpg",
                "mime_type": "image/jpeg",
                "file_token": "must-not-persist",
                "tmp_url": "https://provider.test/temporary",
            },
        ),
    }
    value.update(changes)
    return value


def test_identity_normalization_and_tenant_binding_are_stable():
    normalized = normalize_source_identity(" HTTPS://Example.test/source/?b=2&a=1#ignored ")
    assert normalized == "https://example.test/source?a=1&b=2"
    assert stable_public_id(TENANT_A, normalized) != stable_public_id(TENANT_B, normalized)
    public_id, canonical, _version = canonicalize_source_asset(asset(), TENANT_A)
    assert public_id == stable_public_id(TENANT_A, canonical["source_identity"])
    assert canonical["published_at"] is None
    assert "file_token" not in json.dumps(canonical)
    assert "tmp_url" not in json.dumps(canonical)
    assert canonical["attachments"] == [
        {"attachment_id": "att-1", "name": "cover.jpg", "media_type": "image/jpeg"}
    ]


def test_tenant_id_can_only_come_from_authenticated_context():
    connection = Connection()
    projector = SourceAssetProjection(lambda: factory(connection))
    with pytest.raises(SourceAssetProjectionError, match="authenticated tenant"):
        projector.project(AuthenticatedTenantContext(""), asset())
    with pytest.raises(SourceAssetProjectionError, match="tenant_id"):
        projector.project(AuthenticatedTenantContext(TENANT_A), {**asset(), "tenant_id": TENANT_B})
    assert connection.calls == []


def test_idempotent_write_does_not_increment_revision_for_equal_canonical_content():
    connection = Connection()
    projector = SourceAssetProjection(lambda: factory(connection))
    first = projector.project(AuthenticatedTenantContext(TENANT_A), asset())
    second = projector.project(AuthenticatedTenantContext(TENANT_A), asset())
    changed = projector.project(AuthenticatedTenantContext(TENANT_A), asset(title="Changed title"))
    assert (first.status, first.revision) == ("inserted", 1)
    assert (second.status, second.revision) == ("unchanged", 1)
    assert (changed.status, changed.revision) == ("updated", 2)
    assert connection.commits == 3


def test_verified_publication_evidence_allows_timestamp():
    _public_id, canonical, _version = canonicalize_source_asset(
        asset(
            evidence=(
                {
                    "kind": "publication",
                    "quality_status": "verified",
                    "public_url": "https://example.test/posts/1",
                },
            )
        ),
        TENANT_A,
    )
    assert canonical["published_at"] == "2026-08-08T01:02:03Z"


def test_canonical_output_is_directly_consumable_by_assets_page():
    public_id, canonical, _version = canonicalize_source_asset(
        asset(
            evidence=(
                {
                    "kind": "source",
                    "label": "Original URL",
                    "quality_status": "verified",
                    "public_url": "https://example.test/source",
                    "captured_at": "2026-08-08T00:02:03Z",
                },
            ),
            canonical_data={"platform_hashtags": ["力量"], "materialStatus": "active"},
        ),
        TENANT_A,
    )

    summary = AssetsService._summary_from_row(
        (public_id, 1, canonical, datetime.now(timezone.utc), datetime.now(timezone.utc), 0)
    )
    refs = AssetsService._evidence_refs(canonical, datetime.now(timezone.utc))

    assert summary["title"] == "Source title"
    assert summary["mediaType"] == "video"
    assert summary["sourceLabel"] == "account_xhs_01"
    assert summary["platformHashtags"] == ["力量"]
    assert summary["trackNames"] == ["strength_training"]
    assert summary["qualityStatus"] == "verified"
    assert summary["materialStatus"] == "active"
    assert refs[0]["capturedAt"] == "2026-08-08T00:02:03Z"
    assert canonical["captured_at"] == "2026-08-08T00:02:03Z"
    assert canonical["original_title"] == "Original source title"
    assert canonical["source_kind"] == "source_url"
    assert canonical["request_constraints"] == {"language": "zh-CN"}


def test_retired_source_asset_tags_fail_closed_without_fallback():
    with pytest.raises(SourceAssetProjectionError, match="canonical_data.tags"):
        canonicalize_source_asset(
            asset(canonical_data={"tags": ["力量"], "platform_hashtags": ["训练"]}),
            TENANT_A,
        )


def test_source_asset_extracts_only_explicit_title_hashtags():
    _public_id, canonical, _version = canonicalize_source_asset(
        asset(
            title="训练计划 #短跑",
            original_title="原始标题",
            canonical_data={
                "标签": ["AI"],
                "主题标签": ["旧字段"],
                "trackNames": ["力量训练"],
            },
        ),
        TENANT_A,
    )
    assert canonical["platform_hashtags"] == ["短跑"]
    assert canonical["trackNames"] == ["strength_training"]
    assert "标签" not in canonical
    assert "主题标签" not in canonical


def test_source_asset_retired_chinese_labels_are_removed_at_canonical_boundary():
    _public_id, canonical, _version = canonicalize_source_asset(
        asset(
            canonical_data={
                "platform_hashtags": ["#训练"],
                "标签": ["旧标签"],
                "主题标签": ["旧主题"],
                "nested": {
                    "tags": ["legacy"],
                    "标签": ["嵌套旧标签"],
                },
            }
        ),
        TENANT_A,
    )

    encoded = json.dumps(canonical, ensure_ascii=False)
    assert canonical["platform_hashtags"] == ["训练"]
    assert '"tags"' not in encoded
    assert "标签" not in encoded
    assert "主题标签" not in encoded


def test_authenticated_tenant_must_be_a_canonical_uuid():
    connection = Connection()
    projector = SourceAssetProjection(lambda: factory(connection))
    with pytest.raises(SourceAssetProjectionError, match="canonical UUID"):
        projector.project(AuthenticatedTenantContext("tenant-a"), asset())
    assert connection.calls == []


def test_attachment_local_paths_and_provider_urls_are_rejected():
    for object_ref in ("/tmp/private-cover.jpg", "https://provider.test/temporary"):
        with pytest.raises(SourceAssetProjectionError, match="MediaVault URI"):
            canonicalize_source_asset(
                asset(attachments=({"id": "att-1", "object_ref": object_ref},)),
                TENANT_A,
            )


def test_owner_is_registered_before_idempotent_database_projection():
    class Owners:
        def __init__(self):
            self.owner = None
            self.assertions = 0

        def create(self, resource_type, resource_id, *, session_tenant_id):
            value = (resource_type, resource_id, session_tenant_id)
            if self.owner is not None:
                raise ResourceOwnerConflict("exists")
            self.owner = value

        def assert_owner(self, resource_type, resource_id, *, session_tenant_id):
            assert self.owner == (resource_type, resource_id, session_tenant_id)
            self.assertions += 1

    connection = Connection()
    owners = Owners()
    projector = SourceAssetProjection(lambda: factory(connection), owner_registry=owners)
    first = projector.project(AuthenticatedTenantContext(TENANT_A), asset())
    second = projector.project(AuthenticatedTenantContext(TENANT_A), asset())

    assert owners.owner == ("media.source_asset", first.public_id, TENANT_A)
    assert owners.assertions == 1
    assert second.status == "unchanged"


def test_delete_removes_postgres_asset_and_reads_back_absence():
    connection = Connection()
    projector = SourceAssetProjection(lambda: factory(connection))
    projected = projector.project(AuthenticatedTenantContext(TENANT_A), asset())

    assert projector.exists(TENANT_A, projected.public_id)
    assert projector.delete(TENANT_A, projected.public_id)
    assert not projector.exists(TENANT_A, projected.public_id)
    assert connection.commits == 2
