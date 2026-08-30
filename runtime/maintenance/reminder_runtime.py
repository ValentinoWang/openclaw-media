"""Shared helpers for maintenance scripts that drive openclaw-feishu-reminder.

Three backfill scripts under ``runtime/maintenance/backfills/`` and
``runtime/maintenance/sync/daily_todo_checklist_sync.py`` each independently
resolved the reminder script path, the activity-config path, and (one of
them) a copy of the same "dynamically import reminder.py" loader. This
module is the one place that owns those, per the pe-07 dedup audit --
``common/env.py:feishu_reminder_root()`` (the pe-06 finding) resolves the
checkout root; this module builds the specific file paths under it and the
importlib loader that turns ``reminder.py`` into a usable module object.

Callers keep their own module-level ``REMINDER_PATH`` / ``ACTIVITY_CONFIG_PATH``
constants (existing tests patch those per-module) and their own thin
``load_reminder()`` wrapper that names a distinct ``sys.modules`` key --
see the docstring on :func:`load_reminder_module` for why the module name
stays a required, per-caller argument rather than being hardcoded here.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from common.env import feishu_reminder_root


def reminder_script_path() -> Path:
    """Resolve reminder.py's path: ``OPENCLAW_FEISHU_REMINDER_SCRIPT`` overrides
    the default of ``<feishu_reminder_root()>/reminder.py``."""
    return Path(os.getenv("OPENCLAW_FEISHU_REMINDER_SCRIPT") or feishu_reminder_root() / "reminder.py")


def activity_config_path() -> Path:
    """Resolve the 近期活动 Bitable config path: ``OPENCLAW_ACTIVITY_CONFIG_PATH``
    overrides the default of ``<feishu_reminder_root()>/wiki-activity-config.json``."""
    return Path(os.getenv("OPENCLAW_ACTIVITY_CONFIG_PATH") or feishu_reminder_root() / "wiki-activity-config.json")


def daily_config_path() -> Path:
    """Resolve the daily-checklist Bitable config path: ``OPENCLAW_DAILY_CONFIG_PATH``
    overrides the default of ``<feishu_reminder_root()>/config.json``."""
    return Path(os.getenv("OPENCLAW_DAILY_CONFIG_PATH") or feishu_reminder_root() / "config.json")


def load_reminder_module(path: Path, module_name: str) -> Any:
    """Dynamically import ``reminder.py`` from ``path`` under ``module_name``.

    ``module_name`` is a required argument rather than a shared constant:
    each caller registers itself under a distinct ``sys.modules`` key
    (``openclaw_feishu_reminder_status_backfill``,
    ``openclaw_feishu_reminder_backfill``,
    ``openclaw_feishu_reminder_platform_backfill``, ...) so that if two
    of these scripts are ever imported in the same process, one does not
    shadow the other via the module cache -- they currently run as
    independent CLI invocations, but there is no reason to give that up
    when collapsing the duplication.
    """
    if not path.is_file():
        raise SystemExit(
            f"missing required reminder script: {path}; "
            "set OPENCLAW_FEISHU_REMINDER_SCRIPT or OPENCLAW_FEISHU_REMINDER_ROOT"
        )
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path, *, env_name: str) -> dict[str, Any]:
    """Read a required JSON config file, raising a recovery hint if it's missing."""
    if not path.is_file():
        raise SystemExit(f"missing required JSON config: {path}; set {env_name}")
    return json.loads(path.read_text(encoding="utf-8"))
