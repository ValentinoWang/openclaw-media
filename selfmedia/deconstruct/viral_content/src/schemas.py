from __future__ import annotations

import ast
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, root_validator, validator


class SchemaError(ValueError):
    pass


def _non_empty_string(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} 不能为空")
    return value


def _clean_text_value(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                return text
            if isinstance(parsed, list) and all(not isinstance(item, (dict, list, tuple, set)) for item in parsed):
                return "\n".join(str(item).strip() for item in parsed if str(item).strip())
        return text
    return str(value or "")


def re_split_commas(text: str) -> list[str]:
    return re.split(r"[\n,，、;；]+", text)


PRODUCTION_ROUTE_VALUES = ("真实素材剪辑", "需要补拍", "图片生成", "动效字幕", "Remotion", "FFmpeg", "人工待定")
EDITORIAL_PLAN_TITLE = "千万年薪编导会怎么把这条改出彩？"
STORYBOARD_GRANULARITY_ERROR_CODE = "E_STORYBOARD_GRANULARITY"
STORYBOARD_ANALYSIS_MAX_SECONDS = 60
STORYBOARD_OPENING_SECONDS = 5
STORYBOARD_POST_OPENING_STEP_SECONDS = 3


def _string_list(value: Any, field_name: str) -> list[str]:
    if isinstance(value, str):
        items = [item.strip() for item in re_split_commas(value) if item.strip()]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = [str(value).strip()] if str(value or "").strip() else []
    if not items:
        raise ValueError(f"{field_name} 不能为空")
    return items


class StoryboardItem(BaseModel):
    shot_no: int | str
    duration: str
    visual: str
    subtitle: str
    voiceover: str
    subtitle_or_voiceover: str = ""
    camera_movement: str = ""
    props: str = ""
    edit_notes: str = ""
    image_prompt: str = ""
    evidence_asset_id: str = ""

    class Config:
        extra = "allow"

    @validator("duration", "visual", pre=True)
    def required_text(cls, value: Any) -> str:
        return _non_empty_string(str(value or ""), "video_storyboard")

    @validator("subtitle", "voiceover", pre=True)
    def allow_empty_required_text(cls, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        fabricated_markers = ("假设复刻字幕", "假设字幕", "假设口播", "推测字幕", "推测口播")
        if any(marker in text for marker in fabricated_markers):
            return ""
        return str(value)


class ImagePostItem(BaseModel):
    page_no: int | str
    image_prompt: str
    evidence_asset_id: str = ""
    overlay_text: str = ""
    caption_note: str = ""

    class Config:
        extra = "allow"

    @validator("image_prompt", pre=True)
    def required_image_prompt(cls, value: Any) -> str:
        return _non_empty_string(str(value or ""), "image_post_script.image_prompt")


class AIBlendSegment(BaseModel):
    segment_id: str
    time_range: str
    segment_type: str
    confidence: float
    reasoning_summary: str
    evidence_asset_ids: list[str] = Field(min_items=1)
    blend_method: str = ""
    real_to_ai_transition: str = ""

    class Config:
        extra = "allow"

    @validator("segment_id", "time_range", "segment_type", "reasoning_summary", pre=True)
    def required_text(cls, value: Any) -> str:
        return _non_empty_string(str(value or ""), "ai_blend_analysis")

    @validator("segment_type", pre=True)
    def allowed_segment_type(cls, value: Any) -> str:
        text = _non_empty_string(str(value or ""), "ai_blend_analysis.segment_type")
        if text not in {"real", "ai", "hybrid", "uncertain"}:
            raise ValueError("ai_blend_analysis.segment_type 必须是 real/ai/hybrid/uncertain")
        return text

    @validator("confidence", pre=True)
    def confidence_range(cls, value: Any) -> float:
        number = float(value)
        if not 0 <= number <= 1:
            raise ValueError("ai_blend_analysis.confidence 必须在 0..1")
        return number

    @validator("evidence_asset_ids", pre=True)
    def evidence_list(cls, value: Any) -> list[str]:
        return _string_list(value, "ai_blend_analysis.evidence_asset_ids")


class AIStoryboardPromptShot(BaseModel):
    shot_id: str
    segment_id: str
    duration_seconds: float | int | str
    start_frame_ref: str
    end_frame_ref: str
    continuity_to_real_footage: str
    aspect_ratio: str
    target_tool: str
    prompt_language: str
    prompt: str
    negative_prompt: str
    evidence_asset_ids: list[str] = Field(min_items=1)

    class Config:
        extra = "allow"

    @validator(
        "shot_id",
        "segment_id",
        "start_frame_ref",
        "end_frame_ref",
        "continuity_to_real_footage",
        "aspect_ratio",
        "target_tool",
        "prompt_language",
        "prompt",
        "negative_prompt",
        pre=True,
    )
    def required_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "ai_storyboard_prompt_shots")

    @validator("evidence_asset_ids", pre=True)
    def evidence_list(cls, value: Any) -> list[str]:
        return _string_list(value, "ai_storyboard_prompt_shots.evidence_asset_ids")


class HumanInsightCandidate(BaseModel):
    insight_id: str
    evidence_quote: str = ""
    evidence_asset_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    mechanism_tag: str
    candidate_tags: list[str] = Field(default_factory=list)
    target_emotion: str
    desire_or_fear: str
    emotion_path: str
    audience_group_hypothesis: str
    trigger_pattern: str
    risk_boundary: str
    reuse_warning: str = ""
    confidence: float
    reasoning_summary: str
    comment_data_boundary: str = ""

    class Config:
        extra = "allow"

    @validator(
        "insight_id",
        "mechanism_tag",
        "target_emotion",
        "desire_or_fear",
        "emotion_path",
        "audience_group_hypothesis",
        "trigger_pattern",
        "risk_boundary",
        "reasoning_summary",
        pre=True,
    )
    def required_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "human_insight_candidates")

    @validator("candidate_tags", pre=True)
    def optional_tags(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        return _string_list(value, "human_insight_candidates.candidate_tags")

    @validator("evidence_asset_ids", pre=True)
    def optional_evidence_list(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        return _string_list(value, "human_insight_candidates.evidence_asset_ids")

    @validator("evidence_refs", pre=True)
    def optional_evidence_refs(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        return _string_list(value, "human_insight_candidates.evidence_refs")

    @validator("confidence", pre=True)
    def confidence_range(cls, value: Any) -> float:
        number = float(value)
        if not 0 <= number <= 1:
            raise ValueError("human_insight_candidates.confidence 必须在 0..1")
        return number

    @root_validator(skip_on_failure=True)
    def require_text_or_frame_evidence(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not str(values.get("evidence_quote") or "").strip() and not values.get("evidence_asset_ids") and not values.get("evidence_refs"):
            raise ValueError("human_insight_candidates 每条必须有 evidence_quote、evidence_asset_ids 或 evidence_refs")
        return values


class PartialVisualOrderItem(BaseModel):
    segment: str
    evidence_asset_id: str
    reusable_point: str = ""

    class Config:
        extra = "allow"

    @validator("segment", "evidence_asset_id", pre=True)
    def required_partial_text(cls, value: Any) -> str:
        return _non_empty_string(str(value or ""), "partial_deconstruct.visual_order")


class PartialDeconstructResult(BaseModel):
    content_summary: str
    source_summary: str
    opening_hook: str
    bgm_or_rhythm: str
    visual_order: list[PartialVisualOrderItem] = Field(min_items=1)
    title_cover_pattern: str
    lightweight_edit_card: list[str] = Field(min_items=1)
    material_fill_suggestions: list[str] = Field(min_items=1)
    avoid_plagiarism_notes: str
    production_checklist: list[str] = Field(min_items=1)
    target_audience: list[str] = Field(default_factory=list)
    pain_or_pleasure_points: list[str] = Field(default_factory=list)
    track_tags: list[str] = Field(default_factory=list)
    evidence_asset_ids: list[str] = Field(min_items=1)
    confidence: float = 0.72

    class Config:
        extra = "ignore"

    @validator(
        "content_summary",
        "source_summary",
        "opening_hook",
        "bgm_or_rhythm",
        "title_cover_pattern",
        "avoid_plagiarism_notes",
        pre=True,
    )
    def non_empty_partial_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "partial_deconstruct_result")

    @validator(
        "lightweight_edit_card",
        "material_fill_suggestions",
        "production_checklist",
        "target_audience",
        "pain_or_pleasure_points",
        "track_tags",
        "evidence_asset_ids",
        pre=True,
    )
    def partial_string_list(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in re_split_commas(value) if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value or "").strip() else []


class DeconstructResult(BaseModel):
    content_summary: str
    source_summary: str
    viral_mechanism: str
    video_storyboard: list[StoryboardItem] = Field(default_factory=list)
    image_post_script: list[ImagePostItem] = Field(default_factory=list)
    avoid_plagiarism_notes: str
    production_checklist: list[str] = Field(min_items=1)
    target_audience: list[str] = Field(default_factory=list)
    pain_or_pleasure_points: list[str] = Field(default_factory=list)
    track_tags: list[str] = Field(default_factory=list)
    viral_reuse_assessment: dict[str, Any]
    pacing_profile: dict[str, Any]
    reuse_guardrails: dict[str, Any]
    human_readable_brief: dict[str, Any]
    cover_opening_hook: str
    core_data_summary: str
    top_comment_insight: str
    target_audience_summary: str
    pain_pleasure_summary: str
    attention_elements: list[str] = Field(min_items=1)
    viral_breakdown: str
    viral_migration: str
    creative_upgrade_suggestion: str
    request_constraints: dict[str, Any] = Field(default_factory=dict)
    ai_blend_analysis: list[AIBlendSegment] = Field(default_factory=list)
    ai_storyboard_prompt_shots: list[AIStoryboardPromptShot] = Field(default_factory=list)
    human_insight_candidates: list[HumanInsightCandidate] = Field(default_factory=list)
    no_human_insight_detected: bool = False
    confidence: float = 0.72

    class Config:
        extra = "ignore"

    @root_validator(pre=True)
    def reject_removed_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        if isinstance(values, dict):
            removed = {
                "is_viral",
                "speech_function_lines",
                "screen_text_function_lines",
                "opening_lines",
                "turning_point_lines",
                "comment_trigger_lines",
                "cta_lines",
                "usable_material_brief",
            }
            present = sorted(removed & set(values))
            if present:
                raise ValueError("deconstruction.v2 禁止输出已移除字段: " + ", ".join(present))
        return values

    @validator(
        "content_summary",
        "source_summary",
        "viral_mechanism",
        "avoid_plagiarism_notes",
        "cover_opening_hook",
        "core_data_summary",
        "top_comment_insight",
        "target_audience_summary",
        "pain_pleasure_summary",
        "viral_breakdown",
        "viral_migration",
        "creative_upgrade_suggestion",
        pre=True,
    )
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "deconstruct_result")

    @validator("production_checklist", pre=True)
    def non_empty_checklist(cls, value: Any) -> Any:
        if not value:
            raise ValueError("production_checklist 不能为空")
        return value

    @validator("target_audience", "pain_or_pleasure_points", "track_tags", "attention_elements", pre=True)
    def optional_string_list(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = ast.literal_eval(text)
                except (SyntaxError, ValueError):
                    return [text]
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            return [item.strip() for item in re_split_commas(text) if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    @root_validator(skip_on_failure=True)
    def validate_script_payloads(cls, values: dict[str, Any]) -> dict[str, Any]:
        for field_name in ("viral_reuse_assessment", "pacing_profile", "reuse_guardrails", "human_readable_brief"):
            if values.get(field_name) in ({}, None, "", []):
                raise ValueError(f"{field_name} 不能为空")
        final_label = str((values.get("viral_reuse_assessment") or {}).get("final_label") or "").strip()
        if final_label not in {"strong_reuse_candidate", "weak_reuse_candidate", "reject"}:
            raise ValueError("viral_reuse_assessment.final_label 非法")
        return values


class EditorialPrimaryPlan(BaseModel):
    title: str
    why_better: str
    learn_from_reference: list[str] = Field(min_items=1)
    must_transform: list[str] = Field(min_items=1)
    execution_angle: str

    class Config:
        extra = "ignore"

    @validator("title", "why_better", "execution_angle", pre=True)
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "editorial_plan.primary_plan")

    @validator("learn_from_reference", pre=True)
    def non_empty_learn_from_reference(cls, value: Any) -> list[str]:
        return _string_list(value, "editorial_plan.primary_plan.learn_from_reference")

    @validator("must_transform", pre=True)
    def non_empty_must_transform(cls, value: Any) -> list[str]:
        return _string_list(value, "editorial_plan.primary_plan.must_transform")


class EditorialBackupVariant(BaseModel):
    title: str
    difference: str
    best_for: str
    risk: str

    class Config:
        extra = "ignore"

    @validator("title", "difference", "best_for", "risk", pre=True)
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "editorial_plan.backup_variants")


class EditorialPlan(BaseModel):
    section_title: str = EDITORIAL_PLAN_TITLE
    primary_plan: EditorialPrimaryPlan
    backup_variants: list[EditorialBackupVariant] = Field(min_items=2, max_items=2)

    class Config:
        extra = "ignore"

    @validator("section_title", pre=True, always=True)
    def fixed_section_title(cls, value: Any) -> str:
        text = str(value or EDITORIAL_PLAN_TITLE).strip()
        if text != EDITORIAL_PLAN_TITLE:
            raise ValueError(f"editorial_plan.section_title 必须是 {EDITORIAL_PLAN_TITLE}")
        return text


class ProductionRouteStep(BaseModel):
    segment_id: str
    story_purpose: str
    route: str
    needed_material: str
    execution_note: str
    risk_or_manual_check: str

    class Config:
        extra = "ignore"

    @validator("segment_id", "story_purpose", "needed_material", "execution_note", "risk_or_manual_check", pre=True)
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "production_route_plan.shot_route_table")

    @validator("route", pre=True)
    def valid_route(cls, value: Any) -> str:
        route = _non_empty_string(str(value or ""), "production_route_plan.route")
        if route not in PRODUCTION_ROUTE_VALUES:
            raise ValueError("production_route_plan.route 非法: " + route)
        return route


class ProductionRouteFinalAssembly(BaseModel):
    remotion_usage: str
    ffmpeg_usage: str
    delivery_note: str

    class Config:
        extra = "ignore"

    @validator("remotion_usage", "ffmpeg_usage", "delivery_note", pre=True)
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "production_route_plan.final_assembly")


