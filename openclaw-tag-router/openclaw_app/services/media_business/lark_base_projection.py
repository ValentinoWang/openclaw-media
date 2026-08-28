"""Read-only Feishu Base to Media Product projection.

The Base remains authoritative for B-tenant records.  This module only reads
Base records and writes the tenant-scoped PostgreSQL read model.  Every write
uses ``(tenant_id, public_id)`` as its idempotency identity, so a rerun updates
the existing row instead of creating a duplicate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from psycopg import sql
from media_model.platform_hashtags import normalize_platform_hashtags


TARGET_TENANT_ID = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
DEFAULT_REGISTRY_PATH = Path(
    os.getenv("OPENCLAW_MEDIA_BITABLE_REGISTRY_PATH")
    or Path.home() / "openclaw-feishu-reminder" / "media-bitable-registry.json"
).expanduser()
REGISTRY_VERSION = "media_operations_registry_v2"


@dataclass(frozen=True)
class BaseTableSpec:
    table_key: str
    target_table: str
    id_fields: tuple[str, ...]
    alias_fields: Mapping[str, tuple[str, ...]]


# This is the explicit, reviewed mapping from the Media OS Base contract to
# the media_product read model. Physical table IDs come only from registry v2.
TABLE_SPECS: tuple[BaseTableSpec, ...] = (
    BaseTableSpec("source_asset", "assets", ("素材ID",), {"title": ("标题", "原作品标题"), "name": ("标题",), "status": ("素材状态",), "asset_id": ("素材ID",)}),
    BaseTableSpec("material_deconstruction", "material_deconstructions", ("拆解ID",), {"title": ("摘要",), "name": ("拆解ID",), "status": ("人工复核状态",), "asset_id": ("素材ID",)}),
    BaseTableSpec("creative_pattern", "creative_patterns", ("模式ID",), {"title": ("模式名称",), "name": ("模式ID",), "status": ("模式状态",)}),
    BaseTableSpec("creation_run", "creation_runs", ("创作运行ID",), {"title": ("输入需求摘要",), "name": ("创作运行ID",), "status": ("状态",), "state": ("状态",), "platform": ("平台",), "contentType": ("内容类型",), "trackName": ("赛道",)}),
    BaseTableSpec("post_review", "review_records", ("发布作品ID",), {"title": ("发布作品ID",), "name": ("发布作品ID",), "status": ("表现评级",), "state": ("复盘节点",)}),
    BaseTableSpec("business_account", "business_accounts", ("商务账号ID",), {"title": ("账号名称快照",), "name": ("商务账号ID",), "status": ("平台",)}),
    BaseTableSpec("business_opportunity", "business_opportunities", ("商务机会ID",), {"title": ("品牌", "产品"), "name": ("商务机会ID",), "status": ("档期",)}),
    BaseTableSpec("creator_profile", "creator_profiles", ("达人档案ID",), {"title": ("账号名称",), "name": ("达人档案ID",), "status": ("平台",)}),
    BaseTableSpec("track", "tracks", ("赛道ID",), {"title": ("赛道名称",), "name": ("赛道ID",), "status": ("状态",)}),
    BaseTableSpec("material_usage", "material_usages", ("使用ID",), {"title": ("使用方式",), "name": ("使用ID",), "status": ("效果回流摘要",), "asset_id": ("素材ID",)}),
    BaseTableSpec("decision_trace", "decision_traces", ("决策轨迹ID",), {"title": ("候选记录ID",), "name": ("决策轨迹ID",), "status": ("是否入选",), "state": ("候选类型",)}),
    BaseTableSpec("track_creator_membership", "track_creator_memberships", ("关系ID",), {"title": ("账号名称快照",), "name": ("关系ID",), "status": ("状态",), "state": ("赛道角色",)}),
    BaseTableSpec("post_metric_snapshot", "metric_snapshots", ("快照ID",), {"title": ("原始指标名",), "name": ("快照ID",), "status": ("数据质量",), "state": ("指标键",)}),
    BaseTableSpec("account_metric_snapshot", "account_metric_snapshots", ("快照ID",), {"title": ("博主昵称", "原始指标名"), "name": ("快照ID",), "status": ("数据质量",), "state": ("指标键",)}),
    BaseTableSpec("growth_summary", "growth_summaries", ("产物ID", "增长摘要ID", "摘要ID"), {"title": ("展示标题", "标题", "摘要"), "name": ("产物ID", "增长摘要ID", "摘要ID"), "status": ("状态",), "state": ("质量状态",)}),
)

_AUXILIARY_TABLE_TARGETS = {"platform_event": "external_signals"}
_PENDING_TABLE_TARGETS = {"candidate_topic": "candidate_topics"}
_BINDING_STATUSES = frozenset({"snapshot_only", "readback_verified_current", "target_applied_verified"})
_PENDING_BINDING_STATUS = "pending_create"

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_FEISHU_DOCUMENT_ROOT_HOSTS = frozenset({"feishu.cn", "larksuite.com", "larkoffice.com"})
_FEISHU_DOCUMENT_HOST_SUFFIXES = (".feishu.cn", ".larksuite.com", ".larkoffice.com")
_FEISHU_DOCUMENT_PATH = re.compile(r"^/(wiki|docx)/([A-Za-z0-9_-]{8,160})$")
_PREVIEW_PATH = "/openclaw/media/api/assets/{public_asset_id}/preview"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, Mapping):
        # Feishu URL and user values are intentionally retained as structured
        # JSON, while aliases use their human-readable text.
        return str(value.get("text") or value.get("name") or value.get("link") or "").strip()
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value if _text(item))
    return str(value).strip()


def _review_document_url(value: Any) -> str | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        host = str(parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    if port is not None or parsed.query or parsed.fragment or parsed.params:
        return None
    if not (
        host in _FEISHU_DOCUMENT_ROOT_HOSTS
        or any(host.endswith(suffix) for suffix in _FEISHU_DOCUMENT_HOST_SUFFIXES)
    ):
        return None
    path_match = _FEISHU_DOCUMENT_PATH.fullmatch(parsed.path)
    if path_match is None:
        return None
    document_type, token = path_match.groups()
    return f"https://{host}/{document_type}/{token}"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _cover_attachment(value: Any) -> Mapping[str, Any] | None:
    candidates = value if isinstance(value, list) else [value]
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("name"))
        mime_type = _text(item.get("type") or item.get("mime_type"))
        if name or mime_type.startswith("image/"):
            return item
    return None


def _alias(fields: Mapping[str, Any], candidates: Iterable[str]) -> str:
    for key in candidates:
        value = _text(fields.get(key))
        if value:
            return value
    return ""


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value if (text := _text(item))]
    text = _text(value)
    return [text] if text else []


def _number(fields: Mapping[str, Any], candidates: Iterable[str]) -> int | float:
    text = _alias(fields, candidates)
    if not text:
        raise RuntimeError("numeric Base field is missing")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise RuntimeError("numeric Base field is invalid") from exc
    if not value.is_finite():
        raise RuntimeError("numeric Base field is invalid")
    return int(value) if value == value.to_integral_value() else float(value)


def _timestamp_text(value: Any) -> str:
    if isinstance(value, bool):
        raise RuntimeError("Base record timestamp is invalid")
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if abs(float(value)) >= 100_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.isdigit():
            return _timestamp_text(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("Base record timestamp is invalid") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise RuntimeError("Base record timestamp is missing")


def _evidence_quality(value: Any) -> str:
    source = _text(value).lower()
    mapping = {
        "verified": "verified",
        "已验证": "verified",
        "partial": "partial",
        "部分验证": "partial",
        "screenshot_only": "partial",
        "unverified": "unverified",
        "未验证": "unverified",
        "unavailable": "unavailable",
        "不可用": "unavailable",
    }
    return mapping.get(source, "unverified")


def _safe_key(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return value or "record"


def _stable_public_id(spec: BaseTableSpec, fields: Mapping[str, Any], record_id: str) -> str:
    raw = ""
    for key in spec.id_fields:
        value = _text(fields.get(key))
        if value:
            raw = value
            break
    if not raw:
        raw = f"lark-{_safe_key(spec.table_key)}-{record_id}"
    if _PUBLIC_ID.fullmatch(raw):
        return raw
    safe = _safe_key(raw)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    safe = safe[:149]
    normalized = f"{safe}_{digest}"
    if len(normalized) < 8:
        normalized = f"lark_{normalized}"
    if _PUBLIC_ID.fullmatch(normalized) is None:
        raise RuntimeError("unable to derive a valid public id")
    return normalized


def _source_version(table_id: str, table_revision: Any, record_id: str, fields: Mapping[str, Any]) -> str:
    # Bitable records do not expose a record revision in all API versions.
    # Include a deterministic field digest so a changed record is observed.
    digest = hashlib.sha256(json.dumps(_json_safe(fields), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    return f"lark-base:{table_id}:r{table_revision}:{record_id}:{digest}"


class LarkBaseProjection:
    """Discover and project the reviewed Media OS Base tables."""

    def __init__(
        self,
        feishu_service: Any,
        connection_factory: Any,
        *,
        tenant_id: str = TARGET_TENANT_ID,
        base_token: str = "",
        registry: Mapping[str, Any] | None = None,
        registry_path: str | Path | None = None,
    ):
        self.feishu = feishu_service
        self.connection_factory = connection_factory
        self.tenant_id = tenant_id
        self.base_token = str(base_token or "").strip()
        self.registry = registry
        self.registry_path = Path(registry_path) if registry_path is not None else DEFAULT_REGISTRY_PATH
        self._live_bindings: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    @staticmethod
    def _required_registry_text(row: Mapping[str, Any], field: str, code: str = "INVALID_REGISTRY") -> str:
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"{code}: {field}")
        return value.strip()

    def _load_registry(self) -> Mapping[str, Any]:
        if self.registry is not None:
            document = self.registry
        else:
            if not self.registry_path.is_file():
                raise RuntimeError(f"REGISTRY_UNAVAILABLE: {self.registry_path}")
            try:
                document = json.loads(self.registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"REGISTRY_INVALID: {self.registry_path}") from exc
        if not isinstance(document, Mapping):
            raise RuntimeError("REGISTRY_INVALID: document must be an object")
        return document

    def _validated_registry(
        self,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        document = self._load_registry()
        if document.get("version") != REGISTRY_VERSION:
            raise RuntimeError(f"REGISTRY_VERSION: expected {REGISTRY_VERSION}")

        raw_bases = document.get("bases")
        if not isinstance(raw_bases, list):
            raise RuntimeError("INVALID_REGISTRY: bases must be a list")
        bases: dict[str, dict[str, Any]] = {}
        base_tokens: dict[str, str] = {}
        for index, raw_base in enumerate(raw_bases):
            if not isinstance(raw_base, Mapping):
                raise RuntimeError(f"INVALID_REGISTRY: bases[{index}]")
            base = dict(raw_base)
            base_key = self._required_registry_text(base, "base_key", "INVALID_BASE_KEY")
            base_token = self._required_registry_text(base, "base_token", "INVALID_BASE_TOKEN")
            if not _IDENTIFIER.fullmatch(base_key):
                raise RuntimeError(f"INVALID_BASE_KEY: {base_key}")
            if base_key in bases:
                raise RuntimeError(f"DUPLICATE_BASE_KEY: {base_key}")
            if base_token in base_tokens:
                raise RuntimeError(f"DUPLICATE_BASE_TOKEN: {base_token}")
            bases[base_key] = base
            base_tokens[base_token] = base_key
        if "media_operations" not in bases:
            raise RuntimeError("BASE_MEMBERSHIP: media_operations base is missing")

        expected = {spec.table_key: spec for spec in TABLE_SPECS}
        allowed_targets = {spec.table_key: spec.target_table for spec in TABLE_SPECS}
        allowed_targets.update(_AUXILIARY_TABLE_TARGETS)
        allowed_targets.update(_PENDING_TABLE_TARGETS)
        raw_tables = document.get("tables")
        if not isinstance(raw_tables, list):
            raise RuntimeError("INVALID_REGISTRY: tables must be a list")
        active: dict[str, dict[str, Any]] = {}
        pending: dict[str, dict[str, Any]] = {}
        physical_ids: dict[str, str] = {}
        for index, raw_table in enumerate(raw_tables):
            if not isinstance(raw_table, Mapping):
                raise RuntimeError(f"INVALID_BINDING: tables[{index}]")
            table = dict(raw_table)
            if table.get("resource_scope") != "table" or table.get("resource_type") != "table":
                raise RuntimeError(f"INVALID_BINDING: tables[{index}]")
            table_key = self._required_registry_text(table, "table_key", "INVALID_TABLE_KEY")
            if not _IDENTIFIER.fullmatch(table_key):
                raise RuntimeError(f"INVALID_TABLE_KEY: {table_key}")
            if table_key not in allowed_targets:
                raise RuntimeError(f"UNKNOWN_TABLE_KEY: {table_key}")
            if table_key in active or table_key in pending:
                raise RuntimeError(f"DUPLICATE_TABLE_KEY: {table_key}")
            table_id = self._required_registry_text(table, "table_id", "INVALID_TABLE_ID")
            if any(character.isspace() for character in table_id):
                raise RuntimeError(f"INVALID_TABLE_ID: {table_key}")
            if table_id in physical_ids:
                raise RuntimeError(f"DUPLICATE_TABLE_ID: {table_id}")
            base_key = self._required_registry_text(table, "base_key", "INVALID_BASE_KEY")
            base_token = self._required_registry_text(table, "base_token", "INVALID_BASE_TOKEN")
            base = bases.get(base_key)
            if base is None or base.get("base_token") != base_token:
                raise RuntimeError(f"BASE_MEMBERSHIP: {table_key}")
            if table_key in expected and base_key != "media_operations":
                raise RuntimeError(f"BASE_MEMBERSHIP: {table_key}")
            postgres_target = self._required_registry_text(table, "postgres_target")
            if postgres_target != allowed_targets[table_key]:
                raise RuntimeError(f"POSTGRES_TARGET_MISMATCH: {table_key}")
            binding_status = self._required_registry_text(table, "binding_status")
            if binding_status == _PENDING_BINDING_STATUS:
                raise RuntimeError(f"PENDING_BINDING: {table_key}")
            if binding_status not in _BINDING_STATUSES:
                raise RuntimeError(f"INVALID_BINDING_STATUS: {table_key}")
            active[table_key] = table
            physical_ids[table_id] = table_key

        required_table_keys = set(expected) | set(_AUXILIARY_TABLE_TARGETS)
        missing = sorted(required_table_keys - set(active))
        if missing:
            raise RuntimeError(f"MISSING_TABLE_BINDING: {', '.join(missing)}")

        raw_pending = document.get("pending_tables")
        if not isinstance(raw_pending, list):
            raise RuntimeError("INVALID_REGISTRY: pending_tables must be a list")
        for index, raw_table in enumerate(raw_pending):
            if not isinstance(raw_table, Mapping):
                raise RuntimeError(f"INVALID_PENDING_BINDING: pending_tables[{index}]")
            table = dict(raw_table)
            if table.get("resource_scope") != "table" or table.get("resource_type") != "table":
                raise RuntimeError(f"INVALID_PENDING_BINDING: pending_tables[{index}]")
            if "table_id" in table:
                raise RuntimeError("INVALID_PENDING_BINDING: table_id is forbidden")
            table_key = self._required_registry_text(table, "table_key", "INVALID_TABLE_KEY")
            if not _IDENTIFIER.fullmatch(table_key):
                raise RuntimeError(f"INVALID_TABLE_KEY: {table_key}")
            if table_key in active or table_key in pending:
                raise RuntimeError(f"DUPLICATE_TABLE_KEY: {table_key}")
            if table_key not in allowed_targets:
                raise RuntimeError(f"UNKNOWN_TABLE_KEY: {table_key}")
            base_key = self._required_registry_text(table, "base_key", "INVALID_BASE_KEY")
            base_token = self._required_registry_text(table, "base_token", "INVALID_BASE_TOKEN")
            base = bases.get(base_key)
            if base is None or base.get("base_token") != base_token:
                raise RuntimeError(f"BASE_MEMBERSHIP: {table_key}")
            postgres_target = self._required_registry_text(table, "postgres_target")
            if postgres_target != allowed_targets[table_key]:
                raise RuntimeError(f"POSTGRES_TARGET_MISMATCH: {table_key}")
            binding_status = self._required_registry_text(table, "binding_status")
            if binding_status != _PENDING_BINDING_STATUS:
                raise RuntimeError(f"INVALID_PENDING_BINDING: {table_key}")
            pending[table_key] = table
        return bases, active, pending

    def resolve_base_token(self) -> str:
        bases, _active, _pending = self._validated_registry()
        configured = self.base_token
        resolved = str(bases["media_operations"]["base_token"]).strip()
        if configured and configured != resolved:
            raise RuntimeError("BASE_MEMBERSHIP: configured base token is not registry media_operations")
        self.base_token = resolved
        return resolved

    def resolve_table_binding(self, table_key: str) -> dict[str, Any]:
        _bases, active, pending = self._validated_registry()
        if table_key in pending:
            raise RuntimeError(f"PENDING_BINDING: {table_key}")
        binding = active.get(table_key)
        if binding is None:
            raise RuntimeError(f"UNKNOWN_TABLE_KEY: {table_key}")
        return dict(binding)

    def _tables(self, base_token: str) -> dict[str, dict[str, Any]]:
        resolved = str(base_token or "").strip()
        if not resolved:
            raise RuntimeError("INVALID_BASE_TOKEN: table listing requires a registry base token")
        tables: dict[str, dict[str, Any]] = {}
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            payload = self.feishu._request("GET", f"/bitable/v1/apps/{resolved}/tables", params=params)
            data = payload.get("data") if isinstance(payload, Mapping) else None
            if not isinstance(data, Mapping):
                raise RuntimeError("INVALID_TABLE_LIST: data must be an object")
            items = data.get("items") or []
            if not isinstance(items, list):
                raise RuntimeError("INVALID_TABLE_LIST: items must be a list")
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                table_id = _text(item.get("table_id"))
                if not table_id:
                    continue
                if table_id in tables:
                    raise RuntimeError(f"DUPLICATE_TABLE_ID: {table_id}")
                tables[table_id] = dict(item)
            if not data.get("has_more"):
                return tables
            next_token = str(data.get("page_token") or "")
            if not next_token or next_token == page_token:
                raise RuntimeError("Bitable table pagination did not advance")
            page_token = next_token

    def _preflight_live_bindings(
        self,
    ) -> tuple[dict[str, tuple[dict[str, Any], dict[str, Any]]], list[dict[str, str | None]]]:
        """Validate every registry binding before reading any Base records."""
        bases, active, _pending = self._validated_registry()
        table_tokens = {str(binding["base_token"]) for binding in active.values()}
        tables_by_token = {token: self._tables(token) for token in sorted(table_tokens)}
        runtime: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        warnings: list[dict[str, str | None]] = []
        for table_key, binding in active.items():
            base_key = str(binding["base_key"])
            base = bases.get(base_key)
            if base is None or base.get("base_token") != binding["base_token"]:
                raise RuntimeError(f"BASE_MEMBERSHIP: {table_key}")
            table_id = str(binding["table_id"])
            tables = tables_by_token[str(binding["base_token"])]
            if table_id not in tables:
                raise RuntimeError(f"MISSING_TABLE_BINDING: {table_key}={table_id}")
            table = tables[table_id]
            observed_name = table.get("name")
            observed_name = None if observed_name is None else str(observed_name).strip()
            registry_name = binding.get("observed_feishu_table_display_name")
            registry_name = None if registry_name is None else str(registry_name).strip()
            if observed_name != registry_name:
                warnings.append(
                    {
                        "code": "DISPLAY_NAME_DRIFT",
                        "table_key": table_key,
                        "observed_name": observed_name,
                        "target_name": str(binding.get("target_feishu_table_display_name") or ""),
                    }
                )
            runtime[table_key] = (binding, table)
        return runtime, warnings

    def fetch_records(self) -> tuple[list[tuple[BaseTableSpec, dict[str, Any], dict[str, Any]]], dict[str, Any]]:
        resolved = self.resolve_base_token()
        runtime, warnings = self._preflight_live_bindings()
        self._live_bindings = runtime
        output: list[tuple[BaseTableSpec, dict[str, Any], dict[str, Any]]] = []
        stats: dict[str, Any] = {"base_token": resolved, "tables": {}, "skipped_tenant": 0, "warnings": warnings}
        for spec in TABLE_SPECS:
            binding, table = runtime[spec.table_key]
            table_id = str(binding["table_id"])
            records = self.feishu.list_bitable_records(
                str(binding["base_token"]),
                table_id,
                page_size=500,
                automatic_fields=True,
            )
            table_stats = stats["tables"].setdefault(spec.table_key, {"table_id": table_id, "source_count": len(records), "eligible_count": 0})
            for record in records:
                fields = record.get("fields") if isinstance(record, Mapping) else {}
                fields = fields if isinstance(fields, Mapping) else {}
                source_tenant = _text(fields.get("租户ID"))
                if source_tenant and source_tenant != self.tenant_id:
                    stats["skipped_tenant"] += 1
                    continue
                table_stats["eligible_count"] += 1
                output.append(
                    (
                        spec,
                        dict(table),
                        {
                            "record_id": str(record.get("record_id") or record.get("id") or ""),
                            "created_time": record.get("created_time"),
                            "last_modified_time": record.get("last_modified_time"),
                            "fields": _json_safe(fields),
                        },
                    )
                )
        stats["eligible_count"] = len(output)
        return output, stats

    def _activity_candidate_index(self) -> tuple[dict[str, dict[str, str]], int]:
        try:
            binding, _table = self._live_bindings["platform_event"]
        except (AttributeError, KeyError) as exc:
            raise RuntimeError("LIVE_BINDINGS_UNAVAILABLE: platform_event") from exc
        app_token = str(binding["base_token"])
        table_id = str(binding["table_id"])
        records = self.feishu.list_bitable_records(
            app_token,
            table_id,
            page_size=500,
            automatic_fields=True,
        )
        candidates: dict[str, dict[str, str]] = {}
        for record in records:
            fields = record.get("fields") if isinstance(record, Mapping) else {}
            fields = fields if isinstance(fields, Mapping) else {}
            title = _alias(fields, ("标题",))
            if not title:
                continue
            candidate = {
                "title": title,
                "platform": _alias(fields, ("平台名称",)) or "未标注",
                "sourceType": "activity",
            }
            record_id = str(record.get("record_id") or record.get("id") or "")
            relation_id = _alias(fields, ("关联ID",))
            for candidate_id in (record_id, relation_id):
                if candidate_id:
                    candidates[candidate_id] = candidate
        return candidates, len(records)

    def _candidate_index(
        self,
        rows: list[tuple[BaseTableSpec, dict[str, Any], dict[str, Any]]],
    ) -> tuple[dict[str, dict[str, str]], int]:
        candidates: dict[str, dict[str, str]] = {}
        source_types = {
            "assets": "material",
            "material_deconstructions": "deconstruction",
            "creative_patterns": "pattern",
            "business_opportunities": "business",
            "creator_profiles": "creator",
        }
        has_activity_candidates = False
        for spec, _table, record in rows:
            fields = record.get("fields") or {}
            if spec.target_table == "decision_traces":
                has_activity_candidates = has_activity_candidates or _alias(fields, ("候选类型",)) == "activity"
                continue
            title = _alias(fields, spec.alias_fields.get("title", ()))
            if title:
                candidates[_stable_public_id(spec, fields, str(record.get("record_id") or ""))] = {
                    "title": title,
                    "platform": _alias(fields, ("平台",)) or "未标注",
                    "sourceType": source_types.get(spec.target_table, ""),
                    "trackName": _alias(fields, ("赛道", "赛道名称")) or "未标注",
                }
        activity_count = 0
        if has_activity_candidates:
            activity_candidates, activity_count = self._activity_candidate_index()
            candidates.update(activity_candidates)
        return candidates, activity_count

    @staticmethod
    def _canonical_data(
        spec: BaseTableSpec,
        table: Mapping[str, Any],
        record: Mapping[str, Any],
        candidate_facts: Mapping[str, Mapping[str, str]] | None = None,
    ) -> dict[str, Any]:
        fields = dict(record.get("fields") or {})
        aliases = {name: _alias(fields, candidates) for name, candidates in spec.alias_fields.items()}
        aliases = {key: value for key, value in aliases.items() if value}
        canonical = {
            "source": {
                "provider": "feishu",
                "base_table": str(table.get("name") or spec.table_key),
                "table_id": str(table.get("table_id") or ""),
                "record_id": str(record.get("record_id") or ""),
            },
            "aliases": aliases,
            **aliases,
        }
        if spec.target_table != "assets":
            canonical["fields"] = fields
        if spec.target_table == "assets":
            media_type = "视频" if fields.get("视频附件") else "图片" if fields.get("封面附件") else "链接"
            source_url = _alias(fields, ("来源链接",))
            canonical.update(
                {
                    "title": aliases.get("title") or "未命名素材",
                    "mediaType": media_type,
                    "platform": _alias(fields, ("平台",)) or "未标注",
                    "sourceLabel": _alias(fields, ("账号名称快照", "平台")) or "飞书素材库",
                    "platform_hashtags": normalize_platform_hashtags(
                        fields.get("平台话题标签")
                    ),
                    "trackNames": _strings(fields.get("赛道") or fields.get("赛道名称")),
                    "qualityStatus": _evidence_quality(
                        fields.get("证据质量") or fields.get("数据质量")
                    ),
                    "materialStatus": aliases.get("status") or "状态待确认",
                }
            )
            if source_url:
                canonical["source_url"] = source_url
            cover = _cover_attachment(fields.get("封面附件"))
            if cover is not None:
                public_asset_id = _stable_public_id(spec, fields, str(record.get("record_id") or ""))
                preview: dict[str, Any] = {
                    "kind": "image",
                    "status": "available",
                    "url": _PREVIEW_PATH.format(public_asset_id=public_asset_id),
                    # This is only a display selector. The file token is read
                    # from the current Base record when the preview is served.
                    "attachmentName": _text(cover.get("name")),
                }
                mime_type = _text(cover.get("type") or cover.get("mime_type"))
                if mime_type.startswith("image/"):
                    preview["contentType"] = mime_type
                canonical["preview"] = preview
        elif spec.target_table == "creation_runs":
            canonical.update(
                {
                    "title": aliases.get("title") or "未命名创作运行",
                    "platform": aliases.get("platform"),
                    "contentType": aliases.get("contentType"),
                    "trackName": aliases.get("trackName"),
                    "entrypoint": _alias(fields, ("入口标签", "生成来源")) or "飞书历史导入",
                    "status": aliases.get("status") or "unknown",
                    "availableSections": [],
                }
            )
        elif spec.target_table == "decision_traces":
            selected = fields.get("是否入选")
            candidate_id = aliases.get("title") or ""
            candidate_type = _alias(fields, ("候选类型",))
            candidate = (candidate_facts or {}).get(candidate_id, {})
            candidate_title = candidate.get("title")
            if not candidate_title:
                candidate_title = {
                    "activity": "活动候选（标题待同步）",
                    "material": "素材候选（标题待同步）",
                    "deconstruction": "拆解候选（标题待同步）",
                    "pattern": "创作模式候选（标题待同步）",
                    "business": "商务候选（标题待同步）",
                    "creator": "达人候选（标题待同步）",
                }.get(candidate_type, "候选标题待同步")
            canonical.update(
                {
                    "candidateTitle": candidate_title,
                    "candidateType": candidate_type,
                    "platform": candidate.get("platform") or "未标注",
                    "trackName": candidate.get("trackName") or "未标注",
                    "decisionStatus": "recommended" if selected is True else "candidate",
                    "evidenceRefs": [],
                    "evidenceCount": 0,
                }
            )
        elif spec.target_table == "business_opportunities":
            canonical.update(
                {
                    "brand": _alias(fields, ("品牌",)) or "品牌待确认",
                    "product": _alias(fields, ("产品",)) or "产品待确认",
                    "platform": _alias(fields, ("平台",)) or "平台待确认",
                    "contentType": _alias(fields, ("内容类型",)) or "内容类型待确认",
                    "validFrom": fields.get("有效开始时间"),
                    "validUntil": fields.get("有效结束时间"),
                    "authorizationScope": _alias(fields, ("授权范围",)) or "授权范围待确认",
                    "status": _alias(fields, ("状态", "档期")) or "状态待确认",
                }
            )
        elif spec.target_table == "creator_profiles":
            canonical.update(
                {
                    "account_name": _alias(fields, ("账号名称",)),
                    "platform": _alias(fields, ("平台",)),
                    "author_id": _alias(fields, ("作者ID",)) or None,
                    "creator_role": _alias(fields, ("创作者角色",)),
                    "identity_tags": _strings(fields.get("身份标签")),
                    "expertise_domains": _strings(fields.get("专业能力领域")),
                    "profile_url": _alias(fields, ("主页链接",)) or None,
                    "avatar_url": _alias(fields, ("头像链接",)) or None,
                }
            )
        elif spec.target_table == "tracks":
            parent_id = _alias(fields, ("父赛道ID",))
            canonical.update(
                {
                    "track_name": _alias(fields, ("赛道名称",)),
                    "description": _alias(fields, ("赛道说明",)),
                    "status": _alias(fields, ("状态",)),
                    "platforms": _strings(fields.get("适用平台")),
                    "aliases": _strings(fields.get("赛道别名")),
                    "artifact_count": 0,
                    "parent_track_id": (
                        _stable_public_id(spec, {"赛道ID": parent_id}, f"parent-{parent_id}")
                        if parent_id
                        else None
                    ),
                }
            )
        elif spec.target_table == "track_creator_memberships":
            track_spec = next(item for item in TABLE_SPECS if item.target_table == "tracks")
            canonical.update(
                {
                    "public_track_id": _stable_public_id(
                        track_spec,
                        {"赛道ID": _alias(fields, ("赛道ID",))},
                        str(record.get("record_id") or "track"),
                    ),
                    "public_creator_id": _alias(fields, ("达人档案ID",)),
                    "role": _alias(fields, ("赛道角色",)),
                    "fit_score": _number(fields, ("匹配分",)),
                    "fit_reason": _alias(fields, ("匹配理由",)),
                    "status": _alias(fields, ("状态",)),
                    "last_evaluated_at": _timestamp_text(fields.get("最近评估时间")),
                }
            )
        elif spec.target_table in {"metric_snapshots", "account_metric_snapshots"}:
            is_account = spec.target_table == "account_metric_snapshots"
            subject_id = _alias(fields, ("达人档案ID",)) if is_account else _alias(fields, ("发布作品ID",))
            canonical.update(
                {
                    "subject_type": "account" if is_account else "content",
                    "public_subject_id": subject_id,
                    "review_window": "custom",
                    "metric_key": _alias(fields, ("指标键",)),
                    "metric_value": _number(fields, ("指标值",)),
                    "unit": _alias(fields, ("单位",)) or "count",
                    "evidence_quality": _evidence_quality(fields.get("数据质量")),
                    # A bulk Base edit can give distinct snapshots the same
                    # last-modified time. Record creation is the stable
                    # collection timestamp; modified time is only a fallback.
                    "collected_at": _timestamp_text(
                        record.get("created_time") or record.get("last_modified_time")
                    ),
                }
            )
        elif spec.target_table == "review_records":
            human_decision = _alias(fields, ("表现评级",)) or None
            canonical.update(
                {
                    "public_post_id": _alias(fields, ("发布作品ID",)),
                    "platform": _alias(fields, ("平台",)) or "平台待确认",
                    "snapshot_24h": None,
                    "snapshot_7d": None,
                    "evidence_quality": "partial",
                    "model_suggestion": _alias(fields, ("关键指标摘要",)) or None,
                    "human_decision": human_decision,
                    "status": "confirmed" if human_decision else "pending",
                    "document_url": _review_document_url(fields.get("复盘文档链接")),
                }
            )
        return canonical

    def project(self, *, dry_run: bool = True, target_tables: set[str] | None = None) -> dict[str, Any]:
        rows, stats = self.fetch_records()
        candidate_facts, activity_source_count = self._candidate_index(rows)
        selected_rows = [row for row in rows if target_tables is None or row[0].target_table in target_tables]
        stats.update({"dry_run": dry_run, "inserted": 0, "updated": 0, "unchanged": 0, "errors": []})
        stats["candidate_title_sources"] = {
            "resolved_id_count": len(candidate_facts),
            "activity_record_count": activity_source_count,
        }
        stats["selected_count"] = len(selected_rows)
        if dry_run:
            for spec, table, record in selected_rows:
                record_id = str(record.get("record_id") or "")
                if not record_id:
                    raise RuntimeError(f"{spec.table_key} contains a record without an id")
                if not _IDENTIFIER.fullmatch(spec.target_table):
                    raise RuntimeError(f"invalid target table: {spec.target_table}")
                fields = record.get("fields") or {}
                _stable_public_id(spec, fields, record_id)
                self._canonical_data(spec, table, record, candidate_facts)
                _source_version(
                    str(table.get("table_id") or ""),
                    table.get("revision", "unknown"),
                    record_id,
                    fields,
                )
            stats["would_project"] = len(selected_rows)
            return stats
        with self.connection_factory() as connection:
            try:
                for spec, table, record in selected_rows:
                    record_id = str(record.get("record_id") or "")
                    if not record_id:
                        stats["errors"].append({"table": spec.table_key, "error": "missing record id"})
                        continue
                    fields = record.get("fields") or {}
                    public_id = _stable_public_id(spec, fields, record_id)
                    canonical_data = self._canonical_data(spec, table, record, candidate_facts)
                    source_version = _source_version(str(table["table_id"]), table.get("revision", "unknown"), record_id, fields)
                    target = spec.target_table
                    if not _IDENTIFIER.fullmatch(target):
                        raise RuntimeError(f"invalid target table: {target}")
                    legacy = connection.execute(
                        sql.SQL(
                            "SELECT public_id FROM media_product.{table} "
                            "WHERE tenant_id = %s AND canonical_data->'source'->>'record_id' = %s"
                        ).format(table=sql.Identifier(target)),
                        (self.tenant_id, record_id),
                    ).fetchone()
                    if legacy and str(legacy[0]) != public_id:
                        connection.execute(
                            sql.SQL("DELETE FROM media_product.{table} WHERE tenant_id = %s AND public_id = %s").format(
                                table=sql.Identifier(target)
                            ),
                            (self.tenant_id, str(legacy[0])),
                        )
                    if target == "review_records":
                        existing = connection.execute(
                            "SELECT canonical_data FROM media_product.review_records WHERE tenant_id = %s AND public_id = %s",
                            (self.tenant_id, public_id),
                        ).fetchone()
                        if existing and existing[0] == canonical_data:
                            stats["unchanged"] += 1
                            continue
                        connection.execute(
                            "INSERT INTO media_product.review_records (tenant_id, public_id, revision, canonical_data) "
                            "VALUES (%s, %s, 1, %s::jsonb) "
                            "ON CONFLICT (tenant_id, public_id) DO UPDATE SET "
                            "canonical_data = EXCLUDED.canonical_data, "
                            "revision = media_product.review_records.revision + 1, updated_at = now()",
                            (self.tenant_id, public_id, json.dumps(canonical_data, ensure_ascii=False)),
                        )
                    else:
                        existing = connection.execute(
                            sql.SQL("SELECT source_version, canonical_data FROM media_product.{table} WHERE tenant_id = %s AND public_id = %s").format(table=sql.Identifier(target)),
                            (self.tenant_id, public_id),
                        ).fetchone()
                        if existing and str(existing[0]) == source_version and existing[1] == canonical_data:
                            stats["unchanged"] += 1
                            continue
                        connection.execute(
                            sql.SQL(
                                "INSERT INTO media_product.{table} (tenant_id, public_id, source_version, revision, canonical_data) VALUES (%s, %s, %s, 1, %s::jsonb) "
                                "ON CONFLICT (tenant_id, public_id) DO UPDATE SET source_version = EXCLUDED.source_version, canonical_data = EXCLUDED.canonical_data, revision = media_product.{table}.revision + 1"
                            ).format(table=sql.Identifier(target)),
                            (self.tenant_id, public_id, source_version, json.dumps(canonical_data, ensure_ascii=False)),
                        )
                    stats["updated" if existing else "inserted"] += 1
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return stats


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "TARGET_TENANT_ID",
    "TABLE_SPECS",
    "BaseTableSpec",
    "LarkBaseProjection",
]
