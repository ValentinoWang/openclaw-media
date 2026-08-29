from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from common.llm_validation import LLMValidationContract, register_llm_validation_contract
from selfmedia.context import build_media_context, merge_conversation_context

from .adapters import ActivityAdapter, BusinessAdapter, CreationInspirationAdapter, ViralContentAdapter
from .field_contract import normalize_platform, split_tags
from .llm_generator import (
    _compact_candidates,
    _compact_reference_docs,
    _truncate_list,
    _truncate_nested,
    _truncate_text,
    call_creation_json,
)
from .platform_fit import default_platform_mechanism
from .retrieval import load_business_rows_for_creation, load_inspiration_rows_for_creation, load_rows_for_creation, read_reference_docs
from .workflow import _record_candidate_payload, _reference_doc_urls_from_records


CONSULTATION_PATTERN = re.compile(r"^\s*【创作咨询】")
KEY_VALUE_RE = re.compile(r"(?P<key>平台|账号|作者ID|博主|赛道|主题|主体|问题|关键词|标签)\s*[=:：]\s*(?P<value>.*?)(?=\s+(?:平台|账号|作者ID|博主|赛道|主题|主体|问题|关键词|标签)\s*[=:：]|$)")
ACTIVITY_INTENT_RE = re.compile(r"(活动|平台活动|话题活动|投稿|返稿|冲榜|挑战赛|活动适配|适合参加|挂什么话题|参与哪个话题)")
CONSULTATION_REPORT_LABELS = ("选题拆解：", "依据：", "建议：", "下一步：", "缺口：")
DEFAULT_CONSULTATION_CONCLUSION = "现有信息还不足以给出可靠的创作判断。"
DEFAULT_CONSULTATION_NEXT_ACTION = "先补充一个准备讲述的具体场景或素材。"

CONSULTATION_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.creation.consultation.v1",
        profile="bounded_open",
        required_fields=("reply", "conclusion", "next_actions"),
        non_empty_fields=("reply", "conclusion", "next_actions"),
        field_types={
            "reply": str,
            "conclusion": str,
            "topic_diagnosis": dict,
            "evidence": (list, str),
            "recommendations": (list, str),
            "next_actions": (list, str),
            "data_gaps": (list, str),
        },
        evidence_fields=("evidence", "data_gaps"),
    )
)


@dataclass(frozen=True)
class ConsultationRequest:
    question: str
    platform: str = ""
    account: str = ""
    track: str = ""
    topic: str = ""
    keywords: tuple[str, ...] = ()
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "platform": self.platform,
            "account": self.account,
            "track": self.track,
            "topic": self.topic,
            "keywords": list(self.keywords),
            "raw_text": self.raw_text,
        }


