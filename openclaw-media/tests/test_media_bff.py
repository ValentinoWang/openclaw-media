import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from openclaw_media import (
    ArchiveItem,
    ArchiveManifest,
    ArchiveRegistry,
    Device,
    MediaBff,
    OwnerContext,
    ProjectionRef,
    RunProjection,
)


def committed_archive(tenant="tenant-a", owner="owner-a"):
    content = b'{"review":"ok"}'
    items = (
        ArchiveItem(
            ref="reports/review.json",
            mime_type="application/json",
            sha256=sha256(content).hexdigest(),
            size_bytes=len(content),
            content=content,
        ),
        ArchiveItem(
            ref="media/final.json",
            mime_type="application/json",
            sha256=sha256(b"final-local").hexdigest(),
            size_bytes=11,
            descriptor_only=True,
        ),
    )
    manifest = ArchiveManifest(
        manifest_id="manifest-012",
        tenant_id=tenant,
        owner_id=owner,
        items=items,
        quota_bytes=1024,
    )
    registry = ArchiveRegistry()
    assert registry.create_manifest(manifest).code == "manifest_accepted"
    outcome = registry.commit(tenant, owner, manifest.manifest_id)
    assert outcome.receipt is not None
    return manifest, outcome.receipt


def test_typed_pipeline_device_and_run_projections_are_public_safe():
    bff = MediaBff()
    context = OwnerContext(tenant_id="tenant-a", owner_id="owner-a")

    pipelines = bff.list_pipelines(context)
    assert pipelines.status == "completed" and len(pipelines.pipelines) == 9
    pipeline = pipelines.pipelines[0]
    assert pipeline.node_ids and pipeline.output_names

    device = Device(
        device_id="device/one",
        tenant_id="tenant-a",
        name="Editing Mac",
        revision=2,
        status="paired",
        last_heartbeat=120,
    )
    assert bff.record_device(context, device).code == "device_recorded"
    assert bff.list_devices(context).devices[0].model_dump() == {
        "device_id": "device/one",
        "name": "Editing Mac",
        "revision": 2,
        "status": "paired",
        "last_heartbeat": 120,
    }

    run = RunProjection(
        run_id="run/one",
        pipeline_id=pipeline.pipeline_id,
        device_id="device/one",
        revision=1,
        status="ready_to_archive",
        completed_nodes=pipeline.node_ids,
        artifact_refs=("reports/review.json",),
    )
    assert bff.record_run(context, run).code == "run_recorded"
    assert bff.list_runs(context).runs == (run,)

    payload = json.dumps(
        {
            "pipelines": pipelines.model_dump(mode="json"),
            "devices": bff.list_devices(context).model_dump(mode="json"),
            "runs": bff.list_runs(context).model_dump(mode="json"),
        },
        sort_keys=True,
    ).lower()
    assert all(
        forbidden not in payload
        for forbidden in (
            "/home/",
            "c:\\users",
            "authorization",
            "api_key",
            "raw_prompt",
            "endpoint_url",
            "content\"",
            "tenant_id",
            "owner_id",
        )
    )


def test_archive_readback_and_hard_delete_have_exact_idempotent_receipts():
    bff = MediaBff()
    context = OwnerContext(tenant_id="tenant-a", owner_id="owner-a")
    manifest, receipt = committed_archive()
    pipeline_id = bff.list_pipelines(context).pipelines[0].pipeline_id
    projection_ref = ProjectionRef(
        table_key="02B_MaterialDeconstructions",
        record_id="rec-012",
        owner_contract="material-deconstruction-owner-v1",
    )

    created = bff.record_archive(
        context,
        manifest,
        receipt,
        pipeline_id=pipeline_id,
        created_at=1000,
        run_id="run/one",
        device_id="device/one",
        projection_refs=(projection_ref,),
    )
    assert created.status == "completed" and created.code == "archive_recorded"
    record = created.archives[0]
    assert record.status == "active" and record.cloud_bytes == len(b'{"review":"ok"}')
    assert [item.archive_mode for item in record.artifacts] == [
        "content",
        "descriptor_only",
    ]
    assert "content" not in ArchiveItem.model_fields.keys() - {"content"}
    assert "content" not in record.model_dump()
    assert bff.get_archive(context, record.archive_id).archives == (record,)
    assert bff.record_archive(
        context,
        manifest,
        receipt,
        pipeline_id=pipeline_id,
        created_at=1000,
        run_id="run/one",
        device_id="device/one",
        projection_refs=(projection_ref,),
    ).archives == (record,)

    deleted = bff.delete_archive(context, record.archive_id, deleted_at=1100)
    delete_receipt = deleted.delete_receipt
    assert deleted.code == "archive_deleted" and delete_receipt is not None
    assert delete_receipt.archive_id == record.archive_id
    assert delete_receipt.artifact_hashes == tuple(item.sha256 for item in record.artifacts)
    assert delete_receipt.projection_refs == (projection_ref,)
    assert bff.delete_archive(context, record.archive_id, deleted_at=9999) == deleted
    assert bff.get_archive(context, record.archive_id).code == "archive_not_found"
    assert bff.list_archives(context).archives == ()
    assert bff.get_delete_receipt(context, record.archive_id).delete_receipt == delete_receipt


