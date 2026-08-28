#!/usr/bin/env python3
"""Backfill the review gate for legacy Media Growth artifact payloads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from media_vault import MediaVault


def backfill_vault_visibility(vault: MediaVault, *, apply: bool) -> dict[str, int]:
    """Mark unreviewed legacy candidate artifacts as pending review.

    Older artifacts could claim ``cleaned`` before a reviewer had acted. The
    backfill is deliberately narrow: reviewed artifacts and non-growth files
    are left untouched.
    """

    matched = 0
    updated = 0
    for path, payload in _growth_result_payloads(vault):
        if payload.get("quality_status") != "cleaned" or payload.get("reviewed_at"):
            continue
        matched += 1
        if not apply:
            continue
        payload["schema_version"] = str(payload.get("schema_version") or "media_growth_artifact_v1")
        payload["quality_status"] = "pending_review"
        payload["front_end_eligible"] = False
        _write_payload(vault, path, payload)
        updated += 1
    return {"matched_unreviewed_cleaned_candidates": matched, "updated": updated}


def _growth_result_payloads(vault: MediaVault) -> list[tuple[Path, dict[str, Any]]]:
    results: list[tuple[Path, dict[str, Any]]] = []
    for path in vault.root.rglob("result.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _is_growth_payload(payload):
            results.append((path, payload))
    return results


def _is_growth_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and all(
        str(payload.get(key) or "").strip()
        for key in ("artifact_id", "artifact_type", "source_capability_id")
    )


def _write_payload(vault: MediaVault, path: Path, payload: dict[str, Any]) -> None:
    vault.write_json_artifact(
        path.parent,
        path.name,
        payload,
        owner_type=str(payload.get("artifact_type") or "MediaGrowthArtifact"),
        owner_id=str(payload.get("artifact_id") or path.parent.name),
        artifact_type=str(payload.get("artifact_type") or "MediaGrowthArtifact"),
        artifact_id=str(payload.get("artifact_id") or path.parent.name),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="修复旧增长产物的复核状态。")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--vault-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    vault = MediaVault(tenant_id=args.tenant_id, root=args.vault_root)
    print(json.dumps(backfill_vault_visibility(vault, apply=args.apply), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
