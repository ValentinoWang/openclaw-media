from __future__ import annotations

import inspect

from openclaw_media.pipeline_runtime import PipelineRuntime


def test_runtime_has_no_injected_business_runner():
    signature = inspect.signature(PipelineRuntime.execute)
    assert "runner" not in signature.parameters
    assert "node_registry" in inspect.signature(PipelineRuntime).parameters
