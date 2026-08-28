from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from common.llm_validation import LLMValidationContract, register_llm_validation_contract
from media_model.payloads import normalize_source_url
from selfmedia.context import build_media_context_for_request, merge_conversation_context
from selfmedia.business.schedule import LOCAL_TZ
from media_vault import require_tenant_id

from .adapters import ViralContentAdapter
from .deconstruction_artifact import DeconstructionArtifactUnavailable, attach_deconstruction_artifact_brief
from .field_contract import normalize_content_type, normalize_platform, split_tags
from .llm_generator import call_creation_json
from .media_model_v2_writeback import write_creation_model_v2
from .request_parser import CreationRequest, extract_source_asset_id
from .retrieval import load_material_candidate_rows_for_creation
from .writer import create_shooting_execution_doc


SHOOTING_PATTERN = re.compile(r"^\s*【创作-拍摄执行】")
REQUEST_KEYS = "平台|类型|内容类型|赛道|主体|主题|拍摄目标|目标|场地|地点|人物|时间窗口|总时长|发布时间|参考链接|必拍|约束|项目|账号|关键词|标签|source_asset_id|source|来源|素材源ID|SourceAsset来源ID"
KEY_VALUE_RE = re.compile(rf"(?P<key>{REQUEST_KEYS})\s*[=:：]\s*(?P<value>.*?)(?=\n(?:{REQUEST_KEYS})\s*[=:：]|\s+(?:{REQUEST_KEYS})\s*[=:：]|$)", re.S)

SHOOTING_REQUEST_FIELDS = frozenset({
    "platform", "content_type", "track", "topic", "shooting_goal", "locations", "people",
    "time_window", "publish_time", "project", "account", "reference_links", "must_shoot",
    "constraints", "source_asset_id",
})
SHOOTING_PRIORITY_LABELS = {
    "P0": "必拍",
    "P1": "重要",
    "P2": "可选",
    "必拍": "必拍",
    "重要": "重要",
    "可选": "可选",
}
EVIDENCE_SOURCE_STATUS_LABELS = {
    "confirmed": "已核验",
    "manual_description_only": "仅凭文字描述，未看过原片",
    "pending_manual": "待人工核实",
    "已核验": "已核验",
    "仅凭文字描述，未看过原片": "仅凭文字描述，未看过原片",
    "待人工核实": "待人工核实",
}


def _validate_shooting_request(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    if not any(value not in (None, "", [], {}) for value in payload.values()):
        raise ValueError("shooting request returned no usable fields")
    return payload


SHOOTING_REQUEST_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.creation.shooting_request.v1",
        profile="strict_structured",
        allowed_fields=SHOOTING_REQUEST_FIELDS,
        validator=_validate_shooting_request,
    )
)


@dataclass(frozen=True)
class ShootingExecutionRequest:
    platform: str
    content_type: str
    track: str
    topic: str
    shooting_goal: str
    locations: list[str]
    people: list[str]
    time_window: str = ""
    publish_time: str = ""
    project: str = ""
    account: str = ""
    reference_links: list[str] | None = None
    must_shoot: list[str] | None = None
    constraints: list[str] | None = None
    keywords: list[str] | None = None
    source_asset_id: str = ""
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("reference_links", "must_shoot", "constraints", "keywords"):
            payload[key] = list(payload.get(key) or [])
        return payload

    def to_creation_request(self) -> CreationRequest:
        return CreationRequest(
            platform=self.platform,
            content_type=self.content_type,
            track=self.track,
            topic=self.topic,
            publish_time=self.publish_time,
            user_idea=self.shooting_goal,
            keywords=list(self.keywords or []),
            project=self.project,
            account=self.account,
            source_asset_id=self.source_asset_id,
            raw_text=self.raw_text,
        )


