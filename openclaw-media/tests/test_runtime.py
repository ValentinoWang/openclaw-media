from __future__ import annotations

import json
import sqlite3

from openclaw_media import InstalledCatalog, NodeRegistry
from openclaw_media.pipeline_runtime import PipelineRuntime


def _pipeline(catalog: InstalledCatalog, index: int = 1):
    return catalog.manifest["pipelines"][index]


def _inputs():
    return {"workspace_ref": "media"}


def _create(runtime: PipelineRuntime, pipeline: dict, *, run_ref: str = "runs/demo"):
    return runtime.create_run(
        pipeline["pipeline_id"], pipeline["version"], pipeline["catalog_digest"], run_ref=run_ref, inputs=_inputs()
    )


def test_installed_pipeline_executes_once_and_receipt_survives_restart(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "clip.png").write_bytes(b"media")
    catalog = InstalledCatalog()
    pipeline = _pipeline(catalog)
    runtime = PipelineRuntime(tmp_path, catalog=catalog, node_registry=NodeRegistry(catalog))
    assert _create(runtime, pipeline).status == "created"

    first = runtime.execute("runs/demo", inputs=_inputs())
    reopened = PipelineRuntime(tmp_path, catalog=catalog, node_registry=NodeRegistry(catalog))
    second = reopened.execute("runs/demo", inputs=_inputs())

    assert first.status == "succeeded"
    assert second.code == "already_succeeded"
    assert first.receipt == second.receipt
    assert first.receipt.completed_nodes == ("organize",)
    artifact = first.receipt.node_receipts[0].artifacts[0]
    assert artifact.artifact_ref.startswith("artifacts/")
    assert str(tmp_path) not in first.model_dump_json()
    with sqlite3.connect(tmp_path / "pipeline-runtime.sqlite3") as db:
        raw = db.execute("SELECT output_descriptors_json FROM node_receipts").fetchone()[0]
    assert "local_path" not in raw


def test_unknown_catalog_digest_and_absolute_refs_fail_closed(tmp_path):
    catalog = InstalledCatalog()
    pipeline = _pipeline(catalog)
    runtime = PipelineRuntime(tmp_path, catalog=catalog, node_registry=NodeRegistry(catalog))
    assert runtime.create_run(pipeline["pipeline_id"], pipeline["version"], "sha256:" + "0" * 64, run_ref="runs/bad", inputs=_inputs()).code == "catalog_rejected"
    assert runtime.create_run(pipeline["pipeline_id"], pipeline["version"], pipeline["catalog_digest"], run_ref="/private/run", inputs=_inputs()).code == "invalid_run_ref"


def test_cancel_and_crash_are_explicit_and_never_reexecute_side_effect(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "clip.png").write_bytes(b"media")
    catalog = InstalledCatalog()
    pipeline = _pipeline(catalog)
    runtime = PipelineRuntime(tmp_path, catalog=catalog, node_registry=NodeRegistry(catalog))
    _create(runtime, pipeline, run_ref="runs/cancel")
    assert runtime.cancel("runs/cancel").status == "cancelled"
    assert runtime.execute("runs/cancel", inputs=_inputs()).code == "cancelled"

    _create(runtime, pipeline, run_ref="runs/crash")
    with sqlite3.connect(tmp_path / "pipeline-runtime.sqlite3") as db:
        db.execute("INSERT INTO node_receipts VALUES (?,?,?,?,?,?)", ("runs/crash", 0, "organize", "running", "[]", "{}"))
    crashed = runtime.execute("runs/crash", inputs=_inputs())
    assert (crashed.status, crashed.code) == ("pending_manual", "node_completion_unknown")
