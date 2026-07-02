from __future__ import annotations

import html
import json
import math
import mimetypes
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

from common.llm_client import generate_json_from_parts
from common.llm_settings import LLMProviderSettings

from .media_text_cleaner import MEDIA_TEXT_CLEANER, MediaCopyParts
from .transcription_postprocess_contract import (
    transcription_final_note_value_missing,
    validate_transcription_final_note_contract,
)
from .utils import ensure_dir
from ..router.openclaw_bot_llm import (
    profile_config,
    profile_provider_runtime,
)


CONTENT_FLOW_ROOT = Path(os.getenv("CONTENT_FLOW_ROOT", "/home/ubuntu/selfmedia-tools/selfmedia/ingest/content_flow"))


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
        if not analysis:
            return False
        if analysis.get("analysis_status") == "needs_model_rerun":
            return False
        if analysis.get("incomplete_reason"):
            return False
        for key in (
            "summary",
            "breakdown",
            "hooks",
            "action_plan",
            "hidden_info",
            "visual_cues",
            "transferable_expression",
            "target_audience",
            "pain_point",
            "work_copy",
            "tags",
            "title",
        ):
            value = analysis.get(key)
            if value not in (None, "", [], {}):
                return True
        return False

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
            candidates.append(Path(media_dir) / "analysis.json")

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
        if "xiaohongshu.com" in lower or "xhslink.com" in lower:
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
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://mp.weixin.qq.com/",
        }
        try:
            response = self.session.get(url, headers=headers, timeout=20)
            response.raise_for_status()
        except Exception as exc:
            return {"status": "pending_manual", "reason": f"公众号图文抓取失败：{exc}", "media_dir": str(media_dir)}

        raw_html = response.text or ""
        (media_dir / "article.html").write_text(raw_html, encoding="utf-8")
        article = self._parse_wechat_article_html(raw_html)
        body_text = str(article.get("body_text") or "").strip()
        title = str(article.get("title") or "").strip()
        if not body_text:
            reason = "公众号页面未包含可提取正文"
            if "环境异常" in raw_html or "完成验证后即可继续访问" in raw_html or "secitptpage/verify" in raw_html:
                reason = "公众号页面要求环境验证，当前机器无法直接抓取正文"
            return {"status": "pending_manual", "reason": reason, "media_dir": str(media_dir), "media_type": "article"}

        caption_path = media_dir / "caption.txt"
        caption_path.write_text(body_text + "\n", encoding="utf-8")
        structured_content = self._wechat_structured_article_text(article) or body_text
        structure_path = media_dir / "structure.json"
        structure_path.write_text(json.dumps(article.get("blocks") or [], ensure_ascii=False, indent=2), encoding="utf-8")
        analysis_path = media_dir / "analysis.json"
        image_paths = self._download_wechat_images(article.get("image_urls") or [], media_dir, url)
        tags = self._wechat_article_tags(raw_html, title, body_text)
        visual_cues = f"公众号图文正文提取完成，已保存 {len(image_paths)} 张正文图片。" if image_paths else "公众号图文正文提取完成，未下载到正文图片。"
        analysis = {
            "title": title or self._compact_title(body_text) or "未命名公众号图文",
            "work_copy": body_text,
            "full_content": structured_content,
            "tags": tags,
            "visual_cues": visual_cues,
            "analysis_provider": "wechat-article-extractor",
            "analysis_status": "source_extracted_needs_llm_semantics",
            "platform": "公众号",
            "media_type": "article",
            "caption": body_text,
            "article_structure_path": str(structure_path),
            "article_structure": article.get("blocks") or [],
            "account_name": article.get("account_name") or "",
            "author": article.get("author") or "",
            "publish_time": article.get("publish_time") or "",
        }
        analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "pending_manual",
            "reason": "LLM_SEMANTIC_PERSISTENCE_REQUIRED:wechat_article_semantic_analysis_required",
            "media_dir": str(media_dir),
            "analysis_path": str(analysis_path),
            "caption_path": str(caption_path),
            "caption": body_text,
            "structure_path": str(structure_path),
            "image_paths": image_paths,
            "media_type": "article",
            "analysis": analysis,
        }

    def _parse_wechat_article_html(self, raw_html: str) -> dict[str, Any]:
        parser = _WechatArticleParser()
        try:
            parser.feed(raw_html or "")
        except Exception:
            pass
        body_text = self._normalize_wechat_article_text(parser.body_text())
        title = (
            self._wechat_js_var(raw_html, "msg_title")
            or self._wechat_meta(raw_html, "og:title")
            or self._wechat_meta(raw_html, "twitter:title")
        )
        account_name = (
            self._wechat_js_var(raw_html, "nickname")
            or self._wechat_js_var(raw_html, "user_name")
            or self._wechat_meta(raw_html, "author")
        )
        author = self._wechat_js_var(raw_html, "author")
        publish_time = self._wechat_js_var(raw_html, "publish_time") or self._wechat_js_var(raw_html, "oriCreateTime")
        return {
            "title": self._clean_wechat_meta_text(title),
            "account_name": self._clean_wechat_meta_text(account_name),
            "author": self._clean_wechat_meta_text(author),
            "publish_time": self._normalize_wechat_publish_time(publish_time),
            "body_text": body_text,
            "blocks": self._normalize_wechat_blocks(parser.blocks),
            "image_urls": parser.image_urls,
        }

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

    def _download_wechat_images(self, image_urls: Any, media_dir: Path, referer: str) -> list[str]:
        if not isinstance(image_urls, list):
            return []
        image_dir = ensure_dir(media_dir / "images")
        saved: list[str] = []
        seen: set[str] = set()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger"
            ),
            "Referer": referer,
        }
        for raw_url in image_urls:
            if len(saved) >= 12:
                break
            url = html.unescape(str(raw_url or "")).strip()
            if not url or url.startswith("data:"):
                continue
            url = urljoin("https://mp.weixin.qq.com/", url)
            if url in seen:
                continue
            seen.add(url)
            try:
                response = self.session.get(url, headers=headers, timeout=20)
                response.raise_for_status()
            except Exception:
                continue
            content = response.content or b""
            if not content or len(content) > 10 * 1024 * 1024:
                continue
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            ext = mimetypes.guess_extension(content_type) or Path(urlparse(url).path).suffix or ".jpg"
            if ext == ".jpe":
                ext = ".jpg"
            path = image_dir / f"image-{len(saved) + 1:02d}{ext}"
            path.write_bytes(content)
            saved.append(str(path))
        return saved

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
        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
        if self._analysis_has_structured_content(analysis):
            payload["analysis_completion_checked"] = True
            return payload

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
            if not wait or time.monotonic() >= deadline:
                break
            time.sleep(poll_seconds)

        payload["analysis_completion_checked"] = True
        if not self._analysis_has_structured_content(analysis):
            payload["status"] = "pending_manual"
            payload["reason"] = "LLM_SEMANTIC_PERSISTENCE_REQUIRED:content_flow_structured_analysis_required"
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
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
audio_path = Path(sys.argv[2])
out_dir = Path(sys.argv[3])
out_dir.mkdir(parents=True, exist_ok=True)