def handle_shooting_execution_command(
    raw_text: str,
    *,
    tenant_id: str,
    dry_run: bool = False,
    no_write: bool = False,
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id)
    request = parse_shooting_execution_request(raw_text)
    creation_request = request.to_creation_request()
    media_context = merge_conversation_context(build_media_context_for_request(creation_request, tenant_id=tenant_id), conversation_context)
    deconstruction_evidence = _resolve_deconstruction_evidence(request, tenant_id=tenant_id)
    media_context = dict(media_context)
    media_context["deconstruction_evidence"] = deconstruction_evidence
    draft = generate_shooting_execution_plan(request, media_context=media_context)
    validation = validate_shooting_execution_plan(draft)
    doc_link = ""
    media_model_v2_result: dict[str, Any] = {}
    if not dry_run and not no_write and not validation.get("schedule_conflicts"):
        doc_link = create_shooting_execution_doc(request, draft, validation, media_context=media_context)
        media_model_v2_result = write_creation_model_v2(
            tenant_id=tenant_id,
            request=creation_request,
            entrypoint="【创作-拍摄执行】",
            all_activity_candidates=[],
            all_viral_candidates=[],
            all_inspiration_candidates=[],
            all_business_candidates=[],
            selected_activities=[],
            selected_virals=[],
            selected_inspirations=[],
            selected_businesses=[],
            doc_link=doc_link,
            creation_record_id="",
            draft=draft,
            validation=validation,
            media_context=media_context,
            platform_fit={"platform_mechanism_version": "shooting_execution_v1"},
        )
    return {
        "ok": bool(validation.get("ok")),
        "mode": "dry_run" if dry_run or no_write else "write",
        "generation_mode": "openclaw_llm_first",
        "request": request.to_dict(),
        "draft": draft,
        "validation": validation,
        "doc_link": doc_link,
        "creation_record_id": str(media_model_v2_result.get("run_id") or ""),
        "media_model_v2": media_model_v2_result,
        "deconstruction_evidence": deconstruction_evidence,
        "reply": format_shooting_execution_reply(request, doc_link, validation, media_model_v2_result, dry_run=dry_run or no_write),
    }


def _resolve_deconstruction_evidence(request: ShootingExecutionRequest, *, tenant_id: str) -> dict[str, Any]:
    reference_urls = {
        normalize_source_url(value)
        for value in (request.reference_links or [])
        if normalize_source_url(value)
    }
    if not reference_urls:
        return {"status": "manual_description_only", "reason": "no_reference_links", "items": []}
    try:
        rows = load_material_candidate_rows_for_creation(tenant_id=tenant_id)
    except Exception:
        return {"status": "manual_description_only", "reason": "candidate_lookup_unavailable", "items": []}

    adapter = ViralContentAdapter()
    items: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    for row in rows:
        try:
            record = adapter.to_record(row)
        except Exception:
            unavailable.append({"source_link": "", "reason": "candidate_record_invalid"})
            continue
        source_url = normalize_source_url(record.source_link)
        if not source_url or source_url not in reference_urls:
            continue
        try:
            enriched = attach_deconstruction_artifact_brief(record, tenant_id=tenant_id)
        except DeconstructionArtifactUnavailable as exc:
            unavailable.append({"source_link": source_url, "reason": str(exc)})
            continue
        except Exception:
            unavailable.append({"source_link": source_url, "reason": "artifact_lookup_unavailable"})
            continue
        detail = enriched.detail_json or {}
        items.append(
            {
                "source_link": source_url,
                "source_status": "confirmed",
                "reference_shots": detail.get("reference_shots") or [],
                "pacing_notes": detail.get("pacing_notes") or {},
                "reuse_guardrails": detail.get("reuse_guardrails") or {},
            }
        )
    if items:
        return {"status": "confirmed", "items": items, "unavailable": unavailable}
    return {
        "status": "manual_description_only",
        "reason": "no_valid_deconstruction_artifact",
        "items": [],
        "unavailable": unavailable,
    }


