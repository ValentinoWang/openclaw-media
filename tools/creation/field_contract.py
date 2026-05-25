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
    "状态": ["状态"],
    "关联ID": ["关联ID", "关联 Id", "关联id"],
    "创建时间": ["创建时间"],
    "更新时间": ["更新时间"],
    "平台": ["平台", "平台名称", "来源平台"],
    "内容类型": ["内容类型", "媒体类型", "作品类型"],
    "内容类型要求": ["内容类型要求", "内容要求", "投稿类型要求"],
    "赛道": ["赛道"],
    "主题": ["主题", "主体", "主话题", "选题", "活动主题"],
    "关键词/标签": ["关键词/标签", "赛道/标签", "标签", "话题"],
    "目标受众": ["目标受众"],
    "痛点/爽点": ["痛点/爽点", "痛点", "爽点"],
    "核心价值": ["核心价值"],
    "发布时间": ["发布时间", "计划发布时间"],
    "来源链接": ["来源链接", "参考链接", "原链接", "官方链接", "主页链接"],
    "文档链接": ["文档链接", "拆解文档链接", "创作-再创文档链接", "创作文档链接"],
    "核心数据": ["核心数据", "热榜字段", "账号数据摘要"],
    "活动级别": ["活动级别"],
    "活动开始时间": ["活动开始时间", "开始时间"],
    "活动结束时间": ["活动结束时间", "结束时间"],
    "投稿截止时间": ["投稿截止时间", "截止时间"],
    "活动奖励": ["活动奖励", "奖励/扶持", "奖励"],
    "参与门槛": ["参与门槛"],
    "方向": ["方向", "内容方向", "适配主题"],
    "关联活动ID": ["关联活动ID"],
    "关联活动链接": ["关联活动链接"],
    "参考爆款ID": ["参考爆款ID"],
    "参考拆解文档链接": ["参考拆解文档链接", "拆解文档链接", "拆解文档"],
    "参考创作-再创文档链接": ["参考创作-再创文档链接", "创作-再创文档链接", "创作-再创文档"],
    "创作文档链接": ["创作文档链接"],
    "匹配分数JSON": ["匹配分数JSON"],
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
    "商务状态": ["最近状态", "Brief收集状态"],
    "关联商务ID": ["关联商务ID"],
    "关联商务链接": ["关联商务链接"],
    "素材来源类型": ["素材来源类型", "灵感来源类型", "素材类型"],
    "素材信号类型": ["素材信号类型", "信号类型"],
    "情绪触发": ["情绪触发", "情绪", "触发情绪"],
    "触发原话": ["触发原话", "原话", "触发句"],
    "事件场景": ["事件场景", "场景", "素材场景"],
    "错位点": ["错位点", "冲突点", "矛盾点"],
    "核心观点": ["核心观点", "观点"],
    "可复用角度": ["可复用角度", "复用角度", "内容角度"],
    "素材状态": ["素材状态", "素材成熟度", "处理状态"],
    "一鱼多吃方向": ["一鱼多吃方向", "派生方向", "衍生选题"],
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
    source_link: str = ""
    doc_links: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    activity_level: str = ""
    activity_reward: str = ""
    participation_requirement: str = ""
    direction: str = ""
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
