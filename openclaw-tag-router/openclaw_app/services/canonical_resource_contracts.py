from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


TENANT_PROJECTION_FIELD = "租户ID"


@dataclass(frozen=True)
class CanonicalResourceContract:
    resource_type: str
    canonical_id_name: str
    store: str
    feishu_table: str | None = None
    tenant_projection_field: str | None = None


_CONTRACTS = {
    "media_web.task": CanonicalResourceContract("media_web.task", "task_id", "media_web_tasks"),
    "media_web.upload": CanonicalResourceContract("media_web.upload", "upload_id", "media_web_uploads"),
    "media_vault.artifact": CanonicalResourceContract("media_vault.artifact", "artifact_uri", "media_vault_v2"),
    "media.source_asset": CanonicalResourceContract("media.source_asset", "asset_id", "Media OS", "02A_SourceAssets_素材源", TENANT_PROJECTION_FIELD),
    "media.material_deconstruction": CanonicalResourceContract("media.material_deconstruction", "deconstruction_id", "Media OS", "02B_MaterialDeconstructions_素材拆解", TENANT_PROJECTION_FIELD),
    "media.creative_pattern": CanonicalResourceContract("media.creative_pattern", "pattern_id", "Media OS", "02C_CreativePatterns_创作模式", TENANT_PROJECTION_FIELD),
    "media.creation_run": CanonicalResourceContract("media.creation_run", "run_id", "Media OS", "03_CreationRuns_创作运行", TENANT_PROJECTION_FIELD),
    "media.post_review": CanonicalResourceContract("media.post_review", "post_id", "Media OS", "04_PostReviews_发布复盘", TENANT_PROJECTION_FIELD),
    "media.business_account": CanonicalResourceContract("media.business_account", "business_account_id", "Media OS", "05A_BusinessAccounts_商务账号", TENANT_PROJECTION_FIELD),
    "media.business_opportunity": CanonicalResourceContract("media.business_opportunity", "opportunity_id", "Media OS", "05B_BusinessOpportunities_商务机会", TENANT_PROJECTION_FIELD),
    "media.creator_profile": CanonicalResourceContract("media.creator_profile", "creator_profile_id", "Media OS", "06_CreatorProfiles_达人账号档案", TENANT_PROJECTION_FIELD),
    "media.material_usage": CanonicalResourceContract("media.material_usage", "usage_id", "Media OS", "R01_MaterialUsage_素材使用记录", TENANT_PROJECTION_FIELD),
    "media.decision_trace": CanonicalResourceContract("media.decision_trace", "trace_id", "Media OS", "R02_DecisionTrace_决策轨迹", TENANT_PROJECTION_FIELD),
    "media.track_creator_membership": CanonicalResourceContract("media.track_creator_membership", "membership_id", "Media OS", "R03_TrackCreatorMembership_赛道博主关系", TENANT_PROJECTION_FIELD),
    "media.metric_snapshot": CanonicalResourceContract("media.metric_snapshot", "snapshot_id", "Media OS", "H01_MetricSnapshot_作品指标快照", TENANT_PROJECTION_FIELD),
    "media.account_metric_snapshot": CanonicalResourceContract("media.account_metric_snapshot", "snapshot_id", "Media OS", "H02_AccountMetricSnapshot_账号指标快照", TENANT_PROJECTION_FIELD),
    "media.growth_summary": CanonicalResourceContract("media.growth_summary", "artifact_id", "Media OS", "H03_GrowthSummary_增长摘要", TENANT_PROJECTION_FIELD),
    "media.commercial_delivery": CanonicalResourceContract("media.commercial_delivery", "delivery_id", "Media OS", "COM01_CommercialDelivery_商单交付", TENANT_PROJECTION_FIELD),
    "content_os.project": CanonicalResourceContract("content_os.project", "project_id", "Content OS", "00_Projects_项目看板", TENANT_PROJECTION_FIELD),
    "content_os.task": CanonicalResourceContract("content_os.task", "task_id", "Content OS", "01_Tasks_任务队列", TENANT_PROJECTION_FIELD),
    "content_os.post_review": CanonicalResourceContract("content_os.post_review", "post_review_id", "Content OS", "02_PostsReviews_发布复盘", TENANT_PROJECTION_FIELD),
}

CANONICAL_RESOURCE_CONTRACTS: Mapping[str, CanonicalResourceContract] = MappingProxyType(_CONTRACTS)

CONTENT_OS_TASK_OWNER_CONTRACT = MappingProxyType(
    {
        "table": "01_Tasks_任务队列",
        "resource_type": "content_os.task",
        "canonical_id": "task_id",
        "tenant_projection_field": TENANT_PROJECTION_FIELD,
        "tenant_projection_type": 1,
        "authorization_source": "resource_owner_registry",
        "projection_direction": "canonical_owner_to_feishu_only",
        "activation": "pending_live_schema_readback",
    }
)

CONTENT_OS_POST_REVIEW_OWNER_CONTRACT = MappingProxyType(
    {
        "table": "02_PostsReviews_发布复盘",
        "resource_type": "content_os.post_review",
        "canonical_id": "post_review_id",
        "tenant_projection_field": TENANT_PROJECTION_FIELD,
        "tenant_projection_type": 1,
        "authorization_source": "resource_owner_registry",
        "projection_direction": "canonical_owner_to_feishu_only",
        "activation": "pending_live_schema_readback",
    }
)
