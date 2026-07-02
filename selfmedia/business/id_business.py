#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests


SELFMEDIA_ROOT = Path("/home/ubuntu/selfmedia-tools")
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))
MEDIA_ROOT = Path(os.getenv("OPENCLAW_MEDIA_AGENT_ROOT", "/home/ubuntu/openclaw-agents/media"))

from common.social_runtime import (  # noqa: E402
    FEISHU_BASE,
    detect_platform,
    extract_urls,
    feishu_bool,
    feishu_bitable_refs,
    feishu_coerce_value,
    feishu_ensure_fields,
    feishu_field_types,
    feishu_headers,
    feishu_list_records,
    feishu_plain_text,
    feishu_table_url_from_env,
    feishu_tenant_access_token,
    load_default_env_files,
    load_env_file,
)
from common.bot_llm_config import bot_runtime
from common.llm_client import generate_json_from_parts
from common.llm_settings import load_content_cleaner_llm_settings
from common.standard_fields import normalize_standard_fields, standard_field_specs
from common.standard_fields import select_fields_for_write
from integrations.feishu.media_writer import upsert_entity_record
from media_model.payloads import build_business_account_payload, build_business_opportunity_payload
from media_vault.vault import MediaVault


OUTPUT_DIR = SELFMEDIA_ROOT / "data" / "media_vault" / "business_id_runs"
RECORD_DIR = OUTPUT_DIR / "records"
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
URL_ENV_NAMES = (
    "MEDIA_OS_BUSINESS_ACCOUNTS_V2_URL",
)
OPPORTUNITY_URL_ENV_NAMES = (
    "MEDIA_OS_BUSINESS_OPPORTUNITIES_URL",
)
CREATOR_PROFILE_URL_ENV_NAMES = (
    "MEDIA_OS_CREATOR_PROFILES_V2_URL",
)
NOTIFY_TARGET_ENV_NAMES = (
    "ID_BUSINESS_SOCIAL_TARGET",
    "OPENCLAW_DELIVERY_TO",
    "OPENCLAW_LAST_TO",
    "OPENCLAW_TARGET",
)
BUSINESS_TRIGGER_RE = re.compile(
    r"^\s*【(?P<tag>商务>ID|商务>(?P<author>(?!ID$)[^】>\s]{1,32}))】\s*",
    re.IGNORECASE,
)
LOCAL_TZ = timezone(timedelta(hours=8))


LEGACY_FIELD_SPECS: dict[str, int] = {
    "作者ID": 1,
    "账号名称": 1,
    "平台": 1,
    "主页链接": 15,
    "分享链接": 15,
    "分享原文": 1,
    "启用": 7,
    "更新时间": 5,
    "最近状态": 1,
    "最近错误": 1,
    "主页截图路径": 1,
    "截图状态": 1,
    "主页可见文本": 1,
    "账号数据摘要": 1,
    "给品牌方信息": 1,
    "赞藏总数": 2,
    "获赞数": 2,
    "粉丝数": 2,
    "关注数": 2,
    "作品数": 2,
    "商务原文": 1,
    "沟通开场": 1,
    "项目": 1,
    "品牌": 1,
    "产品": 1,
    "Brief链接": 1,
    "Brief附件路径": 1,
    "Brief关键入库信息": 1,
    "Brief告知类信息": 1,
    "Brief原文": 1,
    "Brief收集状态": 1,
    "档期": 1,
    "合作流程": 1,
    "图文报价": 1,
    "视频报价": 1,
    "非报备图文/视频单品报价": 1,
    "报备视频、图文/单品报价": 1,
    "4月报备图文价格": 1,
    "5月报备图文价格": 1,
    "报备返点": 1,
    "本月下单是否保价次月执行": 1,
    "是否可保价5月": 1,
    "排竞时长": 1,
    "是否有免费分发平台": 1,
    "全渠道授权及时长": 1,
    "笔记默认保留时长": 1,
    "评论区置顶": 1,
    "素材收集要求": 1,
    "需反问博主字段": 1,
    "反问博主话术": 1,
    "反问博主状态": 1,
    "反问博主时间": 5,
    "反问博主通知结果": 1,
    "具体档期": 1,
    "非商用授权": 1,
    "作品保留": 1,
    "所在地区是否可以正常收发快递": 1,
    "商用授权": 1,
    "可同步平台": 1,
    "尺码": 1,
    "报价更新时间": 5,
    "报价提醒月份": 1,
    "报价提醒状态": 1,
    "待补充字段": 1,
}
FIELD_SPECS: dict[str, int] = {
    name: field_type
    for name, field_type in standard_field_specs(LEGACY_FIELD_SPECS).items()
    if not name.endswith("JSON")
}


LABEL_ALIASES = {
    "作者ID": "作者ID",
    "作者Id": "作者ID",
    "作者id": "作者ID",
    "ID": "作者ID",
    "Id": "作者ID",
    "id": "作者ID",
    "简称": "作者ID",
    "作者简称": "作者ID",
    "内部称呼": "作者ID",
    "称呼": "作者ID",
    "备注名": "作者ID",
    "平台": "平台",
    "项目": "项目",
    "品牌": "品牌",
    "产品": "产品",
    "brief链接": "Brief链接",
    "Brief链接": "Brief链接",
    "brief": "Brief链接",
    "Brief": "Brief链接",
    "附件": "Brief附件路径",
    "Brief附件": "Brief附件路径",
    "Brief附件路径": "Brief附件路径",
    "档期": "档期",
    "具体档期": "具体档期",
    "合作流程": "合作流程",
    "图文报价": "图文报价",
    "图文单品报价": "图文报价",
    "图文/单品报价": "图文报价",
    "非报备图文报价": "图文报价",
    "报备图文报价": "图文报价",
    "视频报价": "视频报价",
    "视频单品报价": "视频报价",
    "视频/单品报价": "视频报价",
    "非报备视频报价": "视频报价",
    "报备视频报价": "视频报价",
    "非报备图文/视频单品报价": "非报备图文/视频单品报价",
    "非报备图文": "非报备图文/视频单品报价",
    "非报备图文报价": "非报备图文/视频单品报价",
    "非报备视频": "非报备图文/视频单品报价",
    "非报备视频报价": "非报备图文/视频单品报价",
    "报备视频、图文/单品报价": "报备视频、图文/单品报价",
    "报备视频图文/单品报价": "报备视频、图文/单品报价",
    "报备视频": "报备视频、图文/单品报价",
    "报备图文": "报备视频、图文/单品报价",
    "4月份报备图文价格": "4月报备图文价格",
    "4月报备图文价格": "4月报备图文价格",
    "5月份报备图文价格": "5月报备图文价格",
    "5月报备图文价格": "5月报备图文价格",
    "返点": "报备返点",
    "报备返点": "报备返点",
    "是否可保价5月": "是否可保价5月",
    "可保价5月": "是否可保价5月",
    "排竞时长": "排竞时长",
    "排竞时长是否可前15后15": "排竞时长",
    "是否有免费分发平台": "是否有免费分发平台",
    "免费分发平台": "是否有免费分发平台",
    "是否可以全渠道授权及时长": "全渠道授权及时长",
    "全渠道授权及时长": "全渠道授权及时长",
    "笔记是否默认一年以上": "笔记默认保留时长",
    "笔记默认一年以上": "笔记默认保留时长",
    "发布后第二天是否能配合评论区置顶": "评论区置顶",
    "评论区置顶": "评论区置顶",
    "素材需要收集纯净版和发布版": "素材收集要求",
    "素材收集要求": "素材收集要求",
    "本月下单是否保价次月执行（如不能辛苦给到次月价格）": "本月下单是否保价次月执行",
    "本月下单是否保价次月执行": "本月下单是否保价次月执行",
    "非商用授权": "非商用授权",
    "作品保留": "作品保留",
    "所在地区是否可以正常收发快递": "所在地区是否可以正常收发快递",
    "快递": "所在地区是否可以正常收发快递",
    "商用授权": "商用授权",
    "可同步平台": "可同步平台",
    "尺码": "尺码",
    "账号名称": "账号名称",
    "账号": "账号名称",
    "博主": "账号名称",
    "昵称": "账号名称",
}