def parse_shooting_execution_request(raw_text: str, *, infer_missing: bool = True) -> ShootingExecutionRequest:
    text = str(raw_text or "").strip()
    match = SHOOTING_PATTERN.match(text)
    if not match:
        raise ValueError("不是【创作-拍摄执行】入口")
    body = text[match.end():].strip()
    values = _parse_key_values(body)
    inferred = infer_shooting_execution_request(text, values) if infer_missing else {}
    platform = normalize_platform(values.get("平台") or inferred.get("platform") or "")
    content_type = normalize_content_type(values.get("内容类型") or values.get("类型") or inferred.get("content_type") or "")
    track = _clean(values.get("赛道") or inferred.get("track") or "", 80)
    topic = _clean(values.get("主体") or values.get("主题") or inferred.get("topic") or "", 120)
    shooting_goal = _clean(values.get("拍摄目标") or values.get("目标") or inferred.get("shooting_goal") or "", 1000)
    locations = _list(values.get("场地") or values.get("地点") or inferred.get("locations") or "")
    people = _list(values.get("人物") or inferred.get("people") or "")
    if not platform:
        raise ValueError("【创作-拍摄执行】缺少平台")
    if platform not in {"小红书", "抖音", "B站"}:
        raise ValueError("【创作-拍摄执行】平台只支持 小红书、抖音 或 B站")
    if not content_type:
        content_type = "视频"
    if content_type not in {"图文", "视频"}:
        raise ValueError("【创作-拍摄执行】内容类型只支持 图文 或 视频")
    missing = []
    if not topic:
        missing.append("主体/主题")
    if not shooting_goal:
        missing.append("拍摄目标")
    if not locations:
        missing.append("场地/地点")
    if not people:
        missing.append("人物")
    if missing:
        raise ValueError("【创作-拍摄执行】缺少：" + "、".join(missing))
    keywords = split_tags(values.get("关键词") or values.get("标签") or " ".join([track, topic, shooting_goal]))
    source_asset_id = extract_source_asset_id(
        raw_text,
        values.get("source_asset_id")
        or values.get("SourceAsset来源ID")
        or values.get("素材源ID")
        or values.get("source")
        or values.get("来源")
        or inferred.get("source_asset_id", ""),
    )
    return ShootingExecutionRequest(
        platform=platform,
        content_type=content_type,
        track=track or "未提供",
        topic=topic,
        shooting_goal=shooting_goal,
        locations=locations,
        people=people,
        time_window=_clean(values.get("时间窗口") or values.get("总时长") or inferred.get("time_window") or "", 80),
        publish_time=_clean(values.get("发布时间") or inferred.get("publish_time") or "", 80),
        project=_clean(values.get("项目") or inferred.get("project") or "", 120),
        account=_clean(values.get("账号") or inferred.get("account") or "", 120),
        reference_links=_urls(text) or _list(values.get("参考链接") or inferred.get("reference_links") or ""),
        must_shoot=_list(values.get("必拍") or inferred.get("must_shoot") or ""),
        constraints=_list(values.get("约束") or inferred.get("constraints") or ""),
        keywords=keywords,
        source_asset_id=source_asset_id,
        raw_text=raw_text,
    )


def infer_shooting_execution_request(raw_text: str, explicit: dict[str, str]) -> dict[str, Any]:
    prompt = (
        "你是【创作-拍摄执行】请求解析器。只把用户原文抽取成字段，不写方案，不扩写创意。\n"
        "不能根据平台链接猜视频内容；链接只能原样放入 reference_links。\n"
        "不确定的字段留空字符串或空数组。\n\n"
        "输出合法 JSON object，字段固定为：platform, content_type, track, topic, shooting_goal, "
        "locations, people, time_window, publish_time, project, account, reference_links, must_shoot, constraints, source_asset_id。\n\n"
        f"显式字段：\n{json.dumps(explicit, ensure_ascii=False, indent=2)}\n\n"
        f"用户原文：\n{raw_text}"
    )
    payload = call_creation_json(prompt, validation_contract=SHOOTING_REQUEST_VALIDATION_CONTRACT)
    return payload if isinstance(payload, dict) else {}


