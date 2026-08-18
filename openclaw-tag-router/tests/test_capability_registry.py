from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from openclaw_app.services.capability_registry import (
    CAPABILITY_REGISTRY,
    CapabilityRegistry,
    CapabilityRegistryError,
)


def test_registry_compiles_every_canonical_leaf_with_stable_digest() -> None:
    rebuilt = CapabilityRegistry.compile_all()

    assert len(rebuilt.definitions) == 55
    assert rebuilt.catalog_version == CAPABILITY_REGISTRY.catalog_version
    assert rebuilt.catalog_version.startswith("sha256:")
    assert all(item.fields or item.variants for item in rebuilt.definitions)


def test_aliases_converge_to_one_canonical_leaf() -> None:
    polish = CAPABILITY_REGISTRY.get("style_polish_run")

    assert polish is not None
    assert polish.label == "润色"
    assert CAPABILITY_REGISTRY.resolve_alias("去AI味") is polish
    assert CAPABILITY_REGISTRY.resolve_alias("抖音文案") is polish


def test_deepmath_thinking_projects_to_deepmath_only() -> None:
    thinking = CAPABILITY_REGISTRY.get("deepmath_ceo_thinking_intake")

    assert thinking is not None
    assert thinking.bots == ("DeepMath bot",)
    assert thinking.source_system == "deepmath"
    deepmath_catalog = CAPABILITY_REGISTRY.serialize(
        visibilities=frozenset({"public", "ops", "maintainer"}),
        bots=frozenset({"DeepMath bot"}),
    )
    assert [item["capabilityId"] for item in deepmath_catalog["capabilities"]] == [
        "deepmath_ceo_thinking_intake",
    ]


def test_creator_profile_paths_and_confirmation_are_explicit() -> None:
    lookup = CAPABILITY_REGISTRY.get("creator_profile_lookup")
    upsert = CAPABILITY_REGISTRY.get("creator_profile_upsert")

    assert lookup is not None and upsert is not None
    assert lookup.hierarchy.path_names == ("账号", "博主档案", "查询")
    assert lookup.effect == "read"
    assert lookup.confirmation_policy.stage == "none"
    assert upsert.hierarchy.path_names == ("账号", "博主档案", "入库")
    assert upsert.effect == "write"
    assert upsert.confirmation_policy.stage == "after_candidate"
    assert {field.key for field in upsert.fields} >= {"platform", "author_id", "profile_url", "account_name", "expertise_domains"}


def test_destructive_and_document_mutation_capabilities_are_maintainer_only() -> None:
    deletion = CAPABILITY_REGISTRY.get("universal_deletion")
    document_edit = CAPABILITY_REGISTRY.get("document_edit")

    assert deletion is not None and document_edit is not None
    assert deletion.visibility == "maintainer"
    assert deletion.effect == "destructive"
    assert deletion.confirmation_policy.stage == "destructive_preview_apply"
    assert document_edit.visibility == "maintainer"


@pytest.mark.parametrize("capability_id", ["inspiration_archive", "recent_records_summary", "record_sync"])
def test_persisting_system_capabilities_require_confirmation(capability_id: str) -> None:
    capability = CAPABILITY_REGISTRY.get(capability_id)

    assert capability is not None
    assert capability.effect == "write"
    assert capability.writes_to
    assert capability.confirmation_policy.stage == "before_execute"


@pytest.mark.parametrize(
    "capability_id",
    [
        "activity_archive", "selfmedia_creation", "selfmedia_cognition_accumulation",
        "id_business", "viral_deconstruction", "vlog_inspiration_capture",
    ],
)
def test_media_persisting_handlers_cannot_compile_as_read_only(capability_id: str) -> None:
    capability = CAPABILITY_REGISTRY.get(capability_id)

    assert capability is not None
    assert capability.effect == "write"
    assert capability.writes_to
    assert capability.confirmation_policy.stage == "before_execute"


@pytest.mark.parametrize("capability_id", ["recent_records_lookup", "task_status_lookup"])
def test_query_system_capabilities_are_declared_read_only(capability_id: str) -> None:
    capability = CAPABILITY_REGISTRY.get(capability_id)

    assert capability is not None
    assert capability.effect == "read"
    assert capability.confirmation_policy.stage == "none"


def test_registry_rejects_duplicate_id_and_path() -> None:
    original = CAPABILITY_REGISTRY.definitions[0]

    with pytest.raises(CapabilityRegistryError, match="duplicate capability id"):
        CapabilityRegistry((original, replace(original, display_order=999)))

    other = CAPABILITY_REGISTRY.definitions[1]
    with pytest.raises(CapabilityRegistryError, match="duplicate capability path"):
        CapabilityRegistry((original, replace(other, hierarchy=original.hierarchy)))


