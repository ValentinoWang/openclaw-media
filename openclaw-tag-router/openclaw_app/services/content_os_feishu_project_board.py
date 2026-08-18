"""Live Feishu Base transport for the read-only Content OS project board.

The project overview remains the only source of truth. This client creates
only missing display columns and writes derived text into the existing
``00_Projects_项目看板`` table. It writes only the clean collaborator-facing
schema and never writes project state, tasks, paths, or compatibility fields.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .feishu_service import FeishuService
from .tenant_execution_context import current_session_tenant_id
from .tenant_owned_resources import TenantOwnedResourceService


DEFAULT_TABLE_NAME = "00_Projects_项目看板"
BASE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9]{8,128}$")

# This is the complete live table schema.  The table intentionally has no
# legacy state, local path, task, or internal project-key column.
FIELD_BINDINGS: dict[str, str] = {
    "项目名称": "项目名称",
    "项目阶段": "项目阶段",
    "当前版本": "当前版本",
    "剪辑方式": "剪辑方式",
    "负责人": "负责人",
    "下一步": "下一步",
    "是否阻塞": "是否阻塞",
    "阻塞原因": "阻塞原因",
    "项目说明摘要": "项目说明摘要",
    "脚本摘要": "脚本摘要",
    "镜头安排与剪辑说明摘要": "镜头安排与剪辑说明摘要",
    "交接完成情况": "交接完成情况",
    "成片链接": "成片链接",
    "质检链接": "质检链接",
    "发布链接": "发布链接",
    "复盘链接": "复盘链接",
    "提交修改": "提交修改",
}
SERVER_FIELDS: dict[str, str] = {
    "project_id": "项目ID",
    "tenant_id": "租户ID",
}


class FeishuProjectBoardError(RuntimeError):
    """A live-board transport error safe for server logs only."""


def _record_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(
            str(item.get("text") or "") if isinstance(item, dict) else str(item or "")
            for item in value
        ).strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "").strip()
    return str(value or "").strip()


@dataclass
class FeishuBitableProjectBoardClient:
    """Schema-aware live client injected into the v2 projection adapter."""

    feishu_service: FeishuService
    base_token: str
    table_name: str = DEFAULT_TABLE_NAME
    tenant_owned_resources: TenantOwnedResourceService | None = None
    _table_id: str = ""
    _schema_ready: bool = False

    def __post_init__(self) -> None:
        if not BASE_TOKEN_PATTERN.fullmatch(self.base_token or ""):
            raise FeishuProjectBoardError("Content OS 项目看板 Base 标识无效")
        if self.table_name != DEFAULT_TABLE_NAME:
            raise FeishuProjectBoardError("Content OS 项目看板表名必须使用已登记的项目看板")

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.feishu_service._request(method, path, json_body=json_body, params=params)

    def _resolve_table_id(self) -> str:
        if self._table_id:
            return self._table_id
        items = self._request("GET", f"/bitable/v1/apps/{self.base_token}/tables").get("data", {}).get("items", [])
        matches = [item for item in items if isinstance(item, dict) and item.get("name") == self.table_name] if isinstance(items, list) else []
        if len(matches) != 1 or not str(matches[0].get("table_id") or ""):
            raise FeishuProjectBoardError("飞书项目看板不存在或不唯一")
        self._table_id = str(matches[0]["table_id"])
        return self._table_id

    def _field_names(self) -> set[str]:
        table_id = self._resolve_table_id()
        items = self._request("GET", f"/bitable/v1/apps/{self.base_token}/tables/{table_id}/fields").get("data", {}).get("items", [])
        if not isinstance(items, list):
            raise FeishuProjectBoardError("飞书项目看板字段无法读取")
        return {str(item.get("field_name") or "") for item in items if isinstance(item, dict)}

    def ensure_schema(self) -> None:
        """Add only missing plain-text fields from the clean collaboration schema."""
        if self._schema_ready:
            return
        table_id = self._resolve_table_id()
        existing = self._field_names()
        required = set(FIELD_BINDINGS.values()) | set(SERVER_FIELDS.values())
        unexpected = existing - required
        if unexpected:
            raise FeishuProjectBoardError("飞书项目看板仍有旧字段，必须先完成一次性清理")
        for field_name in (*dict.fromkeys(FIELD_BINDINGS.values()), *SERVER_FIELDS.values()):
            if field_name in existing:
                continue
            self._request(
                "POST",
                f"/bitable/v1/apps/{self.base_token}/tables/{table_id}/fields",
                json_body={"field_name": field_name, "type": 1},
            )
            existing.add(field_name)
        if required - existing:
            raise FeishuProjectBoardError("飞书项目看板缺少必要展示字段")
        self._schema_ready = True

    def _records_for_project(self, project_id: str) -> list[dict[str, Any]]:
        table_id = self._resolve_table_id()
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {
                "page_size": 100,
                "filter": f'CurrentValue.[项目ID] = "{project_id}"',
            }
            if page_token:
                params["page_token"] = page_token
            data = self._request("GET", f"/bitable/v1/apps/{self.base_token}/tables/{table_id}/records", params=params).get("data", {})
            items = data.get("items", []) if isinstance(data, dict) else []
            if not isinstance(items, list):
                raise FeishuProjectBoardError("飞书项目看板记录无法读取")
            records.extend(item for item in items if isinstance(item, dict))
            if not isinstance(data, dict) or not data.get("has_more"):
                return records
            page_token = str(data.get("page_token") or "")
            if not page_token:
                raise FeishuProjectBoardError("飞书项目看板分页信息无效")

    def upsert_content_os_project(self, project_key: str, fields: dict[str, str]) -> None:
        if self.tenant_owned_resources is None:
            raise FeishuProjectBoardError("canonical resource owner service is unavailable")
        tenant_id = current_session_tenant_id()
        self.ensure_schema()
        if set(fields) != set(FIELD_BINDINGS):
            raise FeishuProjectBoardError("项目看板投影字段不完整")
        table_fields = {FIELD_BINDINGS[name]: str(value or "") for name, value in fields.items()}
        table_fields[SERVER_FIELDS["project_id"]] = project_key
        table_fields = self.tenant_owned_resources.create_projection(
            "content_os.project",
            project_key,
            session_tenant_id=tenant_id,
            fields=table_fields,
            writer=lambda projected: projected,
        )
        project_name = table_fields["项目名称"].strip()
        if not project_name:
            raise FeishuProjectBoardError("项目看板投影缺少项目名称")
        table_id = self._resolve_table_id()
        matches = [
            record for record in self._records_for_project(project_key)
            if _record_text((record.get("fields") or {}).get("项目ID")) == project_key
        ]
        if len(matches) > 1:
            raise FeishuProjectBoardError("飞书项目看板存在重复项目名称")
        if matches:
            record_id = str(matches[0].get("record_id") or "")
            if not record_id:
                raise FeishuProjectBoardError("飞书项目看板记录缺少标识")
            self.tenant_owned_resources.assert_projection_read(
                "content_os.project",
                project_key,
                session_tenant_id=tenant_id,
                fields=matches[0].get("fields") or {},
                projection_source=f"feishu:{table_id}/{record_id}",
            )
            self._request("PUT", f"/bitable/v1/apps/{self.base_token}/tables/{table_id}/records/{record_id}", json_body={"fields": table_fields})
        else:
            response = self._request("POST", f"/bitable/v1/apps/{self.base_token}/tables/{table_id}/records", json_body={"fields": table_fields})
            record_id = str((response.get("data", {}).get("record") or {}).get("record_id") or "")
            if not record_id:
                raise FeishuProjectBoardError("飞书项目看板写入后缺少记录标识")
        readback = self.feishu_service.read_bitable_record(
            self.base_token,
            table_id,
            record_id,
        )
        self.tenant_owned_resources.assert_projection_read(
            "content_os.project",
            project_key,
            session_tenant_id=tenant_id,
            fields=readback.get("fields") or {},
            projection_source=f"feishu:{table_id}/{record_id}",
        )
