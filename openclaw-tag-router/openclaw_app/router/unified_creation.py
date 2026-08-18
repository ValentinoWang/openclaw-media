from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from datetime import datetime
from typing import Any

from .creation_feishu_writer import RouterCreationFeishuDocumentWriter
from ..services.utils import now_in_tz


CREATION_TASK_POOL_PARENT_NODE_TOKEN = "Tm69wEqFpi76d9k53KEcqK4Rnkh"
UNIFIED_CREATION_PARENT_NODE_TOKEN = (
    os.environ.get("FEISHU_CREATION_DOC_PARENT_NODE_TOKEN")
    or CREATION_TASK_POOL_PARENT_NODE_TOKEN
)
UNIFIED_CREATION_TABLE_URL = os.environ.get(
    "MEDIA_OS_CREATION_RUNS_URL",
    "",
)
MEDIA_ENV_PATH = "/home/ubuntu/openclaw-agents/media/.env.local"
MEDIA_REGISTRY_PATH = "/home/ubuntu/openclaw-feishu-reminder/media-bitable-registry.json"
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
    "灵感文档链接": 15,
    "素材文档链接": 15,
    "创作文档链接": 15,
    "主状态": 3,
    "入库时间": 5,
    "创建时间": 5,
    "更新时间": 5,
    "灵感评分": 2,
    "评分原因": 1,
    "可迁移点": 1,
    "风险点": 1,
    "建议产物": 1,
    "校验结果": 1,
    "复盘状态": 3,
    "发布链接": 15,
    "素材来源类型": 1,
    "素材信号类型": 1,
    "情绪触发": 1,
    "触发原话": 1,
    "事件场景": 1,
    "错位点": 1,
    "核心观点": 1,
    "读者问题": 1,
    "可复用角度": 1,
    "素材状态": 1,
    "一鱼多吃方向": 1,
    "下一步": 1,
    "定位分析": 1,
    "平台策略": 1,
    "创作记录ID": 1,
    "本地报告路径": 1,
}
CREATION_RUN_FEISHU_FIELD_NAME_MAP: dict[str, str] = {
    "run_id": "创作运行ID",
    "entrypoint": "入口标签",
    "input_summary": "输入需求摘要",
    "platform": "平台",
    "content_type": "内容类型",
    "track_name": "赛道",
    "status": "状态",
    "generation_source": "生成来源",
    "run_artifact_uri": "运行产物URI",
    "render_id": "渲染ID",
    "render_spec_uri": "渲染规格URI",
    "feishu_doc_link": "飞书文档链接",
}
CREATION_RUN_ENTRYPOINT_LABELS = (
    "【创作>小红书】",
    "【创作>抖音】",
    "【创作-拍摄执行】",
    "【创作】",
)
UNIFIED_CREATION_SELECT_OPTIONS: dict[str, list[str]] = {
    "平台": ["小红书", "抖音", "B站", "视频号", "公众号", "微博", "Instagram", "TikTok", "其他", "未知"],
    "内容类型": ["短视频", "图文", "直播", "文章", "音频", "图片", "混合", "未知"],
    "赛道": ["校园生活", "运动康复", "跑步训练", "AI科技", "学习方法", "职场成长", "生活方式", "商业合作", "所有赛道", "未提供", "其他"],
    "主状态": ["待处理", "处理中", "已完成", "待人工补充", "失败", "已归档", "已发布", "已复盘", "已建档"],
    "复盘状态": ["待复盘", "已复盘", "2小时已复盘", "24小时已复盘", "7天已复盘", "复盘完成", "写入失败"],
}
BITABLE_OPTION_ID_RE = re.compile(r"^opt[A-Za-z0-9]{6,}$")


