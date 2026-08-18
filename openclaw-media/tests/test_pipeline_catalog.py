from copy import deepcopy

import pytest

from openclaw_media.catalog import CatalogError, InstalledCatalog, build_projections


def test_installed_catalog_has_nine_pipelines_and_resolves_exact_identity():
    catalog = InstalledCatalog()
    assert catalog.manifest["pipeline_count"] == 9
    pipeline = catalog.manifest["pipelines"][0]
    assert catalog.resolve(
        pipeline["pipeline_id"], pipeline["version"], pipeline["catalog_digest"]
    ) == pipeline


def test_missing_version_and_digest_mismatch_refuse_execution():
    catalog = InstalledCatalog()
    pipeline = catalog.manifest["pipelines"][0]
    with pytest.raises(CatalogError, match="version is not installed"):
        catalog.resolve(pipeline["pipeline_id"], "999.0.0", pipeline["catalog_digest"])
    with pytest.raises(CatalogError, match="digest is not installed"):
        catalog.resolve(pipeline["pipeline_id"], pipeline["version"], "sha256:bad")


def test_unknown_node_and_tampered_catalog_refuse_loading():
    catalog = InstalledCatalog()
    manifest = deepcopy(catalog.manifest)
    manifest["pipelines"][0]["nodes"][0]["type"] = "unknown.node"
    _, web = build_projections(
        {
            "contract_id": manifest["contract_id"],
            "version": manifest["contract_version"],
            "pipeline_catalog": manifest["pipelines"],
            "node_registry": manifest["node_registry"],
            "historical_capability_coverage": manifest["historical_capability_coverage"],
        }
    )
    manifest["catalog_digest"] = web["catalog_digest"]
    for pipeline in manifest["pipelines"]:
        pipeline["catalog_digest"] = web["catalog_digest"]
    with pytest.raises(CatalogError, match="unknown node"):
        InstalledCatalog(manifest)


def test_historical_coverage_is_complete():
    catalog = InstalledCatalog()
    coverage = catalog.manifest["historical_capability_coverage"]
    assert len(coverage) == 9
    assert not [item for item in coverage if item["status"] == "unmapped"]
