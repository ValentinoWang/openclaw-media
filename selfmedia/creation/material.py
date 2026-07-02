from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel, Field, root_validator, validator

from common.social_runtime import (
    FEISHU_BASE,
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
)
from selfmedia.creation.field_contract import normalize_content_type, normalize_platform, split_tags
from selfmedia.creation.llm_generator import CREATOR_BRIEF_REPORT_MODE
from selfmedia.creation.media_model_v2_writeback import write_creation_model_v2
from selfmedia.creation.platform_validator import validate_platform_draft
from selfmedia.creation.request_parser import CreationRequest, normalize_publish_time
from selfmedia.creation.writer import create_creation_doc
from selfmedia.context import build_media_context_for_request, merge_conversation_context, record_creation_memory


ROOT = Path(__file__).resolve().parents[2]
VIRAL_DECONSTRUCT_ROOT = ROOT / "selfmedia" / "deconstruct" / "viral_content"
OUTPUT_DIR = ROOT / "data" / "media_vault" / "material_creation_runs"
MATERIAL_PATTERN = re.compile(r"^\s*【素材创作(?:>(?P<platform>小红书|抖音))?】")
REQUEST_KEYS = "平台|赛道|类型|内容类型|主体|主题|发布时间|用户想法|想法|关键词|标签|账号|作者ID|博主|品牌|产品|项目|发布链接"
KEY_VALUE_RE = re.compile(rf"(?P<key>{REQUEST_KEYS})\s*[=:：]\s*(?P<value>.*?)(?=\s+(?:{REQUEST_KEYS})\s*[=:：]|$)")
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic"}

ACCOUNT_MONITOR_FIELD_SPECS = {
    "账号名称": 1,
    "平台": 1,
    "近期作品链接": 1,
    "启用": 7,
    "最近运行时间": 5,
    "最近状态": 1,
    "最近作品数": 2,
    "最近总互动": 2,
    "最近错误": 1,
    "最近日报摘要": 1,
}


