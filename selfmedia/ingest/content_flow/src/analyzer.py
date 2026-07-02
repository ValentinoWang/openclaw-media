from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Optional

from common.llm_client import generate_json_from_parts
from common.llm_settings import load_profile_llm_settings

from .config import Settings


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
3. 只能从以下统一标准值中选择：AI视频/自动化、模型/智能体、AI工具应用、AI浏览器、AI视频工具、AI增长/GEO、AI趋势盘点、产品增长、AI产品变现、流程管理、算法拆解/增长、自媒体运营、短视频运营、内容创作、内容运营、学习方法、心理认知、关系认知、情感认知、关系风险、健康管理、投资认知、合规风险、生活效率、科技趋势、案例拆解、未细分。
4. 必须和 primary_category 语义一致，不要自造“平台机制”“内容增长”“创作者变现”等新选项；除非内容确实无法判断，否则不要写“未细分”。

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
        float(settings.analysis_timeout or 0),
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


def analyze_with_codex_responses(user_content: str, settings: Settings) -> Optional[dict]:
    message = (
        f"{ANALYST_SYSTEM_PROMPT}\n\n"
        "输入内容：\n"
        f"{user_content}\n\n"
        "只输出 JSON，不要输出 Markdown，不要解释。"
    )
    try:
        llm_settings = load_profile_llm_settings("media_analysis")
        parsed = generate_json_from_parts(
            [{"text": message}],
            llm_settings,
            max_retries=1,
            error_prefix="Codex Responses 结构化分析 JSON 校验失败",
            instructions="你是 Media 内容分析 JSON 引擎。必须只输出合法 JSON object，不要 Markdown，不要解释。",
        )
    except Exception as exc:
        print(f"Codex Responses 结构化分析失败：{str(exc)[-1800:]}。", flush=True)
        return None

    if not parsed:
        print("Codex 结构化分析未返回可解析 JSON。", flush=True)
        return None

    parsed.setdefault("analysis_provider", "codex_responses")
    parsed.setdefault("analysis_runtime", "codex_responses")
    parsed.setdefault("analysis_model", llm_settings.model)
    parsed.setdefault("analysis_status", "complete")
    return parsed


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

    codex_result = analyze_with_codex_responses(user_content, settings)
    if codex_result:
        return codex_result

    print("Codex Responses 分析不可用，标记为需要重新运行模型分析。", flush=True)
    return {
        "title": "",
        "summary": [],
        "primary_category": "其他",
        "secondary_category": ["未细分"],
        "target_audience": "",
        "pain_point": "",
        "work_copy": "",
        "full_content": "",
        "hooks": "",
        "emotion": "",
        "score": 0,
        "tags": [],
        "action_plan": "",
        "hidden_info": "",
        "visual_cues": "",
        "transferable_expression": "",
        "analysis_status": "needs_model_rerun",
        "incomplete_reason": "primary_analysis_unavailable",
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
