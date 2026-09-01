from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys
from typing import Any

import yaml


ROOT = Path(__file__).parents[1]
CONTRACT_DIR = ROOT / "openclaw_app" / "contracts"
OPENAPI_PATH = CONTRACT_DIR / "media_web_business_pages.openapi.yaml"
MIGRATION_PATH = CONTRACT_DIR / "media_web_business_pages.migration.yaml"

PAGE_CONTRACTS = {
    "B01": ("ordinary", "/overview", {"getDashboard", "listContentProjects", "listProjectArtifacts", "createProjectSummary", "getDocumentResource"}),
    "B02": ("ordinary", "/tracks", {"listTracks", "getTrack", "listCreators", "getCreator", "listTrackRelationships", "updateTrackRelationshipStatus", "listOwnedAccounts", "getOwnedAccount", "getAccountTrackStrategy", "getAccountMonitor", "updateAccountMonitor", "pollAccountMonitor", "createMediaTask", "getDocumentResource"}),
    "B03": ("ordinary", "/assets", {"listAssets", "getAsset", "getAssetPreview", "createMediaTask", "getDocumentResource"}),
    "B04": ("ordinary", "/decisions", {"listDecisions", "getDecision", "listDecisionSignals", "confirmDecision", "createMediaTask", "getDocumentResource"}),
    "B05": ("ordinary", "/runs", {"listRuns", "getRun", "getRunSources", "getRunDecisions", "getRunOutputs", "listBusinessOpportunities", "createMediaTask", "createArtifactRevision", "getDocumentResource", "listArtifactSyncBatches"}),
    "B06": ("ordinary", "/publishing", {"listPublishingPackages", "getPublishingPackage", "getPublishedPost", "updatePublishingChecks", "createPublishedPost", "getResourceDocxLink", "createMediaTask", "getDocumentResource"}),
    "B07": ("ordinary", "/reviews", {"listReviews", "getReviewsSummary", "listContentMetrics", "listAccountMetrics", "createMetricImport", "createReview", "confirmReview", "createMediaTask", "getDocumentResource"}),
    "B08": ("ordinary", "/usage-billing", {"getBillingBalance", "listBillingBalancePacks", "listBillingUsage", "getBillingUsageSummary", "redeemBillingCode"}),
    "B09": ("ordinary", "/invites", {"getAffiliateProfile", "listInvitees"}),
    "B10": ("admin", "/admin/overview", {"getAdminDashboard"}),
    "B11": ("admin", "/admin/access", {"listAdminAffiliateUsers", "updateAdminAffiliateUser", "listAdminAdmissionBatches", "createAdminAdmissionBatch", "disableAdminAdmissionBatch", "getAdminRegistrationPolicy", "updateAdminRegistrationPolicy", "revokeAdminUserSessions"}),
    "B12": ("admin", "/admin/tenants", {"listAdminTenants", "getAdminTenant", "listAdminTenantRuns"}),
    "B13": ("admin", "/admin/billing", {"getAdminBillingSummary", "createAdminProductMapping", "createAdminBillingGrant", "createAdminRedemptionBatch", "recoverAdminFulfillment", "refundAdminFulfillment"}),
    "B14": ("admin", "/admin/upstreams", {"getAdminUpstreams", "getAdminPlatformCookies", "reconcileAdminBillingOperation", "rotateAdminUpstreamCredential", "revokeAdminUpstreamCredential"}),
}

SHARED_OPERATION_IDS = {
    "getAuthEntryState",
    "getMediaSession",
    "listMediaCapabilities",
    "matchMediaCapability",
    "createMediaUpload",
    "listMediaTasks",
    "getMediaTask",
    "listMediaTaskEvents",
    "cancelMediaTask",
    "confirmMediaTask",
    "getDocumentResource",
    "getDocumentBody",
    "saveDocumentDraft",
    "getDocumentRevision",
    "createDocumentExport",
    "getDocumentExport",
    "getDocumentExportDownload",
}