COUNT_RE = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>[kKmMwW万千]?)")
CONFIRMATION_FIELDS = {
    "具体档期",
    "图文报价",
    "视频报价",
    "非报备图文/视频单品报价",
    "报备视频、图文/单品报价",
    "4月报备图文价格",
    "5月报备图文价格",
    "报备返点",
    "本月下单是否保价次月执行",
    "是否可保价5月",
    "排竞时长",
    "是否有免费分发平台",
    "全渠道授权及时长",
    "笔记默认保留时长",
    "评论区置顶",
    "素材收集要求",
    "所在地区是否可以正常收发快递",
    "可同步平台",
    "尺码",
}
CONFIRMATION_CANONICAL = {
    "档期": "具体档期",
    "返点": "报备返点",
}
AMBIGUOUS_VALUE_RE = re.compile(r"待补充|待确认|不确定|看情况|尽快|最快|可沟通|都行|\\?|？")
QUESTION_TEMPLATES = {
    "具体档期": "最快可执行/可发布的具体档期是什么？请具体到日期或日期区间，不要只写“尽快”。",
    "图文报价": "本月图文报价是多少？请注明报备/非报备。",
    "视频报价": "本月视频报价是多少？请注明报备/非报备。",
    "非报备图文/视频单品报价": "非报备图文/视频单品报价分别是多少？",
    "报备视频、图文/单品报价": "报备图文、报备视频单品报价分别是多少？",
    "4月报备图文价格": "4月份报备图文价格是多少？",
    "5月报备图文价格": "5月份报备图文价格是多少？",
    "报备返点": "返点是否接受？如果不是 40%，请给可接受返点。",
    "本月下单是否保价次月执行": "本月下单是否可以保价到次月执行？如果不行，请给次月价格。",
    "是否可保价5月": "是否可以保价到 5 月执行？如果不行，请给 5 月价格。",
    "排竞时长": "是否可接受前 15 天后 15 天排竞？如果不能，可接受的排竞时长是多少？",
    "是否有免费分发平台": "是否有可免费同步/分发的平台？具体哪些平台？",
    "全渠道授权及时长": "是否可以全渠道授权？可授权哪些渠道，授权时长多久？",
    "笔记默认保留时长": "笔记是否默认保留一年以上？",
    "评论区置顶": "发布后第二天是否能配合评论区置顶？",
    "素材收集要求": "是否能提供纯净版和发布版素材？",
    "所在地区是否可以正常收发快递": "所在地区是否可以正常收发快递？",
    "可同步平台": "可同步哪些平台？",
    "尺码": "尺码是多少？",
}
BUSINESS_LLM_PROFILE_NAME = "content_cleaner"
BUSINESS_LLM_MIN_CONFIDENCE = 0.55
BUSINESS_LLM_FIELD_NAMES = (
    "作者ID",
    "账号名称",
    "平台",
    "主页链接",
    "分享链接",
    "沟通开场",
    "项目",
    "品牌",
    "产品",
    "Brief链接",
    "Brief附件路径",
    "Brief关键入库信息",
    "Brief告知类信息",
    "Brief原文",
    "Brief收集状态",
    "档期",
    "具体档期",
    "合作流程",
    "图文报价",
    "视频报价",
    "非报备图文/视频单品报价",
    "报备视频、图文/单品报价",
    "4月报备图文价格",
    "5月报备图文价格",
    "报备返点",
    "本月下单是否保价次月执行",
    "是否可保价5月",
    "排竞时长",
    "是否有免费分发平台",
    "全渠道授权及时长",
    "笔记默认保留时长",
    "评论区置顶",
    "素材收集要求",
    "需反问博主字段",
    "反问博主话术",
    "反问博主状态",
    "非商用授权",
    "作品保留",
    "所在地区是否可以正常收发快递",
    "商用授权",
    "可同步平台",
    "尺码",
    "待补充字段",
    "给品牌方信息",
)
BUSINESS_LLM_SIGNAL_FIELDS = (
    "作者ID",
    "账号名称",
    "平台",
    "主页链接",
    "分享链接",
    "项目",
    "品牌",
    "产品",
    "图文报价",
    "视频报价",
    "非报备图文/视频单品报价",
    "报备视频、图文/单品报价",
    "Brief关键入库信息",
    "需反问博主字段",
)
CREATOR_PROFILE_IDENTITY_FIELDS = (
    "博主IP",
    "平台",
    "平台ID",
    "账号名称",
    "作者ID",
    "主页链接",
    "粉丝数(k)",
    "赛道",
    "关键词标签",
    "院校背景",
)
BUSINESS_HISTORY_FIELDS = (
    "档期",
    "具体档期",
    "合作流程",
    "图文报价",
    "视频报价",
    "非报备图文/视频单品报价",
    "报备视频、图文/单品报价",
    "4月报备图文价格",
    "5月报备图文价格",
    "报备返点",
    "本月下单是否保价次月执行",
    "是否可保价5月",
    "排竞时长",
    "是否有免费分发平台",
    "全渠道授权及时长",
    "笔记默认保留时长",
    "评论区置顶",
    "素材收集要求",
    "非商用授权",
    "作品保留",
    "所在地区是否可以正常收发快递",
    "商用授权",
    "可同步平台",
    "尺码",
    "报价更新时间",
)
BUSINESS_ID_EXTRACTION_PROMPT = """你是 OpenClaw Media bot 的【商务>ID】字段清洗器。

目标：把达人主页分享、商务合作话术、品牌 Brief、报价确认信息清洗成可写入飞书的 JSON 字段。

只返回合法 JSON object，不要 Markdown。JSON 结构：
{
  "status": "done 或 pending_manual",
  "confidence": 0.0,
  "reason": "一句话说明",
  "evidence": "引用输入中的关键证据，简短即可",
  "fields": {
    "作者ID": "",
    "账号名称": "",
    "平台": "",
    "主页链接": "",
    "分享链接": "",
    "项目": "",
    "品牌": "",
    "产品": "",
    "Brief链接": "",
    "Brief附件路径": "",
    "Brief关键入库信息": "",
    "Brief告知类信息": "",
    "Brief原文": "",
    "Brief收集状态": "",
    "档期": "",
    "具体档期": "",
    "合作流程": "",
    "图文报价": "",
    "视频报价": "",
    "非报备图文/视频单品报价": "",
    "报备视频、图文/单品报价": "",
    "4月报备图文价格": "",
    "5月报备图文价格": "",
    "报备返点": "",
    "本月下单是否保价次月执行": "",
    "是否可保价5月": "",
    "排竞时长": "",
    "是否有免费分发平台": "",
    "全渠道授权及时长": "",
    "笔记默认保留时长": "",
    "评论区置顶": "",
    "素材收集要求": "",
    "需反问博主字段": "",
    "反问博主话术": "",
    "反问博主状态": "",
    "非商用授权": "",
    "作品保留": "",
    "所在地区是否可以正常收发快递": "",
    "商用授权": "",
    "可同步平台": "",
    "尺码": "",
    "待补充字段": "",
    "给品牌方信息": "",
    "沟通开场": ""
  },
  "pending_fields": [],
  "confirmation_fields": []
}

硬性规则：
- 主体字段必须来自输入证据；不确定就留空，并放入 pending_fields。
- 不要用固定默认值补字段，例如不要默认填“3个月”“2年”“待补充”。
- 不要把项目名机械复制成品牌/产品；只有文本能判断时才填。
- 需反问博主字段、反问博主话术、给品牌方信息也必须由你根据输入生成；信息不可靠时标记 pending_manual。
- URL 候选只用于辅助区分主页链接、分享链接、Brief链接；不要编造链接。
- 如果无法可信抽取核心商务字段，status 设为 pending_manual，并说明还缺什么。
"""

BUSINESS_REPLY_PROMPT = """你是 OpenClaw Media bot 的【商务>ID】商务回复助手。

任务：基于已经查表后的当前字段，生成用户可直接使用的商务回复。只返回合法 JSON object，不要 Markdown。

JSON 结构：
{
  "status": "done 或 pending_manual",
  "reply": "可直接发送的中文回复",
  "missing_fields": ["仍需补充的字段"],
  "evidence": "你使用了哪些字段或查表结果"
}

硬性规则：
- 你只能使用输入 JSON 中的 current_fields 和 history_lookup；不要编造表里没有的报价、返点、档期、保价、授权。
- 报价是达人账号/平台级信息，不按品牌或项目绑定；如果 current_fields 里有图文报价/视频报价，应直接作为当前账号报价使用。
- 如果报价来自历史表字段，要自然说明“当前表内报价为...”，不要说成用户刚刚提供。
- 如果仍缺返点、档期、保价、授权等字段，回复里要明确向博主补问。
- 如果 current_fields 没有报备返点，但业务回复需要给初期谈判口径，可以用 30% 作为初期返点锚点；必须表达为“先按 30% 沟通/锚定/可谈”，不得写成表内已确认返点。
- reply 不能只是字段清单；必须包含“后续怎么谈”的可执行沟通建议，例如先用账号级报价报价，再用 30% 返点锚定，随后确认档期、保价、授权范围和授权时长。
- 如果 06 命中但 05 未命中，说明已识别账号，但没有查到历史商务/报价记录。
- 如果 05 命中但报价字段为空，说明历史商务记录中报价为空。
- 不要输出固定模板；根据字段内容组织回复。
"""

BusinessLlmExtractor = Callable[..., dict[str, Any]]


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def business_now_iso() -> str:
    return datetime.now(LOCAL_TZ).replace(microsecond=0).isoformat()


def load_id_business_env_files() -> None:
    load_default_env_files()
    for path in (MEDIA_ROOT / ".env", MEDIA_ROOT / ".env.local"):
        load_env_file(path)


def normalize_label(label: str) -> str:
    cleaned = re.sub(r"\s+", "", label.strip().strip("：:"))
    cleaned = cleaned.strip("【】[]")
    cleaned_base = re.sub(r"[（(].*?(?:[）)]|$)", "", cleaned)
    mapped = LABEL_ALIASES.get(cleaned) or LABEL_ALIASES.get(cleaned_base)
    if mapped:
        return mapped
    if re.match(r"^\d{1,2}月份?报备图文价格$", cleaned_base):
        month = re.match(r"^(\d{1,2})月份?报备图文价格$", cleaned_base).group(1)
        return f"{month}月报备图文价格"
    if cleaned_base.endswith("图文报价") or cleaned_base.endswith("图文单品报价"):
        return "图文报价"
    if cleaned_base.endswith("视频报价") or cleaned_base.endswith("视频单品报价"):
        return "视频报价"
    return cleaned_base


