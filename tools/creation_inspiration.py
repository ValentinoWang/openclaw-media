from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel, Field, field_validator

from common.social_runtime import (
    FEISHU_BASE,
    feishu_bitable_refs,
    feishu_coerce_value,
    feishu_ensure_fields,
    feishu_field_types,
    feishu_headers,
    feishu_tenant_access_token,
    load_default_env_files,
)
from tools.material_creation.workflow import build_material_evidence, generate_part2_json, load_part2_config


DEFAULT_INSPIRATION_TABLE_URL = (
    "https://tcnwueberajc.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e"
    "?fromScene=spaceOverview&table=tbl3tNirtYn3eOUr&view=vewAaVJP2U"
)
SELFMEDIA_FIELD_GUIDE_URL = "https://tcnwueberajc.feishu.cn/wiki/OmDew1gmSiTQc8kv85rcZCvanib"
UNIFIED_CREATION_FIELD_SPECS: dict[str, int] = {
    "记录类型": 1,
    "标题": 1,
    "主题": 1,
    "内容": 1,
    "摘要": 1,
    "平台": 4,
    "内容类型": 4,
    "赛道": 4,
    "关键词标签": 1,
    "来源链接": 15,
    "文档链接JSON": 1,
    "主状态": 3,
    "入库时间": 5,
    "创建时间": 5,
    "更新时间": 5,
    "核心数据JSON": 1,
    "爆点分析JSON": 1,
    "校验结果JSON": 1,
    "复盘状态": 3,
    "发布链接": 15,
    "详情JSON": 1,
    "素材来源类型": 1,
    "素材信号类型": 1,
    "情绪触发": 1,
    "触发原话": 1,
    "事件场景": 1,
    "错位点": 1,
    "核心观点": 1,
    "可复用角度": 1,
    "素材状态": 1,
    "一鱼多吃方向": 1,
}


class CreationInspirationResult(BaseModel):
    title: str
    theme: str
    track: str = ""
    platform: str = ""
    content_type: str = ""
    cleaned_inspiration: str
    material_summary: str
    source_kind: str = ""
    signal_type: str = ""
    emotion_trigger: str = ""
    trigger_sentence: str = ""
    event_scene: str = ""
    misalignment: str = ""
    core_viewpoint: str = ""
    reader_problem: str = ""
    material_stage: str = ""
    recreation_direction: str
    content_angles: list[str] = Field(default_factory=list)
    reuse_angles: list[str] = Field(default_factory=list)
    derivative_topics: list[str] = Field(default_factory=list)
    publishable_formats: list[str] = Field(default_factory=list)
    hook_options: list[str] = Field(default_factory=list)
    title_options: list[str] = Field(default_factory=list)
    script_outline: list[str] = Field(default_factory=list)
    score: int
    score_reason: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("title", "theme", "cleaned_inspiration", "material_summary", "recreation_direction", "score_reason", mode="before")
    @classmethod
    def required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("创作灵感结果缺少必填文本")
        return text

    @field_validator("score", mode="before")
    @classmethod
    def normalize_score(cls, value: Any) -> int:
        try:
            score = int(float(value))
        except (TypeError, ValueError):
            score = 0
        return max(0, min(100, score))


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _first_url(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, (list, tuple, set)):
        value = "\n".join(str(item) for item in value)
    match = re.search(r"https?://[^\s\"'<>]+", str(value))
    return match.group(0).rstrip("，。；;、)") if match else ""


