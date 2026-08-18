"""The single durable runtime for installed OpenClaw Media pipelines."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import sqlite3
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict

from .catalog import CatalogError, InstalledCatalog, ordered_pipeline_nodes
from .node_registry import NodeExecutionError, NodeRegistry
from .node_sdk import OutputBoundaryError, validate_outputs
from .provider_adapter import ProviderAdapterError


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(raw.encode()).hexdigest()


def _artifact_ref(value: Any) -> str:
    if not isinstance(value, str) or "\\" in value or "://" in value or ":" in value:
        raise ValueError("invalid_artifact_ref")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("invalid_artifact_ref")
    return path.as_posix()


class ArtifactReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    artifact_ref: str
    mime_type: str
    size_bytes: int


class NodeReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str
    status: str
    output_names: tuple[str, ...] = ()
    artifacts: tuple[ArtifactReceipt, ...] = ()


class RuntimeReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    run_ref: str
    pipeline_id: str
    catalog_digest: str
    status: str
    completed_nodes: tuple[str, ...]
    node_receipts: tuple[NodeReceipt, ...]
    cloud_bytes: int = 0
    identity: str


class RuntimeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: str
    code: str
    receipt: RuntimeReceipt | None = None


class PipelineRuntime:
    def __init__(
        self,
        workspace: str | Path,
        catalog: InstalledCatalog | None = None,
        node_registry: NodeRegistry | None = None,
    ) -> None:
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "pipeline-runtime.sqlite3"
        self.catalog = catalog or InstalledCatalog()
        self.node_registry = node_registry or NodeRegistry(self.catalog)
        if self.node_registry.catalog.manifest.get("catalog_digest") != self.catalog.manifest.get("catalog_digest"):
            raise CatalogError("node registry catalog mismatch")
        with self._db() as db:
            db.executescript(
                """CREATE TABLE IF NOT EXISTS analysis_runs(
                    run_ref TEXT PRIMARY KEY, pipeline_id TEXT NOT NULL, version TEXT NOT NULL,
                    catalog_digest TEXT NOT NULL, inputs_json TEXT NOT NULL, input_identity TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS node_receipts(
                    run_ref TEXT NOT NULL, node_index INTEGER NOT NULL, node_id TEXT NOT NULL,
                    status TEXT NOT NULL, output_names_json TEXT NOT NULL,
                    output_descriptors_json TEXT NOT NULL,
                    PRIMARY KEY(run_ref,node_index)
                );"""
            )

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _valid_ref(ref: Any) -> bool:
        if not isinstance(ref, str) or not ref or "\\" in ref:
            return False
        path = PurePosixPath(ref)
        return not path.is_absolute() and path.as_posix() == ref and all(part not in {"", ".", ".."} for part in path.parts)

    def create_run(self, pipeline_id: str, version: str, digest: str, *, run_ref: str, inputs: Mapping[str, Any]) -> RuntimeOutcome:
        if not self._valid_ref(run_ref):
            return RuntimeOutcome(status="pending_manual", code="invalid_run_ref")
        try:
            pipeline = self.catalog.resolve(pipeline_id, version, digest)
        except (CatalogError, TypeError, ValueError):
            return RuntimeOutcome(status="pending_manual", code="catalog_rejected")
        required = pipeline.get("input_schema", {}).get("required", [])
        if not isinstance(inputs, Mapping) or any(key not in inputs for key in required):
            return RuntimeOutcome(status="pending_manual", code="invalid_inputs")
        try:
            encoded = json.dumps(dict(inputs), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return RuntimeOutcome(status="pending_manual", code="invalid_inputs")
        identity = _digest(dict(inputs))
        with self._db() as db:
            row = db.execute("SELECT status, pipeline_id, version, catalog_digest, input_identity FROM analysis_runs WHERE run_ref=?", (run_ref,)).fetchone()
            if row:
                if (row[1], row[2], row[3], row[4]) != (pipeline_id, version, digest, identity):
                    return RuntimeOutcome(status="pending_manual", code="idempotency_conflict")
                return RuntimeOutcome(status=str(row[0]), code="already_exists")
            db.execute("INSERT INTO analysis_runs VALUES (?,?,?,?,?,?,?)", (run_ref, pipeline_id, version, digest, encoded, identity, "created"))
        return RuntimeOutcome(status="created", code="ok")

    def _load(self, run_ref: str):
        with self._db() as db:
            run = db.execute("SELECT * FROM analysis_runs WHERE run_ref=?", (run_ref,)).fetchone()
            nodes = db.execute("SELECT * FROM node_receipts WHERE run_ref=? ORDER BY node_index", (run_ref,)).fetchall()
        return run, nodes

    def _stored_outputs(self, value: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        stored: dict[str, dict[str, Any]] = {}
        for name, descriptor in value.items():
            ref = _artifact_ref(descriptor.get("artifact_ref"))
            mime = descriptor.get("mime_type")
            size = descriptor.get("size_bytes")
            if not isinstance(mime, str) or not isinstance(size, int) or size < 0:
                raise OutputBoundaryError("invalid durable artifact descriptor")
            stored[name] = {"artifact_ref": ref, "mime_type": mime, "size_bytes": size, "cloud_bytes": 0}
        return stored

    def _for_validation(self, value: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        validated: dict[str, dict[str, Any]] = {}
        for name, descriptor in value.items():
            stored = dict(descriptor)
            ref = _artifact_ref(stored["artifact_ref"])
            stored["local_path"] = str(self.root / ref)
            validated[name] = stored
        return validated

    @staticmethod
    def _declarations(pipeline: Mapping[str, Any], node: Mapping[str, Any]) -> tuple[tuple[str, ...], list[Mapping[str, Any]]]:
        output_names = node.get("outputs")
        allowlist = pipeline.get("output_allowlist")
        if not isinstance(output_names, list) or any(not isinstance(name, str) for name in output_names):
            raise OutputBoundaryError("invalid node output contract")
        if not isinstance(allowlist, list):
            raise OutputBoundaryError("invalid output allowlist")
        names = tuple(sorted(output_names))
        declarations = [item for item in allowlist if isinstance(item, Mapping) and item.get("name") in names]
        if len(declarations) != len(names) or {item.get("name") for item in declarations} != set(names):
            raise OutputBoundaryError("invalid output allowlist")
        return names, declarations

    def _validated_stored_outputs(
        self,
        pipeline: Mapping[str, Any],
        node: Mapping[str, Any],
        receipt: sqlite3.Row,
    ) -> dict[str, dict[str, Any]]:
        names, declarations = self._declarations(pipeline, node)
        descriptors = json.loads(receipt["output_descriptors_json"])
        if not isinstance(descriptors, Mapping) or set(descriptors) != set(names):
            raise OutputBoundaryError("invalid durable artifact descriptors")
        output_names = json.loads(receipt["output_names_json"])
        if not isinstance(output_names, list) or tuple(sorted(output_names)) != names or any(not isinstance(name, str) for name in output_names):
            raise OutputBoundaryError("invalid durable output names")

        stored: dict[str, dict[str, Any]] = {}
        for name in names:
            descriptor = descriptors[name]
            if not isinstance(descriptor, Mapping) or set(descriptor) != {"artifact_ref", "mime_type", "size_bytes", "cloud_bytes"}:
                raise OutputBoundaryError("invalid durable artifact descriptor")
            ref = _artifact_ref(descriptor["artifact_ref"])
            mime = descriptor["mime_type"]
            size = descriptor["size_bytes"]
            cloud_bytes = descriptor["cloud_bytes"]
            if not isinstance(mime, str) or not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise OutputBoundaryError("invalid durable artifact descriptor")
            if not isinstance(cloud_bytes, int) or isinstance(cloud_bytes, bool) or cloud_bytes != 0:
                raise OutputBoundaryError("invalid durable artifact descriptor")
            path = (self.root / ref).resolve()
            try:
                path.relative_to(self.root.resolve())
                if not path.is_file() or path.stat().st_size != size:
                    raise OutputBoundaryError("missing durable artifact")
            except (OSError, ValueError):
                raise OutputBoundaryError("missing durable artifact")
            stored[name] = {"artifact_ref": ref, "mime_type": mime, "size_bytes": size, "cloud_bytes": 0}

        try:
            validate_outputs(declarations, self._for_validation(stored))
        except (OutputBoundaryError, KeyError, TypeError, ValueError):
            raise OutputBoundaryError("invalid durable artifact descriptor")
        return stored

    def _expected_nodes_for_receipt(self, run) -> tuple[dict[str, Any], ...]:
        try:
            if not all(isinstance(run[key], str) for key in ("pipeline_id", "version", "catalog_digest")):
                return ()
            pipeline = self.catalog.resolve(run["pipeline_id"], run["version"], run["catalog_digest"])
            return tuple(ordered_pipeline_nodes(pipeline))
        except Exception:
            return ()

    def _receipt(self, run, nodes, status: str | None = None) -> RuntimeReceipt:
        models: list[NodeReceipt] = []
        expected_nodes = self._expected_nodes_for_receipt(run)
        for item in nodes:
            try:
                index = item["node_index"]
                expected = expected_nodes[index] if isinstance(index, int) and 0 <= index < len(expected_nodes) else None
                node_status = item["status"] if item["status"] in {"succeeded", "pending_manual", "cancelled", "paused"} else "completion_unknown"
                if item["status"] == "running":
                    node_status = "completion_unknown"
                node_id = expected["node_id"] if expected and isinstance(expected.get("node_id"), str) else "unknown_node"
                artifacts: tuple[ArtifactReceipt, ...] = ()
                output_names: tuple[str, ...] = ()
                if expected and node_status == "succeeded":
                    pipeline = self.catalog.resolve(run["pipeline_id"], run["version"], run["catalog_digest"])
                    stored = self._validated_stored_outputs(pipeline, expected, item)
                    output_names = tuple(sorted(stored))
                    artifacts = tuple(
                        ArtifactReceipt(
                            artifact_ref=value["artifact_ref"],
                            mime_type=value["mime_type"],
                            size_bytes=value["size_bytes"],
                        )
                        for value in stored.values()
                    )
            except Exception:
                node_id = "unknown_node"
                node_status = "completion_unknown"
                output_names = ()
                try:
                    artifacts = ()
                except Exception:
                    artifacts = ()
            models.append(NodeReceipt(node_id=node_id, status=node_status, output_names=output_names, artifacts=artifacts))
        node_models = tuple(models)
        completed = tuple(item.node_id for item in node_models if item.status == "succeeded")
        run_ref = run["run_ref"] if isinstance(run["run_ref"], str) and self._valid_ref(run["run_ref"]) else "unknown_run"
        pipeline_id = run["pipeline_id"] if isinstance(run["pipeline_id"], str) else "unknown_pipeline"
        catalog_digest = run["catalog_digest"] if isinstance(run["catalog_digest"], str) else "unknown_catalog"
        final_status = status if status in {"created", "running", "paused", "cancelled", "pending_manual", "succeeded"} else run["status"] if run["status"] in {"created", "running", "paused", "cancelled", "pending_manual", "succeeded"} else "pending_manual"
        data = {"run_ref": run_ref, "pipeline_id": pipeline_id, "catalog_digest": catalog_digest, "status": final_status, "completed_nodes": completed, "node_receipts": [item.model_dump(mode="json") for item in node_models], "cloud_bytes": 0}
        return RuntimeReceipt(**data, identity=_digest(data))

    def _validate_succeeded_run(self, pipeline: Mapping[str, Any], nodes: list[sqlite3.Row]) -> None:
        expected_nodes = ordered_pipeline_nodes(pipeline)
        by_index = {item["node_index"]: item for item in nodes}
        if len(by_index) != len(expected_nodes) or set(by_index) != set(range(len(expected_nodes))):
            raise OutputBoundaryError("invalid durable node receipts")
        for index, node in enumerate(expected_nodes):
            item = by_index[index]
            if item["node_id"] != node["node_id"] or item["status"] != "succeeded":
                raise OutputBoundaryError("invalid durable node receipts")
            self._validated_stored_outputs(pipeline, node, item)

    def _set_status(self, ref: str, status: str) -> None:
        with self._db() as db:
            db.execute("UPDATE analysis_runs SET status=? WHERE run_ref=?", (status, ref))

    def pause(self, run_ref: str) -> RuntimeOutcome:
        run, nodes = self._load(run_ref)
        if not run:
            return RuntimeOutcome(status="pending_manual", code="unknown_run")
        if run["status"] in ("succeeded", "cancelled", "pending_manual"):
            return RuntimeOutcome(status=run["status"], code="not_paused", receipt=self._receipt(run, nodes))
        self._set_status(run_ref, "paused")
        run, nodes = self._load(run_ref)
        return RuntimeOutcome(status="paused", code="ok", receipt=self._receipt(run, nodes))

    def resume(self, run_ref: str) -> RuntimeOutcome:
        run, nodes = self._load(run_ref)
        if not run:
            return RuntimeOutcome(status="pending_manual", code="unknown_run")
        if run["status"] == "paused":
            self._set_status(run_ref, "created")
            return RuntimeOutcome(status="created", code="ok")
        return RuntimeOutcome(status=run["status"], code="not_paused", receipt=self._receipt(run, nodes))

    def cancel(self, run_ref: str) -> RuntimeOutcome:
        run, nodes = self._load(run_ref)
        if not run:
            return RuntimeOutcome(status="pending_manual", code="unknown_run")
        if run["status"] not in ("succeeded", "cancelled"):
            self._set_status(run_ref, "cancelled")
        run, nodes = self._load(run_ref)
        return RuntimeOutcome(status="cancelled", code="ok", receipt=self._receipt(run, nodes))

    def execute(self, run_ref: str, *, inputs: Mapping[str, Any]) -> RuntimeOutcome:
        run, nodes = self._load(run_ref)
        if not run:
            return RuntimeOutcome(status="pending_manual", code="unknown_run")
        receipt = self._receipt(run, nodes)
        if run["status"] == "succeeded":
            try:
                pipeline = self.catalog.resolve(run["pipeline_id"], run["version"], run["catalog_digest"])
                self._validate_succeeded_run(pipeline, nodes)
            except (CatalogError, json.JSONDecodeError, OSError, OutputBoundaryError, KeyError, TypeError, ValueError):
                self._set_status(run_ref, "pending_manual")
                run, nodes = self._load(run_ref)
                return RuntimeOutcome(status="pending_manual", code="stored_output_rejected", receipt=self._receipt(run, nodes))
            return RuntimeOutcome(status="succeeded", code="already_succeeded", receipt=receipt)
        if run["status"] in ("paused", "cancelled", "pending_manual"):
            return RuntimeOutcome(status=run["status"], code=run["status"], receipt=receipt)
        if _digest(dict(inputs)) != run["input_identity"]:
            return RuntimeOutcome(status="pending_manual", code="input_identity_mismatch", receipt=receipt)
        try:
            pipeline = self.catalog.resolve(run["pipeline_id"], run["version"], run["catalog_digest"])
            ordered_nodes = ordered_pipeline_nodes(pipeline)
        except (CatalogError, TypeError, ValueError):
            return RuntimeOutcome(status="pending_manual", code="catalog_rejected", receipt=receipt)

        completed_outputs: dict[str, dict[str, Any]] = {}
        for index, node in enumerate(ordered_nodes):
            existing = next((item for item in nodes if item["node_index"] == index), None)
            if existing and existing["status"] in ("completion_unknown", "running"):
                return RuntimeOutcome(status="pending_manual", code="node_completion_unknown", receipt=receipt)
            declarations = [item for item in pipeline.get("output_allowlist", []) if item.get("name") in node.get("outputs", [])]
            if existing and existing["status"] == "succeeded":
                try:
                    stored = self._validated_stored_outputs(pipeline, node, existing)
                except (json.JSONDecodeError, OSError, OutputBoundaryError, KeyError, TypeError, ValueError):
                    self._set_status(run_ref, "pending_manual")
                    run, nodes = self._load(run_ref)
                    return RuntimeOutcome(status="pending_manual", code="stored_output_rejected", receipt=self._receipt(run, nodes))
                completed_outputs[node["node_id"]] = stored
                continue
            node_inputs = dict(inputs)
            try:
                for dependency in node.get("depends_on", []):
                    for name, descriptor in completed_outputs[dependency].items():
                        if name in node_inputs:
                            raise ValueError("dependency output conflict")
                        node_inputs[name] = descriptor
            except (KeyError, TypeError, ValueError):
                self._set_status(run_ref, "pending_manual")
                run, nodes = self._load(run_ref)
                return RuntimeOutcome(status="pending_manual", code="stored_output_rejected", receipt=self._receipt(run, nodes))
            with self._db() as db:
                db.execute("INSERT OR REPLACE INTO node_receipts VALUES (?,?,?,?,?,?)", (run_ref, index, node["node_id"], "running", "[]", "{}"))
            context = {"run_ref": run_ref, "workspace_root": self.root, "inputs": dict(inputs), "artifacts": completed_outputs}
            try:
                produced = self.node_registry.execute(node, context)
                validate_outputs(declarations, produced)
                stored = self._stored_outputs(produced)
                names = tuple(sorted(stored))
                encoded_outputs = json.dumps(stored, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            except ProviderAdapterError:
                code = "provider_unavailable"
                with self._db() as db:
                    db.execute("UPDATE node_receipts SET status=? WHERE run_ref=? AND node_index=?", ("pending_manual", run_ref, index))
                    db.execute("UPDATE analysis_runs SET status=? WHERE run_ref=?", ("pending_manual", run_ref))
                run, nodes = self._load(run_ref)
                return RuntimeOutcome(status="pending_manual", code=code, receipt=self._receipt(run, nodes))
            except NodeExecutionError as exc:
                with self._db() as db:
                    db.execute("UPDATE node_receipts SET status=? WHERE run_ref=? AND node_index=?", ("pending_manual", run_ref, index))
                    db.execute("UPDATE analysis_runs SET status=? WHERE run_ref=?", ("pending_manual", run_ref))
                run, nodes = self._load(run_ref)
                return RuntimeOutcome(status="pending_manual", code=exc.code, receipt=self._receipt(run, nodes))
            except (OutputBoundaryError, KeyError, TypeError, ValueError):
                with self._db() as db:
                    db.execute("UPDATE node_receipts SET status=? WHERE run_ref=? AND node_index=?", ("pending_manual", run_ref, index))
                    db.execute("UPDATE analysis_runs SET status=? WHERE run_ref=?", ("pending_manual", run_ref))
                run, nodes = self._load(run_ref)
                return RuntimeOutcome(status="pending_manual", code="output_rejected", receipt=self._receipt(run, nodes))
            except Exception:
                with self._db() as db:
                    db.execute("UPDATE node_receipts SET status=? WHERE run_ref=? AND node_index=?", ("pending_manual", run_ref, index))
                    db.execute("UPDATE analysis_runs SET status=? WHERE run_ref=?", ("pending_manual", run_ref))
                run, nodes = self._load(run_ref)
                return RuntimeOutcome(status="pending_manual", code="node_failed", receipt=self._receipt(run, nodes))
            with self._db() as db:
                db.execute("UPDATE node_receipts SET status=?, output_names_json=?, output_descriptors_json=? WHERE run_ref=? AND node_index=?", ("succeeded", json.dumps(names), encoded_outputs, run_ref, index))
            completed_outputs[node["node_id"]] = stored
            run, nodes = self._load(run_ref)
            if run["status"] in ("paused", "cancelled"):
                return RuntimeOutcome(status=run["status"], code=run["status"], receipt=self._receipt(run, nodes))
        self._set_status(run_ref, "succeeded")
        run, nodes = self._load(run_ref)
        return RuntimeOutcome(status="succeeded", code="ok", receipt=self._receipt(run, nodes))


__all__ = ["ArtifactReceipt", "NodeReceipt", "PipelineRuntime", "RuntimeOutcome", "RuntimeReceipt"]
