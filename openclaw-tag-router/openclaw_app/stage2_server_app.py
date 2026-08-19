"""Minimal application shell for the isolated Stage-2 production server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .services.stage2_gateway import Stage2Gateway


class Stage2ServerApp:
    """Load only settings plus the injected Stage-2 gateway.

    The normal OpenClawApp also initializes every tag-router capability. The
    isolated production release must not make Stage-2 startup depend on those
    unrelated runtime profiles.
    """

    def __init__(self, settings_path: str | Path, *, stage2_gateway: Stage2Gateway) -> None:
        if not isinstance(stage2_gateway, Stage2Gateway):
            raise TypeError("Stage-2 gateway is required")
        self.settings_path = Path(settings_path)
        parsed = yaml.safe_load(self.settings_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("Stage-2 settings must be an object")
        self.settings: dict[str, Any] = parsed
        self.stage2_gateway = stage2_gateway

    def process_stage2(self, mode: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.stage2_gateway.run(mode, payload)


__all__ = ["Stage2ServerApp"]