def generate_shooting_execution_plan(request: ShootingExecutionRequest, *, media_context: dict[str, Any] | None = None) -> dict[str, Any]:
    deconstruction_evidence = (media_context or {}).get("deconstruction_evidence") or {}
    creator_facing_evidence = creator_facing_deconstruction_evidence(deconstruction_evidence)
    creator_facing_context = dict(media_context or {})
    creator_facing_context.pop("deconstruction_evidence", None)
    prompt = (
        "你是 OpenClaw Media bot 的拍摄执行导演。请把用户的【创作-拍摄执行】请求生成现场可执行拍摄单。\n"
        "硬性规则：\n"
        "1. 只能基于用户原文、显式字段、账号上下文和已提供证据写方案；参考链接无法解析时，在证据附录的来源状态中写“仅凭文字描述，未看过原片”，不要假装看过。\n"
        "2. 输出必须是合法 JSON object，不要 Markdown，不要解释。\n"
        "3. 必须先把用户内容抽象化拆解成任务层，再落到路线、镜头、分支方案和现场检查清单；不要把原文直接压成速拍脚本。\n"
        "4. 用户显式给出时间窗口时，路线图必须按该时间窗口组织；不得擅自缩短或改写为更短拍摄时长。\n"
        "5. 路线、镜头、分支方案、现场检查清单必须能在现场直接执行。\n"
        "6. 证据附录放最后；裸链接不能打断执行稿。\n"
        "7. 发布后首小时动作只写需要创作者手动完成的具体动作；不得安排、声称或暗示系统会自动执行或定时提醒。\n\n"
        "8. 媒体上下文中的未来档期是已知占用：route_map 不得与其冲突；有冲突或无法判断时，"
        "把替代时段写入 branch_plans，并在 onsite_checklist 明示发布日期和发布后首小时的占用风险。\n\n"
        "拆解证据只能使用下方来源状态为“已核验”的内容；其余参考链接一律仅凭文字描述，未看过原片，"
        "不得根据链接补写镜头、节奏或原作细节。\n\n"
        "JSON schema：\n"
        "{\n"
        "  \"shooting_goal\": {\"platform\":\"\", \"content_type\":\"\", \"core_emotion\":\"\", \"mainline\":\"\", \"deliverable\":\"\"},\n"
        "  \"abstraction_map\": [{\"source_signal\":\"\", \"task_layer\":\"\", \"execution_meaning\":\"\"}],\n"
        "  \"route_map\": [{\"time_slot\":\"\", \"location\":\"\", \"shooting_task\":\"\", \"people\":\"\", \"backup\":\"\"}],\n"
        "  \"must_shot_list\": [{\"priority\":\"必拍|重要|可选\", \"location\":\"\", \"people\":\"\", \"action\":\"\", \"shot_size\":\"\", \"reference\":\"\", \"usage\":\"\", \"reshoot_check\":\"\"}],\n"
        "  \"branch_plans\": [{\"condition\":\"\", \"plan\":\"\", \"priority\":\"必拍|重要|可选\"}],\n"
        "  \"storyboard\": [{\"time\":\"\", \"visual\":\"\", \"caption_or_voice\":\"\", \"sound_or_note\":\"\"}],\n"
        "  \"onsite_checklist\": [\"\"],\n"
        "  \"publishing_pack\": {\"title_directions\":[\"\"], \"cover_frame\":\"\", \"body_copy\":\"\", \"hashtags\":[\"\"], \"bgm_suggestion\":\"\", \"comment_prompt\":\"\", \"first_hour_action\":\"\"},\n"
        "  \"evidence_appendix\": [{\"source\":\"\", \"source_status\":\"已核验|仅凭文字描述，未看过原片|待人工核实\", \"available_evidence\":\"\", \"usage_reason\":\"\", \"risk\":\"\"}]\n"
        "}\n\n"
        f"请求字段：\n{json.dumps(request.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"拆解证据：\n{_bounded_context_json(creator_facing_evidence)}\n\n"
        f"媒体上下文：\n{_bounded_context_json(creator_facing_context)}"
    )
    payload = call_creation_json(prompt, validation_contract=SHOOTING_PLAN_VALIDATION_CONTRACT)
    if not isinstance(payload, dict):
        raise RuntimeError("shooting_execution_llm_output_not_object")
    localized = localize_shooting_execution_plan_values(payload)
    return _apply_schedule_conflicts(localized, request=request, media_context=media_context or {})


def localize_shooting_execution_plan_values(draft: dict[str, Any]) -> dict[str, Any]:
    localized = dict(draft)
    if "must_shot_list" in draft:
        localized["must_shot_list"] = _localized_rows(
            draft.get("must_shot_list"), "priority", SHOOTING_PRIORITY_LABELS, unknown_label="待人工确认"
        )
    if "branch_plans" in draft:
        localized["branch_plans"] = _localized_rows(
            draft.get("branch_plans"), "priority", SHOOTING_PRIORITY_LABELS, unknown_label="待人工确认"
        )
    if "evidence_appendix" in draft:
        localized["evidence_appendix"] = _localized_rows(
            draft.get("evidence_appendix"), "source_status", EVIDENCE_SOURCE_STATUS_LABELS, unknown_label="待人工核实"
        )
    return localized


def creator_facing_deconstruction_evidence(value: Any) -> dict[str, Any]:
    evidence = value if isinstance(value, dict) else {}
    items: list[dict[str, Any]] = []
    for item in evidence.get("items") or []:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "参考链接": item.get("source_link") or "",
                "来源状态": _creator_facing_source_status(item.get("source_status")),
                "可参考镜头": item.get("reference_shots") or [],
                "节奏提示": item.get("pacing_notes") or {},
                "复用边界": item.get("reuse_guardrails") or {},
            }
        )
    return {
        "核验状态": _creator_facing_source_status(evidence.get("status")),
        "可用参考素材": items,
    }


