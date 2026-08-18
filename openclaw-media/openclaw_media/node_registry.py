"""The only production node dispatch table for the installed media catalog."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from .analysis import AnalysisModelOutput, SourceFact, TechnicalCheck, build_analysis_report
from .catalog import CatalogError, InstalledCatalog
from .core.extraction import extract_media_evidence
from .core.handoff import HandoffClipDescriptor, SubtitleCue, plan_handoff
from .core.media import MediaFile, scan_media
from .core.organization import plan_media_organization
from .core.revision import (
    ChangeReceipt,
    Revision,
    RevisionArtifact,
    RevisionChange,
    RevisionConfirmation,
    RevisionResult,
    create_revision,
)
from .core.review import (
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
from .core.storyboard import EDLEntry, MaterialDescriptor, ShotRequest, StoryboardEntry, plan_storyboard
from .core.timeline import KdenliveEnvironment, TimelineMediaDescriptor, build_timeline
from .provider_adapter import ProviderAdapter, ProviderAdapterError, VisionImage
from .render import RenderMediaDescriptor, plan_render


class NodeExecutionError(RuntimeError):
    """Stable node failure that is safe to expose in a run outcome."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SemanticModelScores(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    scores: dict[str, float] = Field(default_factory=dict)


NodeHandler = Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Mapping[str, Any]]]


def _json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    except (TypeError, ValueError) as exc:
        raise NodeExecutionError("invalid_node_input") from exc


