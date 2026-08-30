from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

from common.social_runtime import now_iso as utc_now_iso
from common.url_text import extract_urls as _extract_urls


VISIBLE_STATUSES = {"active", "candidate", "published", "reviewed", "ready"}
VISIBLE_QUALITY_STATUSES = {"cleaned", "verified", "accepted"}
VISIBLE_VISIBILITIES = {"public", "ops"}


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def clean_list(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw = [values]
    else:
        raw = list(values)
    return tuple(item for item in (clean_text(value) for value in raw) if item)


def clean_mapping(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def extract_urls(text: str) -> tuple[str, ...]:
    return _extract_urls(text)


@dataclass(frozen=True)
class MediaArtifactBase:
    artifact_id: str
    artifact_type: str
    source_capability_id: str
    schema_version: str = "media_growth_artifact_v1"
    account_id: str = ""
    platform: str = ""
    track_id: str = ""
    source_trace: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    status: str = "candidate"
    visibility: str = "ops"
    quality_status: str = "pending_review"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    display_title: str = ""
    display_summary: str = ""
    artifact_uri: str = ""
    front_end_eligible: bool = True

    required_fields: ClassVar[tuple[str, ...]] = (
        "artifact_id",
        "artifact_type",
        "schema_version",
        "source_capability_id",
        "status",
        "visibility",
        "quality_status",
        "display_title",
        "display_summary",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", clean_text(self.artifact_id))
        object.__setattr__(self, "artifact_type", clean_text(self.artifact_type))
        object.__setattr__(self, "schema_version", clean_text(self.schema_version) or "media_growth_artifact_v1")
        object.__setattr__(self, "source_capability_id", clean_text(self.source_capability_id))
        object.__setattr__(self, "account_id", clean_text(self.account_id))
        object.__setattr__(self, "platform", clean_text(self.platform))
        object.__setattr__(self, "track_id", clean_text(self.track_id))
        object.__setattr__(self, "status", clean_text(self.status) or "candidate")
        object.__setattr__(self, "visibility", clean_text(self.visibility) or "ops")
        object.__setattr__(self, "quality_status", clean_text(self.quality_status) or "pending_review")
        object.__setattr__(self, "display_title", clean_text(self.display_title))
        object.__setattr__(self, "display_summary", clean_text(self.display_summary))
        object.__setattr__(self, "artifact_uri", clean_text(self.artifact_uri))
        object.__setattr__(self, "source_trace", tuple(dict(item) for item in self.source_trace))

    @property
    def is_frontend_visible(self) -> bool:
        return (
            self.front_end_eligible
            and self.visibility in VISIBLE_VISIBILITIES
            and self.status in VISIBLE_STATUSES
            and self.quality_status in VISIBLE_QUALITY_STATUSES
            and bool(self.display_title)
            and bool(self.display_summary)
        )

    def base_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "account_id": self.account_id,
            "platform": self.platform,
            "track_id": self.track_id,
            "source_capability_id": self.source_capability_id,
            "source_trace": [dict(item) for item in self.source_trace],
            "status": self.status,
            "visibility": self.visibility,
            "quality_status": self.quality_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "display_title": self.display_title,
            "display_summary": self.display_summary,
            "artifact_uri": self.artifact_uri,
            "front_end_eligible": self.front_end_eligible,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.base_dict()


@dataclass(frozen=True)
class SourceAsset(MediaArtifactBase):
    raw_text: str = ""
    urls: tuple[str, ...] = field(default_factory=tuple)
    source_kind: str = "user_text"
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    request_constraints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "raw_text", clean_text(self.raw_text))
        object.__setattr__(self, "urls", tuple(self.urls or extract_urls(self.raw_text)))
        object.__setattr__(self, "source_kind", clean_text(self.source_kind) or "user_text")
        object.__setattr__(self, "evidence_refs", clean_list(self.evidence_refs))
        object.__setattr__(self, "request_constraints", dict(self.request_constraints or {}))

    def to_dict(self) -> dict[str, Any]:
        payload = self.base_dict()
        payload.update(
            {
                "raw_text": self.raw_text,
                "urls": list(self.urls),
                "source_kind": self.source_kind,
                "evidence_refs": list(self.evidence_refs),
                "request_constraints": dict(self.request_constraints),
            }
        )
        return payload


@dataclass(frozen=True)
class ExternalResearchBrief(MediaArtifactBase):
    research_question: str = ""
    media_goal: str = ""
    audience_relevance: str = ""
    content_opportunity: str = ""
    usable_angles: tuple[str, ...] = field(default_factory=tuple)
    unusable_angles: tuple[str, ...] = field(default_factory=tuple)
    source_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    next_content_actions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "research_question", clean_text(self.research_question))
        object.__setattr__(self, "media_goal", clean_text(self.media_goal))
        object.__setattr__(self, "audience_relevance", clean_text(self.audience_relevance))
        object.__setattr__(self, "content_opportunity", clean_text(self.content_opportunity))
        object.__setattr__(self, "usable_angles", clean_list(self.usable_angles))
        object.__setattr__(self, "unusable_angles", clean_list(self.unusable_angles))
        object.__setattr__(self, "source_evidence", tuple(dict(item) for item in self.source_evidence))
        object.__setattr__(self, "risk_notes", clean_list(self.risk_notes))
        object.__setattr__(self, "next_content_actions", clean_list(self.next_content_actions))

    def to_dict(self) -> dict[str, Any]:
        payload = self.base_dict()
        payload.update(
            {
                "research_question": self.research_question,
                "media_goal": self.media_goal,
                "audience_relevance": self.audience_relevance,
                "content_opportunity": self.content_opportunity,
                "usable_angles": list(self.usable_angles),
                "unusable_angles": list(self.unusable_angles),
                "source_evidence": [dict(item) for item in self.source_evidence],
                "risk_notes": list(self.risk_notes),
                "next_content_actions": list(self.next_content_actions),
            }
        )
        return payload


@dataclass(frozen=True)
class CommercialBrief(MediaArtifactBase):
    brand: str = ""
    project_name: str = ""
    products: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    platforms: tuple[str, ...] = field(default_factory=tuple)
    content_format: str = ""
    duration_requirement: str = ""
    locations: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    required_brand_mentions: tuple[str, ...] = field(default_factory=tuple)
    must_cover: tuple[str, ...] = field(default_factory=tuple)
    narrative_direction: tuple[str, ...] = field(default_factory=tuple)
    interaction_design: tuple[str, ...] = field(default_factory=tuple)
    compliance_restrictions: tuple[str, ...] = field(default_factory=tuple)
    deliverables: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    technical_specs: dict[str, Any] = field(default_factory=dict)
    approval_requirements: tuple[str, ...] = field(default_factory=tuple)
    cleaned_brief: str = ""
    raw_brief: str = ""
    source_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    next_content_actions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "brand", clean_text(self.brand))
        object.__setattr__(self, "project_name", clean_text(self.project_name))
        object.__setattr__(self, "products", tuple(dict(item) for item in self.products if isinstance(item, dict)))
        object.__setattr__(self, "platforms", clean_list(self.platforms))
        object.__setattr__(self, "content_format", clean_text(self.content_format))
        object.__setattr__(self, "duration_requirement", clean_text(self.duration_requirement))
        object.__setattr__(self, "locations", tuple(dict(item) for item in self.locations if isinstance(item, dict)))
        object.__setattr__(self, "required_brand_mentions", clean_list(self.required_brand_mentions))
        object.__setattr__(self, "must_cover", clean_list(self.must_cover))
        object.__setattr__(self, "narrative_direction", clean_list(self.narrative_direction))
        object.__setattr__(self, "interaction_design", clean_list(self.interaction_design))
        object.__setattr__(self, "compliance_restrictions", clean_list(self.compliance_restrictions))
        object.__setattr__(self, "deliverables", tuple(dict(item) for item in self.deliverables if isinstance(item, dict)))
        object.__setattr__(self, "technical_specs", clean_mapping(self.technical_specs))
        object.__setattr__(self, "approval_requirements", clean_list(self.approval_requirements))
        object.__setattr__(self, "cleaned_brief", clean_text(self.cleaned_brief))
        object.__setattr__(self, "raw_brief", clean_text(self.raw_brief))
        object.__setattr__(self, "source_evidence", tuple(dict(item) for item in self.source_evidence if isinstance(item, dict)))
        object.__setattr__(self, "risk_notes", clean_list(self.risk_notes))
        object.__setattr__(self, "next_content_actions", clean_list(self.next_content_actions))

    def to_dict(self) -> dict[str, Any]:
        payload = self.base_dict()
        payload.update(
            {
                "brand": self.brand,
                "project_name": self.project_name,
                "products": [dict(item) for item in self.products],
                "platforms": list(self.platforms),
                "content_format": self.content_format,
                "duration_requirement": self.duration_requirement,
                "locations": [dict(item) for item in self.locations],
                "required_brand_mentions": list(self.required_brand_mentions),
                "must_cover": list(self.must_cover),
                "narrative_direction": list(self.narrative_direction),
                "interaction_design": list(self.interaction_design),
                "compliance_restrictions": list(self.compliance_restrictions),
                "deliverables": [dict(item) for item in self.deliverables],
                "technical_specs": dict(self.technical_specs),
                "approval_requirements": list(self.approval_requirements),
                "cleaned_brief": self.cleaned_brief,
                "raw_brief": self.raw_brief,
                "source_evidence": [dict(item) for item in self.source_evidence],
                "risk_notes": list(self.risk_notes),
                "next_content_actions": list(self.next_content_actions),
            }
        )
        return payload


