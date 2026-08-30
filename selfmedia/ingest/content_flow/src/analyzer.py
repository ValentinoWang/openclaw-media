from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable, Optional

from common.llm_client import generate_json_from_parts, image_parts_from_paths
from common.llm_settings import load_profile_llm_settings
from common.llm_validation import LLMValidationContract, register_llm_validation_contract
from common.knowledge_categories import (
    normalize_knowledge_secondary_categories,
)

from .config import Settings
from .semantic_persistence import LLM_CLEANED_USER_FIELDS_VERSION


ANALYST_SYSTEM_PROMPT = """
你是一名中文内容分析与运营编辑。你只基于本次标为 available 的内容证据说明作品为什么值得参考，以及创作者可以怎样做出自己的版本；只有随附视觉画面时才分析画面。
所有自然语言字段使用自然、具体的中文编辑口吻；不得直接输出英文或把英文句式逐字翻译成中文。

请根据用户提供的【视频文案/逐字稿/图文 OCR】，输出一份结构化内容分析。

请严格遵守以下输出要求：
1. 必须以 JSON 格式输出。
2. JSON 的 Key 必须包含：title, summary, primary_category, secondary_category, target_audience, pain_point, work_copy, full_content, hooks, emotion, score, tags, action_plan, hidden_info, visual_cues, transferable_expression。
3. 所有分析必须具体说明对应的内容证据和受众问题。不要只写“提升互动”“引发共鸣”这类没有内容指向的空泛结论。
4. 除 primary_category、secondary_category 外，如果某个字段缺少明确证据，请返回空字符串或空数组，不要写“未明确体现”“待复核”“待配置”等占位话术。
5. 如果内容涉及 PUA、服从性训练、操控关系、控制他人、欺骗或胁迫，只能做风险识别、反操控、防被拿捏和传播机制分析；不得输出可执行操控步骤、话术模板或训练方法。
6. OCR 只能作为素材证据和“全部内容”来源，不能原样塞进“全部文案”；需要修正明显 OCR 噪声，例如 Al/AI、断行、页码、乱码符号，再合并成可读正文。

以下是各字段的具体定义：

title (知识标题):
1. 用 15-32 个中文字符概括这条内容的核心主题和关键结论。
2. 必须综合视频文案、逐字稿、摘要、分类和标签生成。
3. 不要直接复制原始分享口令、链接标题或平台营销标题。
4. 标题要适合作为知识库第一列名称，例如“SubQ 用低成本长上下文挑战 Transformer”。

summary (内容要点):
用一句完整总结或不超过三条简短要点，概括这条作品能给受众带来的具体收获。语言简洁，但不要为了凑条数重复同一个判断。

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

hooks (开场抓手):
区分前 3 秒的停留抓手与前 5 秒的留人理由，分别说明可见文案、画面或转场采用的抓手类型（例如：具体问题、反差、利益承诺）。没有画面证据时只分析已有文案或转写，不要假设镜头。

emotion (情绪价值):
1. 这是一个单选或双选：焦虑 / 爽感 / 好奇 / 共鸣 / 愤怒 / 治愈。
2. 简述它是如何调动这种情绪的。

score (可迁移参考指数):
1. 给出 0-100 的打分。
2. 只根据已提供的内容证据评估：结构是否清晰、能否换成自己的真实经验、制作成本是否可控、风险是否可说明。没有播放或互动数据时，不要用“高流量”“爆款”等假设作为依据。

tags (标签):
1. 给出 3-5 个搜索标签。

action_plan (创作改写建议):
写清创作者如何做出自己的版本：可以保留什么结构或表达、应该换成什么真实角度、最低成本怎样拍摄。可用一段连贯说明或少量要点，不要强行套成固定的开头、中间、结尾模板，也不要为了格式硬凑编号。

hidden_info (隐形信息):
只写从文案、画面、身份、语气中能明确推断出的潜台词、可信度来源、价值观暗示或身份反差。证据不足时返回空字符串。

visual_cues (镜头/画面线索):
只写真实出现或可由媒体明确判断的构图、场景、道具、字幕、动作、剪辑节奏与 B-roll。没有看到媒体证据时返回空字符串。

transferable_expression (可迁移表达):
提炼可直接迁移到新视频的句式、镜头套路、情绪包装或结构模板。不能迁移时返回空字符串。
"""