DOCUMENT_OPERATION_PATHS = {
    "getDocumentResource": ("/document-resources/{publicResourceId}", "get"),
    "getDocumentBody": ("/documents/{publicArtifactId}/body", "get"),
    "saveDocumentDraft": ("/documents/{publicArtifactId}/draft", "put"),
    "getDocumentRevision": ("/documents/{publicArtifactId}/revisions/{revision}", "get"),
    "createDocumentExport": ("/documents/{publicArtifactId}/exports", "post"),
    "getDocumentExport": ("/document-exports/{publicExportId}", "get"),
    "getDocumentExportDownload": ("/document-exports/{publicExportId}/download", "get"),
}

DOCUMENT_ARTIFACT_KINDS = {
    "research_snapshot",
    "asset_digest",
    "decision_brief",
    "creation_document",
    "publishing_package",
    "review_report",
    "project_summary",
}

LARK_BODY_AUTHORITY_KINDS = {
    "research_snapshot",
    "asset_digest",
    "decision_brief",
    "creation_document",
    "review_report",
}

INTERNAL_ONLY_ARTIFACT_KINDS = {"publishing_package", "project_summary"}

DOCUMENT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "heading_4",
    "heading_5",
    "heading_6",
    "heading_7",
    "heading_8",
    "heading_9",
    "bullet_list",
    "ordered_list",
    "todo_item",
    "quote",
    "code_block",
    "divider",
    "callout",
    "image",
    "attachment",
    "table",
    "data_snapshot",
}

PROTECTED_LARK_BLOCKS = {
    "whiteboard",
    "bitable",
    "sheet",
    "embed",
    "synced_block",
    "third_party_widget",
    "agenda",
    "okr",
    "mind_note",
    "flowchart",
    "lark_task",
}

EXISTING_EXTENDED_OPERATION_IDS = {
    "getDashboard", "listAssets", "listRuns", "getRun", "getRunSources",
    "getRunDecisions", "getRunOutputs", "getResourceDocxLink", "getAdminDashboard",
}

EXISTING_TYPED_OPERATION_IDS = {
    "getAuthEntryState",
    "getMediaSession", "listMediaCapabilities", "matchMediaCapability", "createMediaUpload",
    "listMediaTasks", "createMediaTask", "getMediaTask", "listMediaTaskEvents",
    "cancelMediaTask", "confirmMediaTask", "getBillingBalance", "listBillingBalancePacks",
    "listBillingUsage", "redeemBillingCode", "getAffiliateProfile", "listInvitees",
    "listAdminAffiliateUsers", "updateAdminAffiliateUser", "listAdminAdmissionBatches",
    "createAdminAdmissionBatch", "disableAdminAdmissionBatch", "getAdminRegistrationPolicy",
    "updateAdminRegistrationPolicy", "revokeAdminUserSessions", "getAdminBillingSummary",
    "createAdminProductMapping", "createAdminBillingGrant", "createAdminRedemptionBatch",
    "recoverAdminFulfillment", "refundAdminFulfillment", "reconcileAdminBillingOperation",
    "rotateAdminUpstreamCredential", "revokeAdminUpstreamCredential",
}

CAPABILITY_STATUSES = {
    "commercial_brief": "implemented",
    "source_asset_intake": "implemented",
    "creation_decision_brief": "implemented",
    "publishing_pack_build": "implemented",
    "media_growth_review": "implemented",
    "track_registry_lookup": "implemented",
    "track_creator_membership_query": "implemented",
    "platform_hotlist": "implemented",
    "document_edit": "implemented",
    "commercial_delivery_draft": "implemented",
    "creator_profile_lookup": "implemented",
    "creator_profile_upsert": "implemented",
    "external_research_brief": "implemented",
    "post_review_signal": "implemented",
    "vlog_inspiration_capture": "external",
    "shooting_execution_plan": "external",
    "creation_checklist_lookup": "external",
    "activity_archive": "external",
    "viral_deconstruction": "external",
    "selfmedia_creation": "external",
    "selfmedia_creation_consultation": "external",
    "selfmedia_data_review": "external",
    "selfmedia_cognition_accumulation": "external",
    "work_acceptance_report": "external",
    "style_polish_run": "external",
    "id_business": "external",
    "account_track_strategy": "not_implemented",
    "owned_media_account_lookup": "not_implemented",
}

