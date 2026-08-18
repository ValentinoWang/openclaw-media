"""Canonical schema and deterministic payload helpers for DeepMath CEO Thinking.

The three Feishu tables are the human-readable audit projection.  Approval and
execution claims are owned by the local U5 ledger; this module only owns the
field contract and the deterministic values shared by both projections.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping
import re


SCHEMA_VERSION = 2
BASE_NAME = "DeepMath CEO Thinking"
TASK_TABLE_NAME = "任务池（飞书任务唯一）"
OPTION_ID_RE = re.compile(r"^opt[A-Za-z0-9]{6,}$")
FIELD_TYPE_MAP = MappingProxyType({
    "text": 1,
    "number": 2,
    "single_select": 3,
    "multi_select": 4,
    "datetime": 5,
    "checkbox": 7,
    "user": 11,
    "url": 15,
    "attachment": 17,
    "linked_record": 18,
})

PROPOSAL_STATES = ("待确认", "已取代", "已取消", "已过期")
DECISION_STATES = ("待决定", "已批准", "已拒绝", "仅保存")
EXECUTION_STATES = (
    "未授权", "待领取", "执行中", "执行成功", "执行失败", "结果未知", "已跳过", "人工处理"
)


def canonical_json(payload: Any) -> str:
    """Return the one canonical JSON representation used for fingerprints."""

    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("proposal payload must be JSON-serializable") from exc


def payload_fingerprint(payload: Any) -> str:
    """Return the SHA-256 of a canonical proposal payload."""

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def fingerprint_canonical_payload(canonical_payload: str) -> str:
    """Hash an already-rendered canonical payload without reformatting it."""

    if not isinstance(canonical_payload, str) or not canonical_payload:
        raise ValueError("canonical payload must be a non-empty string")
    try:
        decoded = json.loads(canonical_payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("canonical payload must contain JSON") from exc
    if canonical_json(decoded) != canonical_payload:
        raise ValueError("payload is not in canonical JSON form")
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def make_execution_key(
    tenant_key: str,
    proposal_id: str,
    proposal_version: int,
    approval_id: str,
    payload_sha256: str,
) -> str:
    """Build the stable idempotency key required by the U5 ledger."""

    parts = (tenant_key, proposal_id, str(int(proposal_version)), approval_id, payload_sha256)
    if any(not str(part).strip() for part in parts):
        raise ValueError("execution key components must be non-empty")
    return "|".join(str(part) for part in parts)


@dataclass(frozen=True)
class FieldContract:
    name: str
    type_name: str
    required: bool = False
    options: tuple[str, ...] = ()
    target_table: str | None = None

    def as_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "name": self.name,
            "type": self.type_name,
            "feishu_type": FIELD_TYPE_MAP[self.type_name],
            "required": self.required,
        }
        if self.options:
            value["options"] = list(self.options)
        if self.target_table:
            value["target_table"] = self.target_table
        return value


@dataclass(frozen=True)
class TableContract:
    name: str
    fields: tuple[FieldContract, ...]
    purpose: str

    def as_mapping(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "fields": [field.as_mapping() for field in self.fields],
        }


INBOX = TableContract(
    "思考收件箱",
    (
        FieldContract("思考ID", "text", True), FieldContract("标题", "text", True),
        FieldContract("原始内容", "text", True), FieldContract("原始附件", "attachment"),
        FieldContract("来源", "single_select", True, ("私聊", "群聊", "语音", "截图", "文件", "链接")),
        FieldContract("核心含义", "text"), FieldContract("已知事实", "text"),
        FieldContract("我的判断", "text"), FieldContract("待验证假设", "text"),
        FieldContract("关联领域", "multi_select", options=("产品", "技术", "商业模式", "市场与客户", "融资", "团队与组织", "科研方向")),
        FieldContract("处理状态", "single_select", True, ("已收件", "结构化中", "待审批", "仅保存", "退回重整", "部分执行", "已执行", "人工处理")),
        FieldContract("未填写原因", "text"), FieldContract("接收时间", "datetime", True),
        FieldContract("提交人", "user", True),
    ),
    "保存原始思考证据与 LLM 结构化语义，不保存正式任务状态。",
)

DECISIONS = TableContract(
    "决策池",
    (
        FieldContract("决策ID", "text", True), FieldContract("关联思考", "linked_record", True, target_table="思考收件箱"),
        FieldContract("决策问题", "text", True), FieldContract("背景", "text", True),
        FieldContract("可选方案", "text", True), FieldContract("推荐方案", "text"),
        FieldContract("判断依据", "text", True), FieldContract("不决策的后果", "text"),
        FieldContract("决策人", "user", True),
        FieldContract("决策状态", "single_select", True, ("待审批", "做", "不做", "延后", "先实验", "退回补充")),
        FieldContract("决策结果说明", "text"), FieldContract("复盘时间", "datetime"),
    ),
    "保存需要 CEO/负责人判断的决策，不直接替代审批记录。",
)

APPROVALS = TableContract(
    "审批记录",
    (
        # Existing source, object, readable-parameter, and external projection fields.
        FieldContract("审批ID", "text", True), FieldContract("关联思考", "linked_record", True, target_table="思考收件箱"),
        FieldContract("关联决策", "linked_record", target_table="决策池"),
        FieldContract("对象类型", "single_select", True, ("资源", "任务", "通知", "提醒", "日历事件", "催办", "结果回流")),
        FieldContract("候选动作", "single_select", True, ("创建", "分派", "发送", "修改", "取消", "绑定", "回写")),
        FieldContract("对象摘要", "text", True), FieldContract("执行参数", "text", True),
        FieldContract("DRI", "user"), FieldContract("Reviewer", "user"), FieldContract("截止时间", "datetime"),
        FieldContract("外部对象ID", "text"), FieldContract("外部对象链接", "url"),
        FieldContract("执行结果", "text"),
        # Versioned proposal and independent decision/execution state.
        FieldContract("提案ID", "text", True), FieldContract("提案版本", "number", True),
        FieldContract("提案项序号", "number", True), FieldContract("参数指纹", "text", True),
        FieldContract("提案过期时间", "datetime", True),
        FieldContract("提案状态", "single_select", True, PROPOSAL_STATES),
        FieldContract("审批决定", "single_select", True, DECISION_STATES),
        FieldContract("执行状态", "single_select", True, EXECUTION_STATES),
        FieldContract("审批人", "user"), FieldContract("审批时间", "datetime"),
        FieldContract("执行键", "text", True), FieldContract("执行尝试", "number", True),
        FieldContract("上游请求ID", "text"), FieldContract("最后回读时间", "datetime"),
    ),
    "保存版本化提案的可读审批审计与外部对象回读，不复制飞书任务完整状态。",
)


TABLE_CONTRACTS: Mapping[str, TableContract] = MappingProxyType({
    INBOX.name: INBOX,
    DECISIONS.name: DECISIONS,
    APPROVALS.name: APPROVALS,
})


def validate_schema() -> None:
    if SCHEMA_VERSION != 2:
        raise ValueError("DeepMath CEO Thinking schema version must be 2")
    if set(TABLE_CONTRACTS) != {INBOX.name, DECISIONS.name, APPROVALS.name}:
        raise ValueError("DeepMath CEO Thinking must contain exactly three canonical tables")
    for table in TABLE_CONTRACTS.values():
        names = [field.name for field in table.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate field in {table.name}")
        if "审批状态" in names:
            raise ValueError("mixed approval state is not part of schema v2")
        for field in table.fields:
            if field.type_name not in FIELD_TYPE_MAP:
                raise ValueError(f"unknown Feishu field type: {field.type_name}")
            if any(OPTION_ID_RE.fullmatch(option) for option in field.options):
                raise ValueError(f"option id leaked into {table.name}.{field.name}")
            if field.type_name in {"single_select", "multi_select"} and not field.options:
                raise ValueError(f"select field has no canonical options: {table.name}.{field.name}")
    if any(table.name == TASK_TABLE_NAME for table in TABLE_CONTRACTS.values()):
        raise ValueError("Base must not contain a formal task table")
    approval_fields = {field.name: field for field in APPROVALS.fields}
    for field_name, options in (
        ("提案状态", PROPOSAL_STATES),
        ("审批决定", DECISION_STATES),
        ("执行状态", EXECUTION_STATES),
    ):
        field = approval_fields.get(field_name)
        if field is None or field.options != options:
            raise ValueError(f"{field_name} options drifted from the canonical state machine")
    required = {
        "提案ID", "提案版本", "提案项序号", "参数指纹", "提案过期时间",
        "提案状态", "审批决定", "执行状态", "执行键", "执行尝试",
    }
    if not required <= approval_fields.keys():
        raise ValueError("schema v2 proposal and execution fields are incomplete")


def schema_manifest() -> dict[str, Any]:
    validate_schema()
    return {"version": SCHEMA_VERSION, "base_name": BASE_NAME, "tables": [table.as_mapping() for table in TABLE_CONTRACTS.values()]}


def feishu_field_payload(field: FieldContract, table_ids: Mapping[str, str]) -> dict[str, Any]:
    """Render one canonical field definition using live table ids only."""

    payload: dict[str, Any] = {"field_name": field.name, "type": FIELD_TYPE_MAP[field.type_name]}
    if field.options:
        payload["property"] = {"options": [{"name": option} for option in field.options]}
    elif field.type_name == "user":
        payload["property"] = {"multiple": False}
    elif field.type_name == "linked_record":
        target_id = str(table_ids.get(field.target_table or "") or "").strip()
        if not target_id:
            raise ValueError(f"live target table id is required for {field.name}")
        payload["property"] = {"table_id": target_id, "multiple": False}
    return payload
