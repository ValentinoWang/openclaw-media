from __future__ import annotations

from pathlib import Path
from typing import Any

from .contract import StylePolishRequest


FORBIDDEN_STYLE_SSOT_NAMES = {
    "creator_voice.yaml": "账号人格必须来自 media_context / media_memory / CreatorProfile",
    "pattern_bank.jsonl": "表达模式必须来自 CreativePattern，不允许另建 pattern bank",
}


def validate_version_text(request: StylePolishRequest, text: str, *, platform_mechanism: dict[str, Any] | None = None) -> list[str]:
    failures: list[str] = []
    candidate = str(text or "")
    for required in request.must_keep:
        if required and required not in candidate:
            failures.append(f"缺少必须保留事实：{required}")
    residual = _remove_must_keep(candidate, request.must_keep)
    for forbidden in request.avoid:
        if forbidden and forbidden in residual:
            failures.append(f"出现禁止表达：{forbidden}")
    for forbidden in (platform_mechanism or {}).get("forbidden_claim_patterns") or []:
        if forbidden and str(forbidden) in residual:
            failures.append(f"出现平台机制禁用宣称：{forbidden}")
    return failures


def _remove_must_keep(candidate: str, must_keep: tuple[str, ...]) -> str:
    residual = candidate
    for phrase in sorted((item for item in must_keep if item), key=len, reverse=True):
        residual = residual.replace(phrase, "")
    return residual


def scan_forbidden_style_ssot(root: str | Path) -> list[str]:
    base = Path(root)
    failures: list[str] = []
    if not base.exists():
        return failures
    for path in base.rglob("*"):
        if path.name in FORBIDDEN_STYLE_SSOT_NAMES:
            failures.append(f"{path}: {FORBIDDEN_STYLE_SSOT_NAMES[path.name]}")
        if path.is_dir() and path.name == "platform_profiles":
            failures.append(f"{path}: 平台机制必须读取 config/platform_mechanisms，不允许复制 platform_profiles")
    return failures
