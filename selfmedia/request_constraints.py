from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from selfmedia.deconstruct.viral_content.src.human_insight_cards import promotion_evidence_threshold


ANALYSIS_SCOPES = ("全片", "开头", "转场", "时间段", "自定义", "历史未标注")
DECONSTRUCTION_FOCUS_VALUES = ("常规拆解", "钩子", "转场", "BGM", "节奏", "AI片段", "人性洞察", "结尾引导")
OUTPUT_TYPE_VALUES = ("拆解摘要", "结构迁移", "分镜提示词", "心理机制卡", "发布脚本", "素材需求清单", "再创任务卡")
DECONSTRUCTION_DEPTH_VALUES = ("brief", "detailed")
WRITE_POLICY_VALUES = ("source_asset_only", "partial_no_write", "full_write_02b", "creation_handoff")
INSIGHT_CARD_POLICY_VALUES = ("single_video_only", "candidate_for_promotion", "promote_to_library")
TAXONOMY_VERSION = "human_insight_taxonomy_v1"


@dataclass(frozen=True)
class RequestConstraints:
    analysis_scope: str = "全片"
    analysis_time_range: str = "全部"
    deconstruction_focus: tuple[str, ...] = ("常规拆解",)
    output_types: tuple[str, ...] = ("拆解摘要",)
    deconstruction_depth: str = "brief"
    write_policy: str = "source_asset_only"
    human_insight_focus: str = "常规洞察"
    insight_card_policy: str = "single_video_only"
    promotion_evidence_threshold: int = field(default_factory=promotion_evidence_threshold)
    taxonomy_version: str = TAXONOMY_VERSION
    privacy_boundary: str = "public_content_only"
    source: str = "explicit_user_request"
    raw_constraints: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_scope": self.analysis_scope,
            "analysis_time_range": self.analysis_time_range,
            "deconstruction_focus": list(self.deconstruction_focus),
            "output_types": list(self.output_types),
            "deconstruction_depth": self.deconstruction_depth,
            "write_policy": self.write_policy,
            "human_insight_focus": self.human_insight_focus,
            "insight_card_policy": self.insight_card_policy,
            "promotion_evidence_threshold": self.promotion_evidence_threshold,
            "taxonomy_version": self.taxonomy_version,
            "privacy_boundary": self.privacy_boundary,
            "source": self.source,
            "raw_constraints": list(self.raw_constraints),
        }

    @property
    def focus_text(self) -> str:
        return " / ".join(self.deconstruction_focus)

    @property
    def output_type_text(self) -> str:
        return " / ".join(self.output_types)