def _localized_rows(rows: Any, field: str, labels: dict[str, str], *, unknown_label: str) -> Any:
    if not isinstance(rows, list):
        return rows
    localized: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            localized.append(row)
            continue
        display_row = dict(row)
        raw_value = str(row.get(field) or "").strip()
        display_row[field] = labels.get(raw_value, unknown_label)
        localized.append(display_row)
    return localized


def _creator_facing_source_status(value: Any) -> str:
    raw_status = str(value or "").strip()
    return EVIDENCE_SOURCE_STATUS_LABELS.get(raw_status, "待人工核实")


def _bounded_context_json(value: Any, *, max_chars: int = 12000) -> str:
    """Keep prompt context valid JSON while marking fields that exceed budget."""
    if not isinstance(value, dict):
        value = {"value": value}
    compact: dict[str, Any] = {}
    used = 2
    for key, item in value.items():
        encoded = json.dumps(item, ensure_ascii=False, default=str)
        if len(encoded) > 2400:
            encoded = encoded[:2380].rstrip() + "...[上下文字段已截断]"
            item = encoded
        candidate = json.dumps({key: item}, ensure_ascii=False, default=str)
        if used + len(candidate) > max_chars:
            compact["_truncated"] = "媒体上下文已按字段预算截断"
            break
        compact[key] = item
        used += len(candidate)
    return json.dumps(compact, ensure_ascii=False, indent=2, default=str)


def validate_shooting_execution_plan(draft: dict[str, Any]) -> dict[str, Any]:
    required_lists = ("route_map", "must_shot_list", "branch_plans", "storyboard", "onsite_checklist", "evidence_appendix")
    missing = [key for key in ("shooting_goal", "publishing_pack", *required_lists) if key not in draft]
    empty_lists = [key for key in required_lists if not isinstance(draft.get(key), list) or not draft.get(key)]
    if not isinstance(draft.get("shooting_goal"), dict) or not isinstance(draft.get("publishing_pack"), dict):
        return {"ok": False, "status": "pending_manual", "missing": [], "empty_lists": [], "reason": "invalid_object_sections", "fallback": "disabled"}
    if not str(draft["publishing_pack"].get("first_hour_action") or "").strip():
        missing.append("first_hour_action")
    schedule_conflicts = draft.get("schedule_conflicts")
    if schedule_conflicts:
        return {
            "ok": False,
            "status": "needs_review",
            "missing": missing,
            "empty_lists": empty_lists,
            "schedule_conflicts": schedule_conflicts,
            "reason": "generated shooting times overlap confirmed schedule windows",
            "fallback": "manual_review",
        }
    if missing or empty_lists:
        return {"ok": False, "status": "pending_manual", "missing": missing, "empty_lists": empty_lists, "fallback": "disabled"}
    return {"ok": True, "status": "passed", "missing": [], "empty_lists": [], "fallback": "disabled"}


