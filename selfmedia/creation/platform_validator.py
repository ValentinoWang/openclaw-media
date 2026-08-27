from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "issues": [item.to_dict() for item in self.issues]}


def count_title_chars(title: str) -> int:
    return len(title.strip())


def validate_platform_draft(platform: str, content_type: str, draft: dict[str, Any]) -> ValidationResult:
    if platform == "小红书":
        return validate_xhs_draft(content_type, draft)
    if platform == "抖音":
        return validate_douyin_draft(content_type, draft)
    return ValidationResult(ok=False, issues=[ValidationIssue("platform", f"不支持的平台：{platform}")])


def validate_xhs_draft(content_type: str, draft: dict[str, Any]) -> ValidationResult:
    issues: list[ValidationIssue] = []
    title = str(draft.get("title") or "").strip()
    tags = _list_value(draft.get("tags"))
    if count_title_chars(title) > 20:
        issues.append(ValidationIssue("title", "小红书标题必须不超过 20 个字符"))
    if not title:
        issues.append(ValidationIssue("title", "小红书标题不能为空"))
    if not 5 <= len(tags) <= 10:
        issues.append(ValidationIssue("tags", "小红书 Tags 需要 5-10 个强相关标签，不为凑数硬造"))
    if content_type == "图文" and not _list_value(draft.get("image_script")):
        issues.append(ValidationIssue("image_script", "小红书图文必须有图片脚本"))
    if content_type == "视频" and not _list_value(draft.get("storyboard")):
        issues.append(ValidationIssue("storyboard", "小红书视频必须有分镜脚本"))
    return ValidationResult(ok=not issues, issues=issues)


def validate_douyin_draft(content_type: str, draft: dict[str, Any]) -> ValidationResult:
    issues: list[ValidationIssue] = []
    title = str(draft.get("title") or "").strip()
    tags = _list_value(draft.get("tags"))
    if not title:
        issues.append(ValidationIssue("title", "抖音标题不能为空"))
    if not 3 <= len(tags) <= 5:
        issues.append(ValidationIssue("tags", "抖音 Tags 需要 3-5 个强相关标签，不为凑数硬造"))
    if content_type == "视频":
        if not str(draft.get("hook_3s") or "").strip():
            issues.append(ValidationIssue("hook_3s", "抖音视频必须有前 3 秒钩子"))
        if not _list_value(draft.get("storyboard")):
            issues.append(ValidationIssue("storyboard", "抖音视频必须有分镜脚本"))
        if not str(draft.get("voiceover") or "").strip():
            issues.append(ValidationIssue("voiceover", "抖音视频必须有口播"))
        if not _list_value(draft.get("subtitles")):
            issues.append(ValidationIssue("subtitles", "抖音视频必须有字幕"))
    if content_type == "图文" and not (_list_value(draft.get("image_script")) or _list_value(draft.get("carousel"))):
        issues.append(ValidationIssue("image_script", "抖音图文必须有图文页脚本或轮播结构"))
    return ValidationResult(ok=not issues, issues=issues)

def _list_value(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [])]
    return [value]
