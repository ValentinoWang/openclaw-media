from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openclaw_app.services.resource_access import ResourceAccessService
from openclaw_app.services.tenant_owned_resources import TenantOwnedResourceService
from openclaw_app.services.resource_owner_registry import (
    ResourceOwnerConflict,
    ResourceOwnerInvalid,
    ResourceOwnerNotFound,
    ResourceOwnerRegistry,
)


class ResourceAccessServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.registry = ResourceOwnerRegistry(Path(self.temporary.name) / "owners.sqlite3")
        self.access = ResourceAccessService(self.registry)
        self.registry.create("media.creation_run", "run_alpha", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        self.registry.create("media.source_asset", "asset_alpha", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_docx_link_is_tenant_scoped_and_base_token_is_rejected(self) -> None:
        self.access.put_docx_link(
            "media.creation_run",
            "run_alpha",
            session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            docx_token="DoxcnTenantOwned123",
            policy="org_link_edit",
        )
        link = self.access.get_docx_link(
            "media.creation_run", "run_alpha", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
        )
        self.assertEqual("https://feishu.cn/docx/DoxcnTenantOwned123", link.document_url)
        with self.assertRaises(ResourceOwnerNotFound):
            self.access.get_docx_link(
                "media.creation_run", "run_alpha", session_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
            )

    def test_owner_service_registers_only_docx_urls(self) -> None:
        service = TenantOwnedResourceService(self.registry)
        link = service.register_docx_link(
            "media.creation_run",
            "run_alpha",
            session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            document_url="https://example.feishu.cn/docx/DoxcnTenantOwned456?from=writer",
            policy="org_link_edit",
        )
        self.assertEqual("https://feishu.cn/docx/DoxcnTenantOwned456", link.document_url)
        with self.assertRaises(ResourceOwnerInvalid):
            service.register_docx_link(
                "media.creation_run",
                "run_alpha",
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
                document_url="https://example.feishu.cn/wiki/WikiNodeOwned456",
                policy="org_link_edit",
            )
        with self.assertRaises(ResourceOwnerInvalid):
            service.register_docx_link(
                "media.creation_run",
                "run_alpha",
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
                document_url="https://attacker.example/docx/DoxcnTenantOwned456",
                policy="org_link_edit",
            )
        with self.assertRaises(ResourceOwnerInvalid):
            self.access.put_docx_link(
                "media.source_asset",
                "asset_alpha",
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
                docx_token="https://feishu.cn/base/tenant-leak",
                policy="anyone_editable",
            )

    def test_revoked_link_cannot_be_reactivated(self) -> None:
        self.access.put_docx_link(
            "media.creation_run", "run_alpha", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            docx_token="DoxcnTerminalStatus123", policy="org_link_edit",
        )
        self.access.set_link_status(
            "media.creation_run", "run_alpha", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", status="revoked",
        )
        with self.assertRaises(ResourceOwnerConflict):
            self.access.put_docx_link(
                "media.creation_run", "run_alpha", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
                docx_token="DoxcnReplacement123", policy="org_link_edit",
            )


if __name__ == "__main__":
    unittest.main()