def _attachment_summary(paths: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        items.append(
            {
                "path": str(path),
                "filename": path.name,
                "suffix": path.suffix.lower(),
                "size_bytes": size,
            }
        )
    return items


def analyze_creation_inspiration(text: str, attachment_paths: list[str], *, conversation_context: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = build_material_evidence(attachment_paths)
    prompt = {
        "text": (
            "你是 Media bot 的【创作-灵感】整理器。用户会给照片、视频、截图或一段话。"
            "任务是把这些素材落成一个可复用的创作灵感任务卡，并做创作-再创方向和评分。只输出严格 JSON object，不要 Markdown。\n"
            "必须输出字段：title, theme, track, platform, content_type, cleaned_inspiration, material_summary, "
            "source_kind, signal_type, emotion_trigger, trigger_sentence, event_scene, misalignment, core_viewpoint, "
            "reader_problem, material_stage, recreation_direction, content_angles, reuse_angles, derivative_topics, "
            "publishable_formats, hook_options, title_options, script_outline, "
            "score, score_reason, strengths, risks, next_actions, tags。\n"
            "规则：\n"
            "1. 只能基于用户文本、附件视觉证据和最近对话上下文判断，不要编造看不到的事实。\n"
            "2. title 用 8-20 个汉字，适合表格主标题。\n"
            "3. cleaned_inspiration 要把用户原始表达整理成完整灵感，不是简单摘要。\n"
            "4. source_kind 从个人经历、对话、情绪波动、用户提问、重复卡点、外部案例、平台趋势、生活场景、视觉素材中选择或概括。\n"
            "5. signal_type 聚焦素材触发信号：不舒服、困惑、触动、重复、观察、成果、失败、问题。\n"
            "6. trigger_sentence 写触发原话或一句话锚点；event_scene 写发生场景；misalignment 写错位、冲突或反常识点。\n"
            "7. core_viewpoint 写这个素材最终能提炼出的观点；reader_problem 写它能帮读者解决的具体问题。\n"
            "8. material_stage 从原始信号、已复盘、已提炼观点、已生成选题、已成稿中选最接近的一项。\n"
            "9. reuse_angles 和 derivative_topics 要体现“一鱼多吃”：个人故事、方法论、清单、问答、复盘、反常识、口播、图文轮播等可拆方向。\n"
            "10. recreation_direction 要说明可以创作-再创成什么内容，以及应该保留素材的哪些核心价值。\n"
            "11. score 是 0-100 的创作潜力分，综合稀缺性、可表达性、平台适配、个人 IP 适配、素材可视化程度和发布阻力。\n"
            "12. 如果附件视觉证据不足，要在 risks 写清楚，不要假装已经看见照片内容。\n"
            "13. 最终内容形态要接近【创作-再创】任务卡：素材来源、原始内容、创作灵感、灵感评分、转化目标、可迁移点、创作-再创方向、建议产物、待补充信息、下一步。\n"
            f"14. 字段口径参考自媒体标准字段 SSOT：{SELFMEDIA_FIELD_GUIDE_URL}；外层字段保持稳定，细节放入详情 JSON。\n"
            f"用户输入：{text.strip() or '无文字，仅附件'}\n"
            f"最近对话上下文：{json.dumps(conversation_context or {}, ensure_ascii=False)}\n"
            f"附件清单：{json.dumps(_attachment_summary(attachment_paths), ensure_ascii=False)}"
        )
    }
    parts = [prompt]
    if evidence.get("parts"):
        parts.append({"text": "以下是用户上传素材的视觉证据，请基于证据判断内容主旨、创作-再创角度和评分。"})
        parts.extend(evidence["parts"])
    else:
        parts.append({"text": "当前没有可用视觉证据；如果用户上传了附件但无法读取，请在 risks 里说明素材证据不足。"})
    raw = generate_part2_json(parts, load_part2_config(), schema=CreationInspirationResult)
    result = CreationInspirationResult.model_validate(raw).model_dump()
    result["created_at"] = _now_iso()
    result["attachment_paths"] = [item["path"] for item in _attachment_summary(attachment_paths)]
    result["evidence"] = {
        "media_type": evidence.get("media_type") or "",
        "source_paths": evidence.get("source_paths") or [],
        "evidence_paths": evidence.get("evidence_paths") or [],
        "work_dir": evidence.get("work_dir") or "",
    }
    return result


def format_inspiration_text(raw_text: str, result: dict[str, Any]) -> str:
    def lines(name: str, value: Any) -> list[str]:
        if isinstance(value, list):
            return [f"- {item}" for item in value if str(item).strip()]
        text = str(value or "").strip()
        return [text] if text else []

    created_at = str(result.get("created_at") or _now_iso())
    title = str(result.get("title") or "未命名灵感").strip()
    attachments = result.get("attachment_paths") or []
    source = "\n".join(f"- {item}" for item in attachments) if attachments else "未提供附件，按文字灵感归档"
    transfer_points = []
    transfer_points.extend(result.get("strengths") or [])
    transfer_points.extend(result.get("content_angles") or [])
    transfer_points.extend(result.get("reuse_angles") or [])
    pending_items = result.get("risks") or []
    sections: list[tuple[str, Any]] = [
        ("素材来源", source),
        ("原始内容", raw_text.strip() or "无文字，仅附件"),
        ("创作灵感", result.get("cleaned_inspiration")),
        ("素材信号", "\n".join(item for item in (
            f"来源类型：{result.get('source_kind') or '待判断'}",
            f"信号类型：{result.get('signal_type') or '待判断'}",
            f"情绪触发：{result.get('emotion_trigger') or '待判断'}",
            f"触发原话：{result.get('trigger_sentence') or '待判断'}",
            f"事件场景：{result.get('event_scene') or '待判断'}",
            f"错位点：{result.get('misalignment') or '待判断'}",
        ) if item)),
        ("核心观点", result.get("core_viewpoint")),
        ("读者问题", result.get("reader_problem")),
        ("素材状态", result.get("material_stage")),
        ("灵感评分", f"{result.get('score')}/100：{result.get('score_reason') or ''}"),
        ("转化目标", "\n".join(item for item in (result.get("platform"), result.get("content_type"), result.get("theme")) if item) or "待明确"),
        ("可迁移点", transfer_points),
        ("一鱼多吃方向", result.get("derivative_topics") or result.get("reuse_angles")),
        ("创作-再创方向", result.get("recreation_direction")),
        ("建议产物", result.get("publishable_formats")),
        ("开头钩子", result.get("hook_options")),
        ("标题备选", result.get("title_options")),
        ("脚本/图文结构", result.get("script_outline")),
        ("待补充信息", pending_items),
        ("下一步", result.get("next_actions")),
        ("标签", "、".join(result.get("tags") or [])),
    ]
    output: list[str] = [
        f"创作灵感任务卡｜{created_at}｜{title}",
        "标签：创作-灵感",
        f"主题：{result.get('theme') or '待明确'}",
        f"赛道：{result.get('track') or '待明确'}",
        "",
    ]
    for section_title, value in sections:
        body = lines(section_title, value)
        if not body:
            continue
        output.append(f"## {section_title}")
        output.extend(body)
        output.append("")
    return "\n".join(output).strip()


def _candidate_fields(text: str, result: dict[str, Any]) -> dict[str, Any]:
    doc_link = result.get("doc_link") or result.get("document_url") or result.get("文档链接")
    detail_json = {
        "workflow": "creation_inspiration",
        "workflow_tag": "创作-灵感",
        "field_guide_url": SELFMEDIA_FIELD_GUIDE_URL,
        "attachment_paths": result.get("attachment_paths") or [],
        "target": "\n".join(item for item in (result.get("platform"), result.get("content_type"), result.get("theme")) if item),
        "next_actions": result.get("next_actions") or [],
        "source_kind": result.get("source_kind", ""),
        "signal_type": result.get("signal_type", ""),
        "emotion_trigger": result.get("emotion_trigger", ""),
        "trigger_sentence": result.get("trigger_sentence", ""),
        "event_scene": result.get("event_scene", ""),
        "misalignment": result.get("misalignment", ""),
        "core_viewpoint": result.get("core_viewpoint", ""),
        "reader_problem": result.get("reader_problem", ""),
        "material_stage": result.get("material_stage", ""),
        "reuse_angles": result.get("reuse_angles") or [],
        "derivative_topics": result.get("derivative_topics") or [],
        "result": result,
    }
    tags = "、".join(str(item).strip() for item in result.get("tags") or [] if str(item).strip())
    now = result.get("created_at") or _now_iso()
    return {
        "记录类型": "创作记录",
        "标题": result.get("title"),
        "主题": result.get("theme"),
        "内容": result.get("cleaned_inspiration"),
        "摘要": result.get("material_summary"),
        "平台": result.get("platform"),
        "内容类型": result.get("content_type") or "混合",
        "赛道": result.get("track"),
        "关键词标签": "、".join(item for item in ("创作-灵感", tags) if item),
        "来源链接": _first_url(result.get("attachment_paths") or []),
        "文档链接JSON": {"inspiration_doc": doc_link} if doc_link else "",
        "主状态": "已归档",
        "入库时间": now,
        "创建时间": now,
        "更新时间": now,
        "核心数据JSON": json.dumps({"score": result.get("score"), "score_reason": result.get("score_reason") or ""}, ensure_ascii=False),
        "爆点分析JSON": json.dumps(
            {
                "recreation_direction": result.get("recreation_direction", ""),
                "content_angles": result.get("content_angles") or [],
                "reuse_angles": result.get("reuse_angles") or [],
                "derivative_topics": result.get("derivative_topics") or [],
                "strengths": result.get("strengths") or [],
                "risks": result.get("risks") or [],
                "publishable_formats": result.get("publishable_formats") or [],
            },
            ensure_ascii=False,
        ),
        "详情JSON": json.dumps(detail_json, ensure_ascii=False),
        "素材来源类型": result.get("source_kind"),
        "素材信号类型": result.get("signal_type"),
        "情绪触发": result.get("emotion_trigger"),
        "触发原话": result.get("trigger_sentence"),
        "事件场景": result.get("event_scene"),
        "错位点": result.get("misalignment"),
        "核心观点": result.get("core_viewpoint"),
        "可复用角度": "、".join(result.get("reuse_angles") or result.get("content_angles") or []),
        "素材状态": result.get("material_stage"),
        "一鱼多吃方向": "、".join(result.get("derivative_topics") or []),
    }


def write_inspiration_record(table_url: str, text: str, result: dict[str, Any]) -> dict[str, Any]:
    doc_link = str(result.get("doc_link") or result.get("document_url") or result.get("文档链接") or "").strip()
    if "UkSMwA36fiZuBdkk63ncnm84n0e" in table_url and "tbl3tNirtYn3eOUr" in table_url and not doc_link:
        raise RuntimeError("写入创作任务总表前必须先创建归档文档并提供文档链接")
    token = feishu_tenant_access_token()
    app_token, table_id, token = feishu_bitable_refs(table_url, token)
    feishu_ensure_fields(app_token, table_id, token, UNIFIED_CREATION_FIELD_SPECS)
    field_types = feishu_field_types(app_token, table_id, token)
    payload_fields: dict[str, Any] = {}
    for name, value in _candidate_fields(text, result).items():
        if name not in field_types or value in (None, "", []):
            continue
        coerced = feishu_coerce_value(value, field_types.get(name))
        if coerced in (None, "", []):
            continue
        payload_fields[name] = coerced
    if not payload_fields:
        raise RuntimeError("目标表没有可写入的已有字段")
    response = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        headers=feishu_headers(token),
        json={"fields": payload_fields},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"写入创作灵感表失败：{payload}")
    record = payload.get("data", {}).get("record") or {}
    return {
        "record_id": str(record.get("record_id") or ""),
        "table_url": table_url,
        "written_fields": sorted(payload_fields),
    }


def handle_creation_inspiration_command(
    text: str,
    *,
    attachment_paths: list[str] | None = None,
    table_url: str = "",
    no_write: bool = False,
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    load_default_env_files()
    target_url = table_url or DEFAULT_INSPIRATION_TABLE_URL
    result = analyze_creation_inspiration(text, attachment_paths or [], conversation_context=conversation_context)
    record_text = format_inspiration_text(text, result)
    feishu = {}
    if not no_write:
        feishu = write_inspiration_record(target_url, record_text, result)
    reply_lines = [
        "【创作-灵感】已整理并评分。",
        f"标题：{result.get('title')}",
        f"评分：{result.get('score')}/100",
        f"创作-再创方向：{result.get('recreation_direction')}",
    ]
    if feishu.get("record_id"):
        reply_lines.append(f"记录 ID：{feishu['record_id']}")
    reply_lines.append(f"灵感表：{target_url}")
    return {
        "ok": True,
        "mode": "creation_inspiration",
        "reply": "\n".join(reply_lines),
        "record_text": record_text,
        "result": result,
        "feishu": feishu,
        "table_url": target_url,
        "record_id": feishu.get("record_id", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze creative inspiration from text and attachments, then write Feishu bitable.")
    parser.add_argument("--text", default="")
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--attachment", dest="attachments", action="append", default=[])
    parser.add_argument("--feishu-url", default="")
    parser.add_argument("--conversation-context-json", default="")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    text = args.text or ""
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    conversation_context = json.loads(args.conversation_context_json) if args.conversation_context_json else None
    payload = handle_creation_inspiration_command(
        text,
        attachment_paths=args.attachments,
        table_url=args.feishu_url,
        no_write=args.no_write,
        conversation_context=conversation_context,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
