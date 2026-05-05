from __future__ import annotations

import ast
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


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


class StoryboardItem(BaseModel):
    model_config = ConfigDict(extra="allow")

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

    @field_validator("duration", "visual", mode="before")
    @classmethod
    def required_text(cls, value: Any) -> str:
        return _non_empty_string(str(value or ""), "video_storyboard")

    @field_validator("subtitle", "voiceover", mode="before")
    @classmethod
    def allow_empty_required_text(cls, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        fabricated_markers = ("假设复刻字幕", "假设字幕", "假设口播", "推测字幕", "推测口播")
        if any(marker in text for marker in fabricated_markers):
            return ""
        return str(value)


class ImagePostItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    page_no: int | str
    image_prompt: str
    evidence_asset_id: str = ""
    overlay_text: str = ""
    caption_note: str = ""

    @field_validator("image_prompt", mode="before")
    @classmethod
    def required_image_prompt(cls, value: Any) -> str:
        return _non_empty_string(str(value or ""), "image_post_script.image_prompt")


class DeconstructResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    content_summary: str
    source_summary: str
    viral_mechanism: str
    video_storyboard: list[StoryboardItem] = Field(min_length=1)
    image_post_script: list[ImagePostItem] = Field(min_length=1)
    republish_copy: dict[str, Any] | str
    avoid_plagiarism_notes: str
    production_checklist: list[str] = Field(min_length=1)
    target_audience: list[str] = Field(default_factory=list)
    pain_or_pleasure_points: list[str] = Field(default_factory=list)
    track_tags: list[str] = Field(default_factory=list)

    @field_validator("content_summary", "source_summary", "viral_mechanism", "avoid_plagiarism_notes", mode="before")
    @classmethod
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "deconstruct_result")

    @field_validator("production_checklist", mode="before")
    @classmethod
    def non_empty_checklist(cls, value: Any) -> Any:
        if not value:
            raise ValueError("production_checklist 不能为空")
        return value

    @field_validator("target_audience", "pain_or_pleasure_points", "track_tags", mode="before")
    @classmethod
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

    @model_validator(mode="after")
    def validate_script_payloads(self) -> "DeconstructResult":
        if self.image_post_script in ("", [], None):
            raise ValueError("image_post_script 不能为空")
        if self.republish_copy in ("", {}, None):
            raise ValueError("republish_copy 不能为空")
        return self


class RecreateResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    doc_title: str = ""
    media_type: str = ""
    creative_positioning: str
    final_script: str
    video_storyboard: list[StoryboardItem] = Field(default_factory=list)
    image_post_script: list[ImagePostItem] = Field(default_factory=list)
    titles: list[str] = Field(min_length=1)
    hashtags: list[str] = Field(min_length=1)
    production_notes: list[str] | str
    anti_copy_notes: str

    @field_validator("creative_positioning", "final_script", "anti_copy_notes", mode="before")
    @classmethod
    def non_empty_text(cls, value: Any) -> str:
        return _non_empty_string(_clean_text_value(value), "recreate_result")

    @model_validator(mode="after")
    def validate_recreate_payloads(self) -> "RecreateResult":
        if self.video_storyboard in ("", [], None) and self.image_post_script in ("", [], None):
            raise ValueError("video_storyboard 和 image_post_script 至少一个不能为空")
        if self.production_notes in ("", [], None):
            raise ValueError("production_notes 不能为空")
        return self


def validate_schema(payload: dict[str, Any], schema: type[BaseModel]) -> dict[str, Any]:
    try:
        return schema.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        raise SchemaError(str(exc)) from exc


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


class NativeVideoObservation(BaseModel):
    model_config = ConfigDict(extra="allow")

    timeline_summary: list[Any] | dict[str, Any] | str = Field(default_factory=list)
    visual_events: list[Any] | dict[str, Any] | str = Field(default_factory=list)
    audio_events: list[Any] | dict[str, Any] | str = Field(default_factory=list)
    speech_summary: list[Any] | dict[str, Any] | str = ""
    music_or_sound_effects: list[Any] | dict[str, Any] | str = Field(default_factory=list)
    hook_moments: list[Any] | dict[str, Any] | str = Field(default_factory=list)
    uncertainty_notes: list[Any] | dict[str, Any] | str = Field(default_factory=list)
