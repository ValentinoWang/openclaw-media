import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from openclaw_media import AnalysisOutputProjection, AnalysisRunProjection, ArchiveItem, ArchiveManifest, ArchiveReceipt, DeviceProjection, MediaBff, OwnerContext, PipelineProjection
from openclaw_media.web_pages import (
    DevicesPage, PipelinesPage, render_analysis_run_detail, render_analysis_runs,
    render_archives, render_assets, render_devices, render_overview, render_pipelines,
    render_publishing, render_reviews, render_run_detail, render_runs, render_tracks,
    TenantWebProjection,
)


def test_pipeline_page_is_catalog_typed_and_complete():
    outcome = MediaBff().list_pipelines(OwnerContext(tenant_id="tenant-a", owner_id="owner-a"))
    page = render_pipelines(outcome)
    assert page.route == "/pipelines" and page.status == "ready"
    assert len(page.pipelines) == 9
    assert page.catalog_digest and all(card.node_ids and card.output_names for card in page.pipelines)


def test_device_page_has_local_cli_guidance_without_credential_controls():
    bff = MediaBff()
    context = OwnerContext(tenant_id="tenant-a", owner_id="owner-a")
    bff.record_device(context, type("D", (), {"tenant_id": "tenant-a", "device_id": "mac/1", "name": "Mac", "revision": 1, "status": "paired", "last_heartbeat": 10})())
    # DeviceProjection is the only accepted page input; no API-key or command fields exist.
    page = render_devices(bff.list_devices(context))
    assert page.route == "/devices" and page.devices[0].configuration_hint == "在 Local CLI 中配置"
    assert page.devices[0].provider_health_hint == "在 Local CLI 中查看"
    payload = json.dumps(page.model_dump(), ensure_ascii=False).lower()
    assert all(x not in payload for x in ("api_key", "credential", "shell", "download", "/home/"))


def test_pending_or_cross_tenant_outcome_never_leaks_cards():
    page = render_devices(MediaBff().list_devices(OwnerContext(tenant_id="tenant-b", owner_id="owner-b")))
    assert page.status == "ready" and page.devices == ()
    pending = render_pipelines(type("O", (), {"status": "pending_manual", "code": "tenant_forbidden", "pipelines": ()})())
    assert pending.status == "pending_manual" and pending.pipelines == ()


def test_page_schemas_reject_runtime_fixture_and_secrets():
    with pytest.raises(ValidationError):
        PipelinesPage(route="/pipelines", status="ready", code="ok", pipelines=({"pipeline_id": "x", "version": "1", "catalog_digest": "sha256:" + "0" * 64, "display_name": "x", "description": "x", "node_ids": (), "output_names": (), "model_modalities": (), "local_path": "/home/x"},))
    names = set(PipelinesPage.model_json_schema().get("properties", {})) | set(DevicesPage.model_json_schema().get("properties", {}))
    assert not names.intersection({"api_key", "credential", "shell", "download_url", "local_path"})


def test_analysis_pages_separate_states_and_keep_video_local_only():
    bff = MediaBff()
    context = OwnerContext(tenant_id="tenant-a", owner_id="owner-a")
    pipeline_id = bff.list_pipelines(context).pipelines[0].pipeline_id
    run = AnalysisRunProjection(run_id="run/a", pipeline_id=pipeline_id, revision=1, business_status="processing", job_id="job/a", job_status="running", analysis_status="ready", archive_status="selected", completed_nodes=("node/a",), outputs=(AnalysisOutputProjection(ref="outputs/final.mp4", mime_type="video/mp4", archive_selected=True),))
    bff.record_analysis_run(context, run)
    page = render_analysis_runs(bff.list_analysis_runs(context))
    assert (page.runs[0].business_status, page.runs[0].job_status, page.runs[0].analysis_status, page.runs[0].archive_status) == ("processing", "running", "ready", "selected")
    assert page.runs[0].outputs[0].availability == "仅本地"
    payload = json.dumps(page.model_dump(), ensure_ascii=False).lower()
    assert all(word not in payload for word in ("play", "download", "local_path", "/home/", "api_key"))


def test_analysis_detail_fails_closed_without_matching_archive_evidence():
    bff = MediaBff()
    context = OwnerContext(tenant_id="tenant-a", owner_id="owner-a")
    pipeline_id = bff.list_pipelines(context).pipelines[0].pipeline_id
    run = AnalysisRunProjection(run_id="run/a", pipeline_id=pipeline_id, revision=1, business_status="archived", job_id="job/a", job_status="succeeded", analysis_status="ready", archive_status="committed", archive_id="archive/missing")
    bff.record_analysis_run(context, run)
    assert render_analysis_run_detail(bff.get_analysis_run(context, "run/a")).code == "archive_evidence_missing"
    assert render_analysis_runs(bff.list_analysis_runs(OwnerContext(tenant_id="tenant-b", owner_id="owner-b"))).runs == ()


