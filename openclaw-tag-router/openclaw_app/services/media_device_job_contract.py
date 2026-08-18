"""The R1 HTTP surface is projected from the canonical generated media client."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping


CANONICAL_GENERATED_CONTRACT = Path("/home/ubuntu/selfmedia-tools/media-agent-cli/generated_product_contract.py")
FROZEN_CONTRACT = Path("/home/ubuntu/docs/ai-harness/openclaw-media-product-contract.json")


def _load_generated_contract() -> ModuleType:
    if not CANONICAL_GENERATED_CONTRACT.is_file():
        raise RuntimeError(f"canonical generated media contract is missing: {CANONICAL_GENERATED_CONTRACT}")
    spec = importlib.util.spec_from_file_location("openclaw_media_generated_product_contract", CANONICAL_GENERATED_CONTRACT)
    if spec is None or spec.loader is None:
        raise RuntimeError("canonical generated media contract cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_GENERATED = _load_generated_contract()
OPERATIONS: Mapping[str, Mapping[str, Any]] = _GENERATED.OPERATIONS
PATH_PARAMETERS: Mapping[str, tuple[str, ...]] = _GENERATED.PATH_PARAMETERS
_R2_OPERATION_IDS = frozenset({"archive_commit", "archive_list", "archive_detail", "archive_delete_plan", "archive_delete", "archive_readback"})
R1_OPERATION_IDS = tuple(operation_id for operation_id in OPERATIONS if operation_id not in _R2_OPERATION_IDS)


def _load_frozen_contract() -> Mapping[str, Any]:
    if not FROZEN_CONTRACT.is_file():
        raise RuntimeError(f"frozen media contract is missing: {FROZEN_CONTRACT}")
    return json.loads(FROZEN_CONTRACT.read_text(encoding="utf-8"))


_FROZEN = _load_frozen_contract()
_FROZEN_SCHEMAS = _FROZEN["api_schemas"]


def _schema_name(operation_id: str, kind: str) -> str | None:
    ref = OPERATIONS[operation_id].get(f"{kind}_schema_ref")
    return None if ref is None else str(ref).rsplit("/", 1)[-1]


def _validate(value: Any, schema_name: str, *, label: str) -> Any:
    try:
        from jsonschema import Draft202012Validator, RefResolver
    except ImportError as exc:  # pragma: no cover - deployment dependency failure
        raise RuntimeError("jsonschema is required for frozen media contract validation") from exc
    root = {"$schema": "https://json-schema.org/draft/2020-12/schema", "api_schemas": _FROZEN_SCHEMAS}
    schema = {"$ref": f"#/api_schemas/{schema_name}"}
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(root))
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise ValueError(f"{label} violates frozen schema {schema_name}: {errors[0].message}")
    return value


def validate_r1_request(operation_id: str, payload: Mapping[str, Any]) -> None:
    name = _schema_name(operation_id, "request")
    if name is not None:
        _validate(dict(payload), name, label=f"{operation_id} request")


def validate_r1_response(operation_id: str, payload: Any) -> None:
    name = _schema_name(operation_id, "response")
    if name is not None:
        _validate(payload, name, label=f"{operation_id} response")


def catalog_digest() -> str:
    catalog = []
    for pipeline in _FROZEN.get("pipeline_catalog", []):
        item = dict(pipeline)
        item.pop("catalog_digest", None)
        catalog.append(item)
    catalog.sort(key=lambda item: (item["pipeline_id"], item["version"]))
    import hashlib
    encoded = json.dumps(catalog, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def pipeline_summaries() -> list[dict[str, str]]:
    digest = catalog_digest()
    return [
        {"pipeline_id": item["pipeline_id"], "version": item["version"],
         "display_name": item["display_name"], "catalog_digest": digest}
        for item in sorted(_FROZEN.get("pipeline_catalog", []), key=lambda item: (item["pipeline_id"], item["version"]))
    ]


SERVER_API_VERSION = str(_FROZEN["version"])


def _numeric_version(value: str) -> tuple[int, ...]:
    if re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))+", value) is None:
        raise RuntimeError("frozen pipeline catalog contains an invalid min_cli_version")
    return tuple(int(part) for part in value.split("."))


_MINIMUM_CLI_VERSIONS = [
    str(item["min_cli_version"])
    for item in _FROZEN.get("pipeline_catalog", [])
]
if not _MINIMUM_CLI_VERSIONS:
    raise RuntimeError("frozen pipeline catalog contains no min_cli_version")
MIN_CLIENT_VERSION = max(_MINIMUM_CLI_VERSIONS, key=_numeric_version)


def operation_metadata(operation_id: str) -> Mapping[str, Any]:
    try:
        return OPERATIONS[operation_id]
    except KeyError as exc:
        raise RuntimeError(f"unknown generated media operation: {operation_id}") from exc


def operation_path(operation_id: str, parameters: Mapping[str, object] | None = None) -> str:
    operation = operation_metadata(operation_id)
    path = str(operation["relative_path"])
    values = parameters or {}
    for parameter in PATH_PARAMETERS[operation_id]:
        if parameter not in values:
            raise ValueError(f"missing path parameter: {parameter}")
        path = path.replace("{" + parameter + "}", str(values[parameter]))
    return path


def _route_pattern(relative_path: str) -> re.Pattern[str]:
    cursor = 0
    pieces: list[str] = []
    for match in re.finditer(r"\{([a-z_]+)\}", relative_path):
        pieces.append(re.escape(relative_path[cursor : match.start()]))
        pieces.append(r"(?P<" + match.group(1) + r">[A-Za-z0-9_-]+)")
        cursor = match.end()
    pieces.append(re.escape(relative_path[cursor:]))
    return re.compile("^" + "".join(pieces) + "$")


_ROUTES = tuple(
    (operation_id, str(operation["method"]).upper(), _route_pattern(str(operation["relative_path"])))
    for operation_id, operation in OPERATIONS.items()
    if operation_id in R1_OPERATION_IDS
)


def resolve_r1_operation(relative_path: str, method: str) -> tuple[str, dict[str, str]] | None:
    normalized_method = method.upper()
    for operation_id, operation_method, pattern in _ROUTES:
        if operation_method != normalized_method:
            continue
        match = pattern.fullmatch(relative_path)
        if match is not None:
            return operation_id, match.groupdict()
    return None
