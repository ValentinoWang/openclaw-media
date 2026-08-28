from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class GrowthCapabilitySpec:
    canonical_capability_id: str
    produces: tuple[str, ...] = field(default_factory=tuple)
    consumes: tuple[str, ...] = field(default_factory=tuple)
    writes_to: tuple[str, ...] = field(default_factory=tuple)
    planned_writes_to: tuple[str, ...] = field(default_factory=tuple)
    write_scope: str = "local_runner"
    implementation_status: str = "not_implemented"
    lifecycle_layer: str = "Operate"
    risk_level: str = "low"
    source_system: str = "media"
    frontend_group: str = "能力目录"
    default_mode: str = "reply_and_persist"
    ssot_refs: tuple[str, ...] = field(default_factory=tuple)
    creator_field_mappings: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)

    @property
    def implemented(self) -> bool:
        return self.implementation_status == "implemented"


CAPABILITY_SPECS: dict[str, GrowthCapabilitySpec] = {
    "source_asset_intake": GrowthCapabilitySpec(
        canonical_capability_id="source_asset_intake",
        produces=("SourceAsset",),
        writes_to=("media_vault/tenants/<tenant_id>/source_assets",),
        implementation_status="implemented",
        lifecycle_layer="Collect",
        frontend_group="素材 / 灵感池",
        ssot_refs=("media://tenants/<tenant_id>/source_assets",),
    ),
    "raw_expression_capture": GrowthCapabilitySpec(
        canonical_capability_id="raw_expression_capture",
        produces=("SourceAsset",),
        planned_writes_to=("media_vault/tenants/<tenant_id>/source_assets",),
        write_scope="planned",
        lifecycle_layer="Collect",
        frontend_group="素材 / 灵感池",
    ),
    "external_research_brief": GrowthCapabilitySpec(
        canonical_capability_id="external_research_brief",
        produces=("ExternalResearchBrief",),
        consumes=("ResearchQuestion", "AccountTrackStrategy", "SourceAsset"),
        writes_to=("media_vault/tenants/<tenant_id>/research_briefs",),
        implementation_status="implemented",
        lifecycle_layer="Decide",
        risk_level="medium",
        frontend_group="选题与决策",
        ssot_refs=("AccountTrackStrategy", "TrackRegistry", "platform_mechanisms", "source_evidence"),
    ),
    "commercial_brief": GrowthCapabilitySpec(
        canonical_capability_id="commercial_brief",
        produces=("CommercialBrief",),
        consumes=("BrandBrief", "RawText", "SourceAsset"),
        writes_to=("media_vault/tenants/<tenant_id>/commercial_briefs",),
        implementation_status="implemented",
        lifecycle_layer="Decide",
        risk_level="medium",
        frontend_group="商务 / Brief",
        ssot_refs=("BrandBrief", "media://tenants/<tenant_id>/commercial_briefs", "shooting_execution_plan"),
    ),
    "creation_decision_brief": GrowthCapabilitySpec(
        canonical_capability_id="creation_decision_brief",
        produces=("DecisionBrief",),
        consumes=("SourceAsset", "ExternalResearchBrief", "CommercialBrief", "ReviewSignal"),
        writes_to=("media_vault/tenants/<tenant_id>/decision_briefs",),
        implementation_status="implemented",
        lifecycle_layer="Decide",
        frontend_group="选题与决策",
        ssot_refs=(
            "SourceAsset",
            "ExternalResearchBrief",
            "CommercialBrief",
            "ReviewSignal",
            "media://tenants/<tenant_id>/review_signals",
            "selfmedia.context.media_context.record_review_memory",
        ),
        creator_field_mappings=(
            (
                "topic_candidates[].pain_point",
                ("topic_candidates[].pain_point", "topic_candidates[].audience_pain"),
            ),
        ),
    ),
    "creator_brief_to_draft": GrowthCapabilitySpec(
        canonical_capability_id="creator_brief_to_draft",
        produces=("DraftPackage",),
        consumes=("DecisionBrief", "SourceAsset"),
        planned_writes_to=("media_vault/tenants/<tenant_id>/creation_runs",),
        write_scope="planned",
        lifecycle_layer="Create",
        frontend_group="创作运行",
    ),
    "shooting_execution_plan": GrowthCapabilitySpec(
        canonical_capability_id="shooting_execution_plan",
        produces=("DraftPackage",),
        consumes=("CommercialBrief", "DecisionBrief", "DraftPackage"),
        writes_to=("03_CreationRuns_创作运行 summary", "Feishu Docx shooting execution document"),
        write_scope="external_handler",
        implementation_status="external",
        lifecycle_layer="Create",
        frontend_group="创作运行",
        ssot_refs=(
            "openclaw-tag-router.handle_shooting_execution",
            "selfmedia.creation.shooting_execution.handle_shooting_execution_command",
            "03_CreationRuns_创作运行",
        ),
    ),
    "style_polish_run": GrowthCapabilitySpec(
        canonical_capability_id="style_polish_run",
        produces=("StylePolishResult", "OutputVariant"),
        consumes=("RawText", "DraftPackage", "PublishingPack"),
        writes_to=("media_vault/tenants/<tenant_id>/style_polish_runs",),
        write_scope="external_handler",
        implementation_status="external",
        lifecycle_layer="Polish",
        frontend_group="表达优化",
        ssot_refs=("openclaw-tag-router.handle_style_polish", "CreatorProfile", "media_memory", "config/platform_mechanisms", "CreativePattern", "recent_reviews"),
    ),
    "creation_checklist_lookup": GrowthCapabilitySpec(
        canonical_capability_id="creation_checklist_lookup",
        produces=("VerificationReport",),
        writes_to=("none",),
        write_scope="external_handler",
        implementation_status="external",
        lifecycle_layer="Verify",
        frontend_group="发布前 Gate",
        default_mode="reply_only",
        ssot_refs=("openclaw-tag-router.handle_创作检查",),
    ),
    "work_acceptance_report": GrowthCapabilitySpec(
        canonical_capability_id="work_acceptance_report",
        produces=("VerificationReport",),
        consumes=("DraftPackage", "RawText"),
        writes_to=("media_vault/tenants/<tenant_id>/verification_reports",),
        write_scope="external_handler",
        implementation_status="external",
        lifecycle_layer="Verify",
        frontend_group="发布前 Gate",
        ssot_refs=("openclaw-tag-router.handle_作品验收",),
    ),
    "media_growth_review": GrowthCapabilitySpec(
        canonical_capability_id="media_growth_review",
        produces=("ReviewDecision",),
        consumes=("MediaGrowthArtifact",),
        writes_to=("media_vault/tenants/<tenant_id>/*/result.json",),
        implementation_status="implemented",
        lifecycle_layer="Verify",
        risk_level="medium",
        frontend_group="发布前 Gate",
        default_mode="persist_and_update_status",
        ssot_refs=("media://tenants/<tenant_id>/*/result.json", "selfmedia.growth.review_growth_artifact"),
    ),
    "publish_readiness_gate": GrowthCapabilitySpec(
        canonical_capability_id="publish_readiness_gate",
        produces=("PublishReadinessGate",),
        consumes=("PublishingPack", "DraftPackage", "CreationRun"),
        writes_to=("media_vault/tenants/<tenant_id>/verification_reports",),
        implementation_status="implemented",
        lifecycle_layer="Verify",
        risk_level="medium",
        frontend_group="发布前 Gate",
        default_mode="reply_and_persist",
        ssot_refs=("PublishReadinessGate", "media://tenants/<tenant_id>/verification_reports"),
    ),
    "publishing_pack_build": GrowthCapabilitySpec(
        canonical_capability_id="publishing_pack_build",
        produces=("PublishingPack", "PublishReadinessGate"),
        consumes=("DraftPackage", "StylePolishResult", "VerificationReport"),
        writes_to=("media_vault/tenants/<tenant_id>/publishing_packs",),
        implementation_status="implemented",
        lifecycle_layer="Publish",
        risk_level="medium",
        frontend_group="发布准备",
        ssot_refs=("DraftPackage", "StylePolishResult", "media://tenants/<tenant_id>/creation_runs", "platform_mechanisms", "media_vault_v2"),
        creator_field_mappings=(
            ("title_1", ("title",)),
            ("cover_text", ("cover_text",)),
            ("body_copy", ("caption",)),
            ("hashtags", ("hashtags",)),
            ("pinned_comment", ("comment_seed",)),
            ("comment_prompt", ("comment_seed",)),
            ("first_hour_action", ("publish_checklist",)),
        ),
    ),
    "post_review_signal": GrowthCapabilitySpec(
        canonical_capability_id="post_review_signal",
        produces=("ReviewSignal",),
        writes_to=("media_vault/tenants/<tenant_id>/review_signals",),
        implementation_status="implemented",
        lifecycle_layer="Learn",
        frontend_group="数据复盘",
        ssot_refs=(
            "ReviewSignal",
            "media://tenants/<tenant_id>/review_signals",
            "selfmedia.context.media_context.record_review_memory",
        ),
    ),
    "account_track_strategy": GrowthCapabilitySpec(
        canonical_capability_id="account_track_strategy",
        produces=("AccountTrackStrategy",),
        consumes=("OwnedMediaAccount", "TrackRegistry", "ReviewSignal"),
        planned_writes_to=("media_vault/tenants/<tenant_id>/account_track_strategy_runs",),
        write_scope="planned",
        lifecycle_layer="Strategy",
        frontend_group="选题与决策",
        ssot_refs=("OwnedMediaAccount", "TrackRegistry", "recent_reviews", "media_memory"),
    ),
    "owned_media_account_lookup": GrowthCapabilitySpec(
        canonical_capability_id="owned_media_account_lookup",
        produces=("OwnedMediaAccount",),
        planned_writes_to=("OwnedMediaAccount",),
        write_scope="planned",
        lifecycle_layer="Entity",
        frontend_group="账号内容地图",
        ssot_refs=("OwnedMediaAccount", "media_memory"),
    ),
    "track_registry_lookup": GrowthCapabilitySpec(
        canonical_capability_id="track_registry_lookup",
        produces=("TrackRegistry",),
        writes_to=("TrackRegistry",),
        implementation_status="implemented",
        lifecycle_layer="Entity",
        risk_level="medium",
        frontend_group="账号内容地图",
        ssot_refs=("TrackRegistry",),
    ),
    "track_creator_membership_query": GrowthCapabilitySpec(
        canonical_capability_id="track_creator_membership_query",
        produces=("TrackCreatorMembership",),
        consumes=("TrackRegistry", "CreatorProfile"),
        writes_to=("TrackCreatorMembership",),
        implementation_status="implemented",
        lifecycle_layer="Entity",
        risk_level="medium",
        frontend_group="账号内容地图",
        ssot_refs=("TrackRegistry", "CreatorProfile"),
    ),
}

