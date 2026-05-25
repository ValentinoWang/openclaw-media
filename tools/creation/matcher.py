from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .field_contract import CanonicalMediaRecord, normalize_key, split_tags
from .request_parser import CreationRequest


ACTIVE_ACTIVITY_STATUSES = {"进行中", "可参与", "未结束", "未开始", "已开始"}
ACTIVITY_PRIMARY_REASON_KEYS = {"平台一致", "赛道精确匹配", "赛道部分匹配", "主题相似", "关键词重合", "发布时间落在活动周期内"}
VIRAL_PRIMARY_REASON_KEYS = {"平台一致", "内容类型一致", "赛道精确匹配", "赛道部分匹配", "主题相似", "关键词重合"}
VIRAL_REQUIRED_REASON_KEYS = {"赛道精确匹配", "赛道部分匹配", "主题相似", "关键词重合"}


@dataclass(frozen=True)
class RankedRecord:
    record: CanonicalMediaRecord
    score: int
    reasons: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {"record": asdict(self.record), "score": self.score, "reasons": self.reasons}


def rank_activities(records: list[CanonicalMediaRecord], request: CreationRequest) -> list[RankedRecord]:
    ranked = []
    for record in records:
        score, reasons = score_activity(record, request)
        if score > 0 and (set(reasons) & ACTIVITY_PRIMARY_REASON_KEYS):
            ranked.append(RankedRecord(record=record, score=score, reasons=reasons))
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def rank_virals(records: list[CanonicalMediaRecord], request: CreationRequest) -> list[RankedRecord]:
    ranked = []
    for record in records:
        score, reasons = score_viral(record, request)
        if score > 0 and (set(reasons) & VIRAL_PRIMARY_REASON_KEYS) and (set(reasons) & VIRAL_REQUIRED_REASON_KEYS):
            ranked.append(RankedRecord(record=record, score=score, reasons=reasons))
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def rank_businesses(records: list[CanonicalMediaRecord], request: CreationRequest) -> list[RankedRecord]:
    if not request_has_business_context(request):
        return []
    ranked = []
    for record in records:
        score, reasons = score_business(record, request)
        if score > 0 and reasons:
            ranked.append(RankedRecord(record=record, score=score, reasons=reasons))
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def score_activity(record: CanonicalMediaRecord, request: CreationRequest) -> tuple[int, dict[str, int]]:
    score = 0
    reasons: dict[str, int] = {}
    if same(record.platform, request.platform):
        score += 30
        reasons["平台一致"] = 30
    if record.content_type_requirement and content_type_allowed(request.content_type, record.content_type_requirement):
        score += 15
        reasons["内容类型符合"] = 15
    if same(record.track, request.track):
        score += 40
        reasons["赛道精确匹配"] = 40
    elif contains(record.track, request.track) or contains(" ".join(record.tags), request.track):
        score += 25
        reasons["赛道部分匹配"] = 25
    topic_score = topic_similarity_score(record.topic or record.direction, request.topic)
    if topic_score:
        score += topic_score
        reasons["主题相似"] = topic_score
    keyword_score = keyword_overlap_score(record.tags, request.keywords or [], max_score=25)
    if keyword_score:
        score += keyword_score
        reasons["关键词重合"] = keyword_score
    if publish_time_in_activity_window(request.publish_time, record.start_time, record.end_time, record.deadline):
        score += 35
        reasons["发布时间落在活动周期内"] = 35
    if record.status and record.status in ACTIVE_ACTIVITY_STATUSES:
        score += 20
        reasons["活动状态可参与"] = 20
    level_score = activity_level_score(record.activity_level)
    if level_score:
        score += level_score
        reasons["活动级别"] = level_score
    return score, reasons


def score_viral(record: CanonicalMediaRecord, request: CreationRequest) -> tuple[int, dict[str, int]]:
    score = 0
    reasons: dict[str, int] = {}
    if same(record.platform, request.platform):
        score += 30
        reasons["平台一致"] = 30
    if same(record.content_type, request.content_type):
        score += 15
        reasons["内容类型一致"] = 15
    if same(record.track, request.track):
        score += 40
        reasons["赛道精确匹配"] = 40
    elif contains(record.track, request.track) or contains(" ".join(record.tags), request.track):
        score += 25
        reasons["赛道部分匹配"] = 25
    topic_score = topic_similarity_score(record.topic, request.topic)
    if topic_score:
        score += topic_score
        reasons["主题相似"] = topic_score
    keyword_score = keyword_overlap_score(record.tags, request.keywords or [], max_score=25)
    if keyword_score:
        score += keyword_score
        reasons["关键词重合"] = keyword_score
    metric_score = viral_metric_score(record.metrics)
    if metric_score:
        score += metric_score
        reasons["爆款样本互动高"] = metric_score
    if record.doc_links.get("decomposition"):
        score += 20
        reasons["有拆解文档"] = 20
    if record.doc_links.get("recreation"):
        score += 10
        reasons["有创作-再创文档"] = 10
    return score, reasons