def parse_count(value: str) -> int | None:
    match = COUNT_RE.search(value.replace(",", ""))
    if not match:
        return None
    number = float(match.group("number"))
    unit = match.group("unit").lower()
    multiplier = 1
    if unit == "k" or unit == "千":
        multiplier = 1_000
    elif unit == "m":
        multiplier = 1_000_000
    elif unit in {"w", "万"}:
        multiplier = 10_000
    return int(number * multiplier)


def extract_labeled_fields(text: str) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, str] = {}
    pending: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*\d+\s*[、.．]\s*", "", line)
        match = re.match(r"^【(?P<label>[^】]+)】\s*[：:]\s*(?P<value>.*)$", line)
        if not match:
            match = re.match(r"^(?P<label>[^：:]{1,120})[：:]\s*(?P<value>.*)$", line)
        if match:
            label = normalize_label(match.group("label"))
            value = match.group("value").strip()
            if label in FIELD_SPECS:
                if value:
                    fields[label] = value
                elif not fields.get(label):
                    pending.append(label)
            continue
        compact = re.sub(r"\s+", "", line)
        matched_compact_label = False
        for label in ("非商用授权", "商用授权", "作品保留"):
            if compact.startswith(label) and len(compact) > len(label):
                fields[label] = line[len(label) :].strip(" ：:，,")
                matched_compact_label = True
                break
        if matched_compact_label:
            continue
        if re.search(r"女码|男码|尺码|码数|最小\d+|最大\d+", line):
            fields.setdefault("尺码", line)
    if fields.get("档期") and not fields.get("具体档期"):
        fields["具体档期"] = fields["档期"]
    pending = [label for label in pending if not fields.get(label)]
    return fields, sorted(set(pending))


def enrich_brief_structured_fields(text: str, fields: dict[str, str], pending: list[str]) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    for index, raw_line in enumerate(lines):
        if not raw_line:
            continue
        line = re.sub(r"^\s*\d+\s*[、.．]\s*", "", raw_line)
        match = re.match(r"^【?(?P<label>[^】：:]{1,140})】?\s*[：:]\s*(?P<value>.*)$", line)
        if not match:
            continue
        normalized = normalize_label(match.group("label"))
        value = match.group("value").strip()
        if normalized == "全渠道授权及时长" and not value:
            bullets: list[str] = []
            for next_line in lines[index + 1 :]:
                if not next_line:
                    continue
                if re.match(r"^\s*\d+\s*[、.．]\s*", next_line):
                    break
                if re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", next_line):
                    bullets.append(next_line)
            if bullets:
                hint_match = re.search(r"[（(]([^）)]+)[）)]", match.group("label"))
                hint = hint_match.group(1).strip() if hint_match else ""
                fields["全渠道授权及时长"] = "\n".join(([hint] if hint else []) + bullets)
        elif normalized == "素材收集要求" and not value:
            fields["素材收集要求"] = "纯净版和发布版"
    return sorted({label for label in pending if not fields.get(label)})


def strip_trigger(text: str) -> str:
    raw = text.strip()
    match = BUSINESS_TRIGGER_RE.match(raw)
    if not match:
        return raw
    body = raw[match.end() :].strip()
    author = str(match.group("author") or "").strip()
    if author:
        author_line = f"作者ID：{author}"
        return f"{author_line}\n{body}" if body else author_line
    return body


def has_id_business_trigger(text: str) -> bool:
    return bool(BUSINESS_TRIGGER_RE.match(text or ""))


def is_profile_url(url: str) -> bool:
    lower = (url or "").lower()
    return any(domain in lower for domain in ("xhslink.com", "xiaohongshu.com", "douyin.com", "iesdouyin.com"))


def split_business_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    profile_urls: list[str] = []
    brief_urls: list[str] = []
    for url in urls:
        if is_profile_url(url):
            profile_urls.append(url)
        else:
            brief_urls.append(url)
    return profile_urls, brief_urls


def infer_author_id(body: str, fields: dict[str, str]) -> str:
    if fields.get("作者ID"):
        return fields["作者ID"].strip()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line_without_urls = re.sub(r"https?://\S+", "", line).strip()
        if not line_without_urls:
            continue
        if re.match(r"^【[^】]+】\s*[：:]", line_without_urls) or re.match(r"^[^：:]{1,40}[：:]", line_without_urls):
            continue
        match = re.match(r"^(?P<id>[A-Za-z0-9_\-\u4e00-\u9fff]{1,12})\s+(.+)$", line_without_urls)
        if match and any(keyword in line_without_urls for keyword in ("小红书", "抖音", "平台", "品牌", "主页", "商务")):
            return match.group("id")
        if any(keyword in line_without_urls for keyword in ("我在小红书", "打开抖音", "长按复制", "哈喽", "补充以下", "合作信息")):
            continue
        if re.search(r"[，。；;：:、,]", line_without_urls):
            continue
        if len(line_without_urls) <= 12:
            return line_without_urls
    return ""


def detect_platform_cn(text: str, urls: list[str], fields: dict[str, str]) -> str:
    explicit = fields.get("平台", "").strip()
    if explicit:
        if explicit.lower() in {"xhs", "rednote", "xiaohongshu"} or "小红书" in explicit:
            return "小红书"
        if explicit.lower() in {"douyin", "tiktok"} or "抖音" in explicit:
            return "抖音"
        return explicit
    combined = "\n".join([text, *urls]).lower()
    if "xhslink.com" in combined or "xiaohongshu.com" in combined or "小红书" in text:
        return "小红书"
    if "douyin.com" in combined or "iesdouyin.com" in combined or "抖音" in text:
        return "抖音"
    platform = detect_platform(urls[0]) if urls else "unknown"
    return {"xiaohongshu": "小红书", "douyin": "抖音"}.get(platform, "未识别")


def metrics_from_text(text: str) -> dict[str, int]:
    metrics: dict[str, int] = {}
    patterns = [
        ("赞藏总数", r"收获了\s*([\d.,]+(?:\s*[kKmMwW万千])?)\s*次赞与收藏"),
        ("获赞数", r"(?:获赞|点赞)\s*(?:约)?\s*([\d.,]+(?:\s*[kKmMwW万千])?)"),
        ("粉丝数", r"粉丝\s*(?:数)?\s*(?:约)?\s*([\d.,]+(?:\s*[kKmMwW万千])?)"),
        ("关注数", r"关注\s*(?:数)?\s*(?:约)?\s*([\d.,]+(?:\s*[kKmMwW万千])?)"),
        ("作品数", r"作品\s*(?:数)?\s*(?:约)?\s*([\d.,]+(?:\s*[kKmMwW万千])?)"),
    ]
    for field, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        parsed = parse_count(match.group(1))
        if parsed is not None:
            metrics[field] = parsed
    return metrics


def sanitize_stem(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value.strip(), flags=re.UNICODE).strip("-._")
    return cleaned[:80] or "creator"


def load_cookie_candidates(platform: str) -> list[Path]:
    if platform == "小红书":
        return [
            SELFMEDIA_ROOT / "integrations" / "platform_auth" / "cookies" / "private" / "xiaohongshu-cookies.json",
            SELFMEDIA_ROOT / "selfmedia" / "ingest" / "content_flow" / "private" / "xiaohongshu-cookies.json",
            Path(os.getenv("XIAOHONGSHU_COOKIES_JSON_PATH", "")),
        ]
    if platform == "抖音":
        return [
            SELFMEDIA_ROOT / "integrations" / "platform_auth" / "cookies" / "private" / "douyin-cookies.json",
            SELFMEDIA_ROOT / "selfmedia" / "ingest" / "content_flow" / "private" / "douyin-cookies.json",
            Path(os.getenv("DOUYIN_COOKIES_JSON_PATH", "")),
        ]
    return []


def load_playwright_cookies(platform: str) -> list[dict[str, Any]]:
    for path in load_cookie_candidates(platform):
        if not str(path) or not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cookies = data if isinstance(data, list) else data.get("cookies") if isinstance(data, dict) else []
        if not isinstance(cookies, list):
            continue
        normalized = []
        for cookie in cookies:
            if not isinstance(cookie, dict) or not cookie.get("name") or not cookie.get("value"):
                continue
            item = {
                "name": str(cookie["name"]),
                "value": str(cookie["value"]),
                "domain": str(cookie.get("domain") or ""),
                "path": str(cookie.get("path") or "/"),
            }
            if cookie.get("expires") not in (None, "", -1):
                try:
                    item["expires"] = int(float(cookie["expires"]))
                except (TypeError, ValueError):
                    pass
            if item["domain"]:
                normalized.append(item)
        if normalized:
            return normalized
    return []


