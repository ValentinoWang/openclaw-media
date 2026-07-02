from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


# Standard field types follow Feishu bitable type ids.
STANDARD_FIELD_SPECS: dict[str, int] = {
    "标题": 1,
    "主题": 1,
    "内容": 1,
    "摘要": 1,
    "平台": 4,
    "记录类型": 1,
    "内容类型": 3,
    "知识类型": 1,
    "赛道": 4,
    "分类JSON": 1,
    "关键词标签": 1,
    "主话题": 1,
    "子方向": 1,
    "关联ID": 1,
    "父记录ID": 1,
    "平台ID": 1,
    "平台账号ID": 1,
    "作者ID": 1,
    "博主IP": 1,
    "账号名称": 1,
    "院校背景": 1,
    "创建时间": 5,
    "入库时间": 5,
    "更新时间": 5,
    "发布时间": 1,
    "地点": 1,
    "截止时间": 5,
    "提醒时间": 5,
    "活动时间JSON": 1,
    "档期": 1,
    "反问时间": 5,
    "报价更新时间": 5,
    "来源链接": 15,
    "主页链接": 15,
    "分享链接": 15,
    "Brief链接": 15,
    "发布链接": 15,
    "创作者主档链接": 15,
    "关联对象链接": 1,
    "文档链接JSON": 1,
    "近期作品链接": 15,
    "主状态": 3,
    "解析状态": 1,
    "监控状态": 1,
    "Brief收集状态": 1,
    "反问状态": 1,
    "报价提醒状态": 1,
    "复盘状态": 3,
    "校验结果JSON": 1,
    "原始媒体附件": 1,
    "原音频": 1,
    "预览附件": 1,
    "截图附件": 1,
    "关键帧附件": 1,
    "Brief附件": 1,
    "核心数据JSON": 1,
    "单一事实JSON": 1,
    "关键指标JSON": 1,
    "指标证据JSON": 1,
    "曲线观察JSON": 1,
    "行动建议JSON": 1,
    "问题诊断JSON": 1,
    "数据质量JSON": 1,
    "截图路径JSON": 1,
    "热榜信息JSON": 1,
    "评论信息JSON": 1,
    "受众洞察JSON": 1,
    "爆点分析JSON": 1,
    "知识抽取JSON": 1,
    "活动规则JSON": 1,
    "人工补充JSON": 1,
    "原始文本JSON": 1,
    "商务需求JSON": 1,
    "报价信息JSON": 1,
    "合作条件JSON": 1,
    "详情JSON": 1,
    "复盘节点": 1,
    "表现评级": 3,
    "粉丝数": 2,
    "粉丝数(k)": 2,
    "关注数": 2,
    "作品数": 2,
    "启用": 7,
    "已提醒": 7,
    "优先级": 1,
    "本地路径": 1,
}

STANDARD_JSON_FIELDS = {
    "分类JSON",
    "活动时间JSON",
    "关联对象链接",
    "文档链接JSON",
    "校验结果JSON",
    "核心数据JSON",
    "单一事实JSON",
    "关键指标JSON",
    "指标证据JSON",
    "曲线观察JSON",
    "行动建议JSON",
    "问题诊断JSON",
    "数据质量JSON",
    "截图路径JSON",
    "热榜信息JSON",
    "评论信息JSON",
    "受众洞察JSON",
    "爆点分析JSON",
    "知识抽取JSON",
    "活动规则JSON",
    "人工补充JSON",
    "原始文本JSON",
    "商务需求JSON",
    "报价信息JSON",
    "合作条件JSON",
    "详情JSON",
}

WRITE_MODE_STANDARD = "standard"
DEFAULT_STANDARD_FIELD_WRITE_MODE = WRITE_MODE_STANDARD

