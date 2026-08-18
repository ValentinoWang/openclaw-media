from __future__ import annotations

from pathlib import Path

from openclaw_media import InstalledCatalog, NodeRegistry, StructuredResult
from openclaw_media.analysis import AnalysisModelOutput
from openclaw_media.node_registry import SemanticModelScores
from openclaw_media.provider_adapter import ProviderAdapter, VisionResult
from openclaw_media.core import (
    EDLEntry,
    HandoffClipDescriptor,
    RevisionArtifact,
    RevisionChange,
    RevisionConfirmation,
    Revision,
    StoryboardEntry,
)


class StubProvider(ProviderAdapter):
    def complete_structured(self, prompt, schema):
        if schema is AnalysisModelOutput:
            value = AnalysisModelOutput(judgments=(), unknowns=())
        else:
            value = SemanticModelScores(scores={"hook": 80.0})
        return StructuredResult(value=value, model_label="test-provider")

    def complete_vision(self, prompt, images):
        return VisionResult(content="bounded", model_label="test-provider")


def _context(root: Path, inputs: dict) -> dict:
    return {"run_ref": "runs/node-types", "workspace_root": root, "inputs": inputs, "artifacts": {}}


def test_every_catalog_node_type_dispatches_through_the_single_registry(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "clip.png").write_bytes(b"png-bytes")
    identity = "sha256:" + "a" * 64
    registry = NodeRegistry(InstalledCatalog(), provider=StubProvider.__new__(StubProvider))

    nodes = {
        "project.prepare": ({"workspace_ref": "media"}, "project_overview"),
        "material.organize": ({"workspace_ref": "media"}, "organization_plan"),
        "material.match": ({"workspace_ref": "media", "brief": "confirmed", "shots": [{"shot_id": "shot-1", "sequence": 1, "duration_seconds": 1.0}]}, "edit_decision_list"),
        "edit.handoff": (
            {
                "clips": [{"clip_id": "clip-1", "identity_ref": identity, "material_ref": "media/clip.png", "kind": "video", "duration_seconds": 1.0}],
                "storyboard": [{"shot_id": "shot-1", "sequence": 1, "timeline_in_seconds": 0.0, "timeline_out_seconds": 1.0, "duration_seconds": 1.0, "match_status": "matched", "error_code": None, "material_ref": "media/clip.png", "identity_ref": identity}],
                "edl": [{"edit_id": "edit-1", "shot_id": "shot-1", "sequence": 1, "timeline_in_seconds": 0.0, "timeline_out_seconds": 1.0, "source_in_seconds": 0.0, "source_out_seconds": 1.0, "material_ref": "media/clip.png", "identity_ref": identity}],
            },
            "handoff_manifest",
        ),
        "edit.timeline": (
            {
                "edl": [{"edit_id": "edit-1", "shot_id": "shot-1", "sequence": 1, "timeline_in_seconds": 0.0, "timeline_out_seconds": 1.0, "source_in_seconds": 0.0, "source_out_seconds": 1.0, "material_ref": "media/clip.png", "identity_ref": identity}],
                "media": [{"identity_ref": identity, "material_ref": "media/clip.png", "kind": "video", "duration_seconds": 1.0}],
            },
            "timeline",
        ),
        "edit.revise": (
            {
                "base_revision": {"revision_ref": "revisions/base.json", "identity_ref": identity, "parent_identity_ref": None, "artifacts": [{"artifact_id": "storyboard", "kind": "storyboard", "artifact_ref": "artifacts/storyboard.json", "identity_ref": "sha256:" + "c" * 64}, {"artifact_id": "edl", "kind": "edl", "artifact_ref": "artifacts/edl.json", "identity_ref": "sha256:" + "d" * 64}, {"artifact_id": "editor", "kind": "editor_artifact", "artifact_ref": "artifacts/editor.otio", "identity_ref": "sha256:" + "e" * 64}]},
                "changes": [{"change_id": "change-1", "sequence": 1, "artifact_id": "edl", "expected_identity_ref": "sha256:" + "d" * 64, "updated_ref": "artifacts/edl-v2.json", "updated_identity_ref": "sha256:" + "b" * 64, "operation": "retime"}],
                "confirmation": {"confirmation_ref": "confirmations/one", "confirmed": True},
                "run_ref": "runs/node-types",
            },
            "change_receipt",
        ),
        "output.review": (
            {"media_ref": "media/clip.png", "platform": "platform/mobile", "versions": [{"version_id": "v1", "media_ref": "media/clip.png", "contact_sheet_ref": "review/contact.jpg", "scene_sheet_ref": "review/scene.jpg", "metrics": [{"metric_id": "bitrate", "value": 8.0, "minimum": 1.0, "maximum": 10.0, "risk_code": "bitrate"}], "dimensions": [{"dimension_id": "hook", "score": 80.0}]}], "weights": [{"dimension_id": "hook", "weight": 1.0}], "required_metrics": ["bitrate"]},
            "review_report",
        ),
        "rhythm.review": ({"media_ref": "media/clip.png", "duration_seconds": 1.0, "audio_events": [{"event_id": "beat-1", "channel": "audio", "event_type": "beat", "timestamp_seconds": 0.5, "strength": 1.0}], "visual_events": [{"event_id": "cut-1", "channel": "visual", "event_type": "cut", "timestamp_seconds": 0.5, "strength": 1.0}], "profile": {"profile_id": "profile/one", "audio_weight": 1.0, "visual_weight": 1.0, "match_window_seconds": 0.1}}, "rhythm_report"),
        "semantic.review": ({"contact_sheet_ref": "media/clip.png", "image_ref": "media/clip.png", "criteria": [{"criterion_id": "hook", "rule_score": 80.0, "model_score": 80.0, "model_confidence": 0.9}], "policy": {"policy_id": "policy/one", "rule_weight": 0.4, "model_weight": 0.6, "required_criteria": ["hook"]}}, "semantic_report"),
    }

    for node_type, (inputs, output_name) in nodes.items():
        entry = registry.allowed[node_type]
        node = {"type": node_type, "version": entry[0], "outputs": list(entry[1])}
        produced = registry.execute(node, _context(tmp_path, inputs))
        assert set(produced) == {output_name}
        assert produced[output_name]["artifact_ref"].startswith("artifacts/")
        assert str(tmp_path) in produced[output_name]["local_path"]
