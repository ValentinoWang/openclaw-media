from __future__ import annotations

import re
from typing import Any


STANDARD_KNOWLEDGE_SECONDARY_CATEGORIES: list[str] = [
    "未细分",
    "AI视频/自动化",
    "模型/智能体",
    "AI工具应用",
    "AI浏览器",
    "AI视频工具",
    "AI增长/GEO",
    "AI趋势盘点",
    "产品增长",
    "AI产品变现",
    "流程管理",
    "算法拆解/增长",
    "自媒体运营",
    "短视频运营",
    "内容创作",
    "内容运营",
    "学习方法",
    "心理认知",
    "关系认知",
    "情感认知",
    "关系风险",
    "健康管理",
    "投资认知",
    "合规风险",
    "生活效率",
    "科技趋势",
    "案例拆解",
]

PRIMARY_DEFAULT_SECONDARY_CATEGORY: dict[str, str] = {
    "AI/工具": "AI工具应用",
    "商业/产品": "产品增长",
    "运营/管理": "流程管理",
    "学习/认知": "学习方法",
    "健康/运动": "健康管理",
    "财经/投资": "投资认知",
    "法律/政策": "合规风险",
    "生活/效率": "生活效率",
    "科技/科学": "科技趋势",
    "人物/案例": "案例拆解",
    "其他": "未细分",
}

_STANDARD_BY_COMPACT = {
    re.sub(r"[\s/_-]+", "", item).lower(): item
    for item in STANDARD_KNOWLEDGE_SECONDARY_CATEGORIES
}

_SECONDARY_ALIASES: dict[str, str] = {
    "平台机制": "算法拆解/增长",
    "算法机制": "算法拆解/增长",
    "推流机制": "算法拆解/增长",
    "平台规则": "算法拆解/增长",
    "内容增长": "算法拆解/增长",
    "流量增长": "算法拆解/增长",
    "涨粉": "算法拆解/增长",
    "创作者变现": "自媒体运营",
    "变现": "自媒体运营",
    "个人ip": "自媒体运营",
    "内容定位": "自媒体运营",
    "创作者提效": "AI工具应用",
    "ai前端动画": "AI工具应用",
    "ai设计工具": "AI工具应用",
    "前端设计": "AI工具应用",
    "前端动画": "AI工具应用",
    "开源工具": "AI工具应用",
    "代码生成": "模型/智能体",
    "ai编程": "模型/智能体",
    "ai记忆机制": "模型/智能体",
    "亲密关系": "关系认知",
    "反pua": "关系风险",
    "pua识别": "关系风险",
    "情感操控": "关系风险",
    "传播机制": "关系风险",
}

_SECONDARY_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("AI视频/自动化", ("剪视频", "自动剪", "视频制作", "remotion", "ffmpeg", "字幕", "剪辑")),
    ("模型/智能体", ("openai", "codex", "智能体", "agent", "大模型", "模型", "transformer", "rag", "提示词", "代码生成")),
    ("AI浏览器", ("浏览器", "指纹", "验证码")),
    ("AI视频工具", ("视频提示词", "ai视频工具")),
    ("AI增长/GEO", ("geo", "出海增长", "搜索增长")),
    ("AI趋势盘点", ("一周ai", "ai新品", "趋势盘点")),
    ("AI工具应用", ("ai", "aigc", "人工智能", "自动化", "工具", "插件", "软件", "skill", "设计工具")),
    ("AI产品变现", ("ai产品", "智能体包装", "下沉", "暴利")),
    ("产品增长", ("产品", "用户", "转化", "销售", "品牌", "定价")),
    ("短视频运营", ("短视频", "抖音", "账号淘汰")),
    ("算法拆解/增长", ("算法", "平台机制", "推流", "流量", "增长", "涨粉", "推荐机制")),
    ("自媒体运营", ("自媒体", "创作者", "变现", "个人ip", "内容定位", "大博主")),
    ("内容运营", ("内容运营", "选题", "发布", "运营打法")),
    ("内容创作", ("内容创作", "创作", "素材库", "表达")),
    ("流程管理", ("流程", "项目", "团队", "组织", "管理")),
    ("关系风险", ("pua", "操控", "风险", "控制欲", "服从性")),
    ("情感认知", ("情感", "两性", "焦虑", "恋爱")),
    ("关系认知", ("关系", "亲密", "沟通", "松弛感")),
    ("心理认知", ("心理", "巴纳姆", "认知偏差")),
    ("学习方法", ("学习", "复盘", "记忆", "方法", "教育")),
    ("健康管理", ("健康", "运动", "健身", "训练", "睡眠", "饮食", "医学")),
    ("投资认知", ("财经", "投资", "股票", "基金", "资产", "现金流", "经济")),
    ("合规风险", ("法律", "政策", "合同", "合规", "监管", "版权")),
    ("生活效率", ("生活", "效率", "习惯", "收纳", "时间管理")),
    ("科技趋势", ("科技", "科学", "研究", "论文", "实验", "工程")),
    ("案例拆解", ("案例", "人物", "故事", "访谈", "经历")),
]

_EMPTY_SECONDARY_VALUES = {
    "",
    "none",
    "null",
    "undefined",
    "其他",
    "未明确体现",
    "待配置",
    "待复核",
}


def _compact_category_text(value: str) -> str:
    return re.sub(r"[\s/_-]+", "", str(value or "")).lower()


def _iter_secondary_items(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(_iter_secondary_items(item))
        return items
    if isinstance(value, dict):
        for key in ("text", "name", "value"):
            if value.get(key):
                return _iter_secondary_items(value.get(key))
        return []

    raw = str(value)
    parts = re.split(r"[\n,，、;；|]+", raw)
    cleaned: list[str] = []
    for part in parts:
        text = re.sub(r"^\s*[-*•]+\s*", "", part).strip()
        text = re.sub(r"^\s*\d+[.、]\s*", "", text).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _add_category(result: list[str], category: str, *, max_items: int) -> None:
    if category and category not in result and category in STANDARD_KNOWLEDGE_SECONDARY_CATEGORIES:
        result.append(category)
    if len(result) > max_items:
        del result[max_items:]


def _normalize_one_secondary(value: str, *, primary: str = "", text: str = "") -> str:
    raw = str(value or "").strip()
    compact = _compact_category_text(raw)
    if compact in _EMPTY_SECONDARY_VALUES:
        return ""
    if compact in _STANDARD_BY_COMPACT:
        return _STANDARD_BY_COMPACT[compact]
    if compact in _SECONDARY_ALIASES:
        return _SECONDARY_ALIASES[compact]

    source = f"{raw}\n{text}".lower()
    for category, keywords in _SECONDARY_KEYWORD_RULES:
        if any(keyword.lower() in source for keyword in keywords):
            return category

    return PRIMARY_DEFAULT_SECONDARY_CATEGORY.get(primary, "")


def normalize_knowledge_secondary_categories(
    value: Any,
    *,
    primary: str = "",
    text: str = "",
    max_items: int = 3,
) -> list[str]:
    result: list[str] = []
    for item in _iter_secondary_items(value):
        category = _normalize_one_secondary(item, primary=primary, text=text)
        _add_category(result, category, max_items=max_items)
        if len(result) >= max_items:
            break
    if result:
        return result

    inferred = _normalize_one_secondary(text, primary=primary, text=text)
    if inferred:
        return [inferred]
    return [PRIMARY_DEFAULT_SECONDARY_CATEGORY.get(primary, "未细分")]
