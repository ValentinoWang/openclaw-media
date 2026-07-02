from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


FIELD_ALIASES: dict[str, list[str]] = {
    "标题": ["标题", "原标题", "名称", "活动标题"],
    "类型": ["类型", "记录类型"],
    "内容": ["内容", "摘要", "活动摘要"],
    "摘要": ["摘要", "内容"],
    "状态": ["状态"],
    "status": ["status", "状态"],
    "run_id": ["run_id", "创作运行ID"],
    "entrypoint": ["entrypoint", "入口标签"],
    "input_summary": ["input_summary", "输入需求摘要"],
    "generation_source": ["generation_source", "生成来源"],
    "run_artifact_uri": ["run_artifact_uri", "运行产物URI"],
    "render_id": ["render_id", "渲染ID"],
    "render_spec_uri": ["render_spec_uri", "渲染规格URI"],
    "feishu_doc_link": ["feishu_doc_link", "飞书文档链接"],
    "主状态": ["主状态"],
    "关联ID": ["关联ID", "关联 Id", "关联id"],
    "创建时间": ["创建时间"],
    "更新时间": ["更新时间"],
    "平台": ["平台", "平台名称", "来源平台"],
    "平台名称": ["平台名称"],
    "内容类型": ["内容类型", "媒体类型", "作品类型"],
    "赛道": ["赛道"],
    "主题": ["主题", "主体", "主话题", "选题", "活动主题"],
    "主话题": ["主话题"],
    "关键词/标签": ["关键词/标签", "赛道/标签", "标签", "话题"],
    "关键词标签": ["关键词标签", "关键词", "标签", "关键词/标签"],
    "目标受众": ["目标受众"],
    "痛点/爽点": ["痛点/爽点", "痛点", "爽点"],
    "核心价值": ["核心价值"],
    "发布时间": ["发布时间", "计划发布时间"],
    "来源链接": ["来源链接", "参考链接", "原链接", "官方链接", "主页链接"],
    "文档链接": ["文档链接", "拆解文档链接", "拆解-再创文档链接", "创作文档链接"],
    "灵感文档链接": ["灵感文档链接", "文档链接"],
    "素材文档链接": ["素材文档链接", "文档链接"],
    "再创作文档链接": ["再创作文档链接", "拆解-再创文档链接"],
    "核心数据": ["核心数据", "热榜字段", "账号数据摘要"],
    "灵感评分": ["灵感评分", "核心数据"],
    "评分原因": ["评分原因"],
    "爆点拆解": ["爆点拆解"],
    "爆点迁移": ["爆点迁移"],
    "吸睛元素": ["吸睛元素"],
    "高赞评论": ["高赞评论"],
    "活动级别": ["活动级别"],
    "活动开始时间": ["活动开始时间"],
    "活动结束时间": ["活动结束时间"],
    "活动奖励": ["活动奖励", "奖励/扶持", "奖励"],
    "冲榜日期": ["冲榜日期"],
    "活动Brief": ["活动Brief"],
    "填写要点": ["填写要点"],
    "参与方式": ["参与方式"],
    "参与形式": ["参与形式"],
    "提交要求": ["提交要求"],
    "子话题方向": ["子话题方向"],
    "爆款示范链接": ["爆款示范链接"],
    "返稿链接": ["返稿链接"],
    "活动文档链接": ["活动文档链接"],
    "关联活动ID": ["关联活动ID"],
    "关联活动链接": ["关联活动链接"],
    "参考爆款ID": ["参考爆款ID"],
    "参考拆解文档链接": ["参考拆解文档链接", "拆解文档链接", "拆解文档"],
    "参考拆解-再创文档链接": ["参考拆解-再创文档链接", "拆解-再创文档链接", "拆解-再创文档"],
    "创作文档链接": ["创作文档链接"],
    "活动匹配分": ["活动匹配分"],
    "爆款匹配分": ["爆款匹配分"],
    "灵感匹配分": ["灵感匹配分"],
    "商务匹配分": ["商务匹配分"],
    "匹配理由": ["匹配理由"],
    "作者ID": ["作者ID", "作者Id", "作者id", "ID", "账号ID"],
    "账号名称": ["账号名称", "账号", "博主", "昵称"],
    "品牌": ["品牌"],
    "产品": ["产品"],
    "项目": ["项目"],
    "Brief链接": ["Brief链接", "brief链接", "Brief", "brief"],
    "主页链接": ["主页链接", "分享链接", "首页链接"],
    "商务原文": ["商务原文", "Brief原文", "分享原文"],
    "给品牌方信息": ["给品牌方信息"],
    "账号数据摘要": ["账号数据摘要"],
    "合作流程": ["合作流程"],
    "档期": ["档期", "具体档期"],
    "图文报价": ["图文报价"],
    "视频报价": ["视频报价"],
    "商务状态": ["商务状态", "最近状态", "Brief收集状态"],
    "关联商务ID": ["关联商务ID"],
    "关联商务链接": ["关联商务链接"],
    "opportunity_id": ["opportunity_id", "商务机会ID"],
    "business_account_id": ["business_account_id", "商务账号ID"],
    "brand": ["brand", "品牌"],
    "product": ["product", "产品"],
    "brief_link": ["brief_link", "Brief链接"],
    "current_quote_amount": ["current_quote_amount", "当前报价"],
    "rebate_ratio": ["rebate_ratio", "返点比例"],
    "valid_from": ["valid_from", "有效开始时间"],
    "valid_until": ["valid_until", "有效结束时间"],
    "quote_snapshot_uri": ["quote_snapshot_uri", "报价快照URI"],
    "pattern_id": ["pattern_id", "模式ID"],
    "pattern_name": ["pattern_name", "模式名称"],
    "pattern_status": ["pattern_status", "模式状态"],
    "platform": ["platform", "平台"],
    "content_type": ["content_type", "内容类型"],
    "applicable_persona": ["applicable_persona", "适用人设"],
    "applicable_scenarios": ["applicable_scenarios", "适用场景"],
    "opening_template": ["opening_template", "开头模板"],
    "structure_template": ["structure_template", "结构模板"],
    "visual_template": ["visual_template", "视觉模板"],
    "emotional_levers": ["emotional_levers", "情绪杠杆"],
    "forbidden_scenarios": ["forbidden_scenarios", "禁用场景"],
    "historical_performance_summary": ["historical_performance_summary", "历史表现摘要"],
    "素材来源类型": ["素材来源类型", "灵感来源类型", "素材类型"],
    "素材信号类型": ["素材信号类型", "信号类型"],
    "情绪触发": ["情绪触发", "情绪", "触发情绪"],
    "触发原话": ["触发原话", "原话", "触发句"],
    "事件场景": ["事件场景", "场景", "素材场景"],
    "错位点": ["错位点", "冲突点", "矛盾点"],
    "核心观点": ["核心观点", "观点"],
    "读者问题": ["读者问题", "读者痛点", "目标读者问题"],
    "可复用角度": ["可复用角度", "复用角度", "内容角度"],
    "下一步": ["下一步", "下一步动作", "next_actions"],
    "素材状态": ["素材状态", "素材成熟度", "处理状态"],
    "一鱼多吃方向": ["一鱼多吃方向", "派生方向", "衍生选题"],
    "拆解-再创方向": ["拆解-再创方向", "再创作方向"],
    "可迁移点": ["可迁移点"],
    "风险点": ["风险点"],
    "建议产物": ["建议产物"],
    "定位分析": ["定位分析"],
    "平台策略": ["平台策略"],
    "校验结果": ["校验结果"],
    "创作请求": ["创作请求"],
    "本地报告路径": ["本地报告路径"],
    "创作记录ID": ["创作记录ID"],
    "asset_id": ["asset_id", "素材ID"],
    "content_fingerprint": ["content_fingerprint", "内容指纹"],
    "title": ["title", "标题"],
    "original_title": ["original_title", "原作品标题"],
    "source_url": ["source_url", "来源链接"],
    "author_id": ["author_id", "作者ID"],
    "account_name_snapshot": ["account_name_snapshot", "账号名称快照"],
    "evidence_uri": ["evidence_uri", "证据URI"],
    "source_doc_link": ["source_doc_link", "原作品文档链接"],
    "enabled": ["enabled", "启用"],
    "deconstruction_id": ["deconstruction_id", "拆解ID"],
    "summary": ["summary", "摘要"],
    "hook": ["hook", "开头钩子"],
    "transferable_points": ["transferable_points", "可迁移点"],
    "non_transferable_points": ["non_transferable_points", "不可迁移点"],
    "reference_shots_status": ["reference_shots_status", "参考镜头状态"],
    "reference_shot_count": ["reference_shot_count", "参考镜头数", "参考镜头数量"],
    "recommended_production_route": ["recommended_production_route", "推荐生产路线", "推荐制作路线"],
    "motion_type_summary": ["motion_type_summary", "运动类型摘要", "动作类型摘要"],
    "reference_shots_summary": ["reference_shots_summary", "参考镜头摘要"],
    "cover_opening_hook": ["cover_opening_hook", "封面/前2秒抓手"],
    "core_data_summary": ["core_data_summary", "核心数据摘要"],
    "top_comment_insight": ["top_comment_insight", "高赞评论洞察"],
    "target_audience_summary": ["target_audience_summary", "目标受众"],
    "pain_pleasure_summary": ["pain_pleasure_summary", "痛点/爽点"],
    "attention_elements": ["attention_elements", "吸睛元素"],
    "viral_breakdown": ["viral_breakdown", "爆点拆解"],
    "viral_migration": ["viral_migration", "爆点迁移"],
    "creative_upgrade_suggestion": ["creative_upgrade_suggestion", "创新修改建议"],
    "prompt_bundle_version": ["prompt_bundle_version", "提示词版本"],
    "model": ["model", "模型"],
    "skill_version": ["skill_version", "技能版本"],
    "confidence": ["confidence", "置信度"],
    "review_status": ["review_status", "人工复核状态"],
    "deconstruction_doc_link": ["deconstruction_doc_link", "拆解文档链接"],
}