@dataclass(frozen=True)
class DecisionBrief(MediaArtifactBase):
    topic_candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    decision_goal: str = ""
    recommended_next_capability_id: str = ""
    risk_or_missing_info: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "topic_candidates", tuple(dict(item) for item in self.topic_candidates))
        object.__setattr__(self, "decision_goal", clean_text(self.decision_goal))
        object.__setattr__(self, "recommended_next_capability_id", clean_text(self.recommended_next_capability_id))
        object.__setattr__(self, "risk_or_missing_info", clean_list(self.risk_or_missing_info))

    def to_dict(self) -> dict[str, Any]:
        payload = self.base_dict()
        payload.update(
            {
                "decision_goal": self.decision_goal,
                "topic_candidates": [dict(item) for item in self.topic_candidates],
                "recommended_next_capability_id": self.recommended_next_capability_id,
                "risk_or_missing_info": list(self.risk_or_missing_info),
            }
        )
        return payload


@dataclass(frozen=True)
class PublishingPack(MediaArtifactBase):
    title: str = ""
    cover_text: str = ""
    caption: str = ""
    hashtags: tuple[str, ...] = field(default_factory=tuple)
    comment_seed: str = ""
    publish_checklist: tuple[str, ...] = field(default_factory=tuple)
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    asset_refs: tuple[str, ...] = field(default_factory=tuple)
    automatic_publish_allowed: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "title", clean_text(self.title))
        object.__setattr__(self, "cover_text", clean_text(self.cover_text))
        object.__setattr__(self, "caption", clean_text(self.caption))
        object.__setattr__(self, "hashtags", clean_list(self.hashtags))
        object.__setattr__(self, "comment_seed", clean_text(self.comment_seed))
        object.__setattr__(self, "publish_checklist", clean_list(self.publish_checklist))
        object.__setattr__(self, "risk_notes", clean_list(self.risk_notes))
        object.__setattr__(self, "asset_refs", clean_list(self.asset_refs))
        object.__setattr__(self, "automatic_publish_allowed", False)

    def to_dict(self) -> dict[str, Any]:
        payload = self.base_dict()
        payload.update(
            {
                "title": self.title,
                "cover_text": self.cover_text,
                "caption": self.caption,
                "hashtags": list(self.hashtags),
                "comment_seed": self.comment_seed,
                "publish_checklist": list(self.publish_checklist),
                "risk_notes": list(self.risk_notes),
                "asset_refs": list(self.asset_refs),
                "automatic_publish_allowed": self.automatic_publish_allowed,
            }
        )
        return payload


