"""Concrete Stage-2 production composition for the isolated deployment.

This module is intentionally separate from the normal 8787 application.  It
reads authority facts from the canonical PostgreSQL account/product schemas,
keeps personal write receipts in the Stage-2 SQLite database, and uses the
existing FeishuService for an actual organization document write plus readback.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import base64
import json
import os
import re
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import yaml

from .feishu_service import FeishuService
from .stage2_context import (
    CapabilityEffect,
    CapabilityEffectRegistry,
    DOCUMENT_WRITER_FIXTURE_ID,
    ORGANIZATION_AUTHORITY_MODE,
    PERSONAL_AUTHORITY_MODE,
)
from .stage2_external_document import (
    BindingIdentity,
    ExternalReadbackOutcome,
    ExternalWriteOutcome,
    OrganizationWriteRequest,
)
from .stage2_production import (
    Stage2ProductionAssemblyError,
    Stage2ProductionDependencies,
    build_stage2_production_gateway,
)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise Stage2ProductionAssemblyError("production_dependency_missing", f"{name} is required")
    return value


def _required_env_any(*names: str) -> str:
    """Read a canonical value while accepting the isolated Stage-2 alias."""

    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    joined = " or ".join(names)
    raise Stage2ProductionAssemblyError("production_dependency_missing", f"{joined} is required")


_ENV_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _read_env_files(paths: Any) -> dict[str, str]:
    """Read only simple KEY=VALUE entries; process environment wins."""

    values: dict[str, str] = {}
    if isinstance(paths, str):
        paths = (paths,)
    if not isinstance(paths, (list, tuple)):
        return values
    for raw_path in paths:
        path = Path(str(raw_path)).expanduser()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            match = _ENV_ASSIGNMENT.match(line.strip())
            if not match:
                continue
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[match.group(1)] = value
    values.update({key: value for key, value in os.environ.items()})
    return values


def _resolve_setting(value: Any, environment: Mapping[str, str]) -> str:
    raw = "" if value is None else str(value)
    return _ENV_REFERENCE.sub(lambda match: environment.get(match.group(1), ""), raw).strip()


def _connection_factory(dsn: str):
    def connect():
        return psycopg.connect(dsn, autocommit=False)

    return connect


class _CanonicalReaders:
    def __init__(self, dsn: str, session_secret: str) -> None:
        self._connect = _connection_factory(dsn)
        if len(session_secret.encode("utf-8")) < 32:
            raise Stage2ProductionAssemblyError(
                "production_dependency_missing",
                "OPENCLAW_ACCOUNT_SESSION_SECRET must be at least 32 bytes",
            )
        self._session_secret = session_secret.encode("utf-8")

    @staticmethod
    def _token_hash(token: str) -> bytes:
        return hashlib.sha256(token.encode("ascii")).digest()

    def _csrf_hash(self, token: str) -> bytes:
        csrf = hmac.new(
            self._session_secret,
            b"openclaw-csrf\0" + token.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return self._token_hash(base64.urlsafe_b64encode(csrf).rstrip(b"=").decode("ascii"))

    def session(self, token: str) -> Mapping[str, Any] | None:
        if not isinstance(token, str) or not token.strip():
            return None
        try:
            digest = self._token_hash(token.strip())
        except (UnicodeEncodeError, ValueError):
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.id::text, u.id::text, t.id::text, t.tenant_type,
                       s.status, m.status, m.tenant_id::text, m.role,
                       t.status, u.status, s.expires_at, s.csrf_token_hash,
                       bg.generation
                FROM openclaw_account.sessions AS s
                JOIN openclaw_account.users AS u ON u.id = s.user_id
                JOIN openclaw_account.tenants AS t ON t.id = s.tenant_id
                JOIN openclaw_account.tenant_members AS m
                  ON m.tenant_id = s.tenant_id AND m.user_id = s.user_id
                LEFT JOIN media_product.stage1_binding_generations AS bg
                  ON bg.tenant_id = t.id AND bg.status = 'ACTIVE'
                WHERE s.session_token_hash = %s
                  AND s.status = 'active'
                  AND s.expires_at > now()
                  AND u.status = 'active'
                  AND t.status = 'active'
                  AND m.status = 'active'
                ORDER BY bg.generation DESC NULLS LAST
                LIMIT 1
                """,
                (digest,),
            ).fetchone()
            if row is None:
                return None
            if not hmac.compare_digest(bytes(row[11]), self._csrf_hash(token)):
                return None
            connection.execute(
                "UPDATE openclaw_account.sessions SET last_seen_at = now() WHERE id = %s",
                (row[0],),
            )
            connection.commit()
        expires = row[10]
        if isinstance(expires, datetime):
            expires_value = expires.astimezone(timezone.utc).isoformat()
        else:
            expires_value = str(expires)
        return {
            "sessionId": row[0],
            "userId": row[1],
            "tenantId": row[2],
            "tenantType": row[3],
            "sessionStatus": row[4],
            "memberStatus": row[5],
            "memberTenantId": row[6],
            "memberRole": row[7],
            "tenantStatus": row[8],
            "expiresAt": expires_value,
            "bindingGeneration": row[12],
        }

    def binding(self, tenant_id: str) -> Mapping[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT bg.binding_id::text, bg.tenant_id::text, bg.generation,
                       bg.status, si.installation_public_id,
                       lb.parent_node_token, lb.space_id
                FROM media_product.stage1_binding_generations AS bg
                JOIN media_product.stage1_installations AS si
                  ON si.id = bg.installation_id AND si.status = 'ACTIVE'
                LEFT JOIN media_product.lark_tenant_bindings AS lb
                  ON lb.id = bg.legacy_binding_id AND lb.status = 'active'
                WHERE bg.tenant_id = %s AND bg.status = 'ACTIVE'
                ORDER BY bg.generation DESC, bg.updated_at DESC
                LIMIT 1
                """,
                (tenant_id,),
            ).fetchone()
        if row is None:
            return None
        web_base = os.getenv("STAGE2_FEISHU_WEB_BASE_URL", "https://tcnwueberajc.feishu.cn").rstrip("/")
        parent = str(row[5] or "").strip()
        if not parent or not str(row[4] or "").strip():
            return None
        trusted_url = f"{web_base}/wiki/{parent}"
        return {
            "bindingId": row[0],
            "tenantId": row[1],
            "generation": int(row[2]),
            "status": str(row[3]).lower(),
            "credentialGeneration": f"{row[4]}:{row[2]}",
            "trustedOpenUrl": trusted_url,
            "spaceId": str(row[6] or "").strip(),
            "parentNodeToken": parent,
        }

    def profile(self, tenant_id: str, tenant_type: str) -> Mapping[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id::text, tenant_type, workspace_mode, body_authority,
                       status, organization_name, updated_at
                FROM openclaw_account.tenants
                WHERE id = %s AND tenant_type = %s
                """,
                (tenant_id, tenant_type),
            ).fetchone()
        if row is None:
            return None
        return {
            "tenantId": row[0],
            "tenantType": row[1],
            "fields": {
                "workspaceMode": row[2],
                "bodyAuthority": row[3],
                "status": row[4],
                "organizationName": row[5] or "",
            },
            "revision": (
                row[6].astimezone(timezone.utc).isoformat()
                if isinstance(row[6], datetime)
                else str(row[6] or "1")
            ),
        }

    def sources(self, tenant_id: str, workspace_mode: str, source_kinds: tuple[str, ...]) -> list[Mapping[str, Any]]:
        tenant_type = "personal" if workspace_mode == "personal_web" else "organization"
        source_kind = "personal_material" if tenant_type == "personal" else "organization_material"
        if source_kind not in source_kinds:
            return []
        binding = self.binding(tenant_id) if tenant_type == "organization" else None
        if tenant_type == "organization" and binding is None:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT a.public_id, a.artifact_kind, a.current_revision,
                       a.workspace_mode, a.body_authority,
                       body.body_json, body.body_checksum,
                       mirror.body_json, mirror.body_checksum
                FROM media_product.document_artifacts AS a
                LEFT JOIN media_document.revision_bodies AS body
                  ON body.tenant_id = a.tenant_id
                 AND body.public_artifact_id = a.public_id
                 AND body.revision = a.current_revision
                LEFT JOIN media_document.lark_read_mirrors AS mirror
                  ON mirror.tenant_id = a.tenant_id
                 AND mirror.public_artifact_id = a.public_id
                 AND mirror.revision = a.current_revision
                WHERE a.tenant_id = %s
                  AND a.workspace_mode = %s
                  AND a.body_authority = %s
                ORDER BY a.updated_at DESC, a.public_id
                """,
                (tenant_id, workspace_mode, "internal" if tenant_type == "personal" else "lark"),
            ).fetchall()
        result: list[Mapping[str, Any]] = []
        for row in rows:
            payload = row[5] if tenant_type == "personal" else row[7]
            # Personal artifacts are canonical local state and may not have a
            # Lark mirror. Do not invent an external payload for them.
            if tenant_type == "personal" and payload is None:
                continue
            item: dict[str, Any] = {
                "sourceId": str(row[0]),
                "sourceKind": source_kind,
                "tenantId": tenant_id,
                "workspaceMode": str(row[3]),
                "bodyAuthority": str(row[4]),
                "revision": str(row[2]),
                "payload": payload if isinstance(payload, Mapping) else {},
            }
            if tenant_type == "organization" and binding is not None:
                item.update(
                    {
                        "bindingId": binding["bindingId"],
                        "bindingGeneration": binding["generation"],
                        "bindingTenantId": tenant_id,
                    }
                )
            result.append(item)
        return result


class _SQLitePersonalWriter:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS stage2_personal_writer_receipts (
                    operation_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    artifact_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def write(self, context: Any, content: Mapping[str, Any], capability_id: str, idempotency_key: str, context_receipt: Any | None = None) -> Mapping[str, Any]:
        tenant_id = str(
            context.get("tenant_id", context.get("tenantId", ""))
            if isinstance(context, Mapping)
            else getattr(context, "tenant_id", "")
        ).strip()
        if not tenant_id or not isinstance(content, Mapping) or not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise RuntimeError("personal writer input is invalid")
        payload = json.dumps({"title": content.get("title"), "body": content.get("body"), "format": content.get("format")}, sort_keys=True, ensure_ascii=True)
        artifact_ref = f"personal:{tenant_id}:{hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]}"
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT tenant_id, content_json, artifact_ref FROM stage2_personal_writer_receipts WHERE operation_id = ?", (idempotency_key,)).fetchone()
            if row is None:
                connection.execute("INSERT INTO stage2_personal_writer_receipts(operation_id, tenant_id, content_json, artifact_ref) VALUES (?, ?, ?, ?)", (idempotency_key, tenant_id, payload, artifact_ref))
            elif str(row[0]) != tenant_id or str(row[1]) != payload:
                raise RuntimeError("personal writer idempotency conflict")
            else:
                artifact_ref = str(row[2])
            readback = connection.execute("SELECT tenant_id, content_json, artifact_ref FROM stage2_personal_writer_receipts WHERE operation_id = ?", (idempotency_key,)).fetchone()
        if readback is None or str(readback[0]) != tenant_id or str(readback[1]) != payload:
            raise RuntimeError("personal writer readback mismatch")
        return {
            "status": "succeeded",
            "artifact_ref": artifact_ref,
            "remote_ref": None,
            "registration": {"status": "registered", "store": "sqlite"},
            "readback": {"status": "confirmed", "store": "sqlite", "artifact_ref": artifact_ref},
        }


class _FeishuOrganizationAdapter:
    def __init__(self, service: FeishuService, binding_loader: Any | None = None) -> None:
        self.service = service
        self._binding_loader = binding_loader
        self._lock = threading.RLock()

    @contextmanager
    def _binding_target(self, binding: BindingIdentity):
        """Route this write to the current non-secret Binding target."""

        if not callable(self._binding_loader):
            yield
            return
        record = self._binding_loader(binding.tenant_id)
        if not isinstance(record, Mapping):
            raise RuntimeError("current Feishu Binding is unavailable")
        if str(record.get("bindingId", record.get("binding_id", ""))) != binding.binding_id or int(record.get("generation", record.get("bindingGeneration", 0))) != binding.binding_generation:
            raise RuntimeError("Feishu Binding changed during document write")
        space_id = str(record.get("spaceId", record.get("space_id", "")) or "").strip()
        parent = str(record.get("parentNodeToken", record.get("parent_node_token", "")) or "").strip()
        if not space_id or not parent:
            raise RuntimeError("Feishu Binding target is incomplete")
        with self._lock:
            previous = self.service.knowledge_base_spaces
            self.service.knowledge_base_spaces = [{"space_id": space_id, "parent_node_token": parent, "pattern": "*"}]
            try:
                yield
            finally:
                self.service.knowledge_base_spaces = previous

    @staticmethod
    def _revision(service: FeishuService, document_id: str) -> str:
        payload = service._request("GET", f"/docx/v1/documents/{document_id}")
        data = payload.get("data", {}) if isinstance(payload, Mapping) else {}
        document = data.get("document", {}) if isinstance(data, Mapping) else {}
        for value in (
            document.get("revision_id") if isinstance(document, Mapping) else None,
            document.get("document_revision_id") if isinstance(document, Mapping) else None,
            data.get("revision_id") if isinstance(data, Mapping) else None,
            payload.get("revision_id") if isinstance(payload, Mapping) else None,
        ):
            if value not in (None, ""):
                return str(value)
        return "1"

    def write(self, request: OrganizationWriteRequest) -> ExternalWriteOutcome:
        title = f"Stage2 {request.title} [{request.idempotency_key}]"
        with self._binding_target(request.binding):
            # FeishuService owns the canonical Markdown-to-Docx block renderer.
            # The production copy exposes that implementation as the private
            # method used by its existing document writers.
            blocks = self.service._content_to_docx_blocks(request.body)
            result = self.service.append_entry_blocks(title, blocks)
        document_id = str(result.get("document_id") or "").strip()
        remote_ref = str(result.get("doc") or "").strip()
        if not document_id or not remote_ref:
            raise RuntimeError("Feishu document creation did not return a document reference")
        revision = self._revision(self.service, document_id)
        binding = request.binding
        return ExternalWriteOutcome("written", remote_ref, revision, binding.tenant_id, binding.binding_id, binding.binding_generation, request.content_digest)

    def readback(self, request: OrganizationWriteRequest, write: ExternalWriteOutcome) -> ExternalReadbackOutcome:
        remote_ref = str(write.remote_ref or "")
        readback = self.service.read_document_text(remote_ref)
        if not readback.get("ok") or request.body.strip() not in str(readback.get("text") or ""):
            raise RuntimeError("Feishu document body readback did not contain the submitted content")
        reference = self.service.resolve_document_reference(remote_ref)
        document_id = str(reference.get("document_id") or "").strip()
        if not document_id:
            raise RuntimeError("Feishu document readback did not resolve a document id")
        revision = self._revision(self.service, document_id)
        binding = request.binding
        return ExternalReadbackOutcome("confirmed", remote_ref, revision, binding.tenant_id, binding.binding_id, binding.binding_generation, request.content_digest)


def _registry() -> CapabilityEffectRegistry:
    return CapabilityEffectRegistry(
        (
            CapabilityEffect(
                capability_id=DOCUMENT_WRITER_FIXTURE_ID,
                document_side_effect=True,
                allowed_authority_modes=frozenset({PERSONAL_AUTHORITY_MODE, ORGANIZATION_AUTHORITY_MODE}),
                readback_required=True,
                source_kinds=frozenset({"personal_material", "organization_material"}),
            ),
        )
    )


def build_production_stage2_gateway(*, settings_path: str, contract_path: str, contract_digest: str):
    if not isinstance(settings_path, str) or not settings_path.strip():
        raise Stage2ProductionAssemblyError("production_settings_invalid", "Stage-2 settings path is required")
    if not isinstance(contract_path, str) or not contract_path.strip() or not isinstance(contract_digest, str) or not contract_digest.strip():
        raise Stage2ProductionAssemblyError("production_contract_invalid", "Stage-2 contract identity is required")
    dsn = _required_env_any("STAGE2_ACCOUNT_DATABASE_URL", "OPENCLAW_ACCOUNT_DATABASE_URL")
    state_db = _required_env_any("STAGE2_STATE_DATABASE_PATH", "OPENCLAW_STAGE2_STATE_DATABASE_PATH")
    readers = _CanonicalReaders(dsn, _required_env("OPENCLAW_ACCOUNT_SESSION_SECRET"))
    try:
        settings = yaml.safe_load(Path(settings_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise Stage2ProductionAssemblyError("production_settings_invalid", "Stage-2 settings are unavailable") from exc
    if not isinstance(settings, Mapping):
        raise Stage2ProductionAssemblyError("production_settings_invalid", "Stage-2 settings must be an object")
    feishu_cfg = settings.get("feishu", {})
    if not isinstance(feishu_cfg, Mapping):
        raise Stage2ProductionAssemblyError("production_settings_invalid", "Feishu settings must be an object")
    env_paths = feishu_cfg.get("env_files", settings.get("feishu_env_files", []))
    if not env_paths and isinstance(settings.get("feishu_reminder"), Mapping):
        env_paths = settings["feishu_reminder"].get("env_files", [])
    environment = _read_env_files(env_paths)
    mode = _resolve_setting(feishu_cfg.get("mode", "knowledge_base"), environment).lower()
    app_id = _resolve_setting(feishu_cfg.get("app_id", ""), environment)
    app_secret = _resolve_setting(feishu_cfg.get("app_secret", ""), environment)
    web_base_url = _resolve_setting(feishu_cfg.get("web_base_url", "https://tcnwueberajc.feishu.cn"), environment)
    if mode != "knowledge_base" or not app_id or not app_secret:
        raise Stage2ProductionAssemblyError("production_dependency_missing", "Feishu knowledge_base mode and app credentials are required")
    if not web_base_url.startswith("https://"):
        raise Stage2ProductionAssemblyError("production_settings_invalid", "Feishu web base URL must use HTTPS")
    space_id = _resolve_setting(feishu_cfg.get("knowledge_base_space_id", ""), environment)
    parent_node_token = _resolve_setting(feishu_cfg.get("knowledge_base_parent_node_token", ""), environment)
    if bool(space_id) != bool(parent_node_token):
        raise Stage2ProductionAssemblyError("production_dependency_missing", "Feishu knowledge base space and parent are both required")
    raw_spaces = feishu_cfg.get("knowledge_base_spaces", [])
    spaces = []
    if isinstance(raw_spaces, list):
        for item in raw_spaces:
            if isinstance(item, Mapping):
                resolved = {key: _resolve_setting(item.get(key, ""), environment) for key in ("name", "pattern", "space_id", "parent_node_token")}
                if resolved["space_id"] and resolved["parent_node_token"]:
                    spaces.append(resolved)
    if not space_id and not spaces:
        raise Stage2ProductionAssemblyError("production_dependency_missing", "Feishu knowledge base space is required")
    service = FeishuService(
        mode,
        _resolve_setting(feishu_cfg.get("local_docs_dir", str(Path(state_db).parent / "feishu_docs")), environment),
        _resolve_setting(feishu_cfg.get("webhook_url", ""), environment),
        app_id,
        app_secret,
        _resolve_setting(feishu_cfg.get("api_base_url", "https://open.feishu.cn/open-apis"), environment),
        web_base_url,
        _resolve_setting(feishu_cfg.get("folder_token", ""), environment),
        space_id,
        parent_node_token,
        _resolve_setting(feishu_cfg.get("knowledge_base_obj_type", "docx"), environment),
        spaces,
    )
    return build_stage2_production_gateway(
        Stage2ProductionDependencies(
            capability_id=DOCUMENT_WRITER_FIXTURE_ID,
            effect_registry=_registry(),
            state_database_path=state_db,
            session_loader=readers.session,
            binding_loader=readers.binding,
            profile_loader=readers.profile,
            source_loader=readers.sources,
            personal_writer=_SQLitePersonalWriter(state_db),
            organization_adapter=_FeishuOrganizationAdapter(service, readers.binding),
        )
    )


__all__ = ["build_production_stage2_gateway"]