def capture_profile(url: str, platform: str, account_name: str = "") -> dict[str, Any]:
    if not url:
        return {"ok": False, "status": "missing_url", "error": "缺少主页链接"}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"ok": False, "status": "playwright_unavailable", "error": str(exc)}

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SCREENSHOT_DIR / f"{stamp}-{sanitize_stem(platform)}-{sanitize_stem(account_name or url[:30])}.png"
    body_text = ""
    final_url = url
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 1800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            cookies = load_playwright_cookies(platform)
            if cookies:
                context.add_cookies(cookies)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(5_000)
            final_url = page.url
            try:
                body_text = page.locator("body").inner_text(timeout=5_000)
            except Exception:
                body_text = ""
            page.screenshot(path=str(path), full_page=False, timeout=20_000, animations="disabled")
            browser.close()
    except Exception as exc:
        return {"ok": False, "status": "capture_failed", "error": str(exc), "path": str(path)}
    if not path.exists() or path.stat().st_size <= 0:
        return {"ok": False, "status": "empty_screenshot", "error": "截图文件为空", "path": str(path)}
    return {
        "ok": True,
        "status": "captured",
        "path": str(path),
        "final_url": final_url,
        "visible_text": body_text[:6000],
        "metrics": metrics_from_text(body_text),
    }


def build_brand_brief(fields: dict[str, Any], pending: list[str]) -> str:
    def get(name: str, default: str = "待补充") -> str:
        value = fields.get(name)
        text = str(value).strip() if value not in (None, "") else ""
        return text or default

    lines = [
        f"平台：{get('平台')}",
        f"作者ID：{get('作者ID')}",
        f"账号：{get('账号名称')}",
        f"账号数据：{get('账号数据摘要')}",
        f"项目：{get('项目')}",
        f"Brief：{get('Brief链接')}",
        f"品牌/产品：{get('品牌')} / {get('产品')}",
        f"合作流程：{get('合作流程')}",
        f"档期：{get('具体档期', get('档期'))}",
        f"4月报备图文价格：{get('4月报备图文价格')}",
        f"5月报备图文价格：{get('5月报备图文价格')}",
        f"图文报价：{get('图文报价')}",
        f"视频报价：{get('视频报价')}",
        f"非报备图文/视频单品报价：{get('非报备图文/视频单品报价')}",
        f"报备视频、图文/单品报价：{get('报备视频、图文/单品报价')}",
        f"报备返点：{get('报备返点')}",
        f"保价次月执行：{get('本月下单是否保价次月执行')}",
        f"是否可保价5月：{get('是否可保价5月')}",
        f"排竞时长：{get('排竞时长')}",
        f"非商用授权：{get('非商用授权', '3个月')}",
        f"商用授权：{get('商用授权', '3个月')}",
        f"全渠道授权及时长：{get('全渠道授权及时长')}",
        f"作品保留：{get('作品保留', '2年')}",
        f"笔记默认保留时长：{get('笔记默认保留时长')}",
        f"可同步平台：{get('可同步平台')}",
        f"是否有免费分发平台：{get('是否有免费分发平台')}",
        f"尺码：{get('尺码')}",
        f"收发快递：{get('所在地区是否可以正常收发快递')}",
        f"评论区置顶：{get('评论区置顶')}",
        f"素材收集要求：{get('素材收集要求')}",
    ]
    if pending:
        lines.append("待补充字段：" + "、".join(pending))
    if fields.get("需反问博主字段"):
        lines.append("不要直接回复品牌方：以下字段需先反问博主确认：" + str(fields["需反问博主字段"]))
    return "\n".join(lines)


def account_data_summary(fields: dict[str, Any]) -> str:
    parts = []
    for name in ("赞藏总数", "获赞数", "粉丝数", "关注数", "作品数"):
        value = fields.get(name)
        if value not in (None, ""):
            parts.append(f"{name}：{int(value) if isinstance(value, float) and value.is_integer() else value}")
    return "；".join(parts)


def display_creator_name(fields: dict[str, Any], record_id: str = "") -> str:
    return (
        feishu_plain_text(fields.get("作者ID"))
        or feishu_plain_text(fields.get("账号名称"))
        or record_id
        or "未命名账号"
    )


def canonical_confirmation_field(name: str) -> str:
    return CONFIRMATION_CANONICAL.get(name, name)


def uncertain_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    return bool(AMBIGUOUS_VALUE_RE.search(text))


def blank_confirmation_labels(body: str) -> set[str]:
    labels: set[str] = set()
    for raw_line in body.splitlines():
        line = re.sub(r"^\s*\d+\s*[、.．]\s*", "", raw_line.strip())
        if not line:
            continue
        match = re.match(r"^【?(?P<label>[^】：:]{1,140})】?\s*[：:]\s*(?P<value>.*)$", line)
        if not match:
            continue
        label = canonical_confirmation_field(normalize_label(match.group("label")))
        value = match.group("value").strip()
        if label in CONFIRMATION_FIELDS and not value:
            labels.add(label)
    return labels


def confirmation_required_fields(body: str, fields: dict[str, Any], pending: list[str]) -> list[str]:
    required: set[str] = {canonical_confirmation_field(label) for label in pending}
    required.update(blank_confirmation_labels(body))
    for label in list(CONFIRMATION_FIELDS):
        if label in required:
            continue
        if label in fields and uncertain_value(fields.get(label)):
            required.add(label)
    if (fields.get("具体档期") or fields.get("档期")) and "具体档期" in required and not uncertain_value(fields.get("具体档期") or fields.get("档期")):
        required.discard("具体档期")
    return [label for label in sorted(required) if label in CONFIRMATION_FIELDS]


def build_creator_question_text(fields: dict[str, Any], confirmation_fields: list[str]) -> str:
    if not confirmation_fields:
        return ""
    creator = display_creator_name(fields)
    project = feishu_plain_text(fields.get("项目") or fields.get("品牌") or fields.get("产品"))
    lines = [
        "【商务>ID】需要先反问博主确认",
        f"作者ID：{creator}",
    ]
    if project:
        lines.append(f"项目：{project}")
    lines.append("以下信息不确定，不能直接粘贴给品牌方；请先向博主确认：")
    for index, field in enumerate(confirmation_fields, start=1):
        question = QUESTION_TEMPLATES.get(field, f"{field} 请确认。")
        lines.append(f"{index}. {field}：{question}")
    return "\n".join(lines)


def add_creator_confirmation_fields(body: str, fields: dict[str, Any], pending: list[str]) -> list[str]:
    confirmation_fields = confirmation_required_fields(body, fields, pending)
    if confirmation_fields:
        fields["需反问博主字段"] = "、".join(confirmation_fields)
        fields["反问博主话术"] = build_creator_question_text(fields, confirmation_fields)
        fields["反问博主状态"] = "pending"
    return confirmation_fields


def extract_project_short_name(project: str) -> str:
    return re.split(r"[（(]", project.strip(), maxsplit=1)[0].strip()


def classify_brief_lines(body: str) -> tuple[list[str], list[str]]:
    key_lines: list[str] = []
    notice_lines: list[str] = []
    notice_keywords = ("宝，", "宝,", "觉得你的账号", "将你提报", "有意向的话", "辛苦完善", "目前有一个项目")
    key_keywords = (
        "brief",
        "Brief",
        "PDF",
        "pdf",
        "模板",
        "必看",
        "严格按照",
        "项目",
        "报价",
        "返点",
        "保价",
        "排竞",
        "档期",
        "分发",
        "授权",
        "笔记",
        "置顶",
        "素材",
        "纯净版",
        "发布版",
    )
    for raw_line in body.splitlines():
        line = raw_line.strip().strip("=")
        if not line:
            continue
        line = re.sub(r"^\s*\d+\s*[、.．]\s*", "", line)
        if any(keyword in line for keyword in notice_keywords):
            notice_lines.append(line)
            continue
        normalized = ""
        match = re.match(r"^【?(?P<label>[^】：:]{1,140})】?\s*[：:]\s*(?P<value>.*)$", line)
        if match:
            normalized = normalize_label(match.group("label"))
        if normalized in FIELD_SPECS or re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", line) or any(keyword in line for keyword in key_keywords):
            key_lines.append(line)
            continue
        if extract_urls([line]):
            key_lines.append(line)
        else:
            notice_lines.append(line)
    return key_lines, notice_lines


def add_brief_fields(fields: dict[str, Any], body: str, brief_urls: list[str], brief_files: list[str]) -> None:
    has_brief_context = bool(
        brief_urls
        or brief_files
        or re.search(r"brief|Brief|PDF|pdf|模板|图文要求|撰写模板|严格按照|项目：|项目:", body)
    )
    if not has_brief_context:
        return
    if brief_urls:
        fields["Brief链接"] = "\n".join(brief_urls)
    if brief_files:
        fields["Brief附件路径"] = "\n".join(brief_files)
    key_lines, notice_lines = classify_brief_lines(body)
    author_id = str(fields.get("作者ID") or "").strip()
    if author_id:
        notice_lines = [line for line in notice_lines if line.strip() != author_id]
    if key_lines:
        fields["Brief关键入库信息"] = "\n".join(dict.fromkeys(key_lines))
    if notice_lines:
        fields["Brief告知类信息"] = "\n".join(dict.fromkeys(notice_lines))
    fields["Brief原文"] = body
    fields["Brief收集状态"] = "collected"


