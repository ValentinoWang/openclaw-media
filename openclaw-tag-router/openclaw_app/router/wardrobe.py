from __future__ import annotations

import base64
import importlib
import json
import mimetypes
import os
import re
import sys
import urllib.parse
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

WORKSPACE_ROOT = Path(
    os.getenv("OPENCLAW_MEDIA_WORKSPACE_ROOT", str(Path(__file__).resolve().parents[3]))
).expanduser()
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from common.llm_client import generate_json_from_parts
from common.llm_validation import LLMValidationContract, register_llm_validation_contract
from common.llm_settings import load_profile_llm_settings

from ..models.message import Message
from ..models.task import TaskResult
from ..services.wardrobe_markdown_renderer import (
    DEFAULT_WARDROBE_ITEMS_ROOT,
    render_wardrobe_markdown_artifact,
)
from ..services.wardrobe_weather import WardrobeWeatherError, fetch_wardrobe_weather


REMINDER_ROOT = Path(
    os.getenv("OPENCLAW_REMINDER_ROOT", str(Path.home() / "openclaw-feishu-reminder"))
).expanduser()
WARDROBE_CONTRACT_PATH = Path(
    os.getenv("OPENCLAW_WARDROBE_CONTRACT_PATH", str(WORKSPACE_ROOT / "docs/ai-harness/wardrobe-model-contract.json"))
).expanduser()
WARDROBE_CONTEXT_CONTRACT_PATH = Path(
    os.getenv("OPENCLAW_WARDROBE_CONTEXT_CONTRACT_PATH", str(WORKSPACE_ROOT / "docs/ai-harness/wardrobe-context-contract.json"))
).expanduser()
WARDROBE_REGISTRY_PATH = Path(
    os.getenv("OPENCLAW_WARDROBE_REGISTRY_PATH", str(REMINDER_ROOT / "wardrobe-config.json"))
).expanduser()
WARDROBE_ITEM_ID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
LOCATION_RE = re.compile(r"(?:位置|地点|当前在|我在)\s*[:：]?\s*([^\s，,。；;\n]+)")
WEATHER_LOCATION_RE = re.compile(r"(?:天气地点|天气城市|目的地|城市)\s*[:：]?\s*([^\s，,。；;\n]+)")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}
MAX_IMAGE_PART_BYTES = 8 * 1024 * 1024
INVENTORY_LOCATION_ALIASES = {"深圳市": "深圳", "深圳": "深圳", "老家": "老家", "行李中": "行李中", "未定位": "未定位"}
DAILY_CURRENT_LOCATION_KEYS = {"current_location", "wardrobe_location", "location", "地点", "位置"}
DAILY_WEATHER_LOCATION_KEYS = {"weather_location", "destination", "destination_location", "目的地", "天气地点", "天气城市"}
_feishu_reminder: ModuleType | None = None
_feishu_registry: ModuleType | None = None


def _load_feishu_integrations() -> tuple[ModuleType, ModuleType]:
    """Load the optional companion integration only when a Feishu write/read is needed."""
    global _feishu_reminder, _feishu_registry
    if _feishu_reminder is not None and _feishu_registry is not None:
        return _feishu_reminder, _feishu_registry
    if REMINDER_ROOT.is_dir() and str(REMINDER_ROOT) not in sys.path:
        sys.path.insert(0, str(REMINDER_ROOT))
    try:
        _feishu_reminder = importlib.import_module("reminder")
        _feishu_registry = importlib.import_module("setup_media_bitable_registry")
    except ModuleNotFoundError as exc:
        _feishu_reminder = None
        _feishu_registry = None
        raise RuntimeError(
            "衣橱飞书集成不可用：请设置 OPENCLAW_REMINDER_ROOT，或安装 reminder 与 setup_media_bitable_registry。"
        ) from exc
    return _feishu_reminder, _feishu_registry


def _validate_wardrobe_llm_payload(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("fields"), dict) and payload["fields"]:
        return payload
    if str(payload.get("status") or "").strip() and any(
        value not in (None, "", [], {}) for key, value in payload.items() if key != "status"
    ):
        return payload
    raise ValueError("wardrobe payload requires fields or a status result with details")


