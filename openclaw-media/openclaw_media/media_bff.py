"""Tenant-owned, public-safe projections for the Media Web BFF."""

from __future__ import annotations

from hashlib import sha256
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .archive import ArchiveManifest, ArchiveReceipt
from .catalog import InstalledCatalog
from .device import Device


_RUN_STATUSES = Literal[
    "created",
    "validating",
    "preprocessing",
    "analyzing",
    "rendering",
    "reviewing",
    "ready_to_archive",
    "succeeded",
    "pending_manual",
    "failed",
    "cancelled",
]


class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


def _safe_id(value: str) -> str:
    if not value or len(value) > 256 or any(char.isspace() for char in value):
        raise ValueError("invalid public identifier")
    lowered = value.lower()
    if (
        value.startswith(("/", "\\"))
        or "\\" in value
        or "://" in value
        or lowered.startswith(("file:", "env:"))
        or (len(value) >= 2 and value[1] == ":")
    ):
        raise ValueError("invalid public identifier")
    return value


def _safe_ref(value: str) -> str:
    _safe_id(value)
    if value.startswith("/") or ".." in value.split("/"):
        raise ValueError("invalid public reference")
    return value


def _safe_text(value: str) -> str:
    lowered = value.lower()
    if (
        "\x00" in value
        or "://" in value
        or "/home/" in lowered
        or "c:\\users" in lowered
        or "authorization:" in lowered
        or "api_key=" in lowered
        or "api-key=" in lowered
    ):
        raise ValueError("unsafe public text")
    return value


class OwnerContext(_PublicModel):
    """Authenticated owner identity supplied by the server session adapter."""

    tenant_id: str = Field(min_length=1, max_length=128, repr=False)
    owner_id: str = Field(min_length=1, max_length=128, repr=False)

    _ids = field_validator("tenant_id", "owner_id")(_safe_id)


class PipelineProjection(_PublicModel):
    pipeline_id: str
    version: str
    catalog_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    display_name: str
    description: str
    min_cli_version: str
    node_ids: tuple[str, ...]
    output_names: tuple[str, ...]
    model_modalities: tuple[str, ...]

    _ids = field_validator("pipeline_id", "version", "min_cli_version")(_safe_id)
    _node_ids = field_validator("node_ids", "output_names", "model_modalities")(
        lambda values: tuple(_safe_id(value) for value in values)
    )
    _text = field_validator("display_name", "description")(_safe_text)


class DeviceProjection(_PublicModel):
    device_id: str
    name: str
    revision: int = Field(ge=1)
    status: Literal["paired", "revoked"]
    last_heartbeat: int | None = Field(default=None, ge=0)

    _id = field_validator("device_id")(_safe_id)
    _name = field_validator("name")(_safe_text)


class RunProjection(_PublicModel):
    run_id: str
    pipeline_id: str
    device_id: str | None = None
    revision: int = Field(ge=1)
    status: _RUN_STATUSES
    completed_nodes: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    archive_id: str | None = None

    _ids = field_validator("run_id", "pipeline_id", "device_id", "archive_id")(
        lambda value: None if value is None else _safe_id(value)
    )
    _nodes = field_validator("completed_nodes")(
        lambda values: tuple(_safe_id(value) for value in values)
    )
    _refs = field_validator("artifact_refs")(
        lambda values: tuple(_safe_ref(value) for value in values)
    )


class AnalysisOutputProjection(_PublicModel):
    ref: str
    mime_type: str
    archive_selected: bool = False

    _ref = field_validator("ref")(_safe_ref)
    _mime = field_validator("mime_type")(_safe_id)


