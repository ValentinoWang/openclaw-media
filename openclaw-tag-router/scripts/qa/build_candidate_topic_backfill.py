#!/usr/bin/env python3
"""Build a deterministic, local-only D01/R02 backfill packet from A1 evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{7,159}$")
RUN_ID_KEYS = ("creation_run_id", "creationRunId", "创作运行ID")
TENANT_ID_KEYS = ("tenant_id", "tenantId", "租户ID")
TRACE_ID_KEYS = ("decision_trace_id", "decisionTraceId", "决策轨迹ID")
RECORD_ID_KEYS = ("record_id", "recordId", "public_id", "publicId")
TITLE_KEYS = ("candidate_title", "candidateTitle", "候选标题", "标题")
TYPE_KEYS = ("candidate_type", "candidateType", "候选类型")
C01_ID_KEYS = (
    "c01_record_ids",
    "c01RecordIds",
    "creation_run_record_ids",
    "creationRunRecordIds",
)


class BackfillBlocked(ValueError):
    """The historical input cannot be migrated without guessing identity."""


def _blocked(code: str, detail: str = "") -> BackfillBlocked:
    return BackfillBlocked(f"{code}{':' + detail if detail else ''}")


def _records(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, Mapping):
        values = payload.get("r02_records")
        if values is None:
            values = payload.get("records")
        if values is None:
            raise _blocked("B6_BLOCKED_R02_RECORD_LIST_MISSING")
    else:
        raise _blocked("B6_BLOCKED_INPUT_SHAPE")
    if not isinstance(values, list) or not all(isinstance(value, Mapping) for value in values):
        raise _blocked("B6_BLOCKED_NON_OBJECT_R02_RECORD")
    if not values:
        raise _blocked("B6_BLOCKED_R02_RECORD_LIST_EMPTY")
    return list(values)


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _source_values(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the physical source fields while retaining every supplied value."""
    for key in ("source_field_values", "fields", "canonical_data", "canonicalData"):
        value = record.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return dict(record)