ARTIFACT_CONSUMERS: dict[str, set[str]] = {
    "SourceAsset": {"commercial_brief", "creation_decision_brief", "creator_brief_to_draft", "external_research_brief", "media_growth_review"},
    "ExternalResearchBrief": {"creation_decision_brief", "media_growth_review"},
    "CommercialBrief": {"creation_decision_brief", "shooting_execution_plan", "media_growth_review"},
    "DecisionBrief": {"creator_brief_to_draft", "shooting_execution_plan", "media_growth_review"},
    "DraftPackage": {"style_polish_run", "work_acceptance_report", "publishing_pack_build", "publish_readiness_gate", "media_growth_review"},
    "StylePolishResult": {"publishing_pack_build", "media_growth_review"},
    "VerificationReport": {"publishing_pack_build", "media_growth_review"},
    "PublishingPack": {"style_polish_run", "publish_readiness_gate", "media_growth_review"},
    "ReviewSignal": {"creation_decision_brief", "media_growth_review"},
    "MediaGrowthArtifact": {"media_growth_review"},
}

PRESET_FLOWS: dict[str, tuple[str, ...]] = {
    "quick_polish": ("style_polish_run",),
    "asset_to_topic": ("source_asset_intake", "creation_decision_brief"),
    "asset_to_draft": ("source_asset_intake", "creation_decision_brief", "creator_brief_to_draft"),
    "draft_to_publish_pack": ("style_polish_run", "publishing_pack_build", "publish_readiness_gate"),
    "metrics_to_next_topics": ("post_review_signal", "creation_decision_brief"),
    "activity_brief_to_shooting": (
        "source_asset_intake",
        "creation_decision_brief",
        "shooting_execution_plan",
        "publishing_pack_build",
    ),
}