CREATION_SOURCE_FIELD_CONTRACT_VERSION = "creation_source_fields_v1"

CREATION_SOURCE_TABLE_CONTRACTS: dict[str, dict[str, Any]] = {
    "activity": {
        "table": "01_近期活动",
        "env": ("MEDIA_OS_ACTIVITY_URL",),
        "config": ("/home/ubuntu/openclaw-feishu-reminder/wiki-activity-config.json",),
        "adapter": "ActivityAdapter",
        "candidate_key": "activity_memory_candidates",
        "selected_id_key": "selected_activity_ids",
        "fields": (
            "record_id",
            "关联ID",
            "标题",
            "内容",
            "主状态",
            "平台名称",
            "创建时间",
            "主话题",
            "活动开始时间",
            "活动结束时间",
            "冲榜日期",
            "活动Brief",
            "填写要点",
            "参与方式",
            "参与形式",
            "提交要求",
            "子话题方向",
            "活动级别",
            "活动奖励",
            "Brief链接",
            "爆款示范链接",
            "返稿链接",
            "活动文档链接",
        ),
    },
    "viral": {
        "table": "02B_MaterialDeconstructions_素材拆解",
        "env": ("MEDIA_OS_SOURCE_ASSETS_URL", "MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL"),
        "config": (),
        "adapter": "ViralContentAdapter",
        "candidate_key": "viral_memory_candidates",
        "selected_id_key": "selected_viral_ids",
        "fields": (
            "record_id",
            "asset_id",
            "content_fingerprint",
            "title",
            "original_title",
            "platform",
            "source_url",
            "author_id",
            "account_name_snapshot",
            "evidence_uri",
            "source_doc_link",
            "status",
            "enabled",
            "deconstruction_id",
            "summary",
            "hook",
            "transferable_points",
            "non_transferable_points",
            "reference_shots_status",
            "reference_shot_count",
            "recommended_production_route",
            "motion_type_summary",
            "reference_shots_summary",
            "cover_opening_hook",
            "core_data_summary",
            "top_comment_insight",
            "target_audience_summary",
            "pain_pleasure_summary",
            "attention_elements",
            "viral_breakdown",
            "viral_migration",
            "creative_upgrade_suggestion",
            "prompt_bundle_version",
            "model",
            "skill_version",
            "confidence",
            "deconstruction_doc_link",
            "review_status",
        ),
    },
    "business": {
        "table": "05B_BusinessOpportunities_商务机会",
        "env": ("MEDIA_OS_BUSINESS_OPPORTUNITIES_URL",),
        "config": (),
        "adapter": "BusinessAdapter",
        "candidate_key": "business_memory_candidates",
        "selected_id_key": "selected_business_ids",
        "fields": (
            "record_id",
            "opportunity_id",
            "business_account_id",
            "brand",
            "product",
            "brief_link",
            "current_quote_amount",
            "rebate_ratio",
            "valid_from",
            "valid_until",
            "quote_snapshot_uri",
        ),
    },
    "inspiration": {
        "table": "02C_CreativePatterns_创作模式",
        "env": ("MEDIA_OS_CREATIVE_PATTERNS_URL",),
        "config": (),
        "adapter": "CreationInspirationAdapter",
        "candidate_key": "inspiration_memory_candidates",
        "selected_id_key": "selected_inspiration_ids",
        "fields": (
            "record_id",
            "pattern_id",
            "pattern_name",
            "pattern_status",
            "platform",
            "content_type",
            "applicable_persona",
            "applicable_scenarios",
            "opening_template",
            "structure_template",
            "visual_template",
            "emotional_levers",
            "forbidden_scenarios",
            "historical_performance_summary",
        ),
    },
}