def test_catalog_serialization_is_immutable_projection() -> None:
    payload = CAPABILITY_REGISTRY.serialize(
        visibilities=frozenset({"public", "ops"}),
        bots=frozenset({"Media bot", "任意 Bot"}),
    )
    creator = next(item for item in payload["capabilities"] if item["capabilityId"] == "creator_profile_upsert")

    assert payload["schemaVersion"] == "capability_catalog_v3"
    assert payload["catalogVersion"] == CAPABILITY_REGISTRY.catalog_version
    assert creator["hierarchy"]["pathNames"] == ["账号", "博主档案", "入库"]
    assert creator["confirmationPolicy"]["stage"] == "after_candidate"
    assert creator["bots"] == ["Media bot"]
    assert creator["variants"]
    assert set(creator["attachmentPolicy"]["types"]) == {"text", "url"}
    assert creator["attachmentPolicy"]["maxCount"] == 8
    assert creator["attachmentPolicy"]["maxBytes"] == 52428800
    assert all(set(item["bots"]) & {"Media bot", "任意 Bot"} for item in payload["capabilities"])


def test_media_catalog_has_explicit_names_and_parsed_directory_paths() -> None:
    payload = CAPABILITY_REGISTRY.serialize(
        visibilities=frozenset({"public", "ops", "maintainer"}),
        bots=frozenset({"Media bot", "任意 Bot"}),
    )
    items = payload["capabilities"]

    assert len(items) == 34
    assert len({item["displayName"] for item in items}) == len(items)
    assert all(2 <= len(item["hierarchy"]["pathNames"]) <= 3 for item in items)
    assert all(item["hierarchy"]["categoryName"] != "能力目录" for item in items)
    assert all(item["displayName"] not in item["hierarchy"]["pathNames"] for item in items)
    assert all(not any(marker in item["displayName"] for marker in (">", "-", "_id")) for item in items)
    assert all(not any(marker in " / ".join(item["hierarchy"]["pathNames"]) for marker in (">", "-")) for item in items)


def test_catalog_visibility_filter_does_not_expose_universal_deletion() -> None:
    public_payload = CAPABILITY_REGISTRY.serialize(visibilities=frozenset({"public"}))
    maintainer_payload = CAPABILITY_REGISTRY.serialize(visibilities=frozenset({"maintainer"}))

    public_ids = {item["capabilityId"] for item in public_payload["capabilities"]}
    maintainer_ids = {item["capabilityId"] for item in maintainer_payload["capabilities"]}
    assert "universal_deletion" not in public_ids
    assert "universal_deletion" in maintainer_ids


def test_serialized_catalog_conforms_to_its_public_json_schema() -> None:
    schema_path = Path(__file__).parents[1] / "openclaw_app/contracts/capability_catalog.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = CAPABILITY_REGISTRY.serialize(
        visibilities=frozenset({"public", "ops", "maintainer"}),
        bots=frozenset({"Media bot", "任意 Bot"}),
    )

    Draft202012Validator(schema).validate(payload)


def test_input_contract_is_direct_id_keyed_without_label_inference() -> None:
    source_path = Path(__file__).parents[1] / "openclaw_app/services/capability_input_contracts.py"
    source = source_path.read_text(encoding="utf-8")

    for retired_symbol in ("_LABEL_CONTRACT_TEMPLATES", "FIELD_KEY_OVERRIDES", "def _field_definition"):
        assert retired_symbol not in source


def test_real_capabilities_expose_generic_renderer_metadata() -> None:
    creator = CAPABILITY_REGISTRY.get("creator_profile_upsert")
    deletion = CAPABILITY_REGISTRY.get("universal_deletion")
    review = CAPABILITY_REGISTRY.get("selfmedia_data_review")
    creation = CAPABILITY_REGISTRY.get("selfmedia_creation")

    assert creator is not None and deletion is not None and review is not None and creation is not None
    creator_fields = {field.key: field for field in creator.fields}
    deletion_fields = {field.key: field for field in deletion.fields}
    assert creator_fields["creator_name"].input_type == "object"
    assert creator_fields["creator_name"].value_type == "string"
    assert creator_fields["profile_url"].format.url_schemes == ("http", "https")
    assert deletion_fields["action"].input_type == "radio"
    assert deletion_fields["action"].visible_when[0].source == "variant"
    assert deletion_fields["action"].visible_when[0].value == "confirm"
    assert "image" in review.supported_attachments
    assert any(field.input_type == "textarea" for field in creation.fields)
    for capability in (creator, deletion, review, creation):
        assert capability.search_keywords
        assert capability.provenance
        assert all(field.semantic_owner and field.persistence_owner for field in capability.fields)


def test_backend_enforces_conditions_url_and_numeric_minimum() -> None:
    hidden_action = CAPABILITY_REGISTRY.validation_issues(
        "universal_deletion", "preview", {"id": "task_12345678", "action": "delete"}
    )
    invalid_creator = CAPABILITY_REGISTRY.validation_issues(
        "creator_profile_upsert",
        "manual",
        {
            "platform": "小红书",
            "profile_url": "javascript:alert(1)",
            "expertise_domains": ["运动训练"],
            "follower_count_k": -1,
        },
    )

    assert {issue["code"] for issue in hidden_action} >= {"field_not_visible"}
    assert {issue["code"] for issue in invalid_creator} >= {"invalid_format", "below_minimum"}
