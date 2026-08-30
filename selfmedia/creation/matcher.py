from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from common.social_runtime import now_iso as _now_iso
from common.social_runtime import parse_iso_datetime

from .field_contract import CanonicalMediaRecord, normalize_key, split_tags
from .request_parser import CreationRequest


ELIGIBLE_ACTIVITY_STATUS = "进行中"
ACTIVITY_RAW_MAX_SCORE = 165
ACTIVITY_SCORE_SCALE = "0-100 normalized from raw max 165"
ACTIVITY_PRIMARY_REASON_KEYS = {"平台一致", "主题相似", "关键词重合", "发布时间落在活动周期内", "主状态进行中"}
VIRAL_PRIMARY_REASON_KEYS = {"平台一致", "内容类型一致", "赛道匹配", "主题相似", "关键词重合", "痛点爽点贴合", "核心价值贴合"}
INSPIRATION_PRIMARY_REASON_KEYS = {"平台一致", "内容类型一致", "赛道匹配", "主题相似", "关键词重合", "痛点/读者问题贴合", "核心观点可用", "可迁移点明确"}


@dataclass(frozen=True)
class RankedRecord:
    record: CanonicalMediaRecord
    score: int
    reasons: dict[str, Any]
    raw_score: int | None = None
    score_scale: str = "0-100"

    def to_dict(self) -> dict[str, Any]:
        payload = {"record": asdict(self.record), "score": self.score, "reasons": self.reasons, "score_scale": self.score_scale}
        if self.raw_score is not None:
            payload["raw_score"] = self.raw_score
        return payload


def rank_activities(records: list[CanonicalMediaRecord], request: CreationRequest) -> list[RankedRecord]:
    ranked = []
    for record in records:
        raw_score, reasons = score_activity(record, request)
        if raw_score > 0 and (set(reasons) & ACTIVITY_PRIMARY_REASON_KEYS):
            ranked.append(
                RankedRecord(
                    record=record,
                    score=normalize_score(raw_score, ACTIVITY_RAW_MAX_SCORE),
                    reasons=reasons,
                    raw_score=raw_score,
                    score_scale=ACTIVITY_SCORE_SCALE,
                )
            )
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def rank_virals(records: list[CanonicalMediaRecord], request: CreationRequest) -> list[RankedRecord]:
    ranked = []
    for record in records:
        score, reasons = score_viral(record, request)
        if score > 0 and (set(reasons) & VIRAL_PRIMARY_REASON_KEYS):
            ranked.append(RankedRecord(record=record, score=score, reasons=reasons))
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def rank_inspirations(records: list[CanonicalMediaRecord], request: CreationRequest) -> list[RankedRecord]:
    ranked = []
    for record in records:
        score, reasons = score_inspiration(record, request)
        if score > 0 and (set(reasons) & INSPIRATION_PRIMARY_REASON_KEYS):
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
    if normalize_key(record.status) != normalize_key(ELIGIBLE_ACTIVITY_STATUS):
        return 0, reasons
    if not publish_time_in_activity_window(activity_reference_time(request), record.start_time, record.end_time):
        return 0, reasons
    score += 55
    reasons["主状态进行中"] = 20
    reasons["发布时间落在活动周期内"] = 35
    if record.platform and request.platform and not same(record.platform, request.platform):
        return 0, {}
    if same(record.platform, request.platform):
        score += 30
        reasons["平台一致"] = 30
    topic_haystack = " ".join(
        item
        for item in (
            record.topic,
            record.direction,
            record.activity_brief,
            record.activity_guidance,
            record.submission_requirement,
        )
        if item
    )
    topic_score = topic_similarity_score(topic_haystack, request.topic)
    if topic_score:
        score += topic_score
        reasons["主题相似"] = topic_score
    keyword_tags = record.tags or split_tags(topic_haystack)
    keyword_score = keyword_overlap_score(keyword_tags, request.keywords or [], max_score=25)
    if keyword_score:
        score += keyword_score
        reasons["关键词重合"] = keyword_score
    level_score = activity_level_score(record.activity_level)
    if level_score:
        score += level_score
        reasons["活动级别"] = level_score
    return score, reasons