@dataclass(frozen=True)
class MaterialRequest:
    platform: str
    content_type: str
    track: str
    topic: str
    publish_time: str
    user_idea: str = ""
    keywords: list[str] | None = None
    account: str = ""
    brand: str = ""
    product: str = ""
    project: str = ""
    publish_url: str = ""
    raw_text: str = ""

    def to_creation_request(self, analysis: dict[str, Any]) -> CreationRequest:
        track = self.track or str(analysis.get("track") or "未定赛道")
        topic = self.topic or str(analysis.get("topic") or analysis.get("material_summary") or "素材创作")
        keywords = self.keywords or split_tags(" ".join([track, topic, self.brand, self.product, self.project]))
        return CreationRequest(
            platform=self.platform,
            content_type=self.content_type,
            track=track,
            topic=topic,
            publish_time=self.publish_time,
            user_idea=self.user_idea,
            keywords=keywords,
            brand=self.brand,
            product=self.product,
            project=self.project,
            account=self.account,
            raw_text=self.raw_text,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["keywords"] = list(self.keywords or [])
        return payload


class MaterialCreationResult(BaseModel):
    track: str = ""
    topic: str = ""
    material_summary: str
    positioning: str
    target_audience: list[str] = Field(default_factory=list)
    pain_or_pleasure_points: list[str] = Field(default_factory=list)
    account_fit: str = ""
    content_angles: list[str] = Field(default_factory=list)
    title: str
    tags: list[str] = Field(default_factory=list)
    final_copy: str
    image_script: list[Any] = Field(default_factory=list)
    hook_3s: str = ""
    storyboard: list[dict[str, Any]] = Field(default_factory=list)
    voiceover: str = ""
    subtitles: list[str] = Field(default_factory=list)
    production_checklist: list[str] = Field(default_factory=list)
    review_plan: list[str] = Field(default_factory=list)
    report_mode: dict[str, Any]
    creator_report: dict[str, Any]

    @validator("material_summary", "positioning", "title", "final_copy", pre=True)
    @classmethod
    def required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("素材创作结果缺少必填文本")
        return text

    @validator("target_audience", "pain_or_pleasure_points", "content_angles", "tags", "subtitles", "production_checklist", "review_plan", pre=True)
    @classmethod
    def normalize_list(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[\n,，、;；]+", value) if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    @root_validator
    def validate_script(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not values.get("image_script") and not values.get("storyboard"):
            raise ValueError("素材创作结果必须包含 image_script 或 storyboard")
        if values.get("report_mode") != CREATOR_BRIEF_REPORT_MODE:
            raise ValueError("素材创作结果 report_mode 必须为 creator_brief")
        required_report_sections = ("overview", "opening_3s", "mainline", "storyboard", "publishing_pack", "material_checklist", "risk_controls", "evidence_appendix")
        creator_report = values.get("creator_report") or {}
        missing = [key for key in required_report_sections if key not in creator_report]
        if missing:
            raise ValueError(f"素材创作结果 creator_report 缺少字段：{missing}")
        return values


def handle_material_creation_command(
    raw_text: str,
    *,
    attachment_paths: list[str] | None = None,
    dry_run: bool = False,
    no_write: bool = False,
    creation_record_url: str = "",
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attachments = [str(Path(path).expanduser()) for path in (attachment_paths or []) if str(path).strip()]
    request = parse_material_request(raw_text, attachments)
    media_context = merge_conversation_context(build_media_context_for_request(request), conversation_context)
    evidence = build_material_evidence(attachments)
    analysis = generate_material_analysis(request, evidence, media_context=media_context)
    creation_request = request.to_creation_request(analysis)
    if not media_context.get("account") and creation_request.account:
        media_context = merge_conversation_context(build_media_context_for_request(creation_request), conversation_context)
    draft = build_platform_draft(creation_request, request, analysis, evidence, media_context=media_context)
    validation_result = validate_platform_draft(creation_request.platform, creation_request.content_type, draft)
    if not validation_result.ok:
        messages = "；".join(issue.message for issue in validation_result.issues)
        raise RuntimeError(f"素材创作 LLM 输出未通过平台校验：{messages}")
    validation = {
        **validation_result.to_dict(),
        "title_ok": not any(issue.field == "title" for issue in validation_result.issues),
        "tags_ok": not any(issue.field == "tags" for issue in validation_result.issues),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
    local_json = OUTPUT_DIR / f"{stamp}-material-creation.json"
    local_md = OUTPUT_DIR / f"{stamp}-material-creation.md"

    doc_link = ""
    creation_record_id = ""
    account_record = {}
    memory_result: dict[str, Any] = {}
    media_model_v2_result: dict[str, Any] = {}
    extra_details = {
        "account": creation_request.account,
        "material_source": "\n".join(evidence.get("source_paths") or attachments),
        "positioning_analysis": analysis,
        "media_context": media_context,
        "publish_url": request.publish_url,
        "review_status": "待发布" if not request.publish_url else "待回收数据",
        "local_json": str(local_json),
        "local_report": str(local_md),
    }
    if not dry_run and not no_write:
        doc_link = create_creation_doc(creation_request, [], [], draft, validation, businesses=[])
        media_model_v2_result = write_creation_model_v2(
            request=creation_request,
            entrypoint="【素材创作】",
            all_activity_candidates=[],
            all_viral_candidates=[],
            all_inspiration_candidates=[],
            all_business_candidates=[],
            selected_activities=[],
            selected_virals=[],
            selected_inspirations=[],
            selected_businesses=[],
            doc_link=doc_link,
            creation_record_id=creation_record_id,
            draft=draft,
            validation=validation,
            media_context=media_context,
            platform_fit={},
        )
        creation_record_id = str(media_model_v2_result.get("run_id") or "")
        memory_result = record_creation_memory(
            creation_request,
            draft=draft,
            analysis=analysis,
            context=media_context,
            doc_link=doc_link,
            creation_record_id=creation_record_id,
            source_paths=evidence.get("source_paths") or attachments,
            validation=validation,
        )

    payload = {
        "ok": validation_result.ok,
        "mode": "dry_run" if dry_run or no_write else "write",
        "request": request.to_dict(),
        "creation_request": creation_request.to_dict(),
        "evidence": evidence,
        "analysis": analysis,
        "media_context": media_context,
        "draft": draft,
        "validation": validation,
        "doc_link": doc_link,
        "creation_record_id": creation_record_id,
        "account_record": account_record,
        "memory": memory_result,
        "media_model_v2": media_model_v2_result,
        "local_json": str(local_json),
        "local_report": str(local_md),
    }
    payload["reply"] = format_material_reply(payload)
    local_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    local_md.write_text(render_material_report(payload), encoding="utf-8")
    return payload


def smoke_material_creation_command(
    raw_text: str,
    *,
    attachment_paths: list[str] | None = None,
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attachments = [str(Path(path).expanduser()) for path in (attachment_paths or []) if str(path).strip()]
    request = parse_material_request(raw_text, attachments)
    media_context = merge_conversation_context(build_media_context_for_request(request), conversation_context)
    evidence = build_material_evidence(attachments)
    loaded = media_context.get("loaded") if isinstance(media_context.get("loaded"), dict) else {}
    return {
        "ok": True,
        "mode": "smoke",
        "module": "selfmedia.creation.material",
        "request": request.to_dict(),
        "evidence": {
            "source_path_count": len(evidence.get("source_paths") or []),
            "text_excerpt_present": bool(evidence.get("text_excerpt")),
        },
        "media_context_loaded": {
            "account_profile": bool(loaded.get("account_profile")),
            "creator_profile": bool(loaded.get("creator_profile")),
            "recent_creations": int(loaded.get("recent_creations") or 0),
            "recent_reviews": int(loaded.get("recent_reviews") or 0),
        },
        "write_policy": "no_feishu_write_no_llm_generation",
    }


def parse_material_request(raw_text: str, attachment_paths: list[str] | None = None) -> MaterialRequest:
    text = raw_text.strip()
    match = MATERIAL_PATTERN.match(text)
    if not match:
        raise ValueError("不是【素材创作】入口")
    body = text[match.end():].strip()
    values = _parse_key_values(body)
    platform = normalize_platform(values.get("平台") or match.group("platform") or "")
    raw_content_type = values.get("内容类型") or values.get("类型") or ""
    content_type = normalize_content_type(raw_content_type)
    inferred_type = infer_content_type(attachment_paths or [])
    if not content_type:
        content_type = inferred_type or ("图文" if platform == "小红书" else "视频")
    if not platform:
        platform = "抖音" if content_type == "视频" else "小红书"
    if content_type not in {"图文", "视频"}:
        raise ValueError("【素材创作】内容类型只支持 图文 或 视频")
    tz = ZoneInfo("Asia/Shanghai")
    publish_time = normalize_publish_time(values.get("发布时间") or "", datetime.now(tz), tz)
    track = (values.get("赛道") or "").strip()
    topic = (values.get("主体") or values.get("主题") or "").strip()
    account = (values.get("账号") or values.get("作者ID") or values.get("博主") or "").strip()
    brand = (values.get("品牌") or "").strip()
    product = (values.get("产品") or "").strip()
    project = (values.get("项目") or "").strip()
    keywords = split_tags(values.get("关键词") or values.get("标签") or " ".join([track, topic, brand, product, project, account]))
    return MaterialRequest(
        platform=platform,
        content_type=content_type,
        track=track,
        topic=topic,
        publish_time=publish_time,
        user_idea=(values.get("用户想法") or values.get("想法") or "").strip(),
        keywords=keywords,
        account=account,
        brand=brand,
        product=product,
        project=project,
        publish_url=(values.get("发布链接") or "").strip(),
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


def infer_content_type(paths: list[str]) -> str:
    has_video = any(Path(path).suffix.lower() in VIDEO_EXTS for path in paths)
    has_image = any(Path(path).suffix.lower() in IMAGE_EXTS for path in paths)
    if has_video:
        return "视频"
    if has_image:
        return "图文"
    return ""


def build_material_evidence(paths: list[str]) -> dict[str, Any]:
    existing = [Path(path).expanduser() for path in paths if Path(path).expanduser().exists()]
    if not existing:
        return {"source_paths": [], "media_type": "text", "parts": [], "evidence_assets": [], "work_dir": ""}
    videos = [str(path) for path in existing if path.suffix.lower() in VIDEO_EXTS]
    images = [str(path) for path in existing if path.suffix.lower() in IMAGE_EXTS or (mimetypes.guess_type(path.name)[0] or "").startswith("image/")]
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
    work_dir = OUTPUT_DIR / "assets" / stamp
    work_dir.mkdir(parents=True, exist_ok=True)
    if videos:
        video_path = videos[0]
        media = build_deconstruct_media_evidence(video_path, [], str(work_dir), max_frames=8)
    elif images:
        media = build_deconstruct_media_evidence(None, images, str(work_dir), max_frames=8)
    else:
        return {"source_paths": [str(path) for path in existing], "media_type": "file", "parts": [], "evidence_assets": [], "work_dir": str(work_dir)}
    return {
        "source_paths": [str(path) for path in existing],
        "media_type": media.media_type,
        "parts": media.parts,
        "evidence_paths": media.evidence_paths,
        "evidence_assets": media.evidence_assets,
        "audio_path": media.audio_path,
        "preview_path": media.preview_path,
        "work_dir": str(work_dir),
    }


def generate_material_analysis(request: MaterialRequest, evidence: dict[str, Any], *, media_context: dict[str, Any] | None = None) -> dict[str, Any]:
    prompt = {
        "text": (
            "你是自媒体内容定位和初稿生成专家。用户给你上传视频/图文素材或文本想法。"
            "请先做定位分析，再给平台化初稿。只输出严格 JSON object，不要 Markdown。\n"
            "必须包含字段：track, topic, material_summary, positioning, target_audience, "
            "pain_or_pleasure_points, account_fit, content_angles, title, tags, final_copy, "
            "image_script, hook_3s, storyboard, voiceover, subtitles, production_checklist, review_plan, report_mode, creator_report。\n"
            "规则：\n"
            "1. positioning 要说明素材适合走什么内容定位，以及为什么。\n"
            "2. account_fit 要说明和账号是否适配；账号未知时写需要补充账号人设。\n"
            "3. 图文必须给 image_script；视频必须给 hook_3s、storyboard、voiceover、subtitles，缺字段会失败，不会由 Python 模板补写。\n"
            "4. review_plan 必须给发布后 2小时、24小时、7天要回收的数据和复盘问题。\n"
            "5. 不要编造公开互动数据；只能基于上传素材和用户输入判断。\n"
            "6. 必须读取并继承下面的媒体长期上下文；如果上下文为空，要明确指出账号画像缺失。\n"
            "7. 视频素材必须优先分析 evidence_assets 中 kind=first5s_frame 的前 5 秒 10fps 高密度采样，判断开头留存钩子；5 秒后按 kind=keyframe 的 fps=2 证据分析主体内容。\n"
            "8. 图文素材必须优先分析 kind=cover_image 的首图/封面，再分析后续 source_image。\n"
            "9. report_mode 必须等于输入的 creator_brief 协议对象；creator_report 必须使用固定结构："
            "{overview, opening_3s, mainline, storyboard, publishing_pack, material_checklist, risk_controls, evidence_appendix}。"
            "创作者执行版不得输出原始 JSON、record_id、评分细节、数据库字段、长链接。\n"
            f"report_mode 输入：{json.dumps(CREATOR_BRIEF_REPORT_MODE, ensure_ascii=False)}\n"
            f"{(media_context or {}).get('prompt', '')}\n"
            f"用户结构化输入：{json.dumps(request.to_dict(), ensure_ascii=False)}"
        )
    }
    parts = [prompt]
    if evidence.get("parts"):
        parts.append({
            "text": "以下是从用户上传素材得到的视觉证据。请基于证据做定位分析和初稿，特别注意 first5s_frame 与 cover_image 的优先级。",
        })
        parts.extend(evidence["parts"])
    else:
        parts.append({"text": "当前没有可用附件视觉证据，请只基于用户文本做定位分析，并在 account_fit 中提示素材证据不足。"})
    config = load_viral_deconstruct_config()
    raw = generate_viral_deconstruct_json(parts, config, schema=MaterialCreationResult)
    return normalize_analysis(raw, request)


def normalize_analysis(raw: dict[str, Any], request: MaterialRequest) -> dict[str, Any]:
    analysis = dict(raw)
    analysis["track"] = str(analysis.get("track") or request.track or "未定赛道").strip()
    analysis["topic"] = str(analysis.get("topic") or request.topic or analysis.get("material_summary") or "素材创作").strip()
    analysis["tags"] = fit_tags(analysis.get("tags"), 10 if request.platform == "小红书" else 5, [request.platform, analysis["track"], analysis["topic"], "内容创作", "复盘"])
    if request.content_type == "图文" and not analysis.get("image_script"):
        raise ValueError("素材创作 LLM 输出缺少 image_script；不使用 Python 模板补写")
    if request.content_type == "视频":
        missing_video_fields = [
            field
            for field in ("hook_3s", "storyboard", "voiceover", "subtitles")
            if not analysis.get(field)
        ]
        if missing_video_fields:
            raise ValueError(f"素材创作 LLM 输出缺少视频脚本字段：{', '.join(missing_video_fields)}；不使用 Python 模板补写")
    return analysis


def build_platform_draft(
    creation_request: CreationRequest,
    material_request: MaterialRequest,
    analysis: dict[str, Any],
    evidence: dict[str, Any],
    *,
    media_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft: dict[str, Any] = {
        "platform": creation_request.platform,
        "content_type": creation_request.content_type,
        "title": str(analysis.get("title") or creation_request.topic)[:20] if creation_request.platform == "小红书" else str(analysis.get("title") or creation_request.topic),
        "tags": fit_tags(analysis.get("tags"), 10 if creation_request.platform == "小红书" else 5, [creation_request.platform, creation_request.track, creation_request.topic, "内容创作", "复盘"]),
        "topic": creation_request.topic,
        "material_source": evidence.get("source_paths") or [],
        "positioning_analysis": {
            "material_summary": analysis.get("material_summary", ""),
            "positioning": analysis.get("positioning", ""),
            "target_audience": analysis.get("target_audience") or [],
            "pain_or_pleasure_points": analysis.get("pain_or_pleasure_points") or [],
            "account_fit": analysis.get("account_fit", ""),
            "content_angles": analysis.get("content_angles") or [],
        },
        "account_profile": {
            "account": creation_request.account,
            "review_status": "待发布" if not material_request.publish_url else "待回收数据",
            "publish_url": material_request.publish_url,
            "context_loaded": (media_context or {}).get("loaded") or {},
            "positioning_summary": ((media_context or {}).get("account_profile") or {}).get("positioning_summary", ""),
            "recent_lessons": ((media_context or {}).get("account_profile") or {}).get("recent_lessons", []),
            "proven_patterns": ((media_context or {}).get("account_profile") or {}).get("proven_patterns", []),
            "avoid_patterns": ((media_context or {}).get("account_profile") or {}).get("avoid_patterns", []),
        },
        "final_copy": analysis.get("final_copy", ""),
        "production_checklist": analysis.get("production_checklist") or [],
        "review_plan": analysis.get("review_plan") or [],
        "report_mode": analysis["report_mode"],
        "creator_report": analysis["creator_report"],
    }
    if creation_request.content_type == "图文":
        draft["image_script"] = analysis.get("image_script") or []
        draft["carousel"] = draft["image_script"]
    else:
        draft["hook_3s"] = str(analysis.get("hook_3s") or "").strip()
        draft["storyboard"] = analysis.get("storyboard") or []
        draft["voiceover"] = str(analysis.get("voiceover") or "").strip()
        draft["subtitles"] = analysis.get("subtitles") or []
    return draft


def fit_tags(value: Any, expected: int, defaults: list[str]) -> list[str]:
    tags = [str(item).strip().lstrip("#") for item in (value if isinstance(value, list) else split_tags(str(value or ""))) if str(item).strip()]
    for item in defaults:
        clean = str(item).strip().lstrip("#")
        if clean and clean not in tags:
            tags.append(clean)
    result: list[str] = []
    for item in tags:
        if item not in result:
            result.append(item)
        if len(result) >= expected:
            break
    filler = ["真实记录", "干货", "方法", "成长", "行动清单", "避坑", "日常", "经验分享", "选题", "账号复盘"]
    for item in filler:
        if len(result) >= expected:
            break
        if item not in result:
            result.append(item)
    return result[:expected]


def update_account_record(bitable_url: str, record_id: str, fields: dict[str, Any], *, token: str) -> None:
    app_token, table_id, token = feishu_bitable_refs(bitable_url, token)
    field_types = feishu_field_types(app_token, table_id, token)
    payload_fields = coerce_fields(fields, field_types)
    if not payload_fields:
        return
    resp = requests.put(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        json={"fields": payload_fields},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"更新账号监控记录失败：{payload}")


def create_bitable_record(app_token: str, table_id: str, token: str, fields: dict[str, Any], specs: dict[str, int]) -> str:
    feishu_ensure_fields(app_token, table_id, token, specs)
    field_types = feishu_field_types(app_token, table_id, token)
    payload_fields = coerce_fields(fields, field_types)
    resp = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        headers=feishu_headers(token),
        json={"fields": payload_fields},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"创建账号监控记录失败：{payload}")
    return str(payload.get("data", {}).get("record", {}).get("record_id") or "")


def coerce_fields(fields: dict[str, Any], field_types: dict[str, Any]) -> dict[str, Any]:
    payload_fields: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in field_types or value in (None, "", []):
            continue
        field_type = field_types.get(key)
        coerced = bool(value) if field_type == 7 else feishu_coerce_value(value, field_type)
        if coerced in (None, "", []):
            continue
        payload_fields[key] = coerced
    return payload_fields


def format_material_reply(payload: dict[str, Any]) -> str:
    request = payload.get("creation_request") or {}
    analysis = payload.get("analysis") or {}
    loaded = ((payload.get("media_context") or {}).get("loaded") or {})
    lines = [
        "【素材创作】已完成" if payload.get("mode") == "write" else "【素材创作】dry-run 已完成",
        f"平台：{request.get('platform', '')}",
        f"内容类型：{request.get('content_type', '')}",
        f"赛道：{request.get('track', '')}",
        f"主体：{request.get('topic', '')}",
        f"定位：{analysis.get('positioning', '')[:120]}",
        f"上下文：账号画像 {'有' if loaded.get('account_profile') else '无'}，历史创作 {loaded.get('recent_creations', 0)} 条，历史复盘 {loaded.get('recent_reviews', 0)} 条，对话 {loaded.get('conversation_context', 0)} 条",
        f"平台规则校验：{'通过' if (payload.get('validation') or {}).get('ok') else '未通过'}",
    ]
    if payload.get("doc_link"):
        lines.append(f"创作文档：{payload['doc_link']}")
    if payload.get("creation_record_id"):
        lines.append(f"作品档案：{payload['creation_record_id']}")
    account_record = payload.get("account_record") or {}
    if account_record.get("record_id"):
        lines.append(f"账号监控记录：{account_record['record_id']}")
    elif account_record.get("reason"):
        lines.append(f"账号监控：{account_record['reason']}")
    memory = payload.get("memory") or {}
    if memory.get("profile", {}).get("path"):
        lines.append(f"账号画像：{memory['profile']['path']}")
    return "\n".join(lines)


def render_material_report(payload: dict[str, Any]) -> str:
    analysis = payload.get("analysis") or {}
    draft = payload.get("draft") or {}
    media_context = payload.get("media_context") or {}
    lines = [
        "# 素材创作报告",
        "",
        "## 已加载上下文",
        "",
        media_context.get("prompt") or "暂无账号历史上下文",
        "",
        "## 定位分析",
        "",
        str(analysis.get("positioning") or ""),
        "",
        "## 目标受众",
        "",
        "\n".join(f"- {item}" for item in analysis.get("target_audience") or []) or "- 暂无",
        "",
        "## 初稿",
        "",
        str(draft.get("final_copy") or ""),
        "",
        "## 复盘计划",
        "",
        "\n".join(f"- {item}" for item in analysis.get("review_plan") or []) or "- 发布后补充 2小时/24小时/7天数据",
        "",
    ]
    return "\n".join(lines)


def load_viral_deconstruct_config() -> Any:
    from selfmedia.deconstruct.viral_content.src.config import load_config  # type: ignore

    return load_config()


def generate_viral_deconstruct_json(parts: list[dict[str, Any]], config: Any, schema: type[BaseModel]) -> dict[str, Any]:
    from selfmedia.deconstruct.viral_content.src.llm_client import generate_json  # type: ignore

    return generate_json(parts, config, schema=schema)


def build_deconstruct_media_evidence(video_path: str | None, image_paths: list[str] | None, work_dir: str, max_frames: int = 8) -> Any:
    from selfmedia.deconstruct.viral_content.src.media_parts import (  # type: ignore
        MediaEvidence,
        _asset_id,
        _copy_asset,
        _image_part,
        detect_media_type,
        ensure_real_file,
        ensure_real_files,
        extract_audio,
        extract_first_frame,
        extract_video_frames,
    )

    media_type = detect_media_type(video_path, image_paths)
    parts: list[dict[str, Any]] = []
    evidence_paths: list[str] = []
    evidence_assets: list[dict[str, str]] = []
    cleanup_paths: list[str] = []
    audio_path = ""
    preview_path = ""

    if media_type == "video":
        checked_video = ensure_real_file(video_path, "原视频")
        frames = [ensure_real_file(frame, "视频关键帧") for frame in extract_video_frames(checked_video, str(Path(work_dir) / "frames"), max_frames=max_frames)]
        if not frames:
            raise RuntimeError(f"视频已下载但抽帧失败，不能进行素材分析：{checked_video}")
        cleanup_paths.extend(frames)
        asset_dir = str(Path(work_dir) / "doc_assets")
        for index, frame in enumerate(frames, 1):
            asset_id = _asset_id("frame", index)
            asset_path = _copy_asset(frame, asset_dir, asset_id)
            evidence_paths.append(asset_path)
            evidence_assets.append({"asset_id": asset_id, "path": asset_path, "kind": "storyboard_frame", "role": "visual"})
            parts.append({"text": f"视觉证据 asset_id={asset_id}；这是从已下载原视频抽取的分镜代表帧。后续脚本必须在 evidence_asset_id 引用这个 ID。"})
            parts.append(_image_part(asset_path))
        preview_path = extract_first_frame(checked_video, str(Path(work_dir) / "preview")) or evidence_assets[0]["path"]
        audio_path = extract_audio(checked_video, str(Path(work_dir) / "audio"))
    else:
        checked_images = ensure_real_files(image_paths, "原图")
        for index, image_path in enumerate(checked_images[:max_frames], 1):
            asset_id = _asset_id("image", index)
            kind = "cover_image" if index == 1 else "source_image"
            evidence_paths.append(image_path)
            evidence_assets.append({"asset_id": asset_id, "path": image_path, "kind": kind, "role": "visual"})
            parts.append({"text": f"视觉证据 asset_id={asset_id}；这是已下载图文原图。后续图文脚本必须在 evidence_asset_id 引用这个 ID。"})
            parts.append(_image_part(image_path))
        preview_path = checked_images[0] if checked_images else ""

    return MediaEvidence(
        media_type=media_type,
        parts=parts,
        evidence_paths=evidence_paths,
        evidence_assets=evidence_assets,
        cleanup_paths=cleanup_paths,
        audio_path=audio_path,
        preview_path=preview_path,
    )
