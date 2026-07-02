"""Language style and net-sense polishing capability."""

from .contract import (
    STYLE_POLISH_ALIASES,
    STYLE_POLISH_CANONICAL_TAG,
    STYLE_POLISH_CAPABILITY,
    StylePolishRequest,
    StylePolishResult,
    normalize_style_polish_tag,
)
from .service import run_style_polish

__all__ = [
    "STYLE_POLISH_ALIASES",
    "STYLE_POLISH_CANONICAL_TAG",
    "STYLE_POLISH_CAPABILITY",
    "StylePolishRequest",
    "StylePolishResult",
    "normalize_style_polish_tag",
    "run_style_polish",
]
