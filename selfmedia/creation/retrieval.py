from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from common.feishu_urls import parse_feishu_document_ref
from common.social_runtime import (
    FEISHU_BASE,
    feishu_bitable_refs,
    feishu_headers,
    feishu_list_records,
    feishu_tenant_access_token,
    load_default_env_files,
    load_env_file,
)
from common.env_paths import load_media_agent_env_files
from common.resource_ownership import canonical_tenant_owned_resources, require_tenant_id

from .field_contract import CREATION_SOURCE_TABLE_CONTRACTS
from media_model.contract import MediaModelContract


DEFAULT_ACTIVITY_CONFIG = Path.home() / "openclaw-feishu-reminder" / "wiki-activity-config.json"
MEDIA_ENV_FILES = (
    Path.home() / "openclaw-agents" / "media" / ".env",
    Path.home() / "openclaw-agents" / "media" / ".env.local",
)
BUSINESS_URL_ENV_NAMES = (
    "MEDIA_OS_BUSINESS_OPPORTUNITIES_URL",
)
SOURCE_ASSET_URL_ENV_NAMES = (
    "MEDIA_OS_SOURCE_ASSETS_URL",
)
MATERIAL_DECONSTRUCTION_URL_ENV_NAMES = (
    "MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL",
)


def load_rows_for_creation(
    *,
    tenant_id: str,
    viral_url: str = "",
    activity_url: str = "",
    limit: int = 300,
    include_activity: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    load_creation_env_files()
    viral = load_material_candidate_rows_for_creation(tenant_id=tenant_id, limit=limit)
    activity = list_records_safe(resolve_activity_bitable_url(activity_url), limit=limit) if include_activity else []
    return viral, activity


def load_material_candidate_rows_for_creation(*, tenant_id: str, limit: int = 300) -> list[dict[str, Any]]:
    source_rows = [_normalize_entity_row(row, "SourceAsset") for row in list_tenant_records_safe("SourceAsset", resolve_source_assets_bitable_url(), tenant_id=tenant_id, limit=limit)]
    deconstruction_rows = [
        _normalize_entity_row(row, "MaterialDeconstruction")
        for row in list_tenant_records_safe("MaterialDeconstruction", resolve_material_deconstructions_bitable_url(), tenant_id=tenant_id, limit=limit)
    ]
    assets_by_id: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        fields = row.get("fields") or {}
        asset_id = str(fields.get("asset_id") or "").strip()
        if asset_id:
            assets_by_id[asset_id] = row

    rows: list[dict[str, Any]] = []
    used_asset_ids: set[str] = set()
    for row in deconstruction_rows:
        deconstruction_fields = dict(row.get("fields") or {})
        asset_id = str(deconstruction_fields.get("asset_id") or "").strip()
        asset = assets_by_id.get(asset_id) or {}
        asset_fields = dict(asset.get("fields") or {})
        combined = {**asset_fields, **deconstruction_fields}
        if asset_id:
            used_asset_ids.add(asset_id)
        rows.append(
            {
                "record_id": row.get("record_id"),
                "source_asset_record_id": asset.get("record_id"),
                "material_deconstruction_record_id": row.get("record_id"),
                "fields": combined,
            }
        )

    for row in source_rows:
        fields = dict(row.get("fields") or {})
        asset_id = str(fields.get("asset_id") or "").strip()
        if asset_id and asset_id in used_asset_ids:
            continue
        if fields.get("enabled") is False:
            continue
        rows.append(
            {
                "record_id": row.get("record_id"),
                "source_asset_record_id": row.get("record_id"),
                "material_deconstruction_record_id": "",
                "fields": fields,
            }
        )
    return rows[:limit]


def load_business_rows_for_creation(*, tenant_id: str, business_url: str = "", limit: int = 300) -> list[dict[str, Any]]:
    load_creation_env_files()
    return [_normalize_entity_row(row, "BusinessOpportunity") for row in list_tenant_records_safe("BusinessOpportunity", resolve_business_bitable_url(business_url), tenant_id=tenant_id, limit=limit)]


def load_inspiration_rows_for_creation(*, tenant_id: str, inspiration_url: str = "", limit: int = 300) -> list[dict[str, Any]]:
    load_creation_env_files()
    return [_normalize_entity_row(row, "CreativePattern") for row in list_tenant_records_safe("CreativePattern", resolve_inspiration_bitable_url(inspiration_url), tenant_id=tenant_id, limit=limit)]


def list_tenant_records_safe(
    entity_name: str,
    bitable_url: str,
    *,
    tenant_id: str,
    limit: int = 300,
) -> list[dict[str, Any]]:
    if not bitable_url:
        return []
    tenant_id = require_tenant_id(tenant_id)
    owner_service = canonical_tenant_owned_resources()
    resource_type, canonical_id_field = {
        "SourceAsset": ("media.source_asset", "asset_id"),
        "MaterialDeconstruction": ("media.material_deconstruction", "deconstruction_id"),
        "CreativePattern": ("media.creative_pattern", "pattern_id"),
        "BusinessOpportunity": ("media.business_opportunity", "opportunity_id"),
    }[entity_name]
    contract = MediaModelContract()
    display_id_field = contract.feishu_field_name(entity_name, canonical_id_field)
    records: list[dict[str, Any]] = []
    offset = 0
    while len(records) < limit:
        page_limit = min(500, limit - len(records))
        owners = owner_service.registry.list_by_tenant(
            tenant_id,
            resource_type=resource_type,
            limit=page_limit,
            offset=offset,
        )
        for owner in owners:
            matches = feishu_list_records(
                bitable_url,
                page_size=2,
                filter_formula=(
                    f'CurrentValue.[{display_id_field}] = '
                    f'{json.dumps(owner.canonical_resource_id, ensure_ascii=False)}'
                ),
            )
            exact = [
                record
                for record in matches
                if str(
                    contract.normalize_record_fields(entity_name, record.get("fields") or {}).get(canonical_id_field)
                    or ""
                ).strip() == owner.canonical_resource_id
            ]
            if len(exact) != 1:
                raise RuntimeError(f"{entity_name} canonical projection is missing or duplicated")
            record = exact[0]
            owner_service.assert_projection_read(
                resource_type,
                owner.canonical_resource_id,
                session_tenant_id=tenant_id,
                fields=record.get("fields") or {},
                projection_source=f"feishu:{entity_name}/{record.get('record_id') or 'missing'}",
            )
            records.append(record)
        if len(owners) < page_limit:
            break
        offset += len(owners)
    return records[:limit]


def list_records_safe(bitable_url: str, *, limit: int = 300) -> list[dict[str, Any]]:
    if not bitable_url:
        return []
    records = feishu_list_records(bitable_url, page_size=min(limit, 500))
    return records[:limit]


def _normalize_entity_row(row: dict[str, Any], entity_name: str) -> dict[str, Any]:
    if not row:
        return row
    contract = MediaModelContract()
    normalized = dict(row)
    normalized["fields"] = contract.normalize_record_fields(entity_name, dict(row.get("fields") or {}))
    return normalized


def resolve_viral_bitable_url(explicit: str = "") -> str:
    return resolve_material_deconstructions_bitable_url()


def resolve_source_assets_bitable_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    load_creation_env_files()
    for name in SOURCE_ASSET_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def resolve_material_deconstructions_bitable_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    load_creation_env_files()
    for name in MATERIAL_DECONSTRUCTION_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def resolve_activity_bitable_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    env_url = os.getenv("MEDIA_OS_ACTIVITY_URL")
    if env_url:
        return env_url
    cfg_path = Path(os.getenv("OPENCLAW_ACTIVITY_CONFIG_PATH", str(DEFAULT_ACTIVITY_CONFIG))).expanduser()
    cfg = _load_json(cfg_path)
    return _bitable_url_from_config(cfg)


def resolve_business_bitable_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    load_creation_env_files()
    for name in BUSINESS_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def resolve_inspiration_bitable_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    load_creation_env_files()
    for name in CREATION_SOURCE_TABLE_CONTRACTS["inspiration"]["env"]:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def load_creation_env_files() -> None:
    load_default_env_files()
    configured_root = os.getenv("OPENCLAW_MEDIA_AGENT_ROOT", "").strip()
    if configured_root:
        # Same env-loading shape as id_business.py/feishu_writer.py once
        # OPENCLAW_MEDIA_AGENT_ROOT is set explicitly.
        load_media_agent_env_files(Path(configured_root).expanduser())
        return
    # No OPENCLAW_MEDIA_AGENT_ROOT: this module's own fallback chain
    # (OPENCLAW_MEDIA_ENV_FILE, then ~/openclaw-agents/media) stays as-is --
    # it is not shared with id_business.py/feishu_writer.py's default.
    env_override = os.getenv("OPENCLAW_MEDIA_ENV_FILE", "").strip()
    env_files = (Path(env_override).expanduser(),) if env_override else MEDIA_ENV_FILES
    for path in env_files:
        load_env_file(path)


def read_reference_docs(doc_urls: list[str], *, max_chars_per_doc: int = 1800) -> list[dict[str, str]]:
    load_default_env_files()
    token = feishu_tenant_access_token()
    results: list[dict[str, str]] = []
    for url in doc_urls:
        document_id = _extract_docx_token(url)
        if not document_id:
            continue
        try:
            content = read_docx_raw_content(document_id, token)
        except Exception as exc:
            results.append({"url": url, "content": "", "error": str(exc)})
            continue
        results.append({"url": url, "content": content[:max_chars_per_doc], "error": ""})
    return results


def read_docx_raw_content(document_id: str, token: str) -> str:
    resp = requests.get(
        f"{FEISHU_BASE}/docx/v1/documents/{document_id}/raw_content",
        headers=feishu_headers(token),
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"读取飞书文档纯文本失败：{payload}")
    return str((payload.get("data") or {}).get("content") or "")


def resolve_wiki_node(token_value: str) -> dict[str, Any]:
    load_default_env_files()
    token = feishu_tenant_access_token()
    resp = requests.get(
        f"{FEISHU_BASE}/wiki/v2/spaces/get_node",
        params={"token": token_value},
        headers=feishu_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"获取知识库节点失败：{payload}")
    return payload.get("data", {}).get("node") or {}


def bitable_refs_from_url(bitable_url: str) -> tuple[str, str, str]:
    load_default_env_files()
    return feishu_bitable_refs(bitable_url)


def _bitable_url_from_config(cfg: dict[str, Any]) -> str:
    url = str(cfg.get("url") or "").strip()
    app_token = str(cfg.get("app_token") or cfg.get("node_token") or "").strip()
    table_id = str(cfg.get("table_id") or "").strip()
    if url and "table=" in url:
        return url
    if url and table_id:
        joiner = "&" if "?" in url else "?"
        return f"{url}{joiner}table={table_id}"
    if app_token and table_id:
        return f"https://tcnwueberajc.feishu.cn/base/{app_token}?table={table_id}"
    return url


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_docx_token(url: str) -> str:
    # hosts=None: this call site has never validated the doc URL's host and
    # isn't being tightened this round for lack of test coverage over real
    # production doc_link data (see the url-7/FC-10 dedup audit).
    # Only accept a "docx" ref (never "wiki") -- this token is passed
    # straight into the docx raw_content API, so a wiki node token would
    # be silently wrong rather than merely a missed match.
    ref = parse_feishu_document_ref(url, hosts=None, allow_bare_token=True)
    return ref["token"] if ref and ref["kind"] == "docx" else ""