def score_viral(record: CanonicalMediaRecord, request: CreationRequest) -> tuple[int, dict[str, int]]:
    score = 0
    reasons: dict[str, int] = {}
    if record_conflicts_platform(record, request) or record_conflicts_content_type(record, request):
        return 0, {}
    if not has_viral_relevance(record, request):
        return 0, {}
    if same(record.platform, request.platform):
        score += 10
        reasons["平台一致"] = 10
    if same(record.content_type, request.content_type):
        score += 10
        reasons["内容类型一致"] = 10
    if same(record.track, request.track):
        score += 10
        reasons["赛道匹配"] = 10
    elif contains(record.track, request.track) or contains(" ".join(record.tags), request.track):
        score += 6
        reasons["赛道匹配"] = 6
    topic_score = scaled_topic_similarity_score(record.topic, request.topic, max_score=5)
    if topic_score:
        score += topic_score
        reasons["主题相似"] = topic_score
    keyword_score = keyword_overlap_score(record.tags, request.keywords or [], max_score=5)
    if keyword_score:
        score += keyword_score
        reasons["关键词重合"] = keyword_score

    metric_score = viral_core_data_score(record.metrics)
    if metric_score:
        score += metric_score
        reasons["核心数据强"] = metric_score
    pain_score = text_fit_score(record.pain_points, request, max_score=5)
    if pain_score:
        score += pain_score
        reasons["痛点爽点贴合"] = pain_score
    core_score = text_fit_score(record.core_value, request, max_score=5)
    if core_score:
        score += core_score
        reasons["核心价值贴合"] = core_score
    audience_score = text_fit_score(record.audience, request, max_score=2)
    if audience_score:
        score += audience_score
        reasons["目标受众贴合"] = audience_score

    if _present(record.detail_json.get("summary")):
        score += 7
        reasons["爆点拆解可用"] = 7
    if _present(record.detail_json.get("transferable_points")):
        score += 8
        reasons["爆点迁移明确"] = 8
    if _present(record.detail_json.get("hook")):
        score += 5
        reasons["吸睛元素可迁移"] = 5

    if record.source_link:
        score += 3
        reasons["有来源链接"] = 3
    if record.doc_links.get("decomposition"):
        score += 7
        reasons["有拆解文档"] = 7
    elif record.doc_links.get("evidence") or _present(record.detail_json.get("evidence_uri")):
        score += 7
        reasons["有证据artifact"] = 7
    if record.doc_links.get("recreation"):
        score += 5
        reasons["有拆解 artifact 或创作交接参考"] = 5
    return min(score, 100), reasons


def score_inspiration(record: CanonicalMediaRecord, request: CreationRequest) -> tuple[int, dict[str, int]]:
    score = 0
    reasons: dict[str, int] = {}
    if record_conflicts_platform(record, request) or record_conflicts_content_type(record, request):
        return 0, {}
    if not has_inspiration_relevance(record, request):
        return 0, {}
    if same(record.platform, request.platform):
        score += 8
        reasons["平台一致"] = 8
    if same(record.content_type, request.content_type):
        score += 7
        reasons["内容类型一致"] = 7
    if same(record.track, request.track):
        score += 7
        reasons["赛道匹配"] = 7
    elif contains(record.track, request.track) or contains(" ".join(record.tags), request.track):
        score += 4
        reasons["赛道匹配"] = 4
    topic_score = scaled_topic_similarity_score(record.topic, request.topic, max_score=8)
    if topic_score:
        score += topic_score
        reasons["主题相似"] = topic_score
    keyword_score = keyword_overlap_score(record.tags, request.keywords or [], max_score=5)
    if keyword_score:
        score += keyword_score
        reasons["关键词重合"] = keyword_score

    audience_score = text_fit_score(record.audience, request, max_score=5)
    if audience_score:
        score += audience_score
        reasons["目标受众贴合"] = audience_score
    pain_text = " ".join(item for item in (record.pain_points, str(record.detail_json.get("读者问题") or "")) if item)
    pain_score = text_fit_score(pain_text, request, max_score=7)
    if pain_score:
        score += pain_score
        reasons["痛点/读者问题贴合"] = pain_score
    core_score = text_fit_score(record.core_value, request, max_score=6)
    if core_score:
        score += core_score
        reasons["核心观点可用"] = core_score
    signal_score = evidence_presence_score(
        record.detail_json,
        ("情绪触发", "触发原话", "事件场景", "错位点"),
        max_score=7,
    )
    if signal_score:
        score += signal_score
        reasons["真实素材信号"] = signal_score

    direction_score = text_fit_score(record.direction, request, max_score=7)
    if direction_score:
        score += direction_score
        reasons["再创方向明确"] = direction_score
    transfer_score = text_fit_score(record.detail_json.get("可迁移点"), request, max_score=7)
    if transfer_score:
        score += transfer_score
        reasons["可迁移点明确"] = transfer_score
    reusable_text = " ".join(
        str(record.detail_json.get(key) or "")
        for key in ("可复用角度", "一鱼多吃方向")
        if record.detail_json.get(key)
    )
    reusable_score = text_fit_score(reusable_text, request, max_score=6)
    if reusable_score:
        score += reusable_score
        reasons["可复用角度明确"] = reusable_score
    product_score = text_fit_score(record.detail_json.get("建议产物"), request, max_score=5)
    if product_score:
        score += product_score
        reasons["建议产物贴合"] = product_score

    quality_score = inspiration_quality_score(record.metrics.get("score"))
    if quality_score:
        score += quality_score
        reasons["灵感评分质量"] = quality_score
    if _present(record.metrics.get("score_reason")):
        score += 3
        reasons["评分原因可信"] = 3
    if record.doc_links.get("inspiration") or record.source_link:
        score += 4
        reasons["有文档或来源"] = 4
    risk_score = evidence_presence_score(record.detail_json, ("风险点", "素材状态", "下一步"), max_score=3)
    if risk_score:
        score += risk_score
        reasons["风险与下一步清楚"] = risk_score
    return min(score, 100), reasons


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