class AnalysisRunProjection(_PublicModel):
    run_id: str
    pipeline_id: str
    device_id: str | None = None
    revision: int = Field(ge=1)
    business_status: Literal["draft", "processing", "ready", "archived", "failed"]
    job_id: str | None = None
    job_status: Literal["not_scheduled", "queued", "leased", "acknowledged", "running", "succeeded", "blocked", "failed", "expired", "cancelled"]
    analysis_status: Literal["created", "running", "ready", "pending_manual", "failed", "cancelled"]
    archive_status: Literal["not_selected", "selected", "committed", "deleting", "deleted", "failed"]
    completed_nodes: tuple[str, ...] = ()
    outputs: tuple[AnalysisOutputProjection, ...] = ()
    archive_id: str | None = None

    _ids = field_validator("run_id", "pipeline_id", "device_id", "job_id", "archive_id")(
        lambda value: None if value is None else _safe_id(value)
    )
    _nodes = field_validator("completed_nodes")(
        lambda values: tuple(_safe_id(value) for value in values)
    )

    @model_validator(mode="after")
    def _state_refs_match(self) -> "AnalysisRunProjection":
        if (self.job_status == "not_scheduled") != (self.job_id is None):
            raise ValueError("job state requires matching job id")
        committed = self.archive_status in {"committed", "deleting", "deleted"}
        if committed != (self.archive_id is not None):
            raise ValueError("archive state requires matching archive id")
        return self


class ArchiveArtifactProjection(_PublicModel):
    ref: str
    mime_type: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    archive_mode: Literal["content", "descriptor_only"]

    _ref = field_validator("ref")(_safe_ref)
    _mime = field_validator("mime_type")(_safe_id)


class ProjectionRef(_PublicModel):
    table_key: str
    record_id: str
    owner_contract: str

    _ids = field_validator("table_key", "record_id", "owner_contract")(_safe_id)


class ArchiveRecord(_PublicModel):
    archive_id: str
    commit_id: str
    manifest_id: str
    pipeline_id: str
    run_id: str | None = None
    device_id: str | None = None
    status: Literal["active", "deleting", "delete_failed"] = "active"
    revision: int = Field(ge=1)
    created_at: int = Field(ge=0)
    artifacts: tuple[ArchiveArtifactProjection, ...]
    projection_refs: tuple[ProjectionRef, ...] = ()
    cloud_bytes: int = Field(ge=0)

    _ids = field_validator(
        "archive_id", "commit_id", "manifest_id", "pipeline_id", "run_id", "device_id"
    )(lambda value: None if value is None else _safe_id(value))


class ArchiveDeleteReceipt(_PublicModel):
    deletion_id: str
    archive_id: str
    commit_id: str
    artifact_hashes: tuple[str, ...]
    projection_refs: tuple[ProjectionRef, ...]
    deleted_at: int = Field(ge=0)
    result: Literal["deleted"] = "deleted"

    _ids = field_validator("deletion_id", "archive_id", "commit_id")(_safe_id)
    _hashes = field_validator("artifact_hashes")(
        lambda values: tuple(
            value
            if len(value) == 64 and all(char in "0123456789abcdef" for char in value)
            else (_ for _ in ()).throw(ValueError("invalid artifact hash"))
            for value in values
        )
    )


class MediaBffOutcome(_PublicModel):
    status: Literal["completed", "pending_manual"]
    code: str
    pipelines: tuple[PipelineProjection, ...] = ()
    devices: tuple[DeviceProjection, ...] = ()
    runs: tuple[RunProjection, ...] = ()
    analysis_runs: tuple[AnalysisRunProjection, ...] = ()
    archives: tuple[ArchiveRecord, ...] = ()
    delete_receipt: ArchiveDeleteReceipt | None = None

    def model_dump(self, *args, **kwargs):
        payload = super().model_dump(*args, **kwargs)
        if not self.analysis_runs:
            payload.pop("analysis_runs", None)
        return payload


def _completed(code: str, **values: object) -> MediaBffOutcome:
    return MediaBffOutcome(status="completed", code=code, **values)


def _pending(code: str) -> MediaBffOutcome:
    return MediaBffOutcome(status="pending_manual", code=code)