@dataclass(frozen=True)
class PublishReadinessGate(MediaArtifactBase):
    gate_status: str = "needs_review"
    ready_to_publish: bool = False
    checklist: tuple[str, ...] = field(default_factory=tuple)
    blocking_issues: tuple[str, ...] = field(default_factory=tuple)
    source_refs: tuple[str, ...] = field(default_factory=tuple)
    automatic_publish_allowed: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        gate_status = clean_text(self.gate_status) or "needs_review"
        if gate_status not in {"ready", "needs_review", "blocked"}:
            gate_status = "needs_review"
        object.__setattr__(self, "gate_status", gate_status)
        object.__setattr__(self, "ready_to_publish", bool(self.ready_to_publish) and gate_status == "ready")
        object.__setattr__(self, "checklist", clean_list(self.checklist))
        object.__setattr__(self, "blocking_issues", clean_list(self.blocking_issues))
        object.__setattr__(self, "source_refs", clean_list(self.source_refs))
        object.__setattr__(self, "automatic_publish_allowed", False)

    def to_dict(self) -> dict[str, Any]:
        payload = self.base_dict()
        payload.update(
            {
                "gate_status": self.gate_status,
                "ready_to_publish": self.ready_to_publish,
                "checklist": list(self.checklist),
                "blocking_issues": list(self.blocking_issues),
                "source_refs": list(self.source_refs),
                "automatic_publish_allowed": self.automatic_publish_allowed,
            }
        )
        return payload