CANONICAL_TABLES = {
    "Activity": "media_product.activities",
    "SourceAsset": "media_product.assets",
    "MaterialDeconstruction": "media_product.material_deconstructions",
    "CreativePattern": "media_product.creative_patterns",
    "CreationRun": "media_product.creation_runs",
    "PublishedPost": "media_product.published_posts",
    "BusinessAccount": "media_product.business_accounts",
    "BusinessOpportunity": "media_product.business_opportunities",
    "CreatorProfile": "media_product.creator_profiles",
    "TrackRegistry": "media_product.tracks",
    "MaterialUsage": "media_product.material_usages",
    "DecisionTrace": "media_product.decision_traces",
    "TrackCreatorMembership": "media_product.track_creator_memberships",
    "MetricSnapshot": "media_product.metric_snapshots",
    "AccountMetricSnapshot": "media_product.account_metric_snapshots",
    "GrowthSummary": "media_product.growth_summaries",
}

PRODUCT_TABLES = {
    "content_projects": "media_product.content_projects",
    "document_artifacts": "media_product.document_artifacts",
    "document_revisions": "media_product.document_revisions",
    "document_revision_bodies": "media_document.revision_bodies",
    "document_exports": "media_document.exports",
    "owned_media_accounts": "media_product.owned_media_accounts",
    "account_track_strategies": "media_product.account_track_strategies",
    "signal_snapshots": "media_product.signal_snapshots",
    "publishing_packages": "media_product.publishing_packages",
    "publishing_checks": "media_product.publishing_checks",
    "review_records": "media_product.review_records",
    "usage_events": "openclaw_account.usage_events",
}

LARK_EXTENSION_TABLES = {
    "tenant_installations": "media_product.lark_tenant_installations",
    "document_bindings": "media_product.lark_document_bindings",
    "document_block_mappings": "media_product.lark_document_block_mappings",
    "sync_batches": "media_product.sync_batches",
}

FORBIDDEN_RESPONSE_PROPERTIES = {
    "tenantId",
    "targetTenantId",
    "feishuRecordId",
    "recordId",
    "localPath",
    "rawPrompt",
    "rawResponse",
    "accessToken",
    "refreshToken",
    "secret",
    "token",
}


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def _operations(document: dict[str, Any]) -> dict[str, tuple[str, str, dict[str, Any]]]:
    result: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, path_item in document["paths"].items():
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if operation is None:
                continue
            operation_id = operation["operationId"]
            assert operation_id not in result, operation_id
            result[operation_id] = (path, method, operation)
    return result