class MediaBff:
    """Single typed BFF owner for safe catalog, device, run, and archive views.

    The authenticated context is never serialized into an outcome. Archive
    content, device credentials, run inputs, local paths, provider payloads,
    and endpoint configuration have no field in this boundary.
    """

    def __init__(self, catalog: InstalledCatalog | None = None) -> None:
        self._catalog = catalog or InstalledCatalog()
        self._lock = RLock()
        self._devices: dict[tuple[str, str, str], DeviceProjection] = {}
        self._runs: dict[tuple[str, str, str], RunProjection] = {}
        self._analysis_runs: dict[tuple[str, str, str], AnalysisRunProjection] = {}
        self._archives: dict[tuple[str, str, str], ArchiveRecord] = {}
        self._commit_index: dict[tuple[str, str, str], str] = {}
        self._deletions: dict[tuple[str, str, str], ArchiveDeleteReceipt] = {}
        self._pipeline_ids = frozenset(
            item["pipeline_id"] for item in self._catalog.manifest["pipelines"]
        )

    @staticmethod
    def _owner_key(context: OwnerContext) -> tuple[str, str]:
        return context.tenant_id, context.owner_id

    def list_pipelines(self, context: OwnerContext) -> MediaBffOutcome:
        self._owner_key(context)
        projections = []
        for item in self._catalog.manifest["pipelines"]:
            projections.append(
                PipelineProjection(
                    pipeline_id=item["pipeline_id"],
                    version=item["version"],
                    catalog_digest=item["catalog_digest"],
                    display_name=item["display_name"],
                    description=item["description"],
                    min_cli_version=item["min_cli_version"],
                    node_ids=tuple(node["node_id"] for node in item["nodes"]),
                    output_names=tuple(
                        output["name"] for output in item["output_allowlist"]
                    ),
                    model_modalities=tuple(
                        sorted(
                            {
                                modality
                                for requirement in item["model_requirements"]
                                for modality in requirement["modalities"]
                            }
                        )
                    ),
                )
            )
        return _completed("pipelines_found", pipelines=tuple(projections))

    def record_device(self, context: OwnerContext, device: Device) -> MediaBffOutcome:
        if device.tenant_id != context.tenant_id:
            return _pending("tenant_forbidden")
        try:
            projection = DeviceProjection(
                device_id=device.device_id,
                name=device.name,
                revision=device.revision,
                status=device.status,
                last_heartbeat=device.last_heartbeat,
            )
        except (TypeError, ValueError):
            return _pending("unsafe_projection")
        key = (*self._owner_key(context), projection.device_id)
        with self._lock:
            current = self._devices.get(key)
            if current is not None and projection.revision < current.revision:
                return _pending("stale_revision")
            self._devices[key] = projection
        return _completed("device_recorded", devices=(projection,))

    def list_devices(self, context: OwnerContext) -> MediaBffOutcome:
        owner = self._owner_key(context)
        with self._lock:
            devices = tuple(
                value
                for key, value in sorted(self._devices.items())
                if key[:2] == owner
            )
        return _completed("devices_found", devices=devices)

    def record_run(self, context: OwnerContext, run: RunProjection) -> MediaBffOutcome:
        if run.pipeline_id not in self._pipeline_ids:
            return _pending("pipeline_not_installed")
        key = (*self._owner_key(context), run.run_id)
        with self._lock:
            current = self._runs.get(key)
            if current is not None and run.revision < current.revision:
                return _pending("stale_revision")
            if current is not None and run.revision == current.revision and run != current:
                return _pending("revision_conflict")
            self._runs[key] = run
        return _completed("run_recorded", runs=(run,))

    def list_runs(self, context: OwnerContext) -> MediaBffOutcome:
        owner = self._owner_key(context)
        with self._lock:
            runs = tuple(
                value for key, value in sorted(self._runs.items()) if key[:2] == owner
            )
        return _completed("runs_found", runs=runs)

    def record_analysis_run(self, context: OwnerContext, run: AnalysisRunProjection) -> MediaBffOutcome:
        if run.pipeline_id not in self._pipeline_ids:
            return _pending("pipeline_not_installed")
        key = (*self._owner_key(context), run.run_id)
        with self._lock:
            current = self._analysis_runs.get(key)
            if current is not None and run.revision < current.revision:
                return _pending("stale_revision")
            if current is not None and run.revision == current.revision and run != current:
                return _pending("revision_conflict")
            self._analysis_runs[key] = run
        return _completed("analysis_run_recorded", analysis_runs=(run,))

    def list_analysis_runs(self, context: OwnerContext) -> MediaBffOutcome:
        owner = self._owner_key(context)
        with self._lock:
            runs = tuple(value for key, value in sorted(self._analysis_runs.items()) if key[:2] == owner)
        return _completed("analysis_runs_found", analysis_runs=runs)

    def get_analysis_run(self, context: OwnerContext, run_id: str) -> MediaBffOutcome:
        try:
            run_id = _safe_id(run_id)
        except ValueError:
            return _pending("invalid_run_id")
        with self._lock:
            run = self._analysis_runs.get((*self._owner_key(context), run_id))
        if run is None:
            return _pending("analysis_run_not_found")
        return _completed("analysis_run_found", analysis_runs=(run,))

    def record_archive(
        self,
        context: OwnerContext,
        manifest: ArchiveManifest,
        receipt: ArchiveReceipt,
        *,
        pipeline_id: str,
        created_at: int,
        run_id: str | None = None,
        device_id: str | None = None,
        projection_refs: tuple[ProjectionRef, ...] = (),
    ) -> MediaBffOutcome:
        if pipeline_id not in self._pipeline_ids:
            return _pending("pipeline_not_installed")
        if created_at < 0:
            return _pending("invalid_timestamp")
        if (
            manifest.tenant_id != context.tenant_id
            or receipt.tenant_id != context.tenant_id
            or manifest.owner_id != context.owner_id
            or receipt.owner_id != context.owner_id
        ):
            return _pending("tenant_forbidden")
        if (
            manifest.manifest_id != receipt.manifest_id
            or tuple(item.ref for item in manifest.items) != receipt.item_refs
        ):
            return _pending("archive_receipt_mismatch")
        # Archive links are owner-scoped as well as typed.  Do not allow a
        # caller to attach a foreign run/device (or a mismatched pipeline) to
        # an otherwise valid commit.
        owner = self._owner_key(context)
        with self._lock:
            if run_id is not None:
                linked_run = self._analysis_runs.get((*owner, run_id))
                if linked_run is not None and linked_run.pipeline_id != pipeline_id:
                    return _pending("pipeline_conflict")
            if device_id is not None and any(
                key[2] == device_id and key[:2] != owner for key in self._devices
            ):
                return _pending("device_forbidden")
        try:
            artifacts = tuple(
                ArchiveArtifactProjection(
                    ref=item.ref,
                    mime_type=item.mime_type,
                    sha256=item.sha256,
                    size_bytes=item.size_bytes,
                    archive_mode="descriptor_only" if item.descriptor_only else "content",
                )
                for item in manifest.items
            )
            archive_id = "archive/" + sha256(receipt.commit_id.encode()).hexdigest()[:32]
            record = ArchiveRecord(
                archive_id=archive_id,
                commit_id=receipt.commit_id,
                manifest_id=manifest.manifest_id,
                pipeline_id=pipeline_id,
                run_id=run_id,
                device_id=device_id,
                revision=1,
                created_at=created_at,
                artifacts=artifacts,
                projection_refs=projection_refs,
                cloud_bytes=sum(
                    item.size_bytes for item in manifest.items if not item.descriptor_only
                ),
            )
        except (TypeError, ValueError):
            return _pending("unsafe_projection")

        commit_key = (*owner, receipt.commit_id)
        key = (*owner, archive_id)
        with self._lock:
            existing_id = self._commit_index.get(commit_key)
            if existing_id is not None:
                existing = self._archives.get((*owner, existing_id))
                if existing is None:
                    return _pending("archive_already_deleted")
                if existing != record:
                    return _pending("archive_conflict")
                return _completed("archive_recorded", archives=(existing,))
            self._archives[key] = record
            self._commit_index[commit_key] = archive_id
            if run_id is not None:
                linked_run = self._analysis_runs.get((*owner, run_id))
                if linked_run is not None:
                    self._analysis_runs[(*owner, run_id)] = linked_run.model_copy(
                        update={"archive_id": archive_id, "archive_status": "committed"}
                    )
        return _completed("archive_recorded", archives=(record,))

    def get_archive(self, context: OwnerContext, archive_id: str) -> MediaBffOutcome:
        try:
            archive_id = _safe_id(archive_id)
        except ValueError:
            return _pending("invalid_archive_id")
        with self._lock:
            record = self._archives.get((*self._owner_key(context), archive_id))
        if record is None:
            return _pending("archive_not_found")
        return _completed("archive_found", archives=(record,))

    def list_archives(self, context: OwnerContext) -> MediaBffOutcome:
        owner = self._owner_key(context)
        with self._lock:
            records = tuple(
                value
                for key, value in sorted(self._archives.items())
                if key[:2] == owner
            )
        return _completed("archives_found", archives=records)

    def delete_archive(
        self, context: OwnerContext, archive_id: str, *, deleted_at: int
    ) -> MediaBffOutcome:
        if deleted_at < 0:
            return _pending("invalid_timestamp")
        try:
            archive_id = _safe_id(archive_id)
        except ValueError:
            return _pending("invalid_archive_id")
        owner = self._owner_key(context)
        key = (*owner, archive_id)
        with self._lock:
            prior = self._deletions.get(key)
            if prior is not None:
                return _completed("archive_deleted", delete_receipt=prior)
            record = self._archives.get(key)
            if record is None:
                return _pending("archive_not_found")
            receipt = ArchiveDeleteReceipt(
                deletion_id="deletion/" + sha256(
                    f"{context.tenant_id}\x00{context.owner_id}\x00{archive_id}".encode()
                ).hexdigest()[:32],
                archive_id=archive_id,
                commit_id=record.commit_id,
                artifact_hashes=tuple(item.sha256 for item in record.artifacts),
                projection_refs=record.projection_refs,
                deleted_at=deleted_at,
            )
            self._archives.pop(key)
            self._deletions[key] = receipt
            # Preserve the run projection while making the archive transition
            # explicit; this is the precise cascade required by the UI and
            # keeps business/job/analysis state independent.
            if record.run_id is not None:
                run_key = (*owner, record.run_id)
                linked_run = self._analysis_runs.get(run_key)
                if linked_run is not None and linked_run.archive_id == archive_id:
                    self._analysis_runs[run_key] = linked_run.model_copy(
                        update={"archive_status": "deleted"}
                    )
        return _completed("archive_deleted", delete_receipt=receipt)

    def get_delete_receipt(
        self, context: OwnerContext, archive_id: str
    ) -> MediaBffOutcome:
        try:
            archive_id = _safe_id(archive_id)
        except ValueError:
            return _pending("invalid_archive_id")
        with self._lock:
            receipt = self._deletions.get((*self._owner_key(context), archive_id))
        if receipt is None:
            return _pending("delete_receipt_not_found")
        return _completed("delete_receipt_found", delete_receipt=receipt)


__all__ = [
    "AnalysisOutputProjection",
    "AnalysisRunProjection",
    "ArchiveArtifactProjection",
    "ArchiveDeleteReceipt",
    "ArchiveRecord",
    "DeviceProjection",
    "MediaBff",
    "MediaBffOutcome",
    "OwnerContext",
    "PipelineProjection",
    "ProjectionRef",
    "RunProjection",
]
