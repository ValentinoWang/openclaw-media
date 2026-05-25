from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from typing import Any, Callable, Optional

import requests

from .config import Settings, _normalize_analysis_thinking
from .utils import parse_json_payload


ANALYST_SYSTEM_PROMPT = """
你是一位拥有千万粉丝的抖音/小红书短视频内容操盘手。你擅长拆解爆款逻辑，并将其转化为可执行的拍摄脚本。

请根据用户提供的【视频文案/逐字稿/图文 OCR】，输出一份结构化的分析报告。

请严格遵守以下输出要求：
1. 必须以 JSON 格式输出。
2. JSON 的 Key 必须包含：title, summary, primary_category, secondary_category, target_audience, pain_point, work_copy, full_content, hooks, emotion, score, tags, action_plan, hidden_info, visual_cues, transferable_expression。
3. 所有文本内容的分析必须犀利、直击痛点，拒绝正确的废话。
4. 除 primary_category、secondary_category 外，如果某个字段缺少明确证据，请返回空字符串或空数组，不要写“未明确体现”“待复核”“待配置”等占位话术。
5. 如果内容涉及 PUA、服从性训练、操控关系、控制他人、欺骗或胁迫，只能做风险识别、反操控、防被拿捏和传播机制分析；不得输出可执行操控步骤、话术模板或训练方法。
6. OCR 只能作为素材证据和“全部内容”来源，不能原样塞进“全部文案”；需要修正明显 OCR 噪声，例如 Al/AI、断行、页码、乱码符号，再合并成可读正文。

以下是各字段的具体定义：

title (知识标题):
1. 用 15-32 个中文字符概括这条内容的核心主题和关键结论。
2. 必须综合视频文案、逐字稿、摘要、分类和标签生成。
3. 不要直接复制原始分享口令、链接标题或平台营销标题。
4. 标题要适合作为知识库第一列名称，例如“SubQ 用低成本长上下文挑战 Transformer”。

summary (黄金总结):
1. 用 3 点概括这条视频的核心价值（用户看了能得到什么）。
2. 语言要极度精炼。

primary_category (一级分类):
只能从以下值中选择一个：AI/工具、商业/产品、运营/管理、学习/认知、健康/运动、财经/投资、法律/政策、生活/效率、科技/科学、人物/案例、其他。

secondary_category (二级分类):
1. 必须输出，不得为空。
2. JSON 中必须输出数组，返回 1-3 个细分方向；如果只能确定一个，也要返回单元素数组。
3. 每个方向用 2-10 个中文字符，例如：AI视频/自动化、模型/智能体、AI工具应用、创作者提效、产品增长、流程管理、学习方法、合规风险、案例拆解。
4. 必须和 primary_category 语义一致，不要写泛泛的“其他”或“未细分”，除非内容确实无法判断。

target_audience (目标人群):
1. 提取这条内容主要写给谁，例如 AI 小白、职场新人、企业老板、学生、创作者。
2. 如果原文没有明确人群，请基于文案和画面谨慎推断，证据不足则返回空字符串。

pain_point (核心痛点):
1. 提取目标人群当前卡住的具体问题。
2. 必须具体，例如“不会开始”“不会提问”“工具太多不知道选哪个”，不要写“提升效率”这类泛泛表述。

work_copy (作品文案):
1. 只输出作品页面里的平台正文、标题描述和 tags/话题标签，适合写入知识库“全部文案”。
2. 无论视频还是图文，都不要把视频语音转写、图片 OCR、画面中文字全文塞进 work_copy。
3. 保留原作品里的 tags/话题标签；清理分享口令、复制打开提示、链接和无关平台噪声。

full_content (全部内容):
1. 输出作品媒体里的完整内容，适合写入知识库“全部内容”。
2. 视频内容输出语音转写的清洗正文；图文内容输出图片 OCR 按页面顺序整合后的清洗正文。
3. 不要保留 `## 01 image-01.jpg`、乱码、重复页脚、无意义符号；不要改写成分析结论。

hooks (黄金三秒):
1. 分析前 5 秒文案或画面是如何留住用户的。
2. 提取出它的“抓手”类型（例如：痛点反问、巨大的反差、利益承诺等）。

emotion (情绪价值):
1. 这是一个单选或双选：焦虑 / 爽感 / 好奇 / 共鸣 / 愤怒 / 治愈。
2. 简述它是如何调动这种情绪的。

score (翻拍推荐指数):
1. 给出 0-100 的打分。
2. 逻辑：低成本+高流量=高分；高成本+低流量=低分。

tags (标签):
1. 给出 3-5 个搜索标签。

action_plan (二创实操SOP):
这是一个极其重要的字段，请必须按照 "1. 2. 3." 的格式分点作答，内容必须包含以下三个维度：
1. 【万能结构公式】：将原视频拆解为“开头+中间+结尾”的填空题模板。（例如：开头用xx提问 + 中间展示3个xx + 结尾升华到xx）。
2. 【差异化切入点】：如果我来拍，如何换个角度蹭这个热点？（例如：原视频讲职场，建议你改到考研赛道；原视频是口播，建议你改为Vlog形式）。
3. 【低成本拍摄方案】：给出具体的画面建议（例如：不需要外景，只需要在这个位置，打一盏灯，对镜头展示xx物品）。

hidden_info (隐形信息):
只写从文案、画面、身份、语气中能明确推断出的潜台词、可信度来源、价值观暗示或身份反差。证据不足时返回空字符串。

visual_cues (镜头/画面线索):
只写真实出现或可由媒体明确判断的构图、场景、道具、字幕、动作、剪辑节奏与 B-roll。没有看到媒体证据时返回空字符串。

transferable_expression (可迁移表达):
提炼可直接迁移到新视频的句式、镜头套路、情绪包装或结构模板。不能迁移时返回空字符串。
"""


