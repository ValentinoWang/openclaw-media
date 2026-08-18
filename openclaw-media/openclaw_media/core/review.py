from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable


_WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")


@dataclass(frozen=True)
class ReviewIssue:
    scope: str
    ref: str | None
    error_code: str


@dataclass(frozen=True)
class OutputMetric:
    metric_id: str
    value: float
    minimum: float | None
    maximum: float | None
    risk_code: str


@dataclass(frozen=True)
class OutputDimension:
    dimension_id: str
    score: float


@dataclass(frozen=True)
class OutputVersionDescriptor:
    version_id: str
    media_ref: str
    contact_sheet_ref: str
    scene_sheet_ref: str
    metrics: tuple[OutputMetric, ...]
    dimensions: tuple[OutputDimension, ...]


@dataclass(frozen=True)
class ReviewWeight:
    dimension_id: str
    weight: float


@dataclass(frozen=True)
class OutputVersionReview:
    version_id: str
    media_ref: str
    gate_status: str
    score: float
    risk_codes: tuple[str, ...]
    suggestion_codes: tuple[str, ...]
    contact_sheet_ref: str
    scene_sheet_ref: str


@dataclass(frozen=True)
class OutputReviewResult:
    status: str
    contract: str
    identity_ref: str | None
    platform: str | None
    versions: tuple[OutputVersionReview, ...]
    issues: tuple[ReviewIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RhythmEvent:
    event_id: str
    channel: str
    event_type: str
    timestamp_seconds: float
    strength: float


@dataclass(frozen=True)
class RhythmProfile:
    profile_id: str
    audio_weight: float
    visual_weight: float
    match_window_seconds: float


@dataclass(frozen=True)
class RhythmMatch:
    audio_event_id: str
    visual_event_id: str
    delta_seconds: float
    score: float


@dataclass(frozen=True)
class RhythmSuggestion:
    timestamp_seconds: float
    suggestion_code: str
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class RhythmReviewResult:
    status: str
    contract: str
    identity_ref: str | None
    media_ref: str | None
    profile_id: str | None
    score: float | None
    phase: str | None
    fixability: str | None
    audio_events: tuple[RhythmEvent, ...]
    visual_events: tuple[RhythmEvent, ...]
    matches: tuple[RhythmMatch, ...]
    suggestions: tuple[RhythmSuggestion, ...]
    issues: tuple[ReviewIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticCriterion:
    criterion_id: str
    rule_score: float
    model_score: float
    model_confidence: float


@dataclass(frozen=True)
class SemanticPolicy:
    policy_id: str
    rule_weight: float
    model_weight: float
    required_criteria: tuple[str, ...]


@dataclass(frozen=True)
class SemanticCriterionReview:
    criterion_id: str
    rule_score: float
    model_score: float
    model_confidence: float
    fused_score: float
    suggestion_code: str | None


@dataclass(frozen=True)
class SemanticReviewResult:
    status: str
    contract: str
    identity_ref: str | None
    contact_sheet_ref: str | None
    policy_id: str | None
    score: float | None
    criteria: tuple[SemanticCriterionReview, ...]
    suggestion_codes: tuple[str, ...]
    issues: tuple[ReviewIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ref(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or _WINDOWS_ABSOLUTE.match(value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def _number(value: object, *, minimum: float | None = None, maximum: float | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return False
    number = float(value)
    return (minimum is None or number >= minimum) and (maximum is None or number <= maximum)


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _issue_ref(value: object) -> str | None:
    return value if _ref(value) else None


def _ordered_issues(issues: Iterable[ReviewIssue]) -> tuple[ReviewIssue, ...]:
    return tuple(sorted(issues, key=lambda item: (item.scope, item.ref or "", item.error_code)))


def _items(value: object) -> list[Any] | None:
    try:
        return list(value)  # type: ignore[arg-type]
    except Exception:
        return None


def review_output(
    versions: Iterable[OutputVersionDescriptor],
    *,
    platform: str,
    weights: Iterable[ReviewWeight],
    required_metrics: Iterable[str] = (),
) -> OutputReviewResult:
    """Rank descriptor-only output versions and enforce explicit technical gates."""
    version_items = _items(versions)
    weight_items = _items(weights)
    required_items = _items(required_metrics)
    issues: list[ReviewIssue] = []
    if version_items is None or weight_items is None or required_items is None or not _ref(platform):
        issues.append(ReviewIssue("output", _issue_ref(platform), "invalid_input"))
    if not version_items:
        issues.append(ReviewIssue("output", None, "missing_version"))
    if not weight_items:
        issues.append(ReviewIssue("policy", None, "missing_weight"))

    valid_weights: dict[str, float] = {}
    for weight in weight_items or []:
        if not isinstance(weight, ReviewWeight) or not _ref(weight.dimension_id) or not _number(weight.weight, minimum=0.0):
            issues.append(ReviewIssue("policy", _issue_ref(getattr(weight, "dimension_id", None)), "invalid_input"))
            continue
        if weight.dimension_id in valid_weights or float(weight.weight) == 0:
            issues.append(ReviewIssue("policy", weight.dimension_id, "weight_conflict"))
            continue
        valid_weights[weight.dimension_id] = float(weight.weight)

    required: set[str] = set()
    for metric_id in required_items or []:
        if not _ref(metric_id) or metric_id in required:
            issues.append(ReviewIssue("policy", _issue_ref(metric_id), "invalid_input"))
        else:
            required.add(metric_id)

    prepared: list[tuple[OutputVersionDescriptor, tuple[str, ...], float]] = []
    version_ids: set[str] = set()
    for version in version_items or []:
        if not isinstance(version, OutputVersionDescriptor):
            issues.append(ReviewIssue("version", None, "invalid_input"))
            continue
        version_ref = _issue_ref(version.version_id)
        if (
            not _ref(version.version_id)
            or not _ref(version.media_ref)
            or not _ref(version.contact_sheet_ref)
            or not _ref(version.scene_sheet_ref)
        ):
            issues.append(ReviewIssue("version", version_ref, "invalid_input"))
            continue
        if version.version_id in version_ids:
            issues.append(ReviewIssue("version", version.version_id, "version_conflict"))
            continue
        version_ids.add(version.version_id)
        metric_items = _items(version.metrics)
        dimension_items = _items(version.dimensions)
        if metric_items is None or dimension_items is None:
            issues.append(ReviewIssue("version", version.version_id, "invalid_input"))
            continue
        metric_ids: set[str] = set()
        risks: list[str] = []
        for metric in metric_items:
            if (
                not isinstance(metric, OutputMetric)
                or not _ref(metric.metric_id)
                or not _ref(metric.risk_code)
                or not _number(metric.value)
                or (metric.minimum is not None and not _number(metric.minimum))
                or (metric.maximum is not None and not _number(metric.maximum))
                or (metric.minimum is not None and metric.maximum is not None and metric.minimum > metric.maximum)
            ):
                issues.append(ReviewIssue("metric", _issue_ref(getattr(metric, "metric_id", None)), "invalid_input"))
                continue
            if metric.metric_id in metric_ids:
                issues.append(ReviewIssue("metric", metric.metric_id, "metric_conflict"))
                continue
            metric_ids.add(metric.metric_id)
            if (metric.minimum is not None and metric.value < metric.minimum) or (
                metric.maximum is not None and metric.value > metric.maximum
            ):
                risks.append(metric.risk_code)
        for missing in sorted(required - metric_ids):
            issues.append(ReviewIssue("metric", f"{version.version_id}/{missing}", "missing_metric"))
        scores: dict[str, float] = {}
        for dimension in dimension_items:
            if (
                not isinstance(dimension, OutputDimension)
                or not _ref(dimension.dimension_id)
                or not _number(dimension.score, minimum=0.0, maximum=100.0)
            ):
                issues.append(
                    ReviewIssue("dimension", _issue_ref(getattr(dimension, "dimension_id", None)), "invalid_input")
                )
                continue
            if dimension.dimension_id in scores:
                issues.append(ReviewIssue("dimension", dimension.dimension_id, "score_conflict"))
                continue
            scores[dimension.dimension_id] = float(dimension.score)
        for missing in sorted(set(valid_weights) - set(scores)):
            issues.append(ReviewIssue("dimension", f"{version.version_id}/{missing}", "missing_score"))
        total_weight = sum(valid_weights.values())
        score = (
            sum(scores.get(key, 0.0) * weight for key, weight in valid_weights.items()) / total_weight
            if total_weight
            else 0.0
        )
        prepared.append((version, tuple(sorted(set(risks))), round(max(0.0, score - 10.0 * len(set(risks))), 6)))

    if issues:
        return OutputReviewResult(
            "rejected", "media.output.review.result.v1", None, platform if _ref(platform) else None, (), _ordered_issues(issues)
        )
    reviews = tuple(
        OutputVersionReview(
            version.version_id,
            version.media_ref,
            "fail" if risks else "pass",
            score,
            risks,
            tuple(f"fix/{code}" for code in risks),
            version.contact_sheet_ref,
            version.scene_sheet_ref,
        )
        for version, risks, score in sorted(prepared, key=lambda item: (-item[2], item[0].version_id))
    )
    payload = {"contract": "media.output.review.result.v1", "platform": platform, "versions": [asdict(item) for item in reviews]}
    return OutputReviewResult("ok", payload["contract"], _digest(payload), platform, reviews, ())


def review_rhythm(
    media_ref: str,
    duration_seconds: float,
    audio_events: Iterable[RhythmEvent],
    visual_events: Iterable[RhythmEvent],
    profile: RhythmProfile,
) -> RhythmReviewResult:
    """Match already-extracted audiovisual events into a deterministic rhythm review."""
    audio_items = _items(audio_events)
    visual_items = _items(visual_events)
    issues: list[ReviewIssue] = []
    if not _ref(media_ref) or not _number(duration_seconds, minimum=0.000001):
        issues.append(ReviewIssue("rhythm", _issue_ref(media_ref), "invalid_input"))
    if (
        not isinstance(profile, RhythmProfile)
        or not _ref(profile.profile_id)
        or not _number(profile.audio_weight, minimum=0.0)
        or not _number(profile.visual_weight, minimum=0.0)
        or not _number(profile.match_window_seconds, minimum=0.000001)
        or float(getattr(profile, "audio_weight", 0)) + float(getattr(profile, "visual_weight", 0)) <= 0
    ):
        issues.append(ReviewIssue("profile", _issue_ref(getattr(profile, "profile_id", None)), "invalid_input"))
    if audio_items is None or visual_items is None:
        issues.append(ReviewIssue("event", None, "invalid_input"))
    if not audio_items:
        issues.append(ReviewIssue("event", "audio", "missing_event"))
    if not visual_items:
        issues.append(ReviewIssue("event", "visual", "missing_event"))

    valid: dict[str, list[RhythmEvent]] = {"audio": [], "visual": []}
    event_ids: set[str] = set()
    for expected, items in (("audio", audio_items or []), ("visual", visual_items or [])):
        for event in items:
            if (
                not isinstance(event, RhythmEvent)
                or not _ref(event.event_id)
                or event.channel != expected
                or not _ref(event.event_type)
                or not _number(event.timestamp_seconds, minimum=0.0)
                or (_number(duration_seconds) and event.timestamp_seconds > duration_seconds)
                or not _number(event.strength, minimum=0.0, maximum=1.0)
            ):
                issues.append(ReviewIssue("event", _issue_ref(getattr(event, "event_id", None)), "invalid_input"))
                continue
            if event.event_id in event_ids:
                issues.append(ReviewIssue("event", event.event_id, "event_conflict"))
                continue
            event_ids.add(event.event_id)
            valid[expected].append(event)
    if issues:
        return RhythmReviewResult(
            "rejected",
            "media.rhythm.review.result.v1",
            None,
            media_ref if _ref(media_ref) else None,
            profile.profile_id if isinstance(profile, RhythmProfile) and _ref(profile.profile_id) else None,
            None,
            None,
            None,
            (),
            (),
            (),
            (),
            _ordered_issues(issues),
        )

    ordered_audio = tuple(sorted(valid["audio"], key=lambda item: (item.timestamp_seconds, item.event_id)))
    ordered_visual = tuple(sorted(valid["visual"], key=lambda item: (item.timestamp_seconds, item.event_id)))
    unmatched_visual = {event.event_id: event for event in ordered_visual}
    matches: list[RhythmMatch] = []
    unmatched_audio: list[RhythmEvent] = []
    total_weight = profile.audio_weight + profile.visual_weight
    for audio in ordered_audio:
        candidates = [
            visual
            for visual in unmatched_visual.values()
            if abs(visual.timestamp_seconds - audio.timestamp_seconds) <= profile.match_window_seconds
        ]
        if not candidates:
            unmatched_audio.append(audio)
            continue
        visual = min(candidates, key=lambda item: (abs(item.timestamp_seconds - audio.timestamp_seconds), item.event_id))
        delta = visual.timestamp_seconds - audio.timestamp_seconds
        alignment = 1.0 - abs(delta) / profile.match_window_seconds
        strength = (audio.strength * profile.audio_weight + visual.strength * profile.visual_weight) / total_weight
        matches.append(RhythmMatch(audio.event_id, visual.event_id, round(delta, 6), round(100.0 * alignment * strength, 6)))
        del unmatched_visual[visual.event_id]
    suggestions = [
        RhythmSuggestion(event.timestamp_seconds, "align_visual_to_audio", (event.event_id,)) for event in unmatched_audio
    ] + [
        RhythmSuggestion(event.timestamp_seconds, "align_audio_to_visual", (event.event_id,))
        for event in unmatched_visual.values()
    ]
    ordered_matches = tuple(sorted(matches, key=lambda item: (item.audio_event_id, item.visual_event_id)))
    ordered_suggestions = tuple(
        sorted(suggestions, key=lambda item: (item.timestamp_seconds, item.suggestion_code, item.event_ids))
    )
    score = round(sum(item.score for item in ordered_matches) / max(len(ordered_audio), len(ordered_visual)), 6)
    mean_delta = sum(item.delta_seconds for item in ordered_matches) / len(ordered_matches) if ordered_matches else 0.0
    phase = "visual_late" if mean_delta > 0.03 else "visual_early" if mean_delta < -0.03 else "synchronized"
    ratio = len(ordered_suggestions) / (len(ordered_audio) + len(ordered_visual))
    fixability = "high" if ratio <= 0.25 else "medium" if ratio <= 0.5 else "low"
    payload = {
        "contract": "media.rhythm.review.result.v1",
        "media_ref": media_ref,
        "profile_id": profile.profile_id,
        "score": score,
        "phase": phase,
        "fixability": fixability,
        "audio_events": [asdict(item) for item in ordered_audio],
        "visual_events": [asdict(item) for item in ordered_visual],
        "matches": [asdict(item) for item in ordered_matches],
        "suggestions": [asdict(item) for item in ordered_suggestions],
    }
    return RhythmReviewResult(
        "ok",
        payload["contract"],
        _digest(payload),
        media_ref,
        profile.profile_id,
        score,
        phase,
        fixability,
        ordered_audio,
        ordered_visual,
        ordered_matches,
        ordered_suggestions,
        (),
    )


def review_semantic(
    contact_sheet_ref: str,
    criteria: Iterable[SemanticCriterion],
    policy: SemanticPolicy,
) -> SemanticReviewResult:
    """Fuse bounded rule and vision-model scores without retaining provider payloads."""
    criterion_items = _items(criteria)
    issues: list[ReviewIssue] = []
    if not _ref(contact_sheet_ref):
        issues.append(ReviewIssue("semantic", None, "invalid_input"))
    if (
        not isinstance(policy, SemanticPolicy)
        or not _ref(policy.policy_id)
        or not _number(policy.rule_weight, minimum=0.0)
        or not _number(policy.model_weight, minimum=0.0)
        or float(getattr(policy, "rule_weight", 0)) + float(getattr(policy, "model_weight", 0)) <= 0
    ):
        issues.append(ReviewIssue("policy", _issue_ref(getattr(policy, "policy_id", None)), "invalid_input"))
    required_items = _items(getattr(policy, "required_criteria", ())) if isinstance(policy, SemanticPolicy) else []
    if criterion_items is None or required_items is None:
        issues.append(ReviewIssue("criterion", None, "invalid_input"))
    if not criterion_items:
        issues.append(ReviewIssue("criterion", None, "missing_model_assessment"))

    required: set[str] = set()
    for criterion_id in required_items or []:
        if not _ref(criterion_id) or criterion_id in required:
            issues.append(ReviewIssue("policy", _issue_ref(criterion_id), "invalid_input"))
        else:
            required.add(criterion_id)
    valid: dict[str, SemanticCriterion] = {}
    for criterion in criterion_items or []:
        if (
            not isinstance(criterion, SemanticCriterion)
            or not _ref(criterion.criterion_id)
            or not _number(criterion.rule_score, minimum=0.0, maximum=100.0)
            or not _number(criterion.model_score, minimum=0.0, maximum=100.0)
            or not _number(criterion.model_confidence, minimum=0.0, maximum=1.0)
        ):
            issues.append(
                ReviewIssue("criterion", _issue_ref(getattr(criterion, "criterion_id", None)), "invalid_model_assessment")
            )
            continue
        if criterion.criterion_id in valid:
            issues.append(ReviewIssue("criterion", criterion.criterion_id, "criterion_conflict"))
            continue
        valid[criterion.criterion_id] = criterion
    for missing in sorted(required - set(valid)):
        issues.append(ReviewIssue("criterion", missing, "missing_model_assessment"))
    if issues:
        return SemanticReviewResult(
            "rejected",
            "media.semantic.review.result.v1",
            None,
            contact_sheet_ref if _ref(contact_sheet_ref) else None,
            policy.policy_id if isinstance(policy, SemanticPolicy) and _ref(policy.policy_id) else None,
            None,
            (),
            (),
            _ordered_issues(issues),
        )

    weight_total = policy.rule_weight + policy.model_weight
    reviews: list[SemanticCriterionReview] = []
    for criterion in valid.values():
        effective_rule_weight = policy.rule_weight + policy.model_weight * (1.0 - criterion.model_confidence)
        effective_model_weight = policy.model_weight * criterion.model_confidence
        fused = round(
            (criterion.rule_score * effective_rule_weight + criterion.model_score * effective_model_weight) / weight_total,
            6,
        )
        reviews.append(
            SemanticCriterionReview(
                criterion.criterion_id,
                float(criterion.rule_score),
                float(criterion.model_score),
                float(criterion.model_confidence),
                fused,
                f"improve/{criterion.criterion_id}" if fused < 60 else None,
            )
        )
    ordered_reviews = tuple(sorted(reviews, key=lambda item: item.criterion_id))
    suggestions = tuple(item.suggestion_code for item in ordered_reviews if item.suggestion_code is not None)
    score = round(sum(item.fused_score for item in ordered_reviews) / len(ordered_reviews), 6)
    payload = {
        "contract": "media.semantic.review.result.v1",
        "contact_sheet_ref": contact_sheet_ref,
        "policy_id": policy.policy_id,
        "score": score,
        "criteria": [asdict(item) for item in ordered_reviews],
        "suggestion_codes": suggestions,
    }
    return SemanticReviewResult(
        "ok", payload["contract"], _digest(payload), contact_sheet_ref, policy.policy_id, score, ordered_reviews, suggestions, ()
    )