@dataclass(frozen=True)
class ReviewSignal(MediaArtifactBase):
    publish_id: str = ""
    metrics_summary: dict[str, Any] = field(default_factory=dict)
    single_fact: str = ""
    effective_patterns: tuple[str, ...] = field(default_factory=tuple)
    failure_reasons: tuple[str, ...] = field(default_factory=tuple)
    next_decision_inputs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "publish_id", clean_text(self.publish_id))
        object.__setattr__(self, "metrics_summary", clean_mapping(self.metrics_summary))
        object.__setattr__(self, "single_fact", clean_text(self.single_fact))
        object.__setattr__(self, "effective_patterns", clean_list(self.effective_patterns))
        object.__setattr__(self, "failure_reasons", clean_list(self.failure_reasons))
        object.__setattr__(self, "next_decision_inputs", clean_list(self.next_decision_inputs))

    def to_dict(self) -> dict[str, Any]:
        payload = self.base_dict()
        payload.update(
            {
                "publish_id": self.publish_id,
                "metrics_summary": dict(self.metrics_summary),
                "single_fact": self.single_fact,
                "effective_patterns": list(self.effective_patterns),
                "failure_reasons": list(self.failure_reasons),
                "next_decision_inputs": list(self.next_decision_inputs),
            }
        )
        return payload


@dataclass(frozen=True)
class OwnedMediaAccount:
    account_id: str
    platform: str
    account_name: str
    account_url: str = ""
    owner: str = ""
    status: str = "active"
    primary_positioning: str = ""
    target_audience: str = ""
    content_pillars: tuple[str, ...] = field(default_factory=tuple)
    persona_boundaries: tuple[str, ...] = field(default_factory=tuple)
    media_memory_uri: str = ""
    profile_doc_uri: str = ""
    last_profile_snapshot_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "platform": self.platform,
            "account_name": self.account_name,
            "account_url": self.account_url,
            "owner": self.owner,
            "status": self.status,
            "primary_positioning": self.primary_positioning,
            "target_audience": self.target_audience,
            "content_pillars": list(self.content_pillars),
            "persona_boundaries": list(self.persona_boundaries),
            "media_memory_uri": self.media_memory_uri,
            "profile_doc_uri": self.profile_doc_uri,
            "last_profile_snapshot_id": self.last_profile_snapshot_id,
        }


@dataclass(frozen=True)
class TrackRegistry:
    track_id: str
    track_name: str
    parent_track_id: str = ""
    description: str = ""
    platform_scope: tuple[str, ...] = field(default_factory=tuple)
    status: str = "active"
    alias_names: tuple[str, ...] = field(default_factory=tuple)

    allowed_statuses: ClassVar[set[str]] = {"active", "inactive"}

    def __post_init__(self) -> None:
        if self.status not in self.allowed_statuses:
            raise ValueError(f"TrackRegistry.status must be one of {sorted(self.allowed_statuses)}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "track_name": self.track_name,
            "parent_track_id": self.parent_track_id,
            "description": self.description,
            "platform_scope": list(self.platform_scope),
            "status": self.status,
            "alias_names": list(self.alias_names),
        }


@dataclass(frozen=True)
class AccountTrackStrategy:
    account_track_id: str
    account_id: str
    track_id: str
    platform: str = ""
    positioning_angle: str = ""
    target_audience: str = ""
    content_pillars: tuple[str, ...] = field(default_factory=tuple)
    usable_identity_points: tuple[str, ...] = field(default_factory=tuple)
    style_boundaries: tuple[str, ...] = field(default_factory=tuple)
    avoid_patterns: tuple[str, ...] = field(default_factory=tuple)
    priority: int = 0
    status: str = "active"
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    last_reviewed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_track_id": self.account_track_id,
            "account_id": self.account_id,
            "track_id": self.track_id,
            "platform": self.platform,
            "positioning_angle": self.positioning_angle,
            "target_audience": self.target_audience,
            "content_pillars": list(self.content_pillars),
            "usable_identity_points": list(self.usable_identity_points),
            "style_boundaries": list(self.style_boundaries),
            "avoid_patterns": list(self.avoid_patterns),
            "priority": self.priority,
            "status": self.status,
            "evidence_refs": list(self.evidence_refs),
            "last_reviewed_at": self.last_reviewed_at,
        }


