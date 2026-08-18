#!/usr/bin/env python3
"""Backfill missing asset covers from retained source evidence.

The command is dry-run by default. It never replaces an existing cover and
never creates synthetic imagery. Execute mode uploads one verified image per
missing Base record and reads the record back before reporting success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync_lark_base_projection import (
    _build_feishu,
    _load_env_file,
    _load_registry_table_bindings,
)


TENANT_ID = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
DEFAULT_DOWNLOADS_ROOT = Path(
    "/home/ubuntu/selfmedia-tools/selfmedia/deconstruct/viral_content/downloads"
)
DEFAULT_EVIDENCE_ROOT = Path(
    f"/home/ubuntu/selfmedia-tools/data/media_vault/tenants/{TENANT_ID}/source_assets/unknown_platform"
)
DEFAULT_CACHE_ROOT = Path("/home/ubuntu/selfmedia-tools/data/media_thumbnail_backfill_cache")

# Every entry points to retained source media or a retained source attachment.
# There is intentionally no synthetic/text-card fallback.
RECOVERY_CATALOG: dict[str, dict[str, str]] = {
    "sha256:1a906d6fd0107aa57d0c2b9eb034704d706b39bbdaa30ef98516974b26730003": {
        "kind": "local_source_image",
        "relative_path": "douyin-7621754135658207067/images/image-01.webp",
    },
    "sha256:19499178f38d2bce76ce85450602eb738e6ae719ec5d2b64f9be9371786652de": {
        "kind": "evidence_video_frame",
        "evidence_field": "封面图/前五秒",
    },
    "sha256:a4fff7d5aae051ac92685033b8476f79cbc3c385caa70b9e65c1fbc820344eab": {
        "kind": "local_source_image",
        "relative_path": "video-0a78a167206b/preview/first_frame.jpg",
    },
    "sha256:315d47ac55e0251cb7ed0b5825a9ad2a3d89207fb857ce522e4f24acfe8968b7": {
        "kind": "local_source_image",
        "relative_path": "douyin-7654878400637507438/images/image-01.webp",
    },
    "sha256:c7d3f02af8a97453c6ac50675db91f31a03aa68177fe5a4de31885e7ea291793": {
        "kind": "local_source_image",
        "relative_path": "douyin-7634196978826595961/images/image-01.webp",
    },
    "sha256:0bcfd83c13b7a039987abfbf679be62c8c45aa1e902054f2e3cb07825db4a439": {
        "kind": "local_source_image",
        "relative_path": "douyin-7634196978826595961/images/image-01.webp",
    },
}


@dataclass(frozen=True)
class RecoveryCandidate:
    path: Path
    provenance: str


@dataclass(frozen=True)
class RecoveryClassification:
    status: str
    candidate: RecoveryCandidate | None = None
    reason: str = ""


def _is_image(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    with path.open("rb") as handle:
        header = handle.read(16)
    return (
        header.startswith(b"\xff\xd8\xff")
        or header.startswith(b"\x89PNG\r\n\x1a\n")
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )


def classify_recovery(
    fields: dict[str, Any],
    *,
    downloads_root: Path,
    evidence_root: Path,
    cache_root: Path,
) -> RecoveryClassification:
    if fields.get("封面附件"):
        return RecoveryClassification("skipped_existing_cover")
    fingerprint = str(fields.get("内容指纹") or "").strip()
    entry = RECOVERY_CATALOG.get(fingerprint)
    if not entry:
        return RecoveryClassification("unrecoverable", reason="no_evidence_strategy")
    if entry["kind"] == "local_source_image":
        path = downloads_root / entry["relative_path"]
        if _is_image(path):
            return RecoveryClassification(
                "recoverable",
                RecoveryCandidate(path, "local_source_image"),
            )
        return RecoveryClassification("unrecoverable", reason="source_image_missing")
    if entry["kind"] == "evidence_video_frame":
        cache_path = cache_root / fingerprint.removeprefix("sha256:") / "first_frame.jpg"
        if _is_image(cache_path):
            return RecoveryClassification(
                "recoverable",
                RecoveryCandidate(cache_path, "historical_evidence_video_frame"),
            )
        asset_id = str(fields.get("素材ID") or "").strip()
        evidence_path = evidence_root / asset_id / "evidence" / "evidence.json"
        if evidence_path.is_file():
            return RecoveryClassification(
                "requires_materialization",
                reason=str(evidence_path),
            )
        return RecoveryClassification("unrecoverable", reason="evidence_manifest_missing")
    return RecoveryClassification("unrecoverable", reason="unsupported_evidence_strategy")


def _attachment_descriptor(evidence_path: Path, field_name: str) -> dict[str, Any]:
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    source_fields = payload.get("source_fields") if isinstance(payload, dict) else {}
    values = source_fields.get(field_name) if isinstance(source_fields, dict) else []
    values = values if isinstance(values, list) else [values]
    for value in values:
        if isinstance(value, dict) and value.get("file_token"):
            return value
    raise RuntimeError("evidence attachment is unavailable")


def _download_evidence_media(service: Any, file_token: str, destination: Path) -> None:
    temporary = service._request(
        "GET",
        "/drive/v1/medias/batch_get_tmp_download_url",
        params={"file_tokens": file_token},
    )
    items = (temporary.get("data") or {}).get("tmp_download_urls") or []
    url = next(
        (
            str(item.get("tmp_download_url") or "")
            for item in items
            if isinstance(item, dict) and str(item.get("file_token") or "") == file_token
        ),
        "",
    )
    if not url.startswith("https://"):
        raise RuntimeError("evidence attachment download URL is unavailable")
    with requests.get(url, timeout=30, stream=True) as response:
        response.raise_for_status()
        size = 0
        with destination.open("wb") as handle:
            for chunk in response.iter_content(64 * 1024):
                size += len(chunk)
                if size > 50 * 1024 * 1024:
                    raise RuntimeError("evidence attachment exceeds 50 MiB")
                handle.write(chunk)
    if destination.stat().st_size <= 0:
        raise RuntimeError("evidence attachment download was empty")


def materialize_evidence_frame(
    fields: dict[str, Any],
    *,
    service: Any,
    evidence_root: Path,
    cache_root: Path,
) -> RecoveryCandidate:
    fingerprint = str(fields.get("内容指纹") or "").strip()
    asset_id = str(fields.get("素材ID") or "").strip()
    entry = RECOVERY_CATALOG[fingerprint]
    evidence_path = evidence_root / asset_id / "evidence" / "evidence.json"
    descriptor = _attachment_descriptor(evidence_path, entry["evidence_field"])
    cache_dir = cache_root / fingerprint.removeprefix("sha256:")
    cache_dir.mkdir(parents=True, exist_ok=True)
    image_path = cache_dir / "first_frame.jpg"
    if _is_image(image_path):
        return RecoveryCandidate(image_path, "historical_evidence_video_frame")
    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".media", delete=False) as handle:
        media_path = Path(handle.name)
    try:
        _download_evidence_media(service, str(descriptor["file_token"]), media_path)
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(media_path),
                "-frames:v",
                "1",
                str(image_path),
            ],
            check=True,
            timeout=60,
        )
    finally:
        media_path.unlink(missing_ok=True)
    if not _is_image(image_path):
        raise RuntimeError("ffmpeg did not produce a valid image")
    return RecoveryCandidate(image_path, "historical_evidence_video_frame")


def _upload_bitable_image(service: Any, app_token: str, path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    token = service._get_tenant_access_token()
    with path.open("rb") as handle:
        response = requests.post(
            f"{service.api_base_url}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": path.name,
                "parent_type": "bitable_file",
                "parent_node": app_token,
                "size": str(path.stat().st_size),
            },
            files={"file": (path.name, handle, mime_type)},
            timeout=60,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Feishu image upload returned invalid JSON") from exc
    if response.status_code >= 400 or payload.get("code") not in {None, 0}:
        raise RuntimeError("Feishu image upload failed")
    file_token = str((payload.get("data") or {}).get("file_token") or "")
    if not file_token:
        raise RuntimeError("Feishu image upload returned no file token")
    return file_token


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redacted_outcome(
    fields: dict[str, Any],
    status: str,
    *,
    candidate: RecoveryCandidate | None = None,
    reason: str = "",
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "asset_id": str(fields.get("素材ID") or ""),
        "content_fingerprint": str(fields.get("内容指纹") or ""),
        "status": status,
    }
    if candidate:
        outcome.update(
            {
                "provenance": candidate.provenance,
                "source_file": candidate.path.name,
                "source_sha256": _sha256(candidate.path),
            }
        )
    if reason:
        outcome["reason"] = reason
    return outcome


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--settings", default="/home/ubuntu/selfmedia-tools/openclaw-tag-router/openclaw_app/config/settings.yaml")
    parser.add_argument("--feishu-env", default="/home/ubuntu/.openclaw/openclaw-feishu-env.conf")
    parser.add_argument("--media-registry", default="/home/ubuntu/openclaw-feishu-reminder/media-bitable-registry.json")
    parser.add_argument("--downloads-root", type=Path, default=DEFAULT_DOWNLOADS_ROOT)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = dict(os.environ)
    env.update(_load_env_file(Path(args.feishu_env)))
    service = _build_feishu(Path(args.settings), env)
    base_token, bindings = _load_registry_table_bindings(Path(args.media_registry))
    binding = bindings["assets"]
    records = service.list_bitable_records(
        base_token,
        binding["table_id"],
        page_size=500,
        automatic_fields=True,
    )
    outcomes: list[dict[str, Any]] = []
    for record in records:
        record_id = str(record.get("record_id") or "")
        fields = record.get("fields") if isinstance(record, dict) else {}
        fields = dict(fields) if isinstance(fields, dict) else {}
        classification = classify_recovery(
            fields,
            downloads_root=args.downloads_root,
            evidence_root=args.evidence_root,
            cache_root=args.cache_root,
        )
        if classification.status == "skipped_existing_cover":
            outcomes.append(_redacted_outcome(fields, classification.status))
            continue
        if classification.status == "unrecoverable":
            outcomes.append(_redacted_outcome(fields, classification.status, reason=classification.reason))
            continue
        candidate = classification.candidate
        try:
            if classification.status == "requires_materialization":
                if args.execute:
                    candidate = materialize_evidence_frame(
                        fields,
                        service=service,
                        evidence_root=args.evidence_root,
                        cache_root=args.cache_root,
                    )
                else:
                    outcomes.append(_redacted_outcome(fields, "dry_run_recoverable", reason="historical_evidence_video"))
                    continue
            if candidate is None:
                raise RuntimeError("recovery candidate is missing")
            if not args.execute:
                outcomes.append(_redacted_outcome(fields, "dry_run_recoverable", candidate=candidate))
                continue
            current = service.read_bitable_record(base_token, binding["table_id"], record_id)
            current_fields = current.get("fields") if isinstance(current, dict) else {}
            if isinstance(current_fields, dict) and current_fields.get("封面附件"):
                outcomes.append(_redacted_outcome(fields, "skipped_existing_cover_after_readback"))
                continue
            file_token = _upload_bitable_image(service, base_token, candidate.path)
            service._request(
                "PUT",
                f"/bitable/v1/apps/{base_token}/tables/{binding['table_id']}/records/{record_id}",
                json_body={"fields": {"封面附件": [{"file_token": file_token}]}},
            )
            persisted = service.read_bitable_record(base_token, binding["table_id"], record_id)
            persisted_fields = persisted.get("fields") if isinstance(persisted, dict) else {}
            if not isinstance(persisted_fields, dict) or not persisted_fields.get("封面附件"):
                raise RuntimeError("cover write readback failed")
            outcomes.append(_redacted_outcome(fields, "written_verified", candidate=candidate))
        except Exception as exc:
            outcomes.append(
                _redacted_outcome(fields, "failed", candidate=candidate, reason=type(exc).__name__)
            )

    counts: dict[str, int] = {}
    for outcome in outcomes:
        status = str(outcome["status"])
        counts[status] = counts.get(status, 0) + 1
    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "execute" if args.execute else "dry_run",
        "base_table": binding["table_name"],
        "source_count": len(records),
        "counts": counts,
        "outcomes": outcomes,
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    blocked = any(item["status"] in {"unrecoverable", "failed"} for item in outcomes)
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