def _containers(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    containers: list[Mapping[str, Any]] = [record]
    for key in ("source_field_values", "fields", "canonical_data", "canonicalData"):
        value = _mapping(record.get(key))
        if value is not None:
            containers.append(value)
    return containers


def _scalar(value: Any, code: str, label: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise _blocked(code, f"{label} has multiple values")
        value = value[0]
    if not isinstance(value, str):
        raise _blocked(code, f"{label} is not text")
    return value.strip()


def _values_from_containers(
    containers: Iterable[Mapping[str, Any]],
    keys: Iterable[str],
    *,
    conflict_code: str,
    label: str,
) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for container in containers:
        for key in keys:
            if key not in container:
                continue
            normalized = _scalar(container.get(key), conflict_code, label)
            if normalized:
                values.append((key, normalized))
    unique = {value for _, value in values}
    if len(unique) > 1:
        raise _blocked(conflict_code, f"{label} values conflict")
    return values


def _required_identity(
    record: Mapping[str, Any],
    keys: Iterable[str],
    *,
    missing_code: str,
    conflict_code: str,
    label: str,
) -> str:
    values = _values_from_containers(
        _containers(record),
        keys,
        conflict_code=conflict_code,
        label=label,
    )
    if not values:
        raise _blocked(missing_code, label)
    return values[0][1]


def _optional_identity(
    record: Mapping[str, Any],
    keys: Iterable[str],
    *,
    conflict_code: str,
    label: str,
) -> str:
    values = _values_from_containers(
        _containers(record),
        keys,
        conflict_code=conflict_code,
        label=label,
    )
    return values[0][1] if values else ""


def _trace_id(record: Mapping[str, Any]) -> str:
    explicit = _optional_identity(
        record,
        TRACE_ID_KEYS,
        conflict_code="B6_BLOCKED_TRACE_ID_CONFLICT",
        label="decision trace ID",
    )
    if explicit:
        return explicit
    fallback = _optional_identity(
        record,
        RECORD_ID_KEYS,
        conflict_code="B6_BLOCKED_TRACE_ID_CONFLICT",
        label="decision trace record ID",
    )
    if not fallback:
        raise _blocked("B6_BLOCKED_INVALID_DECISION_TRACE_ID")
    return fallback


def _check_id(value: str, code: str, label: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise _blocked(code, f"invalid {label}")
    return value


def _first_value(data: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return copy.deepcopy(value)
    return ""


def _id_list(value: Any, *, code: str, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        raise _blocked(code, f"{label} is not a list")
    result: list[str] = []
    for item in value:
        normalized = _scalar(item, code, label)
        if normalized:
            result.append(normalized)
    return result


def _group_run_id(group: Mapping[str, Any]) -> str:
    values: list[tuple[str, str]] = []
    for key in (
        "historical_creation_run_id",
        "historicalCreationRunId",
        "creation_run_id",
        "creationRunId",
    ):
        if key in group:
            value = _scalar(
                group.get(key),
                "B6_BLOCKED_RUN_ID_CONFLICT",
                "D01 group creation run ID",
            )
            if value:
                values.append((key, value))
    field_values = _mapping(group.get("c01_field_values"))
    if field_values is not None:
        for key in RUN_ID_KEYS:
            if key in field_values:
                value = _scalar(
                    field_values.get(key),
                    "B6_BLOCKED_RUN_ID_CONFLICT",
                    "C01 creation run ID",
                )
                if value:
                    values.append((key, value))
    unique = {value for _, value in values}
    if not unique:
        raise _blocked("B6_BLOCKED_MISSING_CREATION_RUN_ID", "D01 group")
    if len(unique) > 1:
        raise _blocked("B6_BLOCKED_RUN_ID_CONFLICT", "D01 group")
    return next(iter(unique))


def _group_tenant_id(group: Mapping[str, Any]) -> str:
    values: list[tuple[str, str]] = []
    for key in TENANT_ID_KEYS:
        if key in group:
            value = _scalar(
                group.get(key),
                "B6_BLOCKED_TENANT_CONFLICT",
                "D01 group tenant ID",
            )
            if value:
                values.append((key, value))
    field_values = _mapping(group.get("c01_field_values"))
    if field_values is not None:
        for key in TENANT_ID_KEYS:
            if key in field_values:
                value = _scalar(
                    field_values.get(key),
                    "B6_BLOCKED_TENANT_CONFLICT",
                    "C01 tenant ID",
                )
                if value:
                    values.append((key, value))
    unique = {value for _, value in values}
    if not unique:
        raise _blocked("B6_BLOCKED_MISSING_TENANT_ID", "D01 group")
    if len(unique) > 1:
        raise _blocked("B6_BLOCKED_TENANT_CONFLICT", "D01 group")
    return next(iter(unique))


def _c01_map(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    values = payload.get("c01_records")
    if values is None:
        values = payload.get("creation_runs")
    if values is None:
        return {}
    if isinstance(values, Mapping):
        items = list(values.items())
        result: dict[str, Mapping[str, Any]] = {}
        for key, value in items:
            if not isinstance(value, Mapping):
                raise _blocked("B6_BLOCKED_NON_OBJECT_C01_RECORD")
            result[str(key)] = value
        return result
    if not isinstance(values, list) or not all(isinstance(value, Mapping) for value in values):
        raise _blocked("B6_BLOCKED_NON_OBJECT_C01_RECORD")
    result = {}
    for value in values:
        record_id = _optional_identity(
            value,
            RECORD_ID_KEYS,
            conflict_code="B6_BLOCKED_C01_RECORD_ID_CONFLICT",
            label="C01 record ID",
        )
        if not record_id:
            raise _blocked("B6_BLOCKED_MISSING_C01_RECORD_ID")
        if record_id in result:
            raise _blocked("B6_BLOCKED_DUPLICATE_C01_RECORD_ID", record_id)
        result[record_id] = value
    return result


def _c01_evidence(
    group: Mapping[str, Any],
    c01_records: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    raw_ids = _first_value(group, C01_ID_KEYS)
    record_ids = _id_list(
        raw_ids,
        code="B6_BLOCKED_AMBIGUOUS_C01_LINK",
        label="D01 C01 record IDs",
    )
    declared_count = group.get("c01_link_count")
    if declared_count is not None and declared_count != 1:
        raise _blocked("B6_BLOCKED_AMBIGUOUS_C01_LINK", "D01 group link count is not one")
    if len(record_ids) != 1:
        raise _blocked("B6_BLOCKED_AMBIGUOUS_C01_LINK", "D01 group must have one C01 record")
    c01_record = c01_records.get(record_ids[0])
    if c01_record is None:
        values = _mapping(group.get("c01_field_values"))
        if values is None:
            raise _blocked("B6_BLOCKED_C01_RECORD_MISSING", record_ids[0])
        c01_record = {"record_id": record_ids[0], "fields": dict(values)}
    c01_run_id = _required_identity(
        c01_record,
        RUN_ID_KEYS,
        missing_code="B6_BLOCKED_MISSING_CREATION_RUN_ID",
        conflict_code="B6_BLOCKED_RUN_ID_CONFLICT",
        label="C01 creation run ID",
    )
    c01_tenant_id = _required_identity(
        c01_record,
        TENANT_ID_KEYS,
        missing_code="B6_BLOCKED_MISSING_TENANT_ID",
        conflict_code="B6_BLOCKED_TENANT_CONFLICT",
        label="C01 tenant ID",
    )
    return (
        record_ids[0],
        c01_run_id,
        {
            "tenant_id": c01_tenant_id,
            "record_ids": record_ids,
            "link_count": 1,
            "exact_match_field": str(group.get("c01_exact_match_field") or "创作运行ID"),
            "source_row_index": group.get("c01_source_row_index"),
            "field_values": copy.deepcopy(_source_values(c01_record)),
        },
        dict(c01_record),
    )


def _groups(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    values = payload.get("d01_groups")
    if not isinstance(values, list) or not all(isinstance(value, Mapping) for value in values):
        raise _blocked("B6_BLOCKED_D01_GROUP_LIST_MISSING")
    if not values:
        raise _blocked("B6_BLOCKED_D01_GROUP_LIST_EMPTY")
    return list(values)


def build_backfill(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _blocked("B6_BLOCKED_INPUT_SHAPE")
    raw_records = _records(payload)
    d01_groups = _groups(payload)
    c01_records = _c01_map(payload)

    traces_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    trace_ids: set[tuple[str, str]] = set()

    for raw in raw_records:
        source_values = _source_values(raw)
        run_id = _check_id(
            _required_identity(
                raw,
                RUN_ID_KEYS,
                missing_code="B6_BLOCKED_MISSING_CREATION_RUN_ID",
                conflict_code="B6_BLOCKED_RUN_ID_CONFLICT",
                label="R02 creation run ID",
            ),
            "B6_BLOCKED_INVALID_CREATION_RUN_ID",
            "creation run ID",
        )
        tenant_id = _required_identity(
            raw,
            TENANT_ID_KEYS,
            missing_code="B6_BLOCKED_MISSING_TENANT_ID",
            conflict_code="B6_BLOCKED_TENANT_CONFLICT",
            label="R02 tenant ID",
        )
        trace_id = _check_id(
            _trace_id(raw),
            "B6_BLOCKED_INVALID_DECISION_TRACE_ID",
            "decision trace ID",
        )
        trace_identity = (tenant_id, trace_id)
        if trace_identity in trace_ids:
            raise _blocked("B6_BLOCKED_DUPLICATE_DECISION_TRACE_ID", trace_id)
        trace_ids.add(trace_identity)

        retained = raw.get("retained_in_r02")
        if retained is False:
            raise _blocked("B6_BLOCKED_R02_EVENT_NOT_RETAINED", trace_id)
        key = (tenant_id, run_id)
        traces_by_key.setdefault(key, []).append(
            {
                "raw": raw,
                "fields": source_values,
                "record_id": _optional_identity(
                    raw,
                    RECORD_ID_KEYS,
                    conflict_code="B6_BLOCKED_TRACE_RECORD_ID_CONFLICT",
                    label="R02 record ID",
                )
                or trace_id,
                "decision_trace_id": trace_id,
                "creation_run_id": run_id,
                "tenant_id": tenant_id,
            }
        )

    group_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    used_c01_ids: set[tuple[str, str]] = set()
    for group in d01_groups:
        run_id = _check_id(
            _group_run_id(group),
            "B6_BLOCKED_INVALID_CREATION_RUN_ID",
            "D01 creation run ID",
        )
        tenant_id = _group_tenant_id(group)
        key = (tenant_id, run_id)
        if key in group_by_key:
            raise _blocked("B6_BLOCKED_AMBIGUOUS_D01_GROUP", run_id)
        if key not in traces_by_key:
            raise _blocked("B6_BLOCKED_D01_GROUP_WITHOUT_R02", run_id)

        c01_id, c01_run_id, c01_link, c01_record = _c01_evidence(group, c01_records)
        c01_identity = (tenant_id, c01_id)
        if c01_identity in used_c01_ids:
            raise _blocked("B6_BLOCKED_AMBIGUOUS_C01_LINK", c01_id)
        used_c01_ids.add(c01_identity)
        if c01_run_id != run_id:
            raise _blocked("B6_BLOCKED_C01_RUN_MISMATCH", run_id)
        if c01_link["tenant_id"] != tenant_id:
            raise _blocked("B6_BLOCKED_C01_TENANT_MISMATCH", run_id)

        events = traces_by_key[key]
        declared_ids = _id_list(
            group.get("r02_record_ids"),
            code="B6_BLOCKED_R02_GROUP_MISMATCH",
            label="D01 R02 record IDs",
        )
        if declared_ids and set(declared_ids) != {event["record_id"] for event in events}:
            raise _blocked("B6_BLOCKED_R02_GROUP_MISMATCH", run_id)
        declared_count = group.get("r02_event_count")
        if declared_count is not None and declared_count != len(events):
            raise _blocked("B6_BLOCKED_R02_GROUP_MISMATCH", run_id)

        topic_id = f"legacy:{run_id}"
        group_by_key[key] = {
            "group": group,
            "tenant_id": tenant_id,
            "creation_run_id": run_id,
            "candidate_id": topic_id,
            "c01_record_ids": [c01_id],
            "c01_link_count": 1,
            "c01_exact_match_field": c01_link["exact_match_field"],
            "c01_source_row_index": c01_link["source_row_index"],
            "c01_field_values": c01_link["field_values"],
            "c01_record": c01_record,
            "candidate_title": str(
                group.get("candidate_topic_title")
                or group.get("candidate_title")
                or ""
            ).strip(),
        }

    if set(group_by_key) != set(traces_by_key):
        missing_groups = sorted(set(traces_by_key) - set(group_by_key))
        extra_groups = sorted(set(group_by_key) - set(traces_by_key))
        raise _blocked(
            "B6_BLOCKED_D01_R02_COVERAGE_MISMATCH",
            f"missing={missing_groups};extra={extra_groups}",
        )

    topics: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for key in sorted(group_by_key):
        topic = group_by_key[key]
        events = sorted(
            traces_by_key[key],
            key=lambda event: (event["decision_trace_id"], event["record_id"]),
        )
        decision_trace_ids: list[str] = []
        for sequence, event in enumerate(events, start=1):
            raw = event["raw"]
            source_values = copy.deepcopy(event["fields"])
            supplied_c01_ids = _id_list(
                raw.get("c01_record_ids"),
                code="B6_BLOCKED_AMBIGUOUS_C01_LINK",
                label="R02 C01 record IDs",
            )
            supplied_c01_count = raw.get("c01_link_count")
            if supplied_c01_count is not None and supplied_c01_count != 1:
                raise _blocked("B6_BLOCKED_AMBIGUOUS_C01_LINK", event["decision_trace_id"])
            if supplied_c01_ids and supplied_c01_ids != topic["c01_record_ids"]:
                raise _blocked("B6_BLOCKED_AMBIGUOUS_C01_LINK", event["decision_trace_id"])
            decision_trace_ids.append(event["decision_trace_id"])
            traces.append(
                {
                    "record_id": event["record_id"],
                    "decision_trace_id": event["decision_trace_id"],
                    "candidate_topic_public_id": topic["candidate_id"],
                    "candidate_id": topic["candidate_id"],
                    "tenant_id": topic["tenant_id"],
                    "creation_run_id": topic["creation_run_id"],
                    "decision_sequence": sequence,
                    "c01_record_ids": list(topic["c01_record_ids"]),
                    "c01_link_count": 1,
                    "retained_in_r02": True,
                    "fields": source_values,
                    "source_field_values": copy.deepcopy(source_values),
                }
            )

        candidate_type = ""
        for event in events:
            value = _first_value(event["fields"], TYPE_KEYS)
            if value not in (None, "", []):
                candidate_type = copy.deepcopy(value)
                break
        if not topic["candidate_title"]:
            for event in events:
                value = _first_value(event["fields"], TITLE_KEYS)
                if isinstance(value, str) and value.strip():
                    topic["candidate_title"] = value.strip()
                    break
        candidate_topic = {
            "tenant_id": topic["tenant_id"],
            "candidate_id": topic["candidate_id"],
            "candidate_topic_public_id": topic["candidate_id"],
            "creation_run_id": topic["creation_run_id"],
            "candidate_title": topic["candidate_title"],
            "candidate_type": candidate_type,
            "decision_trace_ids": decision_trace_ids,
            "decision_trace_count": len(decision_trace_ids),
            "creation_run_ids": [topic["creation_run_id"]],
            "c01_record_ids": list(topic["c01_record_ids"]),
            "c01_link_count": 1,
            "c01_exact_match_field": topic["c01_exact_match_field"],
            "c01_source_row_index": topic["c01_source_row_index"],
            "c01_field_values": copy.deepcopy(topic["c01_field_values"]),
            "d01_group": copy.deepcopy(topic["group"]),
        }
        topics.append(candidate_topic)

    traces.sort(key=lambda item: (item["tenant_id"], item["candidate_id"], item["decision_sequence"], item["decision_trace_id"]))
    if sum(item["decision_trace_count"] for item in topics) != len(traces):
        raise _blocked("B6_BLOCKED_CARDINALITY_MISMATCH")
    if len({(item["tenant_id"], item["decision_trace_id"]) for item in traces}) != len(traces):
        raise _blocked("B6_BLOCKED_DUPLICATE_DECISION_TRACE_ID")

    canonical = {
        "schema_version": "media.candidate-topic-backfill.v2",
        "candidate_topics": topics,
        "decision_traces": traces,
        "counts": {
            "candidate_topics": len(topics),
            "decision_traces": len(traces),
        },
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    canonical["sha256"] = hashlib.sha256(encoded).hexdigest()
    return canonical


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = build_backfill(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "pass", **result["counts"], "sha256": result["sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