CREATION_ACCOUNT_CONTEXT_CONTRACT: dict[str, Any] = {
    "source": "Media context + account Markdown + 06_CreatorProfiles_达人账号档案 when explicitly loaded; source 06_达人账号档案 snapshots are evidence only",
    "env": ("MEDIA_OS_CREATOR_PROFILES_V2_URL",),
    "fields": (
        "account_name",
        "platform",
        "author_id",
        "profile_url",
        "identity_summary",
        "identity_tags",
        "education_background",
        "expertise_domains",
        "creator_role",
        "public_persona_boundaries",
        "story_usable_identity_points",
        "current_metrics_summary",
    ),
}

CREATION_OUTPUT_TABLE_CONTRACT: dict[str, Any] = {
    "table": "03_CreationRuns_创作运行",
    "env": ("MEDIA_OS_CREATION_RUNS_URL",),
    "fields": (
        "run_id",
        "entrypoint",
        "input_summary",
        "status",
        "generation_source",
        "run_artifact_uri",
        "render_id",
        "render_spec_uri",
        "feishu_doc_link",
    ),
}

CREATION_MATCH_SCORE_FIELD_SEMANTICS: dict[str, str] = {
    "活动匹配分": "0-100 normalized current-request fit score for selected activity records; raw activity score is evidence-only",
    "爆款匹配分": "0-100 current-request fit score for selected viral/deconstruction records; LLM selection is a reason, not score=100",
    "灵感匹配分": "0-100 current-request fit score for selected inspiration records; source 灵感评分 is only a small quality input",
    "匹配理由": "Readable score reason summary plus LLM selection reason; long breakdowns stay in the child-doc evidence appendix",
}

