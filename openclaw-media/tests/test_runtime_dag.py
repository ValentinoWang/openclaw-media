from __future__ import annotations

from openclaw_media import InstalledCatalog, NodeRegistry


def test_catalog_derived_registry_has_exactly_the_nine_allowlisted_node_types():
    catalog = InstalledCatalog()
    registry = NodeRegistry(catalog)
    expected = {item["node_type"] for item in catalog.manifest["node_registry"]}
    assert set(registry.allowed) == expected
    assert len(registry.allowed) == 9


def test_registry_rejects_unknown_node_and_version_drift():
    catalog = InstalledCatalog()
    registry = NodeRegistry(catalog)
    for node in (
        {"type": "unknown.node", "version": "1.0.0", "outputs": []},
        {"type": "material.organize", "version": "9.0.0", "outputs": ["organization_plan"]},
    ):
        try:
            registry.execute(node, {})
        except Exception as exc:
            assert getattr(exc, "code", None) == "unknown_node"
        else:
            raise AssertionError("catalog drift was accepted")