def test_archive_links_are_owner_scoped_and_delete_cascades_exactly():
    bff = MediaBff()
    context = OwnerContext(tenant_id="tenant-a", owner_id="owner-a")
    pipeline_id = bff.list_pipelines(context).pipelines[0].pipeline_id
    run = AnalysisRunProjection(
        run_id="run/archive", pipeline_id=pipeline_id, revision=1,
        business_status="ready", job_id="job/archive", job_status="succeeded", analysis_status="ready",
        archive_status="selected",
        outputs=(AnalysisOutputProjection(ref="reports/result.json", mime_type="application/json", archive_selected=True),),
    )
    bff.record_analysis_run(context, run)
    item = ArchiveItem(ref="reports/result.json", mime_type="application/json", sha256=sha256(b"{}").hexdigest(), size_bytes=2, content=b"{}")
    manifest = ArchiveManifest(manifest_id="manifest-a", tenant_id="tenant-a", owner_id="owner-a", items=(item,), quota_bytes=10)
    receipt = ArchiveReceipt(commit_id="commit-a", manifest_id="manifest-a", tenant_id="tenant-a", owner_id="owner-a", item_refs=(item.ref,), total_bytes=2)
    archived = bff.record_archive(context, manifest, receipt, pipeline_id=pipeline_id, run_id=run.run_id, created_at=1)
    archive_id = archived.archives[0].archive_id
    assert bff.get_archive(OwnerContext(tenant_id="tenant-b", owner_id="owner-b"), archive_id).code == "archive_not_found"
    deleted = bff.delete_archive(context, archive_id, deleted_at=2)
    assert deleted.delete_receipt and deleted.delete_receipt.artifact_hashes == (item.sha256,)
    linked = bff.get_analysis_run(context, run.run_id).analysis_runs[0]
    assert linked.archive_status == "deleted"
    page = render_archives(bff.list_archives(context), (deleted,))
    assert page.archives == () and page.deletion_receipts[0].archive_id == archive_id


def test_u15_seven_pages_share_typed_projection_and_local_archive_evidence():
    bff = MediaBff()
    context = OwnerContext(tenant_id="tenant-a", owner_id="owner-a")
    pipeline_id = bff.list_pipelines(context).pipelines[0].pipeline_id
    run = AnalysisRunProjection(
        run_id="run/u15", pipeline_id=pipeline_id, revision=2,
        business_status="archived", job_id="job/u15", job_status="succeeded",
        analysis_status="ready", archive_status="committed", archive_id="archive/u15",
        completed_nodes=("extract",),
        outputs=(
            AnalysisOutputProjection(ref="thumb.jpg", mime_type="image/jpeg", archive_selected=True),
            AnalysisOutputProjection(ref="final.mp4", mime_type="video/mp4", archive_selected=False),
        ),
    )
    bff.record_analysis_run(context, run)
    image = ArchiveItem(ref="thumb.jpg", mime_type="image/jpeg", sha256=sha256(b"thumb").hexdigest(), size_bytes=5, content=b"thumb")
    manifest = ArchiveManifest(manifest_id="manifest/u15", tenant_id="tenant-a", owner_id="owner-a", items=(image,), quota_bytes=10)
    receipt = ArchiveReceipt(commit_id="commit/u15", manifest_id="manifest/u15", tenant_id="tenant-a", owner_id="owner-a", item_refs=(image.ref,), total_bytes=5)
    archive_outcome = bff.record_archive(context, manifest, receipt, pipeline_id=pipeline_id, run_id=run.run_id, created_at=3)

    outcome = bff.list_analysis_runs(context)
    projection = TenantWebProjection(primary=outcome, archive=archive_outcome)
    pages = (
        render_overview(projection), render_tracks(projection), render_assets(projection),
        render_runs(projection), render_run_detail(outcome, archive_outcome),
        render_publishing(projection), render_reviews(projection),
    )
    assert {page.route for page in pages} == {"/overview", "/tracks", "/assets", "/runs", "/runs/:id", "/publishing", "/reviews"}
    for page in pages:
        assert page.local_runs[0].local_run_id == "run/u15"
        assert page.local_runs[0].business_status_label == "已归档"
        assert page.archive_evidence[0].artifact_hashes == (image.sha256,)
        assert "待读取" not in json.dumps(page.model_dump(), ensure_ascii=False)
        payload = json.dumps(page.model_dump(), ensure_ascii=False).lower()
        assert all(secret not in payload for secret in ("/home/", "api_key", "credential", "download"))
    assets = render_assets(outcome, archive_outcome).assets
    assert assets[0].thumbnail_ref == "thumb.jpg" and assets[1].availability == "仅本地"