def test_owner_and_tenant_isolation_fail_closed_without_enumeration():
    bff = MediaBff()
    owner = OwnerContext(tenant_id="tenant-a", owner_id="owner-a")
    other_tenant = OwnerContext(tenant_id="tenant-b", owner_id="owner-a")
    other_owner = OwnerContext(tenant_id="tenant-a", owner_id="owner-b")
    manifest, receipt = committed_archive()
    pipeline_id = bff.list_pipelines(owner).pipelines[0].pipeline_id
    record = bff.record_archive(
        owner, manifest, receipt, pipeline_id=pipeline_id, created_at=1000
    ).archives[0]

    for context in (other_tenant, other_owner):
        assert bff.get_archive(context, record.archive_id).model_dump() == {
            "status": "pending_manual",
            "code": "archive_not_found",
            "pipelines": (),
            "devices": (),
            "runs": (),
            "archives": (),
            "delete_receipt": None,
        }
        assert bff.delete_archive(context, record.archive_id, deleted_at=1100).code == "archive_not_found"
        assert bff.list_archives(context).archives == ()

    wrong_device = Device(
        device_id="device/wrong",
        tenant_id="tenant-b",
        name="Other",
        revision=1,
        status="paired",
    )
    assert bff.record_device(owner, wrong_device).code == "tenant_forbidden"
    assert bff.list_devices(owner).devices == ()
    assert bff.get_archive(owner, record.archive_id).archives == (record,)


def test_unsafe_fields_and_revision_conflicts_are_stable_pending_manual_errors():
    bff = MediaBff()
    context = OwnerContext(tenant_id="tenant-a", owner_id="owner-a")
    pipeline_id = bff.list_pipelines(context).pipelines[0].pipeline_id
    run = RunProjection(
        run_id="run/one",
        pipeline_id=pipeline_id,
        revision=1,
        status="created",
    )
    assert bff.record_run(context, run).code == "run_recorded"
    conflict = run.model_copy(update={"status": "succeeded"})
    assert bff.record_run(context, conflict).model_dump()["code"] == "revision_conflict"
    assert bff.record_run(
        context, run.model_copy(update={"pipeline_id": "media.unknown.v1", "revision": 2})
    ).code == "pipeline_not_installed"

    with pytest.raises(ValidationError):
        RunProjection(
            run_id="/home/alice/private/run",
            pipeline_id=pipeline_id,
            revision=1,
            status="created",
        )
    with pytest.raises(ValidationError):
        RunProjection(
            run_id="run/two",
            pipeline_id=pipeline_id,
            revision=1,
            status="created",
            raw_prompt="secret",
        )
    with pytest.raises(ValidationError):
        ProjectionRef(
            table_key="02B",
            record_id="https://private.example/rec",
            owner_contract="owner-v1",
        )

    schema = bff.list_archives(context).model_json_schema()

    def property_names(value):
        if isinstance(value, dict):
            yield from value.get("properties", {}).keys()
            for child in value.values():
                yield from property_names(child)
        elif isinstance(value, list):
            for child in value:
                yield from property_names(child)

    names = set(property_names(schema))
    assert not names.intersection(
        {"raw_prompt", "endpoint_url", "credential", "local_path", "content"}
    )