def _resolve_internal_ref(document: dict[str, Any], ref: str) -> Any:
    assert ref.startswith("#/"), ref
    value: Any = document
    for part in ref[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _walk(value: Any):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_a2_contract_files_exist() -> None:
    assert OPENAPI_PATH.is_file()
    assert MIGRATION_PATH.is_file()


def test_openapi_freezes_all_pages_and_operations_once() -> None:
    document = _load(OPENAPI_PATH)
    assert document["openapi"] == "3.1.0"
    assert document["info"]["version"] == "2.0.0"
    assert document["servers"] == [{"url": "/openclaw/media/api"}]
    assert document["x-openclaw-interface-freeze-version"] == 5
    assert document["components"]["schemas"]["SchemaVersion"]["const"] == "media_web_business_pages_v2"

    pages = document["x-openclaw-pages"]
    assert set(pages) == set(PAGE_CONTRACTS)
    assert Counter(page["role"] for page in pages.values()) == {"ordinary": 9, "admin": 5}
    for page_id, (role, route, operation_ids) in PAGE_CONTRACTS.items():
        assert pages[page_id] == {
            "role": role,
            "route": route,
            "operationIds": sorted(operation_ids),
        }

    operations = _operations(document)
    page_operation_ids = set().union(*(item[2] for item in PAGE_CONTRACTS.values()))
    assert set(operations) == page_operation_ids | SHARED_OPERATION_IDS


def test_existing_routes_are_extended_without_synonym_paths() -> None:
    operations = _operations(_load(OPENAPI_PATH))
    assert operations["getDashboard"][:2] == ("/dashboard", "get")
    assert operations["listAssets"][:2] == ("/assets", "get")
    assert operations["listRuns"][:2] == ("/runs", "get")
    assert operations["getAdminDashboard"][:2] == ("/admin/dashboard", "get")
    assert operations["listBillingUsage"][:2] == ("/billing/usage", "get")
    assert operations["getAffiliateProfile"][:2] == ("/account/affiliate", "get")
    assert operations["listInvitees"][:2] == ("/account/invitees", "get")
    assert operations["getAuthEntryState"][:2] == ("/openclaw/auth/entry-state", "get")
    assert "/admin/overview" not in _load(OPENAPI_PATH)["paths"]
    assert "/publication-receipts" not in _load(OPENAPI_PATH)["paths"]
    assert {
        operation_id
        for operation_id, (_path, _method, operation) in operations.items()
        if operation["x-runtime-status"] == "existing_extended"
    } == EXISTING_EXTENDED_OPERATION_IDS
    assert {
        operation_id
        for operation_id, (_path, _method, operation) in operations.items()
        if operation["x-runtime-status"] == "existing_typed"
    } == EXISTING_TYPED_OPERATION_IDS
    assert all(
        operation["x-runtime-status"] in {"existing_typed", "existing_extended", "new"}
        for _path, _method, operation in operations.values()
    )


def test_permissions_mutation_headers_and_error_contract_are_machine_checkable() -> None:
    document = _load(OPENAPI_PATH)
    operations = _operations(document)
    matrix = document["x-openclaw-permission-matrix"]
    assert matrix["ordinary"]["tenantSource"] == "verified_session"
    assert matrix["ordinary"]["acceptsCallerTenantId"] is False
    assert matrix["admin"]["crossTenantRead"]["requires"] == ["publicTenantId", "X-Audit-Reason"]
    assert matrix["admin"]["defaultResponse"] == "redacted_aggregate"

    for operation_id, (path, method, operation) in operations.items():
        if operation_id == "getAuthEntryState":
            assert operation["security"] == [], operation_id
        else:
            assert operation["security"] == [{"cookieAuth": []}], operation_id
        responses = set(operation["responses"])
        if operation_id == "getAuthEntryState":
            assert {"400", "500"} <= responses, operation_id
        else:
            assert {"401", "403", "500"} <= responses, operation_id
        permission = operation["x-permission"]
        if operation_id == "getAuthEntryState":
            assert permission == "public-entry"
        else:
            assert permission.startswith("admin") if path.startswith("/admin/") else permission.startswith(("ordinary", "shared"))
        if method == "get":
            continue
        refs = {
            parameter.get("$ref")
            for parameter in operation.get("parameters", [])
            if isinstance(parameter, dict)
        }
        assert "#/components/parameters/CsrfHeader" in refs, operation_id
        assert "#/components/parameters/IdempotencyHeader" in refs, operation_id
        assert {"400", "409"} <= responses, operation_id

    for operation_id in ("getAdminTenant", "listAdminTenantRuns"):
        refs = {item.get("$ref") for item in operations[operation_id][2]["parameters"]}
        assert "#/components/parameters/AuditReasonHeader" in refs
        assert "#/components/parameters/PublicTenantId" in refs


def test_every_internal_reference_resolves_and_response_fields_are_safe() -> None:
    document = _load(OPENAPI_PATH)
    for value in _walk(document):
        if isinstance(value, dict) and "$ref" in value:
            _resolve_internal_ref(document, value["$ref"])

    for schema_name, schema in document["components"]["schemas"].items():
        if schema_name.endswith(("Request", "Input", "Query")):
            continue
        for value in _walk(schema):
            if not isinstance(value, dict):
                continue
            properties = set((value.get("properties") or {}).keys())
            assert not properties & FORBIDDEN_RESPONSE_PROPERTIES, (schema_name, properties)


def test_auth_entry_state_contract_freezes_version_modes_and_four_states() -> None:
    document = _load(OPENAPI_PATH)
    operation = _operations(document)["getAuthEntryState"][2]
    assert operation["parameters"] == [{"$ref": "#/components/parameters/AuthEntryMode"}]
    assert document["components"]["parameters"]["AuthEntryMode"] == {
        "name": "mode",
        "in": "query",
        "required": True,
        "schema": {"type": "string", "enum": ["personal", "organization"]},
    }
    response_schema = document["components"]["schemas"]["AuthEntryStateResponse"]
    assert response_schema["properties"]["schemaVersion"]["const"] == "media_auth_entry_state_v1"
    assert set(response_schema["properties"]["state"]["enum"]) == {
        "matched", "none", "expired", "mismatched"
    }
    assert response_schema["properties"]["entry"]["oneOf"] == [
        {"$ref": "#/components/schemas/AuthEntryStateEntry"},
        {"type": "null"},
    ]
    assert set(response_schema["properties"]["fallback"]["enum"]) == {"password", "feishu_oauth"}


def test_path_parameters_match_literal_path_variables() -> None:
    document = _load(OPENAPI_PATH)
    for operation_id, (path, _method, operation) in _operations(document).items():
        expected = set(re.findall(r"\{([^}]+)\}", path))
        actual = set()
        for parameter in operation.get("parameters", []):
            resolved = _resolve_internal_ref(document, parameter["$ref"])
            if resolved["in"] == "path":
                assert resolved["required"] is True
                actual.add(resolved["name"])
        assert actual == expected, operation_id


def test_canonical_capability_mapping_is_complete_and_unique() -> None:
    document = _load(OPENAPI_PATH)
    mappings = document["x-openclaw-canonical-capabilities"]
    assert len(mappings) == 28
    assert {item["capabilityId"] for item in mappings} == set(CAPABILITY_STATUSES)
    assert {item["capabilityId"]: item["status"] for item in mappings} == CAPABILITY_STATUSES
    assert Counter(item["status"] for item in mappings) == {
        "implemented": 14,
        "external": 12,
        "not_implemented": 2,
    }
    operation_ids = set(_operations(document))
    for item in mappings:
        assert item["operationIds"]
        assert set(item["operationIds"]) <= operation_ids
        assert item["productReadModels"]
        if item["status"] == "not_implemented":
            assert item["handlers"] == []
            assert item["implementationNode"] == "B02"
        else:
            assert item["handlers"]

    task_ids = document["components"]["schemas"]["CreateMediaTaskRequest"]["properties"]["capabilityId"]["enum"]
    assert set(task_ids) == set(CAPABILITY_STATUSES)


def test_capability_status_and_primary_handler_match_runtime_registry() -> None:
    sys.path.insert(0, str(ROOT.parent))
    from openclaw_app.services.capability_registry import CAPABILITY_REGISTRY

    mappings = _load(OPENAPI_PATH)["x-openclaw-canonical-capabilities"]
    for mapping in mappings:
        capability = CAPABILITY_REGISTRY.get(mapping["capabilityId"])
        assert capability is not None
        assert mapping["status"] == capability.status
        if mapping["status"] == "not_implemented":
            assert mapping["handlers"] == []
        else:
            assert any(
                handler == capability.handler or handler.startswith(f"{capability.handler}.")
                for handler in mapping["handlers"]
            ), mapping["capabilityId"]


def test_migration_manifest_has_one_runtime_authority_for_every_entity() -> None:
    manifest = _load(MIGRATION_PATH)
    assert manifest["schemaVersion"] == "media_web_business_pages_migration_v2"
    assert manifest["runtimeDatabase"] == "PostgreSQL"
    assert manifest["legacyRuntimeReadFallback"] is False
    assert manifest["dualWriteAllowed"] is False

    entities = manifest["canonicalEntities"]
    assert {name: item["table"] for name, item in entities.items()} == CANONICAL_TABLES
    for name, item in entities.items():
        assert item["fieldAuthority"] == f"media-model-v2-contract.json#/entities/{name}"
        assert item["requiredProductColumns"] == [
            "tenant_id",
            "public_id",
            "source_version",
            "revision",
            "created_at",
            "updated_at",
        ]
        assert item["legacySources"]
        assert item["runtimeReaders"] == ["PostgreSQL"]

    assert {name: item["table"] for name, item in manifest["productStateObjects"].items()} == PRODUCT_TABLES
    assert {name: item["table"] for name, item in manifest["larkExtensionObjects"].items()} == LARK_EXTENSION_TABLES
    assert manifest["bodyAuthorityModes"] == ["internal", "lark"]
    assert manifest["documentRevisionStates"] == ["draft", "generating", "ready", "failed", "conflict", "archived"]


def test_if2_document_operations_are_typed_and_page_bounded() -> None:
    document = _load(OPENAPI_PATH)
    operations = _operations(document)
    for operation_id, expected in DOCUMENT_OPERATION_PATHS.items():
        path, method, operation = operations[operation_id]
        assert (path, method) == expected
        assert operation["x-permission"] == "ordinary-session"
        assert operation["x-runtime-status"] == "new"
        assert set(operation["x-page-contracts"]) == {f"B{index:02d}" for index in range(1, 8)}
        assert operation["security"] == [{"cookieAuth": []}]
        assert {"401", "403", "404", "500"} <= set(operation["responses"])

    for operation_id in ("saveDocumentDraft", "createDocumentExport"):
        _path, _method, operation = operations[operation_id]
        refs = {parameter.get("$ref") for parameter in operation["parameters"]}
        assert "#/components/parameters/CsrfHeader" in refs
        assert "#/components/parameters/IdempotencyHeader" in refs
        assert {"400", "409", "422"} <= set(operation["responses"])

    assert operations["getDocumentBody"][2]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/DocumentBodyResponse"
    )
    assert operations["saveDocumentDraft"][2]["requestBody"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/SaveDocumentDraftRequest"
    )
    assert operations["createDocumentExport"][2]["requestBody"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/CreateDocumentExportRequest"
    )


