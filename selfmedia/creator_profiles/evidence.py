from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from media_vault.vault import MediaVault

from .schemas import platform_slug


def evidence_uri(platform: str, author_id: str, run_id: str, *, tenant_id: str, root: Path | None = None) -> str:
    vault = MediaVault(tenant_id=tenant_id, root=root)
    return vault.to_uri(evidence_dir(platform, author_id, run_id, tenant_id=tenant_id, root=root))


def evidence_dir(
    platform: str,
    author_id: str,
    run_id: str,
    *,
    tenant_id: str,
    root: Path | None = None,
) -> Path:
    vault = MediaVault(tenant_id=tenant_id, root=root)
    return vault.root / "creator_profiles" / platform_slug(platform) / str(author_id or "unknown") / run_id


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_evidence_bundle(
    *,
    run_id: str,
    resolver_result: dict[str, Any],
    tenant_id: str,
    root: Path | None = None,
) -> dict[str, Any]:
    platform = str(resolver_result.get("platform") or "")
    author_id = str(resolver_result.get("resolved_author_id") or resolver_result.get("input_platform_id") or "unknown")
    vault = MediaVault(tenant_id=tenant_id, root=root)
    target = evidence_dir(platform, author_id, run_id, tenant_id=tenant_id, root=root)
    target.mkdir(parents=True, exist_ok=True)

    raw_dom = str(resolver_result.get("raw_dom") or "")
    rendered_text = str(resolver_result.get("rendered_text") or resolver_result.get("visible_text") or "")
    screenshot_bytes = resolver_result.get("screenshot_bytes") or b""
    extracted_profile = resolver_result.get("extracted_profile") if isinstance(resolver_result.get("extracted_profile"), dict) else {}

    clean_resolver = {
        key: value
        for key, value in resolver_result.items()
        if key not in {"raw_dom", "screenshot_bytes"} and not isinstance(value, bytes)
    }
    metadata = {
        "run_id": run_id,
        "platform": platform,
        "input_platform_id": resolver_result.get("input_platform_id", ""),
        "input_platform_id_type": resolver_result.get("input_platform_id_type", ""),
        "resolved_author_id": author_id,
        "resolved_profile_url": resolver_result.get("resolved_profile_url", ""),
        "resolve_status": resolver_result.get("resolve_status", ""),
        "extractor_version": "creator_profile_enrichment.v1",
        "write_status": "candidate_only",
        "evidence_uri": vault.to_uri(target),
    }
    write_json(target / "metadata.json", metadata)
    write_json(target / "resolver_result.json", clean_resolver)
    write_json(target / "rendered_text.json", {"text": rendered_text})
    write_json(target / "extracted_profile.json", extracted_profile)
    if raw_dom:
        with gzip.open(target / "raw_dom.html.gz", "wt", encoding="utf-8") as fh:
            fh.write(raw_dom)
    if screenshot_bytes:
        (target / "screenshot.png").write_bytes(screenshot_bytes)
    elif resolver_result.get("screenshot_error"):
        write_json(target / "screenshot_error.json", {"error": str(resolver_result.get("screenshot_error") or "")})
    return {"dir": str(target), "uri": metadata["evidence_uri"], "metadata": metadata}