ProgressFn = Callable[[str, int, str], None]


def _analysis_timeout_seconds(settings: Settings) -> float:
    return max(
        float(settings.analysis_openclaw_timeout or 0),
        float(settings.qwen_timeout or 0),
        float(settings.gemini_timeout or 0),
        1.0,
    )


def _analysis_media_kind(
    video_path: Optional[str],
    image_paths: Optional[list[str]],
    media_type: Optional[str],
) -> str:
    if media_type == "animated":
        return "动图"
    if media_type == "image" or (image_paths and not video_path):
        return "图文"
    if not video_path and not image_paths:
        return "文案"
    return "视频"


def _build_analysis_user_content(
    transcript: str,
    url: str,
    video_path: Optional[str],
    image_paths: Optional[list[str]],
    caption: str,
    image_ocr: str,
    media_type: Optional[str],
) -> str:
    kind = _analysis_media_kind(video_path, image_paths, media_type)
    caption_block = f"文案:\n{caption}" if caption else "文案: (空)"
    transcript_block = f"逐字稿:\n{transcript}" if transcript else "逐字稿: (空)"
    ocr_block = f"图文 OCR:\n{image_ocr}" if image_ocr else "图文 OCR: (空)"
    media_lines: list[str] = []
    if video_path:
        media_lines.append(f"本地视频文件: {video_path}")
    if image_paths:
        media_lines.append("本地图片文件:")
        media_lines.extend(f"- {path}" for path in image_paths[:12])
    media_block = "\n".join(media_lines) if media_lines else "本地媒体文件: (无)"
    return (
        f"内容类型: {kind}\n"
        f"链接: {url}\n"
        f"{media_block}\n"
        "请优先基于媒体内容与文案完成分析。\n"
        "若是图文/动图，请以图片内容为主，文案为辅。\n\n"
        f"{caption_block}\n\n{transcript_block}\n\n{ocr_block}"
    )


