#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "openclaw-tag-router/openclaw_app/contracts/media_web_business_pages.openapi.yaml"
DEFAULT_TARGET = ROOT / "src/media/generatedBusinessPagesContract.ts"
ACCEPTED_SOURCE_SHA256 = (
    "84cfcce346b941b6423e5c629d08c1ec3ffe09f0270f5ac8aae767fb2bf16a7a"
)
EXPECTED_PAGE_IDS = tuple(f"B{index:02d}" for index in range(1, 15))
EXPECTED_DOCUMENT_OPERATION_IDS = (
    "createDocumentExport",
    "getDocumentBody",
    "getDocumentResource",
    "getDocumentExport",
    "getDocumentExportDownload",
    "getDocumentRevision",
    "listArtifactSyncBatches",
    "saveDocumentDraft",
)
MEDIA_SESSION_REQUIRED = {
    "publicUserId", "tenantId", "workspaceMode", "editorMode", "bodyAuthority",
    "organizationName", "memberRole", "organizationConnection", "installationConnection",
    "role", "maintainer", "csrfToken", "expiresAt", "routeGrants", "schemaVersion",
}
HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}


def require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a string-keyed mapping")
    return value


def require_string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a string list")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} contains duplicates")
    return value


def render_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def load_contract(source: Path) -> tuple[dict[str, Any], bytes]:
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ACCEPTED_SOURCE_SHA256:
        raise ValueError(
            "accepted OpenAPI hash mismatch: "
            f"expected {ACCEPTED_SOURCE_SHA256}, got {digest}"
        )
    document = yaml.safe_load(raw)
    contract = require_mapping(document, "OpenAPI document")
    if contract.get("openapi") != "3.1.0":
        raise ValueError("accepted OpenAPI must use version 3.1.0")
    if contract.get("x-openclaw-interface-freeze-version") != 5:
        raise ValueError("accepted OpenAPI must use interface freeze version 5")
    return contract, raw


def validate_media_session_mirror(source: Path) -> None:
    source_contract = yaml.safe_load(source.read_bytes())
    mirror_path = ROOT / "contracts/media_web_business_pages.openapi.yaml"
    mirror_contract = yaml.safe_load(mirror_path.read_bytes())
    source_schemas = require_mapping(require_mapping(source_contract.get("components"), "source components").get("schemas"), "source schemas")
    mirror_schemas = require_mapping(require_mapping(mirror_contract.get("components"), "mirror components").get("schemas"), "mirror schemas")
    for schema_name in ("MediaSession", "MediaSessionResponse"):
        if source_schemas.get(schema_name) != mirror_schemas.get(schema_name):
            raise ValueError(f"frontend {schema_name} schema drifted from the server authority")
    session = require_mapping(source_schemas.get("MediaSession"), "MediaSession")
    properties = require_mapping(session.get("properties"), "MediaSession.properties")
    required = set(require_string_list(session.get("required"), "MediaSession.required"))
    if set(properties) != MEDIA_SESSION_REQUIRED or required != MEDIA_SESSION_REQUIRED:
        raise ValueError("MediaSession properties and required fields must match the exact runtime projection")
    route_grants = require_mapping(properties.get("routeGrants"), "MediaSession.routeGrants")
    if route_grants.get("minItems") != 1 or route_grants.get("uniqueItems") is not True:
        raise ValueError("MediaSession.routeGrants must be non-empty and unique")


def collect_page_operations(contract: dict[str, Any]) -> dict[str, list[str]]:
    pages = require_mapping(contract.get("x-openclaw-pages"), "x-openclaw-pages")
    if set(pages) != set(EXPECTED_PAGE_IDS):
        raise ValueError("expected exactly page declarations B01-B14")

    result: dict[str, list[str]] = {}
    for page_id in EXPECTED_PAGE_IDS:
        page = require_mapping(pages[page_id], f"x-openclaw-pages.{page_id}")
        result[page_id] = sorted(
            require_string_list(
                page.get("operationIds"),
                f"x-openclaw-pages.{page_id}.operationIds",
            )
        )
    declared = {operation_id for values in result.values() for operation_id in values}
    if len(declared) != 76:
        raise ValueError(f"expected 76 declared page operations, got {len(declared)}")
    return result