class UnifiedCreationMixin:
    def _sync_unified_creation_record(
        self,
        fields: dict[str, Any],
        *,
        session_tenant_id: str,
        table_url: str = "",
    ) -> dict[str, str]:
        table_url = self._unified_creation_table_url(table_url)
        doc_link_text = self._first_doc_link_from_unified_fields(fields)
        if not doc_link_text.startswith(("http://", "https://")):
            raise RuntimeError("写入 CreationRun 前必须先创建归档文档并提供文档链接")
        if not table_url:
            raise RuntimeError("缺少 MEDIA_OS_CREATION_RUNS_URL，CreationRun 写入必须使用 Media Model v2")
        app_token, table_id = self._unified_creation_bitable_refs(table_url)
        field_types = self._unified_creation_field_types(app_token, table_id)
        payload_fields = self._creation_run_v2_fields(fields, doc_link_text)
        run_id = str(payload_fields.get("run_id") or "").strip()
        if not run_id:
            raise RuntimeError("CreationRun 缺少 canonical run_id")
        owner_service = getattr(self, "tenant_owned_resources", None)
        if owner_service is None:
            raise RuntimeError("canonical resource owner service is unavailable")
        payload_fields = owner_service.create_projection(
            "media.creation_run",
            run_id,
            session_tenant_id=session_tenant_id,
            fields=payload_fields,
            writer=lambda projected: projected,
        )
        payload_fields = {
            feishu_name: self._coerce_unified_creation_value(value, field_types.get(feishu_name))
            for name, value in payload_fields.items()
            for feishu_name in [CREATION_RUN_FEISHU_FIELD_NAME_MAP.get(name, name)]
            if feishu_name in field_types and value not in (None, "", [])
        }
        payload_fields = {name: value for name, value in payload_fields.items() if value not in (None, "", [])}
        if not payload_fields:
            raise RuntimeError("CreationRun 没有可写字段")
        payload = self.feishu_service._request(
            "POST",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            json_body={"fields": payload_fields},
        )
        record = payload.get("data", {}).get("record") or {}
        record_id = str(record.get("record_id") or "")
        if not record_id:
            raise RuntimeError("CreationRun 写入后缺少 record_id")
        readback = self.feishu_service.read_bitable_record(app_token, table_id, record_id)
        owner_service.assert_projection_read(
            "media.creation_run",
            run_id,
            session_tenant_id=session_tenant_id,
            fields=readback.get("fields") or {},
            projection_source=f"feishu:{table_id}/{record_id}",
        )
        owner_service.register_docx_link(
            "media.creation_run",
            run_id,
            session_tenant_id=session_tenant_id,
            document_url=doc_link_text,
            policy="org_link_edit",
        )
        return {
            "record_id": record_id,
            "table_url": table_url,
            "written_fields": ",".join(sorted(payload_fields)),
        }

    def _update_unified_creation_record(
        self,
        record_id: str,
        fields: dict[str, Any],
        *,
        session_tenant_id: str,
        table_url: str = "",
    ) -> dict[str, str]:
        if not record_id:
            return {}
        table_url = self._unified_creation_table_url(table_url)
        if not table_url:
            raise RuntimeError("缺少 MEDIA_OS_CREATION_RUNS_URL，CreationRun 更新必须使用 Media Model v2")
        app_token, table_id = self._unified_creation_bitable_refs(table_url)
        field_types = self._unified_creation_field_types(app_token, table_id)
        doc_link_text = self._first_doc_link_from_unified_fields(fields)
        payload_fields = self._creation_run_v2_fields(fields, doc_link_text)
        run_id = str(payload_fields.get("run_id") or "").strip()
        if not run_id:
            raise RuntimeError("CreationRun 更新缺少 canonical run_id")
        owner_service = getattr(self, "tenant_owned_resources", None)
        if owner_service is None:
            raise RuntimeError("canonical resource owner service is unavailable")
        payload_fields = owner_service.update_projection(
            "media.creation_run",
            run_id,
            session_tenant_id=session_tenant_id,
            fields=payload_fields,
            writer=lambda projected: projected,
        )
        payload_fields = {
            feishu_name: self._coerce_unified_creation_value(value, field_types.get(feishu_name))
            for name, value in payload_fields.items()
            for feishu_name in [CREATION_RUN_FEISHU_FIELD_NAME_MAP.get(name, name)]
            if feishu_name in field_types and value not in (None, "", [])
        }
        payload_fields = {name: value for name, value in payload_fields.items() if value not in (None, "", [])}
        if not payload_fields:
            return {}
        self.feishu_service._request(
            "PUT",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
            json_body={"fields": payload_fields},
        )
        readback = self.feishu_service.read_bitable_record(app_token, table_id, record_id)
        owner_service.assert_projection_read(
            "media.creation_run",
            run_id,
            session_tenant_id=session_tenant_id,
            fields=readback.get("fields") or {},
            projection_source=f"feishu:{table_id}/{record_id}",
        )
        if doc_link_text:
            owner_service.register_docx_link(
                "media.creation_run",
                run_id,
                session_tenant_id=session_tenant_id,
                document_url=doc_link_text,
                policy="org_link_edit",
            )
        return {"record_id": record_id, "table_url": table_url, "written_fields": ",".join(sorted(payload_fields))}

    def _unified_creation_table_url(self, table_url: str = "") -> str:
        explicit = str(table_url or "").strip()
        if explicit:
            return explicit
        env_value = os.environ.get("MEDIA_OS_CREATION_RUNS_URL", "").strip()
        if env_value:
            return env_value
        env_value = self._load_creation_runs_url_from_env_file()
        if env_value:
            os.environ["MEDIA_OS_CREATION_RUNS_URL"] = env_value
            return env_value
        registry_value = self._load_creation_runs_url_from_registry()
        if registry_value:
            os.environ["MEDIA_OS_CREATION_RUNS_URL"] = registry_value
            return registry_value
        return UNIFIED_CREATION_TABLE_URL

    def _load_creation_runs_url_from_env_file(self) -> str:
        try:
            with open(MEDIA_ENV_PATH, "r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key.strip() != "MEDIA_OS_CREATION_RUNS_URL":
                        continue
                    return value.strip().strip("'").strip('"')
        except OSError:
            return ""
        return ""

    def _load_creation_runs_url_from_registry(self) -> str:
        try:
            with open(MEDIA_REGISTRY_PATH, "r", encoding="utf-8") as fh:
                registry = json.load(fh)
        except (OSError, ValueError, TypeError):
            return ""
        creation_runs = ((registry.get("tables") or {}).get("creation_runs") or {})
        env = creation_runs.get("env") if isinstance(creation_runs, dict) else {}
        if isinstance(env, dict):
            value = str(env.get("MEDIA_OS_CREATION_RUNS_URL") or "").strip()
            if value:
                return value
        table = creation_runs.get("table") if isinstance(creation_runs, dict) else {}
        if isinstance(table, dict):
            return str(table.get("url") or "").strip()
        return ""

    def _creation_run_v2_fields(self, fields: dict[str, Any], doc_link: str) -> dict[str, Any]:
        title = str(fields.get("标题") or fields.get("主题") or fields.get("记录类型") or "创作运行").strip()
        topic = str(fields.get("主题") or title).strip()
        record_type = str(fields.get("记录类型") or "creation").strip()
        entrypoint = self._creation_run_entrypoint(fields, record_type, title)
        raw_seed = "|".join(
            str(fields.get(name) or "").strip()
            for name in (
                "来源消息ID",
                "source_message_id",
                "message_id",
                "记录类型",
                "标题",
                "主题",
                "内容",
                "灵感文档链接",
                "素材文档链接",
                "创作文档链接",
            )
        )
        run_id = "run_router_" + hashlib.sha1(raw_seed.encode("utf-8")).hexdigest()[:16]
        status = str(fields.get("主状态") or fields.get("状态") or "success").strip()
        if status in {"已完成", "已归档", "已建档"}:
            status = "success"
        elif status in {"失败", "写入失败"}:
            status = "failed"
        else:
            status = "pending"
        return {
            "run_id": run_id,
            "entrypoint": entrypoint,
            "input_summary": topic,
            "platform": self._unified_join_lines(fields.get("平台")),
            "content_type": self._unified_join_lines(fields.get("内容类型")),
            "track_name": self._unified_join_lines(fields.get("赛道")),
            "status": status,
            "generation_source": "llm",
            "run_artifact_uri": doc_link,
            "render_id": "",
            "render_spec_uri": "",
            "feishu_doc_link": doc_link,
            "created_at": now_in_tz("Asia/Shanghai").isoformat(timespec="seconds"),
        }

    def _creation_run_entrypoint(self, fields: dict[str, Any], record_type: str, title: str) -> str:
        explicit = str(fields.get("入口标签") or fields.get("entrypoint") or "").strip()
        normalized = self._normalize_creation_run_entrypoint(explicit)
        if normalized:
            return normalized
        source_text = "\n".join(
            str(fields.get(name) or "")
            for name in ("标题", "记录类型", "关键词标签", "主题", "灵感文档链接", "素材文档链接", "创作文档链接")
        )
        source_text = f"{title}\n{record_type}\n{source_text}"
        for label in CREATION_RUN_ENTRYPOINT_LABELS:
            bare = label.strip("【】")
            if label in source_text or bare in source_text:
                return label
        return "【创作】"

    @staticmethod
    def _normalize_creation_run_entrypoint(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        for label in CREATION_RUN_ENTRYPOINT_LABELS:
            bare = label.strip("【】")
            if text == label or text == bare:
                return label
        return text

    def _first_doc_link_from_unified_fields(self, fields: dict[str, Any]) -> str:
        for name in ("灵感文档链接", "素材文档链接", "创作文档链接", "文档链接"):
            link = self._first_url_from_value(fields.get(name))
            if link:
                return link
        return ""

    def _unified_join_lines(self, value: Any) -> str:
        if value in (None, "", []):
            return ""
        if isinstance(value, dict):
            return "\n".join(
                f"{key}：{self._unified_join_lines(item)}"
                for key, item in value.items()
                if item not in (None, "", [])
            )
        if isinstance(value, list):
            return "\n".join(f"- {self._unified_join_lines(item)}" for item in value if item not in (None, "", []))
        return str(value).strip()

    def _unified_validation_summary(self, validation: Any) -> str:
        if not isinstance(validation, dict):
            return self._unified_join_lines(validation)
        status = "通过" if validation.get("ok") else "未通过"
        issues = [
            str(item.get("message") or "").strip()
            for item in validation.get("issues", [])
            if isinstance(item, dict) and str(item.get("message") or "").strip()
        ]
        return status + (f"：{'；'.join(issues)}" if issues else "")

    def _unified_creation_bitable_refs(self, table_url: str) -> tuple[str, str]:
        parsed = urllib.parse.urlparse(table_url)
        query = urllib.parse.parse_qs(parsed.query)
        table_id = (query.get("table") or [""])[0]
        if not table_id:
            raise RuntimeError("CreationRun 表链接缺少 table 参数")
        wiki_match = re.search(r"/wiki/([A-Za-z0-9]+)", parsed.path)
        if wiki_match:
            payload = self.feishu_service._request("GET", "/wiki/v2/spaces/get_node", params={"token": wiki_match.group(1)})
            node = payload.get("data", {}).get("node") or {}
            if node.get("obj_type") != "bitable":
                raise RuntimeError(f"CreationRun wiki 节点不是多维表格：{node.get('obj_type')}")
            return str(node.get("obj_token") or ""), table_id
        base_match = re.search(r"/base/([A-Za-z0-9]+)", parsed.path)
        if base_match:
            return base_match.group(1), table_id
        raise RuntimeError("CreationRun 表链接必须包含 /wiki/<token> 或 /base/<app_token>")

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
            return self._unified_join_lines(value)
        return str(value)

    def _sync_unified_creation_child_doc(self, doc_title: str, record_type: str, content: str) -> dict[str, str]:
        return self._creation_feishu_writer().sync_text_child_doc(doc_title, record_type, content)

    def _sync_unified_creation_child_blocks(self, doc_title: str, blocks: list[dict[str, Any]]) -> dict[str, str]:
        return self._creation_feishu_writer().replace_child_doc_blocks(doc_title, blocks)

    def _creation_feishu_writer(self) -> RouterCreationFeishuDocumentWriter:
        return RouterCreationFeishuDocumentWriter(
            feishu_service=self.feishu_service,
            parent_node_token=UNIFIED_CREATION_PARENT_NODE_TOKEN,
            heading_factory=self._docx_heading_block,
            text_factory=self._docx_text_block,
        )

    def _unified_creation_doc_name(self, prefix: str, theme_source: str, seed: str = "") -> str:
        theme = self._unified_compact_theme(theme_source, limit=20) or "未命名主题"
        suffix_seed = str(seed or theme_source or "").strip()
        suffix = hashlib.sha1(suffix_seed.encode("utf-8")).hexdigest()[:4] if suffix_seed else ""
        return f"{prefix}｜{theme}｜{suffix}" if suffix else f"{prefix}｜{theme}"

    @staticmethod
    def _unified_compact_theme(value: str, *, limit: int = 20) -> str:
        text = re.sub(r"https?://\S+", "", str(value or ""))
        text = re.sub(r"[【】#*_`>|\[\]()（）{}:：,，。！？!?\s]+", "", text)
        return text[:limit]

    @staticmethod
    def _unified_now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")