env_path = root / ".env"
if env_path.is_file():
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

sys.path.insert(0, str(root))
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
                [str(python_bin), "-c", script, str(CONTENT_FLOW_ROOT), str(source), str(out_dir)],
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
        if self._env_truthy(env.get("TRANSCRIPTION_POSTPROCESS_CHUNKED", "1")):
            return self._summarize_dialogue_transcript_chunked(text, source_hint, env, artifact_dir=artifact_dir)

        return self._summarize_dialogue_transcript_with_provider("transcription_postprocess", text, source_hint)

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
    ) -> dict[str, Any]:
        sections = self._split_transcript_audio_sections(text)
        chunk_target = self._env_int(env, "TRANSCRIPTION_CHUNK_CHARS_TARGET", 10000)
        chunk_max = self._env_int(env, "TRANSCRIPTION_CHUNK_CHARS_MAX", 12000)
        chunk_overlap = self._env_int(env, "TRANSCRIPTION_CHUNK_OVERLAP", 500)
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
                summary.setdefault("schema_version", "1.0")
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
                parsed.pop("status", None)
                grouped.append(parsed)
                if artifact_root:
                    group_path = self._write_json_artifact(artifact_root, f"group-{group_index:02d}-summary.json", parsed)
                    artifacts.setdefault("groups", []).append(group_path)
            global_input = grouped

        final_note = self._summarize_global_note(global_input, source_hint, env)
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

        global_note_draft = dict(final_note)
        contract_errors = validate_transcription_final_note_contract(final_note)
        if contract_errors:
            if artifact_root:
                artifacts["failure"] = self._write_json_artifact(
                    artifact_root,
                    "global-note-draft-contract-failure.json",
                    {"stage": "global_contract", "errors": contract_errors, "result": final_note},
                )
            return {
                "status": "pending_manual",
                "reason": "全局整理 schema contract 不通过：" + "；".join(contract_errors[:5]),
                "stage": "global_contract",
                "postprocess_artifacts": artifacts,
            }
        consistency = self._check_global_note_consistency(final_note, attachment_summaries, env)
        if artifact_root:
            artifacts["global_note_draft"] = self._write_json_artifact(artifact_root, "global-note-draft.json", final_note)
            artifacts["consistency_check"] = self._write_json_artifact(artifact_root, "consistency-check.json", consistency)
        approved_value = consistency.get("approved")
        approved = approved_value is True or str(approved_value).strip().lower() == "true"
        consistency["approved"] = approved
        blocking_issues = consistency.get("blocking_issues") if isinstance(consistency.get("blocking_issues"), list) else []
        if not approved:
            revised_note = self._revise_global_note(final_note, attachment_summaries, consistency, source_hint, env)
            if revised_note.get("status") == "done":
                revised_note.pop("status", None)
                revised_consistency = self._check_global_note_consistency(revised_note, attachment_summaries, env)
                revised_approved_value = revised_consistency.get("approved")
                revised_approved = revised_approved_value is True or str(revised_approved_value).strip().lower() == "true"
                revised_consistency["approved"] = revised_approved
                if artifact_root:
                    artifacts["global_note_revised"] = self._write_json_artifact(artifact_root, "global-note-revised.json", revised_note)
                    artifacts["consistency_check_revised"] = self._write_json_artifact(
                        artifact_root,
                        "consistency-check-revised.json",
                        revised_consistency,
                    )
                if revised_approved:
                    final_note = revised_note
                    consistency = revised_consistency
                    approved = True
                    blocking_issues = []
                else:
                    consistency = revised_consistency
                    blocking_issues = (
                        revised_consistency.get("blocking_issues")
                        if isinstance(revised_consistency.get("blocking_issues"), list)
                        else blocking_issues
                    )
            elif artifact_root:
                artifacts["global_note_revision_failure"] = self._write_json_artifact(
                    artifact_root,
                    "global-note-revision-failure.json",
                    {"stage": "revision", "result": revised_note},
                )

        if not approved:
            if not blocking_issues:
                blocking_issues = ["一致性检查未批准，但未返回具体阻断项"]
            return {
                "status": "pending_manual",
                "reason": "一致性检查未通过：" + "；".join(str(item) for item in blocking_issues[:5]),
                "stage": "consistency",
                "postprocess_artifacts": artifacts,
                "consistency_check": consistency,
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
        final_note["postprocess_provider"] = final_note.get("postprocess_provider", "chunked")
        final_note["postprocess_pipeline"] = "chunked-map-reduce-final"
        final_note["chunk_count"] = len(chunk_summaries)
        final_note["attachment_count"] = len(attachment_summaries)
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
        prompt = (
            "你是会议逐字稿分片事实提取器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "这是局部 chunk，不要写全局结论，不要生成最终会议纪要。\n"
            "JSON 字段固定为 schema_version、chunk_id、source_audio、source_title、char_start、char_end、has_signal、signal_level、local_topics、key_points、local_observations、local_decisions_or_claims、pending_questions、action_items、speaker_hints、sensitive_items、noise_or_irrelevant、coverage_note。\n"
            "key_points 每项必须是对象，包含 point、evidence、speaker_hint、confidence；evidence 只能是短证据句。\n"
            "local_decisions_or_claims 每项必须标明 status，使用 discussion_tendency / tentative_decision / confirmed_decision / claim 之一。\n"
            "sensitive_items 从本阶段就标记，handling 可用 do_not_include_in_final_note / keep_private / ok_to_include。\n"
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
                "transcript_chunk": text,
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "分片整理")

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
            "只基于 chunk JSON 合并，不要新增事实。需要按 evidence_hash/source range 去重 overlap 内容。\n"
            "JSON 字段固定为 schema_version、attachment_id、attachment_title、covered_chunks、signal_level、main_value、theme_sections、decisions、pending_questions、action_items、speaker_notes、sensitive_summary、low_value_ranges、duplicated_with、unique_contribution。\n"
            "theme_sections 不允许只有一句概括；每个主题必须保留背景、争议/判断依据、具体修改点、例子、风险和后续处理，能列点就列点。\n"
            "decisions 只能收录多处支持或明确表达的结论；局部倾向要写进 theme_sections，不能伪装成已决定。\n"
            "action_items 必须保留执行对象、动作、上下文和时间/节点；没有明确负责人的写未指定，不要删除。\n"
            "sensitive_summary 必须说明哪些内容不应进入公开最终纪要。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "attachment_id": source_audio,
                "source_title": source_title,
                "chunks": chunks,
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "单附件合并")

    def _summarize_attachment_group(self, group_index: int, attachments: list[dict[str, Any]], source_hint: str, env: dict[str, str]) -> dict[str, Any]:
        prompt = (
            "你是会议附件中间合并器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "基于 attachment summaries 合并，不要新增事实。输出字段：group_id、covered_attachments、signal_level、theme_sections、decisions、pending_questions、action_items、speaker_notes、sensitive_summary、unique_contribution。"
        )
        user_content = json.dumps(
            {"source_hint": source_hint.strip() or "无", "group_id": f"group-{group_index:02d}", "attachments": attachments},
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "中间合并")

    def _summarize_global_note(self, summaries: list[dict[str, Any]], source_hint: str, env: dict[str, str]) -> dict[str, Any]:
        prompt = (
            "你是最终会议纪要整理器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "只基于 attachment/group summaries 生成最终纪要，不要读取或假设原始逐字稿外的信息。\n"
            "JSON 字段固定为 title、summary、theme_sections、decisions、action_items、pending_questions、speaker_notes、labeled_transcript、sensitive_summary、archive_macro_summary、archive_summary_bullets。\n"
            "title: 8-24 个汉字，必须是语义化会议主题，不得使用录音名、地点名、UUID、附件数量。\n"
            "summary: Markdown 字符串，这是详细会议纪要，不是摘要；按主题编号整理，覆盖所有高信号附件的有效信息，合并重复主题，但不得压缩成 3-8 条概括。\n"
            "summary 每个主题至少写出具体背景、讨论过程、分歧/判断依据、明确修改点、待补材料、风险提醒和后续动作；原始 summaries 有 action_items/decisions 时必须在 summary 里体现。\n"
            "archive_macro_summary: 一句话宏观总结，说明本次转写的核心问题、判断或推进方向；只基于来源，不新增事实。\n"
            "archive_summary_bullets: 数组，1-5 条周记摘要，每条是一句话，覆盖最关键结论、边界或后续动作；不得超过 5 条。\n"
            "theme_sections: 数组，逐主题保留 detail_points、source_chunks/source_ranges、risks、followups；detail_points 每项是一条具体事实或修改要求，不要写空泛概括。\n"
            "decisions: 数组，保留 item、status、rationale/source_range；status 必须沿用 confirmed_decision/tentative_decision/discussion_tendency/claim，不能把讨论倾向写成已决定。\n"
            "action_items: 数组，保留 task、assignee、context、deadline_or_node、source_range；未指定负责人或时间要明确写未指定。\n"
            "pending_questions: 数组，收录仍需确认/决策/补材料的问题或待办，必须有来源支撑。\n"
            "speaker_notes: 说明说话人或内容角色区分依据和置信度。\n"
            "labeled_transcript: 不要放完整逐字稿，只输出清理后的关键对话脉络或写明完整逐字稿见来源路径。\n"
            "不得把 discussion_tendency 写成 confirmed_decision；不得包含 handling=do_not_include_in_final_note 的敏感细节。"
        )
        user_content = json.dumps(
            {"source_hint": source_hint.strip() or "无", "summaries": summaries},
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "全局整理")

    def _check_global_note_consistency(self, final_note: dict[str, Any], attachments: list[dict[str, Any]], env: dict[str, str]) -> dict[str, Any]:
        prompt = (
            "你是会议纪要一致性检查器。只输出合法 JSON。\n"
            "检查最终纪要是否有无来源结论、把讨论误写成决定、遗漏高信号附件、重复主题、行动项缺少上下文。\n"
            "输出字段固定为 approved、blocking_issues、warnings、revision_notes。"
        )
        user_content = json.dumps({"final_note": final_note, "attachments": attachments}, ensure_ascii=False)
        parsed = self._call_postprocess_json(prompt, user_content, env, "一致性检查")
        if parsed.get("status") != "done":
            return {"approved": False, "blocking_issues": [parsed.get("reason") or "一致性检查失败"], "warnings": [], "revision_notes": ""}
        parsed.pop("status", None)
        return parsed

    def _revise_global_note(
        self,
        final_note: dict[str, Any],
        attachments: list[dict[str, Any]],
        consistency: dict[str, Any],
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        prompt = (
            "你是会议纪要修订器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "任务：基于一致性检查结果，对 final_note 做最小必要修订。\n"
            "必须补齐 blocking_issues 指出的遗漏行动项、上下文或风险说明；不得新增 attachments 中没有来源支撑的事实。\n"
            "保持原 JSON 字段：title、summary、theme_sections、decisions、action_items、pending_questions、speaker_notes、labeled_transcript、sensitive_summary、archive_macro_summary、archive_summary_bullets。\n"
            "pending_questions 必须仍为数组；summary 必须仍为 Markdown 字符串。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "final_note": final_note,
                "attachments": attachments,
                "consistency": consistency,
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "一致性修订")

    def _summarize_dialogue_transcript_with_provider(self, profile_name: str, text: str, source_hint: str) -> dict[str, Any]:
        prompt = (
            "你是会议录音和访谈录音整理助手。请只基于用户提供的逐字稿整理，不要新增事实，不要猜真实姓名。\n"
            "输出 JSON，字段固定为 title、summary、theme_sections、decisions、action_items、pending_questions、speaker_notes、labeled_transcript、archive_macro_summary、archive_summary_bullets。\n"
            "title: 8-24 个汉字的会议主题，概括逐字稿核心内容；不要使用来源补充、文件名、上传批次说明或录音数量。\n"
            "summary: 这是“内容整理”，不是摘要。用一个 Markdown 字符串输出，按主题分条分点全面整理逐字稿里的所有非重复有效信息；保留背景、分歧、判断、细节、例子、结论和行动项；合并同义重复，删除无意义重复，不能只写 3-8 条概括。\n"
            "archive_macro_summary: 一句话宏观总结，说明本次转写的核心问题、判断或推进方向；只基于逐字稿，不新增事实。\n"
            "archive_summary_bullets: 数组，1-5 条周记摘要，每条是一句话，覆盖最关键结论、边界或后续动作；不得超过 5 条。\n"
            "theme_sections: 数组，逐主题保留 detail_points、risks、followups；detail_points 每项是一条具体事实或修改要求，不要写空泛概括。\n"
            "decisions: 数组，保留 item、status、rationale；status 使用 confirmed_decision/tentative_decision/discussion_tendency/claim，不能把讨论倾向写成已决定。\n"
            "action_items: 数组，保留 task、assignee、context、deadline_or_node；未指定负责人或时间要明确写未指定。\n"
            "pending_questions: 这是“待解决的问题”，用数组输出，每项是一个仍需确认/决策/补材料的问题或待办；必须来自逐字稿，不要新增任务。不要加 Markdown 复选框，系统会统一转成 checklist。\n"
            "来源补充只用于理解用户是否显式给了主题；不要把上传批次说明、文件名、路径、录音数量写进 title 或 summary。\n"
            "speaker_notes: 不要猜真实姓名，但要尽量按语义轮次、问答关系和观点角色区分说话人 A/B/C，并说明区分依据；只有完全无法分轮次时，才写“说话人 A（未区分）”。\n"
            "labeled_transcript: 按对话顺序输出清理后的说话人标注整理稿，格式为对象数组，每项包含 speaker 和 text。speaker 使用“说话人 A/B/C”或“说话人 A（未区分）”，不要整篇都写“说话人不明”。text 不是原始逐字稿，必须去掉口吃、无意义语气词、明显 ASR 错字、断裂重复和噪声；保留所有实质信息、问答关系和推进顺序，不要压缩成摘要。\n"
            "如果没有声纹证据，不要判断真实身份；但仍应基于内容角色做 A/B/C 标注，并在 speaker_notes 里标注置信度。"
        )
        user_content = (
            f"来源补充：{source_hint.strip() or '无'}\n\n"
            "逐字稿：\n"
            f"{text[:50000]}"
        )
        return self._call_profile_provider_json(profile_name, prompt, user_content, "转写后处理")

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

    def _call_postprocess_json(self, prompt: str, user_content: str, env: dict[str, str], stage: str) -> dict[str, Any]:
        return self._call_profile_provider_json("transcription_postprocess", prompt, user_content, stage)

    def _call_profile_provider_json(self, profile_name: str, prompt: str, user_content: str, stage: str) -> dict[str, Any]:
        profile = profile_config(profile_name)
        provider = profile_provider_runtime(profile_name)
        if provider.api_type == "openclaw_agent":
            return {
                "status": "pending_manual",
                "reason": f"{stage}：profile `{profile_name}` 仍配置为 openclaw_agent，需要切换为 direct Responses provider",
            }
        if provider.api_type not in {"openai_chat_completions", "openai_codex_responses"}:
            return {"status": "pending_manual", "reason": f"{stage}：provider `{profile_name}` 不支持 direct JSON 调用"}
        settings = LLMProviderSettings(
            model=str(profile.get("model") or provider.model).strip(),
            base_url=provider.base_url,
            api_key=provider.api_key,
            api_type=provider.api_type,
            timeout=float(profile.get("timeout") or provider.timeout or 300),
            thinking=str(profile.get("thinking") or provider.thinking or "").strip(),
        )
        try:
            parsed = generate_json_from_parts(
                [{"text": user_content}],
                settings,
                max_retries=1,
                error_prefix=f"{stage} JSON 校验失败",
                instructions=prompt,
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
            return {"status": "pending_manual", "reason": f"{stage}：{exc}"}

    @staticmethod
    def _split_transcript_audio_sections(text: str) -> list[dict[str, Any]]:
        value = (text or "").strip()
        if not value:
            return []
        pattern = re.compile(r"^###\s*录音\s*(\d+)\s*[:：]\s*(.+?)\s*$", re.M)
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
            for item in items:
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
        env_path = CONTENT_FLOW_ROOT / ".env"
        if env_path.is_file():
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