MEDIA_GROWTH_LABEL_CAPABILITIES: dict[str, str] = {
    "策略": "account_track_strategy",
    "Brief": "commercial_brief",
    "素材": "source_asset_intake",
    "调研": "external_research_brief",
    "选题": "creation_decision_brief",
    "拍摄": "shooting_execution_plan",
    "发布包": "publishing_pack_build",
    "复核": "media_growth_review",
    "复盘": "post_review_signal",
    "账号": "owned_media_account_lookup",
    "赛道": "track_registry_lookup",
    "赛道-关系": "track_creator_membership_query",
}


def get_capability_spec(capability_id: str) -> GrowthCapabilitySpec | None:
    return CAPABILITY_SPECS.get(str(capability_id or "").strip())


def require_capability_spec(capability_id: str) -> GrowthCapabilitySpec:
    capability = str(capability_id or "").strip()
    spec = get_capability_spec(capability)
    if spec is None:
        raise KeyError(f"unknown Mediaclaw capability: {capability}")
    return spec


def capability_produces(capability_id: str) -> tuple[str, ...]:
    spec = get_capability_spec(capability_id)
    return spec.produces if spec else ()


def capability_consumes(capability_id: str) -> tuple[str, ...]:
    spec = get_capability_spec(capability_id)
    return spec.consumes if spec else ()


