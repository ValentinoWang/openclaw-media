#!/usr/bin/env python3
"""Read one JSON request and print a canonical dry-run reconciliation plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from openclaw_app.services.production_reconciliation_planner import (  # noqa: E402
    PlannerValidationError,
    canonical_plan_json,
    plan_production_reconciliation,
)


def _read_request(path: str) -> object:
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    return json.loads(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a pure, declarative Production Reconciliation plan."
    )
    parser.add_argument(
        "request_path",
        nargs="?",
        default="-",
        help="JSON request path, or - to read stdin (default)",
    )
    parser.add_argument(
        "--input",
        dest="input_path",
        help="Explicitly name the JSON request path instead of the positional argument",
    )
    args = parser.parse_args(argv)
    if args.input_path is not None and args.request_path != "-":
        parser.error("use either request_path or --input, not both")
    request_path = args.input_path or args.request_path

    try:
        request = _read_request(request_path)
        plan = plan_production_reconciliation(request)
    except PlannerValidationError as exc:
        sys.stderr.write(json.dumps({"error": {"code": exc.code}}, sort_keys=True))
        return 2
    except (OSError, UnicodeError, json.JSONDecodeError):
        sys.stderr.write(json.dumps({"error": {"code": "SCHEMA_INVALID"}}, sort_keys=True))
        return 2

    sys.stdout.write(canonical_plan_json(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