WARDROBE_LLM_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="tag_router.wardrobe.output.v1",
        profile="strict_structured",
        validator=_validate_wardrobe_llm_payload,
    )
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in paths:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _first_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _item_id_from_text(text: str) -> str:
    match = WARDROBE_ITEM_ID_RE.search(text or "")
    return match.group(0).lower() if match else ""


def _item_id_from_reply_context(metadata: dict[str, Any]) -> str:
    direct_keys = (
        "reply_text",
        "quoted_text",
        "replied_message_text",
        "parent_message_text",
        "referenced_message_text",
        "bot_reply",
        "reply_bot_text",
    )
    for key in direct_keys:
        value = str(metadata.get(key) or "").strip()
        item_id = _item_id_from_text(value)
        if item_id:
            return item_id

    for key in ("reply", "quoted_message", "replied_message", "parent_message", "referenced_message"):
        value = metadata.get(key)
        if isinstance(value, dict):
            for text_key in ("text", "raw_text", "body", "content", "reply", "bot_reply"):
                item_id = _item_id_from_text(str(value.get(text_key) or ""))
                if item_id:
                    return item_id

    conversation = metadata.get("conversation_context")
    if not isinstance(conversation, dict):
        return ""

    target_ids = {
        str(metadata.get(key) or "").strip()
        for key in (
            "reply_to_message_id",
            "reply_message_id",
            "quoted_message_id",
            "parent_message_id",
            "parent_id",
            "root_id",
        )
        if str(metadata.get(key) or "").strip()
    }
    if not target_ids:
        return ""

    for entry in conversation.get("items") or []:
        if not isinstance(entry, dict):
            continue
        entry_ids = {
            str(entry.get(key) or "").strip()
            for key in ("message_id", "bot_reply_message_id", "parent_id", "root_id")
            if str(entry.get(key) or "").strip()
        }
        if not (target_ids & entry_ids):
            continue
        for text_key in ("bot_reply", "text"):
            item_id = _item_id_from_text(str(entry.get(text_key) or ""))
            if item_id:
                return item_id
    return ""


def _wardrobe_item_id_from_message(message: Message) -> str:
    return _item_id_from_text(message.body or "") or _item_id_from_reply_context(message.metadata or {})


def _attachment_paths_from_metadata(metadata: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("downloaded_paths", "attachment_paths", "previous_downloaded_paths"):
        value = metadata.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value if str(item or "").strip())
    for item in metadata.get("attachments") or []:
        if isinstance(item, dict):
            for key in ("path", "local_path", "downloaded_path"):
                if item.get(key):
                    candidates.append(str(item[key]))
    conversation = metadata.get("conversation_context")
    if isinstance(conversation, dict):
        for entry in conversation.get("items") or []:
            if isinstance(entry, dict):
                candidates.extend(str(item) for item in entry.get("downloaded_paths") or [] if str(item or "").strip())
    return _dedupe_paths(candidates)