def _qwen_chat_endpoint(settings: Settings) -> str:
    base_url = (settings.qwen_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _qwen_message_content(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif item is not None:
                parts.append(str(item))
        return "".join(parts)
    return ""


def _normalize_openclaw_model(value: str) -> str:
    model = (value or "").strip()
    if model and "/" not in model:
        return f"openai-codex/{model}"
    return model


def _parse_openclaw_json(output: str) -> dict[str, Any]:
    text = (output or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except ValueError:
        pass

    decoder = json.JSONDecoder()
    fallback: dict[str, Any] = {}
    for match in re.finditer(r"\{", text):
        try:
            payload, _ = decoder.raw_decode(text[match.start() :])
        except ValueError:
            continue
        if isinstance(payload, dict):
            if any(key in payload for key in ("runId", "result", "payloads", "status")):
                return payload
            if not fallback:
                fallback = payload
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
        texts = [
            str(payload.get("text")).strip()
            for payload in payloads
            if isinstance(payload, dict) and payload.get("text")
        ]
        if texts:
            return "\n".join(texts)
    return ""


def _looks_like_openclaw_run(payload: dict[str, Any]) -> bool:
    if any(key in payload for key in ("title", "summary", "primary_category", "secondary_category")):
        return False
    return any(key in payload for key in ("runId", "result", "payloads", "status"))


def _clean_openclaw_error(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return "OpenClaw/Codex 分析失败"
    if "Token refresh failed" in value or "refresh token" in value or "OAuth token refresh failed" in value:
        return "OpenClaw/Codex 授权刷新失败，需要重新登录 Codex/OpenAI 授权。"
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    diagnostics = [
        line
        for line in lines
        if "EMBEDDED FALLBACK" not in line
        and "[diagnostic]" not in line
        and "[model-fallback" not in line
        and not line.startswith("Config warnings:")
    ]
    return "\n".join(diagnostics[-12:]) or lines[-1]


def analyze_with_openclaw(user_content: str, settings: Settings) -> Optional[dict]:
    openclaw_bin = (settings.analysis_openclaw_bin or "openclaw").strip() or "openclaw"
    timeout = max(int(settings.analysis_openclaw_timeout or 0), 1)
    model = _normalize_openclaw_model(settings.analysis_openclaw_model)
    if not model:
        print("OpenClaw/Codex 分析模型未配置：SELFMEDIA_ANALYSIS_OPENCLAW_MODEL 为空。", flush=True)
        return None
    if not settings.analysis_openclaw_agent.strip():
        print("OpenClaw/Codex 分析 agent 未配置：SELFMEDIA_ANALYSIS_OPENCLAW_AGENT 为空。", flush=True)
        return None
    display_model = model
    source_key = hashlib.sha1(user_content[:5000].encode("utf-8")).hexdigest()[:12]
    session_id = f"content-flow-analysis-{source_key}-{time.time_ns()}"
    message = (
        f"{ANALYST_SYSTEM_PROMPT}\n\n"
        "输入内容：\n"
        f"{user_content}\n\n"
        "只输出 JSON，不要输出 Markdown，不要解释。"
    )
    cmd = [openclaw_bin, "agent"]
    if settings.analysis_openclaw_agent.strip():
        cmd.extend(["--agent", settings.analysis_openclaw_agent.strip()])
    cmd.extend(
        [
            "--session-id",
            session_id,
            "--message",
            message,
            "--json",
            "--timeout",
            str(timeout),
        ]
    )
    cmd.extend(["--model", model])
    thinking = _normalize_analysis_thinking(settings.analysis_openclaw_thinking)
    if thinking:
        cmd.extend(["--thinking", thinking])

    run_env = dict(os.environ)
    run_env.setdefault("HOME", "/home/ubuntu")
    if settings.analysis_openclaw_codex_home:
        run_env["CODEX_HOME"] = settings.analysis_openclaw_codex_home
    run_env["PATH"] = (
        "/home/ubuntu/.nvm/versions/node/v22.22.2/bin:"
        "/home/ubuntu/bin:/usr/local/bin:/usr/bin:/bin:"
        f"{run_env.get('PATH', '')}"
    )
    cwd = settings.analysis_openclaw_cwd or "/home/ubuntu/.openclaw/workspace"
    if not os.path.isdir(cwd):
        cwd = "/home/ubuntu"

    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout + 60,
            env=run_env,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        print(f"OpenClaw/Codex 分析超时：超过 {timeout} 秒，切换到 Qwen。", flush=True)
        return None
    except OSError as exc:
        print(f"无法调用 OpenClaw/Codex 分析：{exc}，切换到 Qwen。", flush=True)
        return None

    parsed_run = _parse_openclaw_json(proc.stdout)
    reply = _extract_openclaw_reply(parsed_run) or proc.stdout
    parsed = parse_json_payload(reply) if reply else None
    if parsed and _looks_like_openclaw_run(parsed):
        parsed = None

    if proc.returncode != 0:
        reason = _clean_openclaw_error(proc.stderr.strip() or reply.strip() or f"退出码 {proc.returncode}")
        print(f"OpenClaw/Codex 分析失败：{reason[-1800:]}，切换到 Qwen。", flush=True)
        return None
    if not parsed:
        print("OpenClaw/Codex 未返回可解析 JSON，切换到 Qwen。", flush=True)
        return None

    parsed.setdefault("analysis_provider", "openclaw")
    parsed.setdefault("analysis_model", display_model)
    parsed.setdefault("analysis_status", "complete")
    return parsed


def analyze_with_qwen(user_content: str, settings: Settings) -> Optional[dict]:
    if not settings.qwen_api_key:
        return None

    endpoint = _qwen_chat_endpoint(settings)
    messages = [
        {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    base_payload = {
        "model": settings.qwen_model,
        "messages": messages,
        "temperature": 0.2,
    }
    last_error = ""
    for use_json_mode in (True, False):
        payload = dict(base_payload)
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {settings.qwen_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=settings.qwen_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            resp = getattr(exc, "response", None)
            if resp is not None:
                last_error = f"{resp.status_code} {resp.text[:300].replace(chr(10), ' ')}"
                if use_json_mode and resp.status_code in {400, 422}:
                    continue
            else:
                last_error = str(exc)
            break

        try:
            raw_payload = response.json()
        except ValueError:
            last_error = "Qwen 返回非 JSON"
            break

        try:
            content = raw_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = ""
        text = _qwen_message_content(content).strip()
        parsed = parse_json_payload(text) if text else None
        if parsed:
            parsed.setdefault("analysis_provider", "qwen")
            parsed.setdefault("analysis_model", settings.qwen_model)
            parsed.setdefault("analysis_status", "complete")
            return parsed
        last_error = "Qwen 返回内容无法解析为 JSON"
        break

    if last_error:
        print(f"Qwen 分析失败: {last_error}", flush=True)
    return None


def _analyze_transcript_impl(
    transcript: str,
    url: str,
    video_path: Optional[str],
    image_paths: Optional[list[str]],
    caption: str,
    image_ocr: str = "",
    media_type: Optional[str] | Any = None,
    settings: Optional[Settings] = None,
) -> Optional[dict]:
    if settings is None:
        settings = media_type  # type: ignore[assignment]
        media_type = image_ocr
        image_ocr = ""
    caption = caption or ""
    transcript = transcript or ""
    image_ocr = image_ocr or ""
    user_content = _build_analysis_user_content(
        transcript,
        url,
        video_path,
        image_paths,
        caption,
        image_ocr,
        media_type,
    )

    openclaw_result = analyze_with_openclaw(user_content, settings)
    if openclaw_result:
        return openclaw_result

    print("OpenClaw/Codex 分析不可用，标记为需要重新运行模型分析。", flush=True)
    source_text = (caption or transcript or image_ocr or url or "").strip()
    compact = " ".join(source_text.split())
    full_content_source = transcript or image_ocr
    full_content = " ".join(full_content_source.split())
    summary = compact[:220] or ""
    tags = []
    for token in ["AIGC", "AI生图", "PS", "AE", "视差动画", "AI动画", "设计干货", "小红书"]:
        if token.lower() in compact.lower() or token in url:
            tags.append(token)
    return {
        "title": summary[:32] if summary else "",
        "summary": [summary] if summary else [],
        "primary_category": "其他",
        "secondary_category": ["未细分"],
        "target_audience": "",
        "pain_point": "",
        "work_copy": " ".join(caption.split()),
        "full_content": full_content,
        "hooks": "",
        "emotion": "",
        "score": 0,
        "tags": tags[:5],
        "action_plan": "",
        "hidden_info": "",
        "visual_cues": "",
        "transferable_expression": "",
        "analysis_status": "needs_model_rerun",
        "fallback_reason": "primary_analysis_unavailable",
    }


def analyze_transcript(
    transcript: str,
    url: str,
    video_path: Optional[str],
    image_paths: Optional[list[str]],
    caption: str,
    image_ocr: str = "",
    media_type: Optional[str] | Any = None,
    settings: Optional[Settings] = None,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (70, 90),
) -> Optional[dict]:
    if settings is None:
        settings = media_type  # type: ignore[assignment]
        media_type = image_ocr
        image_ocr = ""
    if not progress:
        return _analyze_transcript_impl(
            transcript,
            url,
            video_path,
            image_paths,
            caption,
            image_ocr,
            media_type,
            settings,
        )

    result_box: dict[str, Optional[dict]] = {"result": None}
    error_box: dict[str, Exception] = {}

    def worker() -> None:
        try:
            result_box["result"] = _analyze_transcript_impl(
                transcript,
                url,
                video_path,
                image_paths,
                caption,
                image_ocr,
                media_type,
                settings,
            )
        except Exception as exc:
            error_box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    start_time = time.time()
    start_percent, end_percent = progress_range
    while thread.is_alive():
        elapsed = time.time() - start_time
        timeout = _analysis_timeout_seconds(settings)
        ratio = min(elapsed / timeout, 0.95)
        percent = start_percent + int((end_percent - start_percent) * ratio)
        try:
            progress("analyst", percent, f"分析中 {elapsed:.0f}s")
        except Exception:
            pass
        thread.join(timeout=1.0)

    thread.join()
    if error_box:
        return None
    return result_box["result"]
