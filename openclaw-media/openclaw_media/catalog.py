from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping


class CatalogError(ValueError):
    """The requested pipeline is not in the installed immutable catalog."""


def ordered_pipeline_nodes(pipeline: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a stable topological order or reject a malformed packaged DAG."""
    nodes = pipeline.get("nodes", [])
    if not isinstance(nodes, list) or not nodes:
        raise CatalogError("invalid dependency graph")
    by_id: dict[str, dict[str, Any]] = {}
    for raw in nodes:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("node_id"), str):
            raise CatalogError("invalid dependency graph")
        node = dict(raw)
        node_id = node["node_id"]
        dependencies = node.get("depends_on", [])
        if node_id in by_id or not isinstance(dependencies, list) or len(dependencies) != len(set(dependencies)):
            raise CatalogError("invalid dependency graph")
        by_id[node_id] = node
    if any(not isinstance(dep, str) or dep not in by_id or dep == node_id for node_id, node in by_id.items() for dep in node.get("depends_on", [])):
        raise CatalogError("invalid dependency graph")
    pending = list(by_id)
    ordered: list[dict[str, Any]] = []
    completed: set[str] = set()
    while pending:
        ready = [node_id for node_id in pending if set(by_id[node_id].get("depends_on", [])) <= completed]
        if not ready:
            raise CatalogError("invalid dependency graph")
        for node_id in ready:
            ordered.append(deepcopy(by_id[node_id]))
            completed.add(node_id)
            pending.remove(node_id)
    return ordered


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def catalog_digest(pipelines: list[Mapping[str, Any]]) -> str:
    """Hash definitions while excluding the digest stamp itself."""
    definitions = []
    for pipeline in pipelines:
        item = deepcopy(dict(pipeline))
        item.pop("catalog_digest", None)
        definitions.append(item)
    definitions.sort(key=lambda item: (item["pipeline_id"], item["version"]))
    return "sha256:" + hashlib.sha256(_canonical_json(definitions)).hexdigest()


def build_projections(contract: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pipelines = deepcopy(contract["pipeline_catalog"])
    digest = catalog_digest(pipelines)
    for pipeline in pipelines:
        pipeline["catalog_digest"] = digest
    manifest = {
        "contract_id": contract["contract_id"],
        "contract_version": contract["version"],
        "catalog_digest": digest,
        "pipeline_count": len(pipelines),
        "pipelines": pipelines,
        "node_registry": deepcopy(contract["node_registry"]),
        "historical_capability_coverage": deepcopy(
            contract["historical_capability_coverage"]
        ),
    }
    web_catalog = {
        "catalog_digest": digest,
        "pipeline_count": len(pipelines),
        "pipelines": [
            {
                "pipeline_id": item["pipeline_id"],
                "version": item["version"],
                "name": item["display_name"],
                "description": item["description"],
                "catalog_digest": digest,
            }
            for item in pipelines
        ],
    }
    return manifest, web_catalog


def generate_data(contract_path: Path, data_dir: Path) -> str:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    manifest, web_catalog = build_projections(contract)
    data_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "pipeline-definition.schema.json": contract["pipeline_definition_schema"],
        "pipelines.json": manifest,
        "web-catalog.json": web_catalog,
    }
    for name, value in outputs.items():
        (data_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return manifest["catalog_digest"]


class InstalledCatalog:
    def __init__(self, manifest: Mapping[str, Any] | None = None) -> None:
        if manifest is None:
            path = files("openclaw_media").joinpath("data/pipelines.json")
            manifest = json.loads(path.read_text(encoding="utf-8"))
        self.manifest = deepcopy(dict(manifest))
        self._validate_manifest()

    def _validate_manifest(self) -> None:
        pipelines = self.manifest.get("pipelines", [])
        expected = catalog_digest(pipelines)
        if self.manifest.get("catalog_digest") != expected:
            raise CatalogError("installed catalog digest mismatch")
        if self.manifest.get("pipeline_count") != len(pipelines):
            raise CatalogError("installed pipeline count mismatch")
        if any(item.get("catalog_digest") != expected for item in pipelines):
            raise CatalogError("pipeline catalog digest mismatch")
        known_nodes = {item["node_type"] for item in self.manifest.get("node_registry", [])}
        for pipeline in pipelines:
            ordered_pipeline_nodes(pipeline)
            for node in pipeline.get("nodes", []):
                if node.get("type") not in known_nodes:
                    raise CatalogError(f"unknown node: {node.get('type')}")

    def resolve(self, pipeline_id: str, version: str, digest: str) -> dict[str, Any]:
        if digest != self.manifest["catalog_digest"]:
            raise CatalogError("requested catalog digest is not installed")
        matches = [
            item
            for item in self.manifest["pipelines"]
            if item["pipeline_id"] == pipeline_id and item["version"] == version
        ]
        if not matches:
            raise CatalogError("requested pipeline version is not installed")
        return deepcopy(matches[0])
