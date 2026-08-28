#!/usr/bin/env python3
"""Generate every Media product client mirror from the canonical JSON contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/ai-harness/openclaw-media-product-contract.json"
CLIENT_ROOT = Path(__file__).resolve().parent
PYTHON_OUTPUTS = (
    CLIENT_ROOT / "generated_product_contract.py",
    CLIENT_ROOT / "src/openclaw_media/product_contract.py",
    ROOT / "openclaw-media/openclaw_media/generated_product_contract.py",
)
TYPESCRIPT_OUTPUTS = (
    CLIENT_ROOT / "generatedProductContract.ts",
    CLIENT_ROOT / "web/src/generated/productContract.ts",
    ROOT / "openclaw-bot-center/src/media/generatedProductContract.ts",
)


def load_contract(path: Path = CONTRACT) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _py_literal(value: Any, level: int = 0) -> str:
    if isinstance(value, dict):
        indent = "    " * level
        rows = [
            f"{'    ' * (level + 1)}{key!r}: {_py_literal(item, level + 1)}"
            for key, item in value.items()
        ]
        return "{}" if not rows else "{\n" + ",\n".join(rows) + f"\n{indent}}}"
    if isinstance(value, list):
        indent = "    " * level
        rows = [f"{'    ' * (level + 1)}{_py_literal(item, level + 1)}" for item in value]
        return "[]" if not rows else "[\n" + ",\n".join(rows) + f"\n{indent}]"
    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    return repr(value)


def _py_type(schema: dict[str, Any]) -> str:
    if "anyOf" in schema:
        return " | ".join(_py_type(item) for item in schema["anyOf"])
    if "$ref" in schema:
        return _schema_name(schema["$ref"])
    if "const" in schema:
        return f"Literal[{schema['const']!r}]"
    if "enum" in schema:
        values = ", ".join(repr(value) for value in schema["enum"])
        return f"Literal[{values}]"
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(_py_type({"type": item}) for item in kind)
    if kind == "array":
        return f"list[{_py_type(schema.get('items', {}))}]"
    if kind == "object":
        return "dict[str, Any]"
    return {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "null": "None"}.get(kind, "Any")


def _ts_type(schema: dict[str, Any]) -> str:
    if "anyOf" in schema:
        return " | ".join(_ts_type(item) for item in schema["anyOf"])
    if "$ref" in schema:
        return _schema_name(schema["$ref"])
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=True)
    if "enum" in schema:
        return " | ".join(json.dumps(value, ensure_ascii=True) for value in schema["enum"])
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(_ts_type({"type": item}) for item in kind)
    if kind == "array":
        return f"Array<{_ts_type(schema.get('items', {}))}>"
    if kind == "object":
        return "Record<string, unknown>"
    return {"string": "string", "integer": "number", "number": "number", "boolean": "boolean", "null": "null"}.get(kind, "unknown")


def _python_types(schemas: dict[str, dict[str, Any]]) -> str:
    chunks: list[str] = []
    for name, schema in schemas.items():
        if schema.get("type") != "object" or "properties" not in schema:
            continue
        required = set(schema.get("required", []))
        chunks.append(f"class {name}(TypedDict):")
        if not schema.get("properties"):
            chunks.append("    pass")
        else:
            for field, field_schema in schema["properties"].items():
                wrapper = "Required" if field in required else "NotRequired"
                chunks.append(f"    {field}: {wrapper}[{_py_type(field_schema)}]")
        chunks.append("")
    return "\n".join(chunks)


def _typescript_types(schemas: dict[str, dict[str, Any]]) -> str:
    chunks: list[str] = []
    for name, schema in schemas.items():
        if schema.get("type") != "object" or "properties" not in schema:
            continue
        required = set(schema.get("required", []))
        chunks.append(f"export interface {name} {{")
        for field, field_schema in schema["properties"].items():
            optional = "" if field in required else "?"
            chunks.append(f"  {field}{optional}: {_ts_type(field_schema)};")
        chunks.extend(("}", ""))
    return "\n".join(chunks)


def _method_name(operation_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", operation_id).strip("_")


def _path_params(path: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\{([^{}]+)\}", path))


def _route_objects(contract: dict[str, Any]) -> dict[str, str]:
    return {item["path"]: item["object_id"] for item in contract["routes"]}


def _assert_python_request_requiredness(contract: dict[str, Any], rendered: bytes) -> None:
    schemas = contract["api_schemas"]
    operations = {item["operation_id"]: item for item in contract["api_operations"]}
    text = rendered.decode("utf-8")
    for operation_id, operation in operations.items():
        request_ref = operation["request_schema_ref"]
        request_name = _schema_name(request_ref) if request_ref else "Mapping[str, Any]"
        request_schema = schemas.get(request_name, {})
        required = bool(request_schema.get("required"))
        annotation = request_name if required else f"{request_name} | None"
        default = "" if required else " = None"
        request_value = "request" if required else "request or {}"
        method = _method_name(operation_id)
        signature = f"    def {method}(self, request: {annotation}{default}) -> "
        if signature not in text or f"self._call({operation_id!r}, {request_value}))" not in text:
            raise AssertionError(
                f"Python request requiredness drift for {operation_id}: "
                f"expected {'required' if required else 'optional'} request"
            )


def render_python(contract: dict[str, Any]) -> bytes:
    schemas = contract["api_schemas"]
    operations = contract["api_operations"]
    route_objects = _route_objects(contract)
    operation_ids = tuple(item["operation_id"] for item in operations)
    path_parameters = {item["operation_id"]: _path_params(item["relative_path"]) for item in operations}
    methods: list[str] = []
    for operation in operations:
        response_ref = operation["response_schema_ref"]
        response_name = _schema_name(response_ref)
        request_ref = operation["request_schema_ref"]
        request_name = _schema_name(request_ref) if request_ref else "Mapping[str, Any]"
        request_schema = schemas.get(request_name, {})
        request_required = bool(request_schema.get("required"))
        request_annotation = request_name if request_required else f"{request_name} | None"
        request_default = "" if request_required else " = None"
        request_value = "request" if request_required else "request or {}"
        method = _method_name(operation["operation_id"])
        methods.extend((
            f"    def {method}(self, request: {request_annotation}{request_default}) -> {response_name}:",
            f"        return cast({response_name}, self._call({operation['operation_id']!r}, {request_value}))",
            "",
        ))
    metadata = {item["operation_id"]: item for item in operations}
    text = '''"""Generated from openclaw-media-product-contract.json. Do not edit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, NotRequired, Protocol, Required, TypedDict, cast
