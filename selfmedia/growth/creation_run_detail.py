from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common.social_runtime import feishu_list_records, feishu_plain_text, feishu_tenant_access_token
from common.resource_ownership import canonical_tenant_owned_resources, require_tenant_id
from media_model.contract import MediaModelContract, resolve_creation_run_detail_contract_path
from media_vault.vault import MediaVault, MediaVaultError


ROOT = Path(__file__).resolve().parents[2]
DETAIL_CONTRACT_PATH = resolve_creation_run_detail_contract_path()
REGISTRY_PATH = ROOT / "openclaw-feishu-reminder/media-bitable-registry.json"
KNOWN_ARTIFACT_FILES = (
    "request.json",
    "retrieval_candidates.json",
    "decision_trace.json",
    "material_usage.json",
    "draft_output.json",
    "validation_report.json",
    "writeback_report.json",
)
INTERNAL_ID_RE = re.compile(r"\b(?:rec|tbl|run_rec)[A-Za-z0-9_-]{6,}\b")
ABSOLUTE_PATH_RE = re.compile(r"/(?:home|tmp)/[^\s]+")
PRIVATE_ENTITY_OWNERS: dict[str, tuple[str, str]] = {
    "SourceAsset": ("media.source_asset", "asset_id"),
    "MaterialDeconstruction": ("media.material_deconstruction", "deconstruction_id"),
    "CreativePattern": ("media.creative_pattern", "pattern_id"),
    "CreationRun": ("media.creation_run", "run_id"),
    "BusinessOpportunity": ("media.business_opportunity", "opportunity_id"),
    "CreatorProfile": ("media.creator_profile", "creator_profile_id"),
    "MaterialUsage": ("media.material_usage", "usage_id"),
    "DecisionTrace": ("media.decision_trace", "trace_id"),
}


class CreationRunDetailError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CreationRunDetailError(f"expected JSON object: {path.name}")
    return payload


