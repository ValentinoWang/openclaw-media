from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, root_validator, validator


class MultiSignalContractSchemaError(ValueError):
    pass


class SignalDimensionStatus(str, Enum):
    AVAILABLE = "available"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SCHEMA_FAILED = "schema_failed"
    LLM_FAILED = "llm_failed"


class DimensionAnalysis(BaseModel):
    dimension_id: str
    status: SignalDimensionStatus
    source_refs: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    summary: str = ""
    reusable_signal: str = ""
    transform_rule: str = ""
    risk_boundary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    insufficient_evidence: list[str] = Field(default_factory=list)
    conflict_notes: list[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"
        use_enum_values = True

    @validator("dimension_id", pre=True)
    def non_empty_dimension_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("dimension_analysis.dimension_id 不能为空")
        return text

    @validator("source_refs", "observations", "insufficient_evidence", "conflict_notes", pre=True)
    def normalize_string_items(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value or "").strip() else []

    @validator("summary", "reusable_signal", "transform_rule", "risk_boundary", pre=True, always=True)
    def normalize_optional_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @root_validator(skip_on_failure=True)
    def validate_dimension_scope(cls, values: dict[str, Any]) -> dict[str, Any]:
        status = str(values.get("status") or "")
        forbidden_final_fields = {
            "editorial_plan",
            "production_route_plan",
            "reusable_high_like_comment",
            "operation_plan",
            "final_script",
            "video_storyboard",
            "image_post_script",
            "titles",
            "hashtags",
        }
        extra_keys = set(values) & forbidden_final_fields
        if extra_keys:
            raise ValueError("DimensionAnalysis 禁止包含最终再创字段: " + ", ".join(sorted(extra_keys)))
        if status == SignalDimensionStatus.AVAILABLE.value:
            for key in ("source_refs", "summary", "reusable_signal", "transform_rule", "risk_boundary"):
                if values.get(key) in (None, "", [], {}):
                    raise ValueError(f"DimensionAnalysis.status=available 时 {key} 不能为空")
        if status == SignalDimensionStatus.INSUFFICIENT_EVIDENCE.value and not values.get("insufficient_evidence"):
            raise ValueError("DimensionAnalysis.status=insufficient_evidence 时 insufficient_evidence 不能为空")
        return values


class AggregationReport(BaseModel):
    dimension_count: int = Field(ge=0)
    available_dimensions: list[str] = Field(default_factory=list)
    insufficient_dimensions: list[str] = Field(default_factory=list)
    failed_dimensions: list[str] = Field(default_factory=list)
    source_ref_failures: list[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"


class ShotAdaptationNote(BaseModel):
    note_id: str
    source_refs: list[str] = Field(default_factory=list)
    source_dimension_ids: list[str] = Field(default_factory=list)
    learnable_pattern: str
    adaptation_rule: str
    do_not_copy: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    class Config:
        extra = "forbid"

    @validator("note_id", "learnable_pattern", "adaptation_rule", pre=True)
    def non_empty_note_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("shot_adaptation_notes.note_id/learnable_pattern/adaptation_rule 不能为空")
        return text

    @validator("source_refs", "source_dimension_ids", "do_not_copy", pre=True)
    def normalize_note_items(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value or "").strip() else []


class MultiSignalContractValidation(BaseModel):
    source_refs_status: str
    multi_signal_contract_status: str
    warnings: list[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"


class MultiSignalContract(BaseModel):
    contract_version: str
    evidence_manifest_refs: list[str] = Field(default_factory=list)
    source_signal_dimensions: list[DimensionAnalysis] = Field(min_items=1)
    shot_adaptation_notes: list[ShotAdaptationNote] = Field(default_factory=list)
    evidence_store_summary: dict[str, Any] = Field(default_factory=dict)
    aggregation_report: AggregationReport
    conflict_notes: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    validation: MultiSignalContractValidation

    class Config:
        extra = "forbid"
        use_enum_values = True

    @validator("contract_version", pre=True)
    def non_empty_contract_version(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("multi_signal_contract.contract_version 不能为空")
        return text

    @validator("evidence_manifest_refs", "conflict_notes", "open_questions", pre=True)
    def normalize_contract_string_items(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value or "").strip() else []


def validate_dimension_analysis_payload(payload: dict[str, Any], evidence_ids: set[str], *, expected_dimension_id: str = "") -> dict[str, Any]:
    if not evidence_ids:
        raise MultiSignalContractSchemaError("缺少 evidence_manifest，无法校验 DimensionAnalysis.source_refs")
    result = jsonable_model_dict(DimensionAnalysis.parse_obj(payload))
    if expected_dimension_id and result.get("dimension_id") != expected_dimension_id:
        raise MultiSignalContractSchemaError(
            f"DimensionAnalysis.dimension_id 不匹配: expected={expected_dimension_id}, actual={result.get('dimension_id')}"
        )
    for ref in result.get("source_refs") or []:
        ref_text = str(ref or "").strip()
        if ref_text not in evidence_ids:
            raise MultiSignalContractSchemaError(f"DimensionAnalysis.source_refs 非法: {ref_text}")
    return result


def validate_multi_signal_contract_payload(payload: dict[str, Any], evidence_ids: set[str]) -> dict[str, Any]:
    if not evidence_ids:
        raise MultiSignalContractSchemaError("缺少 evidence_manifest，无法校验 MultiSignalContract")
    result = jsonable_model_dict(MultiSignalContract.parse_obj(payload))
    for ref in result.get("evidence_manifest_refs") or []:
        ref_text = str(ref or "").strip()
        if ref_text not in evidence_ids:
            raise MultiSignalContractSchemaError(f"MultiSignalContract.evidence_manifest_refs 非法: {ref_text}")
    for index, dimension in enumerate(result.get("source_signal_dimensions") or [], 1):
        for ref in dimension.get("source_refs") or []:
            ref_text = str(ref or "").strip()
            if ref_text not in evidence_ids:
                raise MultiSignalContractSchemaError(f"MultiSignalContract.source_signal_dimensions[{index}].source_refs 非法: {ref_text}")
    for index, note in enumerate(result.get("shot_adaptation_notes") or [], 1):
        for ref in note.get("source_refs") or []:
            ref_text = str(ref or "").strip()
            if ref_text not in evidence_ids:
                raise MultiSignalContractSchemaError(f"MultiSignalContract.shot_adaptation_notes[{index}].source_refs 非法: {ref_text}")
    if len(result.get("source_signal_dimensions") or []) < 1:
        raise MultiSignalContractSchemaError("MultiSignalContract.source_signal_dimensions 不能为空")
    return result


def jsonable_model_dict(model: BaseModel) -> dict[str, Any]:
    return jsonable(model.dict())


def jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value
