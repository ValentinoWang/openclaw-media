from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from media_model.contract import resolve_media_model_contract_path

from .contract import StylePolishRequest, StyleSourceTrace


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_ROOT = ROOT / "data" / "media_memory"
DEFAULT_PLATFORM_MECHANISM_ROOT = ROOT / "config" / "platform_mechanisms"
ANTI_PATTERNS_PATH = Path(__file__).resolve().parent / "assets" / "anti_patterns.yaml"
STYLE_DEFAULTS_PATH = Path(__file__).resolve().parent / "assets" / "style_defaults.yaml"

PLATFORM_FILE_MAP = {
    "抖音": "douyin.json",
    "douyin": "douyin.json",
    "小红书": "xiaohongshu.json",
    "xiaohongshu": "xiaohongshu.json",
    "xhs": "xiaohongshu.json",
    "b站": "bilibili.json",
    "bilibili": "bilibili.json",
}


@dataclass(frozen=True)
class StyleContext:
    media_context: dict[str, Any] = field(default_factory=dict)
    creator_profile: dict[str, Any] = field(default_factory=dict)
    platform_mechanism: dict[str, Any] = field(default_factory=dict)
    creative_pattern_contract: dict[str, Any] = field(default_factory=dict)
    recent_lessons: tuple[str, ...] = field(default_factory=tuple)
    proven_patterns: tuple[str, ...] = field(default_factory=tuple)
    avoid_patterns: tuple[str, ...] = field(default_factory=tuple)
    anti_patterns: tuple[str, ...] = field(default_factory=tuple)
    style_defaults: dict[str, Any] = field(default_factory=dict)
    source_trace: tuple[StyleSourceTrace, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_context": self.media_context,
            "creator_profile": self.creator_profile,
            "platform_mechanism": self.platform_mechanism,
            "creative_pattern_contract": self.creative_pattern_contract,
            "recent_lessons": list(self.recent_lessons),
            "proven_patterns": list(self.proven_patterns),
            "avoid_patterns": list(self.avoid_patterns),
            "anti_patterns": list(self.anti_patterns),
            "style_defaults": self.style_defaults,
            "source_trace": [item.to_dict() for item in self.source_trace],
        }


def load_style_context(
    request: StylePolishRequest,
    *,
    tenant_id: str,
    memory_root: str | Path | None = None,
    platform_mechanism_root: str | Path | None = None,
    allow_live_creator_profile: bool = False,
) -> StyleContext:
    traces: list[StyleSourceTrace] = []
    media_context = _load_media_context(
        request,
        tenant_id=tenant_id,
        memory_root=Path(memory_root or DEFAULT_MEMORY_ROOT),
        allow_live_creator_profile=allow_live_creator_profile,
    )
    loaded = media_context.get("loaded") or {}
    traces.append(
        StyleSourceTrace(
            source_type="account_persona",
            source=str(media_context.get("memory_root") or DEFAULT_MEMORY_ROOT),
            loaded=bool(loaded.get("account_profile")),
            owner="selfmedia.context.media_context",
            fields=("account_profile", "recent_creations", "recent_reviews", "public_persona_boundaries"),
            note="Loaded through canonical selfmedia.context; no creator_voice.yaml source is used.",
        )
    )

    profile = media_context.get("account_profile") or {}
    platform_mechanism = _load_platform_mechanism(request.platform, Path(platform_mechanism_root or DEFAULT_PLATFORM_MECHANISM_ROOT), traces)
    creative_pattern_contract = _load_creative_pattern_contract(traces)
    anti_patterns = tuple(_read_yaml_list(ANTI_PATTERNS_PATH, "avoid_phrases"))
    traces.append(
        StyleSourceTrace(
            source_type="anti_patterns",
            source=str(ANTI_PATTERNS_PATH),
            loaded=ANTI_PATTERNS_PATH.exists(),
            owner="selfmedia.style.assets",
            fields=("avoid_phrases",),
            note="Expression guard only; not an account-persona or pattern SSOT.",
        )
    )
    style_defaults = _read_yaml_mapping(STYLE_DEFAULTS_PATH)
    traces.append(
        StyleSourceTrace(
            source_type="style_defaults",
            source=str(STYLE_DEFAULTS_PATH),
            loaded=STYLE_DEFAULTS_PATH.exists(),
            owner="selfmedia.style.assets",
            fields=("default_strategy", "default_variants", "default_version_name"),
            note="Generic defaults only; not a replacement for CreatorProfile or media_memory.",
        )
    )

    return StyleContext(
        media_context=media_context,
        creator_profile=profile,
        platform_mechanism=platform_mechanism,
        creative_pattern_contract=creative_pattern_contract,
        recent_lessons=tuple(_clean_list(profile.get("recent_lessons"))),
        proven_patterns=tuple(_clean_list(profile.get("proven_patterns"))),
        avoid_patterns=tuple(_clean_list(profile.get("avoid_patterns"))),
        anti_patterns=anti_patterns,
        style_defaults=style_defaults,
        source_trace=tuple(traces),
    )


