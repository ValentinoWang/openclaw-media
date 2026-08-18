"""Canonical U6 schema and record validation for DeepMath Team Capability.

This module owns the one-table capability contract. Directory identity is
represented only by the single Feishu user field; task and calendar usage stay
outside this table and are combined by a later read-only service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
BASE_NAME = "DeepMath Team Capability"
TABLE_NAME = "成员能力与容量"
RUNTIME_KEY = "deepmath_ceo_thinking.people_capability_base_id"
FEISHU_PRIMARY_FIELD_NAME = "职责范围"
STATUS_OPTIONS = ("待确认", "有效", "失效")
OPTION_ID_RE = re.compile(r"^opt[A-Za-z0-9]{6,}$")

FIELD_TYPE_MAP = MappingProxyType({
    "text": 1,
    "number": 2,
    "single_select": 3,
    "datetime": 5,
    "user": 11,
})

FIELD_NAMES = (
    "成员",
    "职责范围",
    "核心技能",
    "可承担角色",
    "技能证据",
    "未来7天可分配工时",
    "不可用区间",
    "负荷确认时间",
    "负荷有效至",
    "记录状态",
    "维护人",
)
ELIGIBILITY_TEXT_FIELDS = ("职责范围", "核心技能", "可承担角色", "技能证据")


@dataclass(frozen=True)
class FieldContract:
    name: str
    type_name: str
    required: bool = False
    options: tuple[str, ...] = ()
    unique: bool = False

    def as_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "name": self.name,
            "type": self.type_name,
            "feishu_type": FIELD_TYPE_MAP[self.type_name],
            "required": self.required,
        }
        if self.options:
            value["options"] = list(self.options)
        if self.unique:
            value["unique"] = True
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


TEAM_CAPABILITY_FIELDS = (
    FieldContract("成员", "user", required=True, unique=True),
    FieldContract("职责范围", "text"),
    FieldContract("核心技能", "text"),
    FieldContract("可承担角色", "text"),
    FieldContract("技能证据", "text"),
    FieldContract("未来7天可分配工时", "number"),
    FieldContract("不可用区间", "text"),
    FieldContract("负荷确认时间", "datetime"),
    FieldContract("负荷有效至", "datetime"),
    FieldContract("记录状态", "single_select", required=True, options=STATUS_OPTIONS),
    FieldContract("维护人", "user"),
)

TEAM_CAPABILITY_TABLE = TableContract(
    TABLE_NAME,
    TEAM_CAPABILITY_FIELDS,
    "保存人工确认的成员职责、技能、角色、证据与宣告容量；不保存目录副本或派生占用。",
)

TABLE_CONTRACTS: Mapping[str, TableContract] = MappingProxyType({TABLE_NAME: TEAM_CAPABILITY_TABLE})


def validate_schema() -> None:
    """Validate the immutable canonical schema before it is rendered or used."""

    if SCHEMA_VERSION != 1:
        raise ValueError("DeepMath Team Capability schema version must be 1")
    if tuple(TABLE_CONTRACTS) != (TABLE_NAME,):
        raise ValueError("DeepMath Team Capability must contain exactly one canonical table")
    if tuple(field.name for field in TEAM_CAPABILITY_TABLE.fields) != FIELD_NAMES:
        raise ValueError("DeepMath Team Capability fields drifted from the SSOT order")
    for field in TEAM_CAPABILITY_TABLE.fields:
        if field.type_name not in FIELD_TYPE_MAP:
            raise ValueError(f"unknown Feishu field type: {field.type_name}")
        if any(OPTION_ID_RE.fullmatch(option) for option in field.options):
            raise ValueError(f"option id leaked into {TABLE_NAME}.{field.name}")
        if field.type_name == "single_select" and field.options != STATUS_OPTIONS:
            raise ValueError("记录状态 must use the exact human-facing status names")
        if field.type_name == "user" and field.name not in {"成员", "维护人"}:
            raise ValueError(f"unexpected user field: {field.name}")
    member = next(field for field in TEAM_CAPABILITY_TABLE.fields if field.name == "成员")
    if member.type_name != "user" or not member.unique:
        raise ValueError("成员 must be a unique single Feishu user field at record-validation level")
    primary = next(field for field in TEAM_CAPABILITY_TABLE.fields if field.name == FEISHU_PRIMARY_FIELD_NAME)
    if primary.type_name != "text":
        raise ValueError("Feishu primary field must use the canonical text field 职责范围")


def schema_manifest() -> dict[str, Any]:
    validate_schema()
    return {
        "version": SCHEMA_VERSION,
        "base_name": BASE_NAME,
        "runtime_key": RUNTIME_KEY,
        "feishu_primary_field": FEISHU_PRIMARY_FIELD_NAME,
        "tables": [table.as_mapping() for table in TABLE_CONTRACTS.values()],
    }


def feishu_field_payload(field: FieldContract) -> dict[str, Any]:
    """Render one field using names for select options and no durable ids."""

    if field.type_name not in FIELD_TYPE_MAP:
        raise ValueError(f"unknown Feishu field type: {field.type_name}")
    payload: dict[str, Any] = {
        "field_name": field.name,
        "type": FIELD_TYPE_MAP[field.type_name],
    }
    if field.type_name == "user":
        payload["property"] = {"multiple": False}
    elif field.type_name == "single_select":
        if not field.options:
            raise ValueError(f"select field has no canonical options: {field.name}")
        payload["property"] = {"options": [{"name": option} for option in field.options]}
    return payload


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _single_user_key(value: Any, field_name: str) -> str:
    if not isinstance(value, (list, tuple)) or len(value) != 1:
        raise ValueError(f"{field_name} must contain exactly one Feishu user")
    item = value[0]
    if not isinstance(item, Mapping):
        raise ValueError(f"{field_name} must contain a Feishu user mapping")
    identity = item.get("id")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError(f"{field_name} must contain a non-empty user id")
    return identity.strip()


def _datetime_value(value: Any, field_name: str) -> datetime | None:
    if _is_blank(value):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, bool):
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    elif isinstance(value, (int, float)) and math.isfinite(float(value)):
        parsed = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 datetime") from exc
    else:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _capacity_value(value: Any) -> float | int | None:
    if _is_blank(value):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("未来7天可分配工时 must be a number")
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError("未来7天可分配工时 must be finite and nonnegative")
    return value


def _text_value(value: Any, field_name: str) -> None:
    if not _is_blank(value) and not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")


def _record_shape(record: Mapping[str, Any]) -> tuple[str, str, datetime | None, datetime | None]:
    if not isinstance(record, Mapping):
        raise ValueError("capability record must be a mapping")
    unknown = set(record) - set(FIELD_NAMES)
    if unknown:
        raise ValueError(f"capability record contains non-canonical fields: {sorted(unknown)}")
    if "成员" not in record:
        raise ValueError("capability record is missing 成员")
    member_key = _single_user_key(record["成员"], "成员")
    status = record.get("记录状态")
    if not isinstance(status, str) or status not in STATUS_OPTIONS:
        raise ValueError("记录状态 must be one of the canonical human-facing status names")
    for field_name in ELIGIBILITY_TEXT_FIELDS + ("不可用区间",):
        if field_name in record:
            _text_value(record[field_name], field_name)
    if "未来7天可分配工时" in record:
        _capacity_value(record["未来7天可分配工时"])
    confirmation = _datetime_value(record.get("负荷确认时间"), "负荷确认时间")
    expiry = _datetime_value(record.get("负荷有效至"), "负荷有效至")
    if confirmation is not None and expiry is not None and expiry <= confirmation:
        raise ValueError("负荷有效至 must be after 负荷确认时间")
    if "维护人" in record and not _is_blank(record["维护人"]):
        _single_user_key(record["维护人"], "维护人")
    return member_key, status, confirmation, expiry


def _eligibility_errors(
    record: Mapping[str, Any],
    confirmation: datetime | None,
    expiry: datetime | None,
    now: datetime,
) -> tuple[str, ...]:
    errors: list[str] = []
    if record.get("记录状态") != "有效":
        errors.append("记录状态 must be 有效")
    if confirmation is None:
        errors.append("负荷确认时间 is required")
    if expiry is None:
        errors.append("负荷有效至 is required")
    elif expiry <= now:
        errors.append("负荷有效至 must be in the future")
    if "维护人" not in record or _is_blank(record.get("维护人")):
        errors.append("维护人 is required")
    for field_name in ELIGIBILITY_TEXT_FIELDS:
        value = record.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field_name} is required")
    capacity = record.get("未来7天可分配工时")
    if capacity is None or capacity == "":
        errors.append("未来7天可分配工时 is required")
    return tuple(errors)


def _coerce_now(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = _datetime_value(value, "now")
    if parsed is None:
        raise ValueError("now must be a timezone-aware datetime")
    return parsed


def record_eligibility_errors(record: Mapping[str, Any], *, now: datetime | str | None = None) -> tuple[str, ...]:
    """Return why a structurally valid record cannot enter a recommendation."""

    _, _, confirmation, expiry = _record_shape(record)
    return _eligibility_errors(record, confirmation, expiry, _coerce_now(now))


def validate_record(record: Mapping[str, Any], *, now: datetime | str | None = None) -> None:
    """Validate one record, including eligibility when its status is 有效."""

    _, status, _, _ = _record_shape(record)
    if status == "有效":
        errors = record_eligibility_errors(record, now=now)
        if errors:
            raise ValueError("ineligible 有效 capability record: " + "; ".join(errors))


def validate_records(records: Iterable[Mapping[str, Any]], *, now: datetime | str | None = None) -> None:
    """Validate record shape, status, effective-record eligibility, and member uniqueness."""

    if isinstance(records, Mapping):
        raise ValueError("records must be an iterable of record mappings")
    seen_members: set[str] = set()
    for index, record in enumerate(records):
        validate_record(record, now=now)
        member_key, _, _, _ = _record_shape(record)
        if member_key in seen_members:
            raise ValueError(f"duplicate 成员 identity at record index {index}")
        seen_members.add(member_key)


def eligible_records(
    records: Iterable[Mapping[str, Any]], *, now: datetime | str | None = None
) -> list[Mapping[str, Any]]:
    """Return only records that are safe evidence for DRI/Reviewer recommendation."""

    materialized = list(records)
    validate_records(materialized, now=now)
    return [record for record in materialized if record.get("记录状态") == "有效"]


def feishu_record_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """Render a validated record without copying user display names or select ids."""

    validate_record(record)
    fields: dict[str, Any] = {}
    for field in TEAM_CAPABILITY_FIELDS:
        if field.name not in record or _is_blank(record[field.name]):
            continue
        value = record[field.name]
        if field.type_name == "user":
            fields[field.name] = [{"id": _single_user_key(value, field.name)}]
        else:
            fields[field.name] = value
    return {"fields": fields}


validate_schema()
