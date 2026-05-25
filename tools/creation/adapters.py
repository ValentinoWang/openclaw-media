from __future__ import annotations

import json
from typing import Any

from .field_contract import (
    CanonicalMediaRecord,
    get_first_datetime,
    get_first_link,
    get_first_value,
    normalize_content_type,
    normalize_platform,
    split_tags,
)


class ViralContentAdapter:
    source_table = "爆款内容积累表"

    def to_record(self, row: dict[str, Any]) -> CanonicalMediaRecord:
        relation_id = get_first_value(row, "关联ID")
        record_id = str(row.get("record_id") or relation_id or "")
        decomposition_link = get_first_link(row, "参考拆解文档链接")
        recreation_link = get_first_link(row, "参考创作-再创文档链接")
        title = get_first_value(row, "标题")
        tags_raw = get_first_value(row, "关键词/标签")
        return CanonicalMediaRecord(
            source_table=self.source_table,
            source_record_id=record_id,
            record_type="爆款样本",
            title=title,
            content=get_first_value(row, "内容"),
            status=get_first_value(row, "状态"),
            relation_id=relation_id,
            platform=normalize_platform(get_first_value(row, "平台")),
            content_type=normalize_content_type(get_first_value(row, "内容类型")),
            track=get_first_value(row, "赛道"),
            topic=get_first_value(row, "主题"),
            tags=split_tags(tags_raw),
            audience=get_first_value(row, "目标受众"),
            pain_points=get_first_value(row, "痛点/爽点"),
            core_value=get_first_value(row, "核心价值"),
            publish_time=get_first_datetime(row, "发布时间") or get_first_value(row, "发布时间"),
            source_link=get_first_link(row, "来源链接"),
            doc_links={
                "decomposition": decomposition_link,
                "recreation": recreation_link,
            },
            metrics={"core_data": get_first_value(row, "核心数据")},
            created_at=get_first_datetime(row, "创建时间") or get_first_value(row, "创建时间"),
            updated_at=get_first_datetime(row, "更新时间") or get_first_value(row, "更新时间"),
            detail_json={
                "爆点拆解": get_first_value(row, "爆点拆解"),
                "爆点迁移": get_first_value(row, "爆点迁移"),
                "吸睛元素": get_first_value(row, "吸睛元素"),
                "高赞评论": get_first_value(row, "高赞评论"),
            },
        )


class ActivityAdapter:
    source_table = "近期活动表"

    def to_record(self, row: dict[str, Any]) -> CanonicalMediaRecord:
        relation_id = get_first_value(row, "关联ID")
        record_id = str(row.get("record_id") or relation_id or "")
        return CanonicalMediaRecord(
            source_table=self.source_table,
            source_record_id=record_id,
            record_type="活动",
            title=get_first_value(row, "标题"),
            content=get_first_value(row, "内容"),
            status=get_first_value(row, "状态"),
            relation_id=relation_id,
            platform=normalize_platform(get_first_value(row, "平台")),
            content_type_requirement=normalize_content_type(get_first_value(row, "内容类型要求")),
            track=get_first_value(row, "赛道"),
            topic=get_first_value(row, "主题"),
            tags=split_tags(get_first_value(row, "关键词/标签")),
            start_time=get_first_datetime(row, "活动开始时间") or get_first_value(row, "活动开始时间"),
            end_time=get_first_datetime(row, "活动结束时间") or get_first_value(row, "活动结束时间"),
            deadline=get_first_datetime(row, "投稿截止时间") or get_first_value(row, "投稿截止时间"),
            source_link=get_first_link(row, "来源链接"),
            activity_level=get_first_value(row, "活动级别"),
            activity_reward=get_first_value(row, "活动奖励"),
            participation_requirement=get_first_value(row, "参与门槛"),
            direction=get_first_value(row, "方向"),
            created_at=get_first_datetime(row, "创建时间") or get_first_value(row, "创建时间"),
            updated_at=get_first_datetime(row, "更新时间") or get_first_value(row, "更新时间"),
            detail_json={"原始平台名称": get_first_value(row, "平台名称")},
        )