def test_document_mutation_errors_declare_optional_block_ids_details() -> None:
    document = _load(OPENAPI_PATH)
    details = document["components"]["schemas"]["ErrorDetail"]["properties"]["details"]
    assert details["additionalProperties"] is False
    assert details["properties"]["blockIds"] == {"type": "array", "items": {"type": "string"}}
    assert "details" not in details.get("required", [])


def test_if2_canonical_body_and_single_authority_contract_are_frozen() -> None:
    document = _load(OPENAPI_PATH)
    contract = document["x-openclaw-document-contract"]
    assert contract["canonicalBodySchema"] == "media.document.body.v1"
    assert set(contract["artifactKinds"]) == DOCUMENT_ARTIFACT_KINDS
    assert set(contract["authorityByWorkspace"]["personal_web"]["internal"]) == DOCUMENT_ARTIFACT_KINDS
    assert set(contract["authorityByWorkspace"]["organization_lark"]["lark"]) == LARK_BODY_AUTHORITY_KINDS
    assert set(contract["authorityByWorkspace"]["organization_lark"]["internal"]) == INTERNAL_ONLY_ARTIFACT_KINDS
    assert contract["noSecondEditableBody"] is True
    assert contract["readyRevisionImmutable"] is True
    assert contract["autosaveUpdatesDraftOnly"] is True
    assert contract["regenerationCreatesRevision"] is True
    assert set(contract["nonCanonicalFormats"]) == {
        "markdown",
        "html",
        "editor_private_json",
        "lark_block_json",
        "docx",
        "pdf",
    }

    schemas = document["components"]["schemas"]
    assert set(schemas["DocumentArtifactKind"]["enum"]) == DOCUMENT_ARTIFACT_KINDS
    assert schemas["DocumentBodyV1"]["properties"]["schemaVersion"]["const"] == "media.document.body.v1"
    assert schemas["DocumentBodyV1"]["properties"]["blocks"]["items"]["$ref"] == "#/components/schemas/DocumentBlock"
    assert schemas["DocumentBlock"]["discriminator"]["propertyName"] == "type"
    mapping = schemas["DocumentBlock"]["discriminator"]["mapping"]
    assert set(mapping) == DOCUMENT_BLOCK_TYPES
    assert schemas["DocumentTableBlock"]["properties"]["rows"]["maxItems"] == 9
    assert schemas["DocumentTableRow"]["properties"]["cells"]["maxItems"] == 9
    assert set(schemas["DocumentRevisionState"]["enum"]) == {
        "draft",
        "generating",
        "ready",
        "failed",
        "conflict",
        "archived",
    }


