from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DAILY_JOURNAL_TRIGGER = "【日记】"
WEEKLY_SELF_MODEL_TRIGGER = "【周记】"

DAILY_JOURNAL_CANONICAL_ID = "daily_journal_entry"
WEEKLY_SELF_MODEL_CANONICAL_ID = "weekly_self_model_summary"

DAILY_JOURNAL_LLM_PROFILE = "daily_task_extraction"
WEEKLY_SELF_MODEL_LLM_PROFILE = "daily_task_extraction"

DEFAULT_DAILY_JOURNAL_CONFIG: dict[str, Any] = {
    "daily_prompt_time": "22:00",
    "weekly_summary_time": "23:59",
    "journal_root": "/home/ubuntu/obsidian-日记/日记",
    "weekly_archive_root": "/home/ubuntu/obsidian-日记/Archieve",
    "minimum_weekly_samples": 3,
}

DAILY_JOURNAL_RECORD_KIND = "daily_journal_entry"
WEEKLY_SELF_MODEL_RECORD_KIND = "weekly_self_model_summary"


@dataclass(frozen=True)
class DailyJournalField:
    field_id: str
    title: str
    group: str
    prompt: str


DAILY_JOURNAL_FIELDS: tuple[DailyJournalField, ...] = (
    DailyJournalField("today_one_sentence", "今天一句话", "core", "今天一句话："),
    DailyJournalField("today_most_recordable", "今天最值得记录的一件事", "core", "今天最值得记录的一件事："),
    DailyJournalField("emotion_pressure", "情绪/压力", "emotion", "情绪/压力："),
    DailyJournalField("emotion_trigger", "触发了什么", "emotion", "触发了什么："),
    DailyJournalField("emotion_first_reaction", "我的第一反应", "emotion", "我的第一反应："),
    DailyJournalField("emotion_next_reminder", "下次提醒自己", "emotion", "下次提醒自己："),
    DailyJournalField("decision_judgment", "决策/判断", "decision", "决策/判断："),
    DailyJournalField("decision_today", "我今天做了什么判断", "decision", "我今天做了什么判断："),
    DailyJournalField("decision_basis", "当时依据是什么", "decision", "当时依据是什么："),
    DailyJournalField("avoidance_escape", "退缩/逃避", "avoidance", "退缩/逃避："),
    DailyJournalField("avoidance_fear", "我今天在怕什么", "avoidance", "我今天在怕什么："),
    DailyJournalField("avoidance_min_action", "明天一个最小动作", "avoidance", "明天一个最小动作："),
    DailyJournalField("development_work", "开发/工作", "work", "开发/工作："),
    DailyJournalField("engineering_experience", "工程经验", "work", "工程经验："),
    DailyJournalField("content_creation", "内容/创作", "creation", "内容/创作："),
    DailyJournalField("people_communication", "人际/沟通", "people", "人际/沟通："),
    DailyJournalField("health_energy", "健康/精力", "health", "健康/精力："),
    DailyJournalField("commitment_unfinished", "承诺/未完成", "commitment", "承诺/未完成："),
)

DAILY_JOURNAL_FIELD_BY_ID: dict[str, DailyJournalField] = {field.field_id: field for field in DAILY_JOURNAL_FIELDS}
DAILY_JOURNAL_FIELD_BY_TITLE: dict[str, DailyJournalField] = {field.title: field for field in DAILY_JOURNAL_FIELDS}

DAILY_JOURNAL_TEMPLATE = """【日记】

今天一句话：
今天最值得记录的一件事：

情绪/压力：
触发了什么：
我的第一反应：
下次提醒自己：

决策/判断：
我今天做了什么判断：
当时依据是什么：

退缩/逃避：
我今天在怕什么：
明天一个最小动作："""


WEEKLY_FIXED_SECTIONS: tuple[str, ...] = (
    "本周一句话",
    "重复情绪触发",
    "重复逃避模式",
    "关键决策复盘",
    "完成/未完成的承诺",
    "最值得保留的经验",
    "开发/工作复盘",
    "工程经验沉淀",
    "内容/创作信号",
    "下周一个行为实验",
)

WEEKLY_DYNAMIC_TOPIC_CLUSTERS: tuple[str, ...] = (
    "情绪/压力",
    "决策/判断",
    "退缩/逃避",
    "开发/工作",
    "工程经验",
    "内容/创作",
    "人际/沟通",
    "健康/精力",
    "承诺/未完成",
)

