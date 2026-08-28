from __future__ import annotations

import base64
import ast
import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass, asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from common.llm_client import generate_json_from_parts as common_generate_json_from_parts
from common.llm_validation import LLMValidationContract, register_llm_validation_contract
from common.llm_settings import LLMProviderSettings, load_profile_llm_settings
from common.social_runtime import (
    FEISHU_BASE,
    feishu_headers,
    feishu_tenant_access_token,
    load_default_env_files,
)
from selfmedia.context import record_review_memory
from selfmedia.context.media_context import build_media_context_for_request, merge_conversation_context
from integrations.feishu.media_writer import upsert_entity_record
from media_model.payloads import build_business_opportunity_payload, build_metric_snapshot_payload
from media_vault.vault import MediaVault, make_timestamp_id


ROOT = Path(__file__).resolve().parents[2]
DATA_REVIEW_PATTERN = re.compile(r"^\s*【数据复盘】")
REQUEST_KEYS = (
    "平台|账号|作者ID|博主|赛道|类型|内容类型|主体|主题|标题|作品|作品标题|发布时间|发布链接|作品链接|"
    "创作记录ID|作品档案|数据节点|复盘节点|分析要求|要求|补充说明|用户想法|想法"
)
KEY_VALUE_RE = re.compile(rf"(?P<key>{REQUEST_KEYS})\s*[=:：]\s*(?P<value>.*?)(?=\s+(?:{REQUEST_KEYS})\s*[=:：]|$)")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic"}
CREATION_PLAN_FIELDS = (
    "title",
    "hook_3s",
    "validation_targets",
    "review_plan",
    "publishing_pack",
)

DEFAULT_GUIDE_URL = "https://tcnwueberajc.feishu.cn/wiki/UyFJwM6SEipIXokm5RFcz0XsnXg"
DEFAULT_OUTPUT_PARENT_NODE_TOKEN = os.getenv("MEDIA_OS_DATA_REVIEW_PARENT_NODE_TOKEN", "CNKdwXKFzi3Wb5k5ePpcbzcmnTg")

PLATFORM_VALUES = ["抖音", "小红书", "视频号", "B站", "未知"]
MEDIA_FORMAT_VALUES = ["视频", "图文", "笔记", "直播", "unknown"]
TRACK_VALUES = ["校园生活", "运动康复", "跑步训练", "AI科技", "学习方法", "职场成长", "生活方式", "商业合作", "所有赛道", "未提供", "其他"]
PERFORMANCE_LEVELS = ["高价值延续", "值得重剪", "观察", "不建议延续", "未评级"]

NOT_SHOWN_TEXT = "截图未显示"
GUIDANCE_LABELS = {
    "dimension": "维度",
    "category": "维度",
    "topic": "主题",
    "suggestion": "建议",
    "advice": "建议",
    "recommendation": "建议",
    "strategy": "策略",
    "action": "动作",
    "task": "动作",
    "reason": "原因",
    "evidence": "依据",
    "note": "说明",
    "details": "说明",
    "owner": "负责人",
    "deadline": "完成时间",
    "priority": "优先级",
}


