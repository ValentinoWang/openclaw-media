from openclaw_app.router.tag_capabilities import TAG_CAPABILITIES
from openclaw_app.services.capability_registry import CAPABILITY_REGISTRY


def test_universal_deletion_is_maintainer_only_and_absent_from_public_catalog() -> None:
    declarations = [
        item for item in TAG_CAPABILITIES if item.canonical_capability_id == "universal_deletion"
    ]
    assert len(declarations) == 1
    assert declarations[0].visibility == "maintainer"

    definition = CAPABILITY_REGISTRY.get("universal_deletion")
    assert definition is not None
    assert definition.effect == "destructive"
    assert definition.visibility == "maintainer"

    public_ids = {
        item["capabilityId"]
        for item in CAPABILITY_REGISTRY.serialize(visibilities=frozenset({"public"}))["capabilities"]
    }
    maintainer_ids = {
        item["capabilityId"]
        for item in CAPABILITY_REGISTRY.serialize(visibilities=frozenset({"maintainer"}))["capabilities"]
    }
    assert "universal_deletion" not in public_ids
    assert "universal_deletion" in maintainer_ids
