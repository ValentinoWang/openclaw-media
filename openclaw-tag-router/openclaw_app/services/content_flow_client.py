from __future__ import annotations

import html
import json
import math
import os
import re
import subprocess
import sys
import time
import hashlib
import string
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from common.llm_client import generate_json_from_parts, is_model_capacity_failure, model_capacity_failure_detail
from common.llm_settings import LLMProviderSettings, load_profile_llm_settings
from common.llm_validation import LLMValidationContract, register_llm_validation_contract
from selfmedia.ingest.content_flow.src.pipeline import _extract_image_ocr
from selfmedia.ingest.content_flow.src.semantic_persistence import (
    LLM_CLEANED_USER_FIELDS_VERSION,
    analysis_user_field_contract_issue,
)

from .media_text_cleaner import MEDIA_TEXT_CLEANER, MediaCopyParts
from .transcription_postprocess_contract import (
    TRANSCRIPTION_FINAL_NOTE_REQUIRED_FIELDS,
    transcription_final_note_value_missing,
    validate_transcription_final_note_contract,
)
from .utils import ensure_dir
from ..router.openclaw_bot_llm import (
    profile_config,
    profile_provider_runtime,
)


CONTENT_FLOW_ROOT = Path(os.getenv("CONTENT_FLOW_ROOT", "/home/ubuntu/selfmedia-tools/selfmedia/ingest/content_flow"))
SELFMEDIA_TOOLS_ROOT = Path(os.getenv("SELFMEDIA_TOOLS_ROOT", "/home/ubuntu/selfmedia-tools"))
CONTENT_FLOW_SECRET_ENV_PATH = Path(
    os.getenv("CONTENT_FLOW_SECRET_ENV_PATH", "/home/ubuntu/.openclaw/openclaw-media.env")
)

TRANSCRIPTION_DETAIL_FIDELITY_CONTRACT = (
    "细节保真契约：目标是去冗余整理，不是摘要。必须保留全部非重复实质信息，包括数字、价格、成本、公司/产品/论文名称、"
    "技术路线、具体例子、对比与替代方案、前提条件、因果链、否定、分歧、风险、未决问题、不确定性和行动上下文。"
    "只允许删除语气词、口吃、寒暄、无意义重复和语义完全相同的复述；不得用上位概念替代多个不同细节，不得因低频、敏感或输出较长而省略有业务含义的内容。"
    "不得压缩成 3-8 条概括，不得把多个具体细节合并成一句上位概括。"
    "来源补充和关键词只作为逐字稿校正、检索和关联线索：逐项核对其在逐字稿中的上下文，存在来源支撑时保留对应细节；没有来源支撑时标为未核验，不得补造事实。"
)

TRANSCRIPTION_SOURCE_UNIT_SCHEMA_VERSION = "3.0"
TRANSCRIPTION_SOURCE_UNIT_TARGET_CHARS = 520
TRANSCRIPTION_SOURCE_UNIT_MAX_CHARS = 780
TRANSCRIPTION_SOURCE_UNIT_MIN_RETAINED_RATIO = 0.45
TRANSCRIPTION_SOURCE_UNIT_MAX_DISCARDED_RATIO = 0.35


def _validate_content_flow_payload(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if not any(value not in (None, "", [], {}) for value in payload.values()):
        raise ValueError(f"{context.get('stage') or 'content flow'} returned an empty payload")
    return payload


CONTENT_FLOW_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="tag_router.content_flow.direct_json.v1",
        profile="bounded_open",
        validator=_validate_content_flow_payload,
    )
)


