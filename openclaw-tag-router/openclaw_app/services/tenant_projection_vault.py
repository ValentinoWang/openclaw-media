from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from media_vault.vault import MediaVault
from selfmedia.growth import source_asset_public_id

from .resource_owner_registry import ResourceOwnerRegistry
from .tenant_projection import AssetSummaryPage, ProjectionRead, RunSummaryPage, TenantProjectionError


_RUN_RESOURCE_TYPE = "media.creation_run"
_INTERNAL_ID = re.compile(r"\b(?:rec|tbl|run_rec)[A-Za-z0-9_-]{6,}\b")
_FORBIDDEN_KEYS = frozenset(
    {
        "record_id",
        "record_ids",
        "tenant_id",
        "owner_id",
        "table_id",
        "view_id",
        "app_token",
        "raw_prompt",
        "raw_response",
        "traceback",
        "stack_trace",
        "access_token",
        "refresh_token",
        "token",
        "debug",
    }
)
_BASE_FIELDS = {
    "entrypoint": "entrypoint",
    "input_summary": "inputSummary",
    "status": "status",
    "generation_source": "generationSource",
    "created_at": "createdAt",
    "updated_at": "updatedAt",
}
_SECTION_FILES = {
    "sources": ("retrieval_candidates.json", "material_usage.json"),
    "decisions": ("decision_trace.json", "validation_report.json"),
    "outputs": ("draft_output.json", "writeback_report.json"),
}


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TenantProjectionError("projection_unavailable", "运行投影暂时不可用。") from exc
    if not isinstance(payload, dict):
        raise TenantProjectionError("projection_contract_violation", "运行产物格式无效。")
    return payload


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[结构已收起]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value.replace("media://", "受控产物:")
        text = re.sub(r"/(?:home|tmp)/[^\s]+", "[受控路径]", text)
        return _INTERNAL_ID.sub("[内部标识已隐藏]", text)[:20_000]
    if isinstance(value, list):
        return [_safe_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:200]:
            key = str(raw_key)
            normalized = key.strip().lower()
            if normalized in _FORBIDDEN_KEYS or normalized.endswith("_id") or normalized.endswith("_ids"):
                continue
            result[key] = _safe_value(item, depth=depth + 1)
        return result
    return str(value)[:4000]


class MediaVaultTenantProjectionReader:
    """Reads only the authenticated tenant partition and never queries Feishu tables."""

    def __init__(self, registry: ResourceOwnerRegistry, *, vault_root: str | Path) -> None:
        self.registry = registry
        self.vault_root = Path(vault_root)

    def dashboard_summary(self, tenant_id: str) -> ProjectionRead:
        count, summary_revision, owner_revision = self.registry.creation_run_summary_state(tenant_id)
        revision = self._list_revision(tenant_id, count, summary_revision, owner_revision)
        return ProjectionRead({"creationRunCount": count}, revision, 1)

    def list_run_summaries(
        self,
        tenant_id: str,
        *,
        cursor: str | None,
        page_size: int,
        search: str,
    ) -> RunSummaryPage:
        offset = self._cursor(cursor)
        summaries = self.registry.list_creation_run_summaries(
            tenant_id,
            search=search,
            limit=page_size + 1,
            offset=offset,
        )
        has_more = len(summaries) > page_size
        items = tuple(self._indexed_summary(item) for item in summaries[:page_size])
        next_cursor = str(offset + len(items)) if has_more else None
        count, summary_revision, owner_revision = self.registry.creation_run_summary_state(tenant_id)
        return RunSummaryPage(
            items,
            next_cursor,
            self._list_revision(tenant_id, count, summary_revision, owner_revision),
            2,
        )

    def list_source_assets(
        self,
        tenant_id: str,
        *,
        cursor: str | None,
        page_size: int,
    ) -> AssetSummaryPage:
        offset = self._cursor(cursor)
        owners = self.registry.list_by_tenant(
            tenant_id,
            resource_type="media.source_asset",
            limit=page_size + 1,
            offset=offset,
        )
        has_more = len(owners) > page_size
        visible = owners[:page_size]
        items = tuple(
            {
                "publicAssetId": source_asset_public_id(owner.canonical_resource_id),
                "createdAt": datetime.fromtimestamp(owner.created_at, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            for owner in visible
        )
        revision_input = "|".join(
            f"{owner.canonical_resource_id}:{owner.owner_revision}" for owner in visible
        )
        revision = hashlib.sha256(f"{tenant_id}|{offset}|{revision_input}".encode("utf-8")).hexdigest()[:24]
        return AssetSummaryPage(
            items,
            str(offset + len(items)) if has_more else None,
            revision,
            1,
        )

    def run_base_detail(self, tenant_id: str, public_run_id: str) -> ProjectionRead:
        owner = self.registry.assert_owner(_RUN_RESOURCE_TYPE, public_run_id, session_tenant_id=tenant_id)
        vault = MediaVault(tenant_id=tenant_id, root=self.vault_root)
        request = _load_object(vault.creation_run_dir(public_run_id) / "request.json")
        payload = {public: _safe_value(request[source]) for source, public in _BASE_FIELDS.items() if request.get(source) not in (None, "")}
        payload.setdefault("title", str(request.get("title") or request.get("input_summary") or public_run_id)[:500])
        return ProjectionRead(payload, str(owner.owner_revision), 1)

    def run_section(self, tenant_id: str, public_run_id: str, section: str) -> ProjectionRead:
        owner = self.registry.assert_owner(_RUN_RESOURCE_TYPE, public_run_id, session_tenant_id=tenant_id)
        vault = MediaVault(tenant_id=tenant_id, root=self.vault_root)
        run_dir = vault.creation_run_dir(public_run_id)
        files = _SECTION_FILES[section]
        artifacts = {
            filename.removesuffix(".json"): _safe_value(payload)
            for filename in files
            if (payload := _load_object(run_dir / filename))
        }
        return ProjectionRead({"artifacts": artifacts}, str(owner.owner_revision), len(files))

    @staticmethod
    def _cursor(cursor: str | None) -> int:
        if cursor is None:
            return 0
        if not cursor.isascii() or not cursor.isdigit() or int(cursor) < 0:
            raise TenantProjectionError("invalid_request", "分页游标无效。")
        return int(cursor)

    @staticmethod
    def _indexed_summary(summary: Any) -> dict[str, Any]:
        result: dict[str, Any] = {
            "publicRunId": summary.canonical_resource_id,
            "title": summary.title,
            "status": summary.status,
        }
        for value, public in (
            (summary.entrypoint, "entrypoint"),
            (summary.created_at, "createdAt"),
            (summary.updated_at, "updatedAt"),
        ):
            if value:
                result[public] = value
        return result

    @staticmethod
    def _list_revision(tenant_id: str, count: int, summary_revision: int, owner_revision: int) -> str:
        raw = f"{count}:{summary_revision}:{owner_revision}"
        return hashlib.sha256(f"{tenant_id}|{raw}".encode("utf-8")).hexdigest()[:24]
