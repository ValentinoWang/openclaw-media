from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any

import requests

from common.social_runtime import (
    FEISHU_BASE,
    feishu_bitable_refs,
    feishu_coerce_value,
    feishu_field_types,
    feishu_headers,
    feishu_list_records,
    feishu_plain_text,
)
from common.resource_ownership import (
    ResourceOwnerConflict,
    canonical_tenant_owned_resources,
    require_tenant_id,
)

from media_model.contract import MediaModelContract
from media_model.payloads import normalize_source_url


OPTION_ID_RE = re.compile(r"^opt[A-Za-z0-9]{6,}$")
SOURCE_ASSET_ATTACHMENT_FIELDS = ("cover_attachment", "video_attachment")
SOURCE_ASSET_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
TENANT_PROJECTION_FIELD = "租户ID"
PRIVATE_ENTITY_OWNERS: dict[str, tuple[str, str]] = {
    "SourceAsset": ("media.source_asset", "asset_id"),
    "MaterialDeconstruction": ("media.material_deconstruction", "deconstruction_id"),
    "CreativePattern": ("media.creative_pattern", "pattern_id"),
    "CreationRun": ("media.creation_run", "run_id"),
    "PublishedPost": ("media.post_review", "post_id"),
    "BusinessAccount": ("media.business_account", "business_account_id"),
    "BusinessOpportunity": ("media.business_opportunity", "opportunity_id"),
    "CreatorProfile": ("media.creator_profile", "creator_profile_id"),
    "MaterialUsage": ("media.material_usage", "usage_id"),
    "DecisionTrace": ("media.decision_trace", "trace_id"),
    "TrackCreatorMembership": ("media.track_creator_membership", "membership_id"),
    "MetricSnapshot": ("media.metric_snapshot", "snapshot_id"),
    "AccountMetricSnapshot": ("media.account_metric_snapshot", "snapshot_id"),
    "GrowthSummary": ("media.growth_summary", "artifact_id"),
}
GLOBAL_READ_ONLY_ENTITIES = frozenset({"TrackRegistry"})
GLOBAL_MUTABLE_ENTITIES = frozenset({"TrackRegistry"})
ENTITY_DOCX_LINK_FIELDS: dict[str, tuple[str, str]] = {
    "MaterialDeconstruction": ("deconstruction_doc_link", "org_link_edit"),
    "CreationRun": ("feishu_doc_link", "org_link_edit"),
    "PublishedPost": ("review_doc_link", "org_link_edit"),
}


class MediaModelFeishuWriterError(RuntimeError):
    pass


def _feishu_url_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("link", "url"):
            candidate = str(value.get(key) or "").strip()
            if candidate:
                return candidate
    return feishu_plain_text(value)