def collect_operations(
    contract: dict[str, Any], page_operations: dict[str, list[str]]
) -> tuple[dict[str, dict[str, object]], dict[str, list[str]]]:
    paths = require_mapping(contract.get("paths"), "paths")
    components = require_mapping(contract.get("components"), "components")
    component_parameters = require_mapping(
        components.get("parameters", {}), "components.parameters"
    )
    document_ids = set(EXPECTED_DOCUMENT_OPERATION_IDS)
    operations: dict[str, dict[str, object]] = {}
    groups: dict[str, list[str]] = {"page": [], "shared": [], "document": []}

    def resolve_parameter(raw_parameter: object, label: str) -> dict[str, Any]:
        parameter = require_mapping(raw_parameter, label)
        reference = parameter.get("$ref")
        if reference is None:
            return parameter
        prefix = "#/components/parameters/"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            raise ValueError(f"{label} contains an unsupported parameter reference")
        name = reference.removeprefix(prefix)
        return require_mapping(
            component_parameters.get(name), f"components.parameters.{name}"
        )

    for route, raw_path_item in paths.items():
        path_item = require_mapping(raw_path_item, f"paths.{route}")
        for method, raw_operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            operation = require_mapping(raw_operation, f"{method.upper()} {route}")
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                raise ValueError(f"{method.upper()} {route} is missing operationId")
            if operation_id in operations:
                raise ValueError(f"duplicate operationId: {operation_id}")

            page_contracts = require_string_list(
                operation.get("x-page-contracts"),
                f"{operation_id}.x-page-contracts",
            )
            if operation_id in document_ids:
                category = "document"
            elif page_contracts == ["shared"]:
                category = "shared"
            else:
                category = "page"

            canonical_capability_ids = require_string_list(
                operation.get("x-canonical-capability-id", []),
                f"{operation_id}.x-canonical-capability-id",
            )
            existing_handlers = require_string_list(
                operation.get("x-existing-handler", []),
                f"{operation_id}.x-existing-handler",
            )
            product_read_models = require_string_list(
                operation.get("x-product-read-model", []),
                f"{operation_id}.x-product-read-model",
            )
            permission = operation.get("x-permission")
            runtime_status = operation.get("x-runtime-status")
            if not isinstance(permission, str) or not permission:
                raise ValueError(f"{operation_id} is missing x-permission")
            if not isinstance(runtime_status, str) or not runtime_status:
                raise ValueError(f"{operation_id} is missing x-runtime-status")

            raw_parameters = [
                *path_item.get("parameters", []),
                *operation.get("parameters", []),
            ]
            if not all(isinstance(value, dict) for value in raw_parameters):
                raise ValueError(f"{operation_id}.parameters must be a list")
            parameter_names: dict[str, list[str]] = {"path": [], "query": []}
            for index, raw_parameter in enumerate(raw_parameters):
                parameter = resolve_parameter(
                    raw_parameter, f"{operation_id}.parameters[{index}]"
                )
                location = parameter.get("in")
                name = parameter.get("name")
                if location not in parameter_names:
                    continue
                if not isinstance(name, str) or not name:
                    raise ValueError(f"{operation_id} has an invalid {location} parameter")
                parameter_names[location].append(name)
            for location, names in parameter_names.items():
                if len(names) != len(set(names)):
                    raise ValueError(f"{operation_id} has duplicate {location} parameters")

            operations[operation_id] = {
                "canonicalCapabilityIds": sorted(canonical_capability_ids),
                "category": category,
                "existingHandlers": sorted(existing_handlers),
                "method": method.upper(),
                "pageContracts": sorted(page_contracts),
                "path": route,
                "pathParameters": sorted(parameter_names["path"]),
                "permission": permission,
                "productReadModels": sorted(product_read_models),
                "queryParameters": sorted(parameter_names["query"]),
                "runtimeStatus": runtime_status,
            }
            groups[category].append(operation_id)

    if len(operations) != 92:
        raise ValueError(f"expected 92 unique operations, got {len(operations)}")
    for values in groups.values():
        values.sort()
    expected_counts = {"page": 74, "shared": 10, "document": 8}
    actual_counts = {name: len(values) for name, values in groups.items()}
    if actual_counts != expected_counts:
        raise ValueError(
            f"operation category drift: expected {expected_counts}, got {actual_counts}"
        )
    if set(groups["document"]) != document_ids:
        raise ValueError("document operation set drifted")

    declared_page_ids = {
        operation_id
        for operation_ids in page_operations.values()
        for operation_id in operation_ids
    }
    if not declared_page_ids.issubset(operations):
        raise ValueError("x-openclaw-pages references an unknown operation")
    if not set(groups["page"]).issubset(declared_page_ids):
        raise ValueError("x-openclaw-pages omits a page operation")
    declared_document_ids = declared_page_ids.intersection(document_ids)
    if declared_page_ids != set(groups["page"]).union(declared_document_ids):
        raise ValueError("x-openclaw-pages contains an invalid non-page operation")
    if declared_document_ids != {"getDocumentResource", "listArtifactSyncBatches"}:
        raise ValueError("declared document page-operation set drifted")
    for operation_id in declared_page_ids:
        expected_pages = sorted(
            page_id
            for page_id, operation_ids in page_operations.items()
            if operation_id in operation_ids
        )
        if operations[operation_id]["pageContracts"] != expected_pages:
            raise ValueError(f"{operation_id} page declaration drifted")
    return dict(sorted(operations.items())), groups