def parse_request_constraints(text: Any, *, default_write_policy: str = "source_asset_only") -> RequestConstraints:
    raw = str(text or "")
    normalized = _normalize_text(raw)
    focus: list[str] = []
    outputs: list[str] = []
    raw_constraints: list[str] = []

    analysis_scope = "全片"
    analysis_time_range = "全部"
    time_range = _explicit_time_range(normalized)
    if time_range:
        analysis_scope = "开头" if time_range.startswith("0-") and _mentions_opening(normalized) else "时间段"
        analysis_time_range = time_range
        raw_constraints.append(f"analysis_time_range={time_range}")
    elif _mentions_opening(normalized):
        analysis_scope = "开头"
        analysis_time_range = "0-5s"
        raw_constraints.append("analysis_time_range=0-5s(default_opening)")
    elif "转场" in normalized and re.search(r"(只|仅|重点|专门).*转场|转场.*(只|仅|重点|专门)", normalized):
        analysis_scope = "转场"
        analysis_time_range = "全部"
        raw_constraints.append("analysis_scope=转场")

    if re.search(r"(钩子|开头抓手|前 ?[2358]? ?秒|前几秒|开头)", normalized):
        focus.append("钩子")
    if "转场" in normalized:
        focus.append("转场")
    if re.search(r"(BGM|bgm|音乐|卡点|鼓点)", raw):
        focus.append("BGM")
    if re.search(r"(节奏|卡点|鼓点)", normalized):
        focus.append("节奏")
    if re.search(r"(AI ?片段|ai ?片段|AI生成|ai生成|AIGC|aigc|现实.*AI|AI.*现实)", raw):
        focus.append("AI片段")
    if re.search(r"(人性洞察|心理机制|群体标签|情绪触发|机制卡|群体卡)", normalized):
        focus.append("人性洞察")
    if re.search(r"(结尾引导|结尾 CTA|结尾CTA|收尾引导)", raw):
        focus.append("结尾引导")
    if not focus:
        focus.append("常规拆解")

    if re.search(r"(结构迁移|迁移结构|可迁移结构|复用结构)", normalized):
        outputs.append("结构迁移")
    if re.search(r"(分镜提示词|AI分镜|ai分镜|提示词|prompt)", raw):
        outputs.append("分镜提示词")
    if re.search(r"(心理机制卡|机制卡|群体卡)", normalized):
        outputs.append("心理机制卡")
    if re.search(r"(发布脚本|发布文案|口播稿|正文初稿)", normalized):
        outputs.append("发布脚本")
    if re.search(r"(素材需求清单|素材清单|补拍清单)", normalized):
        outputs.append("素材需求清单")
    if re.search(r"(再创任务卡|任务卡|再创作任务)", normalized):
        outputs.append("再创任务卡")
    if "拆解摘要" not in outputs:
        outputs.insert(0, "拆解摘要")

    depth = "detailed" if re.search(r"(详细|完整拆解|完整分镜|Storyboard|EDL|逐镜头)", raw, flags=re.I) else "brief"
    write_policy = default_write_policy if default_write_policy in WRITE_POLICY_VALUES else "source_asset_only"
    if re.search(r"(入库|写入|保存到 ?02B|写 ?02B|完整拆解入库)", normalized, flags=re.I):
        write_policy = "full_write_02b"
    elif re.search(r"(创作|拍摄|发布脚本|素材需求清单|再创任务卡)", normalized):
        write_policy = "creation_handoff"
    elif re.search(r"(暂存|不要入库|不写库|no-write|no_write)", raw, flags=re.I):
        write_policy = "partial_no_write"

    human_insight_focus = "常规洞察"
    if "人性洞察" in focus:
        human_insight_focus = "心理机制与叙事型群体"
    insight_card_policy = "single_video_only"
    if re.search(r"(积累|候选入库|后续聚合|聚合候选|机制卡候选|群体卡候选)", normalized):
        insight_card_policy = "candidate_for_promotion"
    if re.search(r"(晋升|写入洞察库|沉淀为机制卡|沉淀为群体卡|promote)", raw, flags=re.I):
        insight_card_policy = "promote_to_library"

    return RequestConstraints(
        analysis_scope=_allowed(analysis_scope, ANALYSIS_SCOPES, "全片"),
        analysis_time_range=analysis_time_range,
        deconstruction_focus=tuple(_dedupe_allowed(focus, DECONSTRUCTION_FOCUS_VALUES, default="常规拆解")),
        output_types=tuple(_dedupe_allowed(outputs, OUTPUT_TYPE_VALUES, default="拆解摘要")),
        deconstruction_depth=_allowed(depth, DECONSTRUCTION_DEPTH_VALUES, "brief"),
        write_policy=write_policy,
        human_insight_focus=human_insight_focus,
        insight_card_policy=_allowed(insight_card_policy, INSIGHT_CARD_POLICY_VALUES, "single_video_only"),
        raw_constraints=tuple(raw_constraints),
    )


def constraints_for_deconstruct_text(text: Any) -> dict[str, Any]:
    return parse_request_constraints(text).to_dict()


