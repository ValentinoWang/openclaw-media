#!/usr/bin/env python3
"""Remove raw URLs from legacy creator-facing Media Growth display text."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from media_vault import MediaVault
from selfmedia.growth.feishu_summary_sync import sync_growth_summary_artifact


_URL_RE = re.compile(r"https?://[^\s<>\]\)\"'，。；、]+")


def backfill_vault_display(
    vault: MediaVault,
    *,
    apply: bool,
    sync_growth_summary: bool = True,
) -> dict[str, int]:
    """Strip raw URLs from display fields without changing stored evidence URLs."""

    matched = 0
    updated = 0
    for path, payload in _growth_result_payloads(vault):
        title = str(payload.get("display_title") or "")
        summary = str(payload.get("display_summary") or "")
        if not (_URL_RE.search(title) or _URL_RE.search(summary)):
            continue
        matched += 1
        if not apply:
            continue
        payload["display_title"] = _strip_urls(title)
        payload["display_summary"] = _strip_urls(summary)
        _write_payload(vault, path, payload)
        if sync_growth_summary:
            sync_growth_summary_artifact(payload, tenant_id=vault.tenant_id)
        updated += 1
    return {"matched_display_url_artifacts": matched, "updated": updated}


def _strip_urls(value: str) -> str:
    return " ".join(_URL_RE.sub(" ", value).split())


def _growth_result_payloads(vault: MediaVault) -> list[tuple[Path, dict[str, Any]]]:
    results: list[tuple[Path, dict[str, Any]]] = []
    for path in vault.root.rglob("result.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and all(
            str(payload.get(key) or "").strip()
            for key in ("artifact_id", "artifact_type", "source_capability_id")
        ):
            results.append((path, payload))
    return results


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
    parser = argparse.ArgumentParser(description="移除旧增长产物展示文字中的原始链接。")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--vault-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-growth-summary-sync", action="store_true")
    args = parser.parse_args()
    vault = MediaVault(tenant_id=args.tenant_id, root=args.vault_root)
    result = backfill_vault_display(
        vault,
        apply=args.apply,
        sync_growth_summary=not args.skip_growth_summary_sync,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