def _ref(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "://" in value:
        raise NodeExecutionError("invalid_input_ref")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise NodeExecutionError("invalid_input_ref")
    return path.as_posix()


def _root(context: Mapping[str, Any]) -> Path:
    value = context.get("workspace_root")
    if not isinstance(value, Path):
        raise NodeExecutionError("workspace_unavailable")
    return value


def _inputs(context: Mapping[str, Any]) -> Mapping[str, Any]:
    value = context.get("inputs")
    if not isinstance(value, Mapping):
        raise NodeExecutionError("invalid_inputs")
    return value


def _scan(context: Mapping[str, Any]):
    ref = _ref(_inputs(context).get("workspace_ref"))
    try:
        return scan_media(_root(context) / ref)
    except (OSError, ValueError) as exc:
        raise NodeExecutionError("media_scan_failed") from exc


def _provider(context: Mapping[str, Any]) -> ProviderAdapter:
    value = context.get("provider")
    if not isinstance(value, ProviderAdapter):
        raise ProviderAdapterError("provider_unavailable")
    return value


def _artifact(context: Mapping[str, Any], name: str, value: Any, mime_type: str) -> Mapping[str, Any]:
    run_ref = str(context.get("run_ref", "run"))
    identity = hashlib.sha256(f"{run_ref}:{name}".encode()).hexdigest()
    relative = f"artifacts/{identity}/{name}.json"
    root = _root(context)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(value)
    path.write_bytes(payload)
    return {
        "local_path": str(path),
        "artifact_ref": relative,
        "mime_type": mime_type,
        "size_bytes": len(payload),
        "cloud_bytes": 0,
    }


def _scan_payload(scan: Any) -> dict[str, Any]:
    return scan.to_dict()


def _project_prepare(node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    scan = _scan(context)
    facts = tuple(
        SourceFact(fact_id=f"media-{index:04d}", statement=f"media file {item.ref}", evidence_refs=(item.ref,))
        for index, item in enumerate(scan.files, start=1)
    )
    checks = tuple(
        TechnicalCheck(
            check_id=f"probe-{index:04d}",
            status="pass" if item.probe is not None and item.probe.status == "ok" else "fail",
            detail_code="probe_ok" if item.probe is not None and item.probe.status == "ok" else "probe_failed",
            fact_ids=(f"media-{index:04d}",),
        )
        for index, item in enumerate(scan.files, start=1)
    )
    if not facts:
        raise NodeExecutionError("no_media")
    model = _provider(context).complete_structured(
        "Return bounded media project judgments for the supplied source facts.", AnalysisModelOutput
    )
    outcome = build_analysis_report(facts, model, checks)
    if outcome.report is None:
        raise NodeExecutionError(outcome.code)
    return {"project_overview": _artifact(context, "project_overview", {"scan": _scan_payload(scan), "analysis": outcome.report.model_dump(mode="json")}, "application/json")}


def _material_from_file(item: MediaFile, tags: tuple[str, ...] = ()) -> MaterialDescriptor:
    duration = item.probe.duration_seconds if item.probe and item.probe.duration_seconds else 1.0
    return MaterialDescriptor(item.ref, item.kind, item.sha256, duration, tags)


def _material_organize(node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    plan = plan_media_organization(_scan(context).files)
    return {"organization_plan": _artifact(context, "organization_plan", plan.to_dict(), "application/json")}


def _material_match(node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    values = _inputs(context)
    scan = _scan(context)
    tags_by_ref = values.get("material_tags", {})
    if not isinstance(tags_by_ref, Mapping):
        raise NodeExecutionError("invalid_node_input")
    materials = tuple(
        _material_from_file(item, tuple(tags_by_ref.get(item.ref, ())))
        for item in scan.files
        if item.kind in {"video", "image", "audio"}
    )
    raw_shots = values.get("shots")
    if not isinstance(raw_shots, list):
        raise NodeExecutionError("shots_required")
    try:
        shots = tuple(
            ShotRequest(
                **{
                    **item,
                    "required_tags": tuple(item.get("required_tags", ())),
                    "preferred_tags": tuple(item.get("preferred_tags", ())),
                    "accepted_kinds": tuple(item.get("accepted_kinds", ("video", "image"))),
                }
            )
            for item in raw_shots
            if isinstance(item, Mapping)
        )
    except (TypeError, ValueError) as exc:
        raise NodeExecutionError("invalid_shots") from exc
    _provider(context).complete_structured(
        'Return exactly this value: {"judgments":[],"unknowns":[]}.',
        AnalysisModelOutput,
    )
    plan = plan_storyboard(materials, shots)
    if plan.status == "failed":
        raise NodeExecutionError("storyboard_rejected")
    return {"edit_decision_list": _artifact(context, "edit_decision_list", plan.to_dict(), "application/json")}


def _dataclass_items(values: Any, cls: type[Any]) -> tuple[Any, ...]:
    if not isinstance(values, list):
        raise NodeExecutionError("invalid_node_input")
    try:
        return tuple(cls(**item) for item in values if isinstance(item, Mapping))
    except (TypeError, ValueError) as exc:
        raise NodeExecutionError("invalid_node_input") from exc


def _handoff(node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    values = _inputs(context)
    clips = _dataclass_items(values.get("clips"), HandoffClipDescriptor)
    storyboard = _dataclass_items(values.get("storyboard"), StoryboardEntry)
    edl = _dataclass_items(values.get("edl"), EDLEntry)
    subtitles = _dataclass_items(values.get("subtitles", []), SubtitleCue)
    plan = plan_handoff(clips, storyboard, edl, subtitles)
    if plan.status != "ok":
        raise NodeExecutionError("handoff_rejected")
    return {"handoff_manifest": _artifact(context, "handoff_manifest", plan.to_dict(), "application/json")}


def _timeline(node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    values = _inputs(context)
    edl = _dataclass_items(values.get("edl"), EDLEntry)
    media = _dataclass_items(values.get("media"), TimelineMediaDescriptor)
    plan = build_timeline(edl, media, kdenlive=KdenliveEnvironment(False))
    if plan.project_otio is None:
        raise NodeExecutionError("timeline_rejected")
    render_request = values.get("render_request")
    if render_request is not None:
        if not isinstance(render_request, Mapping):
            raise NodeExecutionError("invalid_render_request")
        try:
            revision_data = dict(render_request["revision"])
            revision_data["artifacts"] = _dataclass_items(revision_data.get("artifacts"), RevisionArtifact)
            revision = Revision(**revision_data)
            receipt = ChangeReceipt(**dict(render_request["receipt"]))
            revision_result = RevisionResult("ok", revision, receipt, None, ())
            render_media = tuple(RenderMediaDescriptor(**item) for item in render_request["media"] if isinstance(item, Mapping))
            render_plan = plan_render(revision_result, plan.project_otio, render_media)
        except (KeyError, TypeError, ValueError) as exc:
            raise NodeExecutionError("invalid_render_request") from exc
        if render_plan.status != "ok":
            raise NodeExecutionError("render_plan_rejected")
    return {"timeline": _artifact(context, "timeline", plan.project_otio, "application/vnd.otio+json")}


def _revise(node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    values = _inputs(context)
    try:
        base_data = dict(values["base_revision"])
        base_data["artifacts"] = _dataclass_items(base_data.get("artifacts"), RevisionArtifact)
        base = Revision(**base_data)
        confirmation = RevisionConfirmation(**values["confirmation"])
        changes = _dataclass_items(values.get("changes"), RevisionChange)
    except (KeyError, TypeError, ValueError) as exc:
        raise NodeExecutionError("invalid_revision") from exc
    result = create_revision(base, changes, confirmation)
    if result.status != "ok":
        raise NodeExecutionError("revision_rejected")
    return {"change_receipt": _artifact(context, "change_receipt", result.to_dict(), "application/json")}


def _output_review(node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    values = _inputs(context)
    versions: list[OutputVersionDescriptor] = []
    for item in values.get("versions", []):
        if not isinstance(item, Mapping):
            raise NodeExecutionError("invalid_review_input")
        version = dict(item)
        version["metrics"] = tuple(OutputMetric(**metric) for metric in version.get("metrics", []) if isinstance(metric, Mapping))
        version["dimensions"] = tuple(OutputDimension(**dimension) for dimension in version.get("dimensions", []) if isinstance(dimension, Mapping))
        versions.append(OutputVersionDescriptor(**version))
    weights = _dataclass_items(values.get("weights", []), ReviewWeight)
    result = review_output(versions, platform=_ref(values.get("platform")), weights=weights, required_metrics=values.get("required_metrics", []))
    if result.status != "ok":
        raise NodeExecutionError("output_review_rejected")
    return {"review_report": _artifact(context, "review_report", result.to_dict(), "application/yaml")}


def _rhythm_review(node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    values = _inputs(context)
    try:
        profile = RhythmProfile(**values["profile"])
        audio = _dataclass_items(values.get("audio_events"), RhythmEvent)
        visual = _dataclass_items(values.get("visual_events"), RhythmEvent)
        duration = float(values["duration_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NodeExecutionError("invalid_rhythm_input") from exc
    result = review_rhythm(_ref(values["media_ref"]), duration, audio, visual, profile)
    if result.status != "ok":
        raise NodeExecutionError("rhythm_review_rejected")
    return {"rhythm_report": _artifact(context, "rhythm_report", result.to_dict(), "application/json")}


def _semantic_review(node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    values = _inputs(context)
    image_ref = _ref(values.get("image_ref", values.get("contact_sheet_ref")))
    image_path = _root(context) / image_ref
    try:
        image = image_path.read_bytes()
    except OSError as exc:
        raise NodeExecutionError("image_unavailable") from exc
    if not image:
        raise NodeExecutionError("image_unavailable")
    suffix = image_path.suffix.lower()
    media_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/webp" if suffix == ".webp" else "image/png" if suffix == ".png" else None
    if media_type is None:
        raise NodeExecutionError("unsupported_image")
    _provider(context).complete_vision(
        "Inspect this contact sheet for bounded semantic review evidence.",
        (VisionImage(media_type=media_type, data=image),),
    )
    model = _provider(context).complete_structured(
        "Return one bounded score from 0 to 100 for each semantic criterion.", SemanticModelScores
    )
    try:
        criteria = [SemanticCriterion(**item) for item in values["criteria"]]
        policy = SemanticPolicy(**values["policy"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NodeExecutionError("invalid_semantic_input") from exc
    scores = model.value.scores
    adjusted = [
        SemanticCriterion(item.criterion_id, item.rule_score, scores.get(item.criterion_id, item.model_score), item.model_confidence)
        for item in criteria
    ]
    result = review_semantic(_ref(values.get("contact_sheet_ref")), adjusted, policy)
    if result.status != "ok":
        raise NodeExecutionError("semantic_review_rejected")
    return {"semantic_report": _artifact(context, "semantic_report", result.to_dict(), "application/json")}


_HANDLERS: dict[str, NodeHandler] = {
    "project.prepare": _project_prepare,
    "material.organize": _material_organize,
    "material.match": _material_match,
    "edit.handoff": _handoff,
    "edit.timeline": _timeline,
    "edit.revise": _revise,
    "output.review": _output_review,
    "rhythm.review": _rhythm_review,
    "semantic.review": _semantic_review,
}


class NodeRegistry:
    """A catalog-derived, immutable allowlist of node implementations."""

    def __init__(self, catalog: InstalledCatalog, provider: ProviderAdapter | None = None) -> None:
        entries = catalog.manifest.get("node_registry")
        if not isinstance(entries, list) or not entries:
            raise CatalogError("node registry missing")
        allowed: dict[str, tuple[str, tuple[str, ...]]] = {}
        for entry in entries:
            node_type = entry.get("node_type")
            version = entry.get("version")
            outputs = entry.get("outputs")
            if node_type not in _HANDLERS or not isinstance(version, str) or not isinstance(outputs, list):
                raise CatalogError("node registry drift")
            allowed[node_type] = (version, tuple(outputs))
        if set(allowed) != set(_HANDLERS):
            raise CatalogError("node registry drift")
        self.catalog = catalog
        self.provider = provider
        self.allowed = allowed

    def execute(self, node: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
        node_type = node.get("type")
        entry = self.allowed.get(node_type)
        if entry is None or node.get("version") != entry[0] or tuple(node.get("outputs", ())) != entry[1]:
            raise NodeExecutionError("unknown_node")
        child_context = dict(context)
        child_context["provider"] = self.provider
        try:
            produced = _HANDLERS[node_type](node, child_context)
        except ProviderAdapterError:
            raise
        except NodeExecutionError:
            raise
        except (OSError, TypeError, ValueError, KeyError) as exc:
            raise NodeExecutionError("node_failed") from exc
        if not isinstance(produced, Mapping):
            raise NodeExecutionError("invalid_node_output")
        return produced


__all__ = ["NodeExecutionError", "NodeRegistry", "SemanticModelScores"]
