#!/usr/bin/env python3
"""Materialize the five fixed D2 bodies in an isolated personal tenant."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID


SOURCE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOURCE_ROOT))

from openclaw_app.account import AccountDatabase, AccountDatabaseSettings
from openclaw_app.adapters.http_api import load_auth_environment
from openclaw_app.services.media_business.foundation import body_checksum, validate_body


FIXTURE_ROOT = SOURCE_ROOT / "tests/fixtures/d2-five-ready"
MANIFEST_PATH = FIXTURE_ROOT / "ready-revision-manifest.json"
FIXTURE_CHECKER = FIXTURE_ROOT / "generate_d2_fixtures.py"
EXPECTED_KINDS = frozenset(
    {
        "research_snapshot",
        "asset_digest",
        "decision_brief",
        "creation_document",
        "review_report",
    }
)
PUBLIC_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
PROJECT_ID = "project_d2_personal_20260805"
PROJECT_TITLE = "D2 C 端五类文档验收"
ACTOR_ID = "d2-fixture-materializer"
GENERATION_SOURCE = "d2_fixed_ready_fixtures"


class MaterializationError(RuntimeError):
    """The source package or target state differs from the fixed D2 plan."""


@dataclass(frozen=True)
class ResourcePlan:
    public_id: str
    content_type: str
    file_name: str
    checksum: str
    source_path: Path
    object_ref: str


@dataclass(frozen=True)
class RevisionPlan:
    artifact_kind: str
    public_artifact_id: str
    revision: int
    body: dict[str, Any]
    checksum: str
    resources: tuple[ResourcePlan, ResourcePlan]


@dataclass(frozen=True)
class FixturePlan:
    manifest_checksum: str
    revisions: tuple[RevisionPlan, ...]

    @property
    def resources(self) -> tuple[ResourcePlan, ...]:
        return tuple(resource for revision in self.revisions for resource in revision.resources)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise MaterializationError(f"cannot read file: {path}") from exc


def _fixture_file(relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise MaterializationError("fixture path is missing")
    path = (FIXTURE_ROOT / relative).resolve()
    try:
        path.relative_to(FIXTURE_ROOT.resolve())
    except ValueError as exc:
        raise MaterializationError("fixture path escapes the source package") from exc
    if not path.is_file():
        raise MaterializationError(f"fixture file is missing: {relative}")
    return path


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"invalid JSON: {path}") from exc


def _ordered_ids(body: Mapping[str, Any]) -> list[str]:
    identifiers: list[str] = []

    def visit(block: Mapping[str, Any]) -> None:
        identifiers.append(str(block["id"]))
        if block["type"] in {"bullet_list", "ordered_list"}:
            for item in block["items"]:
                identifiers.append(str(item["id"]))
                for child in item["children"]:
                    visit(child)
        if block["type"] == "table":
            for row in block["rows"]:
                identifiers.append(str(row["id"]))
                identifiers.extend(str(cell["id"]) for cell in row["cells"])

    for block in body["blocks"]:
        visit(block)
    return identifiers


def _object_ref(tenant_id: str, checksum: str, source_name: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", source_name)
    return f"d2/{tenant_id}/{checksum[:2]}/{checksum}-{safe_name}"


def _tenant_id(value: str) -> str:
    try:
        parsed = str(UUID(value))
    except (AttributeError, ValueError) as exc:
        raise MaterializationError("tenant id must be a UUID") from exc
    if parsed != value:
        raise MaterializationError("tenant id must use canonical lowercase UUID form")
    return parsed


def _resource(
    tenant_id: str,
    kind: str,
    block: Mapping[str, Any],
    declared: Mapping[str, Any],
) -> ResourcePlan:
    attrs = block.get("attrs")
    if not isinstance(attrs, Mapping):
        raise MaterializationError(f"{kind} resource attributes are invalid")
    public_id = attrs.get("publicResourceId")
    checksum = declared.get("sha256")
    content_type = declared.get("contentType")
    if not isinstance(public_id, str) or not PUBLIC_ID.fullmatch(public_id):
        raise MaterializationError(f"{kind} resource id is invalid")
    if not isinstance(checksum, str) or attrs.get("contentChecksum") != checksum:
        raise MaterializationError(f"{kind} resource checksum binding drift")
    source = _fixture_file(declared.get("file"))
    if _sha256(source) != checksum:
        raise MaterializationError(f"{kind} resource bytes drift")
    if block["type"] == "image":
        if content_type != "image/png" or attrs.get("width") != declared.get("width") or attrs.get("height") != declared.get("height"):
            raise MaterializationError(f"{kind} image metadata drift")
        file_name = source.name
    elif block["type"] == "attachment":
        if content_type != attrs.get("contentType"):
            raise MaterializationError(f"{kind} attachment content type drift")
        file_name = attrs.get("fileName")
    else:
        raise MaterializationError(f"{kind} resource block type is invalid")
    if not isinstance(file_name, str) or not file_name.strip() or any(value in file_name for value in ("/", "\\", "\r", "\n")):
        raise MaterializationError(f"{kind} resource file name is unsafe")
    return ResourcePlan(
        public_id=public_id,
        content_type=str(content_type),
        file_name=file_name,
        checksum=checksum,
        source_path=source,
        object_ref=_object_ref(tenant_id, checksum, source.name),
    )


def load_fixture_plan(tenant_id: str) -> FixturePlan:
    tenant_id = _tenant_id(tenant_id)
    try:
        subprocess.run(
            [sys.executable, str(FIXTURE_CHECKER), "--check"],
            cwd=SOURCE_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "fixture checker failed").strip()
        raise MaterializationError(detail) from exc
    manifest = _json(MANIFEST_PATH)
    if not isinstance(manifest, Mapping):
        raise MaterializationError("fixture manifest must be an object")
    if manifest.get("schemaVersion") != "d2.fixed-ready-revisions.v1" or manifest.get("status") != "READY_TO_MATERIALIZE":
        raise MaterializationError("fixture manifest is not ready to materialize")
    entries = manifest.get("revisions")
    if not isinstance(entries, list) or len(entries) != 5:
        raise MaterializationError("fixture manifest must declare five revisions")

    plans: list[RevisionPlan] = []
    seen_kinds: set[str] = set()
    seen_artifacts: set[str] = set()
    seen_resources: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise MaterializationError("fixture revision declaration is invalid")
        kind = entry.get("artifactKind")
        artifact_id = entry.get("publicArtifactId")
        if kind not in EXPECTED_KINDS or kind in seen_kinds:
            raise MaterializationError("fixture artifact kinds are incomplete or duplicated")
        if not isinstance(artifact_id, str) or not PUBLIC_ID.fullmatch(artifact_id) or artifact_id in seen_artifacts:
            raise MaterializationError(f"{kind} artifact id is invalid or duplicated")
        if entry.get("revisionNumber") != 1 or entry.get("requiredState") != "ready" or entry.get("immutableBinding") is not True:
            raise MaterializationError(f"{kind} ready revision binding drift")
        if entry.get("canonicalBodySchema") != "media.document.body.v1" or entry.get("bodyAuthorityBySurface") != {"react": "internal", "feishu": "lark"}:
            raise MaterializationError(f"{kind} body authority drift")
        body = validate_body(_json(_fixture_file(entry.get("bodyFile"))))
        checksum = body_checksum(body)
        if checksum != entry.get("bodySha256") or _ordered_ids(body) != entry.get("orderedCanonicalIds"):
            raise MaterializationError(f"{kind} canonical body drift")
        binding = entry.get("resourceBinding")
        if not isinstance(binding, Mapping) or binding.get("required") is not True:
            raise MaterializationError(f"{kind} resource binding is missing")
        image_blocks = [block for block in body["blocks"] if block["type"] == "image"]
        attachment_blocks = [block for block in body["blocks"] if block["type"] == "attachment"]
        if len(image_blocks) != 1 or len(attachment_blocks) != 1:
            raise MaterializationError(f"{kind} must bind one image and one attachment")
        image_declared = binding.get("image")
        attachment_declared = binding.get("attachment")
        if not isinstance(image_declared, Mapping) or not isinstance(attachment_declared, Mapping):
            raise MaterializationError(f"{kind} resource declaration is invalid")
        resources = (
            _resource(tenant_id, str(kind), image_blocks[0], image_declared),
            _resource(tenant_id, str(kind), attachment_blocks[0], attachment_declared),
        )
        if any(resource.public_id in seen_resources for resource in resources):
            raise MaterializationError(f"{kind} resource id is duplicated")
        seen_resources.update(resource.public_id for resource in resources)
        plans.append(RevisionPlan(str(kind), artifact_id, 1, body, checksum, resources))
        seen_kinds.add(str(kind))
        seen_artifacts.add(artifact_id)
    if seen_kinds != EXPECTED_KINDS:
        raise MaterializationError("fixture artifact kind coverage drift")
    return FixturePlan(_sha256(MANIFEST_PATH), tuple(plans))


def _exact(connection: Any, query: str, params: tuple[Any, ...], expected: tuple[Any, ...], label: str) -> None:
    row = connection.execute(query, params).fetchone()
    if row is None or tuple(row) != expected:
        raise MaterializationError(f"existing {label} differs from the D2 plan")


def _write_object(root: Path, resource: ResourcePlan) -> None:
    target = (root / resource.object_ref).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise MaterializationError("resource object path escapes resource root") from exc
    if target.exists():
        if not target.is_file() or _sha256(target) != resource.checksum:
            raise MaterializationError(f"resource object drift: {resource.object_ref}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".d2-resource-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(resource.source_path.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        if _sha256(temporary) != resource.checksum:
            raise MaterializationError("resource bytes changed during staging")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def materialize(connection: Any, tenant_id: str, resource_root: Path, plan: FixturePlan) -> dict[str, Any]:
    if not resource_root.expanduser().is_absolute():
        raise MaterializationError("resource root must be absolute")
    root = resource_root.expanduser().resolve()
    tenant = connection.execute(
        "SELECT tenant_type,workspace_mode,body_authority,status,organization_name "
        "FROM openclaw_account.tenants WHERE id=%s FOR UPDATE",
        (tenant_id,),
    ).fetchone()
    if tenant is None:
        raise MaterializationError("target tenant does not exist")
    if tuple(tenant) != ("personal", "personal_web", "internal", "active", None):
        raise MaterializationError("D2 fixtures only accept an active personal C tenant")

    canonical_data = {
        "source": GENERATION_SOURCE,
        "fixtureManifestSha256": plan.manifest_checksum,
        "artifactCount": len(plan.revisions),
    }
    connection.execute(
        "INSERT INTO media_product.content_projects "
        "(tenant_id,public_id,title,stage,revision,canonical_data) "
        "VALUES (%s,%s,%s,'review',1,%s::jsonb) ON CONFLICT (tenant_id,public_id) DO NOTHING",
        (tenant_id, PROJECT_ID, PROJECT_TITLE, json.dumps(canonical_data, ensure_ascii=False, sort_keys=True)),
    )
    _exact(
        connection,
        "SELECT title,stage,revision,canonical_data FROM media_product.content_projects WHERE tenant_id=%s AND public_id=%s",
        (tenant_id, PROJECT_ID),
        (PROJECT_TITLE, "review", 1, canonical_data),
        "D2 project",
    )

    for resource in plan.resources:
        _write_object(root, resource)
        connection.execute(
            "INSERT INTO media_document.resources "
            "(tenant_id,public_resource_id,content_type,file_name,content_checksum,object_ref,status) "
            "VALUES (%s,%s,%s,%s,%s,%s,'active') ON CONFLICT (tenant_id,public_resource_id) DO NOTHING",
            (tenant_id, resource.public_id, resource.content_type, resource.file_name, resource.checksum, resource.object_ref),
        )
        _exact(
            connection,
            "SELECT content_type,file_name,content_checksum,object_ref,status,archived_at "
            "FROM media_document.resources WHERE tenant_id=%s AND public_resource_id=%s",
            (tenant_id, resource.public_id),
            (resource.content_type, resource.file_name, resource.checksum, resource.object_ref, "active", None),
            f"resource {resource.public_id}",
        )

    for revision in plan.revisions:
        connection.execute(
            "INSERT INTO media_product.document_artifacts "
            "(tenant_id,public_id,public_project_id,artifact_kind,workspace_mode,body_authority,current_revision) "
            "VALUES (%s,%s,%s,%s,'personal_web','internal',1) "
            "ON CONFLICT (tenant_id,public_id) DO NOTHING",
            (tenant_id, revision.public_artifact_id, PROJECT_ID, revision.artifact_kind),
        )
        _exact(
            connection,
            "SELECT public_project_id,artifact_kind,workspace_mode,body_authority,current_revision "
            "FROM media_product.document_artifacts WHERE tenant_id=%s AND public_id=%s",
            (tenant_id, revision.public_artifact_id),
            (PROJECT_ID, revision.artifact_kind, "personal_web", "internal", 1),
            f"artifact {revision.public_artifact_id}",
        )
        connection.execute(
            "INSERT INTO media_product.document_revisions "
            "(tenant_id,public_artifact_id,revision,state,base_revision,body_checksum,actor_public_id,generation_source) "
            "VALUES (%s,%s,1,'ready',NULL,%s,%s,%s) "
            "ON CONFLICT (tenant_id,public_artifact_id,revision) DO NOTHING",
            (tenant_id, revision.public_artifact_id, revision.checksum, ACTOR_ID, GENERATION_SOURCE),
        )
        _exact(
            connection,
            "SELECT state,base_revision,body_checksum,actor_public_id,generation_source "
            "FROM media_product.document_revisions WHERE tenant_id=%s AND public_artifact_id=%s AND revision=1",
            (tenant_id, revision.public_artifact_id),
            ("ready", None, revision.checksum, ACTOR_ID, GENERATION_SOURCE),
            f"revision {revision.public_artifact_id}:r1",
        )
        connection.execute(
            "INSERT INTO media_document.revision_bodies "
            "(tenant_id,public_artifact_id,revision,schema_version,body_json,body_checksum) "
            "VALUES (%s,%s,1,'media.document.body.v1',%s::jsonb,%s) "
            "ON CONFLICT (tenant_id,public_artifact_id,revision) DO NOTHING",
            (
                tenant_id,
                revision.public_artifact_id,
                json.dumps(revision.body, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                revision.checksum,
            ),
        )
        _exact(
            connection,
            "SELECT schema_version,body_json,body_checksum FROM media_document.revision_bodies "
            "WHERE tenant_id=%s AND public_artifact_id=%s AND revision=1",
            (tenant_id, revision.public_artifact_id),
            ("media.document.body.v1", revision.body, revision.checksum),
            f"body {revision.public_artifact_id}:r1",
        )
    return {
        "tenantId": tenant_id,
        "projectId": PROJECT_ID,
        "artifactCount": len(plan.revisions),
        "resourceBindingCount": len(plan.resources),
        "uniqueObjectCount": len({resource.object_ref for resource in plan.resources}),
        "manifestSha256": plan.manifest_checksum,
    }


def dry_run(tenant_id: str, resource_root: Path, plan: FixturePlan) -> dict[str, Any]:
    if not resource_root.expanduser().is_absolute():
        raise MaterializationError("resource root must be absolute")
    root = resource_root.expanduser().resolve()
    existing = 0
    for resource in plan.resources:
        target = (root / resource.object_ref).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise MaterializationError("resource object path escapes resource root") from exc
        if target.exists():
            if not target.is_file() or _sha256(target) != resource.checksum:
                raise MaterializationError(f"resource object drift: {resource.object_ref}")
            existing += 1
    return {
        "mode": "dry-run",
        "tenantId": tenant_id,
        "resourceRoot": str(root),
        "artifactCount": len(plan.revisions),
        "resourceBindingCount": len(plan.resources),
        "uniqueObjectCount": len({resource.object_ref for resource in plan.resources}),
        "existingResourceBindings": existing,
        "manifestSha256": plan.manifest_checksum,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--resource-root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--auth-env", type=Path, help="required with --execute")
    args = parser.parse_args()

    tenant_id = _tenant_id(args.tenant_id)
    plan = load_fixture_plan(tenant_id)
    if args.dry_run:
        result = dry_run(tenant_id, args.resource_root, plan)
    else:
        if args.auth_env is None:
            raise MaterializationError("--auth-env is required with --execute")
        settings = AccountDatabaseSettings.from_environment(load_auth_environment(args.auth_env))
        database = AccountDatabase(settings)
        with database.connect() as connection:
            result = materialize(connection, tenant_id, args.resource_root, plan)
        result["mode"] = "execute"
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
