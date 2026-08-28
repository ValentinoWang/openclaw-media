from __future__ import annotations

import re
from enum import Enum

TRIGGER = "【拆解】"
URL_RE = re.compile(r"https?://[^\s]+")


class WorkflowMode(str, Enum):
    ORGANIZE_ONLY = "organize_only"
    DECONSTRUCT_ONLY = "deconstruct_only"


def should_deconstruct(text: str) -> bool:
    return TRIGGER in (text or "")


def extract_url(text: str) -> str:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip("，,。.)>") if match else ""


class RouteError(ValueError):
    pass


def route(text: str) -> WorkflowMode:
    return route_mode(text)


def route_mode(text: str) -> WorkflowMode:
    has_deconstruct = should_deconstruct(text)
    if has_deconstruct:
        return WorkflowMode.DECONSTRUCT_ONLY
    return WorkflowMode.ORGANIZE_ONLY


def require_executable_mode(text: str) -> WorkflowMode:
    return route_mode(text)
