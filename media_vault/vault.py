from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse


MEDIA_URI_SCHEME = "media"
DEFAULT_MEDIA_VAULT_ROOT = Path(
    os.getenv("OPENCLAW_MEDIA_VAULT_ROOT", "/home/ubuntu/selfmedia-tools/data/media_vault")
)
MEDIA_VAULT_VERSION = "media_vault_v2"
SAFE_URI_PART_RE = re.compile(r"[^A-Za-z0-9_.=-]+")
TENANT_DIRECTORIES = (
    "manifest",
    "source_assets",
    "deconstructions",
    "creation_runs",
    "renders",
    "published_posts",
    "business",
    "business_id_runs",
    "creator_profiles",
    "data_review_runs",
    "review_signals",
    "research_briefs",
    "commercial_briefs",
    "decision_briefs",
    "style_polish_runs",
    "verification_reports",
    "publishing_packs",
    "account_memory",
    "exports",
    "cache",
)
REQUIRED_ARTIFACT_MANIFEST_FIELDS = {
    "artifact_id",
    "tenant_id",
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


def require_tenant_id(value: Any) -> str:
    if not isinstance(value, str):
        raise MediaVaultError("tenant_id must be a canonical OpenClaw tenant UUID")
    tenant_id = value.strip()
    try:
        canonical = str(uuid.UUID(tenant_id))
    except ValueError as exc:
        raise MediaVaultError("tenant_id must be a canonical OpenClaw tenant UUID") from exc
    if canonical != tenant_id:
        raise MediaVaultError("tenant_id must be a canonical OpenClaw tenant UUID")
    return tenant_id


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
    """A hard tenant-scoped view of the Media Vault v2 filesystem."""

    def __init__(self, *, tenant_id: str, root: str | Path | None = None) -> None:
        self.tenant_id = require_tenant_id(tenant_id)
        self.vault_root = Path(
            root or os.getenv("OPENCLAW_MEDIA_VAULT_ROOT", str(DEFAULT_MEDIA_VAULT_ROOT))
        ).expanduser().resolve()
        self.tenant_root = (self.vault_root / "tenants" / self.tenant_id).resolve()
        self._assert_under(self.tenant_root, self.vault_root / "tenants")
        # Existing domain code treats ``vault.root`` as its writable root. In
        # v2 that name intentionally exposes only this tenant's partition.
        self.root = self.tenant_root

    @property
    def manifest_dir(self) -> Path:
        return self.tenant_root / "manifest"

    def ensure_root(self) -> None:
        for relative in TENANT_DIRECTORIES:
            (self.tenant_root / relative).mkdir(parents=True, exist_ok=True)

    def ensure_manifest(self) -> dict[str, Any]:
        self.ensure_root()
        path = self.manifest_dir / "media_vault_manifest.json"
        expected = {
            "version": MEDIA_VAULT_VERSION,
            "tenant_id": self.tenant_id,
            "uri_scheme": f"{MEDIA_URI_SCHEME}://",
            "root": str(self.tenant_root),
            "created_at": utc_now_iso(),
            "directories": {name: name for name in TENANT_DIRECTORIES},
        }
        if not path.exists():
            self._write_json_file(path, expected)
            return expected
        loaded = self._read_json_file(path)
        if loaded.get("version") != MEDIA_VAULT_VERSION:
            raise MediaVaultError("tenant vault manifest is not media_vault_v2")
        if str(loaded.get("tenant_id") or "") != self.tenant_id:
            raise MediaVaultError("tenant vault manifest owner mismatch")
        if Path(str(loaded.get("root") or "")).resolve() != self.tenant_root:
            raise MediaVaultError("tenant vault manifest root mismatch")
        return loaded

    def to_uri(self, path: str | Path) -> str:
        resolved = Path(path).expanduser().resolve()
        relative = self._relative_to_tenant(resolved)
        parts = ("tenants", self.tenant_id, *relative.parts)
        return f"{MEDIA_URI_SCHEME}://{'/'.join(quote(part, safe='') for part in parts)}"

    def resolve_uri(self, uri: str, *, require_exists: bool = False) -> Path:
        parsed = urlparse(str(uri or ""))
        if parsed.scheme != MEDIA_URI_SCHEME or parsed.params or parsed.query or parsed.fragment:
            raise MediaVaultUriError(f"unsupported media uri: {uri}")
        encoded = [part for part in (parsed.netloc, *parsed.path.split("/")) if part]
        decoded = [unquote(part) for part in encoded]
        if len(decoded) < 3 or decoded[:2] != ["tenants", self.tenant_id]:
            raise MediaVaultUriError("media uri does not belong to the authenticated tenant")
        if any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in decoded):
            raise MediaVaultUriError(f"unsafe media uri path: {uri}")
        resolved = (self.tenant_root / Path(*decoded[2:])).resolve()
        self._relative_to_tenant(resolved)
        if require_exists and not resolved.is_file():
            raise MediaVaultUriError("media artifact not found")
        return resolved

    def source_asset_dir(self, platform: str, asset_id: str) -> Path:
        return self._directory("source_assets", platform, asset_id)

    def deconstruction_dir(self, deconstruction_id: str) -> Path:
        return self._directory("deconstructions", deconstruction_id)

    def creation_run_dir(self, run_id: str) -> Path:
        return self._directory("creation_runs", run_id)

    def render_dir(self, render_id: str) -> Path:
        return self._directory("renders", render_id)

    def business_dir(self, opportunity_id: str) -> Path:
        return self._directory("business", opportunity_id)

    def account_memory_dir(self, account_id: str) -> Path:
        return self._directory("account_memory", account_id)

    def human_insight_candidate_dir(
        self,
        project_id: str,
        source_asset_id: str,
        deconstruction_id: str,
    ) -> Path:
        """Return the isolated review-only candidate collection for one source analysis."""
        project_key = "project-" + sha256_text(str(project_id or ""))[:24]
        return self._directory(
            "account_memory",
            project_key,
            "human_insight_candidates",
            source_asset_id,
            deconstruction_id,
        )

    def published_post_review_dir(self, post_id: str, review_node: str) -> Path:
        return self._directory("published_posts", post_id, "review", review_node)

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
        path = Path(directory) / self._safe_filename(filename, expected_suffix=".json")
        return self._write_artifact(
            path,
            (canonical_json(payload) + "\n").encode("utf-8"),
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
        return self._write_artifact(
            Path(directory) / self._safe_filename(filename),
            str(text or "").encode("utf-8"),
            owner_type=owner_type,
            owner_id=owner_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            content_type=content_type,
        )

    def read_artifact(self, uri: str) -> bytes:
        return self.resolve_uri(uri, require_exists=True).read_bytes()

    def read_json_artifact(self, uri: str) -> Any:
        path = self.resolve_uri(uri, require_exists=True)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MediaVaultError(f"invalid artifact json: {uri}") from exc

    def export_artifact(self, uri: str, destination: str | Path) -> dict[str, Any]:
        source = self.resolve_uri(uri, require_exists=True)
        target = Path(destination).expanduser().resolve()
        export_root = (self.tenant_root / "exports").resolve()
        self._assert_under(target, export_root)
        source_manifest = self._read_json_file(source.with_suffix(source.suffix + ".manifest.json"))
        failures = self.validate_artifact_manifest(source_manifest)
        if failures:
            raise MediaVaultError("source artifact manifest cannot prove tenant ownership")
        return self._write_artifact(
            target,
            source.read_bytes(),
            owner_type=str(source_manifest["owner_type"]),
            owner_id=str(source_manifest["owner_id"]),
            artifact_type=f"export:{source_manifest['artifact_type']}",
            artifact_id=make_timestamp_id("export"),
            content_type=str(source_manifest.get("content_type") or "application/octet-stream"),
        )

    def list_artifacts(self, *, artifact_type: str = "", limit: int = 100) -> list[dict[str, Any]]:
        expected_type = str(artifact_type or "").strip()
        manifests: list[dict[str, Any]] = []
        for path in sorted(self.tenant_root.rglob("*.manifest.json"), reverse=True):
            try:
                self._relative_to_tenant(path.resolve())
            except MediaVaultUriError:
                continue
            if path == self.manifest_dir / "media_vault_manifest.json":
                continue
            manifest = self._read_json_file(path)
            if self.validate_artifact_manifest(manifest):
                continue
            if expected_type and manifest.get("artifact_type") != expected_type:
                continue
            manifests.append(manifest)
            if len(manifests) >= max(1, min(int(limit), 1000)):
                break
        return manifests

    def search_artifacts(self, query: str, *, limit: int = 100) -> list[dict[str, Any]]:
        needle = str(query or "").strip().casefold()
        if not needle:
            raise MediaVaultError("search query is required")
        return [
            item
            for item in self.list_artifacts(limit=1000)
            if needle in canonical_json(item).casefold()
        ][: max(1, min(int(limit), 1000))]

    def delete_artifact(self, uri: str) -> dict[str, Any]:
        path = self.resolve_uri(uri, require_exists=True)
        sidecar = path.with_suffix(path.suffix + ".manifest.json")
        manifest = self._read_json_file(sidecar)
        failures = self.validate_artifact_manifest(manifest)
        if failures or manifest.get("uri") != uri:
            raise MediaVaultError("artifact manifest cannot prove tenant ownership")
        content_hash = f"sha256:{sha256_bytes(path.read_bytes())}"
        if manifest.get("content_hash") != content_hash:
            raise MediaVaultError("artifact content hash mismatch")
        path.unlink()
        sidecar.unlink()
        return {"deleted": True, "tenant_id": self.tenant_id, "uri": uri, "content_hash": content_hash}

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
        result = {"manifest": self.write_json_artifact(base, "manifest.json", manifest, owner_type="SourceAsset", owner_id=asset_id, artifact_type="source_asset_manifest")}
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
        artifacts = {"request": self.write_json_artifact(base, "request.json", request, owner_type="CreationRun", owner_id=run_id, artifact_type="request")}
        payloads = {
            "input": input_payload,
            "retrieval_candidates": retrieval_candidates,
            "decision_trace": decision_trace,
            "material_usage": material_usage,
            "draft_output": draft_output,
            "validation_report": validation_report,
            "writeback_report": writeback_report,
        }
        for name, payload in payloads.items():
            if payload is not None:
                artifacts[name] = self.write_json_artifact(base, f"{name}.json", payload, owner_type="CreationRun", owner_id=run_id, artifact_type=name)
        return artifacts

    def write_render_artifacts(self, render_id: str, *, render_spec: dict[str, Any], html: str | None = None, feishu_doc_blocks: list[dict[str, Any]] | None = None, storyboard_preview: str | None = None) -> dict[str, dict[str, Any]]:
        base = self.render_dir(render_id)
        artifacts = {"render_spec": self.write_json_artifact(base, "render_spec.json", render_spec, owner_type="RenderArtifact", owner_id=render_id, artifact_type="render_spec")}
        if html is not None:
            artifacts["html"] = self.write_text_artifact(base, "hyperframe_output.html", html, owner_type="RenderArtifact", owner_id=render_id, artifact_type="html", content_type="text/html")
        if feishu_doc_blocks is not None:
            artifacts["feishu_doc_blocks"] = self.write_json_artifact(base, "feishu_doc_blocks.json", feishu_doc_blocks, owner_type="RenderArtifact", owner_id=render_id, artifact_type="feishu_doc_blocks")
        if storyboard_preview is not None:
            artifacts["storyboard_preview"] = self.write_text_artifact(base, "storyboard_preview.html", storyboard_preview, owner_type="RenderArtifact", owner_id=render_id, artifact_type="storyboard_preview", content_type="text/html")
        return artifacts

    def write_quote_snapshot(self, opportunity_id: str, quote_snapshot: dict[str, Any]) -> dict[str, Any]:
        return self.write_json_artifact(self.business_dir(opportunity_id), "quote_snapshot.json", quote_snapshot, owner_type="BusinessOpportunity", owner_id=opportunity_id, artifact_type="quote_snapshot")

    def write_post_review(self, post_id: str, review_node: str, *, metrics: dict[str, Any], review_markdown: str) -> dict[str, dict[str, Any]]:
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
        if str(manifest.get("tenant_id") or "") != self.tenant_id:
            failures.append("artifact tenant_id does not match tenant context")
        uri = str(manifest.get("uri") or "")
        if uri:
            try:
                self.resolve_uri(uri)
            except MediaVaultUriError as exc:
                failures.append(str(exc))
        content_hash = str(manifest.get("content_hash") or "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash):
            failures.append("content_hash must use sha256:<64 lowercase hex>")
        if str(manifest.get("owner_type") or "") in {"", "EvidenceArtifact", "RawJSON", "AgentRunLog"}:
            failures.append("artifact owner_type must be a canonical business owner or RenderArtifact")
        if not str(manifest.get("owner_id") or "").strip():
            failures.append("artifact owner_id is required")
        return failures

    def _write_artifact(self, path: Path, data: bytes, *, owner_type: str, owner_id: str, artifact_type: str, artifact_id: str | None, content_type: str) -> dict[str, Any]:
        self.ensure_manifest()
        resolved = path.expanduser().resolve()
        self._relative_to_tenant(resolved)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        uri = self.to_uri(resolved)
        manifest = {
            "artifact_id": artifact_id or make_timestamp_id("artifact"),
            "tenant_id": self.tenant_id,
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
        resolved.write_bytes(data)
        self._write_json_file(resolved.with_suffix(resolved.suffix + ".manifest.json"), manifest)
        return manifest

    def _directory(self, namespace: str, *parts: str) -> Path:
        if namespace not in TENANT_DIRECTORIES:
            raise MediaVaultError(f"unknown tenant vault namespace: {namespace}")
        normalized = [normalize_uri_part(part) for part in parts]
        path = (self.tenant_root / namespace / Path(*normalized)).resolve()
        self._relative_to_tenant(path)
        return path

    def _relative_to_tenant(self, path: Path) -> Path:
        try:
            return path.relative_to(self.tenant_root)
        except ValueError as exc:
            raise MediaVaultUriError("path is outside authenticated tenant vault") from exc

    @staticmethod
    def _assert_under(path: Path, root: Path) -> None:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise MediaVaultUriError("path escapes media vault root") from exc

    @staticmethod
    def _safe_filename(filename: str, *, expected_suffix: str | None = None) -> str:
        raw = str(filename or "").strip()
        if not raw or "/" in raw or "\\" in raw or raw in {".", ".."}:
            raise MediaVaultError(f"unsafe filename: {filename}")
        if expected_suffix and not raw.endswith(expected_suffix):
            raise MediaVaultError(f"filename must end with {expected_suffix}: {filename}")
        return raw

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MediaVaultError(f"invalid json file: {path}") from exc
        if not isinstance(payload, dict):
            raise MediaVaultError(f"json file must contain object: {path}")
        return payload

    @staticmethod
    def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
