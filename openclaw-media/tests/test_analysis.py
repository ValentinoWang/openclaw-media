from __future__ import annotations

import copy

from openclaw_media import (
    AnalysisModelOutput,
    AnalysisUnknown,
    ModelJudgment,
    SourceFact,
    StructuredResult,
    TechnicalCheck,
    build_analysis_report,
)


def _structured(*, statement: str = "The opening has a clear subject") -> StructuredResult[AnalysisModelOutput]:
    return StructuredResult[AnalysisModelOutput](
        value=AnalysisModelOutput(
            judgments=(
                ModelJudgment(
                    judgment_id="judgment/opening",
                    statement=statement,
                    confidence=0.8,
                    evidence_fact_ids=("fact/duration", "fact/frames"),
                ),
            ),
            unknowns=(
                AnalysisUnknown(
                    unknown_id="unknown/audience-retention",
                    question="How will the target audience retain through the ending?",
                    reason_code="missing_audience_observation",
                ),
            ),
        ),
        model_label="confirmed-vision-model",
    )


def _facts() -> tuple[SourceFact, ...]:
    return (
        SourceFact(
            fact_id="fact/frames",
            statement="The final contains 120 decoded frames",
            evidence_refs=("evidence/final.ffprobe.json",),
        ),
        SourceFact(
            fact_id="fact/duration",
            statement="The final duration is 4 seconds",
            evidence_refs=("evidence/final.ffprobe.json",),
        ),
    )


def test_analysis_golden_separates_facts_judgments_unknowns_and_technical_review() -> None:
    facts = _facts()
    structured = _structured()
    checks = (
        TechnicalCheck(
            check_id="check/audio",
            status="pass",
            detail_code="audio_track_present",
            fact_ids=("fact/duration",),
        ),
        TechnicalCheck(
            check_id="check/bitrate",
            status="fail",
            detail_code="bitrate_below_floor",
            fact_ids=("fact/frames",),
        ),
    )
    before = copy.deepcopy((facts, structured, checks))

    first = build_analysis_report(reversed(facts), structured, reversed(checks))
    second = build_analysis_report(facts, structured, checks)

    assert first == second
    assert (facts, structured, checks) == before
    assert (first.status, first.code, first.archivable) == ("ready", "ok", True)
    assert first.report is not None and first.review is not None
    assert first.report.contract == "media.analysis.report.v1"
    assert first.review.contract == "media.review.result.v1"
    assert first.report.identity_ref.startswith("sha256:")
    assert [item.fact_id for item in first.report.source_facts] == ["fact/duration", "fact/frames"]
    assert [item.judgment_id for item in first.report.model_judgments] == ["judgment/opening"]
    assert [item.unknown_id for item in first.report.unknowns] == ["unknown/audience-retention"]
    assert first.review.status == "fail"
    assert first.review.failed_check_ids == ("check/bitrate",)
    assert first.review.warning_check_ids == ()

    serialized = first.model_dump_json()
    for forbidden in ("raw_prompt", "prompt_tokens", "completion_tokens", "provider_payload"):
        assert forbidden not in serialized


def test_invalid_model_schema_fails_closed_without_report_or_input_leak() -> None:
    malicious = {
        "value": {
            "judgments": [],
            "unknowns": [],
            "raw_prompt": "private prompt /Users/alice/project token=secret-token",
        },
        "model_label": "confirmed-vision-model",
        "prompt_tokens": 999,
    }

    outcome = build_analysis_report(_facts(), malicious, ())

    assert (outcome.status, outcome.code, outcome.archivable) == (
        "pending_manual",
        "invalid_model_schema",
        False,
    )
    assert outcome.report is outcome.review is None
    serialized = outcome.model_dump_json()
    assert "private prompt" not in serialized
    assert "secret-token" not in serialized
    assert "/Users/alice" not in serialized
    assert "999" not in serialized


def test_unknown_references_and_unsafe_evidence_refs_fail_closed() -> None:
    unknown_fact = StructuredResult[AnalysisModelOutput](
        value=AnalysisModelOutput(
            judgments=(
                ModelJudgment(
                    judgment_id="judgment/orphan",
                    statement="Unsupported conclusion",
                    confidence=0.5,
                    evidence_fact_ids=("fact/missing",),
                ),
            ),
            unknowns=(),
        ),
        model_label="confirmed-model",
    )
    unsafe_fact = {
        "fact_id": "fact/path",
        "statement": "Probe exists",
        "evidence_refs": ("/private/probe.json",),
    }

    orphan = build_analysis_report(_facts(), unknown_fact, ())
    unsafe = build_analysis_report((unsafe_fact,), _structured(), ())  # type: ignore[arg-type]

    assert (orphan.status, orphan.code, orphan.archivable) == (
        "pending_manual",
        "invalid_evidence_reference",
        False,
    )
    assert (unsafe.status, unsafe.code, unsafe.archivable) == (
        "pending_manual",
        "invalid_source_facts",
        False,
    )
    assert orphan.report is orphan.review is None
    assert unsafe.report is unsafe.review is None
    assert "/private" not in repr(unsafe)


def test_review_uses_declared_technical_checks_not_business_meaning_fallback() -> None:
    negative_model_statement = _structured(statement="The creative direction appears unsuitable")
    checks = (
        TechnicalCheck(
            check_id="check/container",
            status="pass",
            detail_code="container_valid",
            fact_ids=("fact/frames",),
        ),
    )

    outcome = build_analysis_report(_facts(), negative_model_statement, checks)

    assert outcome.status == "ready"
    assert outcome.review is not None and outcome.review.status == "pass"
    assert outcome.review.passed_check_ids == ("check/container",)
    assert outcome.report is not None
    assert outcome.report.model_judgments[0].statement == "The creative direction appears unsuitable"
