from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from datetime import datetime
from typing import Any

from ..services.utils import now_in_tz


UNIFIED_CREATION_PARENT_NODE_TOKEN = "UkSMwA36fiZuBdkk63ncnm84n0e"
UNIFIED_CREATION_TABLE_URL = os.environ.get(
    "MEDIA_OS_CREATION_TASKS_URL",
    (
        "https://tcnwueberajc.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e"
        "?fromScene=spaceOverview&table=tbl3tNirtYn3eOUr&view=vewAaVJP2U"
    ),
)
UNIFIED_CREATION_FIELD_SPECS: dict[str, int] = {
    "记录类型": 1,
    "标题": 1,
    "主题": 1,
    "内容": 1,
    "摘要": 1,
    "平台": 4,
    "内容类型": 4,
    "赛道": 4,
    "关键词标签": 1,
    "来源链接": 15,
    "文档链接JSON": 1,
    "主状态": 3,
    "入库时间": 5,
    "创建时间": 5,
    "更新时间": 5,
    "核心数据JSON": 1,
    "爆点分析JSON": 1,
    "校验结果JSON": 1,
    "复盘状态": 3,
    "发布链接": 15,
    "详情JSON": 1,
}
UNIFIED_CREATION_SELECT_OPTIONS: dict[str, list[str]] = {
    "平台": ["小红书", "抖音", "B站", "视频号", "公众号", "微博", "Instagram", "TikTok", "其他", "未知"],
    "内容类型": ["短视频", "图文", "直播", "文章", "音频", "图片", "混合", "未知"],
    "赛道": ["校园生活", "运动康复", "跑步训练", "AI科技", "学习方法", "职场成长", "生活方式", "商业合作", "所有赛道", "未提供", "其他"],
    "主状态": ["待处理", "处理中", "已完成", "待人工补充", "失败", "已归档", "已发布", "已复盘", "已建档"],
    "复盘状态": ["待复盘", "已复盘", "2小时已复盘", "24小时已复盘", "7天已复盘", "复盘完成", "写入失败"],
}
BITABLE_OPTION_ID_RE = re.compile(r"^opt[A-Za-z0-9]{6,}$")