def _business_text_value(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [_business_text_value(item) for item in value]
        return "、".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _business_list_value(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_business_list_value(item))
        return result
    text = _business_text_value(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[、,，;；\n]+", text) if item.strip()]


def _business_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _business_llm_status(value: Any) -> str:
    status = str(value or "done").strip().lower()
    if status in {"ok", "success", "succeeded", "complete", "completed"}:
        return "done"
    if status in {"pending", "manual", "pending_manual", "needs_review", "need_review"}:
        return "pending_manual"
    return status or "pending_manual"


def extract_business_fields_with_llm(
    *,
    raw_text: str,
    body: str,
    profile_url: str,
    account_name: str,
    brief_files: list[str],
    urls: list[str],
    profile_urls: list[str],
    brief_urls: list[str],
) -> dict[str, Any]:
    settings = load_content_cleaner_llm_settings()
    if not settings.enabled:
        return {"status": "pending_manual", "reason": f"{BUSINESS_LLM_PROFILE_NAME} 已禁用"}
    payload = {
        "trigger": "【商务>ID】",
        "raw_text": raw_text,
        "body": body,
        "hints": {
            "profile_url": profile_url,
            "account_name": account_name,
            "brief_files": brief_files,
            "urls": urls,
            "profile_urls": profile_urls,
            "brief_urls": brief_urls,
        },
        "allowed_fields": BUSINESS_LLM_FIELD_NAMES,
    }
    max_chars = max(2000, int(settings.max_chars))
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(payload_text) > max_chars:
        payload["raw_text"] = raw_text[: max_chars // 2]
        payload["body"] = body[: max_chars // 2]
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    return generate_json_from_parts(
        [{"text": BUSINESS_ID_EXTRACTION_PROMPT}, {"text": payload_text}],
        settings.provider,
        max_retries=1,
        error_prefix="商务>ID LLM 字段抽取失败",
    )


def generate_business_reply_from_current_fields(
    fields: dict[str, Any],
    *,
    history_lookup: dict[str, Any],
    pending_fields: list[str],
) -> dict[str, Any]:
    settings = load_content_cleaner_llm_settings()
    if not settings.enabled:
        return {"status": "pending_manual", "reason": f"{BUSINESS_LLM_PROFILE_NAME} 已禁用"}
    current_fields = {
        name: _field_text(fields, name)
        for name in (
            "作者ID",
            "账号名称",
            "平台",
            "平台ID",
            "主页链接",
            "项目",
            "品牌",
            "产品",
            "图文报价",
            "视频报价",
            "非报备图文/视频单品报价",
            "报备视频、图文/单品报价",
            "报备返点",
            "具体档期",
            "档期",
            "本月下单是否保价次月执行",
            "是否可保价5月",
            "全渠道授权及时长",
            "非商用授权",
            "商用授权",
            "给品牌方信息",
            "待补充字段",
        )
        if _field_text(fields, name)
    }
    payload = {
        "current_fields": current_fields,
        "pending_fields": pending_fields,
        "history_lookup": history_lookup,
        "reply_boundary": "只能基于 current_fields/history_lookup 生成回复；报价按账号/平台级别使用，不按项目绑定。",
    }
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    max_chars = max(2000, int(settings.max_chars))
    if len(payload_text) > max_chars:
        payload["history_lookup"] = {"truncated": True, "summary": history_lookup}
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)[:max_chars]
    result = generate_json_from_parts(
        [{"text": BUSINESS_REPLY_PROMPT}, {"text": payload_text}],
        settings.provider,
        max_retries=1,
        error_prefix="商务>ID LLM 回复生成失败",
    )
    if not isinstance(result, dict):
        return {"status": "pending_manual", "reason": "商务>ID LLM 回复未返回 JSON object"}
    reply = _business_text_value(result.get("reply"))
    return {
        "status": _business_llm_status(result.get("status")),
        "reply": reply,
        "missing_fields": _business_list_value(result.get("missing_fields")),
        "evidence": _business_text_value(result.get("evidence")),
        "raw": result,
    }


def normalize_business_llm_result(
    payload: dict[str, Any],
    *,
    body: str,
    urls: list[str],
    profile_urls: list[str],
    brief_urls: list[str],
    brief_files: list[str],
    profile_url: str,
    account_name: str,
    screenshot_path: str,
) -> dict[str, Any]:
    raw_fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    if not raw_fields:
        raw_fields = {key: payload.get(key) for key in BUSINESS_LLM_FIELD_NAMES if key in payload}

    fields: dict[str, Any] = {}
    for key in BUSINESS_LLM_FIELD_NAMES:
        value = _business_text_value(raw_fields.get(key))
        if value:
            fields[key] = value

    pending_fields = _business_list_value(payload.get("pending_fields") or raw_fields.get("pending_fields"))
    if not pending_fields:
        pending_fields = _business_list_value(fields.get("待补充字段"))
    confirmation_fields = _business_list_value(payload.get("confirmation_fields") or raw_fields.get("confirmation_fields"))
    if not confirmation_fields:
        confirmation_fields = _business_list_value(fields.get("需反问博主字段"))

    if account_name and not fields.get("账号名称"):
        fields["账号名称"] = account_name
    if profile_urls:
        fields.setdefault("主页链接", profile_urls[0])
        fields.setdefault("分享链接", profile_urls[0])
    elif profile_url:
        fields.setdefault("主页链接", profile_url)
        fields.setdefault("分享链接", profile_url)
    if brief_urls and not fields.get("Brief链接"):
        fields["Brief链接"] = "\n".join(brief_urls)
    if brief_files and not fields.get("Brief附件路径"):
        fields["Brief附件路径"] = "\n".join(brief_files)
    if screenshot_path:
        fields["主页截图路径"] = screenshot_path
        fields["截图状态"] = "manual_screenshot"

    confidence = _business_confidence(payload.get("confidence"))
    status = _business_llm_status(payload.get("status"))
    reason = _business_text_value(payload.get("reason"))
    if status == "done" and confidence < BUSINESS_LLM_MIN_CONFIDENCE:
        status = "pending_manual"
        reason = reason or f"LLM 置信度 {confidence:.2f} 低于 {BUSINESS_LLM_MIN_CONFIDENCE:.2f}"
    if status == "done" and not any(_business_text_value(fields.get(name)) for name in BUSINESS_LLM_SIGNAL_FIELDS):
        status = "pending_manual"
        reason = reason or "LLM 未产出可校验的商务核心字段"

    fields["分享原文"] = body
    fields["商务原文"] = body
    fields["更新时间"] = business_now_iso()
    fields["最近状态"] = "llm_parsed" if status == "done" else "llm_pending_manual"
    fields["启用"] = True
    fields.update(metrics_from_text(body))
    if any(fields.get(name) for name in ("图文报价", "视频报价", "非报备图文/视频单品报价", "报备视频、图文/单品报价")):
        fields["报价更新时间"] = business_now_iso()
    if pending_fields:
        fields["待补充字段"] = "、".join(dict.fromkeys(pending_fields))
    if confirmation_fields:
        fields.setdefault("需反问博主字段", "、".join(dict.fromkeys(confirmation_fields)))
        fields.setdefault("反问博主状态", "pending")
    if status != "done":
        fields["最近错误"] = reason or "商务>ID LLM 字段抽取待人工确认"

    details = {
        "urls": urls,
        "profile_urls": profile_urls,
        "brief_urls": brief_urls,
        "brief_files": brief_files,
        "pending_fields": pending_fields,
        "confirmation_fields": confirmation_fields,
        "llm": {
            "profile": BUSINESS_LLM_PROFILE_NAME,
            "status": status,
            "confidence": confidence,
            "reason": reason,
            "evidence": _business_text_value(payload.get("evidence")),
        },
        "parsed_at": business_now_iso(),
    }
    return {
        "status": status,
        "reason": reason,
        "fields": fields,
        "details": details,
        "pending_fields": pending_fields,
        "confirmation_fields": confirmation_fields,
        "urls": urls,
        "profile_urls": profile_urls,
        "brief_urls": brief_urls,
        "llm": payload,
    }


def parse_business_text(
    text: str,
    *,
    screenshot_path: str = "",
    account_name: str = "",
    profile_url: str = "",
    brief_files: list[str] | None = None,
    llm_extractor: BusinessLlmExtractor | None = None,
) -> dict[str, Any]:
    raw_text = text.strip()
    body = strip_trigger(raw_text)
    urls = extract_urls([body, profile_url])
    profile_urls, brief_urls = split_business_urls(urls)
    if profile_url and profile_url not in profile_urls:
        profile_urls.insert(0, profile_url)
    extractor = llm_extractor or extract_business_fields_with_llm
    try:
        llm_payload = extractor(
            raw_text=raw_text,
            body=body,
            profile_url=profile_url,
            account_name=account_name,
            brief_files=brief_files or [],
            urls=urls,
            profile_urls=profile_urls,
            brief_urls=brief_urls,
        )
    except Exception as exc:
        llm_payload = {"status": "pending_manual", "reason": f"商务>ID LLM 字段抽取失败：{exc}", "confidence": 0}
    return normalize_business_llm_result(
        llm_payload if isinstance(llm_payload, dict) else {"status": "pending_manual", "reason": "商务>ID LLM 未返回 JSON object"},
        body=body,
        urls=urls,
        profile_urls=profile_urls,
        brief_urls=brief_urls,
        brief_files=brief_files or [],
        profile_url=profile_url,
        account_name=account_name,
        screenshot_path=screenshot_path,
    )




def table_url_from_args(value: str = "") -> str:
    if value.strip():
        raise RuntimeError("--feishu-url is not supported; configure the Media Model v2 Feishu URLs through environment variables")
    return feishu_table_url_from_env(*URL_ENV_NAMES)


def opportunity_table_url() -> str:
    return feishu_table_url_from_env(*OPPORTUNITY_URL_ENV_NAMES)


def creator_profile_table_url() -> str:
    return feishu_table_url_from_env(*CREATOR_PROFILE_URL_ENV_NAMES)


def parse_quote_amount(value: Any) -> float | None:
    text = feishu_plain_text(value).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def safe_entity_part(value: Any, default: str = "item") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text, flags=re.IGNORECASE)
    return re.sub(r"_+", "_", text).strip("_") or default


def business_account_id_from_fields(fields: dict[str, Any]) -> str:
    platform = safe_entity_part(fields.get("平台") or "unknown")
    author = safe_entity_part(fields.get("作者ID") or fields.get("平台ID") or fields.get("账号名称") or "unknown")
    return f"business_account_{platform}_{author}"


def business_opportunity_id_from_fields(fields: dict[str, Any], business_account_id: str) -> str:
    source = "|".join(
        str(fields.get(name) or "").strip()
        for name in ("品牌", "产品", "项目", "Brief链接", "商务原文")
    )
    digest = hashlib.sha1(f"{business_account_id}|{source}".encode("utf-8")).hexdigest()[:16]
    return f"business_opportunity_{digest}"


def write_business_model_v2(fields: dict[str, Any], details: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    account_url = table_url_from_args("")
    opportunity_url = opportunity_table_url()
    if not account_url:
        raise RuntimeError("missing MEDIA_OS_BUSINESS_ACCOUNTS_V2_URL")
    if not opportunity_url:
        raise RuntimeError("missing MEDIA_OS_BUSINESS_OPPORTUNITIES_URL")
    author_id = _field_text(fields, "作者ID") or _field_text(fields, "平台ID") or _field_text(fields, "账号名称")
    account_name = _field_text(fields, "账号名称") or author_id
    platform = _field_text(fields, "平台") or "unknown"
    if not author_id or not account_name:
        raise RuntimeError("BusinessAccount requires 作者ID/账号名称")
    business_account_id = business_account_id_from_fields(fields)
    opportunity_id = business_opportunity_id_from_fields(fields, business_account_id)
    vault = MediaVault()
    vault.ensure_manifest()
    quote_artifact = vault.write_json_artifact(
        vault.business_dir(opportunity_id),
        "quote_snapshot.json",
        {
            "fields": fields,
            "details": details,
            "business_account_id": business_account_id,
            "opportunity_id": opportunity_id,
            "written_at": business_now_iso(),
        },
        owner_type="BusinessOpportunity",
        owner_id=opportunity_id,
        artifact_type="business_quote_snapshot",
    )
    quote_uri = str(quote_artifact.get("uri") or "")
    image_quote = parse_quote_amount(fields.get("图文报价") or fields.get("非报备图文/视频单品报价") or fields.get("报备视频、图文/单品报价"))
    video_quote = parse_quote_amount(fields.get("视频报价") or fields.get("非报备图文/视频单品报价") or fields.get("报备视频、图文/单品报价"))
    account_payload = build_business_account_payload(
        business_account_id=business_account_id,
        author_id=author_id,
        account_name_snapshot=account_name,
        platform=platform,
        current_image_quote_amount=image_quote,
        current_video_quote_amount=video_quote,
        quote_snapshot_uri=quote_uri,
    )
    brand = _field_text(fields, "品牌") or _field_text(fields, "项目") or "unknown_brand"
    opportunity_payload = build_business_opportunity_payload(
        opportunity_id=opportunity_id,
        business_account_id=business_account_id,
        brand=brand,
        product=_field_text(fields, "产品"),
        brief_link=_field_text(fields, "Brief链接"),
        current_quote_amount=image_quote or video_quote,
        rebate_ratio=_field_text(fields, "报备返点"),
        valid_from="",
        valid_until="",
        quote_snapshot_uri=quote_uri,
    )
    if dry_run:
        return {
            "mode": "dry_run",
            "business_account": account_payload,
            "business_opportunity": opportunity_payload,
            "quote_snapshot_uri": quote_uri,
        }
    account_write = upsert_entity_record("BusinessAccount", account_url, account_payload, key_field="business_account_id")
    opportunity_write = upsert_entity_record("BusinessOpportunity", opportunity_url, opportunity_payload, key_field="opportunity_id")
    return {
        "mode": "write",
        "business_account_id": business_account_id,
        "business_opportunity_id": opportunity_id,
        "quote_snapshot_uri": quote_uri,
        "writes": [account_write, opportunity_write],
    }


def field_urls(value: Any) -> list[str]:
    if isinstance(value, dict):
        return extract_urls([str(value.get("link") or ""), str(value.get("text") or "")])
    if isinstance(value, list):
        urls: list[str] = []
        for item in value:
            urls.extend(field_urls(item))
        return urls
    return extract_urls([feishu_plain_text(value)])


def same_record(fields: dict[str, Any], candidate: dict[str, Any]) -> bool:
    platform_id = str(fields.get("平台ID") or fields.get("平台账号ID") or "").strip()
    candidate_platform_id = feishu_plain_text(candidate.get("平台ID") or candidate.get("平台账号ID"))
    platform = str(fields.get("平台") or "").strip()
    candidate_platform = feishu_plain_text(candidate.get("平台"))
    if platform_id and candidate_platform_id:
        if platform and candidate_platform:
            return platform == candidate_platform and platform_id == candidate_platform_id
        return platform_id == candidate_platform_id
    urls = set()
    for name in ("主页链接", "分享链接"):
        urls.update(field_urls(fields.get(name)))
    candidate_urls = set()
    for name in ("主页链接", "分享链接"):
        candidate_urls.update(field_urls(candidate.get(name)))
    if urls and candidate_urls and urls.intersection(candidate_urls):
        return True
    author_id = str(fields.get("作者ID") or "").strip()
    account = str(fields.get("账号名称") or "").strip()
    if author_id and platform and author_id == feishu_plain_text(candidate.get("作者ID")) and platform == feishu_plain_text(candidate.get("平台")):
        return True
    return bool(account and platform and account == feishu_plain_text(candidate.get("账号名称")) and platform == feishu_plain_text(candidate.get("平台")))


def _field_text(fields: dict[str, Any], name: str) -> str:
    return feishu_plain_text(fields.get(name)).strip()


def _same_platform_or_unspecified(fields: dict[str, Any], candidate: dict[str, Any]) -> bool:
    platform = _field_text(fields, "平台")
    candidate_platform = _field_text(candidate, "平台")
    return not platform or not candidate_platform or platform == candidate_platform


def _identity_values(fields: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for name in ("博主IP", "账号名称", "作者ID", "平台ID"):
        value = _field_text(fields, name)
        if value:
            values.add(value)
    return values


def same_creator_profile(fields: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if not _same_platform_or_unspecified(fields, candidate):
        return False
    platform_id = _field_text(fields, "平台ID")
    candidate_platform_id = _field_text(candidate, "平台ID")
    if platform_id and candidate_platform_id and platform_id == candidate_platform_id:
        return True
    urls = set()
    for name in ("主页链接", "分享链接"):
        urls.update(field_urls(fields.get(name)))
    candidate_urls = set()
    for name in ("主页链接", "分享链接"):
        candidate_urls.update(field_urls(candidate.get(name)))
    if urls and candidate_urls and urls.intersection(candidate_urls):
        return True
    return bool(_identity_values(fields).intersection(_identity_values(candidate)))


def copy_missing_plain_fields(fields: dict[str, Any], source: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    copied: list[str] = []
    for name in names:
        if _field_text(fields, name):
            continue
        value = _field_text(source, name)
        if not value:
            continue
        fields[name] = value
        copied.append(name)
    return copied


def refresh_pending_fields_from_values(fields: dict[str, Any], parsed: dict[str, Any]) -> list[str]:
    pending = _business_list_value(fields.get("待补充字段") or parsed.get("pending_fields"))
    normalized = [canonical_confirmation_field(item) for item in pending]
    remaining = [item for item in normalized if item and not _field_text(fields, item)]
    fields["待补充字段"] = "、".join(dict.fromkeys(remaining))
    parsed["pending_fields"] = list(dict.fromkeys(remaining))
    confirmation = _business_list_value(fields.get("需反问博主字段") or parsed.get("confirmation_fields"))
    confirmation_remaining = [
        item
        for item in (canonical_confirmation_field(value) for value in confirmation)
        if item and not _field_text(fields, item)
    ]
    if confirmation_remaining:
        fields["需反问博主字段"] = "、".join(dict.fromkeys(confirmation_remaining))
        parsed["confirmation_fields"] = list(dict.fromkeys(confirmation_remaining))
    else:
        fields.pop("需反问博主字段", None)
        parsed["confirmation_fields"] = []
    return parsed["pending_fields"]


def enrich_business_fields_from_history(
    fields: dict[str, Any],
    *,
    business_url: str = "",
    creator_profiles_url: str = "",
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "creator_profiles": {"table": "06_CreatorProfiles_达人账号档案", "url_env": "MEDIA_OS_CREATOR_PROFILES_V2_URL", "matched": False, "copied_fields": []},
        "business_accounts": {"table": "05A_BusinessAccounts_商务账号", "url_env": "MEDIA_OS_BUSINESS_ACCOUNTS_V2_URL", "matched": False, "copied_fields": []},
    }
    if not creator_profiles_url and not business_url:
        return summary
    token = feishu_tenant_access_token()
    if creator_profiles_url:
        profiles = feishu_list_records(creator_profiles_url, token=token, page_size=500)
        profile = next((record for record in profiles if same_creator_profile_v2(fields, record.get("fields") or {})), None)
        summary["creator_profiles"]["record_count"] = len(profiles)
        if profile:
            profile_fields = profile.get("fields") or {}
            copied = copy_creator_profile_v2_fields(fields, profile_fields)
            summary["creator_profiles"].update({"matched": True, "record_id": profile.get("record_id") or "", "copied_fields": copied})
    if business_url:
        records = feishu_list_records(business_url, token=token, page_size=500)
        existing = next((record for record in records if same_business_account_v2(fields, record.get("fields") or {})), None)
        summary["business_accounts"]["record_count"] = len(records)
        if existing:
            existing_fields = existing.get("fields") or {}
            copied = copy_business_account_v2_fields(fields, existing_fields)
            summary["business_accounts"].update({"matched": True, "record_id": existing.get("record_id") or "", "copied_fields": copied})
    return summary


def same_creator_profile_v2(fields: dict[str, Any], candidate: dict[str, Any]) -> bool:
    platform = _field_text(fields, "平台")
    candidate_platform = _field_text(candidate, "platform")
    if platform and candidate_platform and platform != candidate_platform:
        return False
    author = _field_text(fields, "作者ID") or _field_text(fields, "平台ID")
    if author and author == _field_text(candidate, "author_id"):
        return True
    account = _field_text(fields, "账号名称")
    return bool(account and account == _field_text(candidate, "account_name"))


def same_business_account_v2(fields: dict[str, Any], candidate: dict[str, Any]) -> bool:
    platform = _field_text(fields, "平台")
    candidate_platform = _field_text(candidate, "platform")
    if platform and candidate_platform and platform != candidate_platform:
        return False
    author = _field_text(fields, "作者ID") or _field_text(fields, "平台ID")
    if author and author == _field_text(candidate, "author_id"):
        return True
    account = _field_text(fields, "账号名称")
    return bool(account and account == _field_text(candidate, "account_name_snapshot"))


def copy_creator_profile_v2_fields(fields: dict[str, Any], source: dict[str, Any]) -> list[str]:
    copied: list[str] = []
    mapping = {
        "platform": "平台",
        "author_id": "作者ID",
        "account_name": "账号名称",
        "identity_summary": "账号数据摘要",
    }
    for src, dst in mapping.items():
        if _field_text(fields, dst):
            continue
        value = _field_text(source, src)
        if value:
            fields[dst] = value
            copied.append(dst)
    return copied


def copy_business_account_v2_fields(fields: dict[str, Any], source: dict[str, Any]) -> list[str]:
    copied: list[str] = []
    mapping = {
        "platform": "平台",
        "author_id": "作者ID",
        "account_name_snapshot": "账号名称",
        "current_image_quote_amount": "图文报价",
        "current_video_quote_amount": "视频报价",
    }
    for src, dst in mapping.items():
        if _field_text(fields, dst):
            continue
        value = _field_text(source, src)
        if value:
            fields[dst] = value
            copied.append(dst)
    return copied


def coerce_for_feishu(fields: dict[str, Any], field_types: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in field_types or value in (None, "", []):
            continue
        if field_types[key] == 7:
            payload[key] = bool(value)
        else:
            coerced = feishu_coerce_value(value, field_types[key])
            if coerced not in (None, "", []):
                payload[key] = coerced
    return payload


def merge_standard_business_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_standard_fields(fields)
    return select_fields_for_write(fields, normalized_fields=normalized)


def save_local(payload: dict[str, Any]) -> str:
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    path = RECORD_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{sanitize_stem(str(payload.get('account_name') or 'id-business'))}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def smoke_ingest(args: argparse.Namespace, text: str) -> dict[str, Any]:
    body = strip_trigger(text)
    fields, pending = extract_labeled_fields(body)
    if not fields.get("作者ID"):
        project_index = body.find("项目")
        prefix = body[:project_index].strip() if project_index >= 0 else body.strip()
        prefix = re.sub(r"https?://\S+", "", prefix).strip(" ：:=，,、\n\t")
        if prefix and len(prefix) <= 32:
            fields["作者ID"] = prefix.split()[0]
    if not fields.get("项目"):
        match = re.search(r"项目\s*[：:=]\s*(?P<project>[^\n\r]+)", body)
        if match:
            fields["项目"] = match.group("project").strip()
    urls = extract_urls([body, args.profile_url])
    profile_urls, brief_urls = split_business_urls(urls)
    return {
        "ok": True,
        "mode": "smoke",
        "module": "selfmedia.business.id_business",
        "fields": {key: value for key, value in fields.items() if key in {"作者ID", "项目", "平台", "主页链接", "账号名称"}},
        "pending_labeled_fields": pending,
        "urls": urls,
        "profile_urls": profile_urls,
        "brief_urls": brief_urls,
        "write_policy": "no_feishu_write_no_llm_generation",
    }


def ingest(args: argparse.Namespace) -> dict[str, Any]:
    load_id_business_env_files()
    text = args.text or ""
    if args.stdin:
        text = sys.stdin.read()
    if not text.strip():
        raise SystemExit("missing text; pass --text or --stdin")
    if not has_id_business_trigger(text):
        raise SystemExit("商务>ID workflow requires explicit 【商务>ID】/【商务>作者ID】 trigger")
    if getattr(args, "smoke", False):
        return smoke_ingest(args, text)

    parsed = parse_business_text(
        text,
        screenshot_path=args.screenshot,
        account_name=args.account_name,
        profile_url=args.profile_url,
        brief_files=args.brief_file,
    )
    fields = parsed["fields"]
    table_url = table_url_from_args(args.feishu_url)
    history_lookup: dict[str, Any] = {}
    try:
        history_lookup = enrich_business_fields_from_history(
            fields,
            business_url=table_url,
            creator_profiles_url=creator_profile_table_url(),
        )
    except Exception as exc:
        history_lookup = {"ok": False, "error": str(exc)[:500]}
    details = parsed.get("details") if isinstance(parsed.get("details"), dict) else {}
    details["history_lookup"] = history_lookup
    remaining_pending = refresh_pending_fields_from_values(fields, parsed)
    try:
        ai_reply = generate_business_reply_from_current_fields(
            fields,
            history_lookup=history_lookup,
            pending_fields=remaining_pending,
        )
    except Exception as exc:
        ai_reply = {"status": "pending_manual", "reason": f"商务>ID LLM 回复生成失败：{exc}"}
    details["ai_reply"] = ai_reply
    if ai_reply.get("reply"):
        fields["AI回复话术"] = str(ai_reply.get("reply") or "").strip()
        if remaining_pending:
            fields["反问博主话术"] = fields["AI回复话术"]
    if parsed.get("status") != "done":
        local_path = save_local(
            {
                "status": "id_business_llm_pending_manual",
                "reason": parsed.get("reason") or "商务>ID LLM 字段抽取待人工确认",
                "fields": fields,
                "details": details,
                "account_name": display_creator_name(fields),
            }
        )
        return {
            "ok": False,
            "status": "id_business_llm_pending_manual",
            "reason": parsed.get("reason") or fields.get("最近错误") or "商务>ID LLM 字段抽取待人工确认",
            "fields": fields,
            "details": details,
            "feishu": {"ok": False, "skipped": True, "reason": "llm_pending_manual"},
            "local_path": local_path,
            "capture": {},
        }
    capture: dict[str, Any] = {}
    profile_url = str(fields.get("主页链接") or "").strip()
    if not args.no_screenshot and not args.screenshot and profile_url:
        capture = capture_profile(profile_url, str(fields.get("平台") or ""), display_creator_name(fields))
        fields["截图状态"] = capture.get("status", "")
        if capture.get("path"):
            fields["主页截图路径"] = capture["path"]
        if capture.get("final_url"):
            fields["主页链接"] = capture["final_url"]
        if capture.get("visible_text"):
            fields["主页可见文本"] = capture["visible_text"]
        if isinstance(capture.get("metrics"), dict):
            fields.update(capture["metrics"])
        if capture.get("ok"):
            fields["最近状态"] = "captured"
        else:
            fields["最近状态"] = "capture_failed"
            fields["最近错误"] = str(capture.get("error") or "")
    summary = account_data_summary(fields)
    if summary:
        fields["账号数据摘要"] = summary
    if args.require_feishu and not args.dry_run and not table_url:
        raise RuntimeError("缺少商务账号多维表格链接：设置 MEDIA_OS_BUSINESS_ACCOUNTS_V2_URL")
    confirmation_notify: dict[str, Any] = {}
    if args.notify_confirmation and fields.get("需反问博主字段") and fields.get("反问博主话术"):
        fields["反问博主时间"] = business_now_iso()
        confirmation_notify = notify_social(str(fields["反问博主话术"]), dry_run=args.dry_run)
        fields["反问博主状态"] = notify_delivery_status(confirmation_notify, dry_run=args.dry_run)
        fields["反问博主通知结果"] = json.dumps(confirmation_notify, ensure_ascii=False)[:3000]
    details = {
        "urls": parsed.get("urls") or [],
        "profile_urls": parsed.get("profile_urls") or [],
        "brief_urls": parsed.get("brief_urls") or [],
        "brief_files": args.brief_file or [],
        "pending_fields": parsed.get("pending_fields") or [],
        "confirmation_fields": (str(fields.get("需反问博主字段") or "").split("、") if fields.get("需反问博主字段") else []),
        "confirmation_notify": confirmation_notify,
        "capture": capture,
        "llm": (parsed.get("details") or {}).get("llm", {}) if isinstance(parsed.get("details"), dict) else {},
        "history_lookup": history_lookup,
        "ai_reply": ai_reply,
        "ingested_at": business_now_iso(),
    }

    feishu = write_business_model_v2(fields, details, dry_run=args.dry_run)
    local_path = save_local({"fields": fields, "details": details, "feishu": feishu, "capture": capture, "account_name": display_creator_name(fields)})
    return {
        "ok": True,
        "fields": fields,
        "details": details,
        "feishu": feishu,
        "local_path": local_path,
        "capture": capture,
    }


def parse_update_due(value: Any) -> bool:
    text = feishu_plain_text(value)
    if not text:
        return True
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            number = int(float(text))
            dt = datetime.fromtimestamp(number / 1000 if number > 10_000_000_000 else number, timezone.utc)
        except (TypeError, ValueError):
            return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt.astimezone(timezone.utc) >= timedelta(hours=24)


def local_today(value: str = ""):
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.now(LOCAL_TZ).date()


def quote_text(fields: dict[str, Any], name: str) -> str:
    return feishu_plain_text(fields.get(name)).strip()


def missing_quote_fields(fields: dict[str, Any]) -> list[str]:
    combined_quote = quote_text(fields, "非报备图文/视频单品报价") or quote_text(fields, "报备视频、图文/单品报价")
    missing: list[str] = []
    if not quote_text(fields, "图文报价") and not combined_quote:
        missing.append("图文报价")
    if not quote_text(fields, "视频报价") and not combined_quote:
        missing.append("视频报价")
    return missing


def monthly_quote_reminder_due(fields: dict[str, Any], *, today=None, reminder_day: int = 1) -> tuple[bool, list[str], str]:
    today = today or local_today()
    month_key = today.strftime("%Y-%m")
    missing = missing_quote_fields(fields)
    if today.day != reminder_day or not missing:
        return False, missing, month_key
    reminded_month = quote_text(fields, "报价提醒月份")
    return reminded_month != month_key, missing, month_key


def quote_reminder_message(fields: dict[str, Any], *, record_id: str, missing: list[str], month_key: str) -> str:
    platform = quote_text(fields, "平台") or "未识别平台"
    account = display_creator_name(fields, record_id)
    platform_account = quote_text(fields, "账号名称")
    brand = quote_text(fields, "品牌")
    missing_text = "、".join(missing)
    lines = [
        "【商务>ID】每月报价更新提醒",
        f"月份：{month_key}",
        f"平台：{platform}",
        f"作者ID：{account}",
    ]
    if platform_account and platform_account != account:
        lines.append(f"平台账号：{platform_account}")
    if brand:
        lines.append(f"最近品牌：{brand}")
    lines.extend(
        [
            f"缺少报价：{missing_text}",
            "请补充本月对应平台的图文报价和视频报价。",
            f"建议回复格式：{platform} 图文报价：；{platform} 视频报价：",
        ]
    )
    if record_id:
        lines.append(f"飞书记录 ID：{record_id}")
    return "\n".join(lines)


def notify_delivery_status(result: dict[str, Any], *, dry_run: bool = False) -> str:
    if dry_run:
        return "dry_run"
    if result.get("ok"):
        return "sent"
    if result.get("skipped"):
        return "notify_skipped"
    return "notify_failed"


def notify_social(message: str, *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"ok": False, "skipped": True, "reason": "dry_run", "message": message}
    target = next((os.getenv(name, "").strip() for name in NOTIFY_TARGET_ENV_NAMES if os.getenv(name, "").strip()), "")
    if not target:
        return {
            "ok": False,
            "skipped": True,
            "reason": "missing_notify_target",
            "required_env": list(NOTIFY_TARGET_ENV_NAMES),
            "message": message,
        }
    cmd = [
        "openclaw",
        "message",
        "send",
        "--channel",
        "feishu",
        "--account",
        "social",
        "--target",
        target,
        "--message",
        message,
        "--json",
    ]
    run_env = os.environ.copy()
    completed = run_openclaw_message_with_watchdog(cmd, timeout=1860, env=run_env)
    stdout_summary = summarize_openclaw_cli_output(completed.stdout)
    return {
        "ok": completed.returncode == 0,
        "command": cmd[:4],
        "stdout_summary": stdout_summary,
        "stderr": completed.stderr[-1000:],
    }


def run_openclaw_message_with_watchdog(cmd: list[str], *, timeout: int, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    heartbeat_seconds = max(10, int(float(os.getenv("ID_BUSINESS_NOTIFY_WATCHDOG_HEARTBEAT_SECONDS", "60"))))
    started_at = time.monotonic()
    process = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    watchdog_lines: list[str] = []
    while True:
        elapsed = time.monotonic() - started_at
        wait_for = min(float(heartbeat_seconds), max(0.1, float(timeout) - elapsed))
        try:
            stdout, stderr = process.communicate(timeout=wait_for)
            if watchdog_lines:
                stderr = "\n".join([*(line for line in watchdog_lines if line), stderr or ""]).strip()
            return subprocess.CompletedProcess(cmd, process.returncode, stdout or "", stderr or "")
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started_at
            if elapsed >= timeout:
                process.kill()
                stdout, stderr = process.communicate()
                watchdog_lines.append(f"[watchdog] timeout_after={int(elapsed)}s limit={timeout}s command={cmd[0]}")
                stderr = "\n".join([*(line for line in watchdog_lines if line), stderr or ""]).strip()
                return subprocess.CompletedProcess(cmd, -9, stdout or "", stderr)
            watchdog_lines.append(f"[watchdog] still_running elapsed={int(elapsed)}s command={cmd[0]}")


def summarize_openclaw_cli_output(stdout: str) -> str:
    text = (stdout or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
        payloads = result.get("payloads") if isinstance(result, dict) else None
        if isinstance(payloads, list):
            texts = [
                str(payload.get("text")).strip()
                for payload in payloads
                if isinstance(payload, dict) and payload.get("text")
            ]
            if texts:
                return "\n".join(texts)[:1000]
        meta = result.get("meta") if isinstance(result, dict) else None
        if isinstance(meta, dict):
            for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
                value = meta.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:1000]
        run_id = parsed.get("runId") or parsed.get("id") or ""
        status = parsed.get("status") or ""
        return f"OpenClaw structured output status={status} runId={run_id}".strip()[:1000]
    if text.startswith("{") or text.startswith("["):
        return "OpenClaw structured output without visible text"
    return text[-1000:]


def record_enabled(fields: dict[str, Any]) -> bool:
    if "启用" not in fields:
        return True
    return feishu_bool(fields.get("启用"), default=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="商务>ID creator profile and brand inquiry workflow.")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_parser = sub.add_parser("ingest", help="Parse 【商务>ID】 text, capture profile screenshot, upsert Feishu record.")
    ingest_parser.add_argument("--text", default="")
    ingest_parser.add_argument("--stdin", action="store_true")
    ingest_parser.add_argument("--feishu-url", default="")
    ingest_parser.add_argument("--profile-url", default="")
    ingest_parser.add_argument("--screenshot", default="")
    ingest_parser.add_argument("--brief-file", action="append", default=[])
    ingest_parser.add_argument("--account-name", default="")
    ingest_parser.add_argument("--notify-confirmation", action="store_true")
    ingest_parser.add_argument("--require-feishu", action="store_true")
    ingest_parser.add_argument("--dry-run", action="store_true")
    ingest_parser.add_argument("--no-screenshot", action="store_true")
    ingest_parser.add_argument("--smoke", action="store_true", help="Validate trigger/input parsing without LLM, screenshot, Feishu reads, or writes.")
    ingest_parser.set_defaults(func=ingest)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print_json({"ok": False, "error": exc.code})
            return 1
        raise
    except Exception as exc:
        print_json({"ok": False, "error": str(exc), "command": args.command})
        return 1
    print_json(result)
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
