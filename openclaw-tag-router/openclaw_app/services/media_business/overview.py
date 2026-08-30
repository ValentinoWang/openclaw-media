"""Tenant-scoped read and mutation service for the B01 overview page."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
import binascii
from urllib.parse import urlparse
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

from common.feishu_urls import DEFAULT_FEISHU_DOC_HOSTS

from . import foundation
from .foundation import MediaBusinessError, TenantContext, require_context


SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_SEARCH_LENGTH = 200
MAX_REASON_BYTES = 4096
MAX_IDEMPOTENCY_KEY_LENGTH = 200
PUBLIC_ID = foundation.PUBLIC_ID_PATTERN
STAGES = ("research", "assets", "decision", "creation", "publishing", "review")
ARTIFACT_TYPES = frozenset(
    {
        "research_snapshot",
        "asset_digest",
        "decision_brief",
        "creation_document",
        "publishing_package",
        "review_report",
        "project_summary",
    }
)
BODY_AUTHORITIES = frozenset({"internal", "lark"})
REVISION_STATES = frozenset({"draft", "generating", "ready", "failed", "conflict", "archived"})
SYNC_STATUSES = frozenset({"not_applicable", "pending", "synced", "conflict", "failed"})
_PENDING_DECISION_STATES = ("pending", "proposed", "awaiting_confirmation", "needs_attention")
_PENDING_PUBLISHING_STATES = ("pending", "queued", "ready", "scheduled", "needs_attention")
_PENDING_REVIEW_STATES = ("pending", "awaiting_confirmation", "needs_attention")
_TERMINAL_TASK_STATES = frozenset({"succeeded", "cancelled"})
_RUNNING_TASK_STATES = frozenset({"validating", "retrieving", "generating", "persisting", "rendering", "running"})
_ATTENTION_TASK_STATES = frozenset({"awaiting_confirmation", "pending_manual", "needs_attention"})
_CURSOR_SCOPE = {"projects", "artifacts"}
_FEISHU_DOCUMENT_HOST_SUFFIXES = tuple(f".{host}" for host in DEFAULT_FEISHU_DOC_HOSTS)
_FEISHU_DOCUMENT_ROOT_HOSTS = frozenset(DEFAULT_FEISHU_DOC_HOSTS)


OverviewError = MediaBusinessError


class OverviewForbidden(foundation.Forbidden):
    def __init__(self, message: str = "overview data is not available for this session") -> None:
        super().__init__(message)


class OverviewNotFound(foundation.NotFound):
    def __init__(self, message: str = "overview resource was not found") -> None:
        super().__init__(message)


class OverviewInvalidRequest(OverviewError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(foundation.INVALID_REQUEST, message, status=400, field=field)


class OverviewConflict(OverviewError):
    def __init__(
        self,
        message: str = "project revision conflict",
        *,
        field: str | None = None,
    ) -> None:
        super().__init__(foundation.REVISION_CONFLICT, message, status=409, field=field)


class OverviewIdempotencyConflict(foundation.IdempotencyConflict):
    def __init__(self, message: str = "idempotency key was already used for another request") -> None:
        super().__init__(message)


class OverviewInternalError(foundation.InternalError):
    def __init__(self, message: str = "overview data is unavailable") -> None:
        super().__init__(message)


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


class ConnectionFactory(Protocol):
    def __call__(self) -> AbstractContextManager[DatabaseConnection]: ...


TaskReader = Callable[[str], Mapping[str, Any]] | Any


@dataclass(frozen=True)
class _CursorPosition:
    scope: str
    tenant_digest: str
    updated_at: datetime
    public_id: str
    project_id: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp_error(label: str, reason: str) -> Exception:
    return OverviewInternalError("overview timestamp is invalid")


def _timestamp(value: Any) -> datetime:
    return foundation.coerce_utc(value, "overview timestamp", error=_timestamp_error, allow_naive=True)


def _timestamp_text(value: Any) -> str:
    return _timestamp(value).isoformat()


def _require_int(value: Any, message: str) -> int:
    if type(value) is not int or value < 0:
        raise OverviewInternalError(message)
    return value


def _require_public_id(value: Any, *, field: str = "publicId") -> str:
    if not isinstance(value, str) or PUBLIC_ID.fullmatch(value) is None:
        raise OverviewInvalidRequest("public id is invalid", field=field)
    return value


def _json_mapping(value: Any, message: str) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise OverviewInternalError(message) from exc
    if not isinstance(value, Mapping):
        raise OverviewInternalError(message)
    return value


def _json_object(value: Any, message: str) -> dict[str, Any]:
    result = _json_mapping(value, message)
    return dict(result)


def _tenant_digest(tenant_id: str) -> str:
    return hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()


def _safe_base64_decode(value: str) -> bytes:
    try:
        return foundation.b64url_decode(value)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise OverviewInvalidRequest("cursor is invalid", field="cursor") from exc


class OverviewService:
    """Read canonical PostgreSQL product tables under the authenticated tenant."""

    _DASHBOARD_QUERY = """
        WITH scope(tenant_id) AS (VALUES (%s::uuid))
        SELECT
            (SELECT COUNT(*)::int FROM media_product.content_projects AS project WHERE project.tenant_id = scope.tenant_id),
            (SELECT COUNT(*)::int FROM media_product.creation_runs AS run WHERE run.tenant_id = scope.tenant_id),
            (SELECT COUNT(*)::int FROM media_product.assets AS asset WHERE asset.tenant_id = scope.tenant_id),
            (SELECT COUNT(*)::int FROM media_product.tracks AS track WHERE track.tenant_id = scope.tenant_id),
            (SELECT COUNT(*)::int FROM media_product.creator_profiles AS creator WHERE creator.tenant_id = scope.tenant_id),
            (SELECT COUNT(*)::int FROM media_product.published_posts AS post WHERE post.tenant_id = scope.tenant_id),
            (SELECT COUNT(*)::int FROM media_product.review_records AS review WHERE review.tenant_id = scope.tenant_id),
            (SELECT COUNT(*)::int FROM media_product.decision_traces AS decision
             WHERE decision.tenant_id = scope.tenant_id
               AND COALESCE(decision.canonical_data->>'status', decision.canonical_data->>'state', '') IN ('pending', 'proposed', 'awaiting_confirmation', 'needs_attention')),
            (SELECT COUNT(*)::int FROM media_product.published_posts AS post
             WHERE post.tenant_id = scope.tenant_id
               AND COALESCE(post.canonical_data->>'status', post.canonical_data->>'state', '') IN ('pending', 'queued', 'ready', 'scheduled', 'needs_attention')),
            (SELECT COUNT(*)::int FROM media_product.review_records AS review
             WHERE review.tenant_id = scope.tenant_id
               AND COALESCE(review.canonical_data->>'status', review.canonical_data->>'state', '') IN ('pending', 'awaiting_confirmation', 'needs_attention')),
            GREATEST(
                (SELECT COALESCE(MAX(project.revision), 0)::int FROM media_product.content_projects AS project WHERE project.tenant_id = scope.tenant_id),
                (SELECT COALESCE(MAX(run.revision), 0)::int FROM media_product.creation_runs AS run WHERE run.tenant_id = scope.tenant_id),
                (SELECT COALESCE(MAX(asset.revision), 0)::int FROM media_product.assets AS asset WHERE asset.tenant_id = scope.tenant_id),
                (SELECT COALESCE(MAX(track.revision), 0)::int FROM media_product.tracks AS track WHERE track.tenant_id = scope.tenant_id),
                (SELECT COALESCE(MAX(creator.revision), 0)::int FROM media_product.creator_profiles AS creator WHERE creator.tenant_id = scope.tenant_id),
                (SELECT COALESCE(MAX(post.revision), 0)::int FROM media_product.published_posts AS post WHERE post.tenant_id = scope.tenant_id),
                (SELECT COALESCE(MAX(review.revision), 0)::int FROM media_product.review_records AS review WHERE review.tenant_id = scope.tenant_id)
            )
        FROM scope
    """

    _STAGES_QUERY = """
        SELECT project.stage, COUNT(*)::int
        FROM media_product.content_projects AS project
        WHERE project.tenant_id = %s
        GROUP BY project.stage
    """

    _PROJECT_LOOKUP_QUERY = """
        SELECT project.revision, project.updated_at
        FROM media_product.content_projects AS project
        WHERE project.tenant_id = %s
          AND project.public_id = %s
    """

    _PROJECTS_PREFIX = """
        SELECT project.public_id,
               project.title,
               project.stage,
               project.revision,
               project.canonical_data,
               project.updated_at,
               COALESCE(
                   (
                       SELECT jsonb_object_agg(counts.artifact_kind, counts.total)
                       FROM (
                           SELECT artifact.artifact_kind, COUNT(*)::int AS total
                           FROM media_product.document_artifacts AS artifact
                           WHERE artifact.tenant_id = project.tenant_id
                             AND artifact.public_project_id = project.public_id
                           GROUP BY artifact.artifact_kind
                       ) AS counts
                   ),
                   '{}'::jsonb
               ) AS artifact_counts
        FROM media_product.content_projects AS project
    """

    _ARTIFACTS_PREFIX = """
        SELECT artifact.public_id,
               artifact.public_project_id,
               artifact.artifact_kind,
               artifact.body_authority,
               artifact.current_revision,
               document_revision.state,
               binding_batch.remote_document_version,
               COALESCE(
                   NULLIF(BTRIM(binding_batch.error_detail #>> '{larkResource,title}'), ''),
                   artifact_heading.display_name
               ) AS display_name,
               artifact.docx_url,
               artifact.docx_url_expires_at,
               artifact.updated_at
        FROM media_product.content_projects AS project
        JOIN media_product.document_artifacts AS artifact
          ON artifact.tenant_id = project.tenant_id
         AND artifact.public_project_id = project.public_id
        LEFT JOIN media_product.document_revisions AS document_revision
          ON document_revision.tenant_id = artifact.tenant_id
         AND document_revision.public_artifact_id = artifact.public_id
         AND document_revision.revision = artifact.current_revision
        LEFT JOIN media_product.lark_document_bindings AS binding
          ON binding.tenant_id = artifact.tenant_id
         AND binding.public_artifact_id = artifact.public_id
        LEFT JOIN media_product.sync_batches AS binding_batch
          ON binding_batch.tenant_id = binding.tenant_id
         AND binding_batch.public_sync_id = binding.public_sync_id
        LEFT JOIN media_document.revision_bodies AS internal_body
          ON internal_body.tenant_id = artifact.tenant_id
         AND internal_body.public_artifact_id = artifact.public_id
         AND internal_body.revision = artifact.current_revision
        LEFT JOIN media_document.lark_read_mirrors AS lark_mirror
          ON lark_mirror.tenant_id = artifact.tenant_id
         AND lark_mirror.public_artifact_id = artifact.public_id
         AND lark_mirror.revision = artifact.current_revision
        LEFT JOIN LATERAL (
            SELECT NULLIF(
                       BTRIM(
                           STRING_AGG(
                               content_node.value ->> 'text',
                               '' ORDER BY content_node.ordinality
                           )
                       ),
                       ''
                   ) AS display_name
            FROM JSONB_ARRAY_ELEMENTS(
                     COALESCE(
                         CASE
                             WHEN artifact.body_authority = 'lark' THEN lark_mirror.body_json
                             ELSE internal_body.body_json
                         END -> 'blocks',
                         '[]'::jsonb
                     )
                 ) WITH ORDINALITY AS heading(block, ordinality)
            CROSS JOIN LATERAL JSONB_ARRAY_ELEMENTS(
                COALESCE(heading.block -> 'content', '[]'::jsonb)
            ) WITH ORDINALITY AS content_node(value, ordinality)
            WHERE heading.block ->> 'type' = 'heading_1'
            GROUP BY heading.ordinality
            ORDER BY heading.ordinality
            LIMIT 1
        ) AS artifact_heading ON TRUE
        WHERE project.tenant_id = %s
          AND project.public_id = %s
    """

    _IDEMPOTENCY_SELECT = """
        SELECT request_fingerprint, response_json, response_status
        FROM media_product.project_summary_idempotency
        WHERE tenant_id = %s
          AND operation = %s
          AND idempotency_key = %s
        FOR UPDATE
    """

    _SUMMARY_PROJECT_SELECT = """
        SELECT project.public_id,
               project.revision,
               project.title,
               project.stage,
               project.canonical_data,
               project.updated_at
        FROM media_product.content_projects AS project
        WHERE project.tenant_id = %s
          AND project.public_id = %s
        FOR UPDATE
    """

    _SUMMARY_ARTIFACT_SELECT = """
        SELECT artifact.public_id,
               artifact.current_revision,
               artifact.body_authority,
               artifact.workspace_mode
        FROM media_product.document_artifacts AS artifact
        WHERE artifact.tenant_id = %s
          AND artifact.public_project_id = %s
          AND artifact.artifact_kind = 'project_summary'
        ORDER BY artifact.updated_at DESC, artifact.public_id DESC
        LIMIT 1
        FOR UPDATE
    """

    _SUMMARY_PROJECT_READBACK = """
        SELECT project.revision, project.updated_at
        FROM media_product.content_projects AS project
        WHERE project.tenant_id = %s
          AND project.public_id = %s
    """

    _SUMMARY_ARTIFACT_READBACK = """
        SELECT artifact.public_id,
               artifact.current_revision,
               artifact.body_authority,
               artifact.workspace_mode,
               artifact.updated_at
        FROM media_product.document_artifacts AS artifact
        WHERE artifact.tenant_id = %s
          AND artifact.public_project_id = %s
          AND artifact.artifact_kind = 'project_summary'
        ORDER BY artifact.updated_at DESC, artifact.public_id DESC
        LIMIT 1
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        task_reader: TaskReader | None,
        cursor_secret: bytes,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        if len(cursor_secret) < 16:
            raise ValueError("B01 cursor secret must be at least 16 bytes")
        self._connection_factory = connection_factory
        self._task_reader = task_reader
        # c3/c5: purpose-tagged cursor key, distinct from every other
        # service's -- previously a bare sha256(cursor_secret) shared
        # byte-for-byte across services. Deliberately invalidates any
        # cursor a client is holding across the deploy.
        self._cursor_key = foundation.derive_namespace_secret(cursor_secret, "overview-cursor")
        self._id_factory = id_factory or (lambda prefix: f"{prefix}_{uuid.uuid4().hex}")
        self._clock = clock

    def get_dashboard(self, context: TenantContext) -> dict[str, Any]:
        tenant_id = self._scope(context)
        try:
            with self._connection_factory() as connection:
                row = connection.execute(self._DASHBOARD_QUERY, (tenant_id,)).fetchone()
                stage_rows = connection.execute(self._STAGES_QUERY, (tenant_id,)).fetchall()
        except OverviewError:
            raise
        except Exception as exc:
            raise OverviewInternalError() from exc

        if not isinstance(row, (tuple, list)) or len(row) != 11:
            raise OverviewInternalError("dashboard row shape is invalid")
        values = [_require_int(value, "dashboard count is invalid") for value in row]
        counts = {
            "contentProjects": values[0],
            "runs": values[1],
            "assets": values[2],
            "tracks": values[3],
            "creators": values[4],
            "publishedPosts": values[5],
            "reviews": values[6],
        }
        stages = {stage: 0 for stage in STAGES}
        for stage_row in stage_rows:
            if not isinstance(stage_row, (tuple, list)) or len(stage_row) != 2:
                raise OverviewInternalError("project stage row shape is invalid")
            stage, count = stage_row
            if stage not in stages:
                raise OverviewInternalError("project stage is invalid")
            stages[stage] = _require_int(count, "project stage count is invalid")

        task_summary = self._read_task_summary(tenant_id)
        known = sum(counts.values())
        revision = values[10]
        summary = {
            "counts": counts,
            "contentProjectStages": [
                {"stage": stage, "count": stages[stage]} for stage in STAGES
            ],
            "pendingDecisions": values[7],
            "pendingPublishing": values[8],
            "pendingReviews": values[9],
            "taskSummary": task_summary,
            "coverage": {"known": known, "unknown": 0, "unavailable": 0},
            "generatedAt": _timestamp_text(self._clock()),
            "revision": revision,
        }
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": revision,
            "summary": summary,
        }

    @staticmethod
    def response_etag(response: Mapping[str, Any]) -> str:
        """Return a stable strong tag for the semantic B01 response payload."""
        payload = dict(response)
        summary = payload.get("summary")
        if isinstance(summary, Mapping):
            stable_summary = dict(summary)
            stable_summary.pop("generatedAt", None)
            payload["summary"] = stable_summary
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f'"{hashlib.sha256(encoded).hexdigest()}"'

    def list_content_projects(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        search: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = self._scope(context)
        size = self._page_size(page_size)
        search_text = self._search(search)
        position = self._decode_cursor(cursor, scope="projects", tenant_id=tenant_id) if cursor else None
        conditions = ["project.tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if search_text is not None:
            conditions.append("(project.title ILIKE %s OR project.public_id ILIKE %s)")
            pattern = f"%{search_text}%"
            params.extend((pattern, pattern))
        if position is not None:
            conditions.append(
                "(project.updated_at < %s OR (project.updated_at = %s AND project.public_id < %s))"
            )
            params.extend((position.updated_at, position.updated_at, position.public_id))
        query = self._PROJECTS_PREFIX + " WHERE " + " AND ".join(conditions)
        query += " ORDER BY project.updated_at DESC, project.public_id DESC LIMIT %s"
        params.append(size + 1)

        try:
            with self._connection_factory() as connection:
                rows = connection.execute(query, tuple(params)).fetchall()
        except OverviewError:
            raise
        except Exception as exc:
            raise OverviewInternalError() from exc

        if not isinstance(rows, list):
            rows = list(rows)
        has_next = len(rows) > size
        visible_rows = rows[:size]
        items = [self._project_projection(row) for row in visible_rows]
        next_cursor = None
        if has_next:
            last = visible_rows[-1]
            next_cursor = self._encode_cursor(
                _CursorPosition(
                    scope="projects",
                    tenant_digest=_tenant_digest(tenant_id),
                    updated_at=_timestamp(last[5]),
                    public_id=items[-1]["publicProjectId"],
                )
            )
        revision = max((_require_int(row[3], "project revision is invalid") for row in visible_rows), default=0)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": revision,
            "items": items,
            "nextCursor": next_cursor,
        }

    def list_project_artifacts(
        self,
        context: TenantContext,
        public_project_id: str,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        tenant_id = self._scope(context)
        project_id = _require_public_id(public_project_id, field="publicProjectId")
        size = self._page_size(page_size)
        position = self._decode_cursor(
            cursor,
            scope="artifacts",
            tenant_id=tenant_id,
            project_id=project_id,
        ) if cursor else None
        try:
            with self._connection_factory() as connection:
                project_row = connection.execute(
                    self._PROJECT_LOOKUP_QUERY, (tenant_id, project_id)
                ).fetchone()
                if project_row is None:
                    raise OverviewNotFound()
                if not isinstance(project_row, (tuple, list)) or len(project_row) != 2:
                    raise OverviewInternalError("project row shape is invalid")
                project_revision = _require_int(project_row[0], "project revision is invalid")
                condition = "artifact.updated_at < %s OR (artifact.updated_at = %s AND artifact.public_id < %s)"
                params: list[Any] = [tenant_id, project_id]
                if position is not None:
                    params.extend((position.updated_at, position.updated_at, position.public_id))
                query = self._ARTIFACTS_PREFIX
                if position is not None:
                    query += " AND (" + condition + ")"
                query += " ORDER BY artifact.updated_at DESC, artifact.public_id DESC LIMIT %s"
                params.append(size + 1)
                rows = connection.execute(query, tuple(params)).fetchall()
        except OverviewError:
            raise
        except Exception as exc:
            raise OverviewInternalError() from exc

        if not isinstance(rows, list):
            rows = list(rows)
        has_next = len(rows) > size
        visible_rows = rows[:size]
        items = [self._artifact_projection(row) for row in visible_rows]
        next_cursor = None
        if has_next:
            last = visible_rows[-1]
            next_cursor = self._encode_cursor(
                _CursorPosition(
                    scope="artifacts",
                    tenant_digest=_tenant_digest(tenant_id),
                    project_id=project_id,
                    updated_at=_timestamp(last[-1]),
                    public_id=items[-1]["publicArtifactId"],
                )
            )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": project_revision,
            "items": items,
            "nextCursor": next_cursor,
        }

    def create_project_summary(
        self,
        context: TenantContext,
        public_project_id: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        tenant_id = self._scope(context)
        project_id = _require_public_id(public_project_id, field="publicProjectId")
        expected_revision, reason = self._validate_summary_request(request)
        key = self._validate_idempotency_key(idempotency_key)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "publicProjectId": project_id,
                    "expectedRevision": expected_revision,
                    "reason": reason,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        connection: Any = None
        try:
            with self._connection_factory() as connection:
                ledger = connection.execute(
                    self._IDEMPOTENCY_SELECT,
                    (tenant_id, "createProjectSummary", key),
                ).fetchone()
                if ledger is not None:
                    return self._replay_or_conflict(ledger, fingerprint)

                project_row = connection.execute(
                    self._SUMMARY_PROJECT_SELECT,
                    (tenant_id, project_id),
                ).fetchone()
                if project_row is None:
                    raise OverviewNotFound()
                if not isinstance(project_row, (tuple, list)) or len(project_row) != 6:
                    raise OverviewInternalError("project row shape is invalid")
                stored_project_id, current_revision, _title, _stage, canonical_data, _updated_at = project_row
                if stored_project_id != project_id:
                    raise OverviewInternalError("project identity is invalid")
                current_revision = _require_int(current_revision, "project revision is invalid")
                if expected_revision != current_revision:
                    raise OverviewConflict(
                        "expected project revision does not match",
                        field="expectedRevision",
                    )
                canonical = _json_mapping(canonical_data, "project canonical data is invalid")
                workspace_mode = self._workspace_mode(canonical)

                artifact_row = connection.execute(
                    self._SUMMARY_ARTIFACT_SELECT,
                    (tenant_id, project_id),
                ).fetchone()
                now = self._clock()
                if artifact_row is None:
                    public_artifact_id = self._new_public_id("project_summary")
                    artifact_revision = 1
                    connection.execute(
                        """
                        INSERT INTO media_product.document_artifacts
                            (tenant_id, public_id, public_project_id, artifact_kind,
                             workspace_mode, body_authority, current_revision)
                        VALUES (%s, %s, %s, 'project_summary', %s, 'internal', %s)
                        """,
                        (tenant_id, public_artifact_id, project_id, workspace_mode, artifact_revision),
                    )
                else:
                    if not isinstance(artifact_row, (tuple, list)) or len(artifact_row) != 4:
                        raise OverviewInternalError("summary artifact row shape is invalid")
                    public_artifact_id, previous_revision, body_authority, stored_workspace = artifact_row
                    public_artifact_id = _require_public_id(public_artifact_id, field="publicArtifactId")
                    previous_revision = _require_int(previous_revision, "artifact revision is invalid")
                    if body_authority != "internal" or stored_workspace != workspace_mode:
                        raise OverviewInternalError("summary artifact authority is invalid")
                    artifact_revision = previous_revision + 1
                    connection.execute(
                        """
                        UPDATE media_product.document_artifacts
                        SET current_revision = %s, updated_at = now()
                        WHERE tenant_id = %s AND public_id = %s
                        """,
                        (artifact_revision, tenant_id, public_artifact_id),
                    )

                body_checksum = hashlib.sha256(reason.encode("utf-8")).hexdigest()
                connection.execute(
                    """
                    INSERT INTO media_product.document_revisions
                        (tenant_id, public_artifact_id, revision, state, base_revision,
                         body_checksum, actor_public_id, generation_source)
                    VALUES (%s, %s, %s, 'generating', %s, %s, %s, 'b01_project_summary')
                    """,
                    (
                        tenant_id,
                        public_artifact_id,
                        artifact_revision,
                        None if artifact_revision == 1 else artifact_revision - 1,
                        body_checksum,
                        str(context.user_public_id),
                    ),
                )
                new_project_revision = current_revision + 1
                connection.execute(
                    """
                    UPDATE media_product.content_projects
                    SET revision = %s, updated_at = now()
                    WHERE tenant_id = %s AND public_id = %s
                    """,
                    (new_project_revision, tenant_id, project_id),
                )
                project_readback = connection.execute(
                    self._SUMMARY_PROJECT_READBACK,
                    (tenant_id, project_id),
                ).fetchone()
                if not isinstance(project_readback, (tuple, list)) or len(project_readback) != 2:
                    raise OverviewInternalError("project readback shape is invalid")
                readback_project_revision = _require_int(
                    project_readback[0], "project revision readback is invalid"
                )
                _timestamp(project_readback[1])
                if readback_project_revision != new_project_revision:
                    raise OverviewInternalError("project revision readback is stale")

                artifact_readback = connection.execute(
                    self._SUMMARY_ARTIFACT_READBACK,
                    (tenant_id, project_id),
                ).fetchone()
                if not isinstance(artifact_readback, (tuple, list)) or len(artifact_readback) != 5:
                    raise OverviewInternalError("summary artifact readback shape is invalid")
                (
                    readback_artifact_id,
                    readback_artifact_revision,
                    readback_authority,
                    readback_workspace,
                    readback_updated_at,
                ) = artifact_readback
                readback_artifact_id = _require_public_id(
                    readback_artifact_id, field="publicArtifactId"
                )
                readback_artifact_revision = _require_int(
                    readback_artifact_revision, "artifact revision readback is invalid"
                )
                if (
                    readback_artifact_id != public_artifact_id
                    or readback_authority != "internal"
                    or readback_workspace != workspace_mode
                ):
                    raise OverviewInternalError("summary artifact readback is invalid")
                artifact_updated_at = _timestamp_text(readback_updated_at)
                response = {
                    "schemaVersion": SCHEMA_VERSION,
                    "revision": readback_project_revision,
                    "item": {
                        "publicArtifactId": readback_artifact_id,
                        "publicProjectId": project_id,
                        "artifactType": "project_summary",
                        "bodyAuthority": "internal",
                        "currentRevision": readback_artifact_revision,
                        "syncStatus": "not_applicable",
                        "updatedAt": artifact_updated_at,
                        "allowedActions": ["view", "regenerate"],
                    },
                }
                connection.execute(
                    """
                    INSERT INTO media_product.project_summary_idempotency
                        (tenant_id, operation, idempotency_key, request_fingerprint,
                         public_artifact_id, response_json, response_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_id,
                        "createProjectSummary",
                        key,
                        fingerprint,
                        public_artifact_id,
                        json.dumps(response, ensure_ascii=False, sort_keys=True),
                        200,
                    ),
                )
                connection.commit()
                return response
        except OverviewError:
            if connection is not None:
                self._rollback(connection)
            raise
        except Exception as exc:
            if connection is not None:
                self._rollback(connection)
            raise OverviewInternalError() from exc

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, OverviewError):
            return {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "field": error.field,
                }
            }
        return {
            "error": {
                "code": "internal_error",
                "message": "overview data is unavailable",
                "field": None,
            }
        }

    def _scope(self, context: TenantContext | None) -> str:
        try:
            checked = require_context(context)
            tenant_id = str(checked.tenant_id).strip()
            user_id = str(checked.user_public_id).strip()
            if not tenant_id or not user_id:
                raise OverviewForbidden()
            return tenant_id
        except OverviewForbidden:
            raise
        except (MediaBusinessError, AttributeError, TypeError, ValueError) as exc:
            raise OverviewForbidden() from exc

    @staticmethod
    def _page_size(page_size: int) -> int:
        return foundation.page_size(page_size, error=lambda m: OverviewInvalidRequest(m, field="pageSize"))

    @staticmethod
    def _search(search: str | None) -> str | None:
        if search is None:
            return None
        if not isinstance(search, str):
            raise OverviewInvalidRequest("search is invalid", field="search")
        value = search.strip()
        if len(value) > MAX_SEARCH_LENGTH:
            raise OverviewInvalidRequest("search is too long", field="search")
        return value or None

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        if not isinstance(value, str):
            raise OverviewInvalidRequest("idempotency key is required", field="Idempotency-Key")
        key = value.strip()
        if len(key) < 8 or len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise OverviewInvalidRequest("idempotency key is invalid", field="Idempotency-Key")
        return key

    @staticmethod
    def _validate_summary_request(request: Mapping[str, Any]) -> tuple[int, str]:
        if not isinstance(request, Mapping) or set(request) != {"expectedRevision", "reason"}:
            raise OverviewInvalidRequest("project summary request is invalid")
        expected_revision = request["expectedRevision"]
        if type(expected_revision) is not int or expected_revision < 0:
            raise OverviewInvalidRequest("expected revision is invalid", field="expectedRevision")
        reason = request["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise OverviewInvalidRequest("reason is required", field="reason")
        reason = reason.strip()
        if len(reason.encode("utf-8")) > MAX_REASON_BYTES:
            raise OverviewInvalidRequest("reason is too long", field="reason")
        return expected_revision, reason

    def _read_task_summary(self, tenant_id: str) -> dict[str, int]:
        if self._task_reader is None:
            raise OverviewInternalError("task data is unavailable")
        try:
            reader = self._task_reader
            if callable(reader):
                result = reader(tenant_id)
            elif hasattr(reader, "list_tasks"):
                result = reader.list_tasks(tenant_id=tenant_id, limit=100)
            else:
                raise OverviewInternalError("task data is unavailable")
        except OverviewError:
            raise
        except Exception as exc:
            raise OverviewInternalError("task data is unavailable") from exc
        if not isinstance(result, Mapping):
            raise OverviewInternalError("task response shape is invalid")
        if result.get("schemaVersion") == "media_web_task_v3":
            items = result.get("tasks")
            if not isinstance(items, list):
                raise OverviewInternalError("task response shape is invalid")
        elif (
            result.get("schemaVersion") == SCHEMA_VERSION
            and type(result.get("revision")) is int
            and result["revision"] >= 0
            and isinstance(result.get("items"), list)
            and "nextCursor" in result
        ):
            items = result["items"]
        else:
            raise OverviewInternalError("task response shape is invalid")
        summary = {"queued": 0, "running": 0, "needsAttention": 0, "failed": 0}
        for task in items:
            if not isinstance(task, Mapping) or not isinstance(task.get("status"), str):
                raise OverviewInternalError("task row shape is invalid")
            status = task["status"]
            if status == "queued":
                summary["queued"] += 1
            elif status in _RUNNING_TASK_STATES:
                summary["running"] += 1
            elif status in _ATTENTION_TASK_STATES:
                summary["needsAttention"] += 1
            elif status == "failed":
                summary["failed"] += 1
            elif status not in _TERMINAL_TASK_STATES:
                raise OverviewInternalError("task status is invalid")
        return summary

    @staticmethod
    def _workspace_mode(canonical_data: Mapping[str, Any]) -> str:
        value = canonical_data.get("workspace_mode", canonical_data.get("workspaceMode", "personal_web"))
        if value not in {"personal_web", "organization_lark"}:
            raise OverviewInternalError("project workspace mode is invalid")
        return str(value)

    @staticmethod
    def _project_status(canonical_data: Mapping[str, Any]) -> str:
        value = canonical_data.get("status", canonical_data.get("state", "active"))
        if not isinstance(value, str) or not value.strip():
            raise OverviewInternalError("project status is invalid")
        return value.strip()

    def _project_projection(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 7:
            raise OverviewInternalError("project row shape is invalid")
        public_id, title, stage, revision, canonical_data, updated_at, artifact_counts = row
        public_id = _require_public_id(public_id, field="publicProjectId")
        if not isinstance(title, str) or not isinstance(stage, str) or not stage.strip():
            raise OverviewInternalError("project projection is invalid")
        revision = _require_int(revision, "project revision is invalid")
        canonical = _json_mapping(canonical_data, "project canonical data is invalid")
        return {
            "publicProjectId": public_id,
            "title": title,
            "workspaceMode": self._workspace_mode(canonical),
            "stage": stage,
            "status": self._project_status(canonical),
            "artifactCounts": self._artifact_counts(artifact_counts),
            "updatedAt": _timestamp_text(updated_at),
        }

    @staticmethod
    def _artifact_counts(value: Any) -> dict[str, int]:
        mapping = _json_mapping(value, "artifact counts are invalid")
        result: dict[str, int] = {}
        for key, count in mapping.items():
            if not isinstance(key, str) or not key or type(count) is not int or count < 0:
                raise OverviewInternalError("artifact counts are invalid")
            result[key] = count
        return result

    def _artifact_projection(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 11:
            raise OverviewInternalError("artifact row shape is invalid")
        public_id, project_id, artifact_type, body_authority, current_revision, revision_state, remote_version, display_name, document_url, document_url_expires_at, updated_at = row
        public_id = _require_public_id(public_id, field="publicArtifactId")
        project_id = _require_public_id(project_id, field="publicProjectId")
        if artifact_type not in ARTIFACT_TYPES or body_authority not in BODY_AUTHORITIES:
            raise OverviewInternalError("artifact projection is invalid")
        if display_name is not None and not isinstance(display_name, str):
            raise OverviewInternalError("artifact display name is invalid")
        display_name = display_name.strip() if isinstance(display_name, str) else None
        if not display_name:
            display_name = None
        current_revision = _require_int(current_revision, "artifact revision is invalid")
        if revision_state is not None and revision_state not in REVISION_STATES:
            raise OverviewInternalError("artifact revision state is invalid")
        if body_authority == "internal":
            sync_status = "not_applicable"
        elif revision_state == "conflict":
            sync_status = "conflict"
        elif revision_state == "failed":
            sync_status = "failed"
        elif isinstance(remote_version, str) and remote_version.strip():
            sync_status = "synced"
        else:
            sync_status = "pending"
        if sync_status not in SYNC_STATUSES:
            raise OverviewInternalError("artifact sync status is invalid")
        organization_document_url = self._organization_document_url(document_url, body_authority)
        actions = ["view"]
        if organization_document_url is not None:
            actions.append("open_organization_document")
        if artifact_type != "publishing_package":
            actions.append("regenerate")
        if sync_status in {"conflict", "failed"}:
            actions.append("resolve_sync")
        return {
            "publicArtifactId": public_id,
            "publicProjectId": project_id,
            "artifactType": artifact_type,
            "displayName": display_name,
            "bodyAuthority": body_authority,
            "currentRevision": current_revision,
            "syncStatus": sync_status,
            "updatedAt": _timestamp_text(updated_at),
            "organizationDocumentUrl": organization_document_url,
            "organizationDocumentUrlExpiresAt": _timestamp_text(document_url_expires_at) if organization_document_url and document_url_expires_at is not None else None,
            "allowedActions": actions,
        }

    @staticmethod
    def _organization_document_url(value: Any, body_authority: str) -> str | None:
        if body_authority != "lark" or not isinstance(value, str) or not value.strip():
            return None
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
        parts = [part for part in parsed.path.split("/") if part]
        trusted_host = host in _FEISHU_DOCUMENT_ROOT_HOSTS or any(
            host.endswith(suffix) for suffix in _FEISHU_DOCUMENT_HOST_SUFFIXES
        )
        if parsed.scheme != "https" or not trusted_host:
            raise OverviewInternalError("organization document URL host is invalid")
        if len(parts) != 2 or parts[0].lower() not in {"wiki", "docx", "doc", "docs"} or PUBLIC_ID.fullmatch(parts[1]) is None:
            raise OverviewInternalError("organization document URL shape is invalid")
        return value.strip()

    def _new_public_id(self, prefix: str) -> str:
        value = self._id_factory(prefix)
        if not isinstance(value, str) or PUBLIC_ID.fullmatch(value) is None:
            raise OverviewInternalError("generated public id is invalid")
        return value

    def _encode_cursor(self, position: _CursorPosition) -> str:
        if position.scope not in _CURSOR_SCOPE:
            raise OverviewInternalError("cursor scope is invalid")
        payload: dict[str, Any] = {
            "v": 1,
            "scope": position.scope,
            "tenant": position.tenant_digest,
            "updatedAt": _timestamp_text(position.updated_at),
            "publicId": position.public_id,
        }
        if position.project_id is not None:
            payload["projectId"] = position.project_id
        body = foundation.canonical_json_bytes(payload)
        signature = hmac.new(self._cursor_key, body, hashlib.sha256).digest()
        encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
        return f"{encode(body)}.{encode(signature)}"

    def _decode_cursor(
        self,
        cursor: str,
        *,
        scope: str,
        tenant_id: str,
        project_id: str | None = None,
    ) -> _CursorPosition:
        if not isinstance(cursor, str) or cursor.count(".") != 1:
            raise OverviewInvalidRequest("cursor is invalid", field="cursor")
        encoded_body, encoded_signature = cursor.split(".")
        body = _safe_base64_decode(encoded_body)
        signature = _safe_base64_decode(encoded_signature)
        expected = hmac.new(self._cursor_key, body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise OverviewInvalidRequest("cursor is invalid", field="cursor")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OverviewInvalidRequest("cursor is invalid", field="cursor") from exc
        if (
            not isinstance(payload, Mapping)
            or payload.get("v") != 1
            or payload.get("scope") != scope
            or payload.get("tenant") != _tenant_digest(tenant_id)
            or payload.get("projectId") != project_id
        ):
            raise OverviewInvalidRequest("cursor is invalid", field="cursor")
        public_id = payload.get("publicId")
        if not isinstance(public_id, str) or PUBLIC_ID.fullmatch(public_id) is None:
            raise OverviewInvalidRequest("cursor is invalid", field="cursor")
        try:
            updated_at = _timestamp(payload.get("updatedAt"))
        except OverviewError as exc:
            raise OverviewInvalidRequest("cursor is invalid", field="cursor") from exc
        return _CursorPosition(
            scope=scope,
            tenant_digest=_tenant_digest(tenant_id),
            updated_at=updated_at,
            public_id=public_id,
            project_id=project_id,
        )

    @staticmethod
    def _replay_or_conflict(row: Any, fingerprint: str) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise OverviewInternalError("idempotency row shape is invalid")
        stored_fingerprint, stored_response, status = row
        if not isinstance(stored_fingerprint, str) or stored_fingerprint != fingerprint:
            raise OverviewIdempotencyConflict()
        if status != 200:
            raise OverviewInternalError("idempotency response status is invalid")
        response = _json_object(stored_response, "idempotency response is invalid")
        if response.get("schemaVersion") != SCHEMA_VERSION or "item" not in response:
            raise OverviewInternalError("idempotency response is invalid")
        return response

    @staticmethod
    def _rollback(connection: Any) -> None:
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            try:
                rollback()
            except Exception:
                pass
