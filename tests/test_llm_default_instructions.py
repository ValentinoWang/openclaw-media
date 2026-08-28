from __future__ import annotations

import inspect

from common.llm_client import DEFAULT_JSON_OUTPUT_INSTRUCTIONS, generate_json_from_parts, generate_json_once


def test_default_json_instructions_define_only_the_output_protocol() -> None:
    assert "JSON 引擎" not in DEFAULT_JSON_OUTPUT_INSTRUCTIONS
    assert "JSON engine" not in DEFAULT_JSON_OUTPUT_INSTRUCTIONS
    assert "合法 JSON object" in DEFAULT_JSON_OUTPUT_INSTRUCTIONS
    assert inspect.signature(generate_json_from_parts).parameters["instructions"].default == DEFAULT_JSON_OUTPUT_INSTRUCTIONS
    assert inspect.signature(generate_json_once).parameters["instructions"].default == DEFAULT_JSON_OUTPUT_INSTRUCTIONS
