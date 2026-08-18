"""Compatibility-free run command helpers for the canonical PipelineRuntime."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .pipeline_runtime import PipelineRuntime, RuntimeOutcome


def execute_descriptor(runtime: PipelineRuntime, pipeline_id: str, descriptor: Mapping[str, Any]) -> RuntimeOutcome:
    """Create and execute one descriptor through the supplied single runtime."""
    if descriptor.get("confirmed") is not True:
        return RuntimeOutcome(status="pending_manual", code="confirmation_required")
    required = {"version", "catalog_digest", "run_ref", "confirmed", "inputs"}
    if set(descriptor) != required or not isinstance(descriptor.get("inputs"), Mapping):
        return RuntimeOutcome(status="pending_manual", code="invalid_descriptor")
    created = runtime.create_run(
        pipeline_id,
        str(descriptor["version"]),
        str(descriptor["catalog_digest"]),
        run_ref=str(descriptor["run_ref"]),
        inputs=descriptor["inputs"],
    )
    if created.status == "pending_manual":
        return created
    return runtime.execute(str(descriptor["run_ref"]), inputs=descriptor["inputs"])


__all__ = ["execute_descriptor"]
