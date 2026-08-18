"""Typed, public-safe page projections for the Media Web control plane."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .media_bff import MediaBffOutcome


class _PageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class PipelineCard(_PageModel):
    pipeline_id: str
    version: str
    catalog_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    display_name: str
    description: str
    min_cli_version: str
    node_ids: tuple[str, ...]
    output_names: tuple[str, ...]
    model_modalities: tuple[str, ...]


class PipelinesPage(_PageModel):
    route: Literal["/pipelines"] = "/pipelines"
    status: Literal["ready", "pending_manual"]
    code: str
    catalog_digest: str | None = None
    pipelines: tuple[PipelineCard, ...] = ()


class DeviceCard(_PageModel):
    device_id: str
    name: str
    revision: int = Field(ge=1)
    status: Literal["paired", "revoked"]
    last_heartbeat: int | None = Field(default=None, ge=0)
    configuration_hint: Literal["在 Local CLI 中配置"] = "在 Local CLI 中配置"
    provider_health_hint: Literal["在 Local CLI 中查看"] = "在 Local CLI 中查看"


class DevicesPage(_PageModel):
    route: Literal["/devices"] = "/devices"
    status: Literal["ready", "pending_manual"]
    code: str
    devices: tuple[DeviceCard, ...] = ()


class AnalysisOutputView(_PageModel):
    ref: str
    mime_type: str
    archive_selected: bool
    availability: Literal["仅本地", "可归档"]
    archived_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # A thumbnail is shown only when the BFF identifies an actual image
    # artifact.  We never manufacture a placeholder or expose a local path.
    thumbnail_ref: str | None = None


class AnalysisRunView(_PageModel):
    run_id: str
    pipeline_id: str
    revision: int
    business_status: str
    job_status: str
    analysis_status: str
    archive_status: str
    completed_nodes: tuple[str, ...]
    outputs: tuple[AnalysisOutputView, ...]
    archive_id: str | None = None
    local_run_id: str
    business_status_label: str
    job_status_label: str
    analysis_status_label: str
    archive_status_label: str


class AnalysisRunsPage(_PageModel):
    route: Literal["/analysis-runs"] = "/analysis-runs"
    status: Literal["ready", "pending_manual"]
    code: str
    runs: tuple[AnalysisRunView, ...] = ()


class AnalysisRunDetailPage(_PageModel):
    route: Literal["/analysis-runs/:id"] = "/analysis-runs/:id"
    status: Literal["ready", "pending_manual"]
    code: str
    run: AnalysisRunView | None = None


class ArchiveView(_PageModel):
    archive_id: str
    commit_id: str
    run_id: str | None
    status: str
    artifact_hashes: tuple[str, ...]


class DeletionReceiptView(_PageModel):
    deletion_id: str
    archive_id: str
    commit_id: str
    artifact_hashes: tuple[str, ...]
    deleted_at: int


class ArchivesPage(_PageModel):
    route: Literal["/archives"] = "/archives"
    status: Literal["ready", "pending_manual"]
    code: str
    archives: tuple[ArchiveView, ...] = ()
    deletion_receipts: tuple[DeletionReceiptView, ...] = ()


class TenantWebProjection(_PageModel):
    """Single page-facing bundle from the authenticated tenant BFF."""

    primary: MediaBffOutcome
    archive: MediaBffOutcome | None = None


_STATUS_ZH = {
    "created": "已创建", "validating": "校验中", "preprocessing": "预处理中",
    "analyzing": "分析中", "rendering": "渲染中", "reviewing": "审查中",
    "ready_to_archive": "待归档", "draft": "草稿", "processing": "处理中", "ready": "待归档",
    "archived": "已归档", "failed": "失败", "running": "运行中",
    "succeeded": "已完成", "selected": "已选择", "committed": "已归档",
    "not_selected": "未选择", "deleted": "已删除", "cancelled": "已取消",
}


class LegacyPage(_PageModel):
    route: str
    status: Literal["ready", "pending_manual"]
    code: str
    runs: tuple[AnalysisRunView, ...] = ()
    archives: tuple[ArchiveView, ...] = ()
    status_labels: tuple[str, ...] = ()
    # Shared typed projection used by all seven legacy routes.
    local_runs: tuple[AnalysisRunView, ...] = ()
    archive_evidence: tuple[ArchiveView, ...] = ()
    assets: tuple[AnalysisOutputView, ...] = ()


class OverviewPage(LegacyPage):
    route: Literal["/overview"] = "/overview"


class TracksPage(LegacyPage):
    route: Literal["/tracks"] = "/tracks"


class AssetsPage(LegacyPage):
    route: Literal["/assets"] = "/assets"


class RunsPage(LegacyPage):
    route: Literal["/runs"] = "/runs"


class RunDetailPage(LegacyPage):
    route: Literal["/runs/:id"] = "/runs/:id"


class PublishingPage(LegacyPage):
    route: Literal["/publishing"] = "/publishing"


class ReviewsPage(LegacyPage):
    route: Literal["/reviews"] = "/reviews"


def _page_status(outcome: MediaBffOutcome) -> Literal["ready", "pending_manual"]:
    return "ready" if outcome.status == "completed" else "pending_manual"


def render_pipelines(outcome: MediaBffOutcome) -> PipelinesPage:
    """Render only catalog fields supplied by the typed tenant BFF."""
    cards = tuple(PipelineCard.model_validate(item.model_dump()) for item in outcome.pipelines)
    digests = {item.catalog_digest for item in cards}
    if len(digests) > 1:
        return PipelinesPage(status="pending_manual", code="catalog_digest_conflict")
    return PipelinesPage(
        status=_page_status(outcome),
        code=outcome.code,
        catalog_digest=next(iter(digests), None),
        pipelines=cards if outcome.status == "completed" else (),
    )


def render_devices(outcome: MediaBffOutcome) -> DevicesPage:
    """Render paired-device state without credentials, commands, or health secrets."""
    cards = tuple(DeviceCard.model_validate(item.model_dump()) for item in outcome.devices)
    return DevicesPage(
        status=_page_status(outcome),
        code=outcome.code,
        devices=cards if outcome.status == "completed" else (),
    )


def _run_view(run, archive=None) -> AnalysisRunView:
    hashes = {item.ref: item.sha256 for item in archive.artifacts} if archive else {}
    outputs = tuple(
        AnalysisOutputView(
            ref=item.ref,
            mime_type=item.mime_type,
            archive_selected=item.archive_selected,
            availability="仅本地" if item.mime_type.startswith("video/") else "可归档",
            archived_sha256=hashes.get(item.ref),
            thumbnail_ref=item.ref if item.mime_type.startswith("image/") else None,
        )
        for item in getattr(run, "outputs", ())
    )
    # RunProjection is the older summary shape; normalize it into the same
    # tenant-owned view instead of maintaining a second renderer.
    if hasattr(run, "business_status"):
        values = run.model_dump(exclude={
            "device_id", "job_id", "outputs", "business_status",
            "job_status", "analysis_status", "archive_status",
        })
        business_status = run.business_status
        job_status = run.job_status
        analysis_status = run.analysis_status
        archive_status = run.archive_status
        job_id = run.job_id
    else:
        values = {
            "run_id": run.run_id,
            "pipeline_id": run.pipeline_id,
            "revision": run.revision,
            "completed_nodes": run.completed_nodes,
            "archive_id": run.archive_id,
        }
        business_status = run.status
        job_status = "succeeded" if run.status == "succeeded" else "not_scheduled"
        analysis_status = "ready" if run.status in {"ready_to_archive", "succeeded"} else run.status
        archive_status = "committed" if run.archive_id else "not_selected"
        job_id = None
    return AnalysisRunView(
        **values,
        outputs=outputs,
        local_run_id=run.run_id,
        business_status=business_status,
        job_status=job_status,
        analysis_status=analysis_status,
        archive_status=archive_status,
        business_status_label=_STATUS_ZH.get(business_status, "待人工处理"),
        job_status_label=_STATUS_ZH.get(job_status, "待人工处理"),
        analysis_status_label=_STATUS_ZH.get(analysis_status, "待人工处理"),
        archive_status_label=_STATUS_ZH.get(archive_status, "待人工处理"),
    )


def render_analysis_runs(outcome: MediaBffOutcome) -> AnalysisRunsPage:
    runs = tuple(_run_view(run) for run in outcome.analysis_runs)
    return AnalysisRunsPage(status=_page_status(outcome), code=outcome.code, runs=runs if outcome.status == "completed" else ())


def render_analysis_run_detail(run_outcome: MediaBffOutcome, archive_outcome: MediaBffOutcome | None = None) -> AnalysisRunDetailPage:
    if run_outcome.status != "completed" or len(run_outcome.analysis_runs) != 1:
        return AnalysisRunDetailPage(status="pending_manual", code=run_outcome.code)
    run = run_outcome.analysis_runs[0]
    archive = None
    if run.archive_id is not None:
        matches = () if archive_outcome is None or archive_outcome.status != "completed" else tuple(item for item in archive_outcome.archives if item.archive_id == run.archive_id and item.run_id == run.run_id)
        if len(matches) != 1:
            return AnalysisRunDetailPage(status="pending_manual", code="archive_evidence_missing")
        archive = matches[0]
    return AnalysisRunDetailPage(status="ready", code=run_outcome.code, run=_run_view(run, archive))


def render_archives(outcome: MediaBffOutcome, receipt_outcomes: tuple[MediaBffOutcome, ...] = ()) -> ArchivesPage:
    if outcome.status != "completed" or any(item.status != "completed" or item.delete_receipt is None for item in receipt_outcomes):
        return ArchivesPage(status="pending_manual", code=outcome.code)
    archives = tuple(ArchiveView(archive_id=item.archive_id, commit_id=item.commit_id, run_id=item.run_id, status=item.status, artifact_hashes=tuple(artifact.sha256 for artifact in item.artifacts)) for item in outcome.archives)
    receipts = tuple(DeletionReceiptView(**item.delete_receipt.model_dump(exclude={"projection_refs", "result"})) for item in receipt_outcomes)
    return ArchivesPage(status="ready", code=outcome.code, archives=archives, deletion_receipts=receipts)


def _legacy_page(page_type, outcome: MediaBffOutcome | TenantWebProjection, archive_outcome: MediaBffOutcome | None = None):
    if isinstance(outcome, TenantWebProjection):
        archive_outcome = outcome.archive
        outcome = outcome.primary
    runs = tuple(_run_view(run) for run in outcome.runs) + tuple(_run_view(run) for run in outcome.analysis_runs)
    archives = tuple(ArchiveView(archive_id=item.archive_id, commit_id=item.commit_id, run_id=item.run_id, status=item.status, artifact_hashes=tuple(a.sha256 for a in item.artifacts)) for item in (archive_outcome.archives if archive_outcome and archive_outcome.status == "completed" else outcome.archives))
    labels = tuple(dict.fromkeys(_STATUS_ZH.get(value, "待人工处理") for run in runs for value in (run.business_status, run.job_status, run.analysis_status, run.archive_status)))
    visible_runs = runs if outcome.status == "completed" else ()
    visible_archives = archives if outcome.status == "completed" else ()
    assets = tuple(output for run in visible_runs for output in run.outputs)
    return page_type(
        status=_page_status(outcome), code=outcome.code,
        runs=visible_runs, archives=visible_archives, status_labels=labels,
        local_runs=visible_runs, archive_evidence=visible_archives, assets=assets,
    )


def render_overview(outcome: MediaBffOutcome, archive_outcome: MediaBffOutcome | None = None) -> OverviewPage:
    return _legacy_page(OverviewPage, outcome, archive_outcome)


def render_tracks(outcome: MediaBffOutcome, archive_outcome: MediaBffOutcome | None = None) -> TracksPage:
    return _legacy_page(TracksPage, outcome, archive_outcome)


def render_assets(outcome: MediaBffOutcome, archive_outcome: MediaBffOutcome | None = None) -> AssetsPage:
    return _legacy_page(AssetsPage, outcome, archive_outcome)


def render_runs(outcome: MediaBffOutcome, archive_outcome: MediaBffOutcome | None = None) -> RunsPage:
    return _legacy_page(RunsPage, outcome, archive_outcome)


def render_run_detail(outcome: MediaBffOutcome | TenantWebProjection, archive_outcome: MediaBffOutcome | None = None) -> RunDetailPage:
    return _legacy_page(RunDetailPage, outcome, archive_outcome)


def render_publishing(outcome: MediaBffOutcome, archive_outcome: MediaBffOutcome | None = None) -> PublishingPage:
    return _legacy_page(PublishingPage, outcome, archive_outcome)


def render_reviews(outcome: MediaBffOutcome, archive_outcome: MediaBffOutcome | None = None) -> ReviewsPage:
    return _legacy_page(ReviewsPage, outcome, archive_outcome)


__all__ = ["AnalysisRunDetailPage", "AnalysisRunsPage", "ArchivesPage", "AssetsPage", "DeviceCard", "DevicesPage", "OverviewPage", "PipelineCard", "PipelinesPage", "PublishingPage", "RunDetailPage", "RunsPage", "ReviewsPage", "TenantWebProjection", "TracksPage", "render_analysis_run_detail", "render_analysis_runs", "render_archives", "render_assets", "render_devices", "render_overview", "render_pipelines", "render_publishing", "render_run_detail", "render_runs", "render_reviews", "render_tracks"]
