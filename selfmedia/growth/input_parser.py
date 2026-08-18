from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


LABEL_PATTERN = re.compile(
    r"(?:(?<=^)|(?<=\s))(?P<label>[\w\u4e00-\u9fff]{1,16})\s*(?P<sep>[：=]|:(?!//))\s*",
    re.I,
)
TAG_PREFIX_RE = re.compile(r"^\s*【[^】]+】\s*")
ARTIFACT_REF_KEYS = {
    "artifact",
    "artifact_id",
    "artifact_ref",
    "source",
    "来源",
    "引用",
    "源",
    "source_asset_id",
    "draft_id",
    "creation_run_id",
    "publishing_pack_id",
    "run_id",
}


@dataclass(frozen=True)
class ParsedMediaGrowthInput:
    raw_text: str
    content_text: str
    params: dict[str, str] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = field(default_factory=tuple)

    def value(self, *labels: str) -> str:
        for label in labels:
            value = self.params.get(_normalize_key(label))
            if value:
                return value
        return ""


def parse_media_growth_input(text: Any) -> ParsedMediaGrowthInput:
    raw_text = str(text or "").strip()
    body = strip_tag_prefix(raw_text)
    matches = list(LABEL_PATTERN.finditer(body))
    params: dict[str, str] = {}
    spans: list[tuple[int, int]] = []

    for index, match in enumerate(matches):
        value_start = match.end()
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        label = _normalize_key(match.group("label"))
        value = body[value_start:value_end].strip()
        if label and value:
            span_end = value_end
            if label in ARTIFACT_REF_KEYS:
                ref_value, span_end = _split_artifact_ref_value(body, value, value_start)
                value = ref_value
            params[label] = value
            spans.append((match.start(), span_end))

    content_text = _remove_spans(body, spans)
    artifact_refs = tuple(
        value
        for key, value in params.items()
        if key in ARTIFACT_REF_KEYS and value
    )
    return ParsedMediaGrowthInput(raw_text=raw_text, content_text=content_text, params=params, artifact_refs=artifact_refs)


def strip_tag_prefix(text: Any) -> str:
    return TAG_PREFIX_RE.sub("", str(text or "").strip(), count=1).strip()


def display_text_from_input(text: Any) -> str:
    parsed = parse_media_growth_input(text)
    return parsed.content_text or parsed.raw_text


def _normalize_key(label: Any) -> str:
    return str(label or "").strip().lower()


def _split_artifact_ref_value(body: str, value: str, value_start: int) -> tuple[str, int]:
    match = re.match(r"(?P<ref>\S+)(?:\s+(?P<tail>.+))?\Z", value, flags=re.S)
    if not match:
        return value, value_start + len(value)
    ref = match.group("ref").strip()
    if not match.group("tail"):
        return ref, value_start + len(value)
    return ref, value_start + len(match.group("ref"))


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text.strip()
    chunks: list[str] = []
    cursor = 0
    for start, end in spans:
        if start > cursor:
            chunks.append(text[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(text):
        chunks.append(text[cursor:])
    return re.sub(r"\s+", " ", "".join(chunks)).strip()