def capability_writes_to(capability_id: str) -> tuple[str, ...]:
    spec = get_capability_spec(capability_id)
    return spec.writes_to if spec else ()


def capability_creator_field_mappings(capability_id: str) -> dict[str, tuple[str, ...]]:
    spec = get_capability_spec(capability_id)
    if spec is None:
        return {}
    return {target: tuple(sources) for target, sources in spec.creator_field_mappings}


def capability_implementation_status(capability_id: str) -> str:
    spec = get_capability_spec(capability_id)
    return spec.implementation_status if spec else "unknown"


def is_capability_implemented(capability_id: str) -> bool:
    spec = get_capability_spec(capability_id)
    return bool(spec and spec.implemented)


def preset_flow_nodes(preset: str) -> tuple[str, ...]:
    return PRESET_FLOWS.get(str(preset or "").strip(), ())


def validate_artifact_consumption(capability_id: str, artifact_types: Iterable[str]) -> str:
    types = tuple(str(item).strip() for item in artifact_types if str(item).strip())
    if not types:
        return "passed"
    capability = str(capability_id or "").strip()
    for artifact_type in types:
        allowed = ARTIFACT_CONSUMERS.get(artifact_type)
        if allowed is None:
            return f"unknown artifact_type: {artifact_type}"
        if capability and capability not in allowed:
            return f"{artifact_type} cannot be consumed by {capability}"
    return "passed"