class BusinessAdapter:
    source_table = "ID+商务表"

    def to_record(self, row: dict[str, Any]) -> CanonicalMediaRecord:
        relation_id = get_first_value(row, "作者ID") or get_first_value(row, "关联ID")
        record_id = str(row.get("record_id") or relation_id or "")
        account_name = get_first_value(row, "账号名称")
        brand = get_first_value(row, "品牌")
        product = get_first_value(row, "产品")
        project = get_first_value(row, "项目")
        brief_link = get_first_link(row, "Brief链接")
        home_link = get_first_link(row, "主页链接")
        title_parts = [item for item in (account_name, brand, product, project) if item]
        return CanonicalMediaRecord(
            source_table=self.source_table,
            source_record_id=record_id,
            record_type="商务",
            title=" / ".join(title_parts) or relation_id or record_id,
            content=get_first_value(row, "给品牌方信息") or get_first_value(row, "商务原文"),
            status=get_first_value(row, "商务状态") or get_first_value(row, "状态"),
            relation_id=relation_id,
            platform=normalize_platform(get_first_value(row, "平台")),
            content_type_requirement=_business_content_type_requirement(row),
            track="",
            topic=" ".join(item for item in (brand, product, project) if item),
            tags=split_tags(" ".join(item for item in (brand, product, project, account_name) if item)),
            source_link=brief_link or home_link,
            doc_links={"brief": brief_link, "homepage": home_link},
            metrics={"account_data": get_first_value(row, "账号数据摘要")},
            created_at=get_first_datetime(row, "创建时间") or get_first_value(row, "创建时间"),
            updated_at=get_first_datetime(row, "更新时间") or get_first_value(row, "更新时间"),
            detail_json={
                "作者ID": relation_id,
                "账号名称": account_name,
                "品牌": brand,
                "产品": product,
                "项目": project,
                "Brief链接": brief_link,
                "主页链接": home_link,
                "合作流程": get_first_value(row, "合作流程"),
                "档期": get_first_value(row, "档期"),
                "图文报价": get_first_value(row, "图文报价"),
                "视频报价": get_first_value(row, "视频报价"),
                "给品牌方信息": get_first_value(row, "给品牌方信息"),
            },
        )


class CreationInspirationAdapter:
    source_table = "创作灵感表"

    def to_record(self, row: dict[str, Any]) -> CanonicalMediaRecord:
        relation_id = get_first_value(row, "关联ID")
        record_id = str(row.get("record_id") or relation_id or "")
        detail_json = _jsonish_detail(
            get_first_value(row, "详情JSON"),
            get_first_value(row, "爆点分析JSON"),
            get_first_value(row, "核心数据JSON"),
        )
        angles = get_first_value(row, "可复用角度") or get_first_value(row, "一鱼多吃方向")
        title = get_first_value(row, "标题")
        content = get_first_value(row, "内容") or get_first_value(row, "摘要")
        topic = get_first_value(row, "主题") or detail_json.get("theme", "")
        tags_raw = get_first_value(row, "关键词标签") or get_first_value(row, "关键词/标签")
        return CanonicalMediaRecord(
            source_table=self.source_table,
            source_record_id=record_id,
            record_type="创作灵感",
            title=title,
            content=content,
            status=get_first_value(row, "主状态") or get_first_value(row, "状态"),
            relation_id=relation_id,
            platform=normalize_platform(get_first_value(row, "平台")),
            content_type=normalize_content_type(get_first_value(row, "内容类型")),
            track=get_first_value(row, "赛道"),
            topic=topic,
            tags=split_tags(tags_raw),
            audience=get_first_value(row, "目标受众") or detail_json.get("target_audience", ""),
            pain_points=get_first_value(row, "痛点/爽点") or detail_json.get("reader_problem", ""),
            core_value=get_first_value(row, "核心观点") or detail_json.get("core_viewpoint", ""),
            source_link=get_first_link(row, "来源链接"),
            doc_links=_doc_links_from_jsonish(get_first_value(row, "文档链接JSON")),
            metrics={"score": detail_json.get("score", ""), "score_reason": detail_json.get("score_reason", "")},
            direction=angles,
            created_at=get_first_datetime(row, "创建时间") or get_first_value(row, "创建时间"),
            updated_at=get_first_datetime(row, "更新时间") or get_first_value(row, "更新时间"),
            detail_json={
                **detail_json,
                "素材来源类型": get_first_value(row, "素材来源类型"),
                "素材信号类型": get_first_value(row, "素材信号类型"),
                "情绪触发": get_first_value(row, "情绪触发"),
                "触发原话": get_first_value(row, "触发原话"),
                "事件场景": get_first_value(row, "事件场景"),
                "错位点": get_first_value(row, "错位点"),
                "素材状态": get_first_value(row, "素材状态"),
                "一鱼多吃方向": get_first_value(row, "一鱼多吃方向"),
            },
        )


def _business_content_type_requirement(row: dict[str, Any]) -> str:
    has_image = bool(get_first_value(row, "图文报价"))
    has_video = bool(get_first_value(row, "视频报价"))
    if has_image and has_video:
        return "不限"
    if has_image:
        return "图文"
    if has_video:
        return "视频"
    return ""


def _jsonish_detail(*values: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = {"text": text}
        if isinstance(parsed, dict):
            merged.update(parsed)
    result = merged.get("result")
    if isinstance(result, dict):
        merged.update(result)
    return merged


def _doc_links_from_jsonish(value: str) -> dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = {}
    links: dict[str, str] = {}
    if isinstance(parsed, dict):
        for key, item in parsed.items():
            link = get_first_link({"fields": {"link": item}}, "link") or str(item or "").strip()
            if link:
                links[str(key)] = link
    return links