DAILY_JOURNAL_ARRANGEMENT_PROMPT = """你是 OpenClaw Daily bot 的日记整理器。
你会收到完整日记原文，以及 Python 仅按标题切出的 template_fields 辅助索引。
无论用户使用模板还是自由文本，最终 arranged_text 和 sections 都必须由你阅读完整原文后整理生成，不能逐行照抄模板，也不能只返回 Python 切出的字段。
只根据用户原文整理，不要编造、不要诊断人格、不要给人生建议。
整理目标：先写一段适合用户回看的一段式事实整理 arranged_text，不要字段标题，不要项目符号，不要逐项列表；再给系统内部周记使用的 sections，并生成写入本周 Archieve `#YYYYMMDD -> ## 日记` 的 weekly_projection。weekly_projection 是给 Obsidian 周归档看的正常 Markdown 内容来源，只返回短标题和 3-5 句精炼总结，不要写 HTML comment、JSON、字段名、机器标记或模板解释。arranged_text 不是原文缩写，也不是把 template_fields 逐项串成一段；只能基于原文事实重组，按“发生了什么、状态是什么、用户原文里做了什么判断、用户原文里害怕或逃避什么、原文留下的下一步是什么”来整理。不要替用户升华、诊断、给建议、写新的结论或把原因说得比原文更确定。优先合并同类信息，删除流水账、重复表达和模板痕迹；但不能因为内容敏感、口语、性、亲密关系、羞耻、逃避或冲突就删掉关键事实。用户明确写出的判断、恐惧、对象、行动选择和原词，如果是当天事实证据，必须保留或等价转述，不能被泛化成“社交/欲望/关系”这类空泛词。不能改变原意。
如果原文包含 http:// 或 https:// 链接，arranged_text 和 weekly_projection.summary 必须原样保留具体 URL，不要改写成“链接”“视频链接”“某资料”等泛称。
返回 JSON：
{
  "status": "done" | "pending_manual",
  "arranged_text": "一段基于原文事实整理后的日记，不要字段标题，不要列表，不要逐项复述原文字段，不要新增建议或结论。",
  "sections": {
    "today_one_sentence": "...",
    "today_most_recordable": "...",
    "emotion_pressure": "...",
    "emotion_trigger": "...",
    "emotion_first_reaction": "...",
    "emotion_next_reminder": "...",
    "decision_judgment": "...",
    "decision_today": "...",
    "decision_basis": "...",
    "avoidance_escape": "...",
    "avoidance_fear": "...",
    "avoidance_min_action": "...",
    "development_work": "...",
    "engineering_experience": "...",
    "content_creation": "...",
    "people_communication": "...",
    "health_energy": "...",
    "commitment_unfinished": "..."
  },
  "weekly_projection": {
    "title": "一个可放在周归档 ## 日记 下的短主题标题，不要编号，不要备选标题，不要超过 30 个中文字",
    "summary": "3-5 句精炼总结，只保留本条日记最值得进入周归档的事实、判断、状态和下一步；不要写 JSON、字段名、机器标记、原文字段列表或建议。"
  },
  "missing_fields": ["..."]
}
sections 字段没有证据就返回空字符串。weekly_projection.title 和 weekly_projection.summary 必须在 status=done 时返回。若原文没有任何可整理内容，返回 pending_manual 并说明 reason。"""

WEEKLY_SELF_MODEL_SUMMARY_PROMPT = """你是 OpenClaw Daily bot 的周记抽取器。
输入是一周内日记的内部整理信号。你只能总结用户提供的事实，不能做人格定型、命运判断、心理诊断或过度推断。
如果样本少于 3 篇，必须返回 status=insufficient_sample，并且不要生成稳定模式结论。
样本足够时返回 JSON：
{
  "status": "done",
  "fixed_sections": {
    "本周一句话": "...",
    "重复情绪触发": "...",
    "重复逃避模式": "...",
    "关键决策复盘": "...",
    "完成/未完成的承诺": "...",
    "最值得保留的经验": "...",
    "开发/工作复盘": "...",
    "工程经验沉淀": "...",
    "内容/创作信号": "...",
    "下周一个行为实验": "..."
  },
  "dynamic_topic_clusters": [
    {
      "topic": "开发/工作",
      "summary": "...",
      "evidence_dates": ["YYYY-MM-DD"]
    }
  ],
  "missing_fields": ["..."]
}
dynamic_topic_clusters 的 topic 只能来自：情绪/压力、决策/判断、退缩/逃避、开发/工作、工程经验、内容/创作、人际/沟通、健康/精力、承诺/未完成。"""


def daily_journal_template() -> str:
    return DAILY_JOURNAL_TEMPLATE


def daily_journal_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_DAILY_JOURNAL_CONFIG)
    for key, value in (overrides or {}).items():
        if value not in (None, ""):
            config[key] = value
    config["minimum_weekly_samples"] = int(config.get("minimum_weekly_samples") or 3)
    return config


def journal_path(root: str | Path, day: date) -> Path:
    return Path(root) / f"{day.isoformat()}.md"


def weekly_summary_path(root: str | Path, start: date, end: date) -> Path:
    return Path(root) / f"{week_key(start, end)}.md"


def week_key(start: date, end: date) -> str:
    return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"


def week_bounds_for(dt: datetime, timezone: str) -> tuple[date, date]:
    zoned = dt.astimezone(ZoneInfo(timezone))
    start = zoned.date() - timedelta(days=zoned.weekday())
    return start, start + timedelta(days=6)


def parse_compact_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def sample_status(sample_count: int, minimum_samples: int = 3) -> str:
    if sample_count <= 0:
        return "empty"
    if sample_count < minimum_samples:
        return "insufficient"
    return "ready"


def field_titles() -> tuple[str, ...]:
    return tuple(field.title for field in DAILY_JOURNAL_FIELDS)


def field_ids() -> tuple[str, ...]:
    return tuple(field.field_id for field in DAILY_JOURNAL_FIELDS)


def weekly_fixed_sections() -> tuple[str, ...]:
    return WEEKLY_FIXED_SECTIONS


def weekly_dynamic_topic_clusters() -> tuple[str, ...]:
    return WEEKLY_DYNAMIC_TOPIC_CLUSTERS
