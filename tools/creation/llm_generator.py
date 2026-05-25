from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from common.llm_settings import load_creation_agent_settings

from .platform_validator import validate_platform_draft
from .request_parser import CreationRequest


def generate_openclaw_creation_draft(
    request: CreationRequest,
    *,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
    platform_fit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = build_creation_prompt(
        request,
        activity_candidates=activity_candidates,
        viral_candidates=viral_candidates,
        inspiration_candidates=inspiration_candidates,
        business_candidates=business_candidates,
        reference_docs=reference_docs,
        media_context=media_context,
        platform_fit=platform_fit,
    )
    last_error = ""
    for attempt in range(_env_int("SELFMEDIA_CREATION_LLM_RETRIES", 2) + 1):
        message = prompt
        if last_error:
            message = (
                f"{prompt}\n\n"
                "上一次输出没有通过代码校验。\n"
                f"错误：{last_error}\n"
                "请重新输出完整 JSON object，只修正格式和约束，不要解释。"
            )
        payload = _call_openclaw_json(message)
        try:
            return validate_llm_draft_payload(payload, request, platform_fit=platform_fit)
        except ValueError as exc:
            last_error = str(exc)
            if attempt >= _env_int("SELFMEDIA_CREATION_LLM_RETRIES", 2):
                break
    raise RuntimeError(f"OpenClaw/LLM 创作输出未通过校验：{last_error}")


def build_creation_prompt(
    request: CreationRequest,
    *,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
    platform_fit: dict[str, Any] | None = None,
) -> str:
    payload = {
        "request": request.to_dict(),
        "media_memory_prompt": (media_context or {}).get("prompt") or "",
        "media_context_loaded": (media_context or {}).get("loaded") or {},
        "account_profile": (media_context or {}).get("account_profile") or {},
        "recent_creations": (media_context or {}).get("recent_creations") or [],
        "recent_reviews": (media_context or {}).get("recent_reviews") or [],
        "activity_memory_candidates": activity_candidates,
        "viral_memory_candidates": viral_candidates,
        "inspiration_memory_candidates": inspiration_candidates,
        "business_memory_candidates": business_candidates,
        "reference_docs": reference_docs,
        "platform_mechanism_fit": platform_fit or {},
    }
    platform_rules = {
        "小红书": "标题不超过 20 个字符；tags 必须正好 10 个；图文必须输出 image_script 或 carousel；视频必须输出 storyboard。",
        "抖音": "标题不能为空；tags 必须正好 5 个；视频必须输出 hook_3s、storyboard、voiceover、subtitles；图文必须输出 image_script 或 carousel。",
    }
    return (
        "你是 OpenClaw media bot 的创作总编。现在由 OpenClaw/LLM 接管【创作】主链路，"
        "启发式规则只作为硬约束和资料边界，不负责写稿。\n\n"
        "任务：基于用户请求、活动记忆、爆款记忆、商务记忆、账号 Markdown 档案和最近对话，"
        "选择真正适合的参考记录，并生成可直接进入飞书创作文档的平台化初稿。\n\n"
        "硬约束：\n"
        f"1. platform 必须等于 {request.platform}；content_type 必须等于 {request.content_type}；topic 必须围绕 {request.topic}。\n"
        f"2. 平台规则：{platform_rules.get(request.platform, '必须符合平台字段校验。')}\n"
        "3. selected_activity_ids、selected_viral_ids、selected_inspiration_ids、selected_business_ids 只能使用候选里的 id；没有适合参考就输出空数组。\n"
        "4. 活动、商务、爆款、创作灵感数据只来自输入记忆；禁止编造活动奖励、投稿规则、商务承诺、互动数据、个人经历或账号事实。\n"
        "5. 允许创造表达、标题、脚本、分镜和叙事结构；但必须显式说明用了哪些活动/爆款/创作灵感/账号记忆，没用则说明原因。\n"
        "6. 参考爆款只能迁移结构、冲突、情绪推进、行动门槛和画面组织，不得复刻原文；参考创作灵感优先迁移真实场景、信号、观点和可复用角度。\n"
        "7. 如果账号 Markdown 档案信息不足，要在 risks_or_missing_info 中说明要补什么，但仍基于现有输入完成初稿。\n"
        "8. 不要直接从主题跳到标题或脚本。必须先在 topic_strategy 中拆清楚目标人群、真实痛点、单一内容角度、只解决的一个小问题和自查标准，再生成 title/final_copy。\n"
        "9. 如果参考素材里有 OCR 或图片文字，只能当作素材证据和文案补全来源；最终 final_copy、title、topic_strategy 必须经过清洗和改写，不得原样堆叠 OCR。\n"
        "10. 必须参考 platform_mechanism_fit 里的 platform_strategy、activity_strategy、creation_reverse_plan 和 validation_targets；"
        "这只是平台机制拟合假设，不得声称破解平台真实算法或掌握黑箱权重。\n"
        "11. 只输出合法 JSON object，不要 Markdown 代码块，不要解释。\n\n"
        "输出 JSON 字段固定为：\n"
        "platform, content_type, title, tags, topic, topic_strategy, final_copy, inspiration, activity_constraint, "
        "viral_reference, inspiration_reference, business_reference, account_context, positioning_analysis, platform_strategy, "
        "activity_strategy, traffic_hypothesis, creation_reverse_plan, validation_targets, selected_activity_ids, "
        "selected_viral_ids, selected_inspiration_ids, selected_business_ids, image_script, carousel, hook_3s, storyboard, voiceover, "
        "subtitles, production_checklist, review_plan, risks_or_missing_info。\n\n"
        "topic_strategy 字段必须包含：target_audience, pain_point, content_angle, single_problem, self_check。\n\n"
        "输入 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def validate_llm_draft_payload(payload: dict[str, Any], request: CreationRequest, *, platform_fit: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("LLM JSON 顶层必须是 object")
    draft = dict(payload)
    for key in ("platform", "content_type", "title", "topic", "final_copy", "hook_3s", "voiceover"):
        draft[key] = str(draft.get(key) or "").strip()
    if draft["platform"] != request.platform:
        raise ValueError(f"LLM 输出 platform 必须为 {request.platform}")
    if draft["content_type"] != request.content_type:
        raise ValueError(f"LLM 输出 content_type 必须为 {request.content_type}")
    for key in (
        "tags",
        "inspiration",
        "selected_activity_ids",
        "selected_viral_ids",
        "selected_inspiration_ids",
        "selected_business_ids",
        "subtitles",
        "production_checklist",
        "review_plan",
        "risks_or_missing_info",
    ):
        draft[key] = _as_string_list(draft.get(key))
    for key in ("activity_constraint", "viral_reference", "inspiration_reference", "business_reference", "account_context"):
        draft[key] = _as_dict(draft.get(key), default_key="summary")
    draft["positioning_analysis"] = _as_dict(draft.get("positioning_analysis"), default_key="positioning")
    draft["topic_strategy"] = _as_dict(draft.get("topic_strategy"), default_key="summary")
    platform_fit = platform_fit or {}
    for key in ("platform_strategy", "activity_strategy", "traffic_hypothesis", "creation_reverse_plan", "validation_targets"):
        draft[key] = _as_dict(draft.get(key), default_key="summary") or _as_dict(platform_fit.get(key), default_key="summary")
    for key in ("image_script", "carousel", "storyboard"):
        draft[key] = _as_list(draft.get(key))
    if not draft["title"]:
        raise ValueError("title 不能为空")
    if not draft["final_copy"]:
        raise ValueError("final_copy 不能为空")
    if not draft["inspiration"]:
        raise ValueError("inspiration 不能为空")
    if not draft["production_checklist"]:
        raise ValueError("production_checklist 不能为空")
    if not draft["review_plan"]:
        raise ValueError("review_plan 不能为空")
    if request.content_type == "图文" and not (draft["image_script"] or draft["carousel"]):
        raise ValueError("图文稿必须输出 image_script 或 carousel")
    if request.content_type == "视频":
        if not draft["hook_3s"]:
            raise ValueError("视频稿必须输出 hook_3s")
        if not draft["storyboard"]:
            raise ValueError("视频稿必须输出 storyboard")
        if not draft["voiceover"]:
            raise ValueError("视频稿必须输出 voiceover")
        if not draft["subtitles"]:
            raise ValueError("视频稿必须输出 subtitles")
    validation = validate_platform_draft(request.platform, request.content_type, draft)
    if not validation.ok:
        messages = "; ".join(issue.message for issue in validation.issues)
        raise ValueError(f"平台规则校验失败：{messages}")
    return draft


def _call_openclaw_json(message: str) -> dict[str, Any]:
    settings = load_creation_agent_settings()
    openclaw_bin = settings.bin.strip() or "openclaw"
    timeout = max(int(settings.timeout), 1)
    if not settings.agent:
        raise RuntimeError("OpenClaw 创作 agent 未配置：SELFMEDIA_CREATION_OPENCLAW_AGENT 为空")
    if not settings.model:
        raise RuntimeError("OpenClaw 创作模型未配置：SELFMEDIA_CREATION_OPENCLAW_MODEL 为空")
    session_id = f"media-creation-{time.time_ns()}"
    cmd = [
        openclaw_bin,
        "agent",
        "--agent",
        settings.agent,
        "--session-id",
        session_id,
        "--message",
        message,
        "--json",
        "--timeout",
        str(timeout),
    ]
    cmd.extend(["--model", settings.model])
    if settings.thinking:
        cmd.extend(["--thinking", settings.thinking])

    env = dict(os.environ)
    env.setdefault("HOME", "/home/ubuntu")
    env.setdefault("CODEX_HOME", settings.codex_home)
    env.setdefault("PATH", "/home/ubuntu/.nvm/versions/node/v22.22.2/bin:/home/ubuntu/bin:/usr/local/bin:/usr/bin:/bin")
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout + 60,
        env=env,
        cwd=settings.cwd,
    )
    parsed_run = _parse_openclaw_json(proc.stdout)
    reply = _extract_openclaw_reply(parsed_run) or proc.stdout
    if proc.returncode != 0:
        reason = (proc.stderr.strip() or reply.strip() or f"openclaw exited with {proc.returncode}")[-2000:]
        raise RuntimeError(f"OpenClaw 创作调用失败：{reason}")
    parsed = _parse_json_payload(reply)
    if not parsed:
        raise RuntimeError("OpenClaw 创作未返回可解析 JSON")
    return parsed


def _parse_openclaw_json(output: str) -> dict[str, Any]:
    text = (output or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    fallback: dict[str, Any] = {}
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            if any(key in parsed for key in ("runId", "result", "payloads", "status")):
                return parsed
            if not fallback:
                fallback = parsed
    return fallback


def _extract_openclaw_reply(parsed: dict[str, Any]) -> str:
    if not parsed:
        return ""
    for key in ("reply", "message", "text", "output", "final", "content"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    result = parsed.get("result")
    if isinstance(result, dict):
        payloads = result.get("payloads")
        if isinstance(payloads, list):
            texts = [
                str(payload.get("text")).strip()
                for payload in payloads
                if isinstance(payload, dict) and payload.get("text")
            ]
            if texts:
                return "\n".join(texts)
        for key in ("reply", "message", "text", "output", "final", "content"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        meta = result.get("meta")
        if isinstance(meta, dict):
            for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
                value = meta.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    payloads = parsed.get("payloads")
    if isinstance(payloads, list):
        parts = []
        for item in payloads:
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item.get("text", "").strip():
                parts.append(item["text"].strip())
        if parts:
            return "\n".join(parts)
    return ""


def _parse_json_payload(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        return {}
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.S | re.I)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_string_list(value: Any) -> list[str]:
    result = []
    for item in _as_list(value):
        text = str(item or "").strip(" #\t")
        if text:
            result.append(text)
    return result


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [])]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[\n,，、;；]+", value) if item.strip()]
    return [value]


def _as_dict(value: Any, *, default_key: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    return {default_key: text} if text else {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