@dataclass(frozen=True)
class TrackCreatorMembership:
    membership_id: str
    track_id: str
    creator_profile_id: str
    platform: str = ""
    author_id: str = ""
    account_name_snapshot: str = ""
    role: str = "同赛道观察"
    fit_score: int = 0
    fit_reason: str = ""
    content_use_case: str = ""
    business_use_case: str = ""
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    source_capability: str = ""
    status: str = "candidate"
    last_evaluated_at: str = ""
    metrics_snapshot_id: str = ""

    allowed_roles: ClassVar[set[str]] = {"标杆账号", "竞品账号", "合作候选", "素材来源", "同赛道观察", "风险账号"}
    allowed_statuses: ClassVar[set[str]] = {"candidate", "active", "rejected"}

    def __post_init__(self) -> None:
        if self.role not in self.allowed_roles:
            raise ValueError(f"TrackCreatorMembership.role must be one of {sorted(self.allowed_roles)}")
        try:
            fit_score = int(self.fit_score or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("TrackCreatorMembership.fit_score must be an integer from 0 to 100") from exc
        if not 0 <= fit_score <= 100:
            raise ValueError("TrackCreatorMembership.fit_score must be an integer from 0 to 100")
        if self.status not in self.allowed_statuses:
            raise ValueError(f"TrackCreatorMembership.status must be one of {sorted(self.allowed_statuses)}")
        object.__setattr__(self, "fit_score", fit_score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "membership_id": self.membership_id,
            "track_id": self.track_id,
            "creator_profile_id": self.creator_profile_id,
            "platform": self.platform,
            "author_id": self.author_id,
            "account_name_snapshot": self.account_name_snapshot,
            "role": self.role,
            "fit_score": self.fit_score,
            "fit_reason": self.fit_reason,
            "content_use_case": self.content_use_case,
            "business_use_case": self.business_use_case,
            "evidence_refs": list(self.evidence_refs),
            "source_capability": self.source_capability,
            "status": self.status,
            "last_evaluated_at": self.last_evaluated_at,
            "metrics_snapshot_id": self.metrics_snapshot_id,
        }


@dataclass(frozen=True)
class CreatorCohort(MediaArtifactBase):
    purpose: str = ""
    selected_creators: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    grouping: dict[str, Any] = field(default_factory=dict)
    fit_summary: str = ""
    created_from_run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = self.base_dict()
        payload.update(
            {
                "purpose": self.purpose,
                "selected_creators": [dict(item) for item in self.selected_creators],
                "grouping": dict(self.grouping),
                "fit_summary": self.fit_summary,
                "created_from_run_id": self.created_from_run_id,
            }
        )
        return payload


def assert_dashboard_eligible(artifact: MediaArtifactBase) -> None:
    missing = [field_name for field_name in MediaArtifactBase.required_fields if not getattr(artifact, field_name)]
    if missing:
        raise ValueError(f"artifact missing required display fields: {missing}")
    if not artifact.is_frontend_visible:
        raise ValueError("artifact is not frontend visible")
    for field_name in ("display_title", "display_summary"):
        value = clean_text(getattr(artifact, field_name))
        if _looks_like_default_or_route_params(value):
            raise ValueError(f"artifact {field_name} is not semantically display-ready")


def _looks_like_default_or_route_params(value: str) -> bool:
    text = clean_text(value)
    if not text:
        return True
    if TAG_ONLY_RE.fullmatch(text):
        return True
    cleaned = TAG_PREFIX_RE.sub("", text).strip()
    if not cleaned:
        return True
    route_param_matches = list(ROUTE_PARAM_RE.finditer(cleaned))
    if not route_param_matches:
        return False
    remaining = ROUTE_PARAM_RE.sub("", cleaned)
    return not re.sub(r"\s+", "", remaining)


TAG_PREFIX_RE = re.compile(r"^【[^】]+】")
TAG_ONLY_RE = re.compile(r"【[^】]+】")
ROUTE_PARAM_RE = re.compile(r"(?:(?<=^)|(?<=\s))[\w\u4e00-\u9fff]{1,16}\s*(?:[：=]|:(?!//))\s*\S+")