def _apply_schedule_conflicts(
    draft: dict[str, Any],
    *,
    request: ShootingExecutionRequest,
    media_context: dict[str, Any],
) -> dict[str, Any]:
    known_windows = []
    for item in media_context.get("schedule") or []:
        if not isinstance(item, dict):
            continue
        start = _parse_iso_datetime(item.get("starts_at") or item.get("start_at"))
        end = _parse_iso_datetime(item.get("ends_at") or item.get("end_at")) or start
        if start is not None and end is not None:
            known_windows.append((start, end, str(item.get("title") or "已安排事项").strip() or "已安排事项"))
    if not known_windows:
        return draft

    conflicts: list[dict[str, str]] = []
    for index, row in enumerate(draft.get("route_map") or []):
        if not isinstance(row, dict):
            continue
        window = _parse_structured_time_window(row.get("time_slot"))
        if window is None:
            continue
        for start, end, title in known_windows:
            if _windows_overlap(window[0], window[1], start, end):
                conflicts.append(
                    {
                        "kind": "route_map",
                        "item": str(index),
                        "time_slot": str(row.get("time_slot") or ""),
                        "schedule_title": title,
                        "schedule_starts_at": start.isoformat(timespec="minutes"),
                        "schedule_ends_at": end.isoformat(timespec="minutes"),
                    }
                )
    publish_window = _parse_structured_time_window(request.publish_time)
    if publish_window is not None:
        for start, end, title in known_windows:
            if _windows_overlap(publish_window[0], publish_window[1], start, end):
                conflicts.append(
                    {
                        "kind": "publish_time",
                        "item": "request",
                        "time_slot": request.publish_time,
                        "schedule_title": title,
                        "schedule_starts_at": start.isoformat(timespec="minutes"),
                        "schedule_ends_at": end.isoformat(timespec="minutes"),
                    }
                )
    if not conflicts:
        return draft
    updated = dict(draft)
    updated["schedule_conflicts"] = conflicts
    updated["schedule_conflict_status"] = "needs_review"
    branch_plans = list(updated.get("branch_plans") or [])
    branch_plans.append(
        {
            "condition": "已生成时段与已确认档期冲突，需人工复核",
            "plan": "暂停冲突时段；由创作者确认替代拍摄/发布时间后再执行。",
            "priority": "必拍",
        }
    )
    updated["branch_plans"] = branch_plans
    checklist = list(updated.get("onsite_checklist") or [])
    checklist.append("需人工复核：路线图或发布时间与已确认档期冲突，确认替代时段后再拍摄/发布。")
    updated["onsite_checklist"] = checklist
    return updated


def _parse_structured_time_window(value: Any) -> tuple[datetime, datetime] | None:
    text = str(value or "").strip()
    if not text:
        return None
    date_match = re.search(
        r"(?P<year>20\d{2})(?:[-/.年])(?P<month>\d{1,2})(?:[-/.月])(?P<day>\d{1,2})(?:日|号)?",
        text,
    )
    if not date_match:
        return None
    time_matches = re.findall(r"(?<!\d)(\d{1,2})(?::|点|时)(\d{2})?", text)
    if not time_matches:
        return None
    try:
        day = datetime(
            int(date_match.group("year")),
            int(date_match.group("month")),
            int(date_match.group("day")),
            int(time_matches[0][0]),
            int(time_matches[0][1] or 0),
            tzinfo=LOCAL_TZ,
        )
        end = (
            datetime(
                day.year,
                day.month,
                day.day,
                int(time_matches[1][0]),
                int(time_matches[1][1] or 0),
                tzinfo=LOCAL_TZ,
            )
            if len(time_matches) > 1
            else day + timedelta(hours=1)
        )
    except ValueError:
        return None
    if end < day:
        end += timedelta(days=1)
    return day, end


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _windows_overlap(left_start: datetime, left_end: datetime, right_start: datetime, right_end: datetime) -> bool:
    return left_start < right_end and right_start < left_end


def _validate_shooting_plan(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    result = validate_shooting_execution_plan(payload)
    if not result.get("ok"):
        raise ValueError(f"shooting execution plan failed: {result}")
    return payload


SHOOTING_PLAN_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.creation.shooting_plan.v1",
        profile="strict_structured",
        validator=_validate_shooting_plan,
    )
)


def format_shooting_execution_reply(
    request: ShootingExecutionRequest,
    doc_link: str,
    validation: dict[str, Any],
    _media_model_v2_result: dict[str, Any],
    *,
    dry_run: bool,
) -> str:
    lines = [
        "拍摄执行草案已生成，尚未写入文档。" if dry_run else "拍摄执行单已生成。",
        *( [f"拍摄执行文档：{doc_link}"] if doc_link else [] ),
        f"平台：{request.platform}",
        f"内容类型：{request.content_type}",
        f"主体：{request.topic}",
        f"校验：{'通过' if validation.get('ok') else '待人工补充'}",
    ]
    return "\n".join(lines)


def _parse_key_values(body: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in KEY_VALUE_RE.finditer(body):
        key = match.group("key").strip()
        value = match.group("value").strip()
        if value:
            values[key] = value
    return values


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        text = str(value or "").strip()
        items = re.split(r"[\n、,，；;]+", text)
    return [str(item).strip().strip("- ").strip() for item in items if str(item).strip().strip("- ").strip()]


def _urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s，。；;）)】]+", text or "")


def _clean(value: Any, limit: int) -> str:
    if isinstance(value, list):
        text = " ".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value or "").strip()
    return text[:limit]