STANDARD_ALIAS_MAP: dict[str, str] = {
    "原标题": "标题",
    "名称": "标题",
    "title": "标题",
    "topic": "主题",
    "总结": "摘要",
    "活动Brief": "摘要",
    "brief_summary": "摘要",
    "账号数据摘要": "摘要",
    "最近日报摘要": "摘要",
    "平台名称": "平台",
    "来源平台": "平台",
    "platform": "平台",
    "作品形式": "内容类型",
    "类型": "记录类型",
    "记录类型": "记录类型",
    "一级分类": "分类JSON",
    "二级分类": "分类JSON",
    "关键词/标签": "关键词标签",
    "标签": "关键词标签",
    "赛道/标签": "关键词标签",
    "main_topic": "主话题",
    "子话题方向": "子方向",
    "subtopic_directions": "子方向",
    "父记录": "父记录ID",
    "account_id": "平台账号ID",
    "platform_id": "平台ID",
    "账号": "账号名称",
    "博主ip": "博主IP",
    "学校背景": "院校背景",
    "院校": "院校背景",
    "activity_time": "活动时间JSON",
    "activity_time_start": "活动时间JSON",
    "activity_time_end": "活动时间JSON",
    "具体档期": "档期",
    "反问博主时间": "反问时间",
    "参考链接": "来源链接",
    "原链接": "来源链接",
    "source_links": "来源链接",
    "creator_doc": "创作者主档链接",
    "创作者文档": "创作者主档链接",
    "博主档案链接": "创作者主档链接",
    "关联活动链接": "关联对象链接",
    "关联商务链接": "关联对象链接",
    "参考拆解文档链接": "文档链接JSON",
    "参考拆解-再创文档链接": "文档链接JSON",
    "分镜脚本": "文档链接JSON",
    "拆解文档": "文档链接JSON",
    "拆解文档链接": "文档链接JSON",
    "拆解-再创文档": "文档链接JSON",
    "拆解-再创文档链接": "文档链接JSON",
    "创作文档链接": "文档链接JSON",
    "文档链接": "文档链接JSON",
    "图文脚本": "文档链接JSON",
    "状态": "主状态",
    "activity_status": "主状态",
    "解析状态": "解析状态",
    "parse_status": "解析状态",
    "最近状态": "监控状态",
    "反问博主状态": "反问状态",
    "标题校验": "校验结果JSON",
    "Tags校验": "校验结果JSON",
    "平台规则校验": "校验结果JSON",
    "失败原因": "校验结果JSON",
    "原文件": "原始媒体附件",
    "原视频": "原始媒体附件",
    "封面图/前五秒": "预览附件",
    "作品截图": "截图附件",
    "主页截图路径": "截图附件",
    "关键帧": "关键帧附件",
    "Brief附件路径": "Brief附件",
    "附件": "Brief附件",
    "核心数据": "核心数据JSON",
    "评分": "核心数据JSON",
    "分数": "核心数据JSON",
    "灵感评分": "核心数据JSON",
    "关键指标": "关键指标JSON",
    "指标证据": "指标证据JSON",
    "曲线观察": "曲线观察JSON",
    "行动建议": "行动建议JSON",
    "问题诊断": "问题诊断JSON",
    "数据质量": "数据质量JSON",
    "截图路径": "截图路径JSON",
    "赞藏总数": "核心数据JSON",
    "获赞数": "核心数据JSON",
    "最近作品数": "核心数据JSON",
    "最近总互动": "核心数据JSON",
    "热榜字段": "热榜信息JSON",
    "高赞评论": "评论信息JSON",
    "目标受众": "受众洞察JSON",
    "痛点/爽点": "受众洞察JSON",
    "爆点拆解": "爆点分析JSON",
    "爆点迁移": "爆点分析JSON",
    "吸睛元素": "爆点分析JSON",
    "核心价值": "爆点分析JSON",
    "再创作方向": "爆点分析JSON",
    "拆解-再创方向": "爆点分析JSON",
    "避重/改写建议": "爆点分析JSON",
    "隐形信息": "知识抽取JSON",
    "镜头/画面线索": "知识抽取JSON",
    "可迁移表达": "知识抽取JSON",
    "核心观点": "知识抽取JSON",
    "问题提取": "知识抽取JSON",
    "价值判断": "知识抽取JSON",
    "应用建议": "知识抽取JSON",
    "待验证问题": "知识抽取JSON",
    "填写要点": "活动规则JSON",
    "参与方式": "活动规则JSON",
    "participation_method": "活动规则JSON",
    "参与形式": "活动规则JSON",
    "participation_form": "活动规则JSON",
    "提交要求": "活动规则JSON",
    "submission_requirements": "活动规则JSON",
    "活动奖励": "活动规则JSON",
    "reward": "活动规则JSON",
    "活动级别": "活动规则JSON",
    "activity_level": "活动规则JSON",
    "需人工补充": "人工补充JSON",
    "missing_info": "人工补充JSON",
    "confidence_note": "人工补充JSON",
    "分享原文": "原始文本JSON",
    "商务原文": "原始文本JSON",
    "Brief原文": "原始文本JSON",
    "全部文案": "原始文本JSON",
    "全部视频脚本": "原始文本JSON",
    "可复制发布稿": "原始文本JSON",
    "项目": "商务需求JSON",
    "品牌": "商务需求JSON",
    "产品": "商务需求JSON",
    "合作流程": "商务需求JSON",
    "Brief关键入库信息": "商务需求JSON",
    "Brief告知类信息": "商务需求JSON",
    "需反问博主字段": "商务需求JSON",
    "反问博主话术": "商务需求JSON",
    "待补充字段": "商务需求JSON",
    "沟通开场": "商务需求JSON",
    "给品牌方信息": "商务需求JSON",
    "图文报价": "报价信息JSON",
    "视频报价": "报价信息JSON",
    "非报备图文/视频单品报价": "报价信息JSON",
    "报备视频、图文/单品报价": "报价信息JSON",
    "4月报备图文价格": "报价信息JSON",
    "5月报备图文价格": "报价信息JSON",
    "报备返点": "报价信息JSON",
    "报价提醒月份": "报价信息JSON",
    "本月下单是否保价次月执行": "合作条件JSON",
    "是否可保价5月": "合作条件JSON",
    "排竞时长": "合作条件JSON",
    "是否有免费分发平台": "合作条件JSON",
    "全渠道授权及时长": "合作条件JSON",
    "笔记默认保留时长": "合作条件JSON",
    "评论区置顶": "合作条件JSON",
    "素材收集要求": "合作条件JSON",
    "非商用授权": "合作条件JSON",
    "商用授权": "合作条件JSON",
    "可同步平台": "合作条件JSON",
    "尺码": "合作条件JSON",
    "作品保留": "合作条件JSON",
    "所在地区是否可以正常收发快递": "合作条件JSON",
    "关联活动ID": "详情JSON",
    "关联商务ID": "详情JSON",
    "参考爆款ID": "详情JSON",
    "定位分析JSON": "详情JSON",
    "匹配分数JSON": "详情JSON",
    "素材来源": "详情JSON",
    "转化目标": "详情JSON",
    "建议产物": "详情JSON",
    "最近错误": "详情JSON",
    "主页可见文本": "详情JSON",
    "截图状态": "详情JSON",
    "反问博主通知结果": "详情JSON",
}