def render(source: Path) -> str:
    contract, raw = load_contract(source)
    components = require_mapping(contract.get("components"), "components")
    schemas = require_mapping(components.get("schemas"), "components.schemas")
    schema_names = sorted(schemas)
    if len(schema_names) != 184:
        raise ValueError(f"expected 184 schemas, got {len(schema_names)}")

    page_operations = collect_page_operations(contract)
    operations, groups = collect_operations(contract, page_operations)
    schema_refs = {
        schema_name: f"#/components/schemas/{schema_name}"
        for schema_name in schema_names
    }
    source_hash = hashlib.sha256(raw).hexdigest()

    return "\n".join(
        [
            "// Generated from accepted Media Web Business Pages IF2. Do not edit.",
            'import { addAuditReasonHeader } from "./auditReasonHeader";',
            "",
            f'export const sourceSha256 = "{source_hash}" as const;',
            "",
            'export type OperationCategory = "page" | "shared" | "document";',
            "export type GeneratedOperation = {",
            "  readonly method: string;",
            "  readonly path: string;",
            "  readonly pathParameters: readonly string[];",
            "  readonly queryParameters: readonly string[];",
            "  readonly category: OperationCategory;",
            "  readonly pageContracts: readonly string[];",
            "  readonly permission: string;",
            "  readonly runtimeStatus: string;",
            "  readonly canonicalCapabilityIds: readonly string[];",
            "  readonly existingHandlers: readonly string[];",
            "  readonly productReadModels: readonly string[];",
            "};",
            "",
            f"export const schemaNames = {render_json(schema_names)} as const;",
            "",
            f"export const schemaRefs = {render_json(schema_refs)} as const;",
            "",
            f"export const operationIdsByPage = {render_json(page_operations)} as const;",
            "",
            f"export const pageOperationIds = {render_json(groups['page'])} as const;",
            "",
            f"export const sharedOperationIds = {render_json(groups['shared'])} as const;",
            "",
            f"export const documentOperationIds = {render_json(groups['document'])} as const;",
            "",
            "export const operationGroups = {",
            "  page: pageOperationIds,",
            "  shared: sharedOperationIds,",
            "  document: documentOperationIds,",
            "} as const;",
            "",
            f"export const operations = {render_json(operations)} as const satisfies Record<string, GeneratedOperation>;",
            "",
            "export type SchemaName = (typeof schemaNames)[number];",
            "export type SchemaRef = (typeof schemaRefs)[SchemaName];",
            "export type PageId = keyof typeof operationIdsByPage;",
            "export type PageOperationId = (typeof pageOperationIds)[number];",
            "export type SharedOperationId = (typeof sharedOperationIds)[number];",
            "export type DocumentOperationId = (typeof documentOperationIds)[number];",
            "export type OperationId = keyof typeof operations;",
            "",
            "export type BusinessOperationRequest = {",
            "  readonly path?: Readonly<Record<string, unknown>>;",
            "  readonly query?: Readonly<Record<string, unknown>>;",
            "  readonly body?: unknown;",
            "  readonly signal?: AbortSignal;",
            "  readonly csrfToken?: string;",
            "  readonly idempotencyKey?: string;",
            "  readonly auditReason?: string;",
            "};",
            "",
            "export class BusinessOperationError extends Error {",
            "  readonly status: number;",
            "  readonly code: string;",
            "",
            "  constructor(",
            "    status: number,",
            "    code: string,",
            "    message: string,",
            "  ) {",
            "    super(message);",
            '    this.name = "BusinessOperationError";',
            "    this.status = status;",
            "    this.code = code;",
            "  }",
            "}",
            "",
            "function appendQueryValue(search: URLSearchParams, name: string, value: unknown): void {",
            "  if (value === undefined || value === null) return;",
            "  if (Array.isArray(value)) {",
            "    for (const item of value) appendQueryValue(search, name, item);",
            "    return;",
            "  }",
            "  search.append(name, String(value));",
            "}",
            "",
            "export async function callBusinessOperation<T>(",
            "  operationId: OperationId,",
            "  request: BusinessOperationRequest = {},",
            "): Promise<T> {",
            "  const operation = (operations as Record<string, GeneratedOperation>)[operationId];",
            "  if (!operation) {",
            '    throw new BusinessOperationError(0, "undeclared_operation", `Undeclared operation: ${operationId}`);',
            "  }",
            "",
            "  const suppliedPath = request.path ?? {};",
            "  const unexpectedPath = Object.keys(suppliedPath).filter(",
            "    (name) => !operation.pathParameters.includes(name),",
            "  );",
            "  if (unexpectedPath.length > 0) {",
            '    throw new BusinessOperationError(0, "unexpected_path_parameter", `Unexpected path parameter: ${unexpectedPath[0]}`);',
            "  }",
            "  let expandedPath = operation.path;",
            "  for (const name of operation.pathParameters) {",
            "    const value = suppliedPath[name];",
            '    if (value === undefined || value === null || value === "") {',
            '      throw new BusinessOperationError(0, "missing_path_parameter", `Missing path parameter: ${name}`);',
            "    }",
            "    expandedPath = expandedPath.replace(`{${name}}`, encodeURIComponent(String(value)));",
            "  }",
            "",
            "  const search = new URLSearchParams();",
            "  const suppliedQuery = request.query ?? {};",
            "  for (const name of operation.queryParameters) {",
            "    appendQueryValue(search, name, suppliedQuery[name]);",
            "  }",
            "  const queryString = search.toString();",
            '  const url = `/openclaw/media/api${expandedPath}${queryString ? `?${queryString}` : ""}`;',
            '  const headers: Record<string, string> = { Accept: "application/json" };',
            '  if (request.body !== undefined) headers["Content-Type"] = "application/json";',
            '  if (request.csrfToken) headers["X-OpenClaw-CSRF"] = request.csrfToken;',
            '  if (request.idempotencyKey) headers["Idempotency-Key"] = request.idempotencyKey;',
            "  if (request.auditReason) addAuditReasonHeader(headers, request.auditReason);",
            "",
            "  const response = await fetch(url, {",
            "    method: operation.method,",
            '    credentials: "same-origin",',
            "    headers,",
            "    body: request.body === undefined ? undefined : JSON.stringify(request.body),",
            "    signal: request.signal,",
            "  });",
            '  const payload = response.status === 204 ? undefined : await response.json().catch(() => undefined);',
            "  if (!response.ok) {",
            '    const detail = payload && typeof payload === "object" && "error" in payload',
            '      ? (payload as { error?: { code?: unknown; message?: unknown } }).error',
            "      : undefined;",
            '    const code = typeof detail?.code === "string" ? detail.code : `http_${response.status}`;',
            '    const message = typeof detail?.message === "string" ? detail.message : response.statusText || "Request failed";',
            "    throw new BusinessOperationError(response.status, code, message);",
            "  }",
            "  return payload as T;",
            "}",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the accepted Media Web Business Pages IF2 contract."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()

    try:
        validate_media_session_mirror(args.source)
        content = render(args.source)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 1

    if args.check:
        try:
            current = args.target.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = ""
        if current != content:
            print("generated business contract drift", file=__import__("sys").stderr)
            return 1
        print("generated business contract is current")
        return 0

    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(content, encoding="utf-8")
    print(f"generated {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
