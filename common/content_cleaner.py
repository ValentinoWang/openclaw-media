from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .llm_client import generate_json_from_parts
from .llm_validation import LLMValidationContract, register_llm_validation_contract
from .llm_settings import LLMProviderSettings, load_content_cleaner_llm_settings


SOURCE_OCR = "image_ocr"
SOURCE_TRANSCRIPT = "transcript"
SOURCE_CONTENT = "content"


@dataclass(frozen=True)
class ContentCleanerConfig:
    enabled: bool
    base_url: str
    api_key: str
    model: str
    api_type: str
    timeout_seconds: int
    max_chars: int
    max_tokens: int
    thinking: str = ""
    bin: str = ""
    agent: str = ""
    cwd: str = ""
    codex_home: str = ""


def config_from_env() -> ContentCleanerConfig:
    settings = load_content_cleaner_llm_settings()
    return ContentCleanerConfig(
        enabled=settings.enabled,
        base_url=settings.provider.base_url,
        api_key=settings.provider.api_key,
        model=settings.provider.model,
        api_type=settings.provider.api_type,
        timeout_seconds=max(10, int(settings.provider.timeout)),
        max_chars=settings.max_chars,
        max_tokens=settings.max_tokens,
        thinking=settings.provider.thinking,
        bin=settings.provider.bin,
        agent=settings.provider.agent,
        cwd=settings.provider.cwd,
        codex_home=settings.provider.codex_home,
    )


def strip_false_clean_marker(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"(视频语音转写（已清洗）：|图片文字提取（已清洗）：)\s*", "", text)
    return text.strip()


def source_from_context(source_key: str = "", metadata: Mapping[str, Any] | None = None) -> str:
    source_key = (source_key or "").lower()
    content_type = str((metadata or {}).get("内容类型") or "").strip()
    if source_key == SOURCE_OCR or "ocr" in source_key or content_type == "图文":
        return SOURCE_OCR
    if source_key == SOURCE_TRANSCRIPT or "脚本" in source_key or content_type in {"短视频", "音频", "播客"}:
        return SOURCE_TRANSCRIPT
    return SOURCE_CONTENT


def clean_ocr_text(text: Any, *, title: str = "", metadata: Mapping[str, Any] | None = None, config: ContentCleanerConfig | None = None) -> str:
    return _clean_text_with_llm(text, SOURCE_OCR, title=title, metadata=metadata, config=config)


def clean_transcript_text(text: Any, *, title: str = "", metadata: Mapping[str, Any] | None = None, config: ContentCleanerConfig | None = None) -> str:
    return _clean_text_with_llm(text, SOURCE_TRANSCRIPT, title=title, metadata=metadata, config=config)


def clean_collected_text(text: Any, *, title: str = "", metadata: Mapping[str, Any] | None = None, config: ContentCleanerConfig | None = None) -> str:
    return _clean_text_with_llm(text, SOURCE_CONTENT, title=title, metadata=metadata, config=config)


def clean_text_by_source(
    text: Any,
    *,
    source_key: str = "",
    title: str = "",
    metadata: Mapping[str, Any] | None = None,
    config: ContentCleanerConfig | None = None,
) -> str:
    source_name = source_from_context(source_key, metadata)
    if source_name == SOURCE_OCR:
        return clean_ocr_text(text, title=title, metadata=metadata, config=config)
    if source_name == SOURCE_TRANSCRIPT:
        return clean_transcript_text(text, title=title, metadata=metadata, config=config)
    return clean_collected_text(text, title=title, metadata=metadata, config=config)


def _clean_text_with_llm(
    value: Any,
    source_name: str,
    *,
    title: str = "",
    metadata: Mapping[str, Any] | None = None,
    config: ContentCleanerConfig | None = None,
) -> str:
    text = strip_false_clean_marker(value)
    if not text:
        return ""
    cfg = config or config_from_env()
    if not cfg.enabled:
        raise RuntimeError("content cleaner LLM is not enabled")
    chunks = _split_cleaning_chunks(text, cfg.max_chars)
    cleaned_chunks = [_call_clean_llm(source_name, title, chunk, cfg) for chunk in chunks]
    if len(cleaned_chunks) != len(chunks) or any(not str(chunk or "").strip() for chunk in cleaned_chunks):
        raise RuntimeError("content cleaner LLM returned an empty cleaned chunk")
    cleaned = "\n\n".join(chunk for chunk in cleaned_chunks if chunk).strip()
    if not cleaned:
        raise RuntimeError("content cleaner LLM returned empty content")
    return cleaned


