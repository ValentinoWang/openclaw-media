from __future__ import annotations

import copy

from openclaw_media.core import (
    OutputDimension,
    OutputMetric,
    OutputVersionDescriptor,
    ReviewWeight,
    RhythmEvent,
    RhythmProfile,
    SemanticCriterion,
    SemanticPolicy,
    review_output,
    review_rhythm,
    review_semantic,
)


def _version(version_id: str, *, score: float, bitrate: float) -> OutputVersionDescriptor:
    return OutputVersionDescriptor(
        version_id,
        f"media/{version_id}.mp4",
        f"review/{version_id}-contact.jpg",
        f"review/{version_id}-scenes.jpg",
        (OutputMetric("bitrate", bitrate, 4.0, 12.0, "compression_risk"),),
        (OutputDimension("hook", score), OutputDimension("platform", score - 5)),
    )


def test_output_review_golden_ranks_versions_and_applies_technical_gate() -> None:
    versions = [_version("压缩版", score=92, bitrate=2), _version("发布版", score=88, bitrate=8)]
    weights = [ReviewWeight("platform", 1), ReviewWeight("hook", 2)]
    before = copy.deepcopy((versions, weights))

    first = review_output(reversed(versions), platform="douyin", weights=reversed(weights), required_metrics=("bitrate",))
    second = review_output(versions, platform="douyin", weights=weights, required_metrics=("bitrate",))

    assert first == second
    assert (versions, weights) == before
    assert first.status == "ok"
    assert first.identity_ref == "sha256:6b192f5fb81617cd755663ea8534976a3a556bffe3dc76ede63b717cf0fba7bc"
    assert [item.version_id for item in first.versions] == ["发布版", "压缩版"]
    assert first.versions[0].gate_status == "pass"
    assert first.versions[1].risk_codes == ("compression_risk",)
    assert first.versions[1].suggestion_codes == ("fix/compression_risk",)


def test_rhythm_review_golden_matches_events_and_emits_fixable_timestamp() -> None:
    audio = [RhythmEvent("beat-2", "audio", "beat", 2.0, 0.8), RhythmEvent("beat-1", "audio", "beat", 1.0, 1.0)]
    visual = [RhythmEvent("cut-1", "visual", "scene", 1.04, 0.9), RhythmEvent("cut-extra", "visual", "scene", 4.0, 0.7)]
    result = review_rhythm("成片/版本一.mp4", 5.0, audio, visual, RhythmProfile("fast-cut", 1, 1, 0.1))

    assert result.status == "ok"
    assert result.identity_ref == "sha256:f2ff16214a3695c913842f5e3d327e4e0a4ee55465ef5cd1d267bbd7129cce1b"
    assert [(item.audio_event_id, item.visual_event_id) for item in result.matches] == [("beat-1", "cut-1")]
    assert result.phase == "visual_late"
    assert [(item.timestamp_seconds, item.suggestion_code) for item in result.suggestions] == [
        (2.0, "align_visual_to_audio"),
        (4.0, "align_audio_to_visual"),
    ]


def test_semantic_review_golden_fuses_bounded_scores_without_provider_payload() -> None:
    criteria = [
        SemanticCriterion("topic", 70, 90, 1),
        SemanticCriterion("composition", 50, 40, 0.5),
        SemanticCriterion("hook", 80, 60, 0.8),
    ]
    policy = SemanticPolicy("publish-v1", 0.4, 0.6, ("hook", "topic", "composition"))
    result = review_semantic("review/联系表.jpg", reversed(criteria), policy)

    assert result.status == "ok"
    assert result.identity_ref == "sha256:012a151c64a56f3844b53d5af0af9aecc166b03f88938f1db465a90bca004547"
    assert [item.criterion_id for item in result.criteria] == ["composition", "hook", "topic"]
    assert result.suggestion_codes == ("improve/composition",)
    assert "provider" not in result.to_dict()


def test_invalid_missing_conflicting_and_absolute_inputs_are_explicit_and_redacted() -> None:
    output = review_output(
        [_version("same", score=80, bitrate=8), _version("same", score=70, bitrate=8)],
        platform="/private/platform",
        weights=[ReviewWeight("hook", 1)],
        required_metrics=("duration",),
    )
    rhythm = review_rhythm(
        "C:\\private\\clip.mp4", 3, [], [], RhythmProfile("profile", 1, 1, 0.1)
    )
    semantic = review_semantic(
        "/private/contact.jpg", [], SemanticPolicy("policy", 1, 1, ("hook",))
    )

    assert output.status == rhythm.status == semantic.status == "rejected"
    assert output.identity_ref is rhythm.identity_ref is semantic.identity_ref is None
    assert {item.error_code for item in output.issues} >= {"invalid_input", "version_conflict", "missing_metric"}
    assert {item.error_code for item in rhythm.issues} >= {"invalid_input", "missing_event"}
    assert {item.error_code for item in semantic.issues} >= {"invalid_input", "missing_model_assessment"}
    assert "/private" not in repr((output, rhythm, semantic))