def score_business(record: CanonicalMediaRecord, request: CreationRequest) -> tuple[int, dict[str, int]]:
    score = 0
    reasons: dict[str, int] = {}
    if same(record.platform, request.platform):
        score += 15
        reasons["平台一致"] = 15
    if record.content_type_requirement and content_type_allowed(request.content_type, record.content_type_requirement):
        score += 15
        reasons["内容类型可合作"] = 15
    detail_text = " ".join(str(value) for value in record.detail_json.values() if value)
    haystack = " ".join([record.title, record.content, record.topic, detail_text, " ".join(record.tags)])
    if request.brand and contains(haystack, request.brand):
        score += 50
        reasons["品牌匹配"] = 50
    if request.product and contains(haystack, request.product):
        score += 40
        reasons["产品匹配"] = 40
    if request.project and contains(haystack, request.project):
        score += 35
        reasons["项目匹配"] = 35
    if request.account and contains(haystack, request.account):
        score += 50
        reasons["账号匹配"] = 50
    keyword_score = keyword_overlap_score(record.tags, request.keywords or [], max_score=20)
    if keyword_score:
        score += keyword_score
        reasons["商务关键词重合"] = keyword_score
    if record.doc_links.get("brief"):
        score += 15
        reasons["有Brief链接"] = 15
    if record.detail_json.get("给品牌方信息"):
        score += 10
        reasons["有品牌方信息"] = 10
    return score, reasons


def request_has_business_context(request: CreationRequest) -> bool:
    if any((request.brand, request.product, request.project, request.account, request.brief, request.business_note)):
        return True
    raw = " ".join([request.raw_text, request.user_idea or ""])
    return any(word in raw for word in ("品牌", "brief", "Brief", "商务", "合作", "报价", "达人", "博主"))


def same(left: str, right: str) -> bool:
    return bool(left and right and normalize_key(left) == normalize_key(right))


def contains(left: str, right: str) -> bool:
    left_key = normalize_key(left)
    right_key = normalize_key(right)
    return bool(left_key and right_key and (right_key in left_key or left_key in right_key))


def content_type_allowed(request_content_type: str, requirement: str) -> bool:
    if not requirement:
        return True
    requirement_tags = split_tags(requirement)
    if not requirement_tags:
        requirement_tags = [requirement]
    return any(same(item, "不限") or same(item, request_content_type) for item in requirement_tags)


def keyword_overlap_score(record_tags: list[str], request_keywords: list[str], *, max_score: int) -> int:
    if not record_tags or not request_keywords:
        return 0
    record_set = {normalize_key(item) for item in record_tags if normalize_key(item)}
    request_set = {normalize_key(item) for item in request_keywords if normalize_key(item)}
    overlap = record_set & request_set
    return min(len(overlap) * 5, max_score)


def topic_similarity_score(left: str, right: str) -> int:
    if not left or not right:
        return 0
    if same(left, right):
        return 25
    if contains(left, right):
        return 18
    left_tokens = set(_topic_tokens(left))
    right_tokens = set(_topic_tokens(right))
    overlap = left_tokens & right_tokens
    if not overlap:
        return 0
    return min(len(overlap) * 6, 18)


def _topic_tokens(value: str) -> list[str]:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value)
    return [item for item in re.split(r"\s+", text) if item]


def publish_time_in_activity_window(publish_time: str, start_time: str | None, end_time: str | None, deadline: str | None) -> bool:
    publish_dt = _parse_dt(publish_time)
    if not publish_dt:
        return False
    start_dt = _parse_dt(start_time or "")
    end_dt = _parse_dt(end_time or "")
    deadline_dt = _parse_dt(deadline or "")
    if start_dt and publish_dt < start_dt:
        return False
    latest = deadline_dt or end_dt
    if latest and publish_dt > latest:
        return False
    return bool(start_dt or end_dt or deadline_dt)


def activity_level_score(level: str) -> int:
    key = normalize_key(level).upper()
    if key == "S":
        return 30
    if key == "A":
        return 20
    if key == "B":
        return 10
    if key in {"普通", "C"}:
        return 5
    return 0


def viral_metric_score(metrics: dict[str, Any]) -> int:
    text = json.dumps(metrics or {}, ensure_ascii=False)
    numbers = [int(item) for item in re.findall(r"\d+", text)]
    if not numbers:
        return 0
    peak = max(numbers)
    if peak >= 100000:
        return 30
    if peak >= 10000:
        return 20
    if peak >= 1000:
        return 10
    return 0


def _parse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
