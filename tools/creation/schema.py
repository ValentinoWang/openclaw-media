from __future__ import annotations

from common.social_runtime import feishu_bitable_refs, feishu_ensure_fields, load_default_env_files

from .retrieval import resolve_activity_bitable_url, resolve_business_bitable_url, resolve_viral_bitable_url


VIRAL_V1_FIELD_SPECS = {
    "内容类型": 1,
    "主题": 1,
    "更新时间": 5,
}

ACTIVITY_V1_FIELD_SPECS = {
    "平台": 1,
    "赛道": 1,
    "主题": 1,
    "关键词/标签": 1,
    "内容类型要求": 1,
    "活动级别": 1,
    "活动开始时间": 5,
    "活动结束时间": 5,
    "投稿截止时间": 5,
    "活动奖励": 1,
    "参与门槛": 1,
    "官方链接": 15,
    "方向": 1,
    "更新时间": 5,
}

BUSINESS_V1_FIELD_SPECS = {
    "作者ID": 1,
    "账号名称": 1,
    "平台": 1,
    "品牌": 1,
    "产品": 1,
    "项目": 1,
    "Brief链接": 1,
    "主页链接": 15,
    "商务原文": 1,
    "给品牌方信息": 1,
    "账号数据摘要": 1,
    "合作流程": 1,
    "档期": 1,
    "图文报价": 1,
    "视频报价": 1,
    "最近状态": 1,
    "更新时间": 5,
    "详情JSON": 1,
}


def ensure_creation_source_schema(*, viral_url: str = "", activity_url: str = "", business_url: str = "") -> dict[str, str]:
    load_default_env_files()
    result: dict[str, str] = {}
    viral = resolve_viral_bitable_url(viral_url)
    activity = resolve_activity_bitable_url(activity_url)
    if viral:
        app_token, table_id, token = feishu_bitable_refs(viral)
        feishu_ensure_fields(app_token, table_id, token, VIRAL_V1_FIELD_SPECS)
        result["viral"] = viral
    if activity:
        app_token, table_id, token = feishu_bitable_refs(activity)
        feishu_ensure_fields(app_token, table_id, token, ACTIVITY_V1_FIELD_SPECS)
        result["activity"] = activity
    business = resolve_business_bitable_url(business_url)
    if business:
        app_token, table_id, token = feishu_bitable_refs(business)
        feishu_ensure_fields(app_token, table_id, token, BUSINESS_V1_FIELD_SPECS)
        result["business"] = business
    return result
