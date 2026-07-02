from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STYLE_POLISH_CAPABILITY = "style_polish"
STYLE_POLISH_CANONICAL_TAG = "【润色】"
STYLE_POLISH_ALIASES = {
    "【润色】",
    "【网感】",
    "【文案优化】",
    "【改标题】",
    "【去AI味】",
    "【小红书文案】",
    "【抖音文案】",
}


def normalize_style_polish_tag(value: str) -> str:
    """Return the canonical capability for explicit style-polish tags."""
    text = str(value or "").strip()
    if not text:
        return ""
    for tag in sorted(STYLE_POLISH_ALIASES, key=len, reverse=True):
        if text == tag or text.startswith(tag):
            return STYLE_POLISH_CAPABILITY
    return ""


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw = [values]
    else:
        raw = list(values)
    return [item for item in (_clean_text(value) for value in raw) if item]


@dataclass(frozen=True)
class StylePolishRequest:
    raw_text: str
    platform: str = ""
    content_type: str = "general"
    goal: str = ""
    account: str = ""
    tone: str = ""
    must_keep: tuple[str, ...] = field(default_factory=tuple)
    avoid: tuple[str, ...] = field(default_factory=tuple)
    variants: int = 3
    creation_id: str = ""
    material_id: str = ""
    draft_id: str = ""
    source_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_text", _clean_text(self.raw_text))
        object.__setattr__(self, "platform", _clean_text(self.platform))
        object.__setattr__(self, "content_type", _clean_text(self.content_type) or "general")
        object.__setattr__(self, "goal", _clean_text(self.goal))
        object.__setattr__(self, "account", _clean_text(self.account))
        object.__setattr__(self, "tone", _clean_text(self.tone))
        object.__setattr__(self, "must_keep", tuple(_clean_list(self.must_keep)))
        object.__setattr__(self, "avoid", tuple(_clean_list(self.avoid)))
        object.__setattr__(self, "source_ids", tuple(_clean_list(self.source_ids)))
        object.__setattr__(self, "variants", max(1, min(int(self.variants or 3), 5)))
        object.__setattr__(self, "creation_id", _clean_text(self.creation_id))
        object.__setattr__(self, "material_id", _clean_text(self.material_id))
        object.__setattr__(self, "draft_id", _clean_text(self.draft_id))

    @property
    def bind_target_id(self) -> str:
        return self.creation_id or self.material_id or self.draft_id

    @property
    def should_bind_creation_run(self) -> bool:
        return bool(self.bind_target_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "platform": self.platform,
            "content_type": self.content_type,
            "goal": self.goal,
            "account": self.account,
            "tone": self.tone,
            "must_keep": list(self.must_keep),
            "avoid": list(self.avoid),
            "variants": self.variants,
            "creation_id": self.creation_id,
            "material_id": self.material_id,
            "draft_id": self.draft_id,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True)
class StyleSourceTrace:
    source_type: str
    source: str
    loaded: bool
    owner: str = ""
    fields: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source": self.source,
            "loaded": self.loaded,
            "owner": self.owner,
            "fields": list(self.fields),
            "note": self.note,
        }


@dataclass(frozen=True)
class StyleVersion:
    name: str
    text: str
    target_use: str
    score_breakdown: dict[str, Any] = field(default_factory=dict)
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    source_trace: tuple[StyleSourceTrace, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "text": self.text,
            "target_use": self.target_use,
            "score_breakdown": dict(self.score_breakdown),
            "risk_notes": list(self.risk_notes),
            "source_trace": [item.to_dict() for item in self.source_trace],
        }


@dataclass(frozen=True)
class StyleFeedbackRecord:
    selection_status: str = "unselected"
    selected_version: str = ""
    pattern_candidate_uri: str = ""
    creative_pattern_promotion: str = "manual_only"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection_status": self.selection_status,
            "selected_version": self.selected_version,
            "pattern_candidate_uri": self.pattern_candidate_uri,
            "creative_pattern_promotion": self.creative_pattern_promotion,
            "note": self.note,
        }


@dataclass(frozen=True)
class StylePolishResult:
    run_id: str
    diagnosis: tuple[str, ...]
    style_strategy: str
    versions: tuple[StyleVersion, ...]
    recommended_version: str
    score_breakdown: dict[str, Any]
    risk_notes: tuple[str, ...]
    source_trace: tuple[StyleSourceTrace, ...]
    feedback_record: StyleFeedbackRecord
    artifact_uri: str
    status: str = "ready"
    creation_run_binding: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "diagnosis": list(self.diagnosis),
            "style_strategy": self.style_strategy,
            "versions": [item.to_dict() for item in self.versions],
            "recommended_version": self.recommended_version,
            "score_breakdown": dict(self.score_breakdown),
            "risk_notes": list(self.risk_notes),
            "source_trace": [item.to_dict() for item in self.source_trace],
            "feedback_record": self.feedback_record.to_dict(),
            "artifact_uri": self.artifact_uri,
            "status": self.status,
            "creation_run_binding": dict(self.creation_run_binding),
        }
