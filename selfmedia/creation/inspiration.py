"""Stable contract for archived creation-inspiration task cards.

The live creation workflow owns model invocation and persistence.  This module
keeps the executable result contract and its human-readable execution card
available to callers that need to validate or render an already-produced
inspiration result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, validator

from common.social_runtime import local_now_iso as _now_iso


class CreationInspirationStoryboardRow(BaseModel):
    time: str
    visual: str
    subtitle: str
    sound: str
    shooting_note: str

    @validator("time", "visual", "subtitle", "sound", "shooting_note", pre=True)
    @classmethod
    def require_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("storyboard row requires text")
        return text


class CreationInspirationResult(BaseModel):
    title: str
    theme: str
    track: str = ""
    platform: str = ""
    content_type: str = ""
    cleaned_inspiration: str
    material_summary: str
    source_kind: str = ""
    signal_type: str = ""
    emotion_trigger: str = ""
    trigger_sentence: str = ""
    event_scene: str = ""
    misalignment: str = ""
    core_viewpoint: str = ""
    reader_problem: str = ""
    material_stage: str = ""
    recreation_direction: str
    content_angles: list[str] = Field(default_factory=list)
    reuse_angles: list[str] = Field(default_factory=list)
    derivative_topics: list[str] = Field(default_factory=list)
    publishable_formats: list[str] = Field(default_factory=list)
    hook_options: list[str] = Field(default_factory=list)
    title_options: list[str] = Field(default_factory=list)
    script_outline: list[str] = Field(default_factory=list)
    execution_brief: str
    route_map: list[str]
    shooting_schedule: list[str]
    shot_checklist: list[str]
    storyboard: list[CreationInspirationStoryboardRow]
    publishing_plan: list[str]
    score: int
    score_reason: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @validator(
        "title",
        "theme",
        "cleaned_inspiration",
        "material_summary",
        "recreation_direction",
        "execution_brief",
        "score_reason",
        pre=True,
    )
    @classmethod
    def require_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("creation inspiration result requires text")
        return text

    @validator("route_map", "shooting_schedule", "shot_checklist", "storyboard", "publishing_plan")
    @classmethod
    def require_non_empty_list(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("creation inspiration execution card requires all execution sections")
        return value

    @validator("score", pre=True)
    @classmethod
    def normalize_score(cls, value: Any) -> int:
        try:
            score = int(float(value))
        except (TypeError, ValueError):
            score = 0
        return max(0, min(100, score))


def _section_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [f"- {item}" for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _storyboard_lines(value: Any) -> list[str]:
    rows = value if isinstance(value, list) else []
    output = ["| 时间 | 画面 | 字幕/口播 | 声音/拍摄注意 |", "|---|---|---|---|"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        sound_note = "<br>".join(
            str(item).strip()
            for item in (row.get("sound"), row.get("shooting_note"))
            if str(item).strip()
        )
        output.append(
            "| "
            + " | ".join(
                str(item or "").replace("\n", "<br>").replace("|", "/")
                for item in (row.get("time"), row.get("visual"), row.get("subtitle"), sound_note)
            )
            + " |"
        )
    return output


def format_inspiration_text(raw_text: str, result: dict[str, Any]) -> str:
    """Render a validated result with creator actions before audit evidence."""
    created_at = str(result.get("created_at") or _now_iso())
    title = str(result.get("title") or "未命名灵感").strip()
    attachments = result.get("attachment_paths") or []
    source = "\n".join(f"- {item}" for item in attachments) if attachments else "未提供附件，按文字灵感归档"
    transfer_points = [
        *(result.get("strengths") or []),
        *(result.get("content_angles") or []),
        *(result.get("reuse_angles") or []),
    ]
    execution_sections: list[tuple[str, Any]] = [
        ("创作者执行稿", result.get("execution_brief")),
        ("打卡路线图", result.get("route_map")),
        ("拍摄节奏", result.get("shooting_schedule")),
        ("镜头清单", result.get("shot_checklist")),
        ("分镜脚本", _storyboard_lines(result.get("storyboard"))),
        ("发布计划", result.get("publishing_plan")),
    ]
    evidence = "\n".join(
        item
        for item in (
            f"素材来源：{source}",
            f"原始内容：{raw_text.strip() or '无文字，仅附件'}",
            f"来源类型：{result.get('source_kind') or '待判断'}",
            f"信号类型：{result.get('signal_type') or '待判断'}",
            f"情绪触发：{result.get('emotion_trigger') or '待判断'}",
            f"触发原话：{result.get('trigger_sentence') or '待判断'}",
            f"事件场景：{result.get('event_scene') or '待判断'}",
            f"错位点：{result.get('misalignment') or '待判断'}",
            f"素材状态：{result.get('material_stage') or '待判断'}",
            f"灵感评分：{result.get('score')}/100：{result.get('score_reason') or ''}",
        )
        if item
    )
    reference_sections: list[tuple[str, Any]] = [
        ("创作灵感", result.get("cleaned_inspiration")),
        ("核心观点", result.get("core_viewpoint")),
        ("读者问题", result.get("reader_problem")),
        ("转化目标", "\n".join(item for item in (result.get("platform"), result.get("content_type"), result.get("theme")) if item) or "待明确"),
        ("一鱼多吃方向", result.get("derivative_topics") or result.get("reuse_angles")),
        ("拆解-再创方向", result.get("recreation_direction")),
        ("建议产物", result.get("publishable_formats")),
        ("开头钩子", result.get("hook_options")),
        ("标题备选", result.get("title_options")),
        ("脚本/图文结构", result.get("script_outline")),
        ("证据与边界", evidence),
        ("可迁移点", transfer_points),
        ("待补充信息", result.get("risks")),
        ("下一步", result.get("next_actions")),
        ("标签", "、".join(result.get("tags") or [])),
    ]
    output = [
        f"创作灵感任务卡｜{created_at}｜{title}",
        "标签：创作-灵感",
        f"主题：{result.get('theme') or '待明确'}",
        f"赛道：{result.get('track') or '待明确'}",
        "",
    ]
    for section_title, value in [*execution_sections, *reference_sections]:
        body = _section_lines(value)
        if body:
            output.append(f"## {section_title}")
            output.extend(body)
            output.append("")
    return "\n".join(output).strip()
