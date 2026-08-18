"""Fail-closed assembly of local analysis and technical review artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .provider_adapter import StructuredResult


_PUBLIC_ID = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_PUBLIC_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_CODE = re.compile(r"^[a-z0-9][a-z0-9_/-]{0,127}$")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


def _relative_ref(value: str) -> str:
    if not value or "\\" in value or "://" in value:
        raise ValueError("unsafe_ref")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unsafe_ref")
    return value


def _public_id(value: str) -> str:
    if not _PUBLIC_ID.fullmatch(value) or value.startswith("/") or ".." in value.split("/"):
        raise ValueError("invalid_id")
    return value


class SourceFact(_FrozenModel):
    fact_id: str
    statement: str = Field(min_length=1, max_length=4096)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=64)

    _validate_id = field_validator("fact_id")(_public_id)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_relative_ref(value) for value in values)


class ModelJudgment(_FrozenModel):
    judgment_id: str
    statement: str = Field(min_length=1, max_length=4096)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_fact_ids: tuple[str, ...] = Field(min_length=1, max_length=64)

    _validate_id = field_validator("judgment_id")(_public_id)

    @field_validator("evidence_fact_ids")
    @classmethod
    def _validate_fact_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_public_id(value) for value in values)


class AnalysisUnknown(_FrozenModel):
    unknown_id: str
    question: str = Field(min_length=1, max_length=4096)
    reason_code: str

    _validate_id = field_validator("unknown_id")(_public_id)
    _validate_reason = field_validator("reason_code")(
        lambda value: value if _CODE.fullmatch(value) else (_ for _ in ()).throw(ValueError("invalid_code"))
    )


class AnalysisModelOutput(_FrozenModel):
    """The only persisted subset of the provider response."""

    judgments: tuple[ModelJudgment, ...] = Field(max_length=256)
    unknowns: tuple[AnalysisUnknown, ...] = Field(max_length=256)


class TechnicalCheck(_FrozenModel):
    check_id: str
    status: Literal["pass", "warn", "fail"]
    detail_code: str
    fact_ids: tuple[str, ...] = Field(max_length=64)

    _validate_id = field_validator("check_id")(_public_id)
    _validate_detail = field_validator("detail_code")(
        lambda value: value if _CODE.fullmatch(value) else (_ for _ in ()).throw(ValueError("invalid_code"))
    )

    @field_validator("fact_ids")
    @classmethod
    def _validate_fact_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_public_id(value) for value in values)


class AnalysisReport(_FrozenModel):
    contract: Literal["media.analysis.report.v1"]
    identity_ref: str
    source_facts: tuple[SourceFact, ...]
    model_judgments: tuple[ModelJudgment, ...]
    unknowns: tuple[AnalysisUnknown, ...]
    model_label: str


class ReviewResult(_FrozenModel):
    contract: Literal["media.review.result.v1"]
    identity_ref: str
    report_ref: str
    status: Literal["pass", "warn", "fail"]
    technical_checks: tuple[TechnicalCheck, ...]
    passed_check_ids: tuple[str, ...]
    warning_check_ids: tuple[str, ...]
    failed_check_ids: tuple[str, ...]


class AnalysisOutcome(_FrozenModel):
    status: Literal["ready", "pending_manual"]
    code: str
    archivable: bool
    report: AnalysisReport | None
    review: ReviewResult | None


def _pending(code: str) -> AnalysisOutcome:
    return AnalysisOutcome(
        status="pending_manual", code=code, archivable=False, report=None, review=None
    )


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _unique(items: tuple[Any, ...], attribute: str) -> bool:
    values = [getattr(item, attribute) for item in items]
    return len(values) == len(set(values))


def build_analysis_report(
    source_facts: Iterable[SourceFact],
    model_output: object,
    technical_checks: Iterable[TechnicalCheck],
) -> AnalysisOutcome:
    """Build an archivable pair only from already structured, cross-linked inputs."""

    try:
        facts = tuple(sorted(tuple(source_facts), key=lambda item: item.fact_id))
        if not facts or not all(isinstance(item, SourceFact) for item in facts):
            return _pending("invalid_source_facts")
    except Exception:
        return _pending("invalid_source_facts")
    if not _unique(facts, "fact_id"):
        return _pending("invalid_source_facts")

    if not isinstance(model_output, StructuredResult) or not isinstance(
        model_output.value, AnalysisModelOutput
    ):
        return _pending("invalid_model_schema")
    if not isinstance(model_output.model_label, str) or not _PUBLIC_LABEL.fullmatch(
        model_output.model_label
    ):
        return _pending("invalid_model_schema")
    judgments = tuple(sorted(model_output.value.judgments, key=lambda item: item.judgment_id))
    unknowns = tuple(sorted(model_output.value.unknowns, key=lambda item: item.unknown_id))
    if not _unique(judgments, "judgment_id") or not _unique(unknowns, "unknown_id"):
        return _pending("invalid_model_schema")

    try:
        checks = tuple(sorted(tuple(technical_checks), key=lambda item: item.check_id))
        if not all(isinstance(item, TechnicalCheck) for item in checks):
            return _pending("invalid_technical_checks")
    except Exception:
        return _pending("invalid_technical_checks")
    if not _unique(checks, "check_id"):
        return _pending("invalid_technical_checks")

    fact_ids = {item.fact_id for item in facts}
    referenced = [fact_id for item in judgments for fact_id in item.evidence_fact_ids]
    referenced.extend(fact_id for item in checks for fact_id in item.fact_ids)
    if any(fact_id not in fact_ids for fact_id in referenced):
        return _pending("invalid_evidence_reference")
    if not checks:
        return _pending("invalid_technical_checks")

    report_payload = {
        "contract": "media.analysis.report.v1",
        "source_facts": [item.model_dump(mode="json") for item in facts],
        "model_judgments": [item.model_dump(mode="json") for item in judgments],
        "unknowns": [item.model_dump(mode="json") for item in unknowns],
        "model_label": model_output.model_label,
    }
    report = AnalysisReport(
        contract="media.analysis.report.v1",
        identity_ref=_digest(report_payload),
        source_facts=facts,
        model_judgments=judgments,
        unknowns=unknowns,
        model_label=model_output.model_label,
    )
    passed = tuple(item.check_id for item in checks if item.status == "pass")
    warnings = tuple(item.check_id for item in checks if item.status == "warn")
    failed = tuple(item.check_id for item in checks if item.status == "fail")
    status: Literal["pass", "warn", "fail"] = "fail" if failed else "warn" if warnings else "pass"
    review_payload = {
        "contract": "media.review.result.v1",
        "report_ref": report.identity_ref,
        "status": status,
        "technical_checks": [item.model_dump(mode="json") for item in checks],
        "passed_check_ids": passed,
        "warning_check_ids": warnings,
        "failed_check_ids": failed,
    }
    review = ReviewResult(
        contract="media.review.result.v1",
        identity_ref=_digest(review_payload),
        report_ref=report.identity_ref,
        status=status,
        technical_checks=checks,
        passed_check_ids=passed,
        warning_check_ids=warnings,
        failed_check_ids=failed,
    )
    return AnalysisOutcome(status="ready", code="ok", archivable=True, report=report, review=review)


__all__ = [
    "AnalysisModelOutput",
    "AnalysisOutcome",
    "AnalysisReport",
    "AnalysisUnknown",
    "ModelJudgment",
    "ReviewResult",
    "SourceFact",
    "TechnicalCheck",
    "build_analysis_report",
]
