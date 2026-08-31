from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/quality/check_media_asset_route_authority.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("media_asset_route_authority_guard", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = _load_guard()


def _valid_http(extra: str = "") -> str:
    return f'''
class OpenClawHttpHandler:
    def _dispatch_media_business(self, method):
        if is_legacy_if2_business_request(method, self.path):
            return True
        return False

    def do_GET(self):
        path = self.path
        if path == "/openclaw/media/api/assets":
            self._handle_tenant_assets()
        match = re.fullmatch(r"/openclaw/media/api/assets/([A-Za-z0-9_-]{{8,160}})/preview", path)
        if match:
            self._handle_tenant_asset_preview(match.group(1))
        match = re.fullmatch(r"/openclaw/media/api/assets/([A-Za-z0-9_-]{{8,160}})", path)
        if match:
            self._handle_tenant_asset_detail(match.group(1))

def documentation_only():
    """The retired /media/api/assets route remains documented as a negative example."""
    return "/media/api/assets-extra"
{extra}
'''


def _valid_overview(extra: str = "") -> str:
    return f'''
class OverviewService:
    _ARTIFACTS_PREFIX = "SELECT artifact.workspace_mode FROM media_product.document_artifacts AS artifact"

    @staticmethod
    def _organization_document_url(value, body_authority, *, expires_at=None, retired=False):
        if body_authority != "lark":
            return None
        return trusted_organization_resource(value, expires_at=expires_at, retired=retired)

    def _artifact_projection(self, row):
        common = {{
            "publicArtifactId": row[0], "publicProjectId": row[1], "artifactType": row[2],
            "workspaceMode": row[3], "bodyAuthority": row[4], "currentRevision": row[5],
            "updatedAt": row[6],
        }}
        if (row[3], row[4]) == ("personal_web", "internal"):
            return {{**common, "editorMode": "web_edit", "allowedActions": ["read"]}}
        if (row[3], row[4]) != ("organization_lark", "lark"):
            raise RuntimeError
        resource = self._organization_document_url(
            row[7], row[4], expires_at=row[8], retired=row[9]
        )
        return {{
            **common, "editorMode": "lark_edit", "syncStatus": "synced",
            "trustedOrganizationResource": resource, "allowedActions": ["read"],
        }}
{extra}
'''


def _valid_contract() -> str:
    personal = sorted(GUARD.PERSONAL_REQUIRED)
    organization = sorted(GUARD.ORGANIZATION_REQUIRED)
    personal_properties = "\n".join(f"        {key}: {{}}" for key in personal)
    organization_properties = "\n".join(f"        {key}: {{}}" for key in organization)
    personal_required = "\n".join(f"      - {key}" for key in personal)
    organization_required = "\n".join(f"      - {key}" for key in organization)
    return f'''
components:
  schemas:
    ArtifactSummary:
      oneOf:
      - $ref: '#/components/schemas/PersonalWebArtifactSummary'
      - $ref: '#/components/schemas/OrganizationLarkArtifactSummary'
      discriminator:
        propertyName: workspaceMode
    PersonalWebArtifactSummary:
      properties:
{personal_properties}
      required:
{personal_required}
    OrganizationLarkArtifactSummary:
      properties:
{organization_properties}
      required:
{organization_required}
'''


def test_guard_accepts_canonical_routes_union_and_unrelated_literals() -> None:
    assert GUARD.audit_sources(_valid_http(), _valid_overview(), _valid_contract()) == []


def test_guard_rejects_resurrected_legacy_asset_handler_path() -> None:
    source = _valid_http().replace(
        'path == "/openclaw/media/api/assets"',
        'path in {"/openclaw/media/api/assets", "/media/api/assets"}',
    )
    errors = GUARD.audit_sources(source, _valid_overview(), _valid_contract())
    assert any("retired /media/api/assets" in error for error in errors)


def test_guard_rejects_projection_without_authoritative_workspace_column() -> None:
    source = _valid_overview().replace("artifact.workspace_mode", "artifact.body_authority")
    errors = GUARD.audit_sources(_valid_http(), source, _valid_contract())
    assert any("workspace_mode" in error for error in errors)


def test_guard_rejects_organization_union_without_trusted_resource_key() -> None:
    contract = _valid_contract().replace("      - trustedOrganizationResource\n", "", 1)
    errors = GUARD.audit_sources(_valid_http(), _valid_overview(), contract)
    assert any("OrganizationLarkArtifactSummary required fields" in error for error in errors)