def prepare_entity_bitable_fields(
    entity_name: str,
    payload: dict[str, Any],
    field_types: dict[str, Any],
    *,
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    contract = contract or MediaModelContract()
    contract.validate_payload(entity_name, payload)
    prepared: dict[str, Any] = {}
    for canonical_key, value in payload.items():
        feishu_field_name = contract.feishu_field_name(entity_name, canonical_key)
        if feishu_field_name not in field_types:
            continue
        _reject_option_ids(value, field_label=f"{entity_name}.{canonical_key}")
        coerced = feishu_coerce_value(value, field_types.get(feishu_field_name))
        if coerced in (None, "", []):
            continue
        prepared[feishu_field_name] = coerced
    if not prepared:
        raise MediaModelFeishuWriterError(f"{entity_name} payload has no fields present in target table")
    return prepared


def write_entity_record(
    entity_name: str,
    table_url: str,
    payload: dict[str, Any],
    *,
    session_tenant_id: str,
    contract: MediaModelContract | None = None,
    dry_run: bool = False,
    field_types_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not table_url and not field_types_override:
        raise MediaModelFeishuWriterError("table_url is required unless field_types_override is provided")
    token = ""
    app_token = ""
    table_id = ""
    if field_types_override is None:
        app_token, table_id, token = feishu_bitable_refs(table_url)
        field_types = feishu_field_types(app_token, table_id, token)
    else:
        field_types = dict(field_types_override)
    fields = prepare_entity_bitable_fields(entity_name, payload, field_types, contract=contract)
    resource_type, resource_id = _private_resource_identity(entity_name, payload)
    tenant_id = require_tenant_id(session_tenant_id)
    if dry_run:
        return {
            "mode": "dry_run",
            "entity": entity_name,
            "fields": {**fields, TENANT_PROJECTION_FIELD: tenant_id},
        }
    owner_service = canonical_tenant_owned_resources()
    fields = owner_service.create_projection(
        resource_type,
        resource_id,
        session_tenant_id=tenant_id,
        fields=fields,
        writer=lambda projected: projected,
    )
    resp = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        headers=feishu_headers(token),
        json={"fields": fields},
        timeout=20,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise MediaModelFeishuWriterError(f"failed to write {entity_name}: {result}")
    record = result.get("data", {}).get("record", {}) or {}
    record_id = str(record.get("record_id") or "")
    if not record_id:
        raise MediaModelFeishuWriterError(f"failed to read created {entity_name} record id")
    readback = read_entity_record(table_url, record_id)
    owner_service.assert_projection_read(
        resource_type,
        resource_id,
        session_tenant_id=tenant_id,
        fields=readback.get("fields") or {},
        projection_source=f"feishu:{table_id}/{record_id}",
    )
    _assert_source_asset_attachment_readback(entity_name, fields, readback, contract)
    _register_entity_docx_link(
        owner_service,
        entity_name,
        resource_type,
        resource_id,
        tenant_id,
        payload,
    )
    return {
        "mode": "write",
        "entity": entity_name,
        "record_id": record_id,
        "fields": fields,
    }


def update_entity_record(
    entity_name: str,
    table_url: str,
    record_id: str,
    payload: dict[str, Any],
    *,
    session_tenant_id: str,
    canonical_resource_id: str,
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    if not table_url or not record_id:
        raise MediaModelFeishuWriterError("table_url and record_id are required for update")
    app_token, table_id, token = feishu_bitable_refs(table_url)
    field_types = feishu_field_types(app_token, table_id, token)
    fields = prepare_entity_bitable_fields(entity_name, payload, field_types, contract=contract)
    resource_type, _ = _private_resource_identity(
        entity_name,
        {PRIVATE_ENTITY_OWNERS.get(entity_name, ("", ""))[1]: canonical_resource_id},
    )
    tenant_id = require_tenant_id(session_tenant_id)
    owner_service = canonical_tenant_owned_resources()
    existing = read_entity_record(table_url, record_id)
    owner_service.assert_projection_read(
        resource_type,
        canonical_resource_id,
        session_tenant_id=tenant_id,
        fields=existing.get("fields") or {},
        projection_source=f"feishu:{table_id}/{record_id}",
    )
    fields = owner_service.update_projection(
        resource_type,
        canonical_resource_id,
        session_tenant_id=tenant_id,
        fields=fields,
        writer=lambda projected: projected,
    )
    resp = requests.put(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        json={"fields": fields},
        timeout=20,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise MediaModelFeishuWriterError(f"failed to update {entity_name}: {result}")
    readback = read_entity_record(table_url, record_id)
    owner_service.assert_projection_read(
        resource_type,
        canonical_resource_id,
        session_tenant_id=tenant_id,
        fields=readback.get("fields") or {},
        projection_source=f"feishu:{table_id}/{record_id}",
    )
    _assert_source_asset_attachment_readback(entity_name, fields, readback, contract)
    _register_entity_docx_link(
        owner_service,
        entity_name,
        resource_type,
        canonical_resource_id,
        tenant_id,
        payload,
    )
    return {
        "mode": "update",
        "entity": entity_name,
        "record_id": record_id,
        "fields": fields,
    }


def upsert_entity_record(
    entity_name: str,
    table_url: str,
    payload: dict[str, Any],
    *,
    session_tenant_id: str,
    key_field: str,
    contract: MediaModelContract | None = None,
    attachment_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not table_url:
        raise MediaModelFeishuWriterError("table_url is required for upsert")
    contract = contract or MediaModelContract()
    expected = str(payload.get(key_field) or "").strip()
    if not expected:
        raise MediaModelFeishuWriterError(f"{entity_name} upsert missing key field: {key_field}")
    resource_type, resource_id = _private_resource_identity(entity_name, payload)
    tenant_id = require_tenant_id(session_tenant_id)
    owner_service = canonical_tenant_owned_resources()
    try:
        owner_service.registry.create(
            resource_type,
            resource_id,
            session_tenant_id=tenant_id,
        )
    except ResourceOwnerConflict:
        owner_service.registry.assert_owner(
            resource_type,
            resource_id,
            session_tenant_id=tenant_id,
        )
    feishu_key_field = contract.feishu_field_name(entity_name, key_field)
    records = feishu_list_records(
        table_url,
        page_size=10,
        filter_formula=f'CurrentValue.[{feishu_key_field}] = "{expected}"',
    )
    effective_payload = _inherit_source_asset_attachments(entity_name, payload, records, contract=contract)
    if attachment_paths:
        effective_payload = _upload_missing_source_asset_attachments(
            entity_name,
            table_url,
            effective_payload,
            attachment_paths,
            contract=contract,
        )
    for record in records:
        fields = record.get("fields") or {}
        if str(fields.get(feishu_key_field) or "").strip() == expected:
            return update_entity_record(
                entity_name,
                table_url,
                str(record.get("record_id") or ""),
                effective_payload,
                session_tenant_id=tenant_id,
                canonical_resource_id=resource_id,
                contract=contract,
            )
    return write_entity_record(
        entity_name,
        table_url,
        effective_payload,
        session_tenant_id=tenant_id,
        contract=contract,
    )


def upsert_global_entity_record(
    entity_name: str,
    table_url: str,
    payload: dict[str, Any],
    *,
    key_field: str,
    maintainer_authorized: bool,
    contract: MediaModelContract | None = None,
) -> dict[str, Any]:
    """Upsert an allowlisted global catalog row after trusted maintainer authorization."""
    if entity_name not in GLOBAL_MUTABLE_ENTITIES:
        raise MediaModelFeishuWriterError(
            f"{entity_name} is not an allowlisted global catalog writer"
        )
    if not maintainer_authorized:
        raise MediaModelFeishuWriterError("global catalog mutation requires maintainer authorization")
    if not table_url:
        raise MediaModelFeishuWriterError("table_url is required for global catalog upsert")
    contract = contract or MediaModelContract()
    expected = str(payload.get(key_field) or "").strip()
    if not expected:
        raise MediaModelFeishuWriterError(
            f"{entity_name} global upsert missing key field: {key_field}"
        )
    app_token, table_id, token = feishu_bitable_refs(table_url)
    field_types = feishu_field_types(app_token, table_id, token)
    fields = prepare_entity_bitable_fields(entity_name, payload, field_types, contract=contract)
    display_key = contract.feishu_field_name(entity_name, key_field)
    records = feishu_list_records(
        table_url,
        page_size=2,
        filter_formula=f'CurrentValue.[{display_key}] = "{expected}"',
    )
    exact = [
        record
        for record in records
        if feishu_plain_text((record.get("fields") or {}).get(display_key)).strip() == expected
    ]
    if len(exact) > 1:
        raise MediaModelFeishuWriterError(
            f"{entity_name} global key is duplicated: {key_field}={expected}"
        )
    if exact:
        record_id = str(exact[0].get("record_id") or "")
        method = requests.put
        url = f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
        mode = "update"
    else:
        record_id = ""
        method = requests.post
        url = f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        mode = "write"
    response = method(url, headers=feishu_headers(token), json={"fields": fields}, timeout=20)
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0:
        raise MediaModelFeishuWriterError(f"failed to {mode} global {entity_name}: {result}")
    if not record_id:
        record_id = str((result.get("data", {}).get("record", {}) or {}).get("record_id") or "")
    if not record_id:
        raise MediaModelFeishuWriterError(f"failed to read global {entity_name} record id")
    readback = read_entity_record(table_url, record_id)
    normalized = contract.normalize_record_fields(entity_name, readback.get("fields") or {})
    if str(normalized.get(key_field) or "").strip() != expected:
        raise MediaModelFeishuWriterError(f"global {entity_name} readback key mismatch")
    return {
        "mode": mode,
        "entity": entity_name,
        "record_id": record_id,
        "fields": fields,
        "readback_payload": normalized,
    }


def _private_resource_identity(
    entity_name: str,
    payload: dict[str, Any],
) -> tuple[str, str]:
    contract = PRIVATE_ENTITY_OWNERS.get(entity_name)
    if contract is None:
        if entity_name in GLOBAL_READ_ONLY_ENTITIES:
            raise MediaModelFeishuWriterError(
                f"{entity_name} is a global read-only catalog and cannot use tenant writer"
            )
        raise MediaModelFeishuWriterError(f"{entity_name} has no canonical owner contract")
    resource_type, id_field = contract
    resource_id = str(payload.get(id_field) or "").strip()
    if not resource_id:
        raise MediaModelFeishuWriterError(
            f"{entity_name} write missing canonical owner id: {id_field}"
        )
    return resource_type, resource_id


def _register_entity_docx_link(
    owner_service: Any,
    entity_name: str,
    resource_type: str,
    resource_id: str,
    tenant_id: str,
    payload: dict[str, Any],
) -> None:
    contract = ENTITY_DOCX_LINK_FIELDS.get(entity_name)
    if contract is None:
        return
    field_name, policy = contract
    document_url = _feishu_url_value(payload.get(field_name))
    if not document_url:
        return
    owner_service.register_docx_link(
        resource_type,
        resource_id,
        session_tenant_id=tenant_id,
        document_url=document_url,
        policy=policy,
    )


def _inherit_source_asset_attachments(
    entity_name: str,
    payload: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    contract: MediaModelContract,
) -> dict[str, Any]:
    if entity_name != "SourceAsset":
        return payload
    source_url = normalize_source_url(payload.get("source_url"))
    platform = feishu_plain_text(payload.get("platform")).strip().lower()
    if not source_url or not platform:
        return payload

    source_url_field = contract.feishu_field_name("SourceAsset", "source_url")
    platform_field = contract.feishu_field_name("SourceAsset", "platform")
    inherited: dict[str, list[dict[str, str]]] = {}
    for record in records:
        fields = record.get("fields") or {}
        existing_url = normalize_source_url(_feishu_url_value(fields.get(source_url_field)))
        existing_platform = feishu_plain_text(fields.get(platform_field)).strip().lower()
        if existing_url != source_url or existing_platform != platform:
            continue
        for canonical_name in SOURCE_ASSET_ATTACHMENT_FIELDS:
            if inherited.get(canonical_name):
                continue
            display_name = contract.feishu_field_name("SourceAsset", canonical_name)
            attachments = feishu_coerce_value(fields.get(display_name), 17)
            if attachments:
                inherited[canonical_name] = attachments
        if len(inherited) == len(SOURCE_ASSET_ATTACHMENT_FIELDS):
            break
    if not inherited:
        return payload
    return {**payload, **inherited}


def _upload_missing_source_asset_attachments(
    entity_name: str,
    table_url: str,
    payload: dict[str, Any],
    attachment_paths: dict[str, str],
    *,
    contract: MediaModelContract,
) -> dict[str, Any]:
    if entity_name != "SourceAsset":
        raise MediaModelFeishuWriterError("attachment_paths are supported only for SourceAsset")
    unknown = set(attachment_paths) - set(SOURCE_ASSET_ATTACHMENT_FIELDS)
    if unknown:
        raise MediaModelFeishuWriterError(f"unsupported SourceAsset attachment fields: {sorted(unknown)}")

    missing = {
        field_name: Path(path_text)
        for field_name, path_text in attachment_paths.items()
        if not payload.get(field_name)
    }
    if not missing:
        return payload

    app_token, _table_id, token = feishu_bitable_refs(table_url)
    uploaded: dict[str, list[dict[str, str]]] = {}
    for field_name, path in missing.items():
        if not path.is_file() or path.stat().st_size <= 0:
            raise MediaModelFeishuWriterError(f"SourceAsset attachment is unavailable: {path.name}")
        if path.stat().st_size > SOURCE_ASSET_ATTACHMENT_MAX_BYTES:
            raise MediaModelFeishuWriterError(f"SourceAsset attachment exceeds direct-upload limit: {path.name}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        expected_prefix = "image/" if field_name == "cover_attachment" else "video/"
        if not content_type.startswith(expected_prefix):
            raise MediaModelFeishuWriterError(
                f"SourceAsset {field_name} has unsupported media type: {content_type}"
            )
        with path.open("rb") as handle:
            response = requests.post(
                f"{FEISHU_BASE}/drive/v1/medias/upload_all",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "file_name": path.name,
                    "parent_type": "bitable_file",
                    "parent_node": app_token,
                    "size": str(path.stat().st_size),
                },
                files={"file": (path.name, handle, content_type)},
                timeout=120,
            )
        response.raise_for_status()
        result = response.json()
        file_token = str((result.get("data") or {}).get("file_token") or "").strip()
        if result.get("code") not in (None, 0) or not file_token:
            raise MediaModelFeishuWriterError(f"failed to upload SourceAsset attachment: {path.name}")
        uploaded[field_name] = [{"file_token": file_token}]
    return {**payload, **uploaded}


def _assert_source_asset_attachment_readback(
    entity_name: str,
    written_fields: dict[str, Any],
    readback: dict[str, Any],
    contract: MediaModelContract,
) -> None:
    if entity_name != "SourceAsset":
        return
    readback_fields = readback.get("fields") or {}
    for canonical_name in SOURCE_ASSET_ATTACHMENT_FIELDS:
        display_name = contract.feishu_field_name("SourceAsset", canonical_name)
        expected = feishu_coerce_value(written_fields.get(display_name), 17)
        if not expected:
            continue
        actual = feishu_coerce_value(readback_fields.get(display_name), 17)
        expected_tokens = {str(item.get("file_token") or "") for item in expected}
        actual_tokens = {str(item.get("file_token") or "") for item in actual}
        if not expected_tokens or expected_tokens != actual_tokens:
            raise MediaModelFeishuWriterError(f"SourceAsset {canonical_name} readback mismatch")


def read_entity_record(
    table_url: str,
    record_id: str,
) -> dict[str, Any]:
    if not table_url or not record_id:
        raise MediaModelFeishuWriterError("table_url and record_id are required for readback")
    app_token, table_id, token = feishu_bitable_refs(table_url)
    resp = requests.get(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        timeout=20,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise MediaModelFeishuWriterError(f"failed to read record {record_id}: {result}")
    return result.get("data", {}).get("record", {}) or {}


def _reject_option_ids(value: Any, *, field_label: str) -> None:
    if value in (None, "", []):
        return
    if isinstance(value, str):
        if OPTION_ID_RE.match(value.strip()):
            raise MediaModelFeishuWriterError(f"{field_label} contains Feishu option id instead of display value")
        return
    if isinstance(value, list):
        for item in value:
            _reject_option_ids(item, field_label=field_label)
        return
    if isinstance(value, dict):
        for item in value.values():
            _reject_option_ids(item, field_label=field_label)