ANALYSIS_PRIMARY_CATEGORIES = (
    "AI/工具", "商业/产品", "运营/管理", "学习/认知", "健康/运动", "财经/投资",
    "法律/政策", "生活/效率", "科技/科学", "人物/案例", "其他",
)

ANALYST_INSTRUCTIONS = """你是一名中文内容分析与运营编辑。你的输出为创作者提供内容洞察，帮助他们理解内容价值、受众痛点与可执行的创作方向。

输出协议：
只输出合法 JSON object，不要输出 Markdown，不要解释。
"""


ProgressFn = Callable[[str, int, str], None]


class _AnalysisUserContent(str):
    """Text prompt plus the visual evidence that is actually attached to it."""

    def __new__(cls, text: str, evidence_parts: list[dict[str, Any]]) -> _AnalysisUserContent:
        value = super().__new__(cls, text)
        value.evidence_parts = evidence_parts
        return value


ANALYSIS_REQUIRED_FIELDS = (
    "title", "summary", "primary_category", "secondary_category", "target_audience", "pain_point",
    "work_copy", "full_content", "hooks", "emotion", "score", "tags", "action_plan", "hidden_info",
    "visual_cues", "transferable_expression",
)

_ANALYSIS_TEXT_FIELDS = (
    "title", "summary", "target_audience", "pain_point", "work_copy", "full_content",
    "hooks", "emotion", "action_plan", "hidden_info", "visual_cues", "transferable_expression",
)
_ANALYSIS_TEMPLATE_PHRASES = (
    "黄金三秒",
    "万能结构公式",
    "拒绝正确的废话",
    '必须按照 "1. 2. 3." 的格式',
    "必须按 1. 2. 3. 分点",
)
_ANALYSIS_NUMBERED_ITEM = re.compile(r"(?:^|\n)\s*[1-3][.、)]\s*")
_ANALYSIS_VISUAL_CLAIM_TERMS = ("镜头", "画面", "场景", "字幕", "转场", "运镜", "特写", "道具", "剪辑", "B-roll")


def _chinese_ratio(value: Any) -> float:
    text = str(value or "")
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    letters = len(re.findall(r"[A-Za-z\u3400-\u9fff]", text))
    return cjk / letters if letters else 1.0


def _iter_analysis_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _validate_content_analysis_payload(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    for field_name in _ANALYSIS_TEXT_FIELDS:
        for text in _iter_analysis_text(payload.get(field_name)):
            if any(phrase in text for phrase in _ANALYSIS_TEMPLATE_PHRASES):
                raise ValueError(f"{field_name} 含固定课程模板话术，必须改写为具体编辑判断")
            if text.strip() and _chinese_ratio(text) < 0.2:
                raise ValueError(f"{field_name} 必须使用中文，不能直接回灌英文或翻译腔")
    action_plan = "\n".join(_iter_analysis_text(payload.get("action_plan")))
    if _ANALYSIS_NUMBERED_ITEM.search(action_plan):
        raise ValueError("action_plan 不得强制使用 1、2、3 编号模板")
    if not context.get("visual_evidence_available", False):
        if str(payload.get("visual_cues") or "").strip():
            raise ValueError("没有随附视觉证据时 visual_cues 必须为空")
        for field_name in ("hooks", "action_plan"):
            text = "\n".join(_iter_analysis_text(payload.get(field_name)))
            if any(term in text for term in _ANALYSIS_VISUAL_CLAIM_TERMS):
                raise ValueError(f"没有随附视觉证据时 {field_name} 不得假设镜头或画面")
    return payload


CONTENT_ANALYSIS_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.content_flow.analysis.v1",
        profile="strict_structured",
        required_fields=ANALYSIS_REQUIRED_FIELDS,
        allowed_fields=frozenset(ANALYSIS_REQUIRED_FIELDS),
        field_types={"secondary_category": list, "score": (int, float), "tags": list},
        validator=_validate_content_analysis_payload,
    )
)


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


