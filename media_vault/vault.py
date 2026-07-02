from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse


MEDIA_URI_SCHEME = "media"
DEFAULT_MEDIA_VAULT_ROOT = Path(os.getenv("OPENCLAW_MEDIA_VAULT_ROOT", "/home/ubuntu/selfmedia-tools/data/media_vault"))
MEDIA_VAULT_VERSION = "media_vault_v1"
SAFE_URI_PART_RE = re.compile(r"[^A-Za-z0-9_.=-]+")
REQUIRED_ARTIFACT_MANIFEST_FIELDS = {
    "artifact_id",
    "owner_type",
    "owner_id",
    "artifact_type",
    "uri",
    "content_hash",
    "created_at",
}


class MediaVaultError(RuntimeError):
    pass


class MediaVaultUriError(MediaVaultError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_timestamp_id(prefix: str, *, now: datetime | None = None, token_bytes: int = 3) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    return f"{normalize_uri_part(prefix)}_{timestamp}_{secrets.token_hex(token_bytes)}"


def normalize_uri_part(value: Any, *, default: str = "item") -> str:
    text = str(value or "").strip()
    text = text.replace("://", "_").replace("/", "_").replace("\\", "_")
    text = SAFE_URI_PART_RE.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return text or default


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class MediaVault:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.getenv("OPENCLAW_MEDIA_VAULT_ROOT", str(DEFAULT_MEDIA_VAULT_ROOT))).expanduser().resolve()

    @property
    def manifest_dir(self) -> Path:
        return self.root / "manifest"

    def ensure_root(self) -> None:
        for relative in (
            "manifest",
            "source_assets",
            "deconstructions",
            "creation_runs",
            "renders",
            "published_posts",
            "business",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def ensure_manifest(self) -> dict[str, Any]:
        self.ensure_root()
        path = self.manifest_dir / "media_vault_manifest.json"
        manifest = {
            "version": MEDIA_VAULT_VERSION,
            "uri_scheme": f"{MEDIA_URI_SCHEME}://",
            "root": str(self.root),
            "created_at": utc_now_iso(),
            "directories": {
                "manifest": "manifest",
                "source_assets": "source_assets",
                "deconstructions": "deconstructions",
                "creation_runs": "creation_runs",
                "renders": "renders",
                "published_posts": "published_posts",
                "business": "business",
            },
        }
        if path.exists():
            loaded = self._read_json_file(path)
            loaded.setdefault("root", str(self.root))
            loaded.setdefault("uri_scheme", f"{MEDIA_URI_SCHEME}://")
            loaded.setdefault("version", MEDIA_VAULT_VERSION)
            loaded.setdefault("directories", manifest["directories"])
            return loaded
        self._write_json_file(path, manifest)
        return manifest

    def to_uri(self, path: str | Path) -> str:
        resolved = Path(path).expanduser().resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise MediaVaultUriError(f"path is outside media_vault root: {resolved}") from exc
        parts = [quote(part) for part in relative.parts]
        return f"{MEDIA_URI_SCHEME}://{'/'.join(parts)}"

    def resolve_uri(self, uri: str) -> Path:
        parsed = urlparse(str(uri or ""))
        if parsed.scheme != MEDIA_URI_SCHEME:
            raise MediaVaultUriError(f"unsupported media uri scheme: {uri}")
        parts = [part for part in (parsed.netloc, *parsed.path.split("/")) if part]
        if not parts:
            raise MediaVaultUriError(f"empty media uri: {uri}")
        decoded = [unquote(part) for part in parts]
        if any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in decoded):
            raise MediaVaultUriError(f"unsafe media uri path: {uri}")
        resolved = (self.root / Path(*decoded)).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise MediaVaultUriError(f"media uri escapes root: {uri}") from exc
        return resolved

    def source_asset_dir(self, platform: str, asset_id: str) -> Path:
        return self.root / "source_assets" / normalize_uri_part(platform, default="unknown_platform") / normalize_uri_part(asset_id, default="asset")

    def deconstruction_dir(self, deconstruction_id: str) -> Path:
        return self.root / "deconstructions" / normalize_uri_part(deconstruction_id, default="decon")

    def creation_run_dir(self, run_id: str) -> Path:
        return self.root / "creation_runs" / normalize_uri_part(run_id, default="run")

    def render_dir(self, render_id: str) -> Path:
        return self.root / "renders" / normalize_uri_part(render_id, default="render")

    def business_dir(self, opportunity_id: str) -> Path:
        return self.root / "business" / normalize_uri_part(opportunity_id, default="opportunity")

    def published_post_review_dir(self, post_id: str, review_node: str) -> Path:
        return self.root / "published_posts" / normalize_uri_part(post_id, default="post") / "review" / normalize_uri_part(review_node, default="node")

    def write_json_artifact(
        self,
        directory: str | Path,
        filename: str,
        payload: Any,
        *,
        owner_type: str,
        owner_id: str,
        artifact_type: str,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        directory_path = Path(directory)
        path = directory_path / self._safe_filename(filename, expected_suffix=".json")
        text = canonical_json(payload) + "\n"
        return self._write_artifact(
            path,
            text.encode("utf-8"),
            owner_type=owner_type,
            owner_id=owner_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            content_type="application/json",
        )

    def write_text_artifact(
        self,
        directory: str | Path,
        filename: str,
        text: str,
        *,
        owner_type: str,
        owner_id: str,
        artifact_type: str,
        artifact_id: str | None = None,
        content_type: str = "text/plain",
    ) -> dict[str, Any]:
        path = Path(directory) / self._safe_filename(filename)
        return self._write_artifact(
            path,
            str(text or "").encode("utf-8"),
            owner_type=owner_type,
            owner_id=owner_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            content_type=content_type,
        )

    def write_source_asset_bundle(
        self,
        *,
        platform: str,
        asset_id: str,
        manifest: dict[str, Any],
        original_text: str | None = None,
        extracted_text: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = self.source_asset_dir(platform, asset_id)
        result = {
            "manifest": self.write_json_artifact(base, "manifest.json", manifest, owner_type="SourceAsset", owner_id=asset_id, artifact_type="source_asset_manifest"),
        }
        if original_text is not None:
            result["original_text"] = self.write_text_artifact(base / "original", "source_text.md", original_text, owner_type="SourceAsset", owner_id=asset_id, artifact_type="source_original_text", content_type="text/markdown")
        if extracted_text is not None:
            result["extracted_text"] = self.write_text_artifact(base / "extracted", "normalized_text.md", extracted_text, owner_type="SourceAsset", owner_id=asset_id, artifact_type="source_extracted_text", content_type="text/markdown")
        if evidence is not None:
            result["evidence"] = self.write_json_artifact(base / "evidence", "evidence.json", evidence, owner_type="SourceAsset", owner_id=asset_id, artifact_type="source_evidence")
        return result

    def write_creation_run_artifacts(
        self,
        run_id: str,
        *,
        request: dict[str, Any],
        input_payload: dict[str, Any] | None = None,
        retrieval_candidates: dict[str, Any] | None = None,
        decision_trace: list[dict[str, Any]] | dict[str, Any] | None = None,
        material_usage: list[dict[str, Any]] | dict[str, Any] | None = None,
        draft_output: dict[str, Any] | None = None,
        validation_report: dict[str, Any] | None = None,
        writeback_report: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        base = self.creation_run_dir(run_id)
        artifacts: dict[str, dict[str, Any]] = {
            "request": self.write_json_artifact(base, "request.json", request, owner_type="CreationRun", owner_id=run_id, artifact_type="request"),
        }
        optional_payloads = {
            "input": input_payload,
            "retrieval_candidates": retrieval_candidates,
            "decision_trace": decision_trace,
            "material_usage": material_usage,
            "draft_output": draft_output,
            "validation_report": validation_report,
            "writeback_report": writeback_report,
        }
        for name, payload in optional_payloads.items():
            if payload is not None:
                artifacts[name] = self.write_json_artifact(base, f"{name}.json", payload, owner_type="CreationRun", owner_id=run_id, artifact_type=name)
        return artifacts

    def write_render_artifacts(
        self,
        render_id: str,
        *,
        render_spec: dict[str, Any],
        html: str | None = None,
        feishu_doc_blocks: list[dict[str, Any]] | None = None,
        storyboard_preview: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        base = self.render_dir(render_id)
        artifacts: dict[str, dict[str, Any]] = {
            "render_spec": self.write_json_artifact(base, "render_spec.json", render_spec, owner_type="RenderArtifact", owner_id=render_id, artifact_type="render_spec"),
        }
        if html is not None:
            artifacts["html"] = self.write_text_artifact(base, "hyperframe_output.html", html, owner_type="RenderArtifact", owner_id=render_id, artifact_type="html", content_type="text/html")
        if feishu_doc_blocks is not None:
            artifacts["feishu_doc_blocks"] = self.write_json_artifact(base, "feishu_doc_blocks.json", feishu_doc_blocks, owner_type="RenderArtifact", owner_id=render_id, artifact_type="feishu_doc_blocks")
        if storyboard_preview is not None:
            artifacts["storyboard_preview"] = self.write_text_artifact(base, "storyboard_preview.html", storyboard_preview, owner_type="RenderArtifact", owner_id=render_id, artifact_type="storyboard_preview", content_type="text/html")
        return artifacts

    def write_quote_snapshot(
        self,
        opportunity_id: str,
        quote_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return self.write_json_artifact(
            self.business_dir(opportunity_id),
            "quote_snapshot.json",
            quote_snapshot,
            owner_type="BusinessOpportunity",
            owner_id=opportunity_id,
            artifact_type="quote_snapshot",
        )

    def write_post_review(
        self,
        post_id: str,
        review_node: str,
        *,
        metrics: dict[str, Any],
        review_markdown: str,
    ) -> dict[str, dict[str, Any]]:
        base = self.published_post_review_dir(post_id, review_node)
        return {
            "metrics": self.write_json_artifact(base, "metrics.json", metrics, owner_type="PublishedPost", owner_id=post_id, artifact_type=f"review_metrics_{review_node}"),
            "review": self.write_text_artifact(base, "review.md", review_markdown, owner_type="PublishedPost", owner_id=post_id, artifact_type=f"review_markdown_{review_node}", content_type="text/markdown"),
        }

    def validate_artifact_manifest(self, manifest: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        missing = sorted(REQUIRED_ARTIFACT_MANIFEST_FIELDS - set(manifest))
        if missing:
            failures.append(f"missing required fields: {missing}")
        uri = str(manifest.get("uri") or "")
        if uri:
            try:
                self.resolve_uri(uri)
            except MediaVaultUriError as exc:
                failures.append(str(exc))
        if not str(manifest.get("content_hash") or "").startswith("sha256:"):
            failures.append("content_hash must use sha256:<hex>")
        if str(manifest.get("owner_type") or "") in {"", "EvidenceArtifact", "RawJSON", "AgentRunLog"}:
            failures.append("artifact owner_type must be a business owner or RenderArtifact, not a standalone Feishu entity")
        return failures

    def _write_artifact(
        self,
        path: Path,
        data: bytes,
        *,
        owner_type: str,
        owner_id: str,
        artifact_type: str,
        artifact_id: str | None,
        content_type: str,
    ) -> dict[str, Any]:
        self.ensure_manifest()
        resolved = path.expanduser().resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise MediaVaultUriError(f"artifact path escapes media_vault root: {resolved}") from exc
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(data)
        uri = self.to_uri(resolved)
        manifest = {
            "artifact_id": artifact_id or make_timestamp_id("artifact"),
            "owner_type": str(owner_type or "").strip(),
            "owner_id": str(owner_id or "").strip(),
            "artifact_type": str(artifact_type or "").strip(),
            "uri": uri,
            "content_type": content_type,
            "content_hash": f"sha256:{sha256_bytes(data)}",
            "created_at": utc_now_iso(),
            "size_bytes": len(data),
        }
        failures = self.validate_artifact_manifest(manifest)
        if failures:
            raise MediaVaultError("; ".join(failures))
        self._write_json_file(resolved.with_suffix(resolved.suffix + ".manifest.json"), manifest)
        return manifest

    @staticmethod
    def _safe_filename(filename: str, *, expected_suffix: str | None = None) -> str:
        raw = str(filename or "").strip()
        if not raw:
            raise MediaVaultError("filename is required")
        if "/" in raw or "\\" in raw or raw in {".", ".."}:
            raise MediaVaultError(f"unsafe filename: {filename}")
        if expected_suffix and not raw.endswith(expected_suffix):
            raise MediaVaultError(f"filename must end with {expected_suffix}: {filename}")
        return raw

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MediaVaultError(f"invalid json file: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise MediaVaultError(f"json file must contain object: {path}")
        return payload

    @staticmethod
    def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
