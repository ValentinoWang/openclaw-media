#!/usr/bin/env python3
"""Build one local production-release manifest file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from openclaw_app.services.production_release_manifest import (  # noqa: E402
    ManifestValidationError,
    build_manifest,
)


def _previous_identity(value: str | None) -> dict[str, str] | None:
    if value is None:
        return None
    try:
        candidate = Path(value)
        text = candidate.read_text(encoding="utf-8") if candidate.is_file() else value
        parsed: Any = json.loads(text)
    except (OSError, TypeError, ValueError):
        raise ManifestValidationError("SCHEMA_INVALID") from None
    if not isinstance(parsed, dict):
        raise ManifestValidationError("SCHEMA_INVALID")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--file", dest="file_paths", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-release-identity")
    args = parser.parse_args()

    try:
        manifest = build_manifest(
            args.target_root,
            file_paths=args.file_paths,
            previous_release_identity=_previous_identity(args.previous_release_identity),
        )
        output = json.dumps(
            manifest,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="ascii")
    except ManifestValidationError as error:
        print(f"manifest build failed: {error.code}", file=sys.stderr)
        return 2
    except (OSError, TypeError, ValueError):
        print("manifest build failed: output operation", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