def _clean_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _clean_prompt(source_name: str, title: str, text: str) -> list[dict[str, str]]:
    if source_name == SOURCE_OCR:
        task = (
            "输入是图片 OCR 结果。请真正清洗成可阅读的中文正文：去掉 OCR 乱码、随机英文碎片、"
            "页眉页脚、按钮/水印/装饰符号、重复噪声；修复被错误断开的词句和段落；"
            "保留原文的主要信息、顺序和表达，不总结、不扩写、不添加事实。"
        )
    elif source_name == SOURCE_TRANSCRIPT:
        task = (
            "输入是视频或音频转写。请真正清洗成可阅读的中文正文：修正明显错别字和断句，"
            "去掉无意义口癖、重复卡顿和平台尾巴；保留原意、信息顺序和说话风格，不总结、不扩写、不添加事实。"
        )
    else:
        task = (
            "输入是采集到的内容正文。请清洗成可阅读的中文正文：修复格式、断句和明显噪声；"
            "保留原意和信息顺序，不总结、不扩写、不添加事实。"
        )
    system = (
        "你是中文内容清洗器。只输出清洗后的正文，不要解释，不要 Markdown 标题，"
        "不要输出“已清洗”等状态标签。无法确定是否为噪声的内容宁可保留；"
        "如果输入几乎全是无意义噪声，输出空字符串。"
    )
    user = f"标题：{title or '未命名'}\n内容类型：{source_name}\n清洗要求：{task}\n\n待清洗文本：\n{text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _call_clean_llm(source_name: str, title: str, text: str, config: ContentCleanerConfig) -> str:
    if not config.api_key:
        raise RuntimeError("content cleaner LLM api_key not configured")
    if not config.model:
        raise RuntimeError("content cleaner LLM model not configured")
    if not config.base_url:
        raise RuntimeError("content cleaner LLM base_url not configured")
    prompt = _clean_prompt(source_name, title, text)
    payload = generate_json_from_parts(
        [{"text": "\n\n".join(f"{item['role']}:\n{item['content']}" for item in prompt)}],
        LLMProviderSettings(
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            api_type=config.api_type,
            timeout=config.timeout_seconds,
            thinking=config.thinking,
        ),
        max_retries=1,
        instructions=(
            "你是中文内容清洗器。只输出合法 JSON object，不要 Markdown，不要解释。"
            "JSON 字段固定为 cleaned_text，值为清洗后的正文字符串。"
        ),
        error_prefix="content cleaner LLM 输出 JSON 校验失败",
        validation_contract=CONTENT_CLEANER_VALIDATION_CONTRACT,
    )
    cleaned = str(payload.get("cleaned_text") or "").strip()
    cleaned = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", cleaned, flags=re.I).strip()
    return strip_false_clean_marker(cleaned)


def _split_cleaning_chunks(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in re.split(r"(\n{2,})", text):
        if not paragraph:
            continue
        if current and current_len + len(paragraph) > max_chars:
            chunks.append("".join(current).strip())
            current = []
            current_len = 0
        if len(paragraph) > max_chars:
            for start in range(0, len(paragraph), max_chars):
                part = paragraph[start : start + max_chars].strip()
                if part:
                    chunks.append(part)
            continue
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        chunks.append("".join(current).strip())
    return [chunk for chunk in chunks if chunk]
CONTENT_CLEANER_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="common.content_cleaner.cleaned_text.v1",
        profile="strict_structured",
        required_fields=("cleaned_text",),
        allowed_fields=frozenset({"cleaned_text"}),
        field_types={"cleaned_text": str},
    )
)