def standard_field_specs(extra_specs: Mapping[str, int] | None = None) -> dict[str, int]:
    specs = dict(STANDARD_FIELD_SPECS)
    if extra_specs:
        specs.update({str(key): int(value) for key, value in extra_specs.items()})
    return specs


def normalize_standard_field_name(name: str, alias_map: Mapping[str, str] | None = None) -> str:
    clean = str(name or "").strip()
    if not clean:
        return ""
    merged_alias_map = dict(STANDARD_ALIAS_MAP)
    if alias_map:
        merged_alias_map.update({str(key): str(value) for key, value in alias_map.items()})
    return merged_alias_map.get(clean, clean)


def choose_primary_value(values: Iterable[Any]) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if value == []:
            continue
        if value == {}:
            continue
        return value
    return ""


def merge_json_group(base: Any, patch: Any) -> Any:
    if base in (None, "", [], {}):
        return patch
    if patch in (None, "", [], {}):
        return base
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            if key in merged:
                merged[key] = merge_json_group(merged[key], value)
            else:
                merged[key] = value
        return merged
    if isinstance(base, list) and isinstance(patch, list):
        merged = list(base)
        for item in patch:
            if item not in merged:
                merged.append(item)
        return merged
    return choose_primary_value([base, patch])


def normalize_standard_fields(
    fields: Mapping[str, Any],
    *,
    alias_map: Mapping[str, str] | None = None,
    json_fields: set[str] | None = None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    grouped_json_fields = STANDARD_JSON_FIELDS | set(json_fields or set())
    for raw_name, raw_value in fields.items():
        target = normalize_standard_field_name(str(raw_name), alias_map)
        if not target:
            continue
        if target in grouped_json_fields:
            existing = normalized.get(target, {})
            if isinstance(existing, dict) and str(raw_name).strip() != target:
                payload = {str(raw_name).strip(): raw_value}
            else:
                payload = raw_value
            normalized[target] = merge_json_group(existing, payload)
            continue
        if target in normalized:
            normalized[target] = choose_primary_value([normalized[target], raw_value])
            continue
        normalized[target] = raw_value
    return normalized


def select_fields_for_write(
    fields: Mapping[str, Any],
    *,
    normalized_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(normalized_fields or normalize_standard_fields(fields))