def _load_media_context(
    request: StylePolishRequest,
    *,
    tenant_id: str,
    memory_root: Path,
    allow_live_creator_profile: bool,
) -> dict[str, Any]:
    from selfmedia.context.media_context import build_media_context

    if allow_live_creator_profile:
        return build_media_context(
            tenant_id=tenant_id,
            platform=request.platform,
            account=request.account,
            topic=request.raw_text[:120],
            keywords=list(request.source_ids),
            root=memory_root,
            limit=5,
        )
    with _disabled_live_creator_profile():
        return build_media_context(
            tenant_id=tenant_id,
            platform=request.platform,
            account=request.account,
            topic=request.raw_text[:120],
            keywords=list(request.source_ids),
            root=memory_root,
            limit=5,
        )


def _load_platform_mechanism(platform: str, root: Path, traces: list[StyleSourceTrace]) -> dict[str, Any]:
    filename = PLATFORM_FILE_MAP.get(str(platform or "").strip().lower()) or PLATFORM_FILE_MAP.get(str(platform or "").strip())
    if not filename:
        traces.append(
            StyleSourceTrace(
                source_type="platform_mechanism",
                source=str(root),
                loaded=False,
                owner="config.platform_mechanisms",
                fields=("baseline_summary", "core_signals", "forbidden_claim_patterns"),
                note="No platform-specific mechanism requested.",
            )
        )
        return {}
    path = root / filename
    if not path.exists():
        traces.append(
            StyleSourceTrace(
                source_type="platform_mechanism",
                source=str(path),
                loaded=False,
                owner="config.platform_mechanisms",
                fields=("baseline_summary", "core_signals", "forbidden_claim_patterns"),
                note="Expected platform mechanism file is missing.",
            )
        )
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    traces.append(
        StyleSourceTrace(
            source_type="platform_mechanism",
            source=str(path),
            loaded=True,
            owner="config.platform_mechanisms",
            fields=("baseline_summary", "core_signals", "forbidden_claim_patterns"),
            note="Loaded from platform_mechanisms; no platform_profiles copy is used.",
        )
    )
    return payload


def _load_creative_pattern_contract(traces: list[StyleSourceTrace]) -> dict[str, Any]:
    contract_path = resolve_media_model_contract_path()
    if not contract_path.exists():
        traces.append(
            StyleSourceTrace(
                source_type="creative_pattern_contract",
                source=str(contract_path),
                loaded=False,
                owner="media_model.contract",
                fields=("CreativePattern", "pattern_status"),
                note="Media Model v2 contract is missing.",
            )
        )
        return {}
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    fields = ((contract.get("entity_contracts") or {}).get("CreativePattern") or {}).get("fields") or {}
    traces.append(
        StyleSourceTrace(
            source_type="creative_pattern_contract",
            source=str(contract_path),
            loaded=bool(fields),
            owner="media_model.contract",
            fields=tuple(sorted(fields.keys())),
            note="Loaded CreativePattern contract only; StylePolish does not auto-write CreativePattern records.",
        )
    )
    return fields


def _read_yaml_list(path: Path, key: str) -> list[str]:
    mapping = _read_yaml_mapping(path)
    values = mapping.get(key) or []
    if isinstance(values, list):
        return [str(item).strip() for item in values if str(item).strip()]
    return []


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    mapping: dict[str, Any] = {}
    current_key = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not raw_line.startswith(" ") and line.endswith(":"):
            current_key = line[:-1].strip()
            mapping[current_key] = []
            continue
        if current_key and line.startswith("- "):
            mapping.setdefault(current_key, []).append(line[2:].strip().strip('"').strip("'"))
            continue
        if ":" in line and not raw_line.startswith(" "):
            key, value = line.split(":", 1)
            mapping[key.strip()] = value.strip().strip('"').strip("'")
    return mapping


def _clean_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values.strip()] if values.strip() else []
    return [str(value).strip() for value in values if str(value).strip()]


@contextmanager
def _disabled_live_creator_profile() -> Iterator[None]:
    key = "OPENCLAW_MEDIA_CONTEXT_DISABLE_FEISHU_CREATOR_PROFILE"
    old_value = os.environ.get(key)
    os.environ[key] = "1"
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_value
