#!/usr/bin/env python3
"""Check canonical asset routing and server-authoritative artifact summaries."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
HTTP_PATH = ROOT / "openclaw_app/adapters/http_api.py"
OVERVIEW_PATH = ROOT / "openclaw_app/services/media_business/overview.py"
CONTRACT_PATH = ROOT / "openclaw_app/contracts/media_web_business_pages.openapi.yaml"

PERSONAL_REQUIRED = {
    "publicArtifactId",
    "publicProjectId",
    "artifactType",
    "workspaceMode",
    "editorMode",
    "bodyAuthority",
    "currentRevision",
    "updatedAt",
    "allowedActions",
}
ORGANIZATION_REQUIRED = PERSONAL_REQUIRED | {"syncStatus", "trustedOrganizationResource"}
OBSOLETE_ARTIFACT_KEYS = {"organizationDocumentUrl", "organizationDocumentUrlExpiresAt"}


def _class_method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise ValueError(f"missing {class_name}.{method_name}")


def _class_string(tree: ast.Module, class_name: str, name: str) -> str:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if not isinstance(child, ast.Assign):
                continue
            if any(isinstance(target, ast.Name) and target.id == name for target in child.targets):
                if isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                    return child.value.value
    raise ValueError(f"missing {class_name}.{name}")


def _strings(node: ast.AST) -> set[str]:
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def _called_names(node: ast.AST) -> set[str]:
    result: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            result.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            result.add(child.func.attr)
    return result


def _dict_keys(node: ast.AST) -> set[str]:
    keys: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key in child.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


def _legacy_asset_literal(value: str) -> bool:
    return value == "/media/api/assets" or value.startswith("/media/api/assets/") or "|media/api" in value


def audit_sources(http_source: str, overview_source: str, contract_source: str) -> list[str]:
    errors: list[str] = []
    try:
        http_tree = ast.parse(http_source, filename=str(HTTP_PATH))
        dispatch = _class_method(http_tree, "OpenClawHttpHandler", "_dispatch_media_business")
        try:
            do_get = _class_method(http_tree, "OpenClawHttpHandler", "_do_GET")
        except ValueError:
            do_get = _class_method(http_tree, "OpenClawHttpHandler", "do_GET")
    except (SyntaxError, ValueError) as exc:
        errors.append(f"HTTP route source is not auditable: {exc}")
    else:
        if "is_legacy_if2_business_request" not in _called_names(dispatch):
            errors.append("legacy IF2 rejection boundary is missing from media dispatch")
        handler_calls = {
            "_handle_tenant_assets",
            "_handle_tenant_asset_detail",
            "_handle_tenant_asset_preview",
        }
        if handler_calls & _called_names(dispatch):
            errors.append("legacy rejection dispatch must not invoke asset handlers")
        if any(_legacy_asset_literal(value) for value in _strings(dispatch) | _strings(do_get)):
            errors.append("retired /media/api/assets route is executable in HTTP routing")
        if not handler_calls <= _called_names(do_get):
            errors.append("canonical asset list/detail/preview handlers are incomplete")
        do_get_strings = _strings(do_get)
        if "/openclaw/media/api/assets" not in do_get_strings:
            errors.append("canonical asset list route is missing")
        if not any("openclaw/media/api/assets/" in value and "preview" in value for value in do_get_strings):
            errors.append("canonical asset detail/preview route patterns are missing")

    try:
        overview_tree = ast.parse(overview_source, filename=str(OVERVIEW_PATH))
        artifacts_sql = _class_string(overview_tree, "OverviewService", "_ARTIFACTS_PREFIX")
        projection = _class_method(overview_tree, "OverviewService", "_artifact_projection")
        resource_validator = _class_method(overview_tree, "OverviewService", "_organization_document_url")
    except (SyntaxError, ValueError) as exc:
        errors.append(f"overview source is not auditable: {exc}")
    else:
        if "artifact.workspace_mode" not in artifacts_sql:
            errors.append("artifact list SQL does not read authoritative workspace_mode")
        projection_strings = _strings(projection)
        projection_keys = _dict_keys(projection)
        for value in ("personal_web", "web_edit", "internal", "organization_lark", "lark_edit", "lark"):
            if value not in projection_strings:
                errors.append(f"artifact projection is missing frozen discriminator {value}")
        if not PERSONAL_REQUIRED <= projection_keys:
            errors.append("personal artifact projection is missing IFV5 fields")
        if not ORGANIZATION_REQUIRED <= projection_keys:
            errors.append("organization artifact projection is missing IFV5 fields")
        if OBSOLETE_ARTIFACT_KEYS & projection_keys:
            errors.append("artifact projection still emits obsolete URL-shaped fields")
        if "_organization_document_url" not in _called_names(projection):
            errors.append("organization artifact projection bypasses the overview resource validator")
        if "trusted_organization_resource" not in _called_names(resource_validator):
            errors.append("organization artifact projection bypasses trusted resource validation")

    try:
        contract: dict[str, Any] = yaml.safe_load(contract_source)
        schemas = contract["components"]["schemas"]
        union = schemas["ArtifactSummary"]
        personal = schemas["PersonalWebArtifactSummary"]
        organization = schemas["OrganizationLarkArtifactSummary"]
    except (yaml.YAMLError, KeyError, TypeError) as exc:
        errors.append(f"artifact OpenAPI union is not auditable: {exc}")
    else:
        refs = {item.get("$ref") for item in union.get("oneOf", []) if isinstance(item, dict)}
        expected_refs = {
            "#/components/schemas/PersonalWebArtifactSummary",
            "#/components/schemas/OrganizationLarkArtifactSummary",
        }
        if refs != expected_refs or union.get("discriminator", {}).get("propertyName") != "workspaceMode":
            errors.append("ArtifactSummary is not the frozen workspace-discriminated union")
        personal_required = set(personal.get("required", []))
        organization_required = set(organization.get("required", []))
        if not PERSONAL_REQUIRED <= personal_required:
            errors.append("PersonalWebArtifactSummary required fields drifted")
        if not ORGANIZATION_REQUIRED <= organization_required:
            errors.append("OrganizationLarkArtifactSummary required fields drifted")
        if "trustedOrganizationResource" in personal.get("properties", {}):
            errors.append("personal artifact schema leaks organization resource authority")
        for schema in (personal, organization):
            if OBSOLETE_ARTIFACT_KEYS & set(schema.get("properties", {})):
                errors.append("artifact schema contains obsolete URL-shaped fields")
    return errors


def main() -> int:
    errors = audit_sources(
        HTTP_PATH.read_text(encoding="utf-8"),
        OVERVIEW_PATH.read_text(encoding="utf-8"),
        CONTRACT_PATH.read_text(encoding="utf-8"),
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
        print("PASS: canonical asset routes and IFV5 artifact authority are structurally enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
