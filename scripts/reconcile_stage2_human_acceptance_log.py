#!/usr/bin/env python3
"""Rebuild the project human acceptance log using the Stage-2 lane policy.

The shared acceptance Skill derives a workspace's lane from handoff.json. Stage-2
workspaces are still PREPARING and have no handoff, so this project-owned adapter
projects the declared SSOT lane onto those entries without changing fact digests.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLE = PROJECT_ROOT / "agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing"
LEDGER_PATH = PROJECT_ROOT / "acceptance/human-acceptance-log.json"
MARKDOWN_PATH = PROJECT_ROOT / "acceptance/human-acceptance-log.md"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_build_module() -> Any:
    import sys

    original = sys.path[:]
    try:
        sys.path.insert(0, str(BUNDLE))
        return _load_module("stage2_build_for_acceptance_log", BUNDLE / "build_ssot.py")
    finally:
        sys.path[:] = original


def load_renderer_module() -> Any:
    candidates = (
        PROJECT_ROOT / ".agents/skills/design-acceptance-contract/scripts/manage_acceptance_artifacts.py",
        Path("/Users/vsiyo/.codex/skills/design-acceptance-contract/scripts/manage_acceptance_artifacts.py"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return _load_module("acceptance_log_renderer", candidate)
    raise RuntimeError("design-acceptance-contract renderer is unavailable")


def reconcile_payload(payload: dict[str, Any], lane_map: dict[str, bool]) -> dict[str, Any]:
    """Repartition entries while preserving every fact and the source digest."""

    raw_entries = [
        *payload.get("blocking_entries", []),
        *payload.get("non_blocking_entries", []),
    ]
    entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("human acceptance ledger entries must be objects")
        entry = dict(raw)
        task_id = str(entry.get("task_id", ""))
        if task_id in lane_map:
            entry["blocking"] = lane_map[task_id]
        entries.append(entry)
    return {
        **payload,
        "blocking_entries": [entry for entry in entries if entry.get("blocking") is True],
        "non_blocking_entries": [entry for entry in entries if entry.get("blocking") is not True],
    }


def reconcile(*, write: bool = True) -> tuple[dict[str, Any], str]:
    build = load_build_module()
    lane_map = build.human_acceptance_task_lane_map()
    expected = {
        "ST2-HUM-ORG-SCAN": True,
        "ST2-HUM-LARK-READBACK": True,
        "ST2-HUM-SESSION-28D": True,
        "ST2-HUM-LOGIN-FOLD": False,
    }
    if lane_map != expected:
        raise RuntimeError(f"unexpected Stage-2 human acceptance lane map: {lane_map}")

    payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("human acceptance ledger must be a JSON object")
    reconciled = reconcile_payload(payload, lane_map)
    renderer = load_renderer_module()
    markdown = renderer.render_human_log_markdown(reconciled)
    machine = json.dumps(reconciled, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if write:
        LEDGER_PATH.write_text(machine, encoding="utf-8")
        MARKDOWN_PATH.write_text(markdown, encoding="utf-8")
    return reconciled, markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when either log is stale")
    args = parser.parse_args()
    expected, markdown = reconcile(write=False)
    expected_json = json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        actual_json = LEDGER_PATH.read_text(encoding="utf-8")
        actual_markdown = MARKDOWN_PATH.read_text(encoding="utf-8")
        if actual_json != expected_json or actual_markdown != markdown:
            raise SystemExit("Stage-2 human acceptance log is stale")
    else:
        LEDGER_PATH.write_text(expected_json, encoding="utf-8")
        MARKDOWN_PATH.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