def handle_creation_consultation_command(
    raw_text: str,
    *,
    tenant_id: str,
    viral_url: str = "",
    activity_url: str = "",
    business_url: str = "",
    inspiration_url: str = "",
    limit: int = 300,
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = parse_consultation_request(raw_text)
    include_activity = request_needs_activity_candidates(request)
    viral_rows, activity_rows = load_rows_for_creation(tenant_id=tenant_id, viral_url=viral_url, activity_url=activity_url, limit=limit, include_activity=include_activity)
    business_rows = load_business_rows_for_creation(tenant_id=tenant_id, business_url=business_url, limit=limit)
    inspiration_rows = load_inspiration_rows_for_creation(tenant_id=tenant_id, inspiration_url=inspiration_url, limit=limit)

    virals = [ViralContentAdapter().to_record(row) for row in viral_rows]
    activities = [ActivityAdapter().to_record(row) for row in activity_rows]
    businesses = [BusinessAdapter().to_record(row) for row in business_rows]
    inspirations = [CreationInspirationAdapter().to_record(row) for row in inspiration_rows]

    viral_candidates = _top_relevant_records(virals, request, max_items=30)
    activity_candidates = _top_relevant_records(activities, request, max_items=20)
    inspiration_candidates = _top_relevant_records(inspirations, request, max_items=30)
    business_candidates = _top_relevant_records(businesses, request, max_items=12)
    reference_docs = read_reference_docs(_reference_doc_urls_from_records([*viral_candidates, *inspiration_candidates], max_items=6), max_chars_per_doc=1400)
    media_context = merge_conversation_context(
        build_media_context(
            tenant_id=tenant_id,
            platform=request.platform,
            account=request.account,
            track=request.track,
            topic=request.topic,
            keywords=list(request.keywords),
            limit=8,
        ),
        conversation_context,
    )

    answer = generate_consultation_answer(
        request,
        activity_candidates=[_record_candidate_payload(item) for item in activity_candidates],
        viral_candidates=[_record_candidate_payload(item) for item in viral_candidates],
        inspiration_candidates=[_record_candidate_payload(item) for item in inspiration_candidates],
        business_candidates=[_record_candidate_payload(item) for item in business_candidates],
        reference_docs=reference_docs,
        media_context=media_context,
        source_counts={"virals": len(virals), "activities": len(activities), "inspirations": len(inspirations), "businesses": len(businesses)},
    )
    reply = _readable_consultation_reply(answer.get("reply"))
    if not reply:
        reply = format_consultation_reply(answer)
    return {
        "ok": True,
        "mode": "consultation",
        "request": request.to_dict(),
        "source_counts": {"virals": len(virals), "activities": len(activities), "inspirations": len(inspirations), "businesses": len(businesses)},
        "candidate_counts": {
            "virals": len(viral_candidates),
            "activities": len(activity_candidates),
            "inspirations": len(inspiration_candidates),
            "businesses": len(business_candidates),
            "reference_docs": len(reference_docs),
        },
        "media_context": media_context,
        "answer": answer,
        "reply": reply,
    }


def request_needs_activity_candidates(request: ConsultationRequest) -> bool:
    text = " ".join(
        str(item or "")
        for item in (
            request.question,
            request.raw_text,
            request.topic,
            request.track,
            *request.keywords,
        )
    )
    return bool(ACTIVITY_INTENT_RE.search(text))


def parse_consultation_request(raw_text: str) -> ConsultationRequest:
    text = (raw_text or "").strip()
    match = CONSULTATION_PATTERN.match(text)
    if not match:
        raise ValueError("不是【创作咨询】入口")
    body = text[match.end():].strip()
    values = {match.group("key"): match.group("value").strip() for match in KEY_VALUE_RE.finditer(body)}
    tails: list[str] = []
    for key in ("平台", "账号", "作者ID", "博主", "赛道", "主题", "主体"):
        value = values.get(key, "")
        if not value or not re.search(r"\s", value):
            continue
        head, tail = value.split(None, 1)
        values[key] = head.strip()
        if tail.strip():
            tails.append(tail.strip())
    question = values.get("问题") or " ".join(tails).strip() or body
    if not question.strip():
        raise ValueError("【创作咨询】缺少问题")
    platform = normalize_platform(values.get("平台") or _infer_platform(body))
    account = (values.get("账号") or values.get("作者ID") or values.get("博主") or "").strip()
    track = (values.get("赛道") or "").strip()
    topic = (values.get("主题") or values.get("主体") or "").strip()
    keywords = split_tags(values.get("关键词") or values.get("标签") or " ".join([track, topic, account, body]))
    return ConsultationRequest(
        question=question.strip(),
        platform=platform,
        account=account,
        track=track,
        topic=topic,
        keywords=tuple(keywords[:20]),
        raw_text=text,
    )


def generate_consultation_answer(
    request: ConsultationRequest,
    *,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
    source_counts: dict[str, int],
) -> dict[str, Any]:
    payload = _compact_consultation_prompt_payload(
        request,
        activity_candidates=activity_candidates,
        viral_candidates=viral_candidates,
        inspiration_candidates=inspiration_candidates,
        business_candidates=business_candidates,
        reference_docs=reference_docs,
        media_context=media_context,
        source_counts=source_counts,
    )
    prompt = (
        "你是 OpenClaw media bot 的创作顾问。你必须基于输入中的飞书数据表、创作灵感素材、SourceAsset/拆解 artifact 摘要、账号记忆和历史复盘回答用户的创作问题。\n"
        "不要凭空声称看过不存在的数据；如果数据不足，要明确说缺什么。\n"
        "候选只保留与问题相关的摘要；没有强相关候选时，必须把输入中的相关性提示说清楚，不能把摘要当作完整证据。\n"
        "做个人 IP 选题时，优先检查 inspiration_candidates 里的真实场景、情绪信号、触发原话、错位点、核心观点和一鱼多吃方向，再参考爆款结构。\n"
        "涉及平台推荐、活动适配或创作反推时，要参考 platform_mechanism_reference；这只是机制拟合假设，不得声称破解平台真实算法。\n"
        "回答选题、标题或脚本问题时，先做 topic_diagnosis：目标人群、核心痛点、内容角度、只解决的一个小问题、自查标准；不要直接给一组热闹但同质化的标题。\n"
        "回答要给：结论、依据、推荐动作、可直接执行的下一步；必要时给 3-7 个选题/脚本方向。\n"
        "reply 是直接发进聊天窗的最终回答：先说结论和最该做的一步，再补关键依据，像同事当面交代事情那样说连贯的话；"
        "不要用『依据：』『建议：』『下一步：』这类报告小标题分栏，不要满屏项目符号，选题方向可以自然列出但每条要带一句为什么值得做。\n"
        "只输出合法 JSON object，不要 Markdown 代码块。字段：reply, conclusion, topic_diagnosis, evidence, recommendations, next_actions, data_gaps。\n\n"
        f"输入 JSON：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    result = call_creation_json(prompt, validation_contract=CONSULTATION_VALIDATION_CONTRACT)
    return result if isinstance(result, dict) else {}


def _compact_consultation_prompt_payload(
    request: ConsultationRequest,
    *,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
    source_counts: dict[str, int],
) -> dict[str, Any]:
    payload = {
        "request": request.to_dict(),
        "source_counts": source_counts,
        "media_memory_prompt": _truncate_text((media_context or {}).get("prompt"), 3000),
        "media_context_loaded": _truncate_nested((media_context or {}).get("loaded") or {}, 300),
        "account_profile": _truncate_nested((media_context or {}).get("account_profile") or {}, 2500),
        "recent_creations": _truncate_list((media_context or {}).get("recent_creations"), 8, 900),
        "recent_reviews": _truncate_list((media_context or {}).get("recent_reviews"), 8, 900),
        "activity_candidates": _compact_candidates(activity_candidates, 10),
        "viral_candidates": _compact_candidates(viral_candidates, 15),
        "inspiration_candidates": _compact_candidates(inspiration_candidates, 15),
        "business_candidates": _compact_candidates(business_candidates, 10),
        "reference_docs": _compact_reference_docs(reference_docs),
        "platform_mechanism_reference": default_platform_mechanism(request.platform) if request.platform else {},
        "prompt_compaction_note": "候选已按字段白名单和长度预算压缩；detail_json 等原始快照不会进入咨询提示词。",
    }
    return payload


def format_consultation_reply(answer: dict[str, Any]) -> str:
    conclusion = _readable_consultation_reply(answer.get("conclusion")) or DEFAULT_CONSULTATION_CONCLUSION
    next_action = _first_consultation_reply_item(answer.get("next_actions"))
    evidence = _first_consultation_reply_item(answer.get("evidence"))
    data_gap = _first_consultation_reply_item(answer.get("data_gaps"))

    sentences = [conclusion, f"最该做的一步是{next_action or DEFAULT_CONSULTATION_NEXT_ACTION}"]
    if evidence:
        sentences.append(f"主要依据是{evidence}")
    elif data_gap:
        sentences.append(f"还需要补充{data_gap}")
    # Keep the fallback as one chat-ready paragraph instead of a report-like block.
    return " ".join(sentences)


def _readable_consultation_reply(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or any(label in text for label in CONSULTATION_REPORT_LABELS):
        return ""
    return text


def _first_consultation_reply_item(value: Any) -> str:
    candidates = (value,) if isinstance(value, str) else value if isinstance(value, list) else ()
    for item in candidates:
        text = _readable_consultation_reply(item)
        if text:
            return text
    return ""


def _top_relevant_records(records: list[Any], request: ConsultationRequest, *, max_items: int) -> list[Any]:
    scored = [(_relevance_score(record, request), index, record) for index, record in enumerate(records)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    positives = [record for score, _index, record in scored if score > 0]
    return (positives or [record for _score, _index, record in scored])[:max_items]


def _relevance_score(record: Any, request: ConsultationRequest) -> int:
    haystack = " ".join(
        str(item or "")
        for item in (
            getattr(record, "title", ""),
            getattr(record, "content", ""),
            getattr(record, "platform", ""),
            getattr(record, "track", ""),
            getattr(record, "topic", ""),
            " ".join(getattr(record, "tags", []) or []),
            json.dumps(getattr(record, "detail_json", {}) or {}, ensure_ascii=False),
        )
    ).lower()
    score = 0
    if request.platform and request.platform.lower() in haystack:
        score += 5
    if request.track and request.track.lower() in haystack:
        score += 4
    if request.topic and request.topic.lower() in haystack:
        score += 4
    for keyword in request.keywords:
        clean = str(keyword or "").strip().lower()
        if len(clean) >= 2 and clean in haystack:
            score += 2
    for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", request.question.lower()):
        if token in haystack:
            score += 1
    return score


def _infer_platform(text: str) -> str:
    if "小红书" in text:
        return "小红书"
    if "抖音" in text:
        return "抖音"
    if "B站" in text or "哔哩哔哩" in text or "bilibili" in text.lower():
        return "B站"
    return ""