def _attached_image_parts(image_paths: Optional[list[str]]) -> list[dict[str, Any]]:
    return image_parts_from_paths(image_paths, max_items=12)


def _build_analysis_user_content(
    transcript: str,
    url: str,
    video_path: Optional[str],
    image_paths: Optional[list[str]],
    caption: str,
    image_ocr: str,
    media_type: Optional[str],
) -> _AnalysisUserContent:
    kind = _analysis_media_kind(video_path, image_paths, media_type)
    caption_block = f"文案:\n{caption}" if caption else "文案: (空)"
    transcript_block = f"逐字稿:\n{transcript}" if transcript else "逐字稿: (空)"
    ocr_block = f"图文 OCR:\n{image_ocr}" if image_ocr else "图文 OCR: (空)"
    image_parts = _attached_image_parts(image_paths)
    visual_status = "available" if image_parts else "unavailable"
    text = (
        f"内容类型: {kind}\n"
        f"链接: {url}\n"
        "证据可用性:\n"
        f"- 文案: {'available' if caption else 'unavailable'}\n"
        f"- 逐字稿: {'available' if transcript else 'unavailable'}\n"
        f"- OCR 文本: {'available' if image_ocr else 'unavailable'}\n"
        f"- 视觉画面: {visual_status}\n"
        "- 互动数据: unavailable\n"
        "证据边界：只可依据标为 available 的文本或本次随附的视觉画面作出判断。"
        "视觉画面为 unavailable 时，visual_cues 必须为空字符串，hooks 和 action_plan 不得假设镜头、字幕、场景或剪辑；"
        "互动数据为 unavailable 时，score 只能依据已提供的内容结构、真实经验可迁移性、制作成本和风险，不得推断播放、点赞、收藏、评论或传播表现。\n\n"
        f"{caption_block}\n\n{transcript_block}\n\n{ocr_block}"
    )
    return _AnalysisUserContent(text, image_parts)


def analyze_with_openclaw_agent(user_content: str, settings: Settings) -> Optional[dict]:
    message = (
        f"{ANALYST_SYSTEM_PROMPT}\n\n"
        "输入内容：\n"
        f"{user_content}"
    )
    parts: list[dict[str, Any]] = [{"text": message}]
    parts.extend(getattr(user_content, "evidence_parts", []))
    try:
        llm_settings = load_profile_llm_settings("media_analysis")
        parsed = generate_json_from_parts(
            parts,
            llm_settings,
            max_retries=1,
            error_prefix="Codex Responses 结构化分析 JSON 校验失败",
            instructions=ANALYST_INSTRUCTIONS,
            validation_contract=CONTENT_ANALYSIS_VALIDATION_CONTRACT,
            validation_context={
                "visual_evidence_available": bool(getattr(user_content, "evidence_parts", ())),
            },
        )
    except Exception as exc:
        print(f"OpenClaw OAuth 结构化分析失败：{str(exc)[-1800:]}。", flush=True)
        return None

    if not parsed:
        print("OpenClaw OAuth 结构化分析未返回可解析 JSON。", flush=True)
        return None

    if not getattr(user_content, "evidence_parts", ()) and "visual_cues" in parsed:
        parsed["visual_cues"] = ""

    # The model makes the semantic decision; this only bounds its labels to the
    # shared vocabulary before the result is persisted or projected.
    primary = str(parsed.get("primary_category") or "").strip()
    if primary and primary not in ANALYSIS_PRIMARY_CATEGORIES:
        parsed["primary_category"] = "其他"
        primary = "其他"
    if parsed.get("secondary_category") not in (None, "", [], {}):
        parsed["secondary_category"] = normalize_knowledge_secondary_categories(
            parsed.get("secondary_category"), primary=primary, text=""
        )

    parsed.setdefault("analysis_provider", "openclaw_codex")
    parsed.setdefault("analysis_runtime", "openclaw_agent")
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

    openclaw_result = analyze_with_openclaw_agent(user_content, settings)
    if openclaw_result:
        openclaw_result["semantic_persistence_version"] = LLM_CLEANED_USER_FIELDS_VERSION
        return openclaw_result

    print("OpenClaw OAuth 分析不可用，标记为需要重新运行模型分析。", flush=True)
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