class ProductionRoutePlan(BaseModel):
    route_policy: str
    shot_route_table: list[ProductionRouteStep] = Field(min_items=1)
    final_assembly: ProductionRouteFinalAssembly

    class Config:
        extra = "ignore"

    @validator("route_policy", pre=True)
    def non_empty_route_policy(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "production_route_plan.route_policy")


class ReusableHighLikeComment(BaseModel):
    comment_text: str
    sharp_angle: str
    why_it_can_get_likes: str
    reuse_instruction: str
    risk_boundary: str

    class Config:
        extra = "ignore"

    @validator("comment_text", "sharp_angle", "why_it_can_get_likes", "reuse_instruction", "risk_boundary", pre=True)
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "reusable_high_like_comment")


class OperationPlan(BaseModel):
    platform_fit: str
    opening_3s_hook: str
    audience_trigger: str
    comment_area_design: str
    publish_timing: str
    success_metric: str
    republish_or_iteration: str

    class Config:
        extra = "ignore"

    @validator(
        "platform_fit",
        "opening_3s_hook",
        "audience_trigger",
        "comment_area_design",
        "publish_timing",
        "success_metric",
        "republish_or_iteration",
        pre=True,
    )
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "operation_plan")


class MaterialChecklist(BaseModel):
    must_have: list[str] = Field(min_items=1)
    better_to_have: list[str] = Field(default_factory=list)
    can_rescue_without: list[str] = Field(default_factory=list)
    must_not_fabricate: list[str] = Field(min_items=1)

    class Config:
        extra = "ignore"

    @validator("must_have", pre=True)
    def must_have_list_text(cls, value: Any) -> list[str]:
        return _string_list(value, "material_checklist.must_have")

    @validator("better_to_have", pre=True)
    def better_to_have_list_text(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        return _string_list(value, "material_checklist.better_to_have")

    @validator("can_rescue_without", pre=True)
    def can_rescue_without_list_text(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        return _string_list(value, "material_checklist.can_rescue_without")

    @validator("must_not_fabricate", pre=True)
    def must_not_fabricate_list_text(cls, value: Any) -> list[str]:
        return _string_list(value, "material_checklist.must_not_fabricate")


class RiskControl(BaseModel):
    risk: str
    control: str
    applies_to: str = ""

    class Config:
        extra = "ignore"

    @validator("risk", "control", pre=True)
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "risk_controls")

    @validator("applies_to", pre=True, always=True)
    def optional_text(cls, value: Any) -> str:
        return _clean_text_value(value)


class RecreateResult(BaseModel):
    doc_title: str = ""
    media_type: str = ""
    editorial_plan: EditorialPlan
    production_route_plan: ProductionRoutePlan
    reusable_high_like_comment: ReusableHighLikeComment
    operation_plan: OperationPlan
    material_checklist: MaterialChecklist
    risk_controls: list[RiskControl] = Field(min_items=1)
    creative_positioning: str
    final_script: str
    video_storyboard: list[StoryboardItem] = Field(default_factory=list)
    image_post_script: list[ImagePostItem] = Field(default_factory=list)
    titles: list[str] = Field(min_items=1)
    hashtags: list[str] = Field(min_items=1)
    production_notes: list[str] | str
    anti_copy_notes: str

    class Config:
        extra = "allow"

    @validator("creative_positioning", "final_script", "anti_copy_notes", pre=True)
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "recreate_result")

    @root_validator(skip_on_failure=True)
    def validate_recreate_payloads(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("video_storyboard") in ("", [], None) and values.get("image_post_script") in ("", [], None):
            raise ValueError("video_storyboard 和 image_post_script 至少一个不能为空")
        if values.get("production_notes") in ("", [], None):
            raise ValueError("production_notes 不能为空")
        return values


def validate_schema(payload: dict[str, Any], schema: type[BaseModel]) -> dict[str, Any]:
    try:
        return _jsonable_model_dict(schema.parse_obj(payload))
    except ValidationError as exc:
        raise SchemaError(str(exc)) from exc


def validate_video_storyboard_granularity(
    payload: dict[str, Any],
    *,
    media_type: str = "video",
    target_duration_sec: float | int | None = None,
) -> dict[str, Any]:
    if str(media_type or payload.get("media_type") or "").lower() != "video":
        return payload
    storyboard = payload.get("video_storyboard")
    if not isinstance(storyboard, list) or not storyboard:
        raise SchemaError(f"{STORYBOARD_GRANULARITY_ERROR_CODE}: video_storyboard 不能为空")
    actual_ranges = [_parse_storyboard_duration(item.get("duration")) for item in storyboard if isinstance(item, dict)]
    if len(actual_ranges) != len(storyboard):
        raise SchemaError(f"{STORYBOARD_GRANULARITY_ERROR_CODE}: video_storyboard 每行 duration 必须是时间段")
    observed_end = max((end for _, end in actual_ranges), default=0.0)
    if observed_end > STORYBOARD_ANALYSIS_MAX_SECONDS + 0.01:
        raise SchemaError(f"{STORYBOARD_GRANULARITY_ERROR_CODE}: 长视频只允许拆解前 {STORYBOARD_ANALYSIS_MAX_SECONDS} 秒")
    target_end = _storyboard_target_end(target_duration_sec, observed_end)
    expected_ranges = _expected_storyboard_ranges(target_end)
    if len(actual_ranges) < len(expected_ranges):
        raise SchemaError(
            f"{STORYBOARD_GRANULARITY_ERROR_CODE}: video_storyboard 行数不足，"
            f"需要覆盖 {_format_duration_ranges(expected_ranges)}"
        )
    for index, (expected, actual) in enumerate(zip(expected_ranges, actual_ranges), 1):
        if not _close_range(expected, actual):
            raise SchemaError(
                f"{STORYBOARD_GRANULARITY_ERROR_CODE}: video_storyboard[{index}].duration 应为 "
                f"{_format_range(expected)}，实际为 {_format_range(actual)}"
            )
    return payload


def _storyboard_target_end(target_duration_sec: float | int | None, observed_end: float) -> int:
    if target_duration_sec not in (None, ""):
        try:
            target = float(target_duration_sec)
        except (TypeError, ValueError):
            target = 0.0
    else:
        target = observed_end
    target = max(target, float(STORYBOARD_OPENING_SECONDS))
    return max(1, min(STORYBOARD_ANALYSIS_MAX_SECONDS, int(target + 0.999)))


def _expected_storyboard_ranges(target_end: int) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    opening_end = min(STORYBOARD_OPENING_SECONDS, target_end)
    for start in range(0, opening_end):
        ranges.append((float(start), float(start + 1)))
    current = STORYBOARD_OPENING_SECONDS
    while current < target_end:
        end = min(current + STORYBOARD_POST_OPENING_STEP_SECONDS, target_end)
        ranges.append((float(current), float(end)))
        current = end
    return ranges


def _parse_storyboard_duration(value: Any) -> tuple[float, float]:
    text = str(value or "").strip()
    normalized = (
        text.replace("—", "-")
        .replace("–", "-")
        .replace("到", "-")
        .replace("至", "-")
        .replace("秒", "s")
    )
    match = re.search(r"(?P<start>\d+(?:\.\d+)?)\s*(?:-|~|～)\s*(?P<end>\d+(?:\.\d+)?)\s*s?", normalized)
    if not match:
        raise SchemaError(f"{STORYBOARD_GRANULARITY_ERROR_CODE}: duration 必须是 0-1s 这种时间段，实际为 {text}")
    start = float(match.group("start"))
    end = float(match.group("end"))
    if end <= start:
        raise SchemaError(f"{STORYBOARD_GRANULARITY_ERROR_CODE}: duration 结束时间必须大于开始时间，实际为 {text}")
    return (start, end)


def _close_range(expected: tuple[float, float], actual: tuple[float, float]) -> bool:
    return abs(expected[0] - actual[0]) <= 0.05 and abs(expected[1] - actual[1]) <= 0.05


def _format_range(item: tuple[float, float]) -> str:
    return f"{_format_seconds(item[0])}-{_format_seconds(item[1])}s"


def _format_seconds(value: float) -> str:
    if abs(value - int(value)) <= 0.001:
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_duration_ranges(items: list[tuple[float, float]]) -> str:
    return "、".join(_format_range(item) for item in items)


def _jsonable_model_dict(model: BaseModel) -> dict[str, Any]:
    return _jsonable(model.dict())


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def validate_evidence_asset_ids(payload: dict[str, Any], valid_asset_ids: set[str]) -> dict[str, Any]:
    if not valid_asset_ids:
        raise SchemaError("缺少可引用的视觉证据 asset_id")
    for idx, item in enumerate(payload.get("video_storyboard") or [], 1):
        if not isinstance(item, dict):
            raise SchemaError(f"video_storyboard[{idx}] 必须是 object")
        asset_id = str(item.get("evidence_asset_id") or "").strip()
        if asset_id not in valid_asset_ids:
            raise SchemaError(f"video_storyboard[{idx}].evidence_asset_id 非法或缺失: {asset_id}")
    image_script = payload.get("image_post_script")
    if isinstance(image_script, list):
        for idx, item in enumerate(image_script, 1):
            if not isinstance(item, dict):
                continue
            asset_id = str(item.get("evidence_asset_id") or "").strip()
            if asset_id not in valid_asset_ids:
                raise SchemaError(f"image_post_script[{idx}].evidence_asset_id 非法或缺失: {asset_id}")
    return payload