def _image_part(path: str) -> dict[str, Any] | None:
    file_path = Path(path)
    if not file_path.is_file() or file_path.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    if file_path.stat().st_size > MAX_IMAGE_PART_BYTES:
        return None
    mime_type = mimetypes.guess_type(file_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return {"image_data": {"mime_type": mime_type, "data": encoded, "path": str(file_path)}}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def _first_regex_value(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


def _inventory_location_key(value: str) -> str:
    text = str(value or "").strip()
    return INVENTORY_LOCATION_ALIASES.get(text, text)


def _structured_context_strings(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, dict):
        for key in ("text", "name", "value"):
            if key in value:
                strings = _structured_context_strings(value.get(key))
                if strings:
                    return strings
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_structured_context_strings(item))
        return result
    return []


def _daily_context_field_values(value: Any, keys: set[str]) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for raw_key, raw_value in value.items():
            key = str(raw_key or "").strip()
            if key in keys:
                result.extend(_structured_context_strings(raw_value))
            if isinstance(raw_value, (dict, list)):
                result.extend(_daily_context_field_values(raw_value, keys))
    elif isinstance(value, list):
        for item in value:
            result.extend(_daily_context_field_values(item, keys))
    return _dedupe_paths(result)


def _single_daily_context_field(value: Any, keys: set[str]) -> str:
    values = _daily_context_field_values(value, keys)
    return values[0] if len(values) == 1 else ""


class WardrobeMixin:
    def _wardrobe_contract(self) -> dict[str, Any]:
        return _read_json(WARDROBE_CONTRACT_PATH)

    def _wardrobe_context_contract(self) -> dict[str, Any]:
        return _read_json(WARDROBE_CONTEXT_CONTRACT_PATH)

    def _wardrobe_projection(self) -> dict[str, Any]:
        return self._wardrobe_contract()["projection_contracts"]["feishu.wardrobe_items"]

    def _wardrobe_entity(self) -> dict[str, Any]:
        return self._wardrobe_contract()["entity_contracts"]["WardrobeItem"]

    def _wardrobe_field_map(self) -> dict[str, str]:
        return dict(self._wardrobe_projection()["field_name_map"])

    def _wardrobe_registry_entry(self) -> dict[str, Any]:
        registry = _read_json(WARDROBE_REGISTRY_PATH)
        entry = (registry.get("tables") or {}).get("wardrobe_items")
        if not isinstance(entry, dict):
            raise RuntimeError("wardrobe-config.json missing tables.wardrobe_items; run setup_wardrobe_bitable.py --apply")
        if not entry.get("app_token") or not entry.get("table_id"):
            raise RuntimeError("wardrobe-config.json missing app_token/table_id for wardrobe_items")
        return entry

    def _wardrobe_table_ref(self) -> dict[str, str]:
        entry = self._wardrobe_registry_entry()
        env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
        return {
            "app_token": str(entry["app_token"]),
            "table_id": str(entry["table_id"]),
            "url": str(env.get("WARDROBE_ITEMS_URL") or (entry.get("table") or {}).get("url") or ""),
        }

    def _wardrobe_token(self) -> str:
        _, registry = _load_feishu_integrations()
        return registry.tenant_access_token()

    def _wardrobe_field_defs(self, token: str, table_ref: dict[str, str]) -> dict[str, dict[str, Any]]:
        _, registry = _load_feishu_integrations()
        items = registry.list_fields(token, table_ref["app_token"], table_ref["table_id"])
        return {str(item.get("field_name") or ""): item for item in items if item.get("field_name")}

    def _wardrobe_records(self, token: str, table_ref: dict[str, str], field_defs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        reminder, registry = _load_feishu_integrations()
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            query = {"page_size": 100}
            if page_token:
                query["page_token"] = page_token
            payload = registry.request_json(
                "GET",
                f"/bitable/v1/apps/{table_ref['app_token']}/tables/{table_ref['table_id']}/records?{urllib.parse.urlencode(query)}",
                token=token,
            )
            data = payload.get("data") or {}
            for record in data.get("items") or []:
                decoded = reminder._decode_fields_for_read(record.get("fields") or {}, field_defs)
                records.append({"record_id": str(record.get("record_id") or ""), "fields": decoded})
            if not data.get("has_more"):
                return records
            page_token = str(data.get("page_token") or "")
            if not page_token:
                return records

    def _find_wardrobe_record_by_item_id(
        self,
        token: str,
        table_ref: dict[str, str],
        field_defs: dict[str, dict[str, Any]],
        item_id: str,
    ) -> dict[str, Any] | None:
        field_name = self._wardrobe_field_map()["item_id"]
        for record in self._wardrobe_records(token, table_ref, field_defs):
            if str((record.get("fields") or {}).get(field_name) or "").strip().lower() == item_id.lower():
                return record
        return None

    def _allowed_wardrobe_fields(self) -> set[str]:
        return set(self._wardrobe_projection()["agent_write_fields"])

    def _validate_wardrobe_fields(self, fields: dict[str, Any], *, allow_name_missing: bool = False) -> dict[str, Any]:
        entity_fields = self._wardrobe_entity()["fields"]
        allowed = self._allowed_wardrobe_fields()
        clean: dict[str, Any] = {}
        for key, raw_value in fields.items():
            if key not in allowed or raw_value in (None, "", []):
                continue
            spec = entity_fields.get(key) or {}
            allowed_values = spec.get("allowed_values") or []
            if allowed_values:
                if spec.get("type") == "multi_select":
                    values = [item for item in _string_list(raw_value) if item in allowed_values and not item.startswith("opt")]
                    if values:
                        clean[key] = values
                else:
                    value = _string_list(raw_value)[0] if _string_list(raw_value) else ""
                    if value in allowed_values and not value.startswith("opt"):
                        clean[key] = value
                continue
            clean[key] = raw_value
        if not allow_name_missing and not str(clean.get("display_name") or "").strip():
            raise ValueError("LLM 未返回 display_name，已停止写入")
        return clean

    def _wardrobe_display_fields(self, canonical_fields: dict[str, Any]) -> dict[str, Any]:
        field_map = self._wardrobe_field_map()
        return {field_map[key]: value for key, value in canonical_fields.items() if key in field_map}

    def _wardrobe_uploads(self, token: str, table_ref: dict[str, str], paths: list[str], indexes: list[int]) -> list[dict[str, str]]:
        reminder, _ = _load_feishu_integrations()
        uploads: list[dict[str, str]] = []
        for index in indexes:
            if index < 0 or index >= len(paths):
                continue
            path = paths[index]
            if not Path(path).is_file():
                continue
            uploads.append(reminder._upload_bitable_attachment(token, table_ref["app_token"], path))
        return uploads

    def _create_wardrobe_record(
        self,
        token: str,
        table_ref: dict[str, str],
        field_defs: dict[str, dict[str, Any]],
        fields: dict[str, Any],
    ) -> str:
        reminder, registry = _load_feishu_integrations()
        coerced = reminder._coerce_fields_for_write(fields, field_defs)
        payload = registry.request_json(
            "POST",
            f"/bitable/v1/apps/{table_ref['app_token']}/tables/{table_ref['table_id']}/records",
            token=token,
            json={"fields": coerced},
        )
        return str(((payload.get("data") or {}).get("record") or {}).get("record_id") or "")

    def _update_wardrobe_record(
        self,
        token: str,
        table_ref: dict[str, str],
        field_defs: dict[str, dict[str, Any]],
        record_id: str,
        fields: dict[str, Any],
    ) -> None:
        reminder, registry = _load_feishu_integrations()
        coerced = reminder._coerce_fields_for_write(fields, field_defs)
        registry.request_json(
            "PUT",
            f"/bitable/v1/apps/{table_ref['app_token']}/tables/{table_ref['table_id']}/records/{record_id}",
            token=token,
            json={"fields": coerced},
        )

    def _wardrobe_llm_json(self, prompt: str, image_paths: list[str]) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for path in image_paths:
            part = _image_part(path)
            if part:
                parts.append(part)
        return generate_json_from_parts(
            parts,
            load_profile_llm_settings("media_analysis"),
            max_retries=1,
            error_prefix="Wardrobe OS LLM JSON failed",
            validation_contract=WARDROBE_LLM_VALIDATION_CONTRACT,
        )

    def _resolve_wardrobe_weather(self, location_name: str) -> dict[str, Any]:
        return fetch_wardrobe_weather(location_name)

    def _wardrobe_intake_prompt(self, message: Message, image_count: int, *, update_mode: bool) -> str:
        projection = self._wardrobe_projection()
        entity_fields = self._wardrobe_entity()["fields"]
        mode = "补充已入库衣服的截图/OCR字段" if update_mode else "新衣物入库"
        return json.dumps(
            {
                "task": f"Wardrobe OS {mode}",
                "body": message.body,
                "image_count": image_count,
                "allowed_agent_write_fields": projection["agent_write_fields"],
                "field_contract": {
                    key: {
                        "type": spec.get("type"),
                        "allowed_values": spec.get("allowed_values", []),
                        "class": spec.get("class"),
                    }
                    for key, spec in entity_fields.items()
                    if key in projection["agent_write_fields"]
                },
                "rules": [
                    "只返回 JSON object，不要 Markdown。",
                    "fields 只能使用 allowed_agent_write_fields 的英文 key。",
                    "item_id、created_at、photo、receipts 由 Python 写入，不能放入 fields。",
                    "看不清或证据不足时返回 status=pending_manual 和 reason，不要猜。",
                    "截图类型请写入 evidence_types，取值可用 标题截图/价格订单截图/洗涤标签/吊牌/实物照。",
                    "photo_indexes 和 receipt_indexes 使用 0-based 图片序号；不确定就放 receipt_indexes。",
                ],
                "output_schema": {
                    "status": "done | pending_manual",
                    "reason": "string",
                    "fields": "object",
                    "recognized_fields": ["string"],
                    "missing_fields": ["string"],
                    "evidence_types": ["string"],
                    "photo_indexes": [0],
                    "receipt_indexes": [0],
                },
            },
            ensure_ascii=False,
        )

    def handle_衣物_入库(self, message: Message) -> TaskResult:
        body = message.body.strip()
        paths = _attachment_paths_from_metadata(message.metadata)
        item_id = _wardrobe_item_id_from_message(message)
        if not body and not paths:
            return TaskResult(
                ok=False,
                status="wardrobe_ingest_missing_input",
                reply="请在 `【衣橱】` 后写衣物标题/说明，或附上实物照、淘宝截图、洗标截图。",
                task_id="",
            )
        if paths and not item_id and re.search(r"(补充|追加|更新|后补|截图|订单|洗标|吊牌)", body) and "入库" not in body:
            return TaskResult(
                ok=False,
                status="wardrobe_item_link_pending",
                reply="这批截图需要关联到已入库衣物。请回复入库确认里的衣物ID，或发送 `【衣橱】衣物ID：...` 后再补截图。",
                task_id="",
            )

        try:
            parsed = self._wardrobe_llm_json(
                self._wardrobe_intake_prompt(message, len(paths), update_mode=bool(item_id)),
                paths,
            )
        except Exception as exc:
            return TaskResult(
                ok=False,
                status="wardrobe_ingest_pending_manual",
                reply=f"衣物入库未写入：LLM 未返回可用结构化结果。原因：{exc}",
                task_id=item_id,
            )
        if str(parsed.get("status") or "").strip() not in {"done", "ok"}:
            return TaskResult(
                ok=False,
                status="wardrobe_ingest_pending_manual",
                reply=f"衣物入库未写入：{parsed.get('reason') or '证据不足，需要人工确认'}",
                task_id=item_id,
                extra={"wardrobe_parse": parsed},
            )

        try:
            canonical_fields = self._validate_wardrobe_fields(_first_dict(parsed.get("fields")), allow_name_missing=bool(item_id))
        except ValueError as exc:
            return TaskResult(ok=False, status="wardrobe_ingest_pending_manual", reply=f"衣物入库未写入：{exc}", task_id=item_id, extra={"wardrobe_parse": parsed})

        try:
            token = self._wardrobe_token()
            table_ref = self._wardrobe_table_ref()
            field_defs = self._wardrobe_field_defs(token, table_ref)
        except Exception as exc:
            return TaskResult(ok=False, status="wardrobe_registry_failed", reply=f"衣物入库未写入：读取衣橱表配置失败：{exc}", task_id=item_id)

        field_map = self._wardrobe_field_map()
        display_fields = self._wardrobe_display_fields(canonical_fields)
        receipt_indexes = [int(item) for item in parsed.get("receipt_indexes") or [] if str(item).lstrip("-").isdigit()]
        photo_indexes = [int(item) for item in parsed.get("photo_indexes") or [] if str(item).lstrip("-").isdigit()]
        if not receipt_indexes and paths and item_id:
            receipt_indexes = list(range(len(paths)))
        if not photo_indexes and paths and not item_id:
            photo_indexes = [0]
            receipt_indexes = [index for index in range(len(paths)) if index not in photo_indexes]

        try:
            if item_id:
                existing = self._find_wardrobe_record_by_item_id(token, table_ref, field_defs, item_id)
                if not existing:
                    return TaskResult(ok=False, status="wardrobe_item_not_found", reply=f"未找到衣物ID：{item_id}。未写入截图。", task_id=item_id)
                uploads = self._wardrobe_uploads(token, table_ref, paths, receipt_indexes)
                if uploads:
                    display_fields[field_map["receipts"]] = uploads
                if not display_fields:
                    return TaskResult(ok=False, status="wardrobe_ingest_pending_manual", reply="没有可写入字段或附件，已停止更新。", task_id=item_id)
                self._update_wardrobe_record(token, table_ref, field_defs, existing["record_id"], display_fields)
                reply = "\n".join(
                    [
                        "已补充衣橱记录。",
                        f"衣物ID：{item_id}",
                        f"更新字段：{('、'.join(display_fields.keys())) or '附件'}",
                    ]
                )
                return TaskResult(ok=True, status="wardrobe_item_updated", reply=reply, task_id=item_id, feishu_doc=table_ref["url"], extra={"wardrobe_parse": parsed})

            new_item_id = str(uuid.uuid4())
            display_fields[field_map["item_id"]] = new_item_id
            display_fields[field_map["created_at"]] = message.created_at.isoformat(timespec="seconds")
            display_fields.setdefault(field_map["status"], self._wardrobe_entity()["fields"]["status"].get("default", "待确认"))
            photo_uploads = self._wardrobe_uploads(token, table_ref, paths, photo_indexes)
            receipt_uploads = self._wardrobe_uploads(token, table_ref, paths, receipt_indexes)
            if photo_uploads:
                display_fields[field_map["photo"]] = photo_uploads
            if receipt_uploads:
                display_fields[field_map["receipts"]] = receipt_uploads
            record_id = self._create_wardrobe_record(token, table_ref, field_defs, display_fields)
        except Exception as exc:
            return TaskResult(ok=False, status="wardrobe_bitable_write_failed", reply=f"衣物入库写入失败：{exc}", task_id=item_id)

        display_name = str(canonical_fields.get("display_name") or "").strip()
        recognized = "、".join(_string_list(parsed.get("recognized_fields"))) or "名称"
        missing = "、".join(_string_list(parsed.get("missing_fields"))) or "无"
        reply = "\n".join(
            [
                "已写入衣橱。",
                f"名称：{display_name}",
                f"衣物ID：{new_item_id}",
                f"识别字段：{recognized}",
                f"待补字段：{missing}",
            ]
        )
        return TaskResult(
            ok=True,
            status="wardrobe_item_created",
            reply=reply,
            task_id=new_item_id,
            feishu_doc=table_ref["url"],
            extra={"record_id": record_id, "wardrobe_parse": parsed},
        )

    def _wardrobe_context(self, message: Message) -> dict[str, Any]:
        metadata = message.metadata or {}
        body = message.body or ""
        daily_context = metadata.get("daily_context") or metadata.get("todo_context") or {}
        if not daily_context and os.getenv("WARDROBE_DAILY_CONTEXT_JSON"):
            try:
                daily_context = json.loads(os.environ["WARDROBE_DAILY_CONTEXT_JSON"])
            except json.JSONDecodeError:
                daily_context = {}
        location = _first_regex_value(LOCATION_RE, body)
        if not location:
            for key in ("current_location", "wardrobe_location"):
                value = str(metadata.get(key) or "").strip()
                if value:
                    location = value
                    break
        if not location:
            location = _single_daily_context_field(daily_context, DAILY_CURRENT_LOCATION_KEYS)
        if not location:
            location = os.getenv("WARDROBE_DEFAULT_LOCATION", "").strip()
        weather_location = _first_regex_value(WEATHER_LOCATION_RE, body)
        if not weather_location:
            for key in ("weather_location", "destination", "destination_location"):
                value = str(metadata.get(key) or "").strip()
                if value:
                    weather_location = value
                    break
        if not weather_location:
            weather_location = _single_daily_context_field(daily_context, DAILY_WEATHER_LOCATION_KEYS)
        if not weather_location:
            weather_location = location
        weather = metadata.get("weather_context") or metadata.get("weather")
        if not weather and os.getenv("WARDROBE_WEATHER_CONTEXT_JSON"):
            try:
                weather = json.loads(os.environ["WARDROBE_WEATHER_CONTEXT_JSON"])
            except json.JSONDecodeError:
                weather = {}
        weather_error = ""
        if not weather and weather_location:
            try:
                weather = self._resolve_wardrobe_weather(weather_location)
            except WardrobeWeatherError as exc:
                weather = {}
                weather_error = str(exc)
        missing = []
        if not location or location == "未定位":
            missing.append("current_location")
        if not isinstance(weather, dict) or not (weather.get("summary") and weather.get("temperature")):
            missing.append("weather")
        return {
            "location": location,
            "inventory_location": _inventory_location_key(location),
            "weather_location": weather_location,
            "weather": weather if isinstance(weather, dict) else {},
            "weather_error": weather_error,
            "daily_context": daily_context,
            "missing": missing,
        }

    def _wardrobe_recommendation_prompt(self, message: Message, context: dict[str, Any], items: list[dict[str, Any]], table_url: str) -> str:
        return json.dumps(
            {
                "task": "Wardrobe OS outfit or packing recommendation",
                "body": message.body,
                "context": {
                    "current_location": context["location"],
                    "weather_location": context.get("weather_location") or context["location"],
                    "weather": context["weather"],
                    "daily_context": context["daily_context"] or "absent",
                },
                "wardrobe_items": items,
                "rules": [
                    "只返回 JSON object，不要 Markdown。",
                    "只能基于 wardrobe_items 中存在的单品推荐，不要发明衣服。",
                    "如果信息不足，返回 status=pending_manual 和 reason。",
                    "sections.items 里的 item_id 必须来自 wardrobe_items；display_name 使用原记录名称。",
                    "推荐可以覆盖今日穿搭、备选、旅行行李，但只写 Obsidian artifact，不更新衣橱事实。",
                ],
                "output_schema": {
                    "status": "done | pending_manual",
                    "title": "string",
                    "summary": "string",
                    "source": {"wardrobe_table_url": table_url, "item_record_ids": ["record_id"]},
                    "sections": [{"heading": "string", "items": [{"item_id": "string", "display_name": "string", "color": "string", "brand": "string", "occasion": ["string"], "note": "string"}]}],
                },
            },
            ensure_ascii=False,
        )

    def handle_穿搭(self, message: Message) -> TaskResult:
        context = self._wardrobe_context(message)
        if context["missing"]:
            return TaskResult(
                ok=False,
                status="wardrobe_context_pending",
                reply="穿搭推荐缺少必要上下文："
                + "、".join(context["missing"])
                + (
                    f"。天气获取失败：{context.get('weather_error')}"
                    if context.get("weather_error")
                    else "。仅从本次消息明示字段、metadata、Daily/待办/日程的结构化地点字段或已登记默认位置读取；本次不使用手填天气、Codex 搜索、服务器 IP、历史消息或正文猜测补位置。"
                ),
                task_id="",
                extra={"wardrobe_context": context},
            )

        try:
            token = self._wardrobe_token()
            table_ref = self._wardrobe_table_ref()
            field_defs = self._wardrobe_field_defs(token, table_ref)
            records = self._wardrobe_records(token, table_ref, field_defs)
        except Exception as exc:
            return TaskResult(ok=False, status="wardrobe_read_failed", reply=f"读取衣橱失败：{exc}", task_id="")

        field_map = self._wardrobe_field_map()
        reverse_field_map = {value: key for key, value in field_map.items()}
        items: list[dict[str, Any]] = []
        for record in records:
            raw_fields = record.get("fields") or {}
            item = {reverse_field_map[name]: value for name, value in raw_fields.items() if name in reverse_field_map}
            if item.get("status") == "已弃":
                continue
            location = _inventory_location_key(str(item.get("location") or "").strip())
            if location and location not in {context["inventory_location"], "行李中", "未定位"}:
                continue
            item["record_id"] = record.get("record_id", "")
            items.append(item)
        if not items:
            return TaskResult(ok=False, status="wardrobe_no_items", reply="当前上下文下没有可推荐的衣橱单品。", task_id="")

        try:
            artifact = self._wardrobe_llm_json(self._wardrobe_recommendation_prompt(message, context, items, table_ref["url"]), [])
        except Exception as exc:
            return TaskResult(ok=False, status="wardrobe_recommendation_pending_manual", reply=f"穿搭推荐未生成：LLM 未返回可用结构化结果。原因：{exc}", task_id="")
        if str(artifact.get("status") or "").strip() not in {"done", "ok"}:
            return TaskResult(ok=False, status="wardrobe_recommendation_pending_manual", reply=f"穿搭推荐未生成：{artifact.get('reason') or '证据不足'}", task_id="", extra={"wardrobe_recommendation": artifact})

        source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
        source.setdefault("wardrobe_table_url", table_ref["url"])
        artifact["source"] = source
        root = Path(os.getenv("WARDROBE_OBSIDIAN_ITEMS_ROOT", "")) if os.getenv("WARDROBE_OBSIDIAN_ITEMS_ROOT") else DEFAULT_WARDROBE_ITEMS_ROOT
        path = render_wardrobe_markdown_artifact(artifact, root=root)
        summary = str(artifact.get("summary") or "").strip()
        reply = "\n".join(part for part in ("已生成穿搭/行李建议。", f"路径：{path}", summary) if part)
        return TaskResult(
            ok=True,
            status="wardrobe_recommendation_written",
            reply=reply,
            task_id="",
            local_path=str(path),
            extra={"wardrobe_recommendation": artifact},
        )
