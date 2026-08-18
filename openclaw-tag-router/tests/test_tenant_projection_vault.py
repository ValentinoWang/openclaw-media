from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase

from openclaw_app.services.resource_owner_registry import ResourceOwnerRegistry
from openclaw_app.services.tenant_projection import CanonicalCreationRunOwnerAccessor
from openclaw_app.services.tenant_projection_vault import MediaVaultTenantProjectionReader


class TenantProjectionVaultTests(TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.vault_root = root / "vault"
        self.registry = ResourceOwnerRegistry(root / "owners.sqlite3")
        self.registry.create("media.creation_run", "run_owned", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        run_dir = self.vault_root / "tenants" / "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37" / "creation_runs" / "run_owned"
        run_dir.mkdir(parents=True)
        (run_dir / "request.json").write_text(
            json.dumps({"input_summary": "Tenant run", "status": "success", "tenant_id": "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"}),
            encoding="utf-8",
        )
        self.registry.upsert_creation_run_summary(
            "run_owned",
            session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            fields={"input_summary": "Tenant run", "status": "success"},
        )
        (run_dir / "draft_output.json").write_text(
            json.dumps({"title": "Safe output", "record_id": "recPrivate123456"}),
            encoding="utf-8",
        )
        self.reader = MediaVaultTenantProjectionReader(self.registry, vault_root=self.vault_root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_owner_and_reader_are_tenant_scoped(self) -> None:
        accessor = CanonicalCreationRunOwnerAccessor(self.registry)
        self.assertEqual(accessor.resolve_run_owner("run_owned").tenant_id, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        self.assertEqual(self.reader.list_run_summaries("775e0c03-febc-4a39-8ad0-3e18bb8a6d45", cursor=None, page_size=20, search="").items, ())
        self.assertEqual(self.reader.run_base_detail("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", "run_owned").payload["title"], "Tenant run")

    def test_output_section_drops_internal_identifiers(self) -> None:
        payload = self.reader.run_section("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", "run_owned", "outputs").payload
        self.assertNotIn("record_id", json.dumps(payload))

    def test_run_list_cursor_reads_the_requested_window(self) -> None:
        for index in range(3):
            run_id = f"run_page_{index}"
            self.registry.create("media.creation_run", run_id, session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
            run_dir = self.vault_root / "tenants" / "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37" / "creation_runs" / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "request.json").write_text(
                json.dumps({"input_summary": f"Run {index}", "status": "success"}),
                encoding="utf-8",
            )
            self.registry.upsert_creation_run_summary(
                run_id,
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
                fields={
                    "input_summary": f"Run {index}",
                    "status": "success",
                    "created_at": f"2026-07-3{index}T00:00:00+00:00",
                },
            )

        first = self.reader.list_run_summaries("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", cursor=None, page_size=2, search="")
        self.assertEqual(len(first.items), 2)
        self.assertEqual(first.next_cursor, "2")
        second = self.reader.list_run_summaries("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", cursor=first.next_cursor, page_size=2, search="")
        self.assertEqual(len(second.items), 2)
        self.assertIsNone(second.next_cursor)

    def test_run_list_search_uses_sqlite_summary_without_reading_vault_files(self) -> None:
        request_path = (
            self.vault_root
            / "tenants"
            / "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
            / "creation_runs"
            / "run_owned"
            / "request.json"
        )
        request_path.unlink()

        page = self.reader.list_run_summaries(
            "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", cursor=None, page_size=20, search="tenant RUN"
        )

        self.assertEqual([item["publicRunId"] for item in page.items], ["run_owned"])
        self.assertEqual(page.items[0]["title"], "Tenant run")
