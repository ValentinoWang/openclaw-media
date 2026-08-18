from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openclaw_app.services.resource_owner_registry import (
    ResourceOwnerInvalid,
    ResourceOwnerNotFound,
    ResourceOwnerProjectionMismatch,
    ResourceOwnerRegistry,
)
from openclaw_app.services.tenant_owned_resources import (
    TenantOwnedResourceContractError,
    TenantOwnedResourceService,
)


class TenantOwnedResourceServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = ResourceOwnerRegistry(Path(self.temp_dir.name) / "owners.sqlite3")
        self.service = TenantOwnedResourceService(self.registry)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_projects_server_owned_tenant_and_rejects_client_owner_fields(self) -> None:
        projected = self.service.create_projection(
            "media.creation_run",
            "run_101",
            session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            fields={"创作运行ID": "run_101"},
            writer=lambda fields: fields,
        )

        self.assertEqual(projected["租户ID"], "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        summary = self.registry.list_creation_run_summaries(
            "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", search="", limit=20, offset=0
        )
        self.assertEqual([item.canonical_resource_id for item in summary], ["run_101"])
        self.service.update_projection(
            "media.creation_run",
            "run_101",
            session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            fields={"输入需求摘要": "可检索标题", "状态": "success"},
            writer=lambda fields: fields,
        )
        updated = self.registry.list_creation_run_summaries(
            "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", search="可检索", limit=20, offset=0
        )
        self.assertEqual(updated[0].title, "可检索标题")
        for forbidden in ({"租户ID": "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"}, {"tenant_id": "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"}, {"owner_id": "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"}):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ResourceOwnerInvalid):
                    self.service.create_projection(
                        "media.creation_run",
                        "run_forbidden",
                        session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
                        fields=forbidden,
                        writer=lambda fields: fields,
                    )

    def test_cross_tenant_read_update_and_delete_are_uniformly_not_found(self) -> None:
        self.registry.create("media.creation_run", "run_private", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")

        operations = (
            lambda: self.service.assert_projection_read(
                "media.creation_run",
                "run_private",
                session_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
                fields={"租户ID": "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"},
                projection_source="feishu:runs/rec_private",
            ),
            lambda: self.service.update_projection(
                "media.creation_run",
                "run_private",
                session_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
                fields={"状态": "failed"},
                writer=lambda fields: fields,
            ),
            lambda: self.service.archive_after_delete(
                "media.creation_run",
                "run_private",
                session_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
                deleter=lambda: None,
            ),
        )
        messages = []
        for operation in operations:
            with self.assertRaises(ResourceOwnerNotFound) as raised:
                operation()
            messages.append(str(raised.exception))
        self.assertEqual(messages, ["resource not found"] * 3)

    def test_projection_mismatch_queues_repair_and_fails_closed(self) -> None:
        self.registry.create("media.creation_run", "run_mismatch", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")

        with self.assertRaises(ResourceOwnerProjectionMismatch):
            self.service.assert_projection_read(
                "media.creation_run",
                "run_mismatch",
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
                fields={"租户ID": "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"},
                projection_source="feishu:runs/rec_mismatch",
            )

        repairs = self.registry.list_repairs()
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0].canonical_tenant_id, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        self.assertEqual(repairs[0].observed_tenant_id, "775e0c03-febc-4a39-8ad0-3e18bb8a6d45")

    def test_list_rejects_unrequested_or_missing_projection(self) -> None:
        self.registry.create("media.creation_run", "run_a", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")

        with self.assertRaises(TenantOwnedResourceContractError):
            self.service.list_projections(
                "media.creation_run",
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
                loader=lambda _ids: [{"创作运行ID": "run_other", "租户ID": "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"}],
                canonical_id_field="创作运行ID",
                projection_source=lambda _row: "feishu:runs/rec_other",
            )

    def test_relation_endpoints_must_share_authenticated_tenant(self) -> None:
        self.registry.create("media.creation_run", "run_101", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        self.registry.create("media.source_asset", "asset_202", session_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45")

        with self.assertRaises(ResourceOwnerNotFound):
            self.service.assert_same_tenant_relations(
                (
                    ("media.creation_run", "run_101"),
                    ("media.source_asset", "asset_202"),
                ),
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            )


if __name__ == "__main__":
    unittest.main()