def _decode_js_string(value: str) -> str:
    text = str(value or "")

    def replace_unicode(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    def replace_hex(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    text = re.sub(r"\\u([0-9a-fA-F]{4})", replace_unicode, text)
    text = re.sub(r"\\x([0-9a-fA-F]{2})", replace_hex, text)
    text = (
        text.replace("\\/", "/")
        .replace("\\'", "'")
        .replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\r", "\n")
        .replace("\\t", "\t")
    )
    return html.unescape(text).strip()


class _WechatArticleParser(HTMLParser):
    BLOCK_TAGS = {
        "address",
        "article",
        "blockquote",
        "br",
        "div",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
        "ol",
    }
    TEXT_BLOCK_TAGS = {"blockquote", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "td", "th"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_content = False
        self._content_depth = 0
        self._skip_depth = 0
        self._parts: list[str] = []
        self._current_block_tag = ""
        self._current_block_parts: list[str] = []
        self.blocks: list[dict[str, str]] = []
        self.image_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if attr_map.get("id") == "js_content":
            self._in_content = True
            self._content_depth = 1
            self._append_newline()
            return
        if not self._in_content:
            return
        self._content_depth += 1
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in self.BLOCK_TAGS:
            self._append_newline()
        if not self._skip_depth and tag in self.TEXT_BLOCK_TAGS and not self._current_block_tag:
            self._current_block_tag = tag
            self._current_block_parts = []
        if tag == "img":
            for key in ("data-src", "data-original", "src"):
                url = attr_map.get(key, "").strip()
                if url:
                    self.image_urls.append(url)
                    self.blocks.append({"type": "image", "tag": tag, "src": url, "text": ""})
                    break

    def handle_endtag(self, tag: str) -> None:
        if not self._in_content:
            return
        tag = tag.lower()
        if tag in self.BLOCK_TAGS:
            self._append_newline()
        if tag == self._current_block_tag:
            self._flush_current_block()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        self._content_depth -= 1
        if self._content_depth <= 0:
            self._in_content = False
            self._content_depth = 0
            self._skip_depth = 0

    def handle_data(self, data: str) -> None:
        if self._in_content and not self._skip_depth:
            text = str(data or "").strip()
            if text:
                if self._current_block_tag:
                    self._current_block_parts.append(text)
                self._parts.append(text)

    def body_text(self) -> str:
        block_lines = [block["text"] for block in self.blocks if block.get("text")]
        return "\n".join(block_lines or self._parts)

    def _append_newline(self) -> None:
        if self._parts and self._parts[-1] != "\n":
            self._parts.append("\n")

    def _flush_current_block(self) -> None:
        text = re.sub(r"\s+", " ", " ".join(self._current_block_parts)).strip()
        if text:
            self.blocks.append({"type": self._block_type(self._current_block_tag), "tag": self._current_block_tag, "text": text})
        self._current_block_tag = ""
        self._current_block_parts = []

    @staticmethod
    def _block_type(tag: str) -> str:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            return "heading"
        if tag == "li":
            return "list_item"
        if tag in {"td", "th"}:
            return "table_cell"
        if tag == "blockquote":
            return "quote"
        if tag == "figcaption":
            return "caption"
        return "paragraph"


class ContentFlowClient:
    def __init__(self, base_url: str, poll_interval_seconds: float = 0.5, poll_attempts: int = 20, workspace_root: str | Path = "."):
        self.base_url = base_url.rstrip("/")
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_attempts = poll_attempts
        self.workspace_root = Path(workspace_root)
        self.session = requests.Session()
        self.session.trust_env = False

    def _raw_marker_dir(self) -> Path:
        return ensure_dir(self.workspace_root / "content_flow" / "raw")

    def analyze(self, url: str, *, poll_attempts: int | None = None) -> dict[str, Any]:
        marker = self._raw_marker_dir() / "last-selfmedia-link.txt"
        marker.write_text(url + "\n", encoding="utf-8")
        wechat_url = self._extract_wechat_article_url(url)
        if wechat_url:
            return self._analyze_wechat_article(wechat_url)
        return self._run_job("/api/analyze", url, poll_attempts=poll_attempts)

    def download_video(self, url: str) -> dict[str, Any]:
        marker = self._raw_marker_dir() / "last-video-link.txt"
        marker.write_text(url + "\n", encoding="utf-8")
        return self._run_job("/api/video", url)

    def _analysis_has_structured_content(self, analysis: dict[str, Any]) -> bool:
        return not analysis_user_field_contract_issue(analysis)

    def _load_analysis_file(self, path: str | Path) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.is_file() or file_path.stat().st_size <= 0:
            return {}
        try:
            loaded = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _analysis_candidate_paths(self, payload: dict[str, Any]) -> list[Path]:
        candidates: list[Path] = []
        analysis_path = str(payload.get("analysis_path") or "")
        if analysis_path:
            candidates.append(Path(analysis_path))
        media_dir = str(payload.get("media_dir") or "")
        if media_dir:
            inferred_path = Path(media_dir) / "analysis.json"
            if payload.get("job_id") or inferred_path.is_file():
                candidates.append(inferred_path)

        deduped: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)
        return deduped

    def _read_optional_text(self, path: str | Path) -> str:
        if not path:
            return ""
        file_path = Path(path)
        if not file_path.is_file():
            return ""
        try:
            return file_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _platform_from_url(self, url: str) -> str:
        lower = (url or "").lower()
        if "mp.weixin.qq.com" in lower:
            return "公众号"
        if "douyin.com" in lower or "iesdouyin.com" in lower:
            return "抖音"
        if "xiaohongshu.com" in lower or "xhslink.com" in lower or "xhslink.cn" in lower:
            return "小红书"
        if "tiktok.com" in lower:
            return "TikTok"
        if "kuaishou.com" in lower or "gifshow.com" in lower:
            return "快手"
        if "bilibili.com" in lower or "b23.tv" in lower:
            return "B站"
        if "youtube.com" in lower or "youtu.be" in lower:
            return "YouTube"
        return ""

    @staticmethod
    def _extract_wechat_article_url(text: str) -> str:
        for match in re.finditer(r"https?://[^\s<>'\"，。；、）)\]】]+", text or ""):
            url = match.group(0).rstrip("，。；、.）)]】")
            host = urlparse(url).netloc.lower()
            if host == "mp.weixin.qq.com" or host.endswith(".mp.weixin.qq.com"):
                return url
        return ""

    def _wechat_article_dir(self, url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        return ensure_dir(self.workspace_root / "content_flow" / "wechat_articles" / digest)

    def _analyze_wechat_article(self, url: str) -> dict[str, Any]:
        media_dir = self._wechat_article_dir(url)
        fetch_started = time.monotonic()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://mp.weixin.qq.com/",
        }
        try:
            fetch_timeout = max(1.0, float(os.getenv("WECHAT_ARTICLE_FETCH_TIMEOUT_SECONDS", "20")))
            response = self.session.get(url, headers=headers, timeout=fetch_timeout)
            response.raise_for_status()
        except Exception as exc:
            return {
                "status": "pending_manual",
                "error_code": "WECHAT_ARTICLE_FETCH_FAILED",
                "reason": f"公众号图文抓取失败：{exc}",
                "stage": "source_fetch",
                "detail": "未取得可供正文提取的公众号页面，因此未调用 LLM，也未写入知识表。",
                "action": "请确认链接可公开访问后重试；若微信要求验证，请提供可读取的正文或其他公开来源。",
                "diagnostics": {
                    "fetch_elapsed_ms": round((time.monotonic() - fetch_started) * 1000),
                },
                "media_dir": str(media_dir),
                "media_type": "article",
            }

        raw_html = response.text or ""
        (media_dir / "article.html").write_text(raw_html, encoding="utf-8")
        fetch_elapsed_ms = round((time.monotonic() - fetch_started) * 1000)
        extraction_started = time.monotonic()
        article = self._parse_wechat_article_html(raw_html)
        extraction_elapsed_ms = round((time.monotonic() - extraction_started) * 1000)
        body_text = str(article.get("body_text") or "").strip()
        title = str(article.get("title") or "").strip()
        diagnostics = {
            "fetch_elapsed_ms": fetch_elapsed_ms,
            "extraction_elapsed_ms": extraction_elapsed_ms,
            "source_layout": str(article.get("source_layout") or "unknown"),
            "extracted_characters": len(body_text),
            "extracted_blocks": len(article.get("blocks") or []),
            "source_image_count": len(article.get("image_urls") or []),
        }
        if not body_text:
            reason = "公众号页面未包含可提取正文"
            error_code = "WECHAT_ARTICLE_BODY_EMPTY"
            detail = "页面已抓取，但没有发现完整正文来源数据；未调用 LLM，也未写入知识表。"
            action = "请确认文章仍可公开访问，或提供正文、截图等可读取来源后重试。"
            if "环境异常" in raw_html or "完成验证后即可继续访问" in raw_html or "secitptpage/verify" in raw_html:
                reason = "公众号页面要求环境验证，当前机器无法直接抓取正文"
                error_code = "WECHAT_ARTICLE_VERIFICATION_REQUIRED"
                detail = "微信返回了环境验证页面，而不是文章正文；未调用 LLM，也未写入知识表。"
                action = "请先在微信中完成访问验证，或提供可公开读取的正文来源后重试。"
            return {
                "status": "pending_manual",
                "error_code": error_code,
                "reason": reason,
                "stage": "source_extraction",
                "detail": detail,
                "action": action,
                "diagnostics": diagnostics,
                "media_dir": str(media_dir),
                "media_type": "article",
            }

        caption_path = media_dir / "caption.txt"
        caption_path.write_text(body_text + "\n", encoding="utf-8")
        structure_path = media_dir / "structure.json"
        structure_path.write_text(json.dumps(article.get("blocks") or [], ensure_ascii=False, indent=2), encoding="utf-8")
        analysis_path = media_dir / "analysis.json"
        image_download = self._download_wechat_images(article.get("image_sources") or [], media_dir, url)
        image_paths = image_download["image_paths"]
        diagnostics.update(
            {
                "expected_source_image_count": image_download["expected_count"],
                "downloaded_source_image_count": len(image_paths),
                "failed_source_image_count": len(image_download["failures"]),
            }
        )
        if image_download["failures"]:
            analysis_path.write_text(
                json.dumps(
                    {
                        "analysis_status": "source_image_download_incomplete",
                        "source_url": url,
                        "source_image_manifest": image_download["images"],
                        "source_image_failures": image_download["failures"],
                        "source_diagnostics": diagnostics,
                    }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {
                "status": "pending_manual",
                "error_code": "WECHAT_ARTICLE_IMAGE_DOWNLOAD_INCOMPLETE",
                "reason": (
                    f"公众号图集下载不完整：应保存 {image_download['expected_count']} 张，"
                    f"实际保存 {len(image_paths)} 张，失败 {len(image_download['failures'])} 张"
                ),
                "stage": "source_extraction",
                "detail": "页面已提供完整图集清单，但至少一张图片未成功取得原始文件；未调用 LLM，也未写入知识表。",
                "action": "请稍后重试；持续失败时请提供原图或可公开访问的图集来源。",
                "diagnostics": diagnostics,
                "media_dir": str(media_dir),
                "analysis_path": str(analysis_path),
                "caption_path": str(caption_path),
                "caption": body_text,
                "structure_path": str(structure_path),
                "image_paths": image_paths,
                "media_type": "article",
            }
        ocr_path = media_dir / "ocr.txt"
        image_ocr = ""
        ocr_diagnostics: dict[str, Any] = {}
        requires_gallery_ocr = any(
            isinstance(source, dict) and source.get("source") == "picture_page_info_list"
            for source in article.get("image_sources") or []
        )
        if requires_gallery_ocr:
            ocr_result = self._extract_wechat_image_ocr(image_paths, ocr_path)
            image_ocr = str(ocr_result.get("text") or "")
            ocr_diagnostics = {
                "expected_source_image_ocr_count": ocr_result["expected_count"],
                "completed_source_image_ocr_count": ocr_result["completed_count"],
                "failed_source_image_ocr_count": len(ocr_result["failures"]),
            }
            diagnostics.update(ocr_diagnostics)
            if ocr_result["failures"]:
                analysis_path.write_text(
                    json.dumps(
                        {
                            "analysis_status": "source_image_ocr_incomplete",
                            "source_url": url,
                            "source_image_manifest": image_download["images"],
                            "source_image_ocr_failures": ocr_result["failures"],
                            "source_diagnostics": diagnostics,
                        }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return {
                    "status": "pending_manual",
                    "error_code": "WECHAT_ARTICLE_IMAGE_OCR_INCOMPLETE",
                    "reason": (
                        f"公众号图集 OCR 不完整：应识别 {ocr_result['expected_count']} 张，"
                        f"实际识别 {ocr_result['completed_count']} 张，失败 {len(ocr_result['failures'])} 张"
                    ),
                    "stage": "source_extraction",
                    "detail": "图集文件已下载，但无法从全部页面取得完整 OCR 正文；未调用 LLM，也未写入知识表。",
                    "action": "请稍后重试；持续失败时请提供原图或可复制的全文文本。",
                    "diagnostics": diagnostics,
                    "media_dir": str(media_dir),
                    "analysis_path": str(analysis_path),
                    "caption_path": str(caption_path),
                    "caption": body_text,
                    "structure_path": str(structure_path),
                    "image_paths": image_paths,
                    "ocr_path": str(ocr_path),
                    "media_type": "article",
                }
        structured_content = image_ocr or self._wechat_structured_article_text(article) or body_text
        tags = self._wechat_article_tags(raw_html, title, body_text)
        source_extraction_note = f"公众号图文正文提取完成，已保存 {len(image_paths)} 张正文图片。" if image_paths else "公众号图文正文提取完成，未下载到正文图片。"
        if image_ocr:
            source_extraction_note = f"{source_extraction_note} 图集 OCR 已按页面顺序提取。"
        analysis = {
            "title": title or self._compact_title(body_text) or "未命名公众号图文",
            "analysis_provider": "wechat-article-extractor",
            "analysis_status": "source_extracted_needs_llm_semantics",
            "platform": "公众号",
            "media_type": "article",
            "caption": body_text,
            "source_tags": tags,
            "source_extraction_note": source_extraction_note,
            "source_layout": article.get("source_layout") or "unknown",
            "source_diagnostics": diagnostics,
            "source_image_manifest": image_download["images"],
            "image_ocr": image_ocr,
            "ocr_path": str(ocr_path) if image_ocr else "",
            "article_structure_path": str(structure_path),
            "article_structure": article.get("blocks") or [],
            "account_name": article.get("account_name") or "",
            "author": article.get("author") or "",
            "publish_time": article.get("publish_time") or "",
        }
        content_cleaning = self._clean_wechat_article_content(
            str(analysis["title"]),
            structured_content,
            source_kind="gallery_ocr" if image_ocr else "article_body",
        )
        if content_cleaning.get("status") != "done":
            analysis.update(
                {
                    "analysis_status": "needs_model_rerun",
                    "incomplete_reason": "wechat_article_llm_cleaning_required",
                    "semantic_failure_reason": str(content_cleaning.get("reason") or "公众号正文 LLM 清洗未完成"),
                }
            )
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "status": "pending_manual",
                "error_code": "LLM_SEMANTIC_PERSISTENCE_REQUIRED",
                "reason": f"wechat_article_llm_cleaning_required:{analysis['semantic_failure_reason']}",
                "stage": "semantic_analysis",
                "detail": "公众号来源文本已取得，但 LLM 未返回可入库的保真清洗全文。",
                "action": "请稍后重试；持续失败时检查 content_cleaner 模型配置和结构化输出。",
                "diagnostics": diagnostics,
                "media_dir": str(media_dir),
                "analysis_path": str(analysis_path),
                "caption_path": str(caption_path),
                "caption": body_text,
                "structure_path": str(structure_path),
                "image_paths": image_paths,
                "ocr_path": str(ocr_path) if image_ocr else "",
                "image_ocr": image_ocr,
                "media_type": "article",
                "analysis": analysis,
            }
        analysis["full_content"] = str(content_cleaning["full_content"])
        analysis["content_cleaning_provider"] = str(content_cleaning.get("postprocess_provider") or "")
        analysis["content_cleaning_model"] = str(content_cleaning.get("postprocess_model") or "")
        caption_cleaning = self._clean_wechat_article_content(
            str(analysis["title"]),
            body_text,
            source_kind="platform_caption",
        )
        if caption_cleaning.get("status") != "done":
            analysis.update(
                {
                    "analysis_status": "needs_model_rerun",
                    "incomplete_reason": "wechat_article_llm_caption_cleaning_required",
                    "semantic_failure_reason": str(caption_cleaning.get("reason") or "公众号平台文案 LLM 清洗未完成"),
                }
            )
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "status": "pending_manual",
                "error_code": "LLM_SEMANTIC_PERSISTENCE_REQUIRED",
                "reason": f"wechat_article_llm_caption_cleaning_required:{analysis['semantic_failure_reason']}",
                "stage": "semantic_analysis",
                "detail": "公众号平台文案已取得，但 LLM 未返回可入库的保真清洗文案。",
                "action": "请稍后重试；持续失败时检查 content_cleaner 模型配置和结构化输出。",
                "diagnostics": diagnostics,
                "media_dir": str(media_dir),
                "analysis_path": str(analysis_path),
                "caption_path": str(caption_path),
                "caption": body_text,
                "structure_path": str(structure_path),
                "image_paths": image_paths,
                "ocr_path": str(ocr_path) if image_ocr else "",
                "image_ocr": image_ocr,
                "media_type": "article",
                "analysis": analysis,
            }
        analysis["work_copy"] = str(caption_cleaning["full_content"])
        analysis["caption_cleaning_provider"] = str(caption_cleaning.get("postprocess_provider") or "")
        analysis["caption_cleaning_model"] = str(caption_cleaning.get("postprocess_model") or "")
        semantic_analysis = self._analyze_wechat_article_semantics(
            url=url,
            article=article,
            base_analysis=analysis,
            image_count=len(image_paths),
        )
        if semantic_analysis.get("status") != "done":
            analysis.update(
                {
                    "analysis_status": "needs_model_rerun",
                    "incomplete_reason": "wechat_article_semantic_analysis_required",
                    "semantic_failure_reason": str(semantic_analysis.get("reason") or "公众号图文 LLM 结构化分析未完成"),
                }
            )
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "status": "pending_manual",
                "error_code": "LLM_SEMANTIC_PERSISTENCE_REQUIRED",
                "reason": f"wechat_article_semantic_analysis_required:{analysis['semantic_failure_reason']}",
                "stage": "semantic_analysis",
                "detail": "公众号正文已经取得，但 LLM 未返回满足知识入库契约的结构化字段。",
                "action": "请稍后重试；持续失败时检查 media_analysis 模型配置和结构化输出。",
                "diagnostics": diagnostics,
                "media_dir": str(media_dir),
                "analysis_path": str(analysis_path),
                "caption_path": str(caption_path),
                "caption": body_text,
                "structure_path": str(structure_path),
                "image_paths": image_paths,
                "ocr_path": str(ocr_path) if image_ocr else "",
                "image_ocr": image_ocr,
                "media_type": "article",
                "analysis": analysis,
            }

        semantic_analysis.pop("status", None)
        llm_tags = semantic_analysis.get("tags")
        if isinstance(llm_tags, list):
            merged_tags = [str(item).strip() for item in llm_tags if str(item).strip()]
        else:
            merged_tags = []
        analysis.update(
            {
                **semantic_analysis,
                "title": self._semantic_text(semantic_analysis.get("title")),
                "work_copy": str(analysis.get("work_copy") or "").strip(),
                "full_content": str(analysis.get("full_content") or structured_content).strip(),
                "tags": merged_tags,
                "analysis_provider": "wechat-article-llm",
                "source_analysis_provider": "wechat-article-extractor",
                "analysis_status": "llm_structured",
                "semantic_persistence_version": LLM_CLEANED_USER_FIELDS_VERSION,
                "platform": "公众号",
                "media_type": "article",
                "caption": body_text,
                "source_tags": tags,
                "source_extraction_note": source_extraction_note,
                "source_image_manifest": image_download["images"],
                "image_ocr": image_ocr,
                "ocr_path": str(ocr_path) if image_ocr else "",
                "article_structure_path": str(structure_path),
                "article_structure": article.get("blocks") or [],
                "account_name": article.get("account_name") or "",
                "author": article.get("author") or "",
                "publish_time": article.get("publish_time") or "",
                "source_url": url,
            }
        )
        analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "done",
            "media_dir": str(media_dir),
            "analysis_path": str(analysis_path),
            "caption_path": str(caption_path),
            "caption": body_text,
            "structure_path": str(structure_path),
            "image_paths": image_paths,
            "ocr_path": str(ocr_path) if image_ocr else "",
            "image_ocr": image_ocr,
            "media_type": "article",
            "analysis": analysis,
            "diagnostics": diagnostics,
        }

    @staticmethod
    def _extract_wechat_image_ocr(image_paths: list[str], ocr_path: Path) -> dict[str, Any]:
        expected_paths = [Path(path) for path in image_paths if Path(path).is_file()]
        try:
            if ocr_path.is_file():
                ocr_path.unlink()
            text = _extract_image_ocr([str(path) for path in expected_paths], str(ocr_path), lambda *_: None)
        except Exception as exc:
            return {
                "text": "",
                "expected_count": len(expected_paths),
                "completed_count": 0,
                "failures": [f"{path.name}: {exc}" for path in expected_paths],
            }
        completed_names = set(re.findall(r"^##\s*\d+\s+(.+?)\s*$", text or "", flags=re.M))
        failures = [path.name for path in expected_paths if path.name not in completed_names]
        return {
            "text": text,
            "expected_count": len(expected_paths),
            "completed_count": len(expected_paths) - len(failures),
            "failures": failures,
        }

    def _clean_wechat_article_content(self, title: str, source_text: str, *, source_kind: str) -> dict[str, Any]:
        prompt = (
            "你是 OpenClaw 公众号来源文本保真清洗器。只输出合法 JSON object，不要 Markdown，不要解释。\n"
            "必须输出 full_content。只清洗输入来源文本：去除明确乱码、随机英文碎片、页眉页脚、装饰符号和重复噪声，"
            "修复明显断句；保留原文页面顺序、信息覆盖和表达。禁止总结、缩写、扩写、重写观点或加入来源中没有的事实。\n"
            "不能确认是否为噪声时必须保留。"
        )
        timeout = max(1.0, float(os.getenv("WECHAT_ARTICLE_OCR_CLEAN_TIMEOUT_SECONDS", "900")))
        result = self._call_profile_provider_json(
            "content_cleaner",
            prompt,
            json.dumps({"title": title, "source_kind": source_kind, "source_text": source_text}, ensure_ascii=False),
            "公众号来源文本 LLM 清洗",
            timeout_seconds=timeout,
            max_retries=0,
            thinking="medium",
        )
        if result.get("status") != "done":
            return result
        full_content = str(result.get("full_content") or "").strip()
        if not full_content:
            return {"status": "pending_manual", "reason": "公众号来源文本 LLM 清洗缺少 full_content"}
        return {**result, "full_content": full_content}

    def _clean_wechat_gallery_ocr(self, title: str, image_ocr: str) -> dict[str, Any]:
        return self._clean_wechat_article_content(title, image_ocr, source_kind="gallery_ocr")

    def _analyze_wechat_article_semantics(
        self,
        *,
        url: str,
        article: dict[str, Any],
        base_analysis: dict[str, Any],
        image_count: int,
    ) -> dict[str, Any]:
        image_ocr = str(base_analysis.get("image_ocr") or "").strip()
        prompt = (
            "你是 OpenClaw 自媒体知识库的公众号图文结构化分析器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "只基于提供的公众号正文、结构、图片 OCR 和元数据分析；不要访问外部链接，不要编造图片内容。\n"
            "必须输出字段：title、summary、breakdown、hooks、action_plan、hidden_info、visual_cues、transferable_expression、target_audience、pain_point、primary_category、secondary_category、tags、questions、open_questions、risks。\n"
            "primary_category 必须是以下之一：AI/工具、商业/产品、运营/管理、学习/认知、健康/运动、财经/投资、法律/政策、生活/效率、科技/科学、人物/案例。\n"
            "secondary_category 使用 1-3 个中文短分类；tags 使用 3-8 个短标签。\n"
            "cleaned_full_content 是已完成 LLM 保真清洗的全文，分析时以它为主要文本依据。\n"
            "platform_caption 已由独立 LLM 清洗器处理，只作为分析背景，不要在 JSON 中输出或改写平台文案。\n"
            "图片 OCR 存在时，它是图集中文字的唯一事实来源；可据此分析，不得补写 OCR 中没有的图片文字。\n"
            "visual_cues 只能描述正文结构、OCR 文字和已知图片数量，不能声称看到了 OCR 中没有的图片具体内容。\n"
            "如果正文证据不足，仍输出 JSON，但把不确定项写入 open_questions 或 risks；不要用模板兜底。"
        )
        user_content = json.dumps(
            {
                "source_url": url,
                "extracted_title": base_analysis.get("title") or "",
                "account_name": article.get("account_name") or "",
                "author": article.get("author") or "",
                "publish_time": article.get("publish_time") or "",
                "source_tags": base_analysis.get("source_tags") or [],
                "image_count": image_count,
                "body_text": str(article.get("body_text") or "")[:50000],
                "cleaned_full_content": str(base_analysis.get("full_content") or "")[:100000],
                "image_ocr": image_ocr[:100000],
                "article_structure": article.get("blocks") or [],
            },
            ensure_ascii=False,
        )
        semantic_timeout = max(1.0, float(os.getenv("WECHAT_ARTICLE_SEMANTIC_TIMEOUT_SECONDS", "180")))
        result = self._call_profile_provider_json(
            "media_analysis",
            prompt,
            user_content,
            "公众号图文结构化分析",
            timeout_seconds=semantic_timeout,
        )
        if result.get("status") != "done":
            return result
        text_fields = ("title",)
        missing = [field for field in text_fields if not self._semantic_text(result.get(field))]
        missing.extend(
            field
            for field in ("summary", "primary_category", "secondary_category")
            if not self._semantic_value_present(result.get(field))
        )
        if missing:
            return {
                "status": "pending_manual",
                "reason": "公众号图文结构化分析缺少必需字段：" + "、".join(missing),
            }
        return result

    @staticmethod
    def _semantic_value_present(value: Any) -> bool:
        if value in (None, "", [], {}):
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return any(ContentFlowClient._semantic_value_present(item) for item in value)
        if isinstance(value, dict):
            return any(ContentFlowClient._semantic_value_present(item) for item in value.values())
        return True

    @staticmethod
    def _semantic_text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def _parse_wechat_article_html(self, raw_html: str) -> dict[str, Any]:
        embedded_content = self._wechat_cgi_data_property(raw_html, "content_noencode")
        has_js_content = bool(re.search(r"\bid=['\"]js_content['\"]", raw_html or "", flags=re.I))
        source_layout = "cgi_data_content" if embedded_content else ("js_content" if has_js_content else "missing")
        parser = _WechatArticleParser()
        try:
            if embedded_content:
                has_markup = bool(re.search(r"<[a-zA-Z][^>]*>", embedded_content))
                source_fragment = embedded_content if has_markup else html.escape(embedded_content)
                content_html = f'<div id="js_content">{source_fragment}</div>'
            else:
                content_html = raw_html or ""
            parser.feed(content_html)
        except Exception:
            pass
        body_text = self._normalize_wechat_article_text(parser.body_text())
        blocks = self._normalize_wechat_blocks(parser.blocks)
        if body_text and not blocks:
            blocks = [
                {"type": "paragraph", "tag": "p", "text": paragraph}
                for paragraph in re.split(r"\n\s*\n|\n", body_text)
                if paragraph.strip()
            ]
        title = (
            self._wechat_cgi_data_property(raw_html, "title")
            or self._wechat_js_var(raw_html, "msg_title")
            or self._wechat_meta(raw_html, "og:title")
            or self._wechat_meta(raw_html, "twitter:title")
        )
        account_name = (
            self._wechat_cgi_data_property(raw_html, "nick_name")
            or self._wechat_cgi_data_property(raw_html, "nickname")
            or self._wechat_js_var(raw_html, "nickname")
            or self._wechat_js_var(raw_html, "user_name")
            or self._wechat_meta(raw_html, "author")
        )
        author = self._wechat_cgi_data_property(raw_html, "author") or self._wechat_js_var(raw_html, "author")
        publish_time = (
            self._wechat_cgi_data_property(raw_html, "create_time")
            or self._wechat_cgi_data_property(raw_html, "ori_create_time")
            or self._wechat_js_var(raw_html, "publish_time")
            or self._wechat_js_var(raw_html, "oriCreateTime")
        )
        picture_sources = self._wechat_picture_page_info_sources(raw_html)
        image_sources = picture_sources or [
            {"url": image_url, "source": "js_content"}
            for image_url in parser.image_urls
        ]
        cover_url = self._wechat_cgi_data_property(raw_html, "cdn_url")
        if not image_sources and cover_url:
            image_sources.append({"url": cover_url, "source": "cgi_data_cover"})
        image_urls = [str(source.get("url") or "") for source in image_sources if str(source.get("url") or "")]
        if picture_sources:
            blocks.extend(
                {
                    "type": "image",
                    "tag": "picture_page_info_list",
                    "src": str(source["url"]),
                }
                for source in picture_sources
            )
        return {
            "title": self._clean_wechat_meta_text(title),
            "account_name": self._clean_wechat_meta_text(account_name),
            "author": self._clean_wechat_meta_text(author),
            "publish_time": self._normalize_wechat_publish_time(publish_time),
            "body_text": body_text,
            "blocks": blocks,
            "image_urls": image_urls,
            "image_sources": image_sources,
            "source_layout": source_layout,
        }

    @staticmethod
    def _wechat_picture_page_info_sources(raw_html: str) -> list[dict[str, Any]]:
        assignment = re.search(r"\bwindow\.picture_page_info_list\s*=\s*\[", raw_html or "")
        if not assignment:
            return []
        open_index = (raw_html or "").find("[", assignment.start())
        if open_index < 0:
            return []

        objects: list[str] = []
        array_depth = 0
        object_depth = 0
        object_start = -1
        quote = ""
        escaped = False
        for index in range(open_index, len(raw_html or "")):
            char = raw_html[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                continue
            if char in {"'", '"', "`"}:
                quote = char
                continue
            if char == "[":
                array_depth += 1
                continue
            if char == "]":
                array_depth -= 1
                if array_depth == 0:
                    break
                continue
            if array_depth != 1:
                continue
            if char == "{":
                if object_depth == 0:
                    object_start = index
                object_depth += 1
                continue
            if char == "}" and object_depth:
                object_depth -= 1
                if object_depth == 0 and object_start >= 0:
                    objects.append(raw_html[object_start : index + 1])

        sources: list[dict[str, Any]] = []
        for item in objects:
            url_match = re.search(r"\bcdn_url\s*:\s*(['\"])((?:\\.|(?!\1).)*)\1", item, flags=re.S)
            if not url_match:
                continue
            url = _decode_js_string(url_match.group(2))
            if not url:
                continue
            width_match = re.search(r"\bwidth\s*:\s*'?([0-9]+)'?\s*(?:\*\s*1)?", item)
            height_match = re.search(r"\bheight\s*:\s*'?([0-9]+)'?\s*(?:\*\s*1)?", item)
            source: dict[str, Any] = {"url": url, "source": "picture_page_info_list"}
            if width_match:
                source["width"] = int(width_match.group(1))
            if height_match:
                source["height"] = int(height_match.group(1))
            sources.append(source)
        return sources

    @staticmethod
    def _wechat_cgi_data_property(raw_html: str, name: str) -> str:
        script_body = ""
        for script in re.findall(r"<script\b[^>]*>(.*?)</script>", raw_html or "", flags=re.I | re.S):
            if "window.cgiDataNew" in script:
                script_body = script
                break
        if not script_body:
            return ""
        pattern = re.compile(
            rf"\b{re.escape(name)}\s*:\s*(['\"])((?:\\.|(?!\1).)*)\1",
            flags=re.S,
        )
        match = pattern.search(script_body)
        if not match:
            return ""
        return _decode_js_string(match.group(2))

    @staticmethod
    def _wechat_js_var(raw_html: str, name: str) -> str:
        pattern = re.compile(rf"\bvar\s+{re.escape(name)}\s*=\s*(['\"])(.*?)\1", flags=re.S)
        match = pattern.search(raw_html or "")
        if not match:
            return ""
        return _decode_js_string(match.group(2))

    @staticmethod
    def _wechat_meta(raw_html: str, name: str) -> str:
        for tag in re.findall(r"<meta\b[^>]*>", raw_html or "", flags=re.I):
            if not re.search(rf"\b(?:property|name)=['\"]{re.escape(name)}['\"]", tag, flags=re.I):
                continue
            match = re.search(r"\bcontent=(['\"])(.*?)\1", tag, flags=re.I | re.S)
            if match:
                return html.unescape(match.group(2)).strip()
        return ""

    @staticmethod
    def _clean_wechat_meta_text(value: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()

    @staticmethod
    def _normalize_wechat_article_text(value: str) -> str:
        text = html.unescape(str(value or "")).replace("\xa0", " ")
        lines: list[str] = []
        previous_blank = False
        for raw_line in text.splitlines():
            line = re.sub(r"[ \t\r\f\v]+", " ", raw_line).strip()
            if not line:
                if lines and not previous_blank:
                    lines.append("")
                previous_blank = True
                continue
            lines.append(line)
            previous_blank = False
        return "\n".join(lines).strip()

    def _normalize_wechat_blocks(self, blocks: Any) -> list[dict[str, str]]:
        if not isinstance(blocks, list):
            return []
        normalized: list[dict[str, str]] = []
        previous_key = ""
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "paragraph").strip() or "paragraph"
            tag = str(block.get("tag") or "").strip()
            src = html.unescape(str(block.get("src") or "")).strip()
            text = self._normalize_wechat_article_text(str(block.get("text") or ""))
            if block_type != "image" and not text:
                continue
            key = f"{block_type}\n{tag}\n{text}\n{src}"
            if key == previous_key:
                continue
            previous_key = key
            item = {"type": block_type, "tag": tag}
            if text:
                item["text"] = text
            if src:
                item["src"] = src
            normalized.append(item)
        return normalized

    @staticmethod
    def _normalize_wechat_publish_time(value: str) -> str:
        text = re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()
        if re.fullmatch(r"\d{10}", text):
            dt = datetime.fromtimestamp(int(text), tz=timezone(timedelta(hours=8)))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        if re.fullmatch(r"\d{13}", text):
            dt = datetime.fromtimestamp(int(text) / 1000, tz=timezone(timedelta(hours=8)))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return text

    def _wechat_structured_article_text(self, article: dict[str, Any]) -> str:
        blocks = article.get("blocks") if isinstance(article.get("blocks"), list) else []
        if not blocks:
            return ""
        lines: list[str] = []
        image_index = 0
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            text = str(block.get("text") or "").strip()
            if block_type == "image":
                image_index += 1
                lines.append(f"[图片 {image_index}]")
                continue
            if not text:
                continue
            if block_type == "heading":
                tag = str(block.get("tag") or "h2")
                level = int(tag[1]) if re.fullmatch(r"h[1-6]", tag) else 2
                lines.append(f"{'#' * max(2, min(level, 4))} {text}")
            elif block_type == "list_item":
                lines.append(f"- {text}")
            elif block_type == "quote":
                lines.append(f"> {text}")
            elif block_type == "table_cell":
                lines.append(f"| {text} |")
            elif block_type == "caption":
                lines.append(f"图注：{text}")
            else:
                lines.append(text)
        return "\n\n".join(lines).strip()

    def _wechat_article_outline(self, article: dict[str, Any]) -> list[str]:
        blocks = article.get("blocks") if isinstance(article.get("blocks"), list) else []
        headings = [
            str(block.get("text") or "").strip()
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "heading" and str(block.get("text") or "").strip()
        ]
        if headings:
            return headings[:20]
        body_text = str(article.get("body_text") or "")
        lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        candidates = [line for line in lines if 4 <= len(line) <= 32 and not line.endswith(("。", "，", ",", "."))]
        return candidates[:12]

    def _wechat_article_tags(self, raw_html: str, title: str, body_text: str) -> list[str]:
        keyword_text = self._wechat_meta(raw_html, "keywords")
        tags = [item.strip() for item in re.split(r"[,，、/|｜\s]+", keyword_text) if item.strip()]
        if not tags:
            tags = self._extract_hashtags(body_text)
        if not tags:
            tags = [item for item in re.split(r"[\s,，、/|｜:：]+", title or "") if 1 < len(item) <= 12][:5]
        deduped: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            clean = tag.strip("#＃")
            if clean and clean not in seen:
                seen.add(clean)
                deduped.append(clean)
            if len(deduped) >= 8:
                break
        return deduped

    def _wechat_article_summary(self, title: str, body_text: str, article: dict[str, Any]) -> list[str]:
        first_lines = [line for line in body_text.splitlines() if line.strip()]
        lead = self._compact_title(first_lines[0] if first_lines else body_text, limit=120)
        source = str(article.get("account_name") or article.get("author") or "公众号").strip()
        summary = [f"公众号图文《{title or '未命名'}》来自 {source}，正文已提取入库。"]
        if lead:
            summary.append(f"开头信息：{lead}")
        if article.get("publish_time"):
            summary.append(f"发布时间：{article['publish_time']}")
        return summary

    @staticmethod
    def _wechat_image_metadata(content: bytes) -> tuple[str, int, int] | None:
        if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
            width = int.from_bytes(content[16:20], "big")
            height = int.from_bytes(content[20:24], "big")
            return ("png", width, height) if width and height and content.endswith(b"IEND\xaeB`\x82") else None
        if content.startswith((b"GIF87a", b"GIF89a")) and len(content) >= 10:
            width = int.from_bytes(content[6:8], "little")
            height = int.from_bytes(content[8:10], "little")
            return ("gif", width, height) if width and height and content.endswith(b";") else None
        if not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
            return None
        index = 2
        sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
        while index + 3 < len(content):
            if content[index] != 0xFF:
                index += 1
                continue
            while index < len(content) and content[index] == 0xFF:
                index += 1
            if index >= len(content):
                return None
            marker = content[index]
            index += 1
            if marker in {0x01, 0xD8, 0xD9}:
                continue
            if index + 2 > len(content):
                return None
            segment_size = int.from_bytes(content[index : index + 2], "big")
            if segment_size < 2 or index + segment_size > len(content):
                return None
            if marker in sof_markers:
                if segment_size < 8:
                    return None
                height = int.from_bytes(content[index + 3 : index + 5], "big")
                width = int.from_bytes(content[index + 5 : index + 7], "big")
                return ("jpg", width, height) if width and height else None
            index += segment_size
        return None

    def _download_wechat_images(self, image_sources: Any, media_dir: Path, referer: str) -> dict[str, Any]:
        result: dict[str, Any] = {"image_paths": [], "expected_count": 0, "failures": [], "images": []}
        if not isinstance(image_sources, list):
            return result
        image_dir = ensure_dir(media_dir / "images")
        for stale_path in image_dir.glob("image-*"):
            if stale_path.is_file():
                stale_path.unlink()
        seen: set[str] = set()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger"
            ),
            "Referer": referer,
        }
        sources: list[dict[str, Any]] = []
        for raw_source in image_sources:
            source = dict(raw_source) if isinstance(raw_source, dict) else {"url": raw_source}
            url = html.unescape(str(source.get("url") or "")).strip()
            if not url or url.startswith("data:"):
                continue
            url = urljoin("https://mp.weixin.qq.com/", url)
            if url in seen:
                continue
            seen.add(url)
            source["url"] = url
            sources.append(source)

        result["expected_count"] = len(sources)
        fetch_timeout = max(1.0, float(os.getenv("WECHAT_ARTICLE_IMAGE_FETCH_TIMEOUT_SECONDS", "20")))
        attempts = max(1, min(3, int(os.getenv("WECHAT_ARTICLE_IMAGE_DOWNLOAD_ATTEMPTS", "2"))))
        max_bytes = max(1, int(os.getenv("WECHAT_ARTICLE_IMAGE_MAX_BYTES", str(25 * 1024 * 1024))))
        for source in sources:
            url = str(source["url"])
            content = b""
            response = None
            error = ""
            for attempt in range(attempts):
                try:
                    response = self.session.get(url, headers=headers, timeout=fetch_timeout)
                    response.raise_for_status()
                    content = response.content or b""
                    break
                except Exception as exc:
                    error = str(exc)
                    if attempt + 1 < attempts:
                        time.sleep(0.2)
            if not content:
                result["failures"].append({"url": url, "reason": f"下载失败：{error or '空响应'}"})
                continue
            if len(content) > max_bytes:
                result["failures"].append({"url": url, "reason": f"文件超过 {max_bytes} 字节限制"})
                continue
            metadata = self._wechat_image_metadata(content)
            if not metadata:
                result["failures"].append({"url": url, "reason": "响应不是完整、可识别的 PNG、GIF 或 JPEG 图片"})
                continue
            image_type, width, height = metadata
            expected_width = int(source.get("width") or 0)
            expected_height = int(source.get("height") or 0)
            if (expected_width and width < expected_width) or (expected_height and height < expected_height):
                result["failures"].append(
                    {
                        "url": url,
                        "reason": f"图片尺寸不足：取得 {width}x{height}，页面声明 {expected_width}x{expected_height}",
                    }
                )
                continue
            path = image_dir / f"image-{len(result['image_paths']) + 1:02d}.{image_type}"
            path.write_bytes(content)
            result["image_paths"].append(str(path))
            result["images"].append(
                {
                    "url": url,
                    "path": str(path),
                    "width": width,
                    "height": height,
                    "bytes": len(content),
                    "source": str(source.get("source") or ""),
                }
            )
        return result

    def _compact_title(self, value: str, *, limit: int = 42) -> str:
        text = re.sub(r"https?://\S+", " ", str(value or ""))
        text = re.sub(r"#\S+", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" -_，。:：|")
        if not text:
            return ""
        return text if len(text) <= limit else text[:limit].rstrip()

    def _extract_hashtags(self, text: str) -> list[str]:
        tags: list[str] = []
        for match in re.finditer(r"#([^#\s\[]{1,24})(?:\[话题\])?#?", text or ""):
            tag = match.group(1).strip()
            if tag and tag not in tags:
                tags.append(tag)
            if len(tags) >= 8:
                break
        return tags

    def _complete_analysis_payload(self, url: str, payload: dict[str, Any], *, wait: bool) -> dict[str, Any]:
        if str(payload.get("status") or "").strip().lower() in {"pending_manual", "failed", "error"}:
            payload["analysis_completion_checked"] = True
            return payload

        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
        if self._analysis_has_structured_content(analysis):
            payload["analysis_completion_checked"] = True
            return payload

        analysis_status = str(analysis.get("analysis_status") or "").strip().lower()
        if analysis_status and analysis_status not in {"needs_model_rerun", "source_extracted_needs_llm_semantics"}:
            wait = False

        already_checked = bool(payload.get("analysis_completion_checked"))
        candidate_paths = self._analysis_candidate_paths(payload)
        # If the upstream job timed out before returning paths, there is nothing
        # useful to poll here. Avoid an extra 900s apparent hang.
        if already_checked or not candidate_paths:
            wait = False

        deadline = time.monotonic() + max(0.0, float(os.getenv("CONTENT_FLOW_ANALYSIS_WAIT_SECONDS", "900"))) if wait else time.monotonic()
        poll_seconds = max(0.5, float(os.getenv("CONTENT_FLOW_ANALYSIS_POLL_SECONDS", "2")))
        while True:
            for path in candidate_paths:
                loaded = self._load_analysis_file(path)
                if not loaded:
                    continue
                payload["analysis"] = loaded
                payload["analysis_path"] = str(path)
                if self._analysis_has_structured_content(loaded):
                    payload["analysis_completion_checked"] = True
                    return payload
                analysis = loaded
                loaded_status = str(loaded.get("analysis_status") or "").strip().lower()
                if loaded_status and loaded_status not in {"needs_model_rerun", "source_extracted_needs_llm_semantics"}:
                    wait = False
            if not wait or time.monotonic() >= deadline:
                break
            time.sleep(poll_seconds)

        payload["analysis_completion_checked"] = True
        if not self._analysis_has_structured_content(analysis):
            contract_issue = analysis_user_field_contract_issue(analysis) if analysis else ""
            payload["status"] = "pending_manual"
            payload["error_code"] = "LLM_SEMANTIC_PERSISTENCE_REQUIRED"
            payload["reason"] = f"LLM_SEMANTIC_PERSISTENCE_REQUIRED:{contract_issue or 'content_flow_structured_analysis_required'}"
            payload["stage"] = "semantic_analysis"
            payload["detail"] = "来源内容已取得，但有效分析任务没有产出满足知识入库契约的结构化结果。"
            payload["action"] = "请重试分析；持续失败时检查分析任务状态、模型配置和 analysis.json 产物。"
            payload["analysis"] = analysis if isinstance(analysis, dict) else {}
        return payload

    def complete_analysis_payload(self, url: str, payload: dict[str, Any], *, wait: bool = False) -> dict[str, Any]:
        return self._complete_analysis_payload(url, payload, wait=wait)

    def _poll_attempts_for_endpoint(self, endpoint: str, poll_attempts: int | None) -> int:
        attempts = self.poll_attempts if poll_attempts is None else max(1, int(poll_attempts))
        if endpoint != "/api/analyze":
            return attempts

        wait_seconds = max(0.0, float(os.getenv("CONTENT_FLOW_ANALYSIS_WAIT_SECONDS", "900")))
        interval_seconds = max(0.1, float(self.poll_interval_seconds or 0.5))
        minimum_attempts = max(1, math.ceil(wait_seconds / interval_seconds))
        return max(attempts, minimum_attempts)

    def transcribe_file(self, audio_path: str, output_dir: str | Path) -> dict[str, Any]:
        source = Path(audio_path)
        if not source.is_file():
            return {"status": "pending_manual", "reason": f"录音文件不存在：{audio_path}"}

        out_dir = ensure_dir(output_dir)
        python_bin = CONTENT_FLOW_ROOT / ".venv" / "bin" / "python"
        if not python_bin.is_file():
            python_bin = Path(sys.executable)

        script = r'''
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
audio_path = Path(sys.argv[2])
out_dir = Path(sys.argv[3])
project_root = Path(sys.argv[4])
out_dir.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(project_root))
from selfmedia.ingest.content_flow.src.config import load_settings
from selfmedia.ingest.content_flow.src.transcriber import transcribe_audio

try:
    transcript = transcribe_audio(str(audio_path), load_settings(), raise_errors=True)
except Exception as exc:
    print(json.dumps({"status": "pending_manual", "reason": str(exc)}, ensure_ascii=False))
    raise SystemExit(0)

if not transcript:
    print(json.dumps({"status": "pending_manual", "reason": "ASR 未产出逐字稿"}, ensure_ascii=False))
    raise SystemExit(0)

transcript_path = out_dir / "transcript.txt"
transcript_path.write_text(transcript.strip() + "\n", encoding="utf-8")
print(json.dumps({
    "status": "done",
    "audio_path": str(audio_path),
    "media_dir": str(out_dir),
    "transcript_path": str(transcript_path),
}, ensure_ascii=False))
'''
        env = self._content_flow_env()
        timeout_seconds = self._transcription_timeout_seconds(env)
        try:
            proc = subprocess.run(
                [
                    str(python_bin),
                    "-c",
                    script,
                    str(CONTENT_FLOW_ROOT),
                    str(source),
                    str(out_dir),
                    str(SELFMEDIA_TOOLS_ROOT),
                ],
                text=True,
                capture_output=True,
                cwd=str(CONTENT_FLOW_ROOT),
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return {"status": "pending_manual", "reason": f"录音转写超时：超过 {int(exc.timeout or timeout_seconds)} 秒"}
        except OSError as exc:
            return {"status": "pending_manual", "reason": f"无法调用 content-flow 本地转写：{exc}"}

        parsed = self._parse_last_json_line(proc.stdout)
        if proc.returncode != 0:
            reason = self._clean_transcription_error(
                proc.stderr.strip() or proc.stdout.strip() or f"本地转写退出码 {proc.returncode}"
            )
            if parsed and parsed.get("reason"):
                reason = str(parsed["reason"])
            return {"status": "pending_manual", "reason": reason[-2000:]}
        if not parsed:
            return {"status": "pending_manual", "reason": "本地转写未返回 JSON 结果"}
        return parsed

    def summarize_dialogue_transcript(self, transcript: str, source_hint: str = "", artifact_dir: str | Path | None = None) -> dict[str, Any]:
        text = transcript.strip()
        if not text:
            return {"status": "pending_manual", "reason": "缺少逐字稿"}

        env = self._content_flow_env()
        prepared = self._prepare_role_aware_transcript(
            text,
            source_hint,
            env,
            artifact_dir=artifact_dir,
        )
        if prepared.get("status") != "done":
            return prepared
        result = self._summarize_dialogue_transcript_chunked(
            str(prepared.get("rewritten_transcript") or ""),
            source_hint,
            env,
            artifact_dir=artifact_dir,
            speaker_notes=list(prepared.get("speaker_registry") or []),
            labeled_transcript=list(prepared.get("labeled_transcript") or []),
        )
        role_artifacts = prepared.get("postprocess_artifacts")
        if isinstance(role_artifacts, dict) and role_artifacts:
            postprocess_artifacts = result.get("postprocess_artifacts")
            result["postprocess_artifacts"] = {
                **role_artifacts,
                **(postprocess_artifacts if isinstance(postprocess_artifacts, dict) else {}),
            }
        return result

    def _prepare_role_aware_transcript(
        self,
        text: str,
        source_hint: str,
        env: dict[str, str],
        *,
        artifact_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        sections = self._split_transcript_audio_sections(text)
        evidence = self._transcription_speaker_evidence(sections)
        expected_speaker_keys = {
            str(key).strip()
            for item in evidence
            for key in (item.get("observed_speaker_keys") if isinstance(item.get("observed_speaker_keys"), list) else [])
            if str(key).strip()
        }
        artifact_root = ensure_dir(artifact_dir) if artifact_dir else None
        artifacts: dict[str, Any] = {}

        existing_registry = (
            self._read_json_artifact(artifact_root / "speaker-registry.json")
            if artifact_root
            else {}
        )
        if existing_registry and not self._transcription_speaker_registry_error(
            existing_registry,
            expected_speaker_keys,
        ):
            registry_payload = {**existing_registry, "status": "done"}
        else:
            registry_payload = self._identify_transcript_speakers(
                evidence,
                source_hint,
                env,
            )
        registry_error = self._transcription_speaker_registry_error(
            registry_payload,
            expected_speaker_keys,
        )
        if registry_payload.get("status") != "done" or registry_error:
            reason = registry_error or str(registry_payload.get("reason") or "人物与角色识别失败")
            if artifact_root:
                artifacts["speaker_registry_failure"] = self._write_json_artifact(
                    artifact_root,
                    "speaker-registry-failure.json",
                    {"reason": reason, "result": registry_payload},
                )
            return {
                "status": "pending_manual",
                "stage": "speaker_identification",
                "reason": reason,
                "postprocess_artifacts": artifacts,
            }

        speaker_registry = list(registry_payload.get("speaker_registry") or [])
        registry_keys = {
            str(item.get("speaker_key") or "").strip()
            for item in speaker_registry
            if isinstance(item, dict) and str(item.get("speaker_key") or "").strip()
        }
        if artifact_root:
            artifacts["speaker_registry"] = self._write_json_artifact(
                artifact_root,
                "speaker-registry.json",
                {"speaker_registry": speaker_registry},
            )

        rewrite_target = self._env_int(env, "TRANSCRIPTION_REWRITE_CHARS_TARGET", 8000)
        rewrite_max = self._env_int(env, "TRANSCRIPTION_REWRITE_CHARS_MAX", 10000)
        rewritten_sections: list[str] = []
        labeled_transcript: list[dict[str, Any]] = []
        for section in sections:
            section_lines: list[str] = []
            chunks = self._split_text_chunks(str(section["text"]), rewrite_target, rewrite_max, 0)
            for index, chunk in enumerate(chunks, start=1):
                chunk_id = f"{section['source_audio']}-rewrite-{index:02d}"
                source_units = self._split_transcript_source_units(
                    str(chunk["text"]),
                    source_audio=str(section["source_audio"]),
                    chunk_id=chunk_id,
                    base_char_start=int(chunk["char_start"]),
                )
                artifact_path = artifact_root / f"{chunk_id}.json" if artifact_root else None
                existing_rewrite = self._read_json_artifact(artifact_path) if artifact_path else {}
                if existing_rewrite and not self._transcription_rewrite_coverage_error(
                    existing_rewrite,
                    source_units,
                    registry_keys,
                ):
                    rewrite_payload = {**existing_rewrite, "status": "done"}
                else:
                    rewrite_payload = self._rewrite_transcript_chunk_by_role(
                        chunk_id=chunk_id,
                        source_units=source_units,
                        speaker_registry=speaker_registry,
                        source_hint=source_hint,
                        env=env,
                    )
                rewrite_error = self._transcription_rewrite_coverage_error(
                    rewrite_payload,
                    source_units,
                    registry_keys,
                )
                if rewrite_payload.get("status") != "done" or rewrite_error:
                    reason = rewrite_error or str(rewrite_payload.get("reason") or "按角色重洗文字稿失败")
                    if artifact_root:
                        artifacts["transcript_rewrite_failure"] = self._write_json_artifact(
                            artifact_root,
                            f"{chunk_id}-failure.json",
                            {"reason": reason, "result": rewrite_payload},
                        )
                    return {
                        "status": "pending_manual",
                        "stage": "role_aware_rewrite",
                        "reason": reason,
                        "postprocess_artifacts": artifacts,
                    }
                normalized_rewrite = {
                    "schema_version": TRANSCRIPTION_SOURCE_UNIT_SCHEMA_VERSION,
                    "chunk_id": chunk_id,
                    "rewritten_units": list(rewrite_payload.get("rewritten_units") or []),
                }
                if artifact_root:
                    path = self._write_json_artifact(artifact_root, f"{chunk_id}.json", normalized_rewrite)
                    artifacts.setdefault("transcript_rewrites", []).append(path)
                for unit in normalized_rewrite["rewritten_units"]:
                    if not isinstance(unit, dict):
                        continue
                    source_unit_id = str(unit.get("source_unit_id") or "").strip()
                    turns = unit.get("turns") if isinstance(unit.get("turns"), list) else []
                    for turn in turns:
                        if not isinstance(turn, dict):
                            continue
                        display_name = str(turn.get("display_name") or turn.get("speaker_key") or "未区分说话人").strip()
                        role = str(turn.get("meeting_role") or "未从来源识别").strip()
                        cleaned_text = str(turn.get("text") or "").strip()
                        if not cleaned_text:
                            continue
                        label = display_name if role in {"", "未从来源识别"} else f"{display_name}（{role}）"
                        section_lines.append(f"{label}：{cleaned_text}")
                        labeled_transcript.append(
                            {
                                "speaker": display_name,
                                "role": role,
                                "text": cleaned_text,
                                "speaker_key": str(turn.get("speaker_key") or "").strip(),
                                "source": source_unit_id,
                                "confidence": str(turn.get("confidence") or "").strip(),
                            }
                        )
            audio_index = str(section["source_audio"]).rsplit("-", 1)[-1].lstrip("0") or "1"
            rewritten_sections.append(
                f"### 文字稿 {audio_index}：{section['source_title']}\n" + "\n".join(section_lines)
            )

        rewritten_transcript = "\n\n".join(rewritten_sections).strip()
        if not rewritten_transcript or not labeled_transcript:
            return {
                "status": "pending_manual",
                "stage": "role_aware_rewrite",
                "reason": "按角色重洗后没有可用文字内容",
                "postprocess_artifacts": artifacts,
            }
        if artifact_root:
            artifacts["rewritten_transcript"] = self._write_json_artifact(
                artifact_root,
                "rewritten-transcript.json",
                {
                    "speaker_registry": speaker_registry,
                    "labeled_transcript": labeled_transcript,
                    "rewritten_transcript": rewritten_transcript,
                },
            )
        return {
            "status": "done",
            "speaker_registry": speaker_registry,
            "labeled_transcript": labeled_transcript,
            "rewritten_transcript": rewritten_transcript,
            "postprocess_artifacts": artifacts,
        }

    @staticmethod
    def _transcription_speaker_evidence(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        label_pattern = re.compile(
            r"^(?P<label>(?:说话人|发言者|speaker|spk)\s*[_-]?\s*[A-Za-z0-9一二三四五六七八九十]+)\s*[:：]",
            re.I,
        )
        evidence: list[dict[str, Any]] = []
        for section in sections:
            observed: list[str] = []
            for raw_line in str(section.get("text") or "").splitlines():
                match = label_pattern.match(raw_line.strip())
                if not match:
                    continue
                label = re.sub(r"\s+", "", match.group("label")).lower()
                if label not in observed:
                    observed.append(label)
            evidence.append(
                {
                    "source_audio": str(section.get("source_audio") or ""),
                    "source_title": str(section.get("source_title") or ""),
                    "observed_speaker_keys": observed,
                    "transcript": str(section.get("text") or "").strip(),
                }
            )
        return evidence

    @staticmethod
    def _transcription_speaker_registry_error(
        payload: dict[str, Any],
        expected_speaker_keys: set[str],
    ) -> str:
        raw_registry = payload.get("speaker_registry") if isinstance(payload, dict) else None
        registry = raw_registry if isinstance(raw_registry, list) else []
        if not registry:
            return "speaker_registry 必须是非空数组"
        required = ("speaker_key", "display_name", "meeting_role", "identity_evidence", "confidence")
        seen: set[str] = set()
        invalid = 0
        for item in registry:
            if not isinstance(item, dict):
                invalid += 1
                continue
            key = str(item.get("speaker_key") or "").strip()
            if not key or key in seen:
                invalid += 1
                continue
            seen.add(key)
            if any(not str(item.get(field) or "").strip() for field in required[1:]):
                invalid += 1
        issues: list[str] = []
        if invalid:
            issues.append(f"存在 {invalid} 个无效或重复的角色记录")
        missing = expected_speaker_keys - seen
        if missing:
            issues.append("缺少来源说话人标识：" + "、".join(sorted(missing)))
        return "；".join(issues)

    def _identify_transcript_speakers(
        self,
        evidence: list[dict[str, Any]],
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        prompt = (
            "你是会议人物与角色识别器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "先识别稳定的对话人物，再判断其本次会议角色；人物身份、会议角色和发言内容是三个不同层次，不得混为一谈。\n"
            "输出字段固定为 speaker_registry。speaker_registry 是非空数组，每项固定含 speaker_key、display_name、meeting_role、identity_evidence、confidence。\n"
            "若来源已有说话人标签，speaker_key 必须原样覆盖全部 observed_speaker_keys；若来源没有标签，可依据跨段语义和问答关系保守地区分为 speaker_a、speaker_b 等匿名角色。\n"
            "只有来源明确给出真实姓名时才能写姓名；否则 display_name 使用“说话人 A”“说话人 B”等匿名名称，禁止猜测。meeting_role 可写来源支持的会议职能，如产品开发方、需求方、合作方；证据不足写“未从来源识别”。\n"
            "identity_evidence 必须简述区分依据并说明是否来自显式标签；confidence 使用高、中、低。若部分发言无法可靠归属，应增加 speaker_unknown，display_name 写“未区分说话人”。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "speaker_evidence": evidence,
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "人物与角色识别")

    @classmethod
    def _transcription_rewrite_coverage_error(
        cls,
        payload: dict[str, Any],
        source_units: list[dict[str, Any]],
        registry_keys: set[str],
    ) -> str:
        expected = {str(unit.get("source_unit_id") or ""): unit for unit in source_units}
        raw_units = payload.get("rewritten_units") if isinstance(payload, dict) else None
        rewritten_units = raw_units if isinstance(raw_units, list) else []
        seen: set[str] = set()
        duplicates: set[str] = set()
        unknown_ids: set[str] = set()
        unknown_speakers: set[str] = set()
        invalid = 0
        source_chars = 0
        rewritten_chars = 0
        for item in rewritten_units:
            if not isinstance(item, dict):
                invalid += 1
                continue
            unit_id = str(item.get("source_unit_id") or "").strip()
            if unit_id in seen:
                duplicates.add(unit_id)
            seen.add(unit_id)
            source = expected.get(unit_id)
            if source is None:
                unknown_ids.add(unit_id)
                continue
            source_chars += cls._transcription_semantic_char_count(str(source.get("text") or ""))
            turns = item.get("turns") if isinstance(item.get("turns"), list) else []
            if not turns:
                invalid += 1
                continue
            for turn in turns:
                if not isinstance(turn, dict):
                    invalid += 1
                    continue
                speaker_key = str(turn.get("speaker_key") or "").strip()
                if speaker_key not in registry_keys:
                    unknown_speakers.add(speaker_key or "<empty>")
                if any(
                    not str(turn.get(field) or "").strip()
                    for field in ("display_name", "meeting_role", "text", "confidence")
                ):
                    invalid += 1
                    continue
                rewritten_chars += cls._transcription_semantic_char_count(str(turn.get("text") or ""))
        issues: list[str] = []
        missing = set(expected) - seen
        if missing:
            issues.append(f"缺少 {len(missing)} 个来源段")
        if duplicates:
            issues.append(f"包含 {len(duplicates)} 个重复来源段")
        if unknown_ids:
            issues.append(f"包含 {len(unknown_ids)} 个未知来源段")
        if unknown_speakers:
            issues.append("使用了角色注册表之外的说话人：" + "、".join(sorted(unknown_speakers)))
        if invalid:
            issues.append(f"存在 {invalid} 个无效重洗项")
        if source_chars and rewritten_chars / source_chars < 0.4:
            issues.append(f"重洗后有效字符仅保留 {rewritten_chars / source_chars:.1%}，存在过度压缩")
        return "；".join(issues)

    def _rewrite_transcript_chunk_by_role(
        self,
        *,
        chunk_id: str,
        source_units: list[dict[str, Any]],
        speaker_registry: list[dict[str, Any]],
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        prompt = (
            "你是会议文字稿角色化重洗器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "任务是在既定 speaker_registry 下重洗文字稿，不是摘要，也不是会议纪要。保留全部不同的实质内容、数字、例子、条件、分歧、否定和不确定性；只清理口吃、语气词、断裂重复和无意义寒暄。\n"
            "输出字段固定为 chunk_id、rewritten_units。rewritten_units 必须与 source_units 一一对应、顺序不变，每项固定含 source_unit_id、turns。\n"
            "turns 是非空数组，每项固定含 speaker_key、display_name、meeting_role、text、confidence；speaker_key 必须来自 speaker_registry，display_name 和 meeting_role 必须与注册表一致。一个来源段含多个人发言时必须拆成多个 turn。\n"
            "不得猜真实姓名；无法可靠归属时只能使用注册表中的 speaker_unknown。不得合并不同来源段，不得遗漏来源段，不得把讨论内容改写成结论。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "chunk_id": chunk_id,
                "speaker_registry": speaker_registry,
                "source_units": source_units,
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "按角色重洗文字稿")

    @staticmethod
    def _transcription_final_note_value_missing(value: Any) -> bool:
        return transcription_final_note_value_missing(value)

    def summarize_inspiration(self, text: str, source_hint: str = "", artifact_dir: str | Path | None = None) -> dict[str, Any]:
        body = text.strip()
        if not body:
            return {"status": "pending_manual", "reason": "缺少灵感内容"}

        env = self._content_flow_env()
        prompt = (
            "你是灵感归档器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "你不是在写学习笔记，也不是把内容总结成知识条目；你要保留一个想法刚出现时的方向感、张力和可生长性。\n"
            "判断这条灵感真正想推动什么：新内容栏目、产品模块、表达角度、跨领域连接、实验假设，或以后值得展开的判断。\n"
            "JSON 字段固定为 title、weekly_title、archive_macro_summary、archive_summary_bullets、spark、what_it_does、why_now、expansion_directions、possible_outputs、verification_actions、original_lines_to_keep、pending_questions、suggested_tags、confidence_note。\n"
            "title: 8-28 个汉字，语义化命名，不要照抄长句。\n"
            "weekly_title: 18-32 个汉字，写清楚这条灵感在做什么；必须是动作 + 对象 + 意图，避免“关于...的想法”。\n"
            "archive_macro_summary: 1 句话宏观总结，说明这条灵感的核心判断、可生长方向或未来价值，供 Obsidian 周记 # 灵感 使用。\n"
            "archive_summary_bullets: 数组，1-5 条，每条 1 句话，提炼这条灵感可复用的关键判断、展开方向、验证动作或边界；不要超过 5 条。\n"
            "spark: 一句话火花，保留最有能量的原始洞见或表达。\n"
            "what_it_does: 说明这条灵感正在推动什么判断、连接、命名、实验或方向。\n"
            "why_now: 说明它为什么此刻出现，关联当前目标、项目、困惑或机会。\n"
            "expansion_directions: 数组，列出未来可能长出的 3-6 个分支，不要写成完整教程。\n"
            "possible_outputs: 数组，列出可能变成的内容、产品、实验、文章、视频或项目。\n"
            "verification_actions: 数组，只列最小可验证下一步，不要生成大计划。\n"
            "original_lines_to_keep: 数组，保留原文中最值得以后重新捡起的句子。\n"
            "pending_questions: 数组，列出仍需补充或确认的问题。\n"
            "suggested_tags: 数组，给出 3-8 个短标签。\n"
            "不要补充原文没有的事实；不要把灵感整理成已完成方案；结果要短、准、有未来动作感。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "inspiration": body,
            },
            ensure_ascii=False,
        )
        result = self._call_postprocess_json(prompt, user_content, env, "灵感整理")
        if artifact_dir:
            root = ensure_dir(artifact_dir)
            self._write_json_artifact(root, "inspiration-summary.json", result)
            result.setdefault("postprocess_artifacts", {})["inspiration_summary"] = str(root / "inspiration-summary.json")
        return result

    def clean_activity_brief(self, text: str, *, created_at: str = "", source_hint: str = "") -> dict[str, Any]:
        body = (text or "").strip()
        if not body:
            return {"status": "pending_manual", "reason": "缺少活动通知正文"}

        env = self._content_flow_env()
        prompt = (
            "你是活动通知清洗器。只输出合法 JSON，不要 Markdown 代码块，不要解释。\n"
            "任务：把原始活动通知做语义清洗，输出可直接写入多维表格的字段。不要依赖固定标题词；按语义理解通知。\n"
            "必须保留原文所有关键事实，禁止编造。缺失字段输出空字符串或空数组。\n"
            "字段固定为：title、platform、brief_summary、activity_time、activity_time_start、activity_time_end、boost_date、main_topic、activity_level、reward、participation_method、participation_form、filling_points、submission_requirements、subtopic_directions、source_links、activity_status、parse_status、missing_info、confidence_note。\n"
            "title: 必须从活动正文/方向/示例里提取最适合直接创作的选题标题，不是平台活动名、总活动IP、栏目名或话题包装名；去掉平台名、总活动IP、栏目编号、素材类型、重复话题、批次前缀等包装信息。例：“抖音请回答2026高考｜毕业旅行有问必答”不要输出“毕业旅行有问必答”，应提炼为更适合创作的具体标题，如“毕业旅行前最该问清楚的事”；“小创作灵感2｜高考后去办变美落地签”输出“高考后去办变美落地签”。如果原文给出多个创作方向，title 选最适合作为父记录代表的一个，其他方向完整放入 subtopic_directions 作为子记录标题来源。\n"
            "activity_time: 清洗为可分析文本，优先格式为 YYYY-MM-DD 至 YYYY-MM-DD；如果只有单日则 YYYY-MM-DD；年份缺失时按 created_at 所在年份推断。\n"
            "activity_time_start/activity_time_end: 如果能确定，分别输出 YYYY-MM-DD；不能确定输出空字符串。不要输出投稿截止时间字段。\n"
            "boost_date: 单独输出最适合集中发布/投稿冲榜的日期，格式 YYYY-MM-DD。原文出现“冲榜日期/冲榜时间/集中投稿/投稿时间/发布时间/推荐发布时间/抢占首波流量建议提前发布/官方视野锁定”等语义时填写；如果写“投稿时间：2026年6月17日”就输出 2026-06-17；如果写“发布时间：即日起-2026年6月30日”就用 created_at 当天作为即日起日期；如果只有普通活动时间范围但没有发布/投稿/冲榜语义，输出空字符串；不能把普通活动结束日或报名截止日当冲榜日期。\n"
            "main_topic: 只放官方要求携带的话题/hashtag 或明确命名的活动话题；不要放活动目的、内容概述或参与条件。没有明确主话题则输出空字符串。\n"
            "participation_method: 只写怎么参与/怎么发布/怎么邀请，不要混入表单入口、登记链接、奖励、方向列表。\n"
            "submission_requirements: 写提交、审核、报名、入口使用等要求；涉及提交入口、表单、是否重复提交的信息放这里，不要放 participation_method。\n"
            "subtopic_directions: 数组，每个元素只是一条可直接作为创作子记录标题的内容方向/子话题/选题选项，必须完整保留方向名称和说明；不要把参与资格、发布要求、审核条件、首篇内容要求放进方向列表，也不要用数量概括替代列表。\n"
            "filling_points: 写需要填写或登记的信息、表单/入口；如果只是链接，也要说明链接用途。\n"
            "activity_status: 默认进行中；如果明确已结束可写已过期；如果明确放弃可写已放弃。只使用：进行中、已过期、已放弃。\n"
            "parse_status: 只使用：已解析、飞书文档待读取、待人工补充。\n"
            "source_links: 数组，元素为 {label,url}。\n"
            "输出必须是 JSON object。"
        )
        user_content = json.dumps(
            {
                "created_at": created_at,
                "source_hint": source_hint or "",
                "raw_activity_notice": body,
            },
            ensure_ascii=False,
        )
        result = self._call_profile_provider_json("activity_cleaning", prompt, user_content, "活动 Brief AI清洗")
        if result.get("status") != "done":
            return result
        return self._normalize_activity_clean_result(result, raw_text=body)

    def _normalize_activity_clean_result(self, result: dict[str, Any], *, raw_text: str = "") -> dict[str, Any]:
        normalized = dict(result)
        for key in (
            "title",
            "platform",
            "brief_summary",
            "activity_time",
            "activity_time_start",
            "activity_time_end",
            "boost_date",
            "main_topic",
            "activity_level",
            "reward",
            "participation_method",
            "participation_form",
            "filling_points",
            "submission_requirements",
            "activity_status",
            "parse_status",
            "confidence_note",
        ):
            value = normalized.get(key)
            normalized[key] = str(value or "").strip()

        directions = normalized.get("subtopic_directions")
        if isinstance(directions, str):
            directions = [line.strip(" -•\t") for line in directions.splitlines() if line.strip(" -•\t")]
        if not isinstance(directions, list):
            directions = []
        normalized["subtopic_directions"] = [str(item).strip() for item in directions if str(item).strip()]

        links = normalized.get("source_links")
        if not isinstance(links, list):
            links = []
        clean_links: list[dict[str, str]] = []
        for item in links:
            if isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                if url:
                    clean_links.append({"label": str(item.get("label") or "来源链接").strip() or "来源链接", "url": url})
            elif isinstance(item, str) and item.strip().startswith("http"):
                clean_links.append({"label": "来源链接", "url": item.strip()})
        seen_links = {item["url"] for item in clean_links}
        for item in self._activity_raw_source_links(raw_text):
            url = item["url"]
            if url in seen_links:
                continue
            seen_links.add(url)
            clean_links.append(item)
        normalized["source_links"] = clean_links

        missing = normalized.get("missing_info")
        if isinstance(missing, str):
            missing = [item.strip() for item in re.split(r"[、,，\n]", missing) if item.strip()]
        if not isinstance(missing, list):
            missing = []
        normalized["missing_info"] = [str(item).strip() for item in missing if str(item).strip()]

        if normalized.get("activity_status") not in {"进行中", "已过期", "已放弃"}:
            normalized["activity_status"] = "进行中"
        if normalized.get("parse_status") not in {"已解析", "飞书文档待读取", "待人工补充"}:
            normalized["parse_status"] = "已解析"
        return normalized

    @classmethod
    def _activity_raw_source_links(cls, text: str) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for start in cls._raw_url_starts(text):
            url = cls._read_wrapped_url(text, start)
            if not url or url in seen:
                continue
            seen.add(url)
            links.append({"label": cls._activity_raw_link_label(text, start), "url": url})
        return links

    @staticmethod
    def _raw_url_starts(text: str) -> list[int]:
        return [match.start() for match in re.finditer(r"https?://", text or "")]

    @staticmethod
    def _read_wrapped_url(text: str, start: int) -> str:
        allowed = set(string.ascii_letters + string.digits + "-._~:/?#[]@!$&'()*+,;=%")
        chars: list[str] = []
        index = start
        while index < len(text):
            char = text[index]
            if char in allowed:
                chars.append(char)
                index += 1
                continue
            if char.isspace():
                next_index = index + 1
                while next_index < len(text) and text[next_index].isspace():
                    next_index += 1
                if next_index < len(text) and text[next_index] in allowed:
                    index = next_index
                    continue
            break
        return "".join(chars).rstrip("，。；、.）)]】")

    @staticmethod
    def _activity_raw_link_label(text: str, start: int) -> str:
        context = text[max(0, start - 80) : start]
        if "返稿" in context or "报名表" in context or "填表" in context:
            return "返稿报名表"
        if "爆款" in context or "范式" in context or "参考" in context:
            return "爆款范式参考"
        if "活动" in context:
            return "活动链接"
        return "原文链接"

    def _summarize_dialogue_transcript_chunked(
        self,
        text: str,
        source_hint: str,
        env: dict[str, str],
        *,
        artifact_dir: str | Path | None = None,
        speaker_notes: list[dict[str, Any]] | None = None,
        labeled_transcript: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        sections = self._split_transcript_audio_sections(text)
        chunk_target = self._env_int(env, "TRANSCRIPTION_CHUNK_CHARS_TARGET", 10000)
        chunk_max = self._env_int(env, "TRANSCRIPTION_CHUNK_CHARS_MAX", 12000)
        # Source-unit coverage makes every character accountable; overlap would
        # create two valid IDs for the same source text and force repetition.
        chunk_overlap = 0
        artifacts: dict[str, Any] = {}
        artifact_root = ensure_dir(artifact_dir) if artifact_dir else None
        if artifact_root:
            artifacts["dir"] = str(artifact_root)
            self._write_json_artifact(artifact_root, "transcript-sections.json", {"sections": sections})

        chunk_summaries: list[dict[str, Any]] = []

        for section in sections:
            chunks = self._split_text_chunks(str(section["text"]), chunk_target, chunk_max, chunk_overlap)
            section_chunk_ids: list[str] = []
            for index, chunk in enumerate(chunks, start=1):
                chunk_id = f"{section['source_audio']}-chunk-{index:02d}"
                section_chunk_ids.append(chunk_id)
                existing_chunk = (
                    self._read_json_artifact(artifact_root / f"{chunk_id}.json")
                    if artifact_root
                    else {}
                )
                source_units = self._split_transcript_source_units(
                    str(chunk["text"]),
                    source_audio=str(section["source_audio"]),
                    chunk_id=chunk_id,
                    base_char_start=int(chunk["char_start"]),
                )
                reusable_chunk = bool(
                    existing_chunk
                    and existing_chunk.get("schema_version") == TRANSCRIPTION_SOURCE_UNIT_SCHEMA_VERSION
                    and existing_chunk.get("chunk_id") == chunk_id
                    and existing_chunk.get("source_audio") == section["source_audio"]
                    and existing_chunk.get("char_start") == chunk["char_start"]
                    and existing_chunk.get("char_end") == chunk["char_end"]
                    and not self._transcription_source_unit_coverage_error(existing_chunk, source_units, env)
                    and self._transcription_evidence_hashes([existing_chunk])
                )
                if reusable_chunk:
                    parsed = {**existing_chunk, "status": "done"}
                else:
                    parsed = self._summarize_transcript_chunk(
                        chunk_id=chunk_id,
                        source_audio=str(section["source_audio"]),
                        source_title=str(section["source_title"]),
                        char_start=int(chunk["char_start"]),
                        char_end=int(chunk["char_end"]),
                        text=str(chunk["text"]),
                        source_hint=source_hint,
                        env=env,
                    )
                if parsed.get("status") != "done":
                    if artifact_root:
                        artifacts["failure"] = self._write_json_artifact(
                            artifact_root,
                            f"{chunk_id}-failure.json",
                            {"stage": "chunk", "chunk_id": chunk_id, "result": parsed},
                        )
                    return {
                        "status": "pending_manual",
                        "reason": f"分片整理失败 {chunk_id}：{parsed.get('reason') or '未返回可解析 JSON'}",
                        "stage": "chunk",
                        "chunk_id": chunk_id,
                        "postprocess_artifacts": artifacts,
                    }
                summary = dict(parsed)
                summary.pop("status", None)
                summary.setdefault("schema_version", TRANSCRIPTION_SOURCE_UNIT_SCHEMA_VERSION)
                summary["chunk_id"] = chunk_id
                summary["source_audio"] = section["source_audio"]
                summary["source_title"] = section["source_title"]
                summary["char_start"] = chunk["char_start"]
                summary["char_end"] = chunk["char_end"]
                self._annotate_evidence_hashes(summary)
                chunk_summaries.append(summary)
                if artifact_root:
                    chunk_path = self._write_json_artifact(artifact_root, f"{chunk_id}.json", summary)
                    artifacts.setdefault("chunks", []).append(chunk_path)
            if artifact_root:
                self._write_json_artifact(
                    artifact_root,
                    f"{section['source_audio']}-chunk-index.json",
                    {"source_audio": section["source_audio"], "source_title": section["source_title"], "chunks": section_chunk_ids},
                )

        attachment_summaries: list[dict[str, Any]] = []
        for section in sections:
            source_audio = section["source_audio"]
            chunks = [item for item in chunk_summaries if item.get("source_audio") == source_audio]
            if not chunks:
                continue
            expected_hashes = self._transcription_evidence_hashes(chunks)
            existing_attachment = (
                self._read_json_artifact(artifact_root / f"{source_audio}-attachment-summary.json")
                if artifact_root
                else {}
            )
            reusable_attachment = bool(
                existing_attachment
                and existing_attachment.get("attachment_id") == source_audio
                and not self._transcription_coverage_error(existing_attachment, expected_hashes)
            )
            if reusable_attachment:
                parsed = {**existing_attachment, "status": "done"}
            else:
                parsed = self._summarize_attachment_chunks(
                    source_audio=str(source_audio),
                    source_title=str(section["source_title"]),
                    chunks=chunks,
                    source_hint=source_hint,
                    env=env,
                )
            if parsed.get("status") != "done":
                if artifact_root:
                    artifacts["failure"] = self._write_json_artifact(
                        artifact_root,
                        f"{source_audio}-attachment-summary-failure.json",
                        {"stage": "attachment", "source_audio": source_audio, "result": parsed},
                    )
                return {
                    "status": "pending_manual",
                    "reason": f"单附件合并失败 {source_audio}：{parsed.get('reason') or '未返回可解析 JSON'}",
                    "stage": "attachment",
                    "source_audio": source_audio,
                    "postprocess_artifacts": artifacts,
                }
            attachment = dict(parsed)
            attachment.pop("status", None)
            attachment.setdefault("schema_version", "1.0")
            attachment["attachment_id"] = source_audio
            attachment["source_title"] = section["source_title"]
            attachment["covered_evidence_hashes"] = sorted(expected_hashes)
            attachment["detail_coverage"] = self._detail_coverage_from_key_points(chunks, expected_hashes)
            coverage_error = self._transcription_coverage_error(attachment, expected_hashes)
            if coverage_error:
                if artifact_root:
                    artifacts["failure"] = self._write_json_artifact(
                        artifact_root,
                        f"{source_audio}-attachment-coverage-failure.json",
                        {
                            "stage": "attachment_coverage",
                            "source_audio": source_audio,
                            "reason": coverage_error,
                            "result": attachment,
                        },
                    )
                return {
                    "status": "pending_manual",
                    "reason": f"单附件细节覆盖校验失败 {source_audio}：{coverage_error}",
                    "stage": "attachment_coverage",
                    "source_audio": source_audio,
                    "postprocess_artifacts": artifacts,
                }
            attachment_summaries.append(attachment)
            if artifact_root:
                attachment_path = self._write_json_artifact(artifact_root, f"{source_audio}-attachment-summary.json", attachment)
                artifacts.setdefault("attachments", []).append(attachment_path)

        global_input: list[dict[str, Any]] = attachment_summaries
        group_size = self._env_int(env, "TRANSCRIPTION_GLOBAL_GROUP_SIZE", 8)
        if len(attachment_summaries) > group_size:
            grouped: list[dict[str, Any]] = []
            for group_index, start in enumerate(range(0, len(attachment_summaries), group_size), start=1):
                group = attachment_summaries[start : start + group_size]
                parsed = self._summarize_attachment_group(group_index, group, source_hint, env)
                if parsed.get("status") != "done":
                    if artifact_root:
                        artifacts["failure"] = self._write_json_artifact(
                            artifact_root,
                            f"group-{group_index:02d}-summary-failure.json",
                            {"stage": "group", "group_id": f"group-{group_index:02d}", "result": parsed},
                        )
                    return {
                        "status": "pending_manual",
                        "reason": f"中间合并失败 group-{group_index:02d}：{parsed.get('reason') or '未返回可解析 JSON'}",
                        "stage": "group",
                        "postprocess_artifacts": artifacts,
                    }
                group_expected_hashes = self._transcription_evidence_hashes(group)
                parsed["covered_evidence_hashes"] = sorted(group_expected_hashes)
                parsed["detail_coverage"] = self._merge_transcription_detail_coverage(group, group_expected_hashes)
                group_coverage_error = self._transcription_coverage_error(parsed, group_expected_hashes)
                if group_coverage_error:
                    if artifact_root:
                        artifacts["failure"] = self._write_json_artifact(
                            artifact_root,
                            f"group-{group_index:02d}-coverage-failure.json",
                            {
                                "stage": "group_coverage",
                                "group_id": f"group-{group_index:02d}",
                                "reason": group_coverage_error,
                                "result": parsed,
                            },
                        )
                    return {
                        "status": "pending_manual",
                        "reason": f"中间合并细节覆盖校验失败 group-{group_index:02d}：{group_coverage_error}",
                        "stage": "group_coverage",
                        "postprocess_artifacts": artifacts,
                    }
                parsed.pop("status", None)
                grouped.append(parsed)
                if artifact_root:
                    group_path = self._write_json_artifact(artifact_root, f"group-{group_index:02d}-summary.json", parsed)
                    artifacts.setdefault("groups", []).append(group_path)
            global_input = grouped

        expected_global_hashes = self._transcription_evidence_hashes(attachment_summaries)
        existing_global = self._latest_transcription_global_note_artifact(artifact_root) if artifact_root else {}
        if existing_global and all(field in existing_global for field in TRANSCRIPTION_FINAL_NOTE_REQUIRED_FIELDS):
            final_note = {**existing_global, "status": "done"}
        else:
            final_note = self._summarize_global_note(global_input, source_hint, env)
        if speaker_notes is not None:
            final_note["speaker_notes"] = speaker_notes
        if labeled_transcript is not None:
            final_note["labeled_transcript"] = labeled_transcript
        if final_note.get("status") != "done":
            if artifact_root:
                artifacts["failure"] = self._write_json_artifact(
                    artifact_root,
                    "global-note-draft-failure.json",
                    {"stage": "global", "result": final_note},
                )
            return {
                "status": "pending_manual",
                "reason": f"全局整理失败：{final_note.get('reason') or '未返回可解析 JSON'}",
                "stage": "global",
                "postprocess_artifacts": artifacts,
            }

        final_note["covered_evidence_hashes"] = sorted(expected_global_hashes)
        final_note["detail_coverage"] = self._merge_transcription_detail_coverage(
            attachment_summaries,
            expected_global_hashes,
        )

        global_note_draft = dict(final_note)
        contract_errors = validate_transcription_final_note_contract(final_note)
        if contract_errors:
            repaired_note, contract_errors, repair_history = self._repair_global_note_contract_with_retries(
                final_note,
                attachment_summaries,
                contract_errors,
                source_hint,
                env,
            )
            if not contract_errors:
                final_note = {**repaired_note, "status": "done"}
                if artifact_root:
                    artifacts["global_note_contract_repair"] = self._write_json_artifact(
                        artifact_root,
                        "global-note-contract-repair.json",
                        {"attempts": repair_history},
                    )
            if artifact_root:
                artifacts["global_note_draft"] = self._write_json_artifact(
                    artifact_root,
                    "global-note-draft.json",
                    global_note_draft,
                )
            if contract_errors:
                if artifact_root:
                    artifacts["failure"] = self._write_json_artifact(
                        artifact_root,
                        "global-note-draft-contract-failure.json",
                        {
                            "stage": "global_contract",
                            "errors": contract_errors,
                            "result": final_note,
                            "repair_attempts": repair_history,
                        },
                    )
                return {
                    "status": "pending_manual",
                    "reason": "全局整理 schema contract 不通过：" + "；".join(contract_errors[:5]),
                    "stage": "global_contract",
                    "postprocess_artifacts": artifacts,
                }
        consistency = self._check_global_note_consistency(final_note, attachment_summaries, env)
        coverage_error = self._transcription_coverage_error(final_note, expected_global_hashes)
        if coverage_error:
            consistency["approved"] = False
            blocking = consistency.get("blocking_issues") if isinstance(consistency.get("blocking_issues"), list) else []
            consistency["blocking_issues"] = [*blocking, coverage_error]
        if artifact_root:
            artifacts["global_note_draft"] = self._write_json_artifact(artifact_root, "global-note-draft.json", final_note)
            artifacts["consistency_check"] = self._write_json_artifact(artifact_root, "consistency-check.json", consistency)
        approved_value = consistency.get("approved")
        approved = approved_value is True or str(approved_value).strip().lower() == "true"
        consistency["approved"] = approved
        blocking_issues = consistency.get("blocking_issues") if isinstance(consistency.get("blocking_issues"), list) else []
        max_consistency_revisions = max(
            1,
            min(self._env_int(env, "TRANSCRIPTION_CONSISTENCY_MAX_REVISIONS", 5), 5),
        )
        consistency_revision_count = 0
        for revision_attempt in range(1, max_consistency_revisions + 1):
            if approved:
                break
            revision_fields = self._transcription_consistency_repair_fields(consistency)
            if not revision_fields:
                if artifact_root:
                    artifacts["global_note_revision_failure"] = self._write_json_artifact(
                        artifact_root,
                        "global-note-revision-failure.json",
                        {
                            "stage": "revision",
                            "attempt": revision_attempt,
                            "repair_fields": [],
                            "result": {"reason": "一致性检查未返回可修订字段"},
                        },
                    )
                break
            revision_payload = self._revise_global_note(final_note, attachment_summaries, consistency, source_hint, env)
            repairs = revision_payload.get("repairs") if isinstance(revision_payload.get("repairs"), dict) else {}
            applied_revision_fields = revision_fields.intersection(repairs)
            if revision_payload.get("status") == "done" and applied_revision_fields:
                revised_note = dict(final_note)
                self._apply_transcription_field_repairs(
                    revised_note,
                    repairs,
                    applied_revision_fields,
                    merge_list_items=False,
                )
                revised_note.pop("status", None)
                revised_contract_errors = validate_transcription_final_note_contract(revised_note)
                schema_repair_history: list[dict[str, Any]] = []
                if revised_contract_errors:
                    revised_note, revised_contract_errors, schema_repair_history = (
                        self._repair_global_note_contract_with_retries(
                            revised_note,
                            attachment_summaries,
                            revised_contract_errors,
                            source_hint,
                            env,
                        )
                    )
                if revised_contract_errors:
                    if artifact_root:
                        revision_suffix = "" if revision_attempt == 1 else f"-{revision_attempt:02d}"
                        artifacts[f"global_note_revision_schema_failure_{revision_attempt:02d}"] = self._write_json_artifact(
                            artifact_root,
                            f"global-note-revision-schema-failure{revision_suffix}.json",
                            {
                                "stage": "revision_schema",
                                "attempt": revision_attempt,
                                "repair_fields": sorted(revision_fields),
                                "errors": revised_contract_errors,
                                "schema_repair_attempts": schema_repair_history,
                                "result": revised_note,
                            },
                        )
                    continue
                revised_consistency = self._check_global_note_consistency(revised_note, attachment_summaries, env)
                revised_coverage_error = self._transcription_coverage_error(revised_note, expected_global_hashes)
                if revised_coverage_error:
                    revised_consistency["approved"] = False
                    revised_blocking = (
                        revised_consistency.get("blocking_issues")
                        if isinstance(revised_consistency.get("blocking_issues"), list)
                        else []
                    )
                    revised_consistency["blocking_issues"] = [*revised_blocking, revised_coverage_error]
                revised_approved_value = revised_consistency.get("approved")
                revised_approved = revised_approved_value is True or str(revised_approved_value).strip().lower() == "true"
                revised_consistency["approved"] = revised_approved
                consistency_revision_count = revision_attempt
                if artifact_root:
                    revision_suffix = "" if revision_attempt == 1 else f"-{revision_attempt:02d}"
                    note_artifact_key = "global_note_revised" if revision_attempt == 1 else f"global_note_revised_{revision_attempt:02d}"
                    check_artifact_key = (
                        "consistency_check_revised"
                        if revision_attempt == 1
                        else f"consistency_check_revised_{revision_attempt:02d}"
                    )
                    artifacts[note_artifact_key] = self._write_json_artifact(
                        artifact_root,
                        f"global-note-revised{revision_suffix}.json",
                        revised_note,
                    )
                    artifacts[check_artifact_key] = self._write_json_artifact(
                        artifact_root,
                        f"consistency-check-revised{revision_suffix}.json",
                        revised_consistency,
                    )
                final_note = revised_note
                consistency = revised_consistency
                blocking_issues = (
                    revised_consistency.get("blocking_issues")
                    if isinstance(revised_consistency.get("blocking_issues"), list)
                    else blocking_issues
                )
                if revised_approved:
                    approved = True
                    blocking_issues = []
            else:
                if artifact_root:
                    revision_suffix = "" if revision_attempt == 1 else f"-{revision_attempt:02d}"
                    artifacts[f"global_note_revision_failure_{revision_attempt:02d}"] = self._write_json_artifact(
                        artifact_root,
                        f"global-note-revision-failure{revision_suffix}.json",
                        {
                            "stage": "revision",
                            "attempt": revision_attempt,
                            "repair_fields": sorted(revision_fields),
                            "result": revision_payload,
                        },
                    )
                continue

        if not approved:
            if not blocking_issues:
                blocking_issues = ["一致性检查未批准，但未返回具体阻断项"]
            return {
                "status": "pending_manual",
                "reason": "一致性检查未通过：" + "；".join(str(item) for item in blocking_issues[:5]),
                "stage": "consistency",
                "postprocess_artifacts": artifacts,
                "consistency_check": consistency,
                "consistency_revision_count": consistency_revision_count,
                "consistency_revision_limit": max_consistency_revisions,
            }
        final_contract_errors = validate_transcription_final_note_contract(final_note)
        if final_contract_errors:
            if artifact_root:
                artifacts["failure"] = self._write_json_artifact(
                    artifact_root,
                    "global-note-final-contract-failure.json",
                    {"stage": "final_contract", "errors": final_contract_errors, "result": final_note},
                )
            return {
                "status": "pending_manual",
                "reason": "最终整理 schema contract 不通过：" + "；".join(final_contract_errors[:5]),
                "stage": "final_contract",
                "postprocess_artifacts": artifacts,
                "consistency_check": consistency,
            }
        final_note["status"] = "done"
        final_note["postprocess_provider"] = final_note.get("postprocess_provider", "chunked")
        final_note["postprocess_pipeline"] = "chunked-map-reduce-final"
        final_note["chunk_count"] = len(chunk_summaries)
        final_note["attachment_count"] = len(attachment_summaries)
        final_note["consistency_revision_count"] = consistency_revision_count
        final_note["consistency_revision_limit"] = max_consistency_revisions
        if self._env_truthy(env.get("TRANSCRIPTION_POSTPROCESS_RETURN_INTERMEDIATES", "0")):
            final_note["chunk_summaries"] = chunk_summaries
            final_note["attachment_summaries"] = attachment_summaries
        else:
            final_note.setdefault("attachment_summaries_compact", attachment_summaries)
        final_note["consistency_check"] = consistency
        final_note["postprocess_artifacts"] = artifacts
        return final_note

    def _summarize_transcript_chunk(
        self,
        *,
        chunk_id: str,
        source_audio: str,
        source_title: str,
        char_start: int,
        char_end: int,
        text: str,
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        source_units = self._split_transcript_source_units(
            text,
            source_audio=source_audio,
            chunk_id=chunk_id,
            base_char_start=char_start,
        )
        prompt = (
            "你是会议逐字稿分片事实提取器。只输出合法 JSON，不要 Markdown 代码块。\n"
            f"{TRANSCRIPTION_DETAIL_FIDELITY_CONTRACT}\n"
            "这是局部 chunk，不要写全局结论，不要生成最终会议纪要。\n"
            "JSON 字段固定为 schema_version、chunk_id、source_audio、source_title、char_start、char_end、has_signal、signal_level、source_unit_coverage、local_topics、key_points、local_observations、local_decisions_or_claims、pending_questions、action_items、speaker_hints、sensitive_items、noise_or_irrelevant、coverage_note。\n"
            "source_unit_coverage 必须与输入 source_units 一一对应，顺序不变且每个 source_unit_id 只能出现一次。每项字段为 source_unit_id、disposition、theme、cleaned_details、duplicate_of、reason、speaker_hint、confidence。\n"
            "disposition 只能是 retained、duplicate、noise。retained 的 cleaned_details 必须是非空字符串数组：在不补造事实的前提下，把本来源段的全部不同实质信息逐条清理出来，保留主体、对象、限定条件、上下文、例子、数字、因果、否定、分歧和不确定性；不能压成一句上位概括。\n"
            "duplicate 只允许用于与本 chunk 另一来源段语义完全相同的复述，必须填写 duplicate_of；noise 只允许用于整段均为语气词、寒暄、口吃或无业务含义内容，必须填写具体 reason。敏感内容不是 noise，仍须 retained 并另行标记 sensitive_items。\n"
            "key_points 由系统根据 source_unit_coverage 生成，你可以返回空数组；不得用 key_points 代替逐段覆盖。\n"
            "local_decisions_or_claims 每项必须标明 status，使用 discussion_tendency / tentative_decision / confirmed_decision / claim 之一。\n"
            "sensitive_items 从本阶段就标记；每项保留原细节和 evidence_hash，并用 visibility=restricted/private、verification_status=unverified/verified、public_use=forbidden/allowed 表达权限与核验状态。敏感性不得成为删除、概括或省略实质信息的理由。\n"
            "如果本段主要是闲聊或噪声，has_signal=false，并在 noise_or_irrelevant 说明。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "chunk_id": chunk_id,
                "source_audio": source_audio,
                "source_title": source_title,
                "char_start": char_start,
                "char_end": char_end,
                "source_units": source_units,
            },
            ensure_ascii=False,
        )
        parsed = self._call_postprocess_json(prompt, user_content, env, "分片整理")
        coverage_error = self._transcription_source_unit_coverage_error(parsed, source_units, env)
        if coverage_error:
            repair_content = json.dumps(
                {
                    "coverage_errors": coverage_error,
                    "instruction": "重新输出完整 JSON，修复全部来源段覆盖错误；不得通过复制、赘述或把实质内容标成 noise 来凑长度。",
                    "source_units": source_units,
                    "previous_result": parsed,
                },
                ensure_ascii=False,
            )
            parsed = self._call_postprocess_json(prompt, repair_content, env, "分片整理覆盖修复")
            coverage_error = self._transcription_source_unit_coverage_error(parsed, source_units, env)
        if coverage_error:
            return {
                "status": "pending_manual",
                "reason": f"来源段覆盖校验失败：{coverage_error}",
            }
        self._materialize_source_unit_key_points(parsed, source_units)
        parsed["schema_version"] = TRANSCRIPTION_SOURCE_UNIT_SCHEMA_VERSION
        return parsed

    def _summarize_attachment_chunks(
        self,
        *,
        source_audio: str,
        source_title: str,
        chunks: list[dict[str, Any]],
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        prompt = (
            "你是单条录音的 reduce 合并器。只输出合法 JSON，不要 Markdown 代码块。\n"
            f"{TRANSCRIPTION_DETAIL_FIDELITY_CONTRACT}\n"
            "只基于 chunk JSON 合并，不要新增事实。需要按 evidence_hash/source range 去重 overlap 内容。\n"
            "JSON 字段固定为 schema_version、attachment_id、attachment_title、covered_chunks、covered_evidence_hashes、detail_coverage、signal_level、main_value、theme_sections、decisions、pending_questions、action_items、speaker_notes、sensitive_summary、low_value_ranges、duplicated_with、unique_contribution。\n"
            "covered_evidence_hashes 和 detail_coverage 由系统从逐段校验结果原样继承，你可以返回空数组；禁止重新改写、压缩或复制这些细节。\n"
            "theme_sections 不允许只有一句概括；每个主题必须保留背景、争议/判断依据、具体修改点、例子、风险和后续处理，能列点就列点。\n"
            "必须逐项合并 chunks 的全部非重复 key_points、local_observations、判断、数字、例子、条件和未决信息；不得为了缩短输出删除低频但有业务含义的细节。\n"
            "decisions 只能收录多处支持或明确表达的结论；局部倾向要写进 theme_sections，不能伪装成已决定。\n"
            "action_items 必须保留执行对象、动作、上下文和时间/节点；没有明确负责人的写未指定，不要删除。\n"
            "sensitive_summary 只记录 visibility、verification_status 和 public_use 等权限与核验标记，不是删除清单；对应实质细节必须同时保留在 theme_sections 和系统继承的 detail_coverage 中。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "attachment_id": source_audio,
                "source_title": source_title,
                "expected_evidence_hashes": sorted(self._transcription_evidence_hashes(chunks)),
                "chunks": self._compact_transcription_reduce_payloads(chunks),
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "单附件合并")

    def _summarize_attachment_group(self, group_index: int, attachments: list[dict[str, Any]], source_hint: str, env: dict[str, str]) -> dict[str, Any]:
        prompt = (
            "你是会议附件中间合并器。只输出合法 JSON，不要 Markdown 代码块。\n"
            f"{TRANSCRIPTION_DETAIL_FIDELITY_CONTRACT}\n"
            "基于 attachment summaries 合并，不要新增事实。输出字段：group_id、covered_attachments、covered_evidence_hashes、detail_coverage、signal_level、theme_sections、decisions、pending_questions、action_items、speaker_notes、sensitive_summary、unique_contribution。\n"
            "covered_evidence_hashes 和 detail_coverage 由系统从已校验附件原样继承，你可以返回空数组；禁止重新改写或压缩这些细节。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "group_id": f"group-{group_index:02d}",
                "expected_evidence_hashes": sorted(self._transcription_evidence_hashes(attachments)),
                "attachments": self._compact_transcription_reduce_payloads(attachments),
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "中间合并")

    def _summarize_global_note(self, summaries: list[dict[str, Any]], source_hint: str, env: dict[str, str]) -> dict[str, Any]:
        prompt = (
            "你是最终会议纪要整理器。只输出合法 JSON，不要 Markdown 代码块。\n"
            f"{TRANSCRIPTION_DETAIL_FIDELITY_CONTRACT}\n"
            "只基于 attachment/group summaries 生成最终纪要，不要读取或假设原始逐字稿外的信息。\n"
            "最终纪要是决策与执行接口，不是按发言顺序复述会议。内容充分优先，不限制结论摘要、决策清单、议题分析或其他清单的篇幅和条目数。\n"
            "JSON 字段固定为 title、meeting_info、conclusion_summary、decision_list、topic_cards、pending_decisions、validation_hypotheses、action_items、risks_and_constraints、next_meeting、topical_attachments、sensitive_summary、archive_macro_summary、archive_summary_bullets、covered_evidence_hashes、detail_coverage。说话人注册表和角色化文字稿由前序阶段注入，本阶段不得重新生成。\n"
            "covered_evidence_hashes 和 detail_coverage 由系统从已校验附件原样继承，输出时可保留为空数组；不得花费输出篇幅重写或压缩这些细节。\n"
            "title: 8-24 个汉字，必须是语义化会议主题，不得使用录音名、地点名、UUID、附件数量。\n"
            "meeting_info: 对象，固定字段 meeting_name、meeting_goal、meeting_time、participants、facilitator、minutes_owner、related_project、related_documents、version。来源明确会议目标时，meeting_goal 必须写成可判断是否完成的目标，不得写成“讨论某方案”这类活动描述；来源未明确统一会议目标时固定写“来源未明确会议目标”，不得把多个分享主题归纳成会议既定目标。其他来源未说明字段填写“未从来源识别”，不得猜测。\n"
            "conclusion_summary: 详细管理层摘要，对象固定含 overall_judgment、key_implications。overall_judgment 给出本次会议的总体判断、核心取舍和当前状态；key_implications 是对象数组，每项固定含 item、rationale、implications、related_ids。开放问题、验证假设、风险与约束分别只写入 pending_decisions、validation_hypotheses、risks_and_constraints，由渲染器并入第 1 节，禁止在 overall_judgment 或 key_implications 中逐条重复。\n"
            "来源中的个人判断、偏好、建议或可能性，除非来源明确形成会议共识，不得升级成“重点候选”、优先方向或会议结论。同一事项只允许出现在 conclusion_summary、pending_decisions、validation_hypotheses、risks_and_constraints 中语义最匹配的一个字段，禁止跨字段重复。\n"
            "decision_list: 详细决策清单数组，每项固定含 id、topic、decision、status、rationale、scope、review_condition、source_range；status 只能是 decided/tentative_direction/pending_validation/pending_decision。每项完整说明决策内容、依据、适用范围和来源约定的复审条件；来源未约定时固定写“来源未约定复审条件”，不得补造阈值。\n"
            "topic_cards: 议题分析数组，至少一项；每项固定含 id、topic、current_facts、core_question、options、conclusion_status、conclusion、unresolved_questions、next_step、source_ranges。current_facts 只写已知事实；options 是 {option,assessment} 对象数组；按问题结构整理，不按发言顺序。若议题已有 decision_list 记录，只引用决策 ID，不重复决策全文。\n"
            "pending_decisions: 待拍板清单数组，每项固定含 id、question、options、decision_owner、deadline、source_range；options 必须是数组。缺负责人或时间时写“未指定”。\n"
            "validation_hypotheses: 待验证假设清单数组，每项固定含 id、hypothesis、validation_method、metrics、pass_criteria、owner、source_range。不能靠继续讨论回答的问题才放这里；来源未给指标或标准时写“未指定”，不得发明。\n"
            "action_items: 行动项清单数组，每项固定含 id、action、assignee、deliverable、acceptance_criteria、deadline、dependencies、source_range。只有来源明确承诺或委派，且负责人、交付物、验收标准、截止时间都有来源依据时才能进入行动项；进入行动项后，负责人、交付物、验收标准、截止时间均不得省略。不能把探索方向、信息缺口、转写核验建议、“继续研究”或“进一步完善”升级成行动项。需要保留但不满足行动项条件的推进上下文，按语义放入 validation_hypotheses、topic_cards.next_step 或 topical_attachments，并明确“非会议承诺/责任与验收未指定”，不得删除。\n"
            "risks_and_constraints: 数组，每项固定含 risk、impact、mitigation、source_range；记录当前方案最可能失效的位置。\n"
            "next_meeting: 对象，固定含 trigger_conditions、required_materials、decisions_needed 三个数组；只记录来源明确约定的下次会议安排，来源未约定时三个数组均为空，不得从复审条件或验证事项自行生成会议安排。\n"
            "topical_attachments: 专题附件数组，每项固定含 id、title、status_note、summary、details、source_ranges。只放需要独立展开的详细框架、案例、技术路线或论证；status_note 必须说明这是结构化整理、是否已经形成正式决策。没有必要独立成文的专题材料时用空数组，不得为凑结构生成空附件。\n"
            "主纪要必须让未参会者完整回答：为什么开会、已知事实、做了什么决定、什么未决定、谁做什么、什么条件下重议。所有内容只保留一个规范位置：结论摘要只给总判断与跨议题影响，决策详情只在 decision_list，议题分析引用决策 ID，行动项只在 action_items，专题细节只在 topical_attachments。系统会把 detail_coverage 逐条渲染为主纪要的受限“细节保全附录”，因此任何未进入上述结构字段的非重复业务细节仍必须保留在 detail_coverage。\n"
            "detail_coverage 必须保留 summaries 中每条非重复业务细节，包括数字、报价、成本、公司与产品名称、技术路线、例子、替代方案、条件、因果、否定、争议、风险和未决信息；只删除语气词、赘余和语义完全重复内容。\n"
            "archive_macro_summary: 一句话宏观总结，说明本次转写的核心问题、判断或推进方向；只基于来源，不新增事实。\n"
            "archive_summary_bullets: 数组，1-5 条周记摘要，每条是一句话，覆盖最关键结论、边界或后续动作；不得超过 5 条。\n"
            "不得把讨论倾向升级成 decided，不得把待验证问题混入待拍板。敏感细节必须保留，只能标记 visibility、verification_status 和 public_use；禁止因敏感性删除、泛化或省略。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "expected_evidence_hashes": sorted(self._transcription_evidence_hashes(summaries)),
                "summaries": self._compact_transcription_reduce_payloads(summaries),
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "全局整理")

    def _check_global_note_consistency(self, final_note: dict[str, Any], attachments: list[dict[str, Any]], env: dict[str, str]) -> dict[str, Any]:
        prompt = (
            "你是会议纪要一致性检查器。只输出合法 JSON。\n"
            f"{TRANSCRIPTION_DETAIL_FIDELITY_CONTRACT}\n"
            "检查最终纪要是否有无来源结论、把讨论倾向误写成 decided、遗漏高信号附件、重复议题、行动项不可验收，或把实验问题误写成待拍板。\n"
            "来源中的个人判断、偏好、建议或可能性，除非来源明确形成会议共识，不得升级成“重点候选”、优先方向或会议结论。同一事项只允许出现在 conclusion_summary、pending_decisions、validation_hypotheses、risks_and_constraints 中语义最匹配的一个字段，出现跨字段重复时必须 approved=false。\n"
            "来源小段 ID、逐条 detail_coverage 和精确 source_range 已由系统完成一对一结构校验，本轮不要重抄或重新统计细节正文。比较 compact attachments 与 final note 的会议目标、总体判断、决策清单、议题分析、待拍板、待验证、行动项、风险和专题附件：任何无来源结论、决定状态升级、重要议题缺失、行动上下文丢失、内容重复或专题细节丢失都必须 approved=false。\n"
            "渲染契约：meeting_info 的固定字段写入 Obsidian 笔记属性；主纪要正文固定为“1 结论摘要、2 决策清单、3 议题分析与行动项、4 下次会议、5 细节保全附录（受限）、6 关联文档”。第 1 节由 conclusion_summary、pending_decisions、validation_hypotheses、risks_and_constraints 组合渲染，各字段不得重复同一内容。专题附件独立落盘并仅在第 6 节链接；没有专题内容时不得创建空附件。原字稿单独落盘，主纪要不得重复塞入说话人逐字稿。不得以 artifact 中存在证据为由放过会议目标空泛、决策缺依据/复审条件、议题分析缺事实/核心问题、行动项缺交付物/验收标准的问题。\n"
            "schema 与渲染边界：speaker_notes 和 labeled_transcript 由前序角色阶段固定注入，本轮输入不包含这两个大字段，也不得要求修改。来源没有明确统一会议目标时，meeting_info.meeting_goal 固定写“来源未明确会议目标”即为合格缺失标记，只能给 warning，禁止要求补造统一目标或以该缺失单独阻断。decision_list.status 和 topic_cards.conclusion_status 只能使用 decided、tentative_direction、pending_validation、pending_decision，禁止建议 confirmed_current_state 等 schema 外状态；既有现状用 tentative_direction 并在依据中注明“非本次新决策”。\n"
            "证据定位契约：系统已确认 evidence_hash 绑定具体来源小段，source_range 是该 source_unit 的精确字符范围；不得要求额外音频时间戳。\n"
            "行动语义必须稳定：只有来源明确承诺或委派，且负责人、交付物、验收标准、截止时间都有来源依据的事项才进入 action_items；其他推进上下文必须保留在 validation_hypotheses、topic_cards.next_step 或 topical_attachments，并明确非会议承诺，不得因不属于行动项而判定为遗漏。decision_list.review_condition 只接受来源明确约定，未约定时固定写“来源未约定复审条件”；next_meeting 只接受来源明确安排，不能由整理者推导。\n"
            "不以页数、字符数或条目数判定主纪要；明显丢失细节、重复内容或用上位概念替代多个具体事实属于阻断问题。需要独立展开的专题细节进入 topical_attachments；去掉语气词、口吃和语义完全重复不算遗漏。\n"
            "输出字段固定为 approved、blocking_issues、warnings、revision_notes。blocking_issues 每项必须是对象，固定含 issue、repair_fields、required_fix；repair_fields 必须是最终纪要顶层字段名数组，且只列实际需要修改的字段。"
        )
        user_content = json.dumps(
            {
                "final_note": {
                    key: value
                    for key, value in final_note.items()
                    if key not in {"detail_coverage", "covered_evidence_hashes", "speaker_notes", "labeled_transcript"}
                },
                "attachments": self._compact_transcription_reduce_payloads(attachments),
            },
            ensure_ascii=False,
        )
        parsed = self._call_postprocess_json(prompt, user_content, env, "一致性检查")
        if parsed.get("status") != "done":
            return {"approved": False, "blocking_issues": [parsed.get("reason") or "一致性检查失败"], "warnings": [], "revision_notes": ""}
        parsed.pop("status", None)
        return parsed

    def _repair_global_note_contract(
        self,
        final_note: dict[str, Any],
        attachments: list[dict[str, Any]],
        contract_errors: list[str],
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        prompt = (
            "你是会议纪要 JSON schema patch 生成器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "只输出 {\"repairs\": {...}}，repairs 只能包含 repair_fields 指定的字段；禁止输出或改写其他字段。\n"
            "只修复 contract_errors 指出的字段形状或缺失字段，不得新增 attachments 没有支撑的事实。\n"
            "meeting_info、conclusion_summary、decision_list、topic_cards、pending_decisions、validation_hypotheses、action_items、risks_and_constraints、next_meeting、topical_attachments 必须遵守最终会议纪要的决策接口 schema；来源未说明的负责人、时间、指标、标准或依赖写“未指定”，不得猜测。\n"
            "speaker_notes、labeled_transcript、covered_evidence_hashes 和 detail_coverage 由系统固定保留，不得修复或返回。"
        )
        repair_fields = sorted(self._transcription_contract_error_fields(contract_errors))
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "contract_errors": contract_errors,
                "repair_fields": repair_fields,
                "final_note": {
                    key: value
                    for key, value in final_note.items()
                    if key not in {"detail_coverage", "covered_evidence_hashes", "speaker_notes", "labeled_transcript"}
                },
                "attachments": self._compact_transcription_reduce_payloads(attachments),
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "全局纪要 schema 修复")

    def _repair_global_note_contract_with_retries(
        self,
        final_note: dict[str, Any],
        attachments: list[dict[str, Any]],
        contract_errors: list[str],
        source_hint: str,
        env: dict[str, str],
    ) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
        repaired_note = dict(final_note)
        remaining_errors = list(contract_errors)
        history: list[dict[str, Any]] = []
        max_attempts = max(
            1,
            min(self._env_int(env, "TRANSCRIPTION_SCHEMA_REPAIR_MAX_ATTEMPTS", 3), 5),
        )

        for attempt in range(1, max_attempts + 1):
            if not remaining_errors:
                break
            repair_fields = self._transcription_contract_error_fields(remaining_errors)
            if not repair_fields:
                history.append(
                    {
                        "attempt": attempt,
                        "status": "not_repairable",
                        "errors_before": remaining_errors,
                        "repair_fields": [],
                        "errors_after": remaining_errors,
                    }
                )
                break

            repair_payload = self._repair_global_note_contract(
                repaired_note,
                attachments,
                remaining_errors,
                source_hint,
                env,
            )
            repairs = repair_payload.get("repairs") if isinstance(repair_payload.get("repairs"), dict) else {}
            applied_fields = repair_fields.intersection(repairs)
            attempt_record: dict[str, Any] = {
                "attempt": attempt,
                "status": repair_payload.get("status", "pending_manual"),
                "errors_before": remaining_errors,
                "repair_fields": sorted(repair_fields),
                "applied_fields": sorted(applied_fields),
            }
            if repair_payload.get("status") != "done" or not applied_fields:
                attempt_record["reason"] = str(repair_payload.get("reason") or "schema 修复未返回可应用字段")
                attempt_record["errors_after"] = remaining_errors
                history.append(attempt_record)
                continue

            candidate = dict(repaired_note)
            self._apply_transcription_field_repairs(
                candidate,
                repairs,
                applied_fields,
                merge_list_items=True,
            )
            candidate.pop("status", None)
            candidate_errors = validate_transcription_final_note_contract(candidate)
            attempt_record["errors_after"] = candidate_errors
            history.append(attempt_record)
            repaired_note = candidate
            remaining_errors = candidate_errors

        return repaired_note, remaining_errors, history

    @staticmethod
    def _transcription_contract_error_fields(contract_errors: list[str]) -> set[str]:
        known_fields = set(TRANSCRIPTION_FINAL_NOTE_REQUIRED_FIELDS)
        fields: set[str] = set()
        for error in contract_errors:
            for field in known_fields:
                if field in str(error):
                    fields.add(field)
        return fields

    @staticmethod
    def _transcription_consistency_repair_fields(consistency: dict[str, Any]) -> set[str]:
        issues = consistency.get("blocking_issues") if isinstance(consistency.get("blocking_issues"), list) else []
        repairable_fields = {
            "meeting_info",
            "conclusion_summary",
            "decision_list",
            "topic_cards",
            "pending_decisions",
            "validation_hypotheses",
            "action_items",
            "risks_and_constraints",
            "next_meeting",
            "topical_attachments",
            "sensitive_summary",
            "archive_macro_summary",
            "archive_summary_bullets",
        }
        fields: set[str] = set()
        issue_texts: list[str] = []
        for issue in issues:
            if isinstance(issue, dict):
                requested = issue.get("repair_fields")
                if isinstance(requested, list):
                    fields.update(str(field) for field in requested if str(field) in repairable_fields)
                issue_texts.append(json.dumps(issue, ensure_ascii=False))
            else:
                issue_texts.append(str(issue))
        for text in issue_texts:
            fields.update(field for field in repairable_fields if field in text)
        aliases = {
            "会议目标": {"meeting_info"},
            "结论摘要": {"conclusion_summary"},
            "决策清单": {"decision_list"},
            "复审条件": {"decision_list"},
            "议题卡": {"topic_cards"},
            "待拍板": {"pending_decisions"},
            "待验证": {"validation_hypotheses"},
            "行动项": {"action_items"},
            "风险与约束": {"risks_and_constraints"},
            "下次会议": {"next_meeting"},
            "专题附件": {"topical_attachments"},
        }
        for text in issue_texts:
            for phrase, mapped_fields in aliases.items():
                if phrase in text:
                    fields.update(mapped_fields)
        return fields

    def _revise_global_note(
        self,
        final_note: dict[str, Any],
        attachments: list[dict[str, Any]],
        consistency: dict[str, Any],
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        prompt = (
            "你是会议纪要字段 patch 生成器。只输出合法 JSON，不要 Markdown 代码块。\n"
            f"{TRANSCRIPTION_DETAIL_FIDELITY_CONTRACT}\n"
            "任务：基于一致性检查结果，只修复 repair_fields 指定字段。只输出 {\"repairs\": {...}}，repairs 只能包含 repair_fields，禁止输出或改写其他字段。\n"
            "repairs 中的列表字段必须返回修订后的完整列表：包含全部应保留项，省略全部应删除项；系统会完整替换该字段，禁止只返回增量、追加项或单项 patch。\n"
            "必须修复 blocking_issues 指出的错误；不得新增 attachments 中没有来源支撑的事实。\n"
            "个人判断、偏好、建议或可能性不得升级成“重点候选”、优先方向或会议结论；若草稿已经升级，必须删除该升级，并把 conclusion_summary、pending_decisions、validation_hypotheses、risks_and_constraints 中的同一事项收敛到唯一正确字段。\n"
            "行动项只保留来源明确承诺或委派，且负责人、交付物、验收标准、截止时间都有来源依据的事项。其他推进上下文必须保留并移入 validation_hypotheses、topic_cards.next_step 或 topical_attachments，明确非会议承诺并保留来源细节，禁止直接删除或再次升级为行动项。decision_list.review_condition 无来源约定时固定写“来源未约定复审条件”；next_meeting 无来源明确安排时三个数组均为空。\n"
            "禁止返回 covered_evidence_hashes、detail_coverage、speaker_notes 或 labeled_transcript，它们由系统原样保留。不得限制篇幅或清单条目数；保持总体结论、决策详情、议题分析、行动项和独立专题附件之间不重复，待拍板与待验证分开。"
        )
        repair_fields = sorted(self._transcription_consistency_repair_fields(consistency))
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "repair_fields": repair_fields,
                "final_note": {
                    key: value
                    for key, value in final_note.items()
                    if key not in {"detail_coverage", "covered_evidence_hashes", "speaker_notes", "labeled_transcript"}
                },
                "attachments": self._compact_transcription_reduce_payloads(attachments),
                "consistency": consistency,
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "一致性修订")

    def _run_job(self, endpoint: str, url: str, *, poll_attempts: int | None = None) -> dict[str, Any]:
        if not self.base_url:
            return {"status": "pending_manual", "reason": "content-flow base_url 未配置"}
        try:
            response = self.session.post(f"{self.base_url}{endpoint}", json={"url": url}, timeout=10)
            response.raise_for_status()
            data = response.json()
            job_id = data.get("job_id") or data.get("id")
            if not job_id:
                return {"status": "done", **data}
            attempts = self._poll_attempts_for_endpoint(endpoint, poll_attempts)
            for _ in range(attempts):
                status_resp = self.session.get(f"{self.base_url}/api/status", params={"job_id": job_id}, timeout=10)
                status_resp.raise_for_status()
                status_data = status_resp.json()
                status = status_data.get("status", "")
                if status in {"done", "completed", "success"}:
                    result = status_data.get("result") if isinstance(status_data.get("result"), dict) else {}
                    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
                    analysis_path = str(result.get("analysis_path") or "")
                    if not analysis and analysis_path:
                        try:
                            loaded = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
                            if isinstance(loaded, dict):
                                analysis = loaded
                        except Exception:
                            analysis = {}
                    media_dir = str(result.get("media_dir") or "")
                    video_path = str(result.get("video_path") or "")
                    if not video_path and media_dir:
                        candidate = Path(media_dir) / "video.mp4"
                        if candidate.is_file() and candidate.stat().st_size > 0:
                            video_path = str(candidate)
                    audio_path = str(result.get("audio_path") or "")
                    if not audio_path and media_dir:
                        candidate = Path(media_dir) / "audio.mp3"
                        if candidate.is_file() and candidate.stat().st_size > 0:
                            audio_path = str(candidate)
                    caption_path = str(result.get("caption_path") or "")
                    if not caption_path and media_dir:
                        candidate = Path(media_dir) / "caption.txt"
                        if candidate.is_file():
                            caption_path = str(candidate)
                    transcript_path = str(result.get("transcript_path") or "")
                    if not transcript_path and media_dir:
                        candidate = Path(media_dir) / "transcript.txt"
                        if candidate.is_file():
                            transcript_path = str(candidate)
                    caption = str(result.get("caption") or analysis.get("caption") or "")
                    if not caption and caption_path:
                        try:
                            caption = Path(caption_path).read_text(encoding="utf-8").strip()
                        except Exception:
                            caption = ""
                    image_paths = result.get("image_paths", [])
                    if not isinstance(image_paths, list):
                        image_paths = []
                    if not image_paths and media_dir:
                        image_dir = Path(media_dir) / "images"
                        if image_dir.is_dir():
                            image_paths = [
                                str(path)
                                for path in sorted(image_dir.rglob("*"))
                                if path.is_file() and path.stat().st_size > 0
                            ]
                    payload = {
                        "status": "done",
                        "job_id": job_id,
                        "media_dir": media_dir,
                        "analysis_path": analysis_path,
                        "transcript_path": transcript_path,
                        "caption_path": caption_path,
                        "caption": caption,
                        "ocr_path": result.get("ocr_path", ""),
                        "image_ocr": result.get("image_ocr") or analysis.get("image_ocr") or "",
                        "video_path": video_path,
                        "audio_path": audio_path,
                        "image_paths": image_paths,
                        "media_type": result.get("media_type") or analysis.get("media_type") or "",
                        "interaction_screenshot_path": result.get("interaction_screenshot_path", ""),
                    }
                    if analysis:
                        payload["analysis"] = analysis
                    if endpoint == "/api/analyze":
                        payload = self._complete_analysis_payload(url, payload, wait=True)
                    return payload
                if status in {"failed", "error"}:
                    return {"status": "pending_manual", "reason": str(status_data)}
                time.sleep(self.poll_interval_seconds)
            return {"status": "pending_manual", "reason": f"轮询超时 job_id={job_id}"}
        except Exception as exc:
            return {"status": "pending_manual", "reason": str(exc)}

    @staticmethod
    def _parse_last_json_line(output: str) -> dict[str, Any]:
        for line in reversed((output or "").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    @staticmethod
    def _parse_json_payload(text: str) -> dict[str, Any]:
        value = (text or "").strip()
        if not value:
            return {}
        try:
            payload = json.loads(value)
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            pass

        decoder = json.JSONDecoder()
        candidate_payload: dict[str, Any] = {}
        preferred_keys = {
            "analysis",
            "meeting_info",
            "conclusion_summary",
            "decision_list",
            "topic_cards",
            "pending_decisions",
            "validation_hypotheses",
            "risks_and_constraints",
            "next_meeting",
            "topical_attachments",
            "labeled_transcript",
            "pending_questions",
            "primary_category",
            "speaker_notes",
            "status",
            "summary",
            "title",
            "mode",
            "items",
            "checklist_tree",
            "due_at",
            "remind_at",
            "confidence",
            "missing_fields",
        }
        for match in re.finditer(r"\{", value):
            try:
                payload, _ = decoder.raw_decode(value[match.start() :])
            except ValueError:
                continue
            if not isinstance(payload, dict):
                continue
            if any(key in payload for key in preferred_keys):
                return payload
            if not candidate_payload:
                candidate_payload = payload
        return candidate_payload

    def _call_postprocess_json(
        self,
        prompt: str,
        user_content: str,
        env: dict[str, str],
        stage: str,
        *,
        timeout_seconds: float | None = None,
        max_retries: int = 1,
        thinking: str | None = None,
    ) -> dict[str, Any]:
        return self._call_profile_provider_json(
            "transcription_postprocess",
            prompt,
            user_content,
            stage,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            thinking=thinking,
        )

    def _call_profile_provider_json(
        self,
        profile_name: str,
        prompt: str,
        user_content: str,
        stage: str,
        *,
        timeout_seconds: float | None = None,
        max_retries: int = 1,
        thinking: str | None = None,
        parts: list[dict[str, Any]] | None = None,
        capacity_max_retries: int | None = None,
    ) -> dict[str, Any]:
        profile = profile_config(profile_name)
        configured = load_profile_llm_settings(profile_name)
        settings = LLMProviderSettings(
            model=configured.model,
            base_url=configured.base_url,
            api_key=configured.api_key,
            api_type=configured.api_type,
            timeout=float(timeout_seconds or profile.get("timeout") or configured.timeout or 300),
            thinking=str(thinking if thinking is not None else profile.get("thinking") or configured.thinking or "").strip(),
            bin=configured.bin,
            agent=configured.agent,
            cwd=configured.cwd,
            codex_home=configured.codex_home,
        )
        try:
            parsed = generate_json_from_parts(
                parts or [{"text": user_content}],
                settings,
                max_retries=max(0, int(max_retries)),
                capacity_max_retries=max(
                    max(0, int(max_retries)),
                    int(profile.get("capacity_max_retries") or 0) if capacity_max_retries is None else max(0, int(capacity_max_retries)),
                ),
                error_prefix=f"{stage} JSON 校验失败",
                instructions=prompt,
                validation_contract=CONTENT_FLOW_VALIDATION_CONTRACT,
                validation_context={"profile_name": profile_name, "stage": stage},
            )
            if not parsed:
                return {"status": "pending_manual", "reason": f"{stage}：{profile_name} 未返回可解析 JSON"}
            return {
                "status": "done",
                "postprocess_provider": str(profile.get("provider") or "").strip() or profile_name,
                "postprocess_model": settings.model,
                **parsed,
            }
        except Exception as exc:
            if profile_name == "daily_task_extraction" and is_model_capacity_failure(exc):
                return {
                    "status": "pending_manual",
                    "error_code": "DAILY_LLM_MODEL_AT_CAPACITY",
                    "reason": "模型当前容量已满，待办未创建、未落盘。",
                    "detail": model_capacity_failure_detail(exc),
                    "suggested_action": "请稍后直接重试原消息。",
                }
            return {"status": "pending_manual", "reason": f"{stage}：{exc}"}

    @staticmethod
    def _split_transcript_audio_sections(text: str) -> list[dict[str, Any]]:
        value = (text or "").strip()
        if not value:
            return []
        pattern = re.compile(r"^###\s*(?:录音|文字稿)\s*(\d+)\s*[:：]\s*(.+?)\s*$", re.M)
        matches = list(pattern.finditer(value))
        if not matches:
            return [{"source_audio": "audio-01", "source_title": "录音 1", "text": value, "char_start": 0, "char_end": len(value)}]

        sections: list[dict[str, Any]] = []
        for item_index, match in enumerate(matches):
            start = match.end()
            end = matches[item_index + 1].start() if item_index + 1 < len(matches) else len(value)
            body = value[start:end].strip()
            if not body:
                continue
            try:
                audio_index = int(match.group(1))
            except ValueError:
                audio_index = item_index + 1
            sections.append(
                {
                    "source_audio": f"audio-{audio_index:02d}",
                    "source_title": match.group(2).strip() or f"录音 {audio_index}",
                    "text": body,
                    "char_start": start,
                    "char_end": end,
                }
            )
        return sections or [{"source_audio": "audio-01", "source_title": "录音 1", "text": value, "char_start": 0, "char_end": len(value)}]

    @staticmethod
    def _split_text_chunks(text: str, target_chars: int, max_chars: int, overlap_chars: int) -> list[dict[str, Any]]:
        value = text or ""
        if not value.strip():
            return []
        target = max(1000, int(target_chars or 10000))
        limit = max(target, int(max_chars or target))
        overlap = max(0, min(int(overlap_chars or 0), target // 2))
        length = len(value)
        if length <= limit:
            return [{"char_start": 0, "char_end": length, "text": value.strip()}]

        chunks: list[dict[str, Any]] = []
        pos = 0
        while pos < length:
            window_end = min(length, pos + limit)
            if window_end >= length:
                end = length
            else:
                window = value[pos:window_end]
                min_boundary = min(len(window), max(1, int(target * 0.65)))
                candidates = [match.end() for match in re.finditer(r"[。！？!?]\s*|\n{2,}", window) if match.end() >= min_boundary]
                end = pos + (candidates[-1] if candidates else min(target, len(window)))
            if end <= pos:
                end = min(length, pos + limit)

            raw = value[pos:end]
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw) - len(raw.rstrip())
            char_start = pos + leading
            char_end = end - trailing
            chunk_text = value[char_start:char_end]
            if chunk_text.strip():
                chunks.append({"char_start": char_start, "char_end": char_end, "text": chunk_text.strip()})
            if end >= length:
                break
            next_pos = max(0, end - overlap)
            pos = next_pos if next_pos > pos else end
        return chunks

    @staticmethod
    def _split_transcript_source_units(
        text: str,
        *,
        source_audio: str,
        chunk_id: str,
        base_char_start: int,
    ) -> list[dict[str, Any]]:
        value = text or ""
        if not value.strip():
            return []
        units: list[dict[str, Any]] = []
        pos = 0
        length = len(value)
        while pos < length:
            window_end = min(length, pos + TRANSCRIPTION_SOURCE_UNIT_MAX_CHARS)
            if window_end >= length:
                end = length
            else:
                window = value[pos:window_end]
                minimum = min(len(window), int(TRANSCRIPTION_SOURCE_UNIT_TARGET_CHARS * 0.65))
                boundaries = [
                    match.end()
                    for match in re.finditer(r"[。！？!?]\s*|\n+", window)
                    if match.end() >= minimum
                ]
                end = pos + (boundaries[-1] if boundaries else min(TRANSCRIPTION_SOURCE_UNIT_TARGET_CHARS, len(window)))
            if end <= pos:
                end = min(length, pos + TRANSCRIPTION_SOURCE_UNIT_MAX_CHARS)
            raw = value[pos:end]
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw) - len(raw.rstrip())
            relative_start = pos + leading
            relative_end = end - trailing
            unit_text = value[relative_start:relative_end]
            if unit_text:
                absolute_start = base_char_start + relative_start
                absolute_end = base_char_start + relative_end
                units.append(
                    {
                        "source_unit_id": f"{source_audio}-u-{absolute_start:06d}-{absolute_end:06d}",
                        "chunk_id": chunk_id,
                        "char_start": absolute_start,
                        "char_end": absolute_end,
                        "text": unit_text,
                    }
                )
            pos = end
        return units

    @classmethod
    def _transcription_source_unit_coverage_error(
        cls,
        payload: dict[str, Any],
        source_units: list[dict[str, Any]],
        env: dict[str, str],
    ) -> str:
        expected = {str(unit.get("source_unit_id") or ""): unit for unit in source_units}
        raw_items = payload.get("source_unit_coverage") if isinstance(payload, dict) else None
        items = raw_items if isinstance(raw_items, list) else []
        seen: set[str] = set()
        duplicate_ids: set[str] = set()
        unknown_ids: set[str] = set()
        invalid_items = 0
        discarded_chars = 0
        retained_source_chars = 0
        retained_detail_chars = 0
        for item in items:
            if not isinstance(item, dict):
                invalid_items += 1
                continue
            unit_id = str(item.get("source_unit_id") or "").strip()
            if unit_id in seen:
                duplicate_ids.add(unit_id)
            seen.add(unit_id)
            unit = expected.get(unit_id)
            if unit is None:
                unknown_ids.add(unit_id)
                continue
            source_chars = cls._transcription_semantic_char_count(str(unit.get("text") or ""))
            disposition = str(item.get("disposition") or "").strip()
            details = item.get("cleaned_details")
            cleaned = [str(detail).strip() for detail in details if str(detail).strip()] if isinstance(details, list) else []
            if disposition == "retained":
                if not cleaned or not str(item.get("theme") or "").strip():
                    invalid_items += 1
                    continue
                retained_source_chars += source_chars
                retained_detail_chars += sum(cls._transcription_semantic_char_count(detail) for detail in cleaned)
            elif disposition == "duplicate":
                duplicate_of = str(item.get("duplicate_of") or "").strip()
                if duplicate_of not in expected or duplicate_of == unit_id:
                    invalid_items += 1
                discarded_chars += source_chars
            elif disposition == "noise":
                if not str(item.get("reason") or "").strip():
                    invalid_items += 1
                discarded_chars += source_chars
            else:
                invalid_items += 1

        missing_ids = set(expected) - seen
        total_source_chars = sum(cls._transcription_semantic_char_count(str(unit.get("text") or "")) for unit in source_units)
        min_retained_ratio = cls._env_float(
            env,
            "TRANSCRIPTION_SOURCE_UNIT_MIN_RETAINED_RATIO",
            TRANSCRIPTION_SOURCE_UNIT_MIN_RETAINED_RATIO,
        )
        max_discarded_ratio = cls._env_float(
            env,
            "TRANSCRIPTION_SOURCE_UNIT_MAX_DISCARDED_RATIO",
            TRANSCRIPTION_SOURCE_UNIT_MAX_DISCARDED_RATIO,
        )
        issues: list[str] = []
        if missing_ids:
            issues.append(f"缺少 {len(missing_ids)} 个来源段")
        if unknown_ids:
            issues.append(f"包含 {len(unknown_ids)} 个未知来源段")
        if duplicate_ids:
            issues.append(f"包含 {len(duplicate_ids)} 个重复来源段")
        if invalid_items:
            issues.append(f"存在 {invalid_items} 个无效覆盖项")
        if total_source_chars and discarded_chars / total_source_chars > max_discarded_ratio:
            issues.append(
                f"标记为重复或噪声的来源内容占比 {discarded_chars / total_source_chars:.1%}，超过 {max_discarded_ratio:.0%}"
            )
        if retained_source_chars and retained_detail_chars / retained_source_chars < min_retained_ratio:
            issues.append(
                f"清理后细节字符占比 {retained_detail_chars / retained_source_chars:.1%}，低于 {min_retained_ratio:.0%}，存在过度压缩"
            )
        return "；".join(issues)

    @staticmethod
    def _transcription_semantic_char_count(value: str) -> int:
        return len(re.sub(r"[\s\W_]+", "", value or "", flags=re.UNICODE))

    @staticmethod
    def _env_float(env: dict[str, str], key: str, default: float) -> float:
        try:
            return float(str(env.get(key, default)).strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _materialize_source_unit_key_points(
        payload: dict[str, Any],
        source_units: list[dict[str, Any]],
    ) -> None:
        source_by_id = {str(unit.get("source_unit_id") or ""): unit for unit in source_units}
        key_points: list[dict[str, Any]] = []
        coverage = payload.get("source_unit_coverage")
        for item in coverage if isinstance(coverage, list) else []:
            if not isinstance(item, dict) or item.get("disposition") != "retained":
                continue
            unit_id = str(item.get("source_unit_id") or "").strip()
            unit = source_by_id.get(unit_id)
            if not unit:
                continue
            details = item.get("cleaned_details")
            for detail_index, detail in enumerate(details if isinstance(details, list) else [], start=1):
                point = str(detail or "").strip()
                if not point:
                    continue
                normalized_point = re.sub(r"\s+", "", point).lower()
                evidence_hash = hashlib.sha256(
                    f"{unit_id}:{detail_index}:{normalized_point}".encode("utf-8")
                ).hexdigest()[:16]
                key_points.append(
                    {
                        "point": point,
                        "theme": str(item.get("theme") or "其他讨论").strip() or "其他讨论",
                        "speaker_hint": str(item.get("speaker_hint") or "").strip(),
                        "confidence": str(item.get("confidence") or "").strip(),
                        "source_unit_id": unit_id,
                        "evidence_hash": evidence_hash,
                        "source_range": {
                            "source_audio": str(unit_id).split("-u-", 1)[0],
                            "chunk_id": unit.get("chunk_id"),
                            "char_start": unit.get("char_start"),
                            "char_end": unit.get("char_end"),
                        },
                    }
                )
        payload["key_points"] = key_points

    @staticmethod
    def _transcription_evidence_hashes(payloads: list[dict[str, Any]]) -> set[str]:
        hashes: set[str] = set()
        for payload in payloads:
            covered = payload.get("covered_evidence_hashes")
            if isinstance(covered, list):
                hashes.update(str(value).strip() for value in covered if str(value).strip())
            items = payload.get("key_points")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                value = str(item.get("evidence_hash") or "").strip()
                if value:
                    hashes.add(value)
        return hashes

    @staticmethod
    def _merge_transcription_detail_coverage(
        payloads: list[dict[str, Any]],
        expected_hashes: set[str],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for payload in payloads:
            items = payload.get("detail_coverage")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                evidence_hash = str(item.get("evidence_hash") or "").strip()
                if evidence_hash not in expected_hashes or evidence_hash in seen:
                    continue
                merged.append(dict(item))
                seen.add(evidence_hash)
        return merged

    @staticmethod
    def _detail_coverage_from_key_points(
        payloads: list[dict[str, Any]],
        expected_hashes: set[str],
    ) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        seen: set[str] = set()
        for payload in payloads:
            items = payload.get("key_points")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                evidence_hash = str(item.get("evidence_hash") or "").strip()
                point = str(item.get("point") or "").strip()
                if evidence_hash not in expected_hashes or evidence_hash in seen or not point:
                    continue
                details.append(
                    {
                        "evidence_hash": evidence_hash,
                        "theme": str(item.get("theme") or "其他讨论").strip() or "其他讨论",
                        "detail": point,
                        "source_range": item.get("source_range") if isinstance(item.get("source_range"), dict) else {},
                    }
                )
                seen.add(evidence_hash)
        return details

    @staticmethod
    def _compact_transcription_reduce_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        excluded = {"source_unit_coverage", "detail_coverage", "covered_evidence_hashes"}
        compacted: list[dict[str, Any]] = []
        for payload in payloads:
            compacted.append({key: value for key, value in payload.items() if key not in excluded})
        return compacted

    @staticmethod
    def _transcription_coverage_error(payload: dict[str, Any], expected_hashes: set[str]) -> str:
        if not expected_hashes:
            return ""
        raw_covered = payload.get("covered_evidence_hashes")
        covered = {
            str(value).strip()
            for value in raw_covered
            if str(value).strip()
        } if isinstance(raw_covered, list) else set()
        missing = expected_hashes - covered
        unknown = covered - expected_hashes
        detail_items = payload.get("detail_coverage")
        detail_ids: list[str] = []
        incomplete_detail_ids: set[str] = set()
        if isinstance(detail_items, list):
            for item in detail_items:
                if not isinstance(item, dict):
                    continue
                evidence_hash = str(item.get("evidence_hash") or "").strip()
                if not evidence_hash:
                    continue
                detail_ids.append(evidence_hash)
                if not str(item.get("theme") or "").strip() or not str(item.get("detail") or "").strip():
                    incomplete_detail_ids.add(evidence_hash)
        detail_id_set = set(detail_ids)
        missing_details = expected_hashes - detail_id_set
        unknown_details = detail_id_set - expected_hashes
        duplicate_details = len(detail_ids) - len(detail_id_set)
        issues: list[str] = []
        if missing:
            issues.append(f"缺少 {len(missing)} 个来源细节 ID")
        if unknown:
            issues.append(f"包含 {len(unknown)} 个无来源细节 ID")
        if missing_details:
            issues.append(f"缺少 {len(missing_details)} 条来源细节正文")
        if unknown_details:
            issues.append(f"包含 {len(unknown_details)} 条无来源细节正文")
        if incomplete_detail_ids:
            issues.append(f"存在 {len(incomplete_detail_ids)} 条主题或正文为空的细节")
        if duplicate_details:
            issues.append(f"存在 {duplicate_details} 条重复细节 ID")
        return "；".join(issues)

    @staticmethod
    def _annotate_evidence_hashes(summary: dict[str, Any]) -> None:
        chunk_id = str(summary.get("chunk_id") or "").strip()
        source_audio = str(summary.get("source_audio") or "").strip()
        char_start = summary.get("char_start")
        char_end = summary.get("char_end")
        fields = (
            "key_points",
            "local_observations",
            "local_decisions_or_claims",
            "pending_questions",
            "action_items",
            "sensitive_items",
        )
        for field in fields:
            items = summary.get(field)
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict) and str(item or "").strip():
                    item = {"text": str(item).strip()}
                    items[index] = item
                if not isinstance(item, dict):
                    continue
                basis = str(
                    item.get("evidence")
                    or item.get("point")
                    or item.get("claim")
                    or item.get("question")
                    or item.get("action")
                    or item.get("summary")
                    or item.get("text")
                    or item.get("content")
                    or item.get("item")
                    or item.get("task")
                    or item.get("detail")
                    or ""
                )
                normalized = re.sub(r"\s+", "", basis).lower()
                if normalized and not item.get("evidence_hash"):
                    item["evidence_hash"] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
                if not item.get("source_range"):
                    item["source_range"] = {
                        "source_audio": source_audio,
                        "chunk_id": chunk_id,
                        "char_start": char_start,
                        "char_end": char_end,
                    }

    @staticmethod
    def _read_json_artifact(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _latest_transcription_global_note_artifact(cls, root: Path) -> dict[str, Any]:
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        paths = [
            root / "global-note-draft.json",
            root / "global-note-revised.json",
            *sorted(root.glob("global-note-revised-[0-9][0-9].json")),
        ]
        for priority, path in enumerate(paths):
            payload = cls._read_json_artifact(path)
            if not payload or not all(field in payload for field in TRANSCRIPTION_FINAL_NOTE_REQUIRED_FIELDS):
                continue
            try:
                modified_at = path.stat().st_mtime_ns
            except OSError:
                continue
            candidates.append((modified_at, priority, payload))
        return max(candidates, default=(0, 0, {}), key=lambda item: (item[0], item[1]))[2]

    @staticmethod
    def _apply_transcription_field_repairs(
        note: dict[str, Any],
        repairs: dict[str, Any],
        fields: set[str],
        *,
        merge_list_items: bool = False,
    ) -> None:
        for field in fields:
            current = note.get(field)
            repair = repairs[field]
            if isinstance(current, dict) and isinstance(repair, dict):
                note[field] = {**current, **repair}
                continue
            if merge_list_items and isinstance(current, list) and isinstance(repair, dict):
                indexed_repairs: list[tuple[int, dict[str, Any]]] = []
                for raw_index, item_patch in repair.items():
                    index_text = str(raw_index)
                    if (
                        not index_text.isdigit()
                        or not isinstance(item_patch, dict)
                        or int(index_text) >= len(current)
                        or not isinstance(current[int(index_text)], dict)
                    ):
                        indexed_repairs = []
                        break
                    indexed_repairs.append((int(index_text), item_patch))
                if indexed_repairs:
                    merged = [dict(item) if isinstance(item, dict) else item for item in current]
                    for index, item_patch in indexed_repairs:
                        merged[index] = {**merged[index], **item_patch}
                    note[field] = merged
                    continue
            if merge_list_items and isinstance(current, list) and isinstance(repair, list):
                repair_has_stable_ids = bool(repair) and all(
                    isinstance(item, dict) and str(item.get("id") or "").strip()
                    for item in repair
                )
                if not repair_has_stable_ids:
                    note[field] = repair
                    continue
                merged = [dict(item) if isinstance(item, dict) else item for item in current]
                positions = {
                    str(item.get("id")): index
                    for index, item in enumerate(merged)
                    if isinstance(item, dict) and str(item.get("id") or "").strip()
                }
                for item in repair:
                    item_id = str(item.get("id") or "").strip() if isinstance(item, dict) else ""
                    if item_id and item_id in positions and isinstance(merged[positions[item_id]], dict):
                        index = positions[item_id]
                        merged[index] = {**merged[index], **item}
                    else:
                        merged.append(item)
                note[field] = merged
                continue
            note[field] = repair

    @staticmethod
    def _write_json_artifact(root: Path, filename: str, payload: dict[str, Any]) -> str:
        path = ensure_dir(root) / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(path)

    @staticmethod
    def _env_int(env: dict[str, str], key: str, default: int) -> int:
        try:
            return int(float(str(env.get(key, default)).strip()))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _env_truthy(value: str) -> bool:
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _content_flow_env() -> dict[str, str]:
        env = dict(os.environ)
        for env_path in (CONTENT_FLOW_ROOT / ".env", CONTENT_FLOW_SECRET_ENV_PATH):
            if not env_path.is_file():
                continue
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return env

    @staticmethod
    def _transcription_timeout_seconds(env: dict[str, str]) -> int:
        base = env.get("CODEX_RESPONSES_TRANSCRIPTION_TIMEOUT") or env.get("TRANSCRIPTION_TIMEOUT") or "1800"
        try:
            return max(300, int(float(base)) + 120)
        except ValueError:
            return 1920

    @staticmethod
    def _clean_transcription_error(text: str) -> str:
        value = (text or "").strip()
        if not value:
            return "本地转写失败"
        value = re.sub(r"\n+", "\n", value)
        value = re.sub(r"Command '\[.*?\]' timed out after [0-9.]+ seconds", "录音转写超时", value, flags=re.S)
        return value[-800:]
