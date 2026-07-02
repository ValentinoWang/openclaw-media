from __future__ import annotations

from common.social_runtime import feishu_bitable_refs, feishu_ensure_fields, load_default_env_files

from .retrieval import (
    resolve_activity_bitable_url,
    resolve_business_bitable_url,
    resolve_material_deconstructions_bitable_url,
    resolve_source_assets_bitable_url,
)

ACTIVITY_V1_FIELD_SPECS = {
    "平台名称": 4,
    "主话题": 1,
    "活动级别": 1,
    "活动开始时间": 5,
    "活动结束时间": 5,
    "冲榜日期": 5,
    "活动Brief": 1,
    "填写要点": 1,
    "参与方式": 1,
    "参与形式": 1,
    "提交要求": 1,
    "子话题方向": 1,
    "活动奖励": 1,
    "Brief链接": 15,
    "爆款示范链接": 15,
    "返稿链接": 15,
    "活动文档链接": 15,
}

def ensure_creation_source_schema(*, viral_url: str = "", activity_url: str = "", business_url: str = "") -> dict[str, str]:
    load_default_env_files()
    result: dict[str, str] = {}
    activity = resolve_activity_bitable_url(activity_url)
    if activity:
        app_token, table_id, token = feishu_bitable_refs(activity)
        feishu_ensure_fields(app_token, table_id, token, ACTIVITY_V1_FIELD_SPECS)
        result["activity"] = activity
    source_assets = resolve_source_assets_bitable_url()
    if source_assets:
        result["source_assets"] = source_assets
    material_deconstructions = resolve_material_deconstructions_bitable_url()
    if material_deconstructions:
        result["material_deconstructions"] = material_deconstructions
    business = resolve_business_bitable_url(business_url)
    if business:
        result["business"] = business
    return result
