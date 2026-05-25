from __future__ import annotations

import re
from dataclasses import dataclass


NOISE_MARKER_RE = re.compile(
    r"(?:\[?噪音\]?|\[?静音\]?|\[?音乐\]?|\[?掌声\]?|\[?笑声\]?|<\|.*?\|>)",
    flags=re.I,
)


@dataclass(frozen=True)
class MediaCopyParts:
    caption: str = ""
    transcript: str = ""
    image_ocr: str = ""
    tags: tuple[str, ...] = ()


class MediaTextCleaner:
    """Clean extracted media text before it is stored as reusable knowledge."""

    def clean_generated_copy(self, text: str) -> str:
        lines = []
        for raw_line in str(text or "").splitlines():
            line = " ".join(str(raw_line or "").replace("\f", " ").split())
            if not line:
                continue
            line = self._normalize_common_ocr_errors(line)
            line = self._clean_noise_tokens(line)
            if line:
                lines.append(line)
        return "\n".join(self._dedupe_adjacent(lines)).strip()

    def clean_ocr_for_copy(self, text: str) -> str:
        cleaned_lines: list[str] = []
        for raw_line in str(text or "").splitlines():
            line = " ".join(str(raw_line or "").replace("\f", " ").split())
            if not line:
                continue
            if re.match(r"^#{1,3}\s*\d{1,2}\s+image[-_]\d+\.(jpg|jpeg|png|webp)$", line, flags=re.I):
                continue
            if (
                re.fullmatch(r"[\W_]{1,4}", line)
                or re.fullmatch(r"[a-zA-Z]{1,2}", line)
                or (len(line) <= 4 and re.search(r"[^\w\u4e00-\u9fff\s]", line))
            ):
                continue
            line = self._normalize_common_ocr_errors(line)
            line = self._clean_noise_tokens(line)
            if line:
                cleaned_lines.append(line)
        return "\n".join(self._dedupe_all(cleaned_lines)).strip()

    def clean_transcript_for_copy(self, transcript: str) -> str:
        lines: list[str] = []
        for raw_line in str(transcript or "").splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue
            line = NOISE_MARKER_RE.sub("", line).strip()
            line = self.clean_spoken_line(line)
            if line:
                lines.append(line)
        return "\n".join(self._dedupe_adjacent(lines)).strip()

    def clean_tags(self, tags: object) -> list[str]:
        if tags in (None, "", [], {}):
            return []
        if isinstance(tags, str):
            raw_items = re.split(r"[\n,，、/|｜\s]+", tags)
        else:
            try:
                raw_items = list(tags)  # type: ignore[arg-type]
            except TypeError:
                raw_items = [tags]
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            tag = str(item or "").strip()
            if not tag:
                continue
            tag = tag.strip("#＃")
            tag = re.sub(r"\[话题\]$", "", tag).strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            cleaned.append(tag)
        return cleaned

    def build_work_copy(self, caption: str, tags: object = ()) -> str:
        copy = self.clean_generated_copy(caption)
        existing_tags = set(re.findall(r"[#＃]([^#＃\s\[]+)(?:\[话题\])?", copy))
        extra_tags = [tag for tag in self.clean_tags(tags) if tag not in existing_tags]
        if extra_tags:
            tag_line = " ".join(f"#{tag}[话题]#" for tag in extra_tags)
            copy = "\n".join(part for part in (copy, tag_line) if part).strip()
        return copy

    def build_full_content(self, parts: MediaCopyParts) -> str:
        blocks: list[str] = []
        transcript = self.clean_transcript_for_copy(parts.transcript)
        image_ocr = self.clean_ocr_for_copy(parts.image_ocr)
        if transcript:
            blocks.append(f"视频语音转写（已清洗）：\n{transcript}")
        if image_ocr:
            blocks.append(f"图片文字提取（已清洗）：\n{image_ocr}")
        return "\n\n".join(blocks).strip()

    def clean_spoken_line(self, value: object) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return ""
        text = NOISE_MARKER_RE.sub("", text).strip()
        text = re.sub(r"[，,、\s]*(嗯|呃|额|啊)[，,、\s]*(?=(嗯|呃|额|啊)[，,、\s]*)", "，", text)
        for token in ("就是", "然后", "那个", "这个", "对", "嗯", "呃", "额", "啊"):
            text = re.sub(rf"(?:{token}[，,、\s]*){{2,}}", token + "，", text)
        text = text.strip(" ，,、")
        if len(text) > 12:
            previous = None
            while previous != text:
                previous = text
                text = re.sub(r"^(?:嗯|呃|额|啊|对|好|然后|就是|那个|这个)[，,、\s]*", "", text).strip()
        text = re.sub(r"[，,、\s]+([。！？!?])", r"\1", text)
        text = re.sub(r"([。！？!?]){2,}", r"\1", text)
        return text.strip(" ，,、")

    def build_unified_copy(self, parts: MediaCopyParts) -> str:
        blocks: list[str] = []
        caption = self.build_work_copy(parts.caption, parts.tags)
        full_content = self.build_full_content(parts)
        if caption:
            blocks.append(caption)
        if full_content:
            blocks.append(full_content)
        return "\n\n".join(blocks).strip()

    def _normalize_common_ocr_errors(self, line: str) -> str:
        line = re.sub(r"\s*[€$¥#@][A-Za-z0-9]*\s*", " ", line).strip()
        line = re.sub(r"(?<![A-Za-z])A[lI1](?![A-Za-z])", "AI", line)
        line = re.sub(r"\bAl(?=[\s自选入从])", "AI", line)
        return (
            line.replace("和和角", "和角")
            .replace("人群、痛点和角", "人群、痛点和角度")
            .replace("职场新人人", "职场新人")
        ).strip()

    def _clean_noise_tokens(self, line: str) -> str:
        line = re.sub(r"\s{2,}", " ", line).strip()
        if re.fullmatch(r"[\W_]{1,4}", line):
            return ""
        return line

    def _dedupe_all(self, lines: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
        return deduped

    def _dedupe_adjacent(self, lines: list[str]) -> list[str]:
        deduped: list[str] = []
        previous = ""
        for line in lines:
            normalized = re.sub(r"\s+", "", line)
            if normalized and normalized == previous:
                continue
            previous = normalized
            deduped.append(line)
        return deduped


MEDIA_TEXT_CLEANER = MediaTextCleaner()
