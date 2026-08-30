"""DeepMath-only U3 intake and candidate writer.

The writer persists immutable source evidence before asking the LLM for one
structured result.  It only writes the three DeepMath Base tables: executing
tasks, reminders, messages, or calendar changes belongs to later units.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
from typing import Any, Mapping

import requests

from common.llm_client import image_part_from_path

from .deepmath_ceo_thinking_schema import (
    APPROVALS,
    DECISIONS,
    INBOX,
    canonical_json,
    make_execution_key,
    payload_fingerprint,
)
from .deepmath_resources import DEEP_MATH_FEISHU_ACCOUNT_ID, load_resource_config
from .deepmath_runtime_config import load_deepmath_account, load_deepmath_allowed_senders
from .deepmath_approval_service import DeepMathApprovalService
from .deepmath_approval_store import DeepMathApprovalStore
from .deepmath_people_runtime import make_people_recommendation_service


FEISHU_API = "https://open.feishu.cn/open-apis"
LLM_PROFILE = "deepmath_ceo_thinking_structure"
LLM_STAGE = "DeepMath CEO 思考结构化"
ALLOWED_DOMAINS = {"产品", "技术", "商业模式", "市场与客户", "融资", "团队与组织", "科研方向"}
ALLOWED_OBJECT_TYPES = {"资源", "任务", "通知", "提醒", "日历事件", "催办", "结果回流"}
ALLOWED_ACTIONS = {"创建", "分派", "发送", "修改", "取消", "绑定", "回写"}
ALLOWED_CANDIDATE_KINDS = {"最小实验", "任务", "其他动作"}
IMAGE_MIME_PREFIX = "image/"
AUDIO_MIME_PREFIX = "audio/"
PROPOSAL_TTL = timedelta(days=7)
PEOPLE_REQUIRED_OBJECT_TYPES = frozenset({"任务", "通知", "提醒", "日历事件", "催办"})
PEOPLE_LLM_PROFILE = "deepmath_people_recommendation"
PEOPLE_LLM_STAGE = "DeepMath 负责人证据推荐"


class DeepMathThinkingError(RuntimeError):
    pass


def _clean(value: Any, limit: int = 10000) -> str:
    return str(value or "").strip()[:limit]


def _lines(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(f"- {_clean(item, 2000)}" for item in value if _clean(item, 2000))
    return _clean(value)


class DeepMathBitableClient:
    def __init__(self, app_token: str, app_id: str, app_secret: str):
        self.app_token = app_token
        response = requests.post(
            f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret}, timeout=30,
        )
        payload = response.json()
        self.token = _clean(payload.get("tenant_access_token"), 300)
        if response.status_code >= 400 or payload.get("code") not in (None, 0) or not self.token:
            raise DeepMathThinkingError("DeepMath Feishu authentication failed")
        self.table_ids = self._load_table_ids()

    def _request(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
        response = requests.request(
            method, FEISHU_API + path,
            headers={"Authorization": f"Bearer {self.token}"},
            params=params, json=body, timeout=30,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise DeepMathThinkingError(f"Feishu returned non-JSON for {method} {path}") from exc
        if response.status_code >= 400 or payload.get("code") not in (None, 0):
            raise DeepMathThinkingError(f"Feishu rejected {method} {path}: {payload.get('code')} {payload.get('msg')}")
        return payload

    def _load_table_ids(self) -> dict[str, str]:
        payload = self._request("GET", f"/bitable/v1/apps/{self.app_token}/tables", params={"page_size": 100})
        result = {str(item.get("name")): str(item.get("table_id")) for item in (payload.get("data") or {}).get("items") or []}
        required = {INBOX.name, DECISIONS.name, APPROVALS.name}
        if set(result) != required:
            raise DeepMathThinkingError("DeepMath Base is not the canonical three-table schema")
        return result

    def list_records(self, table_name: str) -> list[dict[str, Any]]:
        table_id = self.table_ids[table_name]
        payload = self._request("GET", f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records", params={"page_size": 500})
        return list((payload.get("data") or {}).get("items") or [])

    def find(self, table_name: str, field_name: str, value: str) -> dict[str, Any] | None:
        for item in self.list_records(table_name):
            if _clean((item.get("fields") or {}).get(field_name), 500) == value:
                return item
        return None

    def get(self, table_name: str, record_id: str) -> dict[str, Any]:
        table_id = self.table_ids[table_name]
        payload = self._request("GET", f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}")
        return (payload.get("data") or {}).get("record") or {}

    def create(self, table_name: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        table_id = self.table_ids[table_name]
        payload = self._request("POST", f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records", body={"fields": dict(fields)})
        return (payload.get("data") or {}).get("record") or {}

    def update(self, table_name: str, record_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        table_id = self.table_ids[table_name]
        payload = self._request("PUT", f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}", body={"fields": dict(fields)})
        return (payload.get("data") or {}).get("record") or {}

    def delete(self, table_name: str, record_id: str) -> None:
        table_id = self.table_ids[table_name]
        self._request("DELETE", f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}")

    def send_card(self, open_id: str, card: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._request(
            "POST",
            "/im/v1/messages",
            params={"receive_id_type": "open_id"},
            body={"receive_id": open_id, "msg_type": "interactive", "content": canonical_json(card)},
        )
        data = payload.get("data") or {}
        message = data.get("message") or data
        if not _clean(message.get("message_id"), 300):
            raise DeepMathThinkingError("DeepMath approval card send readback is incomplete")
        return message

    def upload(self, path: Path) -> dict[str, str]:
        if not path.is_file() or path.stat().st_size <= 0:
            raise DeepMathThinkingError(f"attachment unavailable: {path.name}")
        if path.stat().st_size > 20 * 1024 * 1024:
            raise DeepMathThinkingError(f"attachment exceeds U3 direct-upload limit: {path.name}")
        with path.open("rb") as handle:
            response = requests.post(
                f"{FEISHU_API}/drive/v1/medias/upload_all",
                headers={"Authorization": f"Bearer {self.token}"},
                data={"file_name": path.name, "parent_type": "bitable_file", "parent_node": self.app_token, "size": str(path.stat().st_size)},
                files={"file": (path.name, handle, "application/octet-stream")}, timeout=120,
            )
        payload = response.json()
        token = _clean((payload.get("data") or {}).get("file_token"), 300)
        if response.status_code >= 400 or payload.get("code") not in (None, 0) or not token:
            raise DeepMathThinkingError(f"attachment upload failed: {path.name}")
        return {"file_token": token}


def _attachment_items(metadata: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = metadata.get("attachments") or []
    result: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping):
            continue
        path = _clean(item.get("local_path") or item.get("path"), 1000)
        if not path:
            continue
        mime = _clean(item.get("mime_type"), 200) or (mimetypes.guess_type(path)[0] or "application/octet-stream")
        result.append({"path": path, "mime_type": mime, "file_name": _clean(item.get("file_name"), 300) or Path(path).name})
    return result[:8]


def _source(body: str, attachments: list[dict[str, str]], chat_type: str) -> str:
    if any(item["mime_type"].startswith(AUDIO_MIME_PREFIX) for item in attachments):
        return "语音"
    if any(item["mime_type"].startswith(IMAGE_MIME_PREFIX) for item in attachments):
        return "截图"
    if attachments:
        return "文件"
    if re.fullmatch(r"\s*https?://\S+\s*", body):
        return "链接"
    return "群聊" if chat_type == "group" else "私聊"


def _ids(message_id: str, body: str, sender_id: str) -> tuple[str, str]:
    stable = message_id or hashlib.sha256(f"{sender_id}\n{body}".encode()).hexdigest()[:24]
    digest = hashlib.sha256(stable.encode()).hexdigest()[:20]
    return f"TH-{digest}", digest


def _proposal_expiry_ms(created_at: datetime) -> int:
    value = created_at + PROPOSAL_TTL
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _proposal_payload(action: Mapping[str, Any]) -> dict[str, Any]:
    """Select the typed U3 action fields into the immutable proposal payload."""

    return {
        "candidate_kind": action["candidate_kind"],
        "object_type": action["object_type"],
        "action": action["action"],
        "summary": action["summary"],
        "owner_role": action["owner_role"],
        "owner_reason": action["owner_reason"],
        "deliverable": action["deliverable"],
        "acceptance_criteria": action["acceptance_criteria"],
        "execution_parameters": action["execution_parameters"],
        "decision_index": action.get("decision_index"),
    }


def _readable_parameters(action: Mapping[str, Any], canonical_payload: str) -> str:
    lines = [
        f"候选类型：{action['candidate_kind']}",
        f"负责人类型：{action['owner_role']}",
        f"推荐理由：{action['owner_reason']}",
        f"交付物：{action['deliverable']}",
        f"验收标准：{action['acceptance_criteria']}",
    ]
    if action["execution_parameters"]:
        lines.append(f"其他参数：{action['execution_parameters']}")
    lines.append(f"规范化参数：{canonical_payload}")
    return "\n".join(lines)


def _normalize_llm(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "done":
        raise DeepMathThinkingError(_clean(payload.get("reason"), 1000) or "LLM unavailable")
    title = _clean(payload.get("title"), 80)
    if not title:
        raise DeepMathThinkingError("LLM result is missing title")
    decisions: list[dict[str, Any]] = []
    for raw in payload.get("decisions") or []:
        if not isinstance(raw, Mapping):
            continue
        options = [_clean(x, 1000) for x in raw.get("options") or [] if _clean(x, 1000)]
        item = {
            "question": _clean(raw.get("question"), 2000), "background": _clean(raw.get("background"), 4000),
            "options": options, "recommendation": _clean(raw.get("recommendation"), 2000),
            "basis": _clean(raw.get("basis"), 4000), "inaction_consequence": _clean(raw.get("inaction_consequence"), 2000),
        }
        if item["question"] and item["background"] and item["basis"] and len(options) >= 2:
            decisions.append(item)
    actions: list[dict[str, Any]] = []
    for index, raw in enumerate(payload.get("action_candidates") or [], 1):
        if not isinstance(raw, Mapping):
            raise DeepMathThinkingError(f"action candidate {index} must be an object")
        object_type, action = _clean(raw.get("object_type"), 30), _clean(raw.get("action"), 30)
        item = {
            "candidate_kind": _clean(raw.get("candidate_kind"), 30),
            "object_type": object_type,
            "action": action,
            "summary": _clean(raw.get("summary"), 3000),
            "owner_role": _clean(raw.get("owner_role"), 500),
            "owner_reason": _clean(raw.get("owner_reason"), 2000),
            "deliverable": _clean(raw.get("deliverable"), 2000),
            "acceptance_criteria": _clean(raw.get("acceptance_criteria"), 3000),
            "execution_parameters": _clean(raw.get("execution_parameters"), 3000),
            "decision_index": raw.get("decision_index") if isinstance(raw.get("decision_index"), int) else None,
        }
        required = ("summary", "owner_role", "owner_reason", "deliverable", "acceptance_criteria")
        if (
            item["candidate_kind"] not in ALLOWED_CANDIDATE_KINDS
            or object_type not in ALLOWED_OBJECT_TYPES
            or action not in ALLOWED_ACTIONS
            or any(not item[key] for key in required)
        ):
            raise DeepMathThinkingError(f"action candidate {index} is incomplete or outside the U3 contract")
        if item["candidate_kind"] in {"最小实验", "任务"} and (object_type, action) != ("任务", "创建"):
            raise DeepMathThinkingError(f"action candidate {index} task/experiment mapping is invalid")
        actions.append(item)
    return {
        "title": title, "core_meaning": _clean(payload.get("core_meaning"), 500),
        "facts": _lines(payload.get("facts")), "judgments": _lines(payload.get("judgments")),
        "hypotheses": _lines(payload.get("hypotheses")),
        "domains": [x for x in (_clean(v, 50) for v in payload.get("domains") or []) if x in ALLOWED_DOMAINS],
        "missing_reason": _clean(payload.get("missing_reason"), 3000), "decisions": decisions, "actions": actions,
    }


class DeepMathThinkingIntakeService:
    def __init__(
        self,
        resource_config_path: str,
        content_flow_client: Any,
        *,
        people_capability_base_id: str,
        approval_state_path: str,
        approver_open_id: str,
    ):
        resource = load_resource_config(resource_config_path)
        if not resource.base_id or not resource.tenant_proof:
            raise DeepMathThinkingError("DeepMath Base binding is incomplete")
        app_id, app_secret = load_deepmath_account()
        self.client = DeepMathBitableClient(resource.base_id, app_id, app_secret)
        self.content_flow_client = content_flow_client
        self.people_service = make_people_recommendation_service(
            capability_app_token=people_capability_base_id,
            resource=resource,
            access_token=self.client.token,
            llm=self._recommend_people,
        )
        self.allowed_sender_ids = load_deepmath_allowed_senders()
        self.approver_open_id = _clean(approver_open_id, 300)
        signing_secret = os.environ.get("OPENCLAW_DEEPMATH_APPROVAL_TOKEN_SECRET", "").strip()
        if not approval_state_path or not self.approver_open_id or not signing_secret:
            raise DeepMathThinkingError("DeepMath approval ledger configuration is incomplete")
        self.approval_service = DeepMathApprovalService(
            DeepMathApprovalStore(approval_state_path),
            approver_user_id=self.approver_open_id,
            token_signing_secret=signing_secret,
        )

    @staticmethod
    def people_prompt() -> str:
        return (
            "你是 DeepMath 负责人推荐器。只输出 JSON 对象 assignments。"
            "只能复制输入 candidates 中的 candidate_ref；role 只能是 DRI、Reviewer 或 Participant。"
            "DRI 最多一名，Reviewer 最多一名，Participant 可为零或多名；同一候选不能重复。"
            "只依据输入中的人工确认能力、容量与当前 Tasks/Calendar 只读证据，不得猜测人员事实。"
        )

    def _recommend_people(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        result = self.content_flow_client._call_profile_provider_json(
            PEOPLE_LLM_PROFILE,
            self.people_prompt(),
            canonical_json(request),
            PEOPLE_LLM_STAGE,
            max_retries=0,
            capacity_max_retries=0,
        )
        if not isinstance(result, Mapping) or result.get("status") != "done" or not isinstance(result.get("assignments"), list):
            raise DeepMathThinkingError(_clean((result or {}).get("reason") if isinstance(result, Mapping) else "", 1000) or "people recommendation LLM unavailable")
        return {"assignments": list(result["assignments"])}

    @staticmethod
    def prompt() -> str:
        return (
            "你是 DeepMath CEO 原始思考结构化器。只输出合法 JSON，禁止 Markdown。你只有一次结构化机会。"
            "只依据用户原文、明确的语音转写和随附图片；严格区分事实、我的判断、待验证假设。"
            "不要为了显得积极而制造任务、实验或决策；模糊想法允许 actions/decisions 为空。"
            "只有确有至少两个真实选项时才生成 decisions。任何任务、通知、提醒、日历或资源动作都只是待审批候选，绝不声称已执行。"
            "固定 JSON 字段：title, core_meaning, facts, judgments, hypotheses, domains, missing_reason, decisions, action_candidates。"
            "facts/judgments/hypotheses/domains 为字符串数组。domains 只能从 产品、技术、商业模式、市场与客户、融资、团队与组织、科研方向选择。"
            "decisions 每项字段 question,background,options(至少两个),recommendation,basis,inaction_consequence。"
            "action_candidates 每项字段 candidate_kind,object_type,action,summary,owner_role,owner_reason,deliverable,acceptance_criteria,execution_parameters,decision_index。"
            "candidate_kind 只能是最小实验/任务/其他动作；最小实验和任务必须映射为 object_type=任务、action=创建。"
            "owner_role 只写负责人类型而不猜测具体人，owner_reason 说明理由，deliverable 和 acceptance_criteria 必须可供人工审批；execution_parameters 只保存其他明确参数。"
            "object_type 只能是资源/任务/通知/提醒/日历事件/催办/结果回流，action 只能是创建/分派/发送/修改/取消/绑定/回写。"
        )

    def ingest(self, *, body: str, chat_type: str, metadata: Mapping[str, Any], created_at: datetime) -> dict[str, Any]:
        if _clean(metadata.get("account_id"), 100) != DEEP_MATH_FEISHU_ACCOUNT_ID:
            raise DeepMathThinkingError("【思考】is DeepMath-only")
        if chat_type not in {"private", "group"}:
            raise DeepMathThinkingError("DeepMath U3 intake requires a private or allowlisted group chat")
        sender_id = _clean(metadata.get("source_sender_id"), 300)
        if not sender_id:
            raise DeepMathThinkingError("source sender is required")
        if sender_id not in self.allowed_sender_ids:
            raise DeepMathThinkingError("source sender is not in the DeepMath allowlist")
        message_id = _clean(metadata.get("source_message_id"), 300)
        thought_id, digest = _ids(message_id, body, sender_id)
        existing = self.client.find(INBOX.name, "思考ID", thought_id)
        if existing:
            fields = existing.get("fields") or {}
            return {"status": "idempotent_replay", "thought_id": thought_id, "record_id": existing.get("record_id"), "processing_status": fields.get("处理状态"), "chat_type": chat_type, "group_receipt_only": chat_type == "group"}

        attachments = _attachment_items(metadata)
        evidence_text = _clean(body, 20000)
        if not evidence_text and attachments:
            evidence_text = "[附件输入] " + "、".join(item["file_name"] for item in attachments)
        if not evidence_text:
            raise DeepMathThinkingError("原始思考正文或附件至少需要一项")
        received_ms = int(created_at.timestamp() * 1000)
        inbox_fields: dict[str, Any] = {
            "思考ID": thought_id, "标题": f"待整理-{created_at.strftime('%Y%m%d-%H%M%S')}",
            "原始内容": evidence_text, "来源": _source(body, attachments, chat_type),
            "处理状态": "已收件", "接收时间": received_ms, "提交人": [{"id": sender_id}],
        }
        inbox = self.client.create(INBOX.name, inbox_fields)
        inbox_record_id = _clean(inbox.get("record_id"), 300)
        if not inbox_record_id:
            raise DeepMathThinkingError("Feishu did not return the source record id")

        readback = self.client.get(INBOX.name, inbox_record_id)
        readback_fields = readback.get("fields") or {}
        if _clean(readback_fields.get("思考ID"), 300) != thought_id or _clean(readback_fields.get("原始内容"), 20000) != evidence_text:
            raise DeepMathThinkingError("original evidence readback mismatch")
        self.client.update(INBOX.name, inbox_record_id, {"处理状态": "结构化中"})

        try:
            if attachments:
                uploaded = [self.client.upload(Path(item["path"])) for item in attachments]
                self.client.update(INBOX.name, inbox_record_id, {"原始附件": uploaded})
            transcripts: list[str] = []
            parts: list[dict[str, Any]] = [{"text": evidence_text}]
            for index, item in enumerate(attachments):
                path = Path(item["path"])
                if item["mime_type"].startswith(AUDIO_MIME_PREFIX):
                    result = self.content_flow_client.transcribe_file(str(path), path.parent / f"deepmath-asr-{digest}-{index}")
                    if result.get("status") != "done" or not result.get("transcript_path"):
                        raise DeepMathThinkingError(_clean(result.get("reason"), 1000) or "audio transcription failed")
                    transcript = Path(str(result["transcript_path"])).read_text(encoding="utf-8").strip()
                    transcripts.append(transcript)
                elif item["mime_type"].startswith(IMAGE_MIME_PREFIX):
                    # dedup(llm-wrapper-02): this used to append a flat
                    # {"image_data": <base64 str>, "mime_type": ...} part,
                    # which is not the {"image_data": {"mime_type", "data",
                    # "path"}} shape every LLM transport channel expects --
                    # it raised in the openclaw_agent channel and would
                    # AttributeError in the other two. image_part_from_path
                    # builds the correct nested shape; the mime_type is then
                    # overridden with the already-resolved item["mime_type"]
                    # (metadata-provided, or the same extension-based guess
                    # as a fallback) rather than re-derived from the path.
                    image_part = image_part_from_path(path)
                    image_part["image_data"]["mime_type"] = item["mime_type"]
                    parts.append(image_part)
            if transcripts:
                transcript_text = "\n\n".join(transcripts)
                evidence_text = f"{evidence_text}\n\n[语音转写]\n{transcript_text}"
                self.client.update(INBOX.name, inbox_record_id, {"原始内容": evidence_text})
                parts[0] = {"text": evidence_text}
            llm = self.content_flow_client._call_profile_provider_json(
                LLM_PROFILE, self.prompt(), evidence_text, LLM_STAGE,
                max_retries=0, capacity_max_retries=0, parts=parts,
            )
            structured = _normalize_llm(llm)
            has_candidates = bool(structured["decisions"] or structured["actions"])
            self.client.update(INBOX.name, inbox_record_id, {
                "标题": structured["title"], "核心含义": structured["core_meaning"],
                "已知事实": structured["facts"], "我的判断": structured["judgments"],
                "待验证假设": structured["hypotheses"], "关联领域": structured["domains"],
                "处理状态": "待审批" if has_candidates else "仅保存",
                "未填写原因": structured["missing_reason"],
            })
            decision_records: list[str] = []
            for index, decision in enumerate(structured["decisions"], 1):
                decision_id = f"DC-{digest}-{index}"
                record = self.client.create(DECISIONS.name, {
                    "决策ID": decision_id, "关联思考": [inbox_record_id], "决策问题": decision["question"],
                    "背景": decision["background"], "可选方案": "\n".join(f"{i}. {v}" for i, v in enumerate(decision["options"], 1)),
                    "推荐方案": decision["recommendation"], "判断依据": decision["basis"],
                    "不决策的后果": decision["inaction_consequence"], "决策人": [{"id": sender_id}], "决策状态": "待审批",
                })
                decision_records.append(_clean(record.get("record_id"), 300))
            approval_ids: list[str] = []
            approval_card_count = 0
            proposal_id = f"PR-{digest}"
            proposal_expiry = _proposal_expiry_ms(created_at)
            for index, action in enumerate(structured["actions"], 1):
                approval_id = f"AP-{digest}-{index}"
                payload = _proposal_payload(action)
                if action["object_type"] in PEOPLE_REQUIRED_OBJECT_TYPES:
                    payload["people_assignment"] = self.people_service.recommend(task_context=payload)
                canonical_payload = canonical_json(payload)
                payload_sha256 = payload_fingerprint(payload)
                execution_key = make_execution_key(
                    DEEP_MATH_FEISHU_ACCOUNT_ID,
                    proposal_id,
                    1,
                    approval_id,
                    payload_sha256,
                )
                fields: dict[str, Any] = {
                    "审批ID": approval_id, "关联思考": [inbox_record_id], "对象类型": action["object_type"],
                    "候选动作": action["action"], "对象摘要": action["summary"],
                    "执行参数": _readable_parameters(action, canonical_payload),
                    "提案ID": proposal_id, "提案版本": 1, "提案项序号": index,
                    "参数指纹": payload_sha256, "提案过期时间": proposal_expiry,
                    "提案状态": "待确认", "审批决定": "待决定", "执行状态": "未授权",
                    "执行键": execution_key, "执行尝试": 0,
                }
                decision_index = action.get("decision_index")
                if isinstance(decision_index, int) and 0 <= decision_index < len(decision_records) and decision_records[decision_index]:
                    fields["关联决策"] = [decision_records[decision_index]]
                ledger_item = self.approval_service.create_item(
                    tenant_key=DEEP_MATH_FEISHU_ACCOUNT_ID,
                    proposal_id=proposal_id,
                    proposal_version=1,
                    approval_id=approval_id,
                    payload=payload,
                    expires_at=created_at + PROPOSAL_TTL,
                )
                self.client.create(APPROVALS.name, fields)
                self.client.send_card(self.approver_open_id, ledger_item["card"])
                approval_card_count += 1
                approval_ids.append(approval_id)
            return {
                "status": "structured", "thought_id": thought_id, "record_id": inbox_record_id,
                "processing_status": "待审批" if has_candidates else "仅保存",
                "decision_count": len(decision_records), "approval_count": len(approval_ids), "side_effects_executed": False,
                "approval_card_count": approval_card_count,
                "chat_type": chat_type, "group_receipt_only": chat_type == "group",
            }
        except Exception as exc:
            reason = _clean(exc, 1800) or type(exc).__name__
            self.client.update(INBOX.name, inbox_record_id, {"处理状态": "人工处理", "未填写原因": reason})
            return {"status": "pending_manual", "thought_id": thought_id, "record_id": inbox_record_id, "reason": reason, "side_effects_executed": False, "chat_type": chat_type, "group_receipt_only": chat_type == "group"}