def normalize_score(score: int, max_score: int) -> int:
    if max_score <= 0:
        return 0
    return max(0, min(100, round(min(score, max_score) / max_score * 100)))


def record_conflicts_platform(record: CanonicalMediaRecord, request: CreationRequest) -> bool:
    return bool(record.platform and request.platform and not same(record.platform, request.platform))


def record_conflicts_content_type(record: CanonicalMediaRecord, request: CreationRequest) -> bool:
    return bool(record.content_type and request.content_type and not same(record.content_type, request.content_type))


def has_viral_relevance(record: CanonicalMediaRecord, request: CreationRequest) -> bool:
    fields = (record.title, record.content, record.track, record.topic, " ".join(record.tags), record.pain_points, record.core_value)
    return any(text_has_request_signal(value, request) for value in fields)


def has_inspiration_relevance(record: CanonicalMediaRecord, request: CreationRequest) -> bool:
    fields = (
        record.title,
        record.content,
        record.track,
        record.topic,
        " ".join(record.tags),
        record.pain_points,
        record.core_value,
        record.direction,
        str(record.detail_json.get("可迁移点") or ""),
    )
    return any(text_has_request_signal(value, request) for value in fields)


def text_has_request_signal(value: Any, request: CreationRequest) -> bool:
    text = str(value or "")
    if not text:
        return False
    request_values = [request.track, request.topic, *(request.keywords or [])]
    return any(contains(text, item) for item in request_values if item)


def text_fit_score(value: Any, request: CreationRequest, *, max_score: int) -> int:
    text = str(value or "")
    if not text:
        return 0
    request_values = [request.topic, request.track, *(request.keywords or [])]
    if any(same(text, item) for item in request_values if item):
        return max_score
    if any(contains(text, item) for item in request_values if item):
        return max(1, round(max_score * 0.75))
    token_hits = 0
    text_tokens = set(_topic_tokens(text))
    for item in request_values:
        item_tokens = set(_topic_tokens(str(item or "")))
        if item_tokens and text_tokens & item_tokens:
            token_hits += 1
    if token_hits:
        return min(max_score, max(1, token_hits * 2))
    return 0


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


def scaled_topic_similarity_score(left: str, right: str, *, max_score: int) -> int:
    raw = topic_similarity_score(left, right)
    if not raw:
        return 0
    return max(1, min(max_score, round(raw / 25 * max_score)))


def evidence_presence_score(data: dict[str, Any], keys: tuple[str, ...], *, max_score: int) -> int:
    present = sum(1 for key in keys if _present(data.get(key)))
    if not present:
        return 0
    return min(max_score, round(max_score * present / len(keys)))


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _topic_tokens(value: str) -> list[str]:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value)
    return [item for item in re.split(r"\s+", text) if item]


def activity_reference_time(request: CreationRequest) -> str:
    if request.publish_time:
        return request.publish_time
    return _now_iso()


def publish_time_in_activity_window(reference_time: str, start_time: str | None, end_time: str | None) -> bool:
    reference_dt = _parse_dt(reference_time)
    start_dt = _parse_dt(start_time or "")
    end_dt = _parse_dt(end_time or "")
    if not reference_dt or not start_dt or not end_dt:
        return False
    if reference_dt < start_dt:
        return False
    if reference_dt > end_dt:
        return False
    return True


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


def viral_core_data_score(metrics: dict[str, Any]) -> int:
    text = json.dumps(metrics or {}, ensure_ascii=False)
    numbers = [int(item) for item in re.findall(r"\d+", text)]
    if not numbers:
        return 0
    peak = max(numbers)
    if peak >= 100000:
        return 8
    if peak >= 10000:
        return 5
    if peak >= 1000:
        return 3
    return 0


def inspiration_quality_score(value: Any) -> int:
    text = str(value or "")
    match = re.search(r"\d+", text)
    if not match:
        return 0
    score = int(match.group(0))
    if score >= 90:
        return 5
    if score >= 80:
        return 3
    if score >= 70:
        return 1
    return 0


def _parse_dt(value: str) -> datetime | None:
    # Consolidated into common/social_runtime.parse_iso_datetime (H9). A
    # naive input is assumed UTC; an already tz-aware input is returned
    # as parsed (NOT forced to UTC) -- this must stay assume_tz-only, no
    # convert_to, to match the original inline implementation.
    return parse_iso_datetime(value, assume_tz=timezone.utc)