def test_if2_export_and_lark_block_rules_fail_closed() -> None:
    document = _load(OPENAPI_PATH)
    contract = document["x-openclaw-document-contract"]
    export = contract["export"]
    assert export["sourceRevisionState"] == "ready"
    assert set(export["formats"]) == {"docx", "pdf"}
    assert export["idempotencyIdentity"] == [
        "publicArtifactId",
        "revision",
        "format",
        "templateVersion",
        "rendererVersion",
    ]
    assert set(export["states"]) == {"queued", "rendering", "ready", "failed"}

    lark = contract["larkNativeBlocks"]
    assert lark["tableRootBlockType"] == 31
    assert lark["tableCellBlockType"] == 32
    assert lark["maxRowsPerTable"] == 9
    assert lark["maxColumnsPerTable"] == 9
    assert lark["maxCellsPerTable"] == 81
    assert lark["rowsPerSplitTable"] == 8
    assert lark["repeatHeaderOnSplit"] is True
    assert lark["tooManyColumnsError"] == "lark_table_shape_unsupported"
    assert set(lark["protectedBlocks"]) == PROTECTED_LARK_BLOCKS
    assert lark["protectedBlockPolicy"] == "preserve_and_fail_on_targeted_update_or_export"
    assert set(contract["errorCodes"]) >= {
        "document_revision_conflict",
        "unsupported_document_block",
        "lark_table_shape_unsupported",
    }

    schemas = document["components"]["schemas"]
    assert set(schemas["DocumentExportFormat"]["enum"]) == {"docx", "pdf"}
    assert set(schemas["DocumentExportState"]["enum"]) == {"queued", "rendering", "ready", "failed"}
    request = schemas["CreateDocumentExportRequest"]
    assert set(request["required"]) == {"revision", "format", "templateVersion", "rendererVersion"}