def validate_request_constraints_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("request_constraints 必须是 object")
    threshold = promotion_evidence_threshold()
    normalized = RequestConstraints(
        analysis_scope=_allowed(str(value.get("analysis_scope") or ""), ANALYSIS_SCOPES, "全片"),
        analysis_time_range=_validate_time_range(str(value.get("analysis_time_range") or "全部")),
        deconstruction_focus=tuple(
            _dedupe_allowed(_list_value(value.get("deconstruction_focus")), DECONSTRUCTION_FOCUS_VALUES, default="常规拆解")
        ),
        output_types=tuple(_dedupe_allowed(_list_value(value.get("output_types")), OUTPUT_TYPE_VALUES, default="拆解摘要")),
        deconstruction_depth=_allowed(str(value.get("deconstruction_depth") or ""), DECONSTRUCTION_DEPTH_VALUES, "brief"),
        write_policy=_allowed(str(value.get("write_policy") or ""), WRITE_POLICY_VALUES, "source_asset_only"),
        human_insight_focus=str(value.get("human_insight_focus") or "常规洞察").strip() or "常规洞察",
        insight_card_policy=_allowed(str(value.get("insight_card_policy") or ""), INSIGHT_CARD_POLICY_VALUES, "single_video_only"),
        promotion_evidence_threshold=int(value.get("promotion_evidence_threshold") or threshold),
        taxonomy_version=str(value.get("taxonomy_version") or TAXONOMY_VERSION).strip() or TAXONOMY_VERSION,
        privacy_boundary=str(value.get("privacy_boundary") or "public_content_only").strip() or "public_content_only",
        source=str(value.get("source") or "explicit_user_request").strip() or "explicit_user_request",
        raw_constraints=tuple(_list_value(value.get("raw_constraints"))),
    )
    if normalized.promotion_evidence_threshold < threshold:
        raise ValueError(f"promotion_evidence_threshold 不能小于 {threshold}")
    if normalized.taxonomy_version != TAXONOMY_VERSION:
        raise ValueError(f"taxonomy_version 必须是 {TAXONOMY_VERSION}")
    if normalized.privacy_boundary != "public_content_only":
        raise ValueError("privacy_boundary 必须是 public_content_only")
    return normalized.to_dict()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _mentions_opening(text: str) -> bool:
    return bool(re.search(r"(开头|前几秒|前[0-9一二三四五六七八九十]+秒|前 ?[0-9]+ ?s|0-5s|0-5秒)", text, flags=re.I))


def _explicit_time_range(text: str) -> str:
    match = re.search(r"(?P<start>\d+(?:\.\d+)?)\s*[-~到至]\s*(?P<end>\d+(?:\.\d+)?)\s*(?:秒|s)", text, flags=re.I)
    if match:
        return f"{match.group('start')}-{match.group('end')}s"
    match = re.search(r"前\s*(?P<seconds>\d+(?:\.\d+)?)\s*(?:秒|s)", text, flags=re.I)
    if match:
        seconds = match.group("seconds")
        return f"0-{seconds}s"
    return ""


def _validate_time_range(value: str) -> str:
    text = str(value or "").strip()
    if text in {"全部", "历史未标注"}:
        return text
    parts = [item.strip() for item in text.split(",") if item.strip()]
    if parts and all(re.fullmatch(r"\d+(?:\.\d+)?s?-\d+(?:\.\d+)?s", item) for item in parts):
        return ",".join(parts)
    raise ValueError("analysis_time_range 必须是 全部、历史未标注 或 Ns-Ms 时间段")


def _list_value(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re_split_commas(str(value)) if item.strip()]


def re_split_commas(text: str) -> list[str]:
    return re.split(r"[\n,，、;；]+", text)


def _allowed(value: str, allowed: tuple[str, ...], default: str) -> str:
    return value if value in allowed else default


def _dedupe_allowed(values: list[str], allowed: tuple[str, ...], *, default: str) -> list[str]:
    result: list[str] = []
    for value in values:
        if value in allowed and value not in result:
            result.append(value)
    return result or [default]
