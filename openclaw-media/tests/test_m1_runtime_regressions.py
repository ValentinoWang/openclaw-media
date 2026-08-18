from __future__ import annotations

import json
import sqlite3

import pytest

from openclaw_media import InstalledCatalog, NodeRegistry
from openclaw_media.pipeline_runtime import PipelineRuntime


def _pipeline(catalog: InstalledCatalog) -> dict:
    return catalog.manifest["pipelines"][1]


def _inputs() -> dict[str, str]:
    return {"workspace_ref": "media"}


def _runtime(tmp_path, registry: NodeRegistry | None = None) -> tuple[PipelineRuntime, dict]:
    media = tmp_path / "media"
    media.mkdir()
    (media / "clip.png").write_bytes(b"media")
    catalog = InstalledCatalog()
    return PipelineRuntime(tmp_path, catalog=catalog, node_registry=registry or NodeRegistry(catalog)), _pipeline(catalog)


def _create(runtime: PipelineRuntime, pipeline: dict, run_ref: str) -> None:
    outcome = runtime.create_run(
        pipeline["pipeline_id"], pipeline["version"], pipeline["catalog_digest"],
        run_ref=run_ref, inputs=_inputs(),
    )
    assert (outcome.status, outcome.code) == ("created", "ok")


@pytest.mark.parametrize(
    "corrupt_descriptors",
    [
        "not-json",
        "null",
        json.dumps({"organization_plan": {"artifact_ref": "artifacts/missing/organization_plan.json", "mime_type": "application/json", "size_bytes": 2}}),
    ],
)
def test_succeeded_run_with_corrupt_stored_output_fails_closed(tmp_path, corrupt_descriptors):
    runtime, pipeline = _runtime(tmp_path)
    _create(runtime, pipeline, "runs/corrupt")
    assert runtime.execute("runs/corrupt", inputs=_inputs()).status == "succeeded"
    with sqlite3.connect(tmp_path / "pipeline-runtime.sqlite3") as db:
        db.execute("UPDATE node_receipts SET output_descriptors_json=? WHERE run_ref=?", (corrupt_descriptors, "runs/corrupt"))
    reopened = PipelineRuntime(tmp_path, catalog=runtime.catalog, node_registry=NodeRegistry(runtime.catalog))
    outcome = reopened.execute("runs/corrupt", inputs=_inputs())
    assert (outcome.status, outcome.code) == ("pending_manual", "stored_output_rejected")


def test_run_ref_idempotency_rejects_conflicting_inputs(tmp_path):
    runtime, pipeline = _runtime(tmp_path)
    _create(runtime, pipeline, "runs/idempotent")
    same = runtime.create_run(pipeline["pipeline_id"], pipeline["version"], pipeline["catalog_digest"], run_ref="runs/idempotent", inputs=_inputs())
    conflict = runtime.create_run(pipeline["pipeline_id"], pipeline["version"], pipeline["catalog_digest"], run_ref="runs/idempotent", inputs={"workspace_ref": "other-media"})
    assert same.code == "already_exists"
    assert (conflict.status, conflict.code) == ("pending_manual", "idempotency_conflict")


class _ExplodingRegistry(NodeRegistry):
    def __init__(self, catalog: InstalledCatalog) -> None:
        super().__init__(catalog)
        self.calls = 0

    def execute(self, node, context):
        self.calls += 1
        raise RuntimeError("secret-canary raw-provider-payload")


def test_failed_node_is_not_retried_and_receipt_is_redacted(tmp_path):
    catalog = InstalledCatalog()
    registry = _ExplodingRegistry(catalog)
    runtime, pipeline = _runtime(tmp_path, registry)
    _create(runtime, pipeline, "runs/failure")
    first = runtime.execute("runs/failure", inputs=_inputs())
    second = runtime.execute("runs/failure", inputs=_inputs())
    serialized = first.model_dump_json() + second.model_dump_json()
    assert (first.status, first.code) == ("pending_manual", "node_failed")
    assert (second.status, second.code) == ("pending_manual", "pending_manual")
    assert registry.calls == 1
    assert "secret-canary" not in serialized
    assert "raw-provider-payload" not in serialized
    assert str(tmp_path) not in serialized