def test_if2_migration_manifest_owns_body_bindings_and_exports_once() -> None:
    manifest = _load(MIGRATION_PATH)
    body = manifest["documentBodyStorage"]
    assert body["schemaVersion"] == "media.document.body.v1"
    assert body["table"] == "media_document.revision_bodies"
    assert body["bodyColumn"] == "body_json"
    assert body["bodyColumnType"] == "JSONB"
    assert body["noSecondEditableBody"] is True
    assert set(body["nonCanonicalFormats"]) == {
        "markdown",
        "html",
        "editor_private_json",
        "lark_block_json",
        "docx",
        "pdf",
    }
    assert body["objectStorage"]["stores"] == ["images", "attachments", "exports"]
    assert body["objectStorage"]["bodyStoresOnly"] == [
        "public_resource_id",
        "alt_text",
        "dimensions",
        "content_checksum",
    ]

    artifacts = manifest["productStateObjects"]["document_artifacts"]
    assert set(artifacts["requiredColumns"]) >= {"public_id", "artifact_kind", "body_authority"}
    revisions = manifest["productStateObjects"]["document_revisions"]
    assert set(revisions["requiredColumns"]) >= {
        "public_artifact_id",
        "revision",
        "state",
        "base_revision",
        "body_checksum",
        "actor_public_id",
    }
    exports = manifest["productStateObjects"]["document_exports"]
    assert set(exports["requiredColumns"]) >= {
        "public_export_id",
        "public_artifact_id",
        "revision",
        "format",
        "state",
        "template_version",
        "renderer_version",
        "idempotency_identity",
        "content_checksum",
        "object_ref",
    }
    binding = manifest["larkExtensionObjects"]["document_bindings"]
    assert set(binding["requiredColumns"]) >= {
        "public_artifact_id",
        "remote_document_version",
        "body_checksum",
    }
    block_mapping = manifest["larkExtensionObjects"]["document_block_mappings"]
    assert set(block_mapping["requiredColumns"]) >= {
        "public_artifact_id",
        "public_block_id",
        "remote_block_id",
        "remote_document_version",
        "block_checksum",
    }