from urllib.parse import quote

'''
    text += _python_types(schemas)
    text += "\n"
    text += f"API_BASE = {contract['api_base']!r}\n"
    text += f"RELEASE_PLATFORMS = {_py_literal(tuple(contract['release']['platforms']))}\n"
    text += f"OBJECT_IDS = {_py_literal({item['id']: item['id_field'] for item in contract['objects']})}\n"
    text += f"WEB_ROUTES = {_py_literal(tuple(route_objects))}\n"
    text += f"ROUTE_OBJECTS = {_py_literal(route_objects)}\n"
    text += f"LOCAL_COLLABORATION = {_py_literal(contract['web']['local_collaboration'])}\n"
    text += f"STATE_MACHINES = {_py_literal(contract['state_machines'])}\n"
    text += f"OPERATION_IDS = {_py_literal(operation_ids)}\n"
    text += "OperationId = Literal[" + ", ".join(repr(item) for item in operation_ids) + "]\n"
    text += f"OPERATIONS: dict[str, dict[str, Any]] = {_py_literal(metadata)}\n"
    text += f"PATH_PARAMETERS: dict[str, tuple[str, ...]] = {_py_literal(path_parameters)}\n\n"
    text += '''class ProductTransport(Protocol):
    def request(
        self, *, operation_id: str, method: str, path: str, auth_source: str,
        owner_rule: str, idempotency: str, request: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


def objects_for_route(path: str) -> str:
    return ROUTE_OBJECTS[path]


def _interpolate_path(operation_id: str, request: Mapping[str, Any]) -> str:
    path = OPERATIONS[operation_id]["relative_path"]
    for parameter in PATH_PARAMETERS[operation_id]:
        value = request.get(parameter)
        if value is None:
            raise ValueError(f"missing path parameter: {parameter}")
        path = path.replace("{" + parameter + "}", quote(str(value), safe=""))
    return path


class MediaProductClient:
    def __init__(self, transport: ProductTransport) -> None:
        self._transport = transport

    def _call(self, operation_id: OperationId, request: Mapping[str, Any]) -> Mapping[str, Any]:
        operation = OPERATIONS[operation_id]
        return self._transport.request(
            operation_id=operation_id, method=operation["method"],
            path=_interpolate_path(operation_id, request), auth_source=operation["auth"],
            owner_rule=operation["owner_rule"], idempotency=operation["idempotency"],
            request=request,
        )

'''
    text += "\n".join(methods)
    return (text.rstrip() + "\n").encode("utf-8")


def render_typescript(contract: dict[str, Any]) -> bytes:
    schemas = contract["api_schemas"]
    operations = contract["api_operations"]
    route_objects = _route_objects(contract)
    methods: list[str] = []
    for operation in operations:
        response_name = _schema_name(operation["response_schema_ref"])
        request_ref = operation["request_schema_ref"]
        request_name = _schema_name(request_ref) if request_ref else "Record<string, unknown>"
        request_schema = schemas.get(request_name, {})
        path_parameters = _path_params(operation["relative_path"])
        request_type = request_name
        if path_parameters:
            request_type += " & { " + "; ".join(f"{parameter}: string" for parameter in path_parameters) + " }"
        request_default = "" if request_schema.get("required") or path_parameters else " = {}"
        method = _method_name(operation["operation_id"])
        methods.extend((
            f"  {method}(request: {request_type}{request_default}, options?: ProductRequestOptions): Promise<{response_name}> {{",
            f"    return this.invoke<{response_name}>({operation['operation_id']!r}, request, {json.dumps(list(path_parameters))}, options);",
            "  }", "",
        ))
    metadata = {item["operation_id"]: item for item in operations}
    text = "// Generated from openclaw-media-product-contract.json. Do not edit.\n\n"
    text += _typescript_types(schemas)
    text += f"export const apiBase = {json.dumps(contract['api_base'])} as const;\n"
    text += "export const releasePlatforms = " + json.dumps(contract["release"]["platforms"], separators=(",", ":")) + " as const;\n"
    text += "export const objectIds = " + json.dumps({item["id"]: item["id_field"] for item in contract["objects"]}, separators=(",", ":")) + " as const;\n"
    text += "export const webRoutes = " + json.dumps(list(route_objects), separators=(",", ":")) + " as const;\n"
    text += "export const routeObjects = " + json.dumps(route_objects, separators=(",", ":")) + " as const;\n"
    text += "export const localCollaboration = " + json.dumps(contract["web"]["local_collaboration"], separators=(",", ":")) + " as const;\n"
    text += "export const stateMachines = " + json.dumps(contract["state_machines"], separators=(",", ":")) + " as const;\n"
    text += "export const operations = " + json.dumps(metadata, separators=(",", ":")) + " as const;\n"
    text += "export type OperationId = keyof typeof operations;\n\n"
    text += '''export type ProductRequestEnvelope = {
  method: string;
  path: string;
  query: Record<string, string>;
  body: Record<string, unknown> | undefined;
  authSource: string;
  ownerRule: string;
  idempotency: string;
  idempotencyKey?: string;
  signal?: AbortSignal;
};

export type ProductRequestOptions = {
  idempotencyKey?: string;
  signal?: AbortSignal;
};

export interface ProductTransport {
  request<TResponse>(operationId: OperationId, envelope: ProductRequestEnvelope): Promise<TResponse>;
}

function interpolatePath(path: string, request: Record<string, unknown>): string {
  return path.replace(/\\{([^{}]+)\\}/g, (_match, parameter: string) => {
    const value = request[parameter];
    if (value === undefined || value === null) throw new Error(`missing path parameter: ${parameter}`);
    return encodeURIComponent(String(value));
  });
}

export class MediaProductClient {
  private readonly transport: ProductTransport;

  constructor(transport: ProductTransport) {
    this.transport = transport;
  }

  private invoke<TResponse>(
    operationId: OperationId,
    request: object,
    pathParameters: readonly string[] = [],
    options: ProductRequestOptions = {},
  ): Promise<TResponse> {
    const operation = operations[operationId];
    const requestRecord = request as Record<string, unknown>;
    const pathParameterSet = new Set(pathParameters);
    const pathRequest = Object.fromEntries(Object.entries(requestRecord).filter(([key]) => pathParameterSet.has(key)));
    const body = operation.method === 'GET'
      ? undefined
      : Object.fromEntries(Object.entries(requestRecord).filter(([key]) => !pathParameterSet.has(key)));
    const query = operation.method === 'GET'
      ? Object.fromEntries(Object.entries(requestRecord)
        .filter(([key, value]) => !pathParameterSet.has(key) && value !== undefined && value !== null)
        .map(([key, value]) => [key, String(value)]))
      : {};
    return this.transport.request<TResponse>(operationId, {
      method: operation.method,
      path: interpolatePath(operation.relative_path, pathRequest),
      query,
      body,
      authSource: operation.auth,
      ownerRule: operation.owner_rule,
      idempotency: operation.idempotency,
      idempotencyKey: options.idempotencyKey,
      signal: options.signal,
    });
  }

'''
    text += "\n".join(methods) + "}\n"
    return text.encode("utf-8")


def render_clients(contract: dict[str, Any] | None = None) -> dict[Path, bytes]:
    contract = contract or load_contract()
    python = render_python(contract)
    _assert_python_request_requiredness(contract, python)
    typescript = render_typescript(contract)
    return {**{path: python for path in PYTHON_OUTPUTS}, **{path: typescript for path in TYPESCRIPT_OUTPUTS}}


def write_clients(contract: dict[str, Any] | None = None, outputs: dict[Path, bytes] | None = None) -> None:
    for path, content in (outputs or render_clients(contract)).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify generated bytes without writing")
    args = parser.parse_args()
    expected = render_clients()
    mismatches = [str(path) for path, content in expected.items() if not path.is_file() or path.read_bytes() != content]
    if args.check:
        if mismatches:
            raise SystemExit("FAIL: generated client drift: " + ", ".join(mismatches))
        print("PASS: deterministic product clients")
        return 0
    write_clients(outputs=expected)
    print("PASS: generated product clients")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
