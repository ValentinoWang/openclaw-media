from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.reconcile_media_vault_assets import (
    OperatorScope,
    ReconciliationError,
    discover_candidates,
    repair_sidecar_sizes,
    reconcile,
)
from openclaw_app.services.resource_owner_registry import ResourceOwnerConflict


TENANT = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "media_vault"
    tenant_root = root / "tenants" / TENANT
    (tenant_root / "manifest").mkdir(parents=True)
    (tenant_root / "manifest" / "media_vault_manifest.json").write_text(
        json.dumps(
            {
                "version": "media_vault_v2",
                "tenant_id": TENANT,
                "root": str(tenant_root),
            }
        ),
        encoding="utf-8",
    )
    return root


def _source(root: Path, asset_id: str = "asset_demo_123", **fields: object) -> Path:
    tenant_root = root / "tenants" / TENANT
    path = tenant_root / "source_assets" / "douyin" / asset_id / "manifest.json"
    path.parent.mkdir(parents=True)
    payload = {"asset_id": asset_id, **fields}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    uri = "media://tenants/" + TENANT + "/" + "/".join(path.relative_to(tenant_root).parts)
    path.with_name("manifest.json.manifest.json").write_text(
        json.dumps(
            {
                "artifact_id": "artifact_demo_123",
                "artifact_type": "source_asset_manifest",
                "content_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "owner_id": asset_id,
                "owner_type": "SourceAsset",
                "size_bytes": len(raw),
                "tenant_id": TENANT,
                "uri": uri,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_discovery_projects_only_manifest_evidence(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    path = _source(
        root,
        title="Observed title",
        platform="抖音",
        source_url="https://example.test/source",
        invented_status="should not enter the projection",
    )

    candidates, errors = discover_candidates(root, TENANT)

    assert not errors
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.path == str(path)
    assert candidate.canonical_data["title"] == "Observed title"
    assert candidate.canonical_data["fields"]["platform"] == "抖音"
    assert "invented_status" not in candidate.canonical_data
    assert candidate.canonical_data["source"]["content_hash"].startswith("sha256:")


def test_discovery_rejects_unverified_sidecar_without_projecting(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    path = _source(root, title="Observed title")
    sidecar = json.loads(path.with_name("manifest.json.manifest.json").read_text())
    sidecar["content_hash"] = "sha256:" + ("0" * 64)
    path.with_name("manifest.json.manifest.json").write_text(json.dumps(sidecar))

    candidates, errors = discover_candidates(root, TENANT)

    assert candidates == []
    assert errors and "content hash" in errors[0]["error"]


def test_admin_scope_requires_reason_and_tenant_scope_is_explicit() -> None:
    with pytest.raises(ReconciliationError, match="audit_reason"):
        OperatorScope("admin", "admin").validate()
    OperatorScope("operator", "tenant").validate()


class _Result:
    def __init__(self, row: object | None) -> None:
        self.row = row

    def fetchone(self) -> object | None:
        return self.row


class _Connection:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict[str, object]]] = {}
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> _Result:
        if "tenant_members" in query:
            return _Result((1,))
        if "FROM media_product.assets" in query:
            return _Result(self.rows.get(str(params[1])))
        if query.startswith("INSERT INTO media_product.assets"):
            _tenant, public_id, source_version, payload = params
            self.rows[str(public_id)] = (str(source_version), json.loads(str(payload)))
            return _Result(None)
        if query.startswith("UPDATE media_product.assets"):
            if "canonical_data" not in query:
                source_version, _tenant, public_id = params
                current = self.rows[str(public_id)]
                self.rows[str(public_id)] = (str(source_version), current[1])
                return _Result(None)
            source_version, payload, _tenant, public_id = params
            self.rows[str(public_id)] = (str(source_version), json.loads(str(payload)))
            return _Result(None)
        raise AssertionError(query)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _Owners:
    def __init__(self) -> None:
        self.values: set[tuple[str, str, str]] = set()

    def create(self, resource_type, resource_id, *, session_tenant_id):
        value = (resource_type, resource_id, session_tenant_id)
        if value in self.values:
            raise ResourceOwnerConflict("exists")
        self.values.add(value)

    def assert_owner(self, resource_type, resource_id, *, session_tenant_id):
        assert (resource_type, resource_id, session_tenant_id) in self.values


def test_reconcile_is_idempotent_for_same_verified_source(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    _source(root, title="Observed title")
    candidates, errors = discover_candidates(root, TENANT)
    assert not errors
    connection = _Connection()
    scope = OperatorScope("operator", "tenant")
    owners = _Owners()

    assert reconcile(connection, TENANT, candidates, scope, owner_registry=owners) == {"inserted": 1, "updated": 0, "unchanged": 0}
    assert reconcile(connection, TENANT, candidates, scope, owner_registry=owners) == {"inserted": 0, "updated": 0, "unchanged": 1}
    assert connection.commits == 2
    assert connection.rollbacks == 0
    assert ("media.source_asset", "asset_demo_123", TENANT) in owners.values


def test_qa_manifests_are_explicitly_excluded(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    _source(root, asset_id="qa_asset_demo_123", qa=True)

    candidates, errors = discover_candidates(root, TENANT)

    assert candidates == []
    assert errors and "QA manifest" in errors[0]["error"]


def test_repair_sidecar_sizes_repairs_only_verified_production_metadata(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    production = _source(root, asset_id="asset_production_123", title="Observed title")
    qa = _source(root, asset_id="asset_qa_fixture_123", qa=True)
    production_sidecar = production.with_name("manifest.json.manifest.json")
    qa_sidecar = qa.with_name("manifest.json.manifest.json")
    production_data = json.loads(production_sidecar.read_text(encoding="utf-8"))
    qa_data = json.loads(qa_sidecar.read_text(encoding="utf-8"))
    production_data["size_bytes"] -= 2
    qa_data["size_bytes"] -= 2
    production_sidecar.write_text(json.dumps(production_data), encoding="utf-8")
    qa_sidecar.write_text(json.dumps(qa_data), encoding="utf-8")

    repaired = repair_sidecar_sizes(root, TENANT)

    assert repaired == [str(production_sidecar)]
    assert json.loads(production_sidecar.read_text(encoding="utf-8"))["size_bytes"] == production.stat().st_size
    assert json.loads(qa_sidecar.read_text(encoding="utf-8"))["size_bytes"] == qa_data["size_bytes"]


def test_repair_sidecar_sizes_leaves_hash_mismatch_untouched(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    path = _source(root, title="Observed title")
    sidecar_path = path.with_name("manifest.json.manifest.json")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["size_bytes"] -= 2
    sidecar["content_hash"] = "sha256:" + ("0" * 64)
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    assert repair_sidecar_sizes(root, TENANT) == []
    assert json.loads(sidecar_path.read_text(encoding="utf-8"))["size_bytes"] == sidecar["size_bytes"]


def test_existing_page_fields_and_preview_are_preserved_while_evidence_is_added(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    _source(
        root,
        title="Manifest title",
        platform="抖音",
        source_url="https://example.test/source",
        captured_at=1782822671597,
    )
    candidates, errors = discover_candidates(root, TENANT)
    assert not errors
    connection = _Connection()
    connection.rows["asset_demo_123"] = (
        "lark:v1",
        {
            "title": "Feishu title",
            "mediaType": "video",
            "platform": "抖音",
            "sourceLabel": "飞书素材库",
            "tags": ["训练"],
            "trackNames": [],
            "qualityStatus": "verified",
            "materialStatus": "active",
            "source_url": "https://example.test/source",
            "source": {"provider": "feishu"},
            "fields": {"封面附件": [{"name": "cover.jpg"}]},
            "preview": {"kind": "image", "status": "available", "url": "/openclaw/media/api/assets/asset_demo_123/preview"},
        },
    )

    stats = reconcile(
        connection,
        TENANT,
        candidates,
        OperatorScope("operator", "tenant"),
        owner_registry=_Owners(),
    )
    merged = connection.rows["asset_demo_123"][1]

    assert stats == {"inserted": 0, "updated": 1, "unchanged": 0}
    assert merged["title"] == "Feishu title"
    assert merged["source"] == {"provider": "feishu"}
    assert merged["preview"]["status"] == "available"
    assert merged["captured_at"] == "2026-06-30T12:31:11.597000Z"
    assert merged["mediaVaultEvidence"]["provider"] == "media_vault"
