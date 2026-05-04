from __future__ import annotations

import re
from enum import Enum

TRIGGER = "【拆解】"
RECREATE_TRIGGER = "【再创作】"
URL_RE = re.compile(r"https?://[^\s]+")


class WorkflowMode(str, Enum):
    ORGANIZE_ONLY = "organize_only"
    DECONSTRUCT_ONLY = "deconstruct_only"
    DECONSTRUCT_AND_RECREATE = "deconstruct_and_recreate"
    INVALID_RECREATE_ONLY = "invalid_recreate_only"


def should_deconstruct(text: str) -> bool:
    return TRIGGER in (text or "")


def extract_url(text: str) -> str:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip("，,。.)>") if match else ""


def should_recreate(text: str) -> bool:
    return RECREATE_TRIGGER in (text or "")


class RouteError(ValueError):
    pass


def route(text: str) -> WorkflowMode:
    return route_mode(text)


def route_mode(text: str) -> WorkflowMode:
    has_deconstruct = should_deconstruct(text)
    has_recreate = should_recreate(text)
    if has_recreate and not has_deconstruct:
        return WorkflowMode.INVALID_RECREATE_ONLY
    if has_deconstruct and has_recreate:
        return WorkflowMode.DECONSTRUCT_AND_RECREATE
    if has_deconstruct:
        return WorkflowMode.DECONSTRUCT_ONLY
    return WorkflowMode.ORGANIZE_ONLY


def require_executable_mode(text: str) -> WorkflowMode:
    mode = route_mode(text)
    if mode == WorkflowMode.INVALID_RECREATE_ONLY:
        raise RouteError("只有【再创作】不允许执行：必须同时包含【拆解】，先产出拆解结果。")
    return mode