RECORD_TYPE_VALUES = {
    "内容素材",
    "活动",
    "自媒体知识",
    "知识",
    "创作",
    "创作灵感",
    "爆款样本",
    "账号监控",
    "商务",
}

CONTENT_TYPE_VALUES = {
    "图文",
    "视频",
    "直播",
    "网页",
    "活动",
    "不限",
}

PLATFORM_ALIASES = {
    "xhs": "小红书",
    "xiaohongshu": "小红书",
    "小红书": "小红书",
    "douyin": "抖音",
    "抖音": "抖音",
}

CONTENT_TYPE_ALIASES = {
    "image_post": "图文",
    "image": "图文",
    "图文": "图文",
    "视频": "视频",
    "video": "视频",
    "直播": "直播",
    "网页": "网页",
    "不限": "不限",
}


@dataclass
class CanonicalMediaRecord:
    source_table: str
    source_record_id: str
    record_type: str
    title: str = ""
    content: str = ""
    status: str = ""
    relation_id: str = ""
    platform: str = ""
    content_type: str = ""
    content_type_requirement: str = ""
    track: str = ""
    topic: str = ""
    tags: list[str] = field(default_factory=list)
    audience: str = ""
    pain_points: str = ""
    core_value: str = ""
    publish_time: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    deadline: str | None = None
    boost_date: str | None = None
    source_link: str = ""
    doc_links: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    activity_level: str = ""
    activity_reward: str = ""
    participation_requirement: str = ""
    direction: str = ""
    activity_brief: str = ""
    activity_guidance: str = ""
    participation_method: str = ""
    participation_form: str = ""
    submission_requirement: str = ""
    brief_link: str = ""
    viral_example_link: str = ""
    submission_link: str = ""
    activity_doc_link: str = ""
    related_activity_id: str = ""
    related_activity_link: str = ""
    related_business_id: str = ""
    related_business_link: str = ""
    reference_viral_ids: list[str] = field(default_factory=list)
    reference_decomposition_links: list[str] = field(default_factory=list)
    reference_recreation_links: list[str] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    detail_json: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_platform(value: Any) -> str:
    text = normalize_feishu_value(value)
    compact = text.strip().lower()
    return PLATFORM_ALIASES.get(compact, text)