@dataclass(frozen=True)
class DataReviewRequest:
    platform: str = ""
    account: str = ""
    track: str = ""
    content_type: str = ""
    topic: str = ""
    title: str = ""
    publish_time: str = ""
    publish_url: str = ""
    creation_record_id: str = ""
    data_window: str = ""
    analysis_requirements: str = ""
    notes: str = ""
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def handle_data_review_command(
    raw_text: str,
    *,
    tenant_id: str,
    attachment_paths: list[str] | None = None,
    no_write: bool = False,
    output_parent_node_token: str = "",
    guide_url: str = "",
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    load_default_env_files()
    vault = MediaVault(tenant_id=tenant_id)
    attachments = _existing_images(attachment_paths or [])
    request = parse_data_review_request(raw_text)
    reviewed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")

    if not attachments:
        return {
            "ok": False,
            "status": "missing_screenshots",
            "reply": "【数据复盘】未开始：请先上传抖音/小红书后台数据截图，再发送 `【数据复盘】`。",
        }

    guide_text = read_feishu_document_text(guide_url or DEFAULT_GUIDE_URL)
    creation_plan = resolve_creation_plan_for_review(tenant_id, request)
    resolved_creation_record_id = str(creation_plan.get("creation_record_id") or "").strip()
    if resolved_creation_record_id and resolved_creation_record_id != request.creation_record_id:
        request = replace(request, creation_record_id=resolved_creation_record_id)
    review_context = merge_conversation_context(
        build_media_context_for_request(request, tenant_id=tenant_id),
        conversation_context,
    )
    analysis = analyze_data_screenshots(
        request=request,
        screenshots=attachments,
        reviewed_at=reviewed_at,
        guide_text=guide_text,
        conversation_context=review_context,
        creation_plan=creation_plan,
    )
    normalized = normalize_analysis(analysis, request)

    output_dir = vault.root / "data_review_runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
    local_json = output_dir / f"{stamp}-data-review.json"
    local_md = output_dir / f"{stamp}-data-review.md"

    doc_link = ""
    record_id = ""
    memory_result: dict[str, Any] = {}
    media_model_v2_result: dict[str, Any] = {}
    if not no_write:
        doc_link = create_data_review_doc(
            request=request,
            analysis=normalized,
            screenshots=attachments,
            reviewed_at=reviewed_at,
            parent_node_token=output_parent_node_token or DEFAULT_OUTPUT_PARENT_NODE_TOKEN,
            guide_url=guide_url or DEFAULT_GUIDE_URL,
        )
        memory_result = record_review_memory(
            _review_memory_text(request, normalized),
            tenant_id=tenant_id,
            source="data-review",
            analysis=normalized,
        )
        media_model_v2_result = write_data_review_model_v2(
            tenant_id=tenant_id,
            request=request,
            analysis=normalized,
            screenshots=attachments,
            reviewed_at=reviewed_at,
            doc_link=doc_link,
            source_record_id=str(creation_plan.get("creation_record_id") or ""),
        )
        record_id = str(media_model_v2_result.get("post_id") or "")

    payload = {
        "ok": True,
        "status": "dry_run" if no_write else "written",
        "reviewed_at": reviewed_at,
        "request": request.to_dict(),
        "screenshots": attachments,
        "analysis": normalized,
        "creation_plan": creation_plan,
        "doc_link": doc_link,
        "record_id": record_id,
        "memory": memory_result,
        "media_model_v2": media_model_v2_result,
        "local_json": str(local_json),
        "local_report": str(local_md),
    }
    payload["reply"] = format_data_review_reply(payload)
    local_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    local_md.write_text(render_data_review_report(payload), encoding="utf-8")
    return payload


def parse_data_review_request(raw_text: str) -> DataReviewRequest:
    text = raw_text.strip()
    match = DATA_REVIEW_PATTERN.match(text)
    body = text[match.end():].strip() if match else text
    values = _parse_key_values(body)
    return DataReviewRequest(
        platform=(values.get("平台") or _infer_platform(body)).strip(),
        account=(values.get("账号") or values.get("作者ID") or values.get("博主") or "").strip(),
        track=(values.get("赛道") or "").strip(),
        content_type=(values.get("内容类型") or values.get("类型") or "").strip(),
        topic=(values.get("主体") or values.get("主题") or "").strip(),
        title=(values.get("标题") or values.get("作品") or values.get("作品标题") or "").strip(),
        publish_time=(values.get("发布时间") or "").strip(),
        publish_url=(values.get("发布链接") or values.get("作品链接") or "").strip(),
        creation_record_id=(values.get("创作记录ID") or values.get("作品档案") or "").strip(),
        data_window=(values.get("数据节点") or values.get("复盘节点") or "").strip(),
        analysis_requirements=(values.get("分析要求") or values.get("要求") or "").strip(),
        notes=(values.get("补充说明") or values.get("用户想法") or values.get("想法") or "").strip(),
        raw_text=raw_text,
    )

def _parse_key_values(body: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in KEY_VALUE_RE.finditer(body):
        key = match.group("key").strip()
        value = match.group("value").strip()
        if value:
            values[key] = value
    return values


def _infer_platform(text: str) -> str:
    if "小红书" in text or "xhslink" in text:
        return "小红书"
    if "抖音" in text or "douyin" in text:
        return "抖音"
    return ""


def _existing_images(paths: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(str(raw).strip()).expanduser()
        if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            continue
        mime = mimetypes.guess_type(path.name)[0] or ""
        if path.suffix.lower() not in IMAGE_EXTS and not mime.startswith("image/"):
            continue
        normalized = str(path)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def load_creation_plan(tenant_id: str, creation_record_id: str) -> dict[str, Any]:
    """Load the small, review-relevant projection of a prior CreationRun.

    A review must remain usable when the user does not supply an ID or the
    referenced run was pruned, so a missing artifact is explicit context rather
    than a hard failure. Only the fields needed for outcome comparison reach the
    review model.
    """
    run_id = str(creation_record_id or "").strip()
    if not run_id:
        return {"status": "not_requested", "creation_record_id": ""}
    vault = MediaVault(tenant_id=tenant_id)
    path = vault.creation_run_dir(run_id) / "draft_output.json"
    if not path.is_file():
        return {
            "status": "not_found",
            "creation_record_id": run_id,
            "reason": "creation_run_artifact_not_found",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "unreadable",
            "creation_record_id": run_id,
            "reason": "creation_run_artifact_unreadable",
        }
    if not isinstance(payload, dict):
        return {
            "status": "unreadable",
            "creation_record_id": run_id,
            "reason": "creation_run_artifact_invalid",
        }
    report = payload.get("creator_report") if isinstance(payload.get("creator_report"), dict) else {}
    overview = report.get("overview") if isinstance(report.get("overview"), dict) else {}
    publishing_pack = payload.get("publishing_pack")
    if not isinstance(publishing_pack, dict):
        publishing_pack = report.get("publishing_pack") if isinstance(report.get("publishing_pack"), dict) else {}
    plan = {
        "title": payload.get("title") or overview.get("recommended_topic") or "",
        "hook_3s": payload.get("hook_3s") or "",
        "validation_targets": payload.get("validation_targets") or {},
        "review_plan": payload.get("review_plan") or [],
        "publishing_pack": {
            key: publishing_pack.get(key)
            for key in ("title_1", "title_2", "cover_text", "pinned_comment", "comment_prompt", "first_hour_action")
            if publishing_pack.get(key) not in (None, "", [])
        },
    }
    return {
        "status": "loaded",
        "creation_record_id": run_id,
        "plan": {key: plan[key] for key in CREATION_PLAN_FIELDS},
    }


def resolve_creation_plan_for_review(tenant_id: str, request: DataReviewRequest) -> dict[str, Any]:
    """Resolve a review's CreationRun without crossing tenant boundaries.

    An explicit run ID is authoritative. Without one, only an exact published
    URL or exact title-plus-account match can be selected automatically. A
    review with multiple plausible plans stays unlinked until the creator picks
    a run instead of silently attributing evidence to the wrong work.
    """
    if request.creation_record_id:
        return load_creation_plan(tenant_id, request.creation_record_id)
    candidates = _matching_creation_run_ids(tenant_id, request)
    if len(candidates) == 1:
        plan = load_creation_plan(tenant_id, candidates[0])
        if plan.get("status") == "loaded":
            plan["matched_by"] = "publish_url_or_title_account"
        return plan
    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "creation_record_id": "",
            "candidate_creation_record_ids": candidates[:8],
            "reason": "multiple_creation_runs_match_review",
        }
    return {"status": "not_requested", "creation_record_id": ""}


def _matching_creation_run_ids(tenant_id: str, request: DataReviewRequest) -> list[str]:
    vault = MediaVault(tenant_id=tenant_id)
    runs_root = vault.root / "creation_runs"
    if not runs_root.is_dir():
        return []
    request_url = _canonical_public_url(request.publish_url)
    request_title = _match_text(request.title or request.topic)
    request_account = _match_text(request.account)
    matches: list[str] = []
    for run_dir in sorted(runs_root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        draft_path = run_dir / "draft_output.json"
        request_path = run_dir / "request.json"
        try:
            draft = json.loads(draft_path.read_text(encoding="utf-8")) if draft_path.is_file() else {}
            saved_request = json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(draft, dict) or not isinstance(saved_request, dict):
            continue
        saved_request = saved_request.get("request") if isinstance(saved_request.get("request"), dict) else saved_request
        saved_urls = {
            _canonical_public_url(value)
            for value in (
                draft.get("publish_url"),
                draft.get("published_url"),
                saved_request.get("publish_url"),
                saved_request.get("published_url"),
            )
            if _canonical_public_url(value)
        }
        if request_url and request_url in saved_urls:
            matches.append(run_id)
            continue
        saved_title = _match_text(draft.get("title") or saved_request.get("title") or saved_request.get("topic"))
        saved_account = _match_text(saved_request.get("account"))
        if request_title and request_account and saved_title == request_title and saved_account == request_account:
            matches.append(run_id)
    return matches


def _canonical_public_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def _match_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def analyze_data_screenshots(
    *,
    request: DataReviewRequest,
    screenshots: list[str],
    reviewed_at: str,
    guide_text: str,
    conversation_context: dict[str, Any],
    creation_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = (
        "你是 Media bot 的自媒体作品数据复盘分析器。只输出合法 JSON object，不要 Markdown，不要解释。\n"
        "任务：根据用户上传的抖音/小红书后台数据截图，完成作品数据分析、结论判断和下一步动作。\n"
        "要求：\n"
        "1. 只从截图和用户文字中抽取数据；看不清的字段必须写入 data_quality_notes，不要编造。\n"
        "2. metrics 用键值对记录截图中可见数据，例如 播放/阅读/曝光/点赞/收藏/评论/分享/完播率/互动率/新增关注/主页访问/发布时间。\n"
        "3. 如果截图包含曲线/趋势图，trend_curves 必须单独描述每条曲线：指标名、时间范围、峰值、拐点、衰减、二次推荐迹象、当前趋势；看不清则写不确定。\n"
        "4. 必须先判定作品形式 media_format：video=视频，image_text=图文/笔记，unknown=截图无法判断；必须给 media_format_evidence 说明截图依据。\n"
        "5. format_specific_metrics 必须按作品形式输出关键指标：video 至少关注 2s跳出率、完播率、5s完播率、平均播放时长、留存/跳出曲线、推荐页/流量来源；image_text 至少关注 封面点击率、曝光到观看转化、平均观看时长、互动率、收藏、评论、搜索/推荐来源。\n"
        "6. atomic_facts 必须构造“单一事实”列表，每条只表达一个可验证事实，不要把两个指标或建议混在一条里；格式为对象数组：fact, metric, value, scope, evidence, source, confidence, implication, recommended_use。\n"
        "7. priority_metrics 写 4-8 个最能指导后续发布的指标，不要简单罗列全部数据；格式为对象数组：metric, value, signal, why_it_matters, content_action。\n"
        "8. content_guidance 聚焦内容生产调整：选题、前2秒钩子、结构节奏、视频时长、封面标题、评论引导、目标人群。\n"
        "9. publishing_guidance 聚焦发布策略：发布时间、观察窗口、复投/重剪/停止标准、平台差异；没有截图依据则写不确定。\n"
        "10. conclusion 必须是一句话结论，说明这条作品是否值得延续、问题在哪里、下一步怎么做。\n"
        "11. key_insights 写 3-6 条数据洞察；next_actions 写可执行动作，不要泛泛建议。\n"
        "12. problems、content_guidance、publishing_guidance、next_actions、data_quality_notes 尽量输出对象数组，不要把多个维度挤进一条字符串。\n"
        "13. performance_level 只能是：高价值延续、值得重剪、观察、不建议延续、未评级。\n"
        "14. 不要为了填表重复输出同一批指标；原始可见数据放 metrics，作品形式专项指标放 format_specific_metrics，曲线只放 trend_curves，后续由脚本合并成表格字段。\n"
        "15. 当创作计划状态为 loaded 时，必须输出 plan_comparison 对象数组，逐条对照标题、前三秒钩子、验证指标、复盘计划和发布动作。每项包含 plan_item、status（已兑现/未兑现/证据不足）、evidence、next_step；没有计划时 plan_comparison 必须为空数组，且不得编造归因。\n"
        "16. 输出字段固定为：platform, account, media_format, media_format_evidence, format_specific_metrics, track, title, publish_time, data_window, metrics, atomic_facts, priority_metrics, trend_curves, metric_interpretation, conclusion, performance_level, key_insights, problems, content_guidance, publishing_guidance, next_actions, data_quality_notes, plan_comparison。\n"
    )
    user_payload = {
        "reviewed_at": reviewed_at,
        "user_request": request.to_dict(),
        "guide_or_template_from_feishu": guide_text[:20000],
        "recent_conversation_context": conversation_context.get("prompt", ""),
        "screenshot_count": len(screenshots),
        "creation_plan": creation_plan or {"status": "not_requested", "creation_record_id": ""},
    }
    parts: list[dict[str, Any]] = [
        {"text": prompt + "\n\n输入上下文：" + json.dumps(user_payload, ensure_ascii=False)},
    ]
    for index, path in enumerate(screenshots, 1):
        parts.append({"text": f"数据截图 {index}：{path}。请先 OCR 可见字段，再做复盘判断。"})
        parts.append(_image_part(path))
    config = load_llm_config()
    return generate_validated_review_json(
        parts,
        config,
        creation_plan_loaded=bool((creation_plan or {}).get("status") == "loaded"),
    )


def validate_data_review_analysis(payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("数据复盘模型输出必须是 JSON object")
    analysis = dict(payload)
    conclusion = str(analysis.get("conclusion") or "").strip()
    if not conclusion:
        raise ValueError("数据复盘结论不能为空")
    analysis["conclusion"] = conclusion
    analysis["performance_level"] = normalize_performance_rating(analysis.get("performance_level"))
    analysis["media_format"] = str(analysis.get("media_format") or "").strip()
    if analysis["media_format"] not in {"video", "image_text", "unknown"}:
        raise ValueError("数据复盘必须输出 media_format，且只能是 video/image_text/unknown")
    analysis["media_format_evidence"] = str(analysis.get("media_format_evidence") or "").strip()
    if not analysis["media_format_evidence"]:
        raise ValueError("数据复盘必须输出 media_format_evidence")
    if not isinstance(analysis.get("metrics"), dict):
        analysis["metrics"] = {}
    if not isinstance(analysis.get("format_specific_metrics"), dict):
        raise ValueError("数据复盘必须输出 format_specific_metrics")
    if not isinstance(analysis.get("trend_curves"), (dict, list)):
        analysis["trend_curves"] = {}
    analysis["atomic_facts"] = normalize_structured_list(analysis.get("atomic_facts"))
    if not analysis["atomic_facts"]:
        raise ValueError("数据复盘必须输出 atomic_facts 单一事实列表")
    analysis["priority_metrics"] = normalize_structured_list(analysis.get("priority_metrics"))
    if not analysis["priority_metrics"]:
        raise ValueError("数据复盘必须输出 priority_metrics 关键指标列表")
    for key in ("metric_interpretation", "key_insights", "problems", "content_guidance", "publishing_guidance", "next_actions", "data_quality_notes"):
        analysis[key] = normalize_text_list(analysis.get(key))
    if not analysis["content_guidance"]:
        raise ValueError("数据复盘必须输出 content_guidance 内容指导")
    if not analysis["publishing_guidance"]:
        raise ValueError("数据复盘必须输出 publishing_guidance 发布建议")
    analysis["plan_comparison"] = normalize_structured_list(analysis.get("plan_comparison"))
    if (context or {}).get("creation_plan_loaded"):
        if not analysis["plan_comparison"]:
            raise ValueError("已加载创作计划时必须输出 plan_comparison")
        allowed_statuses = {"已兑现", "未兑现", "证据不足"}
        for item in analysis["plan_comparison"]:
            if not str(item.get("plan_item") or "").strip():
                raise ValueError("plan_comparison 每项必须包含 plan_item")
            if str(item.get("status") or "").strip() not in allowed_statuses:
                raise ValueError("plan_comparison.status 必须为已兑现/未兑现/证据不足")
            if not str(item.get("evidence") or "").strip():
                raise ValueError("plan_comparison 每项必须包含 evidence")
            if not str(item.get("next_step") or "").strip():
                raise ValueError("plan_comparison 每项必须包含 next_step")
    return analysis


DATA_REVIEW_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.review.data_review.v1",
        profile="bounded_open",
        evidence_fields=("atomic_facts", "media_format_evidence"),
        validator=lambda payload, context: validate_data_review_analysis(payload, dict(context)),
    )
)


def normalize_text_list(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    parsed = parse_structured_text(value)
    if isinstance(parsed, str):
        return [item.strip(" -•\t") for item in re.split(r"[\n;；]+", parsed) if item.strip(" -•\t")]
    if isinstance(parsed, list):
        result: list[str] = []
        for item in parsed:
            item = parse_structured_text(item)
            if isinstance(item, list):
                result.extend(normalize_text_list(item))
                continue
            rendered = render_guidance_value(item)
            if rendered:
                result.append(rendered)
        return result
    rendered = render_guidance_value(parsed)
    return [rendered] if rendered else []


def render_guidance_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            rendered = render_guidance_value(item)
            if rendered:
                parts.append(f"{guidance_label(key)}：{rendered}")
        return "；".join(parts)
    if isinstance(value, list):
        return "、".join(item for item in (render_guidance_value(item) for item in value) if item)
    return str(value).strip()


def guidance_label(value: Any) -> str:
    label = str(value or "").strip()
    normalized = re.sub(r"[ _-]+", " ", label).lower()
    return GUIDANCE_LABELS.get(normalized, label)


def normalize_table_items(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    items = value if isinstance(value, list) else [value]
    result: list[Any] = []
    for item in items:
        parsed = parse_structured_text(item)
        if isinstance(parsed, list):
            result.extend(parsed)
            continue
        if parsed not in (None, "", []):
            result.append(parsed)
    return result


def normalize_labeled_items(value: Any, label: str) -> list[dict[str, Any]]:
    normalized = normalize_table_items(value)
    result: list[dict[str, Any]] = []
    for item in normalized:
        if isinstance(item, dict):
            result.append(item)
            continue
        text = str(item or "").strip()
        if not text:
            continue
        match = re.match(r"^([^：:]{1,24})[：:]\s*(.+)$", text)
        if match:
            result.append({"维度": match.group(1).strip(), label: match.group(2).strip()})
        else:
            result.append({label: text})
    return result


def parse_structured_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    if text[:1] not in {"{", "["}:
        return text
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
    return text


def normalize_structured_list(value: Any) -> list[dict[str, Any]]:
    if value in (None, "", []):
        return []
    items = value if isinstance(value, list) else [value]
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            clean = {str(key).strip(): item_value for key, item_value in item.items() if str(key).strip() and item_value not in (None, "", [])}
            if clean:
                result.append(clean)
            continue
    return result


def normalize_analysis(raw: dict[str, Any], request: DataReviewRequest) -> dict[str, Any]:
    analysis = dict(raw)
    for key, request_value in {
        "platform": request.platform,
        "account": request.account,
        "content_type": request.content_type,
        "media_format": "",
        "media_format_evidence": "",
        "track": request.track,
        "topic": request.topic,
        "title": request.title or request.topic,
        "publish_time": request.publish_time,
        "data_window": request.data_window,
    }.items():
        analysis[key] = str(analysis.get(key) or request_value or "").strip()
    analysis["metrics"] = analysis.get("metrics") if isinstance(analysis.get("metrics"), dict) else {}
    return analysis


def normalize_platform_tags(value: Any) -> list[str]:
    mapping = {
        "douyin": "抖音",
        "dy": "抖音",
        "抖音": "抖音",
        "巨量": "抖音",
        "xhs": "小红书",
        "xiaohongshu": "小红书",
        "rednote": "小红书",
        "小红书": "小红书",
        "视频号": "视频号",
        "wechat_channels": "视频号",
        "wechat channel": "视频号",
        "b站": "B站",
        "bilibili": "B站",
    }
    return normalize_select_tags(value, default="未知", mapping=mapping, allowed=PLATFORM_VALUES)


def normalize_media_format_tags(value: Any) -> list[str]:
    mapping = {
        "video": "视频",
        "视频": "视频",
        "short_video": "视频",
        "image_text": "图文",
        "image-text": "图文",
        "图文": "图文",
        "笔记": "笔记",
        "note": "笔记",
        "live": "直播",
        "直播": "直播",
        "unknown": "unknown",
        "未知": "unknown",
    }
    return normalize_select_tags(value, default="unknown", mapping=mapping, allowed=MEDIA_FORMAT_VALUES)


def normalize_track_tags(value: Any) -> list[str]:
    mapping = {
        "校园": "校园生活",
        "校园生活": "校园生活",
        "清华": "校园生活",
        "运动": "运动康复",
        "运动康复": "运动康复",
        "膝盖": "运动康复",
        "跑步": "跑步训练",
        "跑步训练": "跑步训练",
        "ai": "AI科技",
        "ai科技": "AI科技",
        "科技": "AI科技",
        "学习": "学习方法",
        "学习方法": "学习方法",
        "职场": "职场成长",
        "职场成长": "职场成长",
        "生活": "生活方式",
        "生活方式": "生活方式",
        "商务": "商业合作",
        "商业合作": "商业合作",
        "所有赛道": "所有赛道",
        "未提供": "未提供",
        "其他": "其他",
    }
    return normalize_select_tags(value, default="未提供", mapping=mapping, allowed=TRACK_VALUES)


def normalize_performance_rating(value: Any) -> str:
    text = _select_source_text(value)
    if any(word in text for word in ("重剪", "中低", "留存", "跳出", "推荐不足")):
        return "值得重剪"
    if any(word in text for word in ("高价值", "较好", "优秀", "值得延续", "强正向")):
        return "高价值延续"
    if any(word in text for word in ("不建议", "停止", "低价值")):
        return "不建议延续"
    if "观察" in text:
        return "观察"
    return normalize_single_select(value, default="未评级", mapping={"未评级": "未评级"}, allowed=PERFORMANCE_LEVELS)


def normalize_select_tags(value: Any, *, default: str, mapping: dict[str, str], allowed: list[str]) -> list[str]:
    if value in (None, "", []):
        return [default]
    raw_items = value if isinstance(value, list) else re.split(r"[,，/、;；|]\s*", str(value))
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        text = str(raw or "").strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text).lower()
        mapped = mapping.get(key) or mapping.get(text) or text
        if mapped not in allowed:
            mapped = default
        if mapped and mapped not in seen:
            seen.add(mapped)
            result.append(mapped)
    return result or [default]


def normalize_single_select(value: Any, *, default: str, mapping: dict[str, str], allowed: list[str]) -> str:
    text = _select_source_text(value)
    if not text:
        return default
    key = re.sub(r"\s+", " ", text).lower()
    mapped = mapping.get(key) or mapping.get(text) or text
    return mapped if mapped in allowed else default


def _select_source_text(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, list):
        return str(next((item for item in value if str(item).strip()), "")).strip()
    return str(value).strip()


def build_data_quality_json(analysis: dict[str, Any]) -> dict[str, Any]:
    quality = {
        "作品形式依据": _required_text(analysis.get("media_format_evidence"), NOT_SHOWN_TEXT),
        "截图识别说明": normalize_labeled_items(analysis.get("data_quality_notes") or [], "说明"),
    }
    return quality


def _required_text(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _required_json(value: Any, default: Any) -> Any:
    if value in (None, "", []):
        return default
    return value


def write_data_review_model_v2(
    *,
    tenant_id: str,
    request: DataReviewRequest,
    analysis: dict[str, Any],
    screenshots: list[str],
    reviewed_at: str,
    doc_link: str,
    source_record_id: str,
) -> dict[str, Any]:
    post_reviews_url = os.getenv("MEDIA_OS_POST_REVIEWS_URL", "").strip()
    metric_snapshot_url = os.getenv("MEDIA_OS_METRIC_SNAPSHOT_URL", "").strip()
    if not post_reviews_url or not metric_snapshot_url:
        raise RuntimeError("missing MEDIA_OS_POST_REVIEWS_URL or MEDIA_OS_METRIC_SNAPSHOT_URL")
    post_id = f"post_{source_record_id}" if source_record_id else make_timestamp_id("post_review", token_bytes=2)
    review_node = str(analysis.get("data_window") or request.data_window or "unknown").strip() or "unknown"
    vault = MediaVault(tenant_id=tenant_id)
    review_artifacts = vault.write_post_review(
        post_id,
        review_node,
        metrics={
            "metrics": analysis.get("metrics") or {},
            "priority_metrics": analysis.get("priority_metrics") or [],
            "atomic_facts": analysis.get("atomic_facts") or [],
            "trend_curves": analysis.get("trend_curves") or {},
            "data_quality": build_data_quality_json(analysis),
            "screenshots": screenshots,
            "reviewed_at": reviewed_at,
        },
        review_markdown=render_data_review_report(
            {
                "request": request.to_dict(),
                "analysis": analysis,
                "screenshots": screenshots,
                "doc_link": doc_link,
                "record_id": source_record_id,
                "reviewed_at": reviewed_at,
            }
        ),
    )
    review_artifact_uri = review_artifacts["metrics"]["uri"]
    post_payload = {
        "post_id": post_id,
        "creation_run_id": source_record_id or request.creation_record_id,
        "platform": analysis.get("platform") or request.platform or "unknown",
        "published_url": request.publish_url,
        "review_node": review_node,
        "performance_rating": normalize_performance_rating(analysis.get("performance_level")),
        "key_metrics_summary": analysis.get("conclusion") or "",
        "review_doc_link": doc_link,
        "review_artifact_uri": review_artifact_uri,
    }
    post_write = upsert_entity_record(
        "PublishedPost",
        post_reviews_url,
        post_payload,
        key_field="post_id",
        session_tenant_id=tenant_id,
    )
    metric_writes: list[dict[str, Any]] = []
    for metric in _metric_snapshot_payloads(post_id, review_node, analysis, review_artifact_uri):
        metric_writes.append(
            upsert_entity_record(
                "MetricSnapshot",
                metric_snapshot_url,
                metric,
                key_field="snapshot_id",
                session_tenant_id=tenant_id,
            )
        )
    business_delivery_writes = _write_selected_business_deliveries(
        tenant_id=tenant_id,
        creation_run_id=source_record_id or request.creation_record_id,
        review_artifact_uri=review_artifact_uri,
        published_url=request.publish_url,
        delivered_at=reviewed_at,
    )
    return {
        "post_id": post_id,
        "review_artifact_uri": review_artifact_uri,
        "post_review_record_id": post_write.get("record_id", ""),
        "metric_snapshot_count": len(metric_writes),
        "metric_snapshot_record_ids": [item.get("record_id", "") for item in metric_writes],
        "business_delivery_count": len(business_delivery_writes),
        "business_delivery_record_ids": [item.get("record_id", "") for item in business_delivery_writes],
    }


def _write_selected_business_deliveries(
    *,
    tenant_id: str,
    creation_run_id: str,
    review_artifact_uri: str,
    published_url: str,
    delivered_at: str,
) -> list[dict[str, Any]]:
    """Advance only the business candidates explicitly selected by this run."""
    run_id = str(creation_run_id or "").strip()
    if not run_id:
        return []
    candidates = _selected_business_candidates(tenant_id, run_id)
    if not candidates:
        return []
    table_url = os.getenv("MEDIA_OS_BUSINESS_OPPORTUNITIES_URL", "").strip()
    if not table_url:
        raise RuntimeError("missing MEDIA_OS_BUSINESS_OPPORTUNITIES_URL for selected business delivery writeback")
    writes: list[dict[str, Any]] = []
    for record in candidates:
        payload = _business_delivery_payload(
            record,
            run_id=run_id,
            review_artifact_uri=review_artifact_uri,
            published_url=published_url,
            delivered_at=delivered_at,
        )
        writes.append(
            upsert_entity_record(
                "BusinessOpportunity",
                table_url,
                payload,
                key_field="opportunity_id",
                session_tenant_id=tenant_id,
            )
        )
    return writes


def _selected_business_candidates(tenant_id: str, run_id: str) -> list[dict[str, Any]]:
    vault = MediaVault(tenant_id=tenant_id)
    run_dir = vault.creation_run_dir(run_id)
    traces = _read_json_object(run_dir / "decision_trace.json", default=[])
    candidates = _read_json_object(run_dir / "retrieval_candidates.json", default={})
    if not isinstance(traces, list) or not isinstance(candidates, dict):
        return []
    selected_ids = {
        str(item.get("candidate_id") or "").strip()
        for item in traces
        if isinstance(item, dict) and item.get("candidate_type") == "business" and item.get("selected") is True
    }
    if not selected_ids:
        return []
    selected: list[dict[str, Any]] = []
    for item in candidates.get("businesses") or []:
        if not isinstance(item, dict):
            continue
        record = item.get("record")
        if not isinstance(record, dict):
            continue
        candidate_id = _business_candidate_id(record)
        if candidate_id in selected_ids:
            selected.append(record)
    missing = selected_ids - {_business_candidate_id(record) for record in selected}
    if missing:
        raise RuntimeError(f"selected business decision has no matching retrieval candidate: {sorted(missing)}")
    return selected


def _read_json_object(path: Path, *, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read CreationRun artifact: {path}") from exc


def _business_candidate_id(record: dict[str, Any]) -> str:
    return str(
        record.get("relation_id")
        or record.get("source_record_id")
        or record.get("source_link")
        or record.get("title")
        or ""
    ).strip()


def _business_delivery_payload(
    record: dict[str, Any],
    *,
    run_id: str,
    review_artifact_uri: str,
    published_url: str,
    delivered_at: str,
) -> dict[str, Any]:
    details = record.get("detail_json") if isinstance(record.get("detail_json"), dict) else {}
    opportunity_id = _business_candidate_id(record)
    brand = str(details.get("brand") or "").strip()
    if not opportunity_id or not brand:
        raise RuntimeError("selected BusinessOpportunity is missing opportunity_id or brand")
    linked_run_ids = details.get("linked_run_ids")
    if not isinstance(linked_run_ids, list):
        linked_run_ids = [linked_run_ids] if linked_run_ids else []
    return build_business_opportunity_payload(
        opportunity_id=opportunity_id,
        brand=brand,
        business_account_id=str(details.get("business_account_id") or ""),
        product=str(details.get("product") or ""),
        platform=str(details.get("platform") or record.get("platform") or ""),
        content_type=str(details.get("content_type") or record.get("content_type_requirement") or ""),
        brief_link=str(details.get("brief_link") or record.get("source_link") or ""),
        current_quote_amount=details.get("current_quote_amount"),
        rebate_ratio=details.get("rebate_ratio"),
        valid_from=str(details.get("valid_from") or record.get("start_time") or ""),
        valid_until=str(details.get("valid_until") or record.get("end_time") or ""),
        schedule=str(details.get("schedule") or ""),
        price_protection_policy=str(details.get("price_protection_policy") or ""),
        authorization_scope=str(details.get("authorization_scope") or ""),
        authorization_duration=str(details.get("authorization_duration") or ""),
        quote_snapshot_uri=str(details.get("quote_snapshot_uri") or ""),
        lifecycle_status="delivered",
        linked_run_ids=[*linked_run_ids, run_id],
        delivery_evidence_uri=review_artifact_uri,
        delivery_published_url=published_url,
        delivered_at=delivered_at,
        settlement_evidence_uri=str(details.get("settlement_evidence_uri") or ""),
        settled_at=str(details.get("settled_at") or ""),
    )


def _metric_snapshot_payloads(post_id: str, review_node: str, analysis: dict[str, Any], evidence_uri: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for index, item in enumerate(analysis.get("priority_metrics") or [], 1):
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("metric") or item.get("name") or "").strip()
        metric_key = _metric_key(raw_name)
        if not metric_key:
            continue
        numeric = _metric_number(item.get("value"))
        if numeric is None:
            continue
        unit = "%" if "%" in str(item.get("value") or "") else "次"
        payloads.append(
            build_metric_snapshot_payload(
                snapshot_id=f"{post_id}_{review_node}_{metric_key}_{index}",
                post_id=post_id,
                review_node=review_node,
                metric_key=metric_key,
                raw_metric_name=raw_name,
                metric_value=numeric,
                unit=unit,
                evidence_uri=evidence_uri,
                data_quality="screenshot_only",
            )
        )
    return payloads


def _metric_key(raw_name: str) -> str:
    text = raw_name.lower()
    if any(word in raw_name for word in ("曝光", "展现")) or "impression" in text:
        return "impressions"
    if any(word in raw_name for word in ("播放", "观看")) or "view" in text:
        return "views"
    if "阅读" in raw_name or "read" in text:
        return "reads"
    if "点赞" in raw_name or "like" in text:
        return "likes"
    if "收藏" in raw_name or "save" in text or "collect" in text:
        return "saves"
    if "评论" in raw_name or "comment" in text:
        return "comments"
    if "分享" in raw_name or "share" in text:
        return "shares"
    if "吸粉" in raw_name or "涨粉" in raw_name or "follow" in text:
        return "follows"
    return ""


def _metric_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def create_data_review_doc(
    *,
    request: DataReviewRequest,
    analysis: dict[str, Any],
    screenshots: list[str],
    reviewed_at: str,
    parent_node_token: str,
    guide_url: str,
) -> str:
    from selfmedia.creation import writer

    token = feishu_tenant_access_token()
    title = doc_title(analysis, reviewed_at)
    old_parent = os.environ.get("FEISHU_CREATION_DOC_PARENT_NODE_TOKEN")
    os.environ["FEISHU_CREATION_DOC_PARENT_NODE_TOKEN"] = parent_node_token
    try:
        document_id, node_token, created = writer._create_doc(title, token)
    finally:
        if old_parent is None:
            os.environ.pop("FEISHU_CREATION_DOC_PARENT_NODE_TOKEN", None)
        else:
            os.environ["FEISHU_CREATION_DOC_PARENT_NODE_TOKEN"] = old_parent
    blocks = data_review_doc_blocks(title, request, analysis, screenshots, reviewed_at, guide_url)
    if created:
        writer._append_blocks(document_id, blocks, token)
    else:
        writer._replace_blocks(document_id, blocks, token)
    append_screenshot_images(document_id, screenshots, token)
    return f"https://tcnwueberajc.feishu.cn/docx/{document_id}"


def doc_title(analysis: dict[str, Any], reviewed_at: str) -> str:
    dt = reviewed_at.replace("-", "").replace(":", "").replace("T", "-")[:15]
    platform = str(analysis.get("platform") or "平台未识别").strip()
    account = str(analysis.get("account") or "账号未填").strip()
    topic = str(analysis.get("topic") or analysis.get("title") or "作品").strip()
    topic = re.sub(r"[^\w\u4e00-\u9fff]+", "", topic)[:18] or "作品"
    return f"数据复盘｜{platform}｜{account}｜{topic}｜{dt}"


def data_review_doc_blocks(
    title: str,
    request: DataReviewRequest,
    analysis: dict[str, Any],
    screenshots: list[str],
    reviewed_at: str,
    guide_url: str,
) -> list[dict[str, Any]]:
    return [
        _heading(1, title),
        _paragraph(f"复盘时间：{reviewed_at}"),
        _paragraph(f"平台：{analysis.get('platform') or request.platform or '未识别'}"),
        _paragraph(f"账号：{analysis.get('account') or request.account or '未填写'}"),
        _paragraph(f"作品：{analysis.get('title') or analysis.get('topic') or request.title or request.topic or '未填写'}"),
        _paragraph(f"作品形式：{analysis.get('media_format') or 'unknown'}；依据：{analysis.get('media_format_evidence') or '未填写'}"),
        _paragraph(f"数据截图：{len(screenshots)} 张"),
        _paragraph(f"参考模板：{guide_url}"),
        _heading(2, "一、核心结论"),
        _paragraph(str(analysis.get("conclusion") or "")),
        _heading(2, "二、创作计划对照"),
        *_list_blocks(_review_lines(analysis.get("plan_comparison"))),
        _heading(2, "三、下一步动作"),
        *_list_blocks(_review_lines(analysis.get("next_actions"))),
        _heading(2, "四、内容调整"),
        *_list_blocks(_review_lines(analysis.get("content_guidance"))),
        _heading(2, "五、发布建议"),
        *_list_blocks(_review_lines(analysis.get("publishing_guidance"))),
        _heading(2, "六、关键数据"),
        *_list_blocks(_review_lines(analysis.get("metrics"))),
        _heading(2, "七、作品形式专项指标"),
        *_list_blocks(_review_lines(analysis.get("format_specific_metrics"))),
        _heading(2, "八、数据解释"),
        *_list_blocks(_review_lines(analysis.get("metric_interpretation") or analysis.get("key_insights"))),
        _heading(2, "九、问题判断"),
        *_list_blocks(_review_lines(analysis.get("problems"))),
        _heading(2, "十、关键事实与趋势依据"),
        *_list_blocks(_review_lines(analysis.get("atomic_facts"))),
        *_list_blocks(_review_lines(analysis.get("priority_metrics"))),
        *_list_blocks(_review_lines(analysis.get("trend_curves"))),
        _heading(2, "十一、截图与可信度"),
        _paragraph("\n".join(screenshots)),
        *_list_blocks(_review_lines(analysis.get("data_quality_notes") or ["截图字段可读"])),
    ]


def _heading(level: int, text: str) -> dict[str, Any]:
    normalized = min(max(level, 1), 9)
    return {
        "block_type": normalized + 2,
        f"heading{normalized}": {"elements": [{"text_run": {"content": str(text or "")[:500]}}]},
    }


def _paragraph(text: str) -> dict[str, Any]:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": str(text or "")[:1800]}}]}}


_REVIEW_LABELS = {
    "fact": "事实",
    "metric": "指标",
    "name": "指标",
    "value": "数值",
    "scope": "范围",
    "evidence": "依据",
    "source": "来源",
    "confidence": "可信度",
    "implication": "含义",
    "recommended_use": "建议用途",
    "signal": "信号",
    "why_it_matters": "重要原因",
    "content_action": "内容动作",
    "peak": "峰值",
    "turning_point": "拐点",
    "trend": "趋势",
    "views": "播放/阅读",
    "impressions": "曝光",
    "likes": "点赞",
    "saves": "收藏",
    "comments": "评论",
    "shares": "分享",
    "follows": "新增关注",
    "retention": "留存",
    "traffic": "流量来源",
    "interaction": "互动",
    "audience": "受众",
    "diagnosis": "平台诊断",
    "plan_item": "计划项",
    "status": "对照结果",
    "next_step": "后续动作",
}


def _review_label(key: Any) -> str:
    text = str(key or "").strip()
    if text in _REVIEW_LABELS:
        return _REVIEW_LABELS[text]
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return text
    return "说明"


def _review_value(value: Any, *, depth: int = 0) -> str:
    if depth > 3:
        return "内容较多，详见复盘产物"
    if value in (None, "", []):
        return "未提供"
    if isinstance(value, dict):
        return "；".join(
            f"{_review_label(key)}：{_review_value(item, depth=depth + 1)}"
            for key, item in value.items()
            if item not in (None, "", [])
        ) or "未提供"
    if isinstance(value, list):
        return "；".join(_review_value(item, depth=depth + 1) for item in value[:12]) or "未提供"
    return str(value).strip() or "未提供"


def _review_lines(value: Any) -> list[str]:
    if value in (None, "", []):
        return ["暂无"]
    if isinstance(value, dict):
        return [
            f"{_review_label(key)}：{_review_value(item)}"
            for key, item in value.items()
            if item not in (None, "", [])
        ] or ["暂无"]
    items = value if isinstance(value, list) else [value]
    return [_review_value(item) for item in items[:12] if item not in (None, "", [])] or ["暂无"]


def _list_blocks(value: Any) -> list[dict[str, Any]]:
    clean = normalize_text_list(value)
    if not clean:
        clean = ["暂无"]
    return [_paragraph(f"{index}. {item}") for index, item in enumerate(clean, 1)]


def append_screenshot_images(document_id: str, screenshots: list[str], token: str) -> None:
    if not screenshots:
        return
    _post_docx_children(document_id, document_id, [_heading(2, "十三、后台截图原图")], token)
    for path in screenshots[:12]:
        payload = _post_docx_children(document_id, document_id, [{"block_type": 27, "image": {}}], token)
        image_block_id = _find_created_block_id(payload, 27)
        if not image_block_id:
            continue
        file_token = upload_doc_image(document_id, image_block_id, path, token)
        requests.patch(
            f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{image_block_id}",
            headers=feishu_headers(token),
            json={"replace_image": {"token": file_token}},
            params={"document_revision_id": -1},
            timeout=20,
        ).raise_for_status()


def _post_docx_children(document_id: str, parent_block_id: str, children: list[dict[str, Any]], token: str) -> dict[str, Any]:
    resp = requests.post(
        f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children",
        headers=feishu_headers(token),
        json={"children": children},
        params={"document_revision_id": -1},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"写入飞书截图块失败：{payload}")
    return payload


def _find_created_block_id(payload: dict[str, Any], block_type: int) -> str:
    def visit(value: Any) -> str:
        if isinstance(value, dict):
            if value.get("block_type") == block_type and value.get("block_id"):
                return str(value["block_id"])
            for child in value.values():
                found = visit(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found:
                    return found
        return ""

    return visit(payload)


def upload_doc_image(document_id: str, image_block_id: str, file_path: str, token: str) -> str:
    path = Path(file_path)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    with path.open("rb") as handle:
        resp = requests.post(
            f"{FEISHU_BASE}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": path.name,
                "parent_type": "docx_image",
                "parent_node": image_block_id or document_id,
                "size": str(path.stat().st_size),
                "mime_type": mime,
            },
            files={"file": (path.name, handle, mime)},
            timeout=60,
        )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"上传飞书截图失败：{payload}")
    file_token = str(payload.get("data", {}).get("file_token") or "")
    if not file_token:
        raise RuntimeError(f"上传飞书截图未返回 file_token：{payload}")
    return file_token


def read_feishu_document_text(url: str) -> str:
    if not url:
        raise RuntimeError("数据复盘模板链接不能为空")
    token = feishu_tenant_access_token()
    document_id = resolve_document_id(url, token)
    if not document_id:
        raise RuntimeError(f"无法解析数据复盘模板文档：{url}")
    resp = requests.get(f"{FEISHU_BASE}/docx/v1/documents/{document_id}/raw_content", headers=feishu_headers(token), timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"读取数据复盘模板失败：{payload}")
    return extract_readable_text(payload)


def resolve_document_id(url: str, token: str) -> str:
    parsed = urlparse(url)
    segments = [item for item in parsed.path.split("/") if item]
    for index, segment in enumerate(segments):
        if segment in {"docx", "doc", "docs"} and index + 1 < len(segments):
            return re.sub(r"[^A-Za-z0-9_-]", "", segments[index + 1])
        if segment == "wiki" and index + 1 < len(segments):
            node_token = re.sub(r"[^A-Za-z0-9_-]", "", segments[index + 1])
            resp = requests.get(f"{FEISHU_BASE}/wiki/v2/spaces/get_node", params={"token": node_token}, headers=feishu_headers(token), timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            node = payload.get("data", {}).get("node") or {}
            return str(node.get("obj_token") or "")
    return ""


def extract_readable_text(payload: Any, *, limit: int = 30000) -> str:
    values: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if len("\n".join(values)) >= limit:
            return
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
            return
        if isinstance(value, list):
            for item in value:
                visit(item, key)
            return
        if not isinstance(value, str):
            return
        clean = value.strip()
        if not clean:
            return
        if key in {"content", "text", "plain_text", "raw_content", "title", "summary"} or len(clean) >= 12:
            values.append(clean)

    visit(payload)
    seen: set[str] = set()
    lines: list[str] = []
    for value in values:
        for line in value.splitlines():
            clean = line.strip()
            if clean and clean not in seen:
                seen.add(clean)
                lines.append(clean)
            if len("\n".join(lines)) >= limit:
                return "\n".join(lines)[:limit]
    return "\n".join(lines)[:limit]


def _review_memory_text(request: DataReviewRequest, analysis: dict[str, Any]) -> str:
    metrics = analysis.get("metrics") or {}
    metric_bits = []
    for key in ("播放", "播放量", "阅读", "阅读量", "曝光", "点赞", "赞", "收藏", "评论", "分享", "转发", "完播率", "互动率", "新增关注", "涨粉"):
        if key in metrics:
            metric_bits.append(f"{key}={metrics[key]}")
    priority_bits = []
    for item in analysis.get("priority_metrics") or []:
        if isinstance(item, dict) and item.get("metric"):
            priority_bits.append(f"{item.get('metric')}={item.get('value') or item.get('signal') or ''}".strip("="))
    return " ".join(
        item
        for item in [
            "【数据复盘】",
            f"平台={analysis.get('platform') or request.platform}" if analysis.get("platform") or request.platform else "",
            f"账号={analysis.get('account') or request.account}" if analysis.get("account") or request.account else "",
            f"主题={analysis.get('topic') or analysis.get('title') or request.topic or request.title}" if analysis.get("topic") or analysis.get("title") or request.topic or request.title else "",
            " ".join(metric_bits),
            f"关键指标={'；'.join(priority_bits)}" if priority_bits else "",
            f"结论={analysis.get('conclusion') or ''}",
            f"下一步={'；'.join(normalize_text_list(analysis.get('next_actions')))}",
        ]
        if item
    )


def format_data_review_reply(payload: dict[str, Any]) -> str:
    analysis = payload.get("analysis") or {}
    lines = [
        "【数据复盘】已完成" if payload.get("ok") else "【数据复盘】已部分完成",
        f"结论：{analysis.get('conclusion') or ''}",
        f"复盘文档：{payload['doc_link']}" if payload.get("doc_link") else "",
        f"表现评级：{analysis.get('performance_level') or '未评级'}",
        f"平台：{analysis.get('platform') or '未识别'}",
        f"账号：{analysis.get('account') or '未填写'}",
    ]
    creation_plan = payload.get("creation_plan") if isinstance(payload.get("creation_plan"), dict) else {}
    if creation_plan.get("status") == "loaded":
        lines.append("已按创作计划完成对照复盘")
    elif creation_plan.get("creation_record_id"):
        lines.append("创作记录未找到，本次未做创作计划对照")
    return "\n".join(line for line in lines if line)


def render_data_review_report(payload: dict[str, Any]) -> str:
    analysis = payload.get("analysis") or {}
    sections = (
        ("创作计划对照", analysis.get("plan_comparison")),
        ("下一步动作", analysis.get("next_actions")),
        ("内容调整", analysis.get("content_guidance")),
        ("发布建议", analysis.get("publishing_guidance")),
        ("关键数据", analysis.get("metrics")),
        ("作品形式专项指标", analysis.get("format_specific_metrics")),
        ("数据解释", analysis.get("metric_interpretation") or analysis.get("key_insights")),
        ("问题判断", analysis.get("problems")),
        ("关键事实与趋势依据", [
            *(analysis.get("atomic_facts") or []),
            *(analysis.get("priority_metrics") or []),
            analysis.get("trend_curves") or {},
        ]),
    )
    lines = [
        "# 数据复盘",
        "",
        f"时间戳：{payload.get('reviewed_at') or ''}",
        "",
        "## 核心结论",
        "",
        str(analysis.get("conclusion") or ""),
        "",
        "## 作品形式",
        "",
        f"{analysis.get('media_format') or 'unknown'}：{analysis.get('media_format_evidence') or ''}",
    ]
    for title, value in sections:
        lines.extend(["", f"## {title}", "", *(f"- {item}" for item in _review_lines(value))])
    return "\n".join(lines) + "\n"
def _image_part(path: str) -> dict[str, Any]:
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return {"image_data": {"mime_type": mime, "data": data, "path": str(p)}}


def load_llm_config() -> dict[str, Any]:
    settings = load_profile_llm_settings("media_analysis")
    return {
        "model": settings.model,
        "base_url": settings.base_url,
        "api_key": settings.api_key,
        "api_type": settings.api_type,
        "timeout": settings.timeout,
        "thinking": settings.thinking,
        "bin": settings.bin,
        "agent": settings.agent,
        "cwd": settings.cwd,
        "codex_home": settings.codex_home,
    }


def generate_validated_review_json(
    parts: list[dict[str, Any]],
    config: dict[str, Any],
    max_retries: int = 2,
    *,
    creation_plan_loaded: bool = False,
) -> dict[str, Any]:
    return common_generate_json_from_parts(
        parts,
        _llm_provider_from_dict(config),
        max_retries=max_retries,
        error_prefix="数据复盘 LLM 输出 JSON 校验失败",
        validation_contract=DATA_REVIEW_VALIDATION_CONTRACT,
        validation_context={"creation_plan_loaded": creation_plan_loaded},
    )


def _llm_provider_from_dict(config: dict[str, Any]) -> LLMProviderSettings:
    return LLMProviderSettings(
        model=str(config.get("model") or ""),
        base_url=str(config.get("base_url") or "").rstrip("/"),
        api_key=str(config.get("api_key") or ""),
        api_type=str(config.get("api_type") or "openai_chat_completions"),
        timeout=float(config.get("timeout") or 1200),
        thinking=str(config.get("thinking") or ""),
        bin=str(config.get("bin") or ""),
        agent=str(config.get("agent") or ""),
        cwd=str(config.get("cwd") or ""),
        codex_home=str(config.get("codex_home") or ""),
    )