def _public_id(kind: str, value: Any) -> str:
    digest = hashlib.sha256(f"{kind}:{_text(value)}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}_{digest}"


def _text(value: Any) -> str:
    return feishu_plain_text(value).strip()


def _safe_text(value: Any, *, limit: int = 4000) -> str:
    text = _text(value)
    text = ABSOLUTE_PATH_RE.sub("[受控路径]", text)
    text = text.replace("media://", "受控产物:")
    text = INTERNAL_ID_RE.sub("[内部标识已隐藏]", text)
    text = re.sub(r"(?i)\b(?:raw_prompt|raw_response|traceback|stack trace)\b", "[敏感内容已隐藏]", text)
    return text[:limit]


def _safe_url(value: Any) -> str:
    text = _text(value)
    if not text.startswith(("https://", "http://")):
        return ""
    parsed = urlparse(text)
    if not parsed.hostname or parsed.hostname in {"localhost", "127.0.0.1"}:
        return ""
    return text


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[结构已收起]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_safe_value(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lower = key_text.lower()
            if lower.endswith("_id") or lower.endswith("_ids") or lower in {
                "record_id",
                "record_ids",
                "raw_prompt",
                "raw_response",
                "traceback",
                "debug",
                "token",
            }:
                continue
            result[key_text] = _safe_value(item, depth=depth + 1)
        return result
    return _safe_text(value)


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


class CreationRunDetailBuilder:
    def __init__(
        self,
        *,
        model_contract: MediaModelContract | None = None,
        detail_contract_path: str | Path = DETAIL_CONTRACT_PATH,
    ) -> None:
        self.model_contract = model_contract or MediaModelContract()
        self.detail_contract = _load_json(Path(detail_contract_path))

    def build(
        self,
        *,
        run: dict[str, Any],
        source_payloads: dict[str, dict[str, Any]],
        artifacts: dict[str, Any],
        artifact_state: str,
    ) -> dict[str, Any]:
        raw_run_id = _text(run.get("run_id"))
        if not raw_run_id:
            raise CreationRunDetailError("CreationRun detail requires run_id")
        groups: list[dict[str, Any]] = []
        field_lineage: list[dict[str, Any]] = []
        for spec in self.detail_contract["source_groups"]:
            key = spec["key"]
            payload = source_payloads.get(key) or {
                "read_state": "not_queried",
                "records": [],
                "reason": "source was not queried",
            }
            group = self._source_group(spec, payload)
            groups.append(group)
            for record in group["records"]:
                field_lineage.extend(record["fields"])
        draft = artifacts.get("draft_output.json") if isinstance(artifacts.get("draft_output.json"), dict) else {}
        decision_group = next(item for item in groups if item["key"] == "decision_traces")
        usage_group = next(item for item in groups if item["key"] == "material_usage")
        safe_artifact = self._safe_artifact(draft, decision_group, usage_group)
        outputs = self._outputs(run, artifacts.get("writeback_report.json"), groups, source_payloads)
        projection = {
            "schemaVersion": self.detail_contract["schema_version"],
            "publicRunId": _public_id("run", raw_run_id),
            "run": {
                "entrypoint": _safe_text(run.get("entrypoint")),
                "inputSummary": _safe_text(run.get("input_summary")),
                "status": _safe_text(run.get("status")),
                "generationSource": _safe_text(run.get("generation_source")),
                "artifactState": artifact_state,
            },
            "timeline": self._timeline(run, artifacts, artifact_state),
            "sources": groups,
            "decisions": {
                "traces": self._decision_rows(decision_group),
                "materialUsage": self._usage_rows(usage_group),
            },
            "artifact": safe_artifact,
            "outputs": outputs,
            "fieldLineage": field_lineage,
            "safeTree": {
                "run": {
                    "entrypoint": _safe_text(run.get("entrypoint")),
                    "input_summary": _safe_text(run.get("input_summary")),
                    "status": _safe_text(run.get("status")),
                    "generation_source": _safe_text(run.get("generation_source")),
                },
                "sources": {item["key"]: item["records"] for item in groups if item["key"] not in {"run", "decision_traces", "material_usage"}},
                "decisions": {
                    "traces": self._decision_rows(decision_group),
                    "material_usage": self._usage_rows(usage_group),
                },
                "artifact": safe_artifact,
                "outputs": outputs,
            },
        }
        self.assert_complete_and_safe(projection)
        return projection

    def _source_group(self, spec: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        entity = spec["entity"]
        records = payload.get("records") if isinstance(payload.get("records"), list) else []
        read_state = str(payload.get("read_state") or "not_queried")
        if read_state not in self.detail_contract["read_states"]:
            raise CreationRunDetailError(f"invalid read state for {spec['key']}: {read_state}")
        projected_records = [self._source_record(spec, row, index) for index, row in enumerate(records)]
        return {
            "key": spec["key"],
            "entity": entity,
            "sourceTable": spec["source_table"],
            "displayName": spec["source_table"],
            "readState": read_state,
            "recordCount": len(projected_records),
            "reason": _safe_text(payload.get("reason")),
            "records": projected_records,
        }

    def _source_record(self, spec: dict[str, Any], row: dict[str, Any], index: int) -> dict[str, Any]:
        entity = spec["entity"]
        primary_key = str(self.model_contract.entity(entity).get("primary_key") or "")
        raw_primary = row.get(primary_key) or f"{spec['key']}:{index}"
        human_fields = self.model_contract.projection(entity).get("human_view_fields") or []
        field_map = self.model_contract.field_name_map(entity)
        fields: list[dict[str, Any]] = []
        for canonical_name in human_fields:
            # Document links grant access to a private workspace and do not belong
            # in the public-safe run projection, even when a table exposes them.
            if canonical_name.endswith("_doc_link"):
                continue
            value = row.get(canonical_name)
            if value in (None, "", []):
                continue
            is_internal_ref = canonical_name == primary_key or canonical_name.endswith("_id") or canonical_name.endswith("_uri")
            preview = "已登记" if canonical_name == primary_key else ("已关联" if canonical_name.endswith("_id") else ("受控产物" if canonical_name.endswith("_uri") else _safe_value(value)))
            if isinstance(preview, (dict, list)):
                preview = json.dumps(preview, ensure_ascii=False, separators=(",", ":"))[:1200]
            fields.append(
                {
                    "sourceTable": spec["source_table"],
                    "sourceField": field_map.get(canonical_name, canonical_name),
                    "canonicalField": canonical_name,
                    "jsonPath": f"sources.{spec['key']}[{index}].fields.{canonical_name}",
                    "valuePreview": preview,
                    "valueType": "reference" if is_internal_ref else _value_type(value),
                    "consumedBy": self._consumers(spec["key"]),
                    "writebackTarget": self._writeback_target(spec["key"]),
                    "readbackState": "matched" if self._writeback_target(spec["key"]) != "只读来源，不回写" else "not_attempted",
                }
            )
        display_name = next(
            (
                _safe_text(row.get(name))
                for name in ("title", "track_name", "account_name", "pattern_name", "summary", "input_summary", "brand", "candidate_type", "usage_type")
                if _safe_text(row.get(name))
            ),
            spec["source_table"],
        )
        selected_state = "reference"
        if spec["key"] == "decision_traces":
            selected_state = "selected" if row.get("selected") is True else "rejected"
        elif spec["key"] == "material_usage":
            selected_state = "selected" if row.get("selected_for_final") is True else "candidate"
        elif row.get("_selected") is True:
            selected_state = "selected"
        return {
            "recordRef": _public_id("record", f"{entity}:{raw_primary}"),
            "displayName": display_name,
            "selectedState": selected_state,
            "fields": fields,
        }

    @staticmethod
    def _consumers(group_key: str) -> list[str]:
        if group_key == "run":
            return ["请求校验", "持久化", "渲染/readback"]
        if group_key in {"decision_traces", "material_usage"}:
            return ["候选排序", "LLM 选择/生成", "持久化"]
        return ["来源检索", "候选排序", "LLM 选择/生成"]

    @staticmethod
    def _writeback_target(group_key: str) -> str:
        return {
            "run": "03_CreationRuns_创作运行",
            "decision_traces": "R02_DecisionTrace_决策轨迹",
            "material_usage": "R01_MaterialUsage_素材使用记录",
        }.get(group_key, "只读来源，不回写")

    def _safe_artifact(self, draft: dict[str, Any], decision_group: dict[str, Any], usage_group: dict[str, Any]) -> dict[str, Any]:
        core_keys = self.detail_contract["safe_json_groups"]["artifact.content_core"]
        core = {key: _safe_value(draft.get(key)) for key in core_keys if draft.get(key) not in (None, "", [])}
        option_keys = self.detail_contract["safe_json_groups"]["artifact.options"]
        options: list[dict[str, Any]] = []
        recommended_raw = _text(draft.get("recommended_option_id"))
        for index, option in enumerate(draft.get("script_options") or []):
            if not isinstance(option, dict):
                continue
            raw_option_id = _text(option.get("option_id")) or str(index)
            safe_option = {key: _safe_value(option.get(key)) for key in option_keys if option.get(key) not in (None, "", [])}
            safe_option["optionRef"] = _public_id("option", raw_option_id)
            safe_option["recommended"] = bool(recommended_raw and raw_option_id == recommended_raw)
            options.append(safe_option)
        storyboard_keys = self.detail_contract["safe_json_groups"]["artifact.storyboard"]
        storyboard = [
            {key: _safe_value(item.get(key)) for key in storyboard_keys if item.get(key) not in (None, "", [])}
            for item in (draft.get("storyboard") or [])
            if isinstance(item, dict)
        ]
        creator_report = draft.get("creator_report") if isinstance(draft.get("creator_report"), dict) else {}
        creator_keys = self.detail_contract["safe_json_groups"]["artifact.creator_report"]
        safe_creator_report = {key: _safe_value(creator_report.get(key)) for key in creator_keys if creator_report.get(key) not in (None, "", [])}
        return {
            "content_core": core,
            "usable_material_brief": {
                "selected_source_count": sum(1 for item in decision_group["records"] if item["selectedState"] == "selected"),
                "selected_usage_count": sum(1 for item in usage_group["records"] if item["selectedState"] == "selected"),
                "material_checklist": _safe_value(creator_report.get("material_checklist") or {}),
                "risks_or_missing_info": _safe_value(draft.get("risks_or_missing_info") or []),
            },
            "options": options,
            "storyboard": storyboard,
            "creator_report": safe_creator_report,
        }

    @staticmethod
    def _decision_rows(group: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in group["records"]:
            values = {field["canonicalField"]: field["valuePreview"] for field in record["fields"]}
            rows.append(
                {
                    "recordRef": record["recordRef"],
                    "candidateType": values.get("candidate_type", ""),
                    "rank": values.get("rank"),
                    "score": values.get("score"),
                    "selected": record["selectedState"] == "selected",
                    "reason": values.get("reason_summary", ""),
                    "rejectionReason": values.get("rejection_reason", ""),
                    "decisionVersion": values.get("decision_version", ""),
                }
            )
        return rows

    @staticmethod
    def _usage_rows(group: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in group["records"]:
            values = {field["canonicalField"]: field["valuePreview"] for field in record["fields"]}
            rows.append(
                {
                    "recordRef": record["recordRef"],
                    "usageType": values.get("usage_type", ""),
                    "score": values.get("score"),
                    "selectedForFinal": record["selectedState"] == "selected",
                    "performanceFeedback": values.get("performance_feedback_summary", ""),
                }
            )
        return rows

    def _timeline(self, run: dict[str, Any], artifacts: dict[str, Any], artifact_state: str) -> list[dict[str, Any]]:
        validation = artifacts.get("validation_report.json") if isinstance(artifacts.get("validation_report.json"), dict) else {}
        failed = _text(run.get("status")).lower() in {"failed", "error"}
        states = [
            "succeeded",
            "succeeded" if "retrieval_candidates.json" in artifacts else "pending_manual",
            "succeeded" if "decision_trace.json" in artifacts else "pending_manual",
            "failed" if failed else ("succeeded" if "draft_output.json" in artifacts else "pending_manual"),
            "succeeded" if validation.get("ok") is True else ("failed" if failed else "pending_manual"),
            "succeeded" if "writeback_report.json" in artifacts else "pending_manual",
            "succeeded" if _safe_url(run.get("feishu_doc_link")) else ("failed" if failed else "pending_manual"),
        ]
        if artifact_state != "available":
            states[1:6] = ["pending_manual"] * 5
        return [
            {"step": step, "status": states[index], "order": index + 1}
            for index, step in enumerate(self.detail_contract["timeline_steps"])
        ]

    def _outputs(
        self,
        run: dict[str, Any],
        writeback: Any,
        groups: list[dict[str, Any]],
        source_payloads: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        report = writeback if isinstance(writeback, dict) else {}
        grouped: dict[str, dict[str, Any]] = {}
        for item in report.get("writes") or []:
            if not isinstance(item, dict):
                continue
            entity = _safe_text(item.get("entity"))
            if not entity:
                continue
            current = grouped.setdefault(entity, {"field_count": 0, "modes": set(), "keys": [], "record_ids": []})
            current["field_count"] += int(item.get("field_count") or 0)
            current["modes"].add(_safe_text(item.get("mode")) or "written")
            if _safe_text(item.get("key_field")) and _text(item.get("key_value")):
                current["keys"].append((_safe_text(item.get("key_field")), _text(item.get("key_value"))))
            if _text(item.get("record_id")):
                current["record_ids"].append(_text(item.get("record_id")))
        groups_by_key = {str(item.get("key") or ""): item for item in groups}
        outputs: list[dict[str, Any]] = []
        targets = {
            "CreationRun": ("03_CreationRuns_创作运行", "run"),
            "DecisionTrace": ("R02_DecisionTrace_决策轨迹", "decision_traces"),
            "MaterialUsage": ("R01_MaterialUsage_素材使用记录", "material_usage"),
        }
        for entity, (target, group_key) in targets.items():
            write = grouped.get(entity)
            live_group = groups_by_key.get(group_key) or {}
            live_state = str(live_group.get("readState") or "not_queried")
            live_rows = (source_payloads.get(group_key) or {}).get("records") or []
            keys = list((write or {}).get("keys") or [])
            record_ids = list((write or {}).get("record_ids") or [])
            matched_keys = sum(
                1
                for key_field, key_value in keys
                if any(_text(row.get(key_field)) == key_value for row in live_rows if isinstance(row, dict))
            )
            matched_records = sum(
                1
                for record_id in record_ids
                if any(_text(row.get("_record_id")) == record_id for row in live_rows if isinstance(row, dict))
            )
            expected_matches = len(keys) if keys else len(record_ids)
            actual_matches = matched_keys if keys else matched_records
            if not write:
                readback_state = "not_attempted"
            elif live_state in {"unavailable", "not_queried"}:
                readback_state = "unavailable"
            elif expected_matches and actual_matches == expected_matches:
                readback_state = "matched"
            elif not expected_matches:
                readback_state = "pending"
            else:
                readback_state = "mismatched"
            field_count = int((write or {}).get("field_count") or 0)
            outputs.append(
                {
                    "target": target,
                    "fieldOrBlock": ", ".join(key for key, _ in keys) or "record identity",
                    "writeState": "written" if write else "not_attempted",
                    "expectedValueSummary": f"写入 {field_count} 个字段并读回 {expected_matches} 条目标记录" if write else "本次未声明写入",
                    "actualValueSummary": f"live 读回匹配 {actual_matches}/{expected_matches} 条目标记录；source={live_state}",
                    "readbackState": readback_state,
                    "checkedAt": datetime.now(timezone.utc).isoformat(),
                    "fieldCount": field_count,
                }
            )
        return outputs

    def assert_complete_and_safe(self, projection: dict[str, Any]) -> None:
        expected_groups = [item["key"] for item in self.detail_contract["source_groups"]]
        actual_groups = [item.get("key") for item in projection.get("sources") or []]
        if actual_groups != expected_groups:
            raise CreationRunDetailError("detail projection source groups are incomplete or reordered")
        if len(projection.get("timeline") or []) != 7:
            raise CreationRunDetailError("detail projection must contain seven timeline steps")
        artifact = projection.get("artifact") or {}
        if set(artifact) != {"content_core", "usable_material_brief", "options", "storyboard", "creator_report"}:
            raise CreationRunDetailError("detail projection safe artifact groups are incomplete")
        raw = json.dumps(projection, ensure_ascii=False).lower()
        for token in self.detail_contract["forbidden_output_tokens"]:
            if str(token).lower() in raw:
                raise CreationRunDetailError(f"detail projection contains forbidden token: {token}")


class CreationRunDetailExporter:
    def __init__(
        self,
        *,
        tenant_id: str,
        registry_path: str | Path = REGISTRY_PATH,
        vault: MediaVault | None = None,
        record_loader=feishu_list_records,
        token_loader=feishu_tenant_access_token,
        builder: CreationRunDetailBuilder | None = None,
        tenant_owned_resources=None,
    ) -> None:
        self.tenant_id = require_tenant_id(tenant_id)
        self.registry = _load_json(Path(registry_path))
        self.vault = vault or MediaVault(tenant_id=self.tenant_id)
        if self.vault.tenant_id != self.tenant_id:
            raise CreationRunDetailError("vault tenant does not match requested tenant")
        self.record_loader = record_loader
        self.token_loader = token_loader
        self.builder = builder or CreationRunDetailBuilder()
        self.model_contract = self.builder.model_contract
        self.tenant_owned_resources = tenant_owned_resources or canonical_tenant_owned_resources()

    def export(self, public_run_id: str) -> dict[str, Any]:
        specs = {spec["key"]: spec for spec in self.builder.detail_contract["source_groups"]}
        all_rows: dict[str, dict[str, Any]] = {}
        source_payloads: dict[str, dict[str, Any]] = {}

        try:
            token = self.token_loader()
            run_spec = specs["run"]
            raw_run_id = self._tenant_resource_id_for_public(
                "media.creation_run",
                public_run_id,
                public_kind="run",
            )
            if not raw_run_id:
                # A hash-shaped public ID may only resolve through the tenant
                # ownership registry. A non-public value is checked once as an
                # opaque run key so an unknown request gets the same not-found
                # result without probing relation tables.
                if re.fullmatch(r"run_[a-f0-9]{16}", public_run_id):
                    raise CreationRunDetailError("CreationRun detail not found")
                raw_run_id = public_run_id
            run_rows = self._records(
                run_spec["entity"],
                run_spec["registry_key"],
                token=token,
                filter_formula=self._equals_filter("CreationRun", "run_id", raw_run_id),
            )
        except CreationRunDetailError:
            raise
        except Exception as exc:
            raise CreationRunDetailError("CreationRun source unavailable") from exc
        run = next((row for row in run_rows if _text(row.get("run_id")) == raw_run_id), None)
        if not run:
            raise CreationRunDetailError("CreationRun detail not found")
        source_payloads["run"] = {"read_state": "available", "records": [run], "reason": "CreationRun matched"}
        artifacts, artifact_state = self._artifacts(run)
        declared_write_entities = self._declared_write_entities(artifacts)

        relation_sources = {
            "decision_traces": ("DecisionTrace", "DecisionTrace"),
            "material_usage": ("MaterialUsage", "MaterialUsage"),
        }
        for key, (write_entity, model_entity) in relation_sources.items():
            if write_entity not in declared_write_entities:
                source_payloads[key] = {
                    "read_state": "not_queried",
                    "records": [],
                    "reason": "writeback report does not prove this source belongs to the run",
                }
                continue
            spec = specs[key]
            try:
                filter_formula = self._equals_filter(model_entity, "run_id", raw_run_id)
                rows = self._records(spec["entity"], spec["registry_key"], token=token, filter_formula=filter_formula)
                all_rows[key] = {"spec": spec, "rows": rows}
            except Exception as exc:
                source_payloads[key] = {"read_state": "unavailable", "records": [], "reason": str(exc)}

        traces = [row for row in ((all_rows.get("decision_traces") or {}).get("rows") or []) if _text(row.get("run_id")) == raw_run_id]
        usages = [row for row in ((all_rows.get("material_usage") or {}).get("rows") or []) if _text(row.get("run_id")) == raw_run_id]
        if "decision_traces" not in source_payloads:
            source_payloads["decision_traces"] = self._matched_payload(
                traces,
                (all_rows.get("decision_traces") or {}).get("rows") or [],
                filtered=True,
            )
        if "material_usage" not in source_payloads:
            source_payloads["material_usage"] = self._matched_payload(
                usages,
                (all_rows.get("material_usage") or {}).get("rows") or [],
                filtered=True,
            )

        wanted = self._wanted_ids(run, traces, usages)
        for key, spec in specs.items():
            if key in {"run", "decision_traces", "material_usage"}:
                continue
            wanted_ids = wanted.get(key, set())
            if not wanted_ids:
                source_payloads[key] = {
                    "read_state": "not_queried",
                    "records": [],
                    "reason": "run has no persisted references to this source",
                }
                continue
            try:
                primary_key = str(self.model_contract.entity(spec["entity"]).get("primary_key") or "")
                rows = []
                for wanted_id in sorted(wanted_ids):
                    rows.extend(
                        self._records(
                            spec["entity"],
                            spec["registry_key"],
                            token=token,
                            filter_formula=self._equals_filter(spec["entity"], primary_key, wanted_id),
                        )
                    )
            except Exception as exc:
                source_payloads[key] = {"read_state": "unavailable", "records": [], "reason": str(exc)}
                continue
            matches = []
            for row in rows:
                raw_id = _text(row.get(primary_key))
                if raw_id and raw_id in wanted_ids:
                    matches.append({**row, "_selected": raw_id in wanted.get(f"{key}:selected", set())})
            source_payloads[key] = self._matched_payload(matches, rows)

        return self.builder.build(run=run, source_payloads=source_payloads, artifacts=artifacts, artifact_state=artifact_state)

    def _table_url(self, registry_key: str) -> str:
        entry = (self.registry.get("tables") or {}).get(registry_key) or {}
        urls = [str(value).strip() for value in (entry.get("env") or {}).values() if str(value).strip()]
        if len(urls) != 1:
            raise CreationRunDetailError(f"source registry unavailable: {registry_key}")
        return urls[0]

    def _records(self, entity: str, registry_key: str, *, token: str, filter_formula: str = "") -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in self.record_loader(self._table_url(registry_key), token=token, filter_formula=filter_formula):
            fields = record.get("fields") if isinstance(record, dict) else None
            if isinstance(fields, dict):
                row = self.model_contract.normalize_record_fields(entity, fields)
                owner_contract = PRIVATE_ENTITY_OWNERS.get(entity)
                if owner_contract is not None:
                    resource_type, id_field = owner_contract
                    resource_id = _text(row.get(id_field))
                    if not resource_id:
                        raise CreationRunDetailError(f"{entity} projection is missing canonical id")
                    self.tenant_owned_resources.assert_projection_read(
                        resource_type,
                        resource_id,
                        session_tenant_id=self.tenant_id,
                        fields=fields,
                        projection_source=f"feishu:{registry_key}/{record.get('record_id') or 'missing'}",
                    )
                row["_record_id"] = _text(record.get("record_id"))
                rows.append(row)
        return rows

    def _tenant_resource_id_for_public(
        self,
        resource_type: str,
        public_id: str,
        *,
        public_kind: str,
    ) -> str:
        owners = self.tenant_owned_resources.registry.list_all_by_tenant(
            self.tenant_id,
            resource_type=resource_type,
        )
        matches = [
            owner.canonical_resource_id
            for owner in owners
            if _public_id(public_kind, owner.canonical_resource_id) == public_id
        ]
        if len(matches) > 1:
            raise CreationRunDetailError("CreationRun public reference is ambiguous")
        return matches[0] if matches else ""

    def _equals_filter(self, entity: str, canonical_field: str, value: str) -> str:
        field_name = self.model_contract.feishu_field_name(entity, canonical_field)
        return f"CurrentValue.[{field_name}]={json.dumps(value, ensure_ascii=False)}"

    @staticmethod
    def _declared_write_entities(artifacts: dict[str, Any]) -> set[str]:
        report = artifacts.get("writeback_report.json")
        if not isinstance(report, dict):
            return set()
        return {
            _text(item.get("entity"))
            for item in (report.get("writes") or [])
            if isinstance(item, dict) and _text(item.get("entity"))
        }

    @staticmethod
    def _matched_payload(
        matches: list[dict[str, Any]],
        all_rows: list[dict[str, Any]],
        *,
        filtered: bool = False,
    ) -> dict[str, Any]:
        if matches:
            return {"read_state": "available", "records": matches, "reason": "matched persisted records"}
        if not all_rows:
            if filtered:
                return {"read_state": "no_match", "records": [], "reason": "no records matched this run"}
            return {"read_state": "upstream_empty", "records": [], "reason": "source table is empty"}
        return {"read_state": "no_match", "records": [], "reason": "no records matched this run"}

    @staticmethod
    def _wanted_ids(run: dict[str, Any], traces: list[dict[str, Any]], usages: list[dict[str, Any]]) -> dict[str, set[str]]:
        wanted: dict[str, set[str]] = {key: set() for key in ("activities", "assets", "deconstructions", "patterns", "business", "creators")}
        selected: dict[str, set[str]] = {key: set() for key in wanted}
        candidate_map = {
            "activity": ("activities",),
            "material": ("assets", "deconstructions", "patterns"),
            "deconstruction": ("deconstructions",),
            "pattern": ("patterns",),
            "business": ("business",),
            "creator": ("creators",),
        }
        for trace in traces:
            candidate_id = _text(trace.get("candidate_id"))
            for group in candidate_map.get(_text(trace.get("candidate_type")), ()):
                if candidate_id:
                    wanted[group].add(candidate_id)
                    if trace.get("selected") is True:
                        selected[group].add(candidate_id)
        source_asset_id = _text(run.get("source_asset_id"))
        if source_asset_id:
            wanted["assets"].add(source_asset_id)
            selected["assets"].add(source_asset_id)
        for usage in usages:
            for group, field in (("assets", "asset_id"), ("deconstructions", "deconstruction_id"), ("patterns", "pattern_id")):
                value = _text(usage.get(field))
                if value:
                    wanted[group].add(value)
                    if usage.get("selected_for_final") is True:
                        selected[group].add(value)
        for key, values in selected.items():
            wanted[f"{key}:selected"] = values
        return wanted

    def _artifacts(self, run: dict[str, Any]) -> tuple[dict[str, Any], str]:
        uri = _text(run.get("run_artifact_uri"))
        if not uri:
            return {}, "unavailable"
        try:
            anchor = self.vault.resolve_uri(uri)
            directory = anchor.parent
            artifacts: dict[str, Any] = {}
            for filename in KNOWN_ARTIFACT_FILES:
                path = directory / filename
                if not path.is_file():
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, (dict, list)):
                    artifacts[filename] = payload
            return artifacts, "available" if artifacts else "unavailable"
        except (OSError, ValueError, json.JSONDecodeError, MediaVaultError):
            return {}, "unavailable"