class UnifiedCreationMixin:
    def _sync_unified_creation_record(self, fields: dict[str, Any], *, table_url: str = UNIFIED_CREATION_TABLE_URL) -> dict[str, str]:
        doc_link_text = self._first_url_from_value(fields.get("文档链接JSON"))
        if not doc_link_text.startswith(("http://", "https://")):
            raise RuntimeError("写入创作任务总表前必须先创建归档文档并提供文档链接")
        app_token, table_id = self._unified_creation_bitable_refs(table_url)
        self._ensure_unified_creation_fields(app_token, table_id)
        self._ensure_unified_creation_select_options(app_token, table_id, fields)
        field_types = self._unified_creation_field_types(app_token, table_id)
        payload_fields: dict[str, Any] = {}
        for name, value in fields.items():
            if name not in field_types or value in (None, "", []):
                continue
            coerced = self._coerce_unified_creation_value(value, field_types.get(name))
            if coerced in (None, "", []):
                continue
            payload_fields[name] = coerced
        if not payload_fields:
            raise RuntimeError("创作任务总表没有可写字段")
        payload = self.feishu_service._request(
            "POST",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            json_body={"fields": payload_fields},
        )
        record = payload.get("data", {}).get("record") or {}
        return {
            "record_id": str(record.get("record_id") or ""),
            "table_url": table_url,
            "written_fields": ",".join(sorted(payload_fields)),
        }

    def _update_unified_creation_record(self, record_id: str, fields: dict[str, Any], *, table_url: str = UNIFIED_CREATION_TABLE_URL) -> dict[str, str]:
        if not record_id:
            return {}
        app_token, table_id = self._unified_creation_bitable_refs(table_url)
        self._ensure_unified_creation_fields(app_token, table_id)
        self._ensure_unified_creation_select_options(app_token, table_id, fields)
        field_types = self._unified_creation_field_types(app_token, table_id)
        payload_fields: dict[str, Any] = {}
        for name, value in fields.items():
            if name not in field_types or value in (None, "", []):
                continue
            coerced = self._coerce_unified_creation_value(value, field_types.get(name))
            if coerced in (None, "", []):
                continue
            payload_fields[name] = coerced
        if not payload_fields:
            return {}
        self.feishu_service._request(
            "PUT",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
            json_body={"fields": payload_fields},
        )
        return {"record_id": record_id, "table_url": table_url, "written_fields": ",".join(sorted(payload_fields))}

    def _unified_creation_bitable_refs(self, table_url: str) -> tuple[str, str]:
        parsed = urllib.parse.urlparse(table_url)
        query = urllib.parse.parse_qs(parsed.query)
        table_id = (query.get("table") or [""])[0]
        if not table_id:
            raise RuntimeError("创作任务总表链接缺少 table 参数")
        wiki_match = re.search(r"/wiki/([A-Za-z0-9]+)", parsed.path)
        if wiki_match:
            payload = self.feishu_service._request("GET", "/wiki/v2/spaces/get_node", params={"token": wiki_match.group(1)})
            node = payload.get("data", {}).get("node") or {}
            if node.get("obj_type") != "bitable":
                raise RuntimeError(f"创作任务总表 wiki 节点不是多维表格：{node.get('obj_type')}")
            return str(node.get("obj_token") or ""), table_id
        base_match = re.search(r"/base/([A-Za-z0-9]+)", parsed.path)
        if base_match:
            return base_match.group(1), table_id
        raise RuntimeError("创作任务总表链接必须包含 /wiki/<token> 或 /base/<app_token>")

    def _unified_creation_field_types(self, app_token: str, table_id: str) -> dict[str, Any]:
        payload = self.feishu_service._request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields")
        return {
            str(item.get("field_name")): item.get("type")
            for item in payload.get("data", {}).get("items", [])
            if item.get("field_name")
        }

    def _unified_creation_field_items(self, app_token: str, table_id: str) -> dict[str, dict[str, Any]]:
        payload = self.feishu_service._request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields")
        return {
            str(item.get("field_name")): item
            for item in payload.get("data", {}).get("items", [])
            if item.get("field_name")
        }

    def _ensure_unified_creation_fields(self, app_token: str, table_id: str) -> None:
        existing = set(self._unified_creation_field_types(app_token, table_id))
        for name, field_type in UNIFIED_CREATION_FIELD_SPECS.items():
            if name in existing:
                continue
            try:
                self.feishu_service._request(
                    "POST",
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                    json_body={"field_name": name, "type": field_type},
                )
                existing.add(name)
            except Exception:
                continue

    def _ensure_unified_creation_select_options(self, app_token: str, table_id: str, raw_fields: dict[str, Any]) -> None:
        items = self._unified_creation_field_items(app_token, table_id)
        for name, base_options in UNIFIED_CREATION_SELECT_OPTIONS.items():
            item = items.get(name)
            if not item:
                continue
            target_type = UNIFIED_CREATION_FIELD_SPECS.get(name)
            options = [str(option).strip() for option in base_options if str(option).strip()]
            for option in self._select_options_from_value(raw_fields.get(name)):
                if option not in options:
                    options.append(option)
            existing = [
                str(option.get("name") or "").strip()
                for option in ((item.get("property") or {}).get("options") or [])
                if str(option.get("name") or "").strip()
            ]
            if item.get("type") == target_type and all(option in existing for option in options):
                continue
            merged = list(options)
            for option in existing:
                if option not in merged:
                    merged.append(option)
            try:
                self.feishu_service._request(
                    "PUT",
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{item.get('field_id')}",
                    json_body={
                        "field_name": name,
                        "type": target_type,
                        "property": {"options": [{"name": option} for option in merged]},
                    },
                )
            except Exception:
                continue

    @staticmethod
    def _select_options_from_value(value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        raw_items = value if isinstance(value, list) else re.split(r"[,，/、;；|]\s*", str(value))
        result: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = str(item).strip()
            if not text or BITABLE_OPTION_ID_RE.fullmatch(text) or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _coerce_unified_creation_value(self, value: Any, field_type: Any) -> Any:
        if value is None:
            return ""
        if field_type == 2:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        if field_type == 3:
            if isinstance(value, list):
                value = next((item for item in value if str(item).strip()), "")
            text = str(value).strip()
            return text or None
        if field_type == 4:
            raw_items = value if isinstance(value, list) else re.split(r"[,，/、;；|]\s*", str(value))
            items: list[str] = []
            seen: set[str] = set()
            for item in raw_items:
                text = str(item).strip()
                if not text or BITABLE_OPTION_ID_RE.fullmatch(text) or text in seen:
                    continue
                seen.add(text)
                items.append(text)
            return items or None
        if field_type == 5:
            if isinstance(value, datetime):
                return int(value.timestamp() * 1000)
            if isinstance(value, (int, float)):
                return int(value)
            text = str(value).strip()
            if not text:
                return None
            try:
                normalized = text.replace("Z", "+00:00")
                return int(datetime.fromisoformat(normalized).timestamp() * 1000)
            except ValueError:
                return text
        if field_type == 15:
            if isinstance(value, dict):
                return value
            text = self._first_url_from_value(value)
            if not text:
                return None
            return {"text": text[:120], "link": text}
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _sync_unified_creation_child_doc(self, doc_title: str, record_type: str, content: str) -> dict[str, str]:
        doc_content = f"# {doc_title}\n\n标签：{record_type}\n\n{content}".strip()
        if hasattr(self.feishu_service, "replace_child_entry_under_node"):
            return self.feishu_service.replace_child_entry_under_node(UNIFIED_CREATION_PARENT_NODE_TOKEN, doc_title, doc_content)
        raise RuntimeError("FeishuService 缺少按 wiki 节点创建子文档的能力，拒绝写入未统一任务池")

    def _markdownish_docx_blocks(self, doc_title: str, record_type: str, content: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [
            self._docx_heading_block(1, doc_title),
            self._docx_text_block(f"标签：{record_type}"),
        ]
        for raw_line in str(content or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("## "):
                blocks.append(self._docx_heading_block(2, line[3:].strip() or "未命名段落"))
            elif line.startswith("# "):
                blocks.append(self._docx_heading_block(2, line[2:].strip() or "未命名段落"))
            else:
                blocks.append(self._docx_text_block(line))
        return blocks

    def _unified_creation_doc_name(self, prefix: str, theme_source: str, seed: str = "") -> str:
        theme = self._normalize_recreation_title(theme_source, limit=20) or self._recreation_compact_theme(theme_source, limit=20) or "未命名主题"
        suffix_seed = str(seed or theme_source or "").strip()
        suffix = hashlib.sha1(suffix_seed.encode("utf-8")).hexdigest()[:4] if suffix_seed else ""
        return f"{prefix}｜{theme}｜{suffix}" if suffix else f"{prefix}｜{theme}"

    @staticmethod
    def _unified_now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")