def normalize_content_type(value: Any) -> str:
    text = normalize_feishu_value(value)
    compact = text.strip().lower()
    return CONTENT_TYPE_ALIASES.get(compact, text)


def normalize_key(value: Any) -> str:
    return re.sub(r"\s+", "", normalize_feishu_value(value)).lower()


def normalize_feishu_value(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            part = normalize_feishu_value(item)
            if part:
                parts.append(part)
        return " ".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "name", "value", "link", "url"):
            text = normalize_feishu_value(value.get(key))
            if text:
                return text
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).strip()


def normalize_feishu_link(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("link", "url", "text", "name", "value"):
            text = normalize_feishu_value(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        for item in value:
            text = normalize_feishu_link(item)
            if text:
                return text
    return normalize_feishu_value(value)


def normalize_feishu_datetime(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, list):
        return normalize_feishu_datetime(normalize_feishu_value(value))
    if isinstance(value, dict):
        return normalize_feishu_datetime(normalize_feishu_value(value))
    if isinstance(value, (int, float)):
        number = int(value)
        if number <= 0:
            return ""
        seconds = number / 1000 if number > 10_000_000_000 else number
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat()
    text = str(value).strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def get_first_value(row: dict[str, Any], canonical_name: str, default: str = "") -> str:
    aliases = FIELD_ALIASES.get(canonical_name, [canonical_name])
    fields = row.get("fields", row)
    for name in aliases:
        value = fields.get(name)
        if value not in (None, "", []):
            return normalize_feishu_value(value)
    return default


def get_first_link(row: dict[str, Any], canonical_name: str, default: str = "") -> str:
    aliases = FIELD_ALIASES.get(canonical_name, [canonical_name])
    fields = row.get("fields", row)
    for name in aliases:
        value = fields.get(name)
        if value not in (None, "", []):
            return normalize_feishu_link(value)
    return default


def get_first_datetime(row: dict[str, Any], canonical_name: str) -> str:
    aliases = FIELD_ALIASES.get(canonical_name, [canonical_name])
    fields = row.get("fields", row)
    for name in aliases:
        value = fields.get(name)
        if value not in (None, "", []):
            return normalize_feishu_datetime(value)
    return ""


def get_exact_value(row: dict[str, Any], field_name: str, default: str = "") -> str:
    fields = row.get("fields", row)
    value = fields.get(field_name)
    if value not in (None, "", []):
        return normalize_feishu_value(value)
    return default


def get_exact_link(row: dict[str, Any], field_name: str, default: str = "") -> str:
    fields = row.get("fields", row)
    value = fields.get(field_name)
    if value not in (None, "", []):
        return normalize_feishu_link(value)
    return default


def get_exact_datetime(row: dict[str, Any], field_name: str) -> str:
    fields = row.get("fields", row)
    value = fields.get(field_name)
    if value not in (None, "", []):
        return normalize_feishu_datetime(value)
    return ""


def split_tags(raw: Any) -> list[str]:
    text = normalize_feishu_value(raw)
    if not text:
        return []
    for sep in ("，", ",", "、", "#", "\n", "\t", " "):
        text = text.replace(sep, "|")
    seen: set[str] = set()
    tags: list[str] = []
    for item in text.split("|"):
        tag = item.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags
