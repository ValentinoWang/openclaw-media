from __future__ import annotations

import inspect
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from openclaw_app.services.canonical_resource_contracts import (
    CANONICAL_RESOURCE_CONTRACTS,
    CONTENT_OS_POST_REVIEW_OWNER_CONTRACT,
    CONTENT_OS_TASK_OWNER_CONTRACT,
    TENANT_PROJECTION_FIELD,
)
from openclaw_app.services.resource_owner_registry import (
    ResourceOwnerConflict,
    ResourceOwnerInvalid,
    ResourceOwnerNotFound,
    ResourceOwnerProjectionMismatch,
    ResourceOwnerRegistry,
    require_tenant_id,
)


RESOURCE_TYPE = "content_os.task"
RESOURCE_ID = "task_01HZYX"


class ResourceOwnerRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "resource-owners.sqlite3"
        self.registry = ResourceOwnerRegistry(self.db_path, clock=lambda: 1_700_000_000)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def create_owner(
        self,
        *,
        resource_id: str = RESOURCE_ID,
        tenant_id: str = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
    ):
        return self.registry.create(
            RESOURCE_TYPE,
            resource_id,
            session_tenant_id=tenant_id,
        )

    def test_uuid_tenant_id_is_canonical(self) -> None:
        self.assertEqual(require_tenant_id("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"), "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")

        invalid_values = (None, "", " ", "0", 0, -1, "-1", "01", "1.0", "abc", True)
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ResourceOwnerInvalid):
                    require_tenant_id(value)  # type: ignore[arg-type]

    def test_resource_type_must_be_registered(self) -> None:
        with self.assertRaises(ResourceOwnerInvalid):
            self.registry.create(
                "unknown.resource",
                RESOURCE_ID,
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            )

    def test_create_and_get_use_one_canonical_owner(self) -> None:
        created = self.create_owner()
        loaded = self.registry.get(RESOURCE_TYPE, RESOURCE_ID)

        self.assertEqual(created, loaded)
        self.assertEqual(loaded.tenant_id, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        self.assertEqual(loaded.owner_revision, 1)
        self.assertEqual(loaded.status, "active")

    def test_duplicate_resource_conflicts_for_same_or_different_tenant(self) -> None:
        self.create_owner()

        for tenant_id in ("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"):
            with self.subTest(tenant_id=tenant_id):
                with self.assertRaises(ResourceOwnerConflict):
                    self.registry.create(
                        RESOURCE_TYPE,
                        RESOURCE_ID,
                        session_tenant_id=tenant_id,
                    )

    def test_create_does_not_accept_caller_supplied_tenant_id_keyword(self) -> None:
        parameters = inspect.signature(self.registry.create).parameters
        self.assertIn("session_tenant_id", parameters)
        self.assertNotIn("tenant_id", parameters)

        with self.assertRaises(TypeError):
            self.registry.create(  # type: ignore[call-arg]
                RESOURCE_TYPE,
                RESOURCE_ID,
                tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            )

    def test_cross_tenant_and_absent_assertions_are_indistinguishable(self) -> None:
        self.create_owner()

        with self.assertRaises(ResourceOwnerNotFound) as cross_tenant:
            self.registry.assert_owner(
                RESOURCE_TYPE,
                RESOURCE_ID,
                session_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
            )
        with self.assertRaises(ResourceOwnerNotFound) as absent:
            self.registry.assert_owner(
                RESOURCE_TYPE,
                "task_absent",
                session_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
            )

        self.assertEqual(str(cross_tenant.exception), str(absent.exception))

    def test_list_is_scoped_to_session_tenant(self) -> None:
        self.create_owner(resource_id="task_a", tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        self.create_owner(resource_id="task_b", tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45")

        tenant_a = self.registry.list_by_tenant("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        tenant_b = self.registry.list_by_tenant("775e0c03-febc-4a39-8ad0-3e18bb8a6d45")

        self.assertEqual([owner.canonical_resource_id for owner in tenant_a], ["task_a"])
        self.assertEqual([owner.canonical_resource_id for owner in tenant_b], ["task_b"])

    def test_creation_run_summary_search_and_pagination_are_tenant_first(self) -> None:
        for tenant_id, run_id, title, created_at in (
            ("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", "run_old", "Alpha launch", "2026-07-01T00:00:00+00:00"),
            ("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", "run_new", "Beta launch", "2026-07-02T00:00:00+00:00"),
            ("775e0c03-febc-4a39-8ad0-3e18bb8a6d45", "run_private", "Beta private", "2026-07-03T00:00:00+00:00"),
        ):
            self.registry.create("media.creation_run", run_id, session_tenant_id=tenant_id)
            self.registry.upsert_creation_run_summary(
                run_id,
                session_tenant_id=tenant_id,
                fields={
                    "input_summary": title,
                    "status": "success",
                    "entrypoint": "【创作】",
                    "created_at": created_at,
                },
            )

        page = self.registry.list_creation_run_summaries(
            "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", search="launch", limit=1, offset=0
        )
        next_page = self.registry.list_creation_run_summaries(
            "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", search="launch", limit=1, offset=1
        )

        self.assertEqual([item.canonical_resource_id for item in page], ["run_new"])
        self.assertEqual([item.canonical_resource_id for item in next_page], ["run_old"])
        self.assertNotIn(
            "run_private",
            [item.canonical_resource_id for item in page + next_page],
        )

    def test_creation_run_summary_requires_matching_active_owner(self) -> None:
        self.registry.create("media.creation_run", "run_owned", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")

        with self.assertRaises(ResourceOwnerNotFound):
            self.registry.upsert_creation_run_summary(
                "run_owned",
                session_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
                fields={"input_summary": "Cross tenant"},
            )

        self.registry.archive(
            "media.creation_run", "run_owned", session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
        )
        self.assertEqual(
            self.registry.list_creation_run_summaries(
                "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", search="", limit=20, offset=0
            ),
            [],
        )

    def test_list_all_crosses_internal_page_boundary(self) -> None:
        for index in range(501):
            self.create_owner(resource_id=f"task_page_{index:03d}", tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")

        owners = self.registry.list_all_by_tenant("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", resource_type=RESOURCE_TYPE)

        self.assertEqual(len(owners), 501)
        self.assertEqual(owners[0].canonical_resource_id, "task_page_000")
        self.assertEqual(owners[-1].canonical_resource_id, "task_page_500")

    def test_archive_is_tenant_scoped_and_not_repeatable(self) -> None:
        self.create_owner()

        with self.assertRaises(ResourceOwnerNotFound):
            self.registry.archive(
                RESOURCE_TYPE,
                RESOURCE_ID,
                session_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
            )

        archived = self.registry.archive(
            RESOURCE_TYPE,
            RESOURCE_ID,
            session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
        )
        self.assertEqual(archived.status, "archived")
        self.assertEqual(archived.archived_at, 1_700_000_000)

        with self.assertRaises(ResourceOwnerNotFound):
            self.registry.archive(
                RESOURCE_TYPE,
                RESOURCE_ID,
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            )
        with self.assertRaises(ResourceOwnerNotFound):
            self.registry.assert_owner(
                RESOURCE_TYPE,
                RESOURCE_ID,
                session_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            )

        self.assertEqual(self.registry.get(RESOURCE_TYPE, RESOURCE_ID), archived)
        self.assertEqual(self.registry.list_by_tenant("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"), [])
        self.assertEqual(
            self.registry.list_by_tenant("618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", include_archived=True),
            [archived],
        )

    def test_ordinary_registry_api_has_no_owner_update_method(self) -> None:
        forbidden_methods = {
            "update_owner",
            "set_owner",
            "change_owner",
            "repair_owner_from_feishu",
            "transfer",
            "list_transfers",
        }
        self.assertTrue(forbidden_methods.isdisjoint(dir(self.registry)))

        self.create_owner()
        with sqlite3.connect(self.db_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE resource_owners
                    SET tenant_id = '202', owner_revision = 2
                    WHERE resource_type = ? AND canonical_resource_id = ?
                    """,
                    (RESOURCE_TYPE, RESOURCE_ID),
                )
        self.assertEqual(self.registry.get(RESOURCE_TYPE, RESOURCE_ID).tenant_id, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")

    def test_feishu_projection_is_derived_from_canonical_owner(self) -> None:
        self.create_owner()

        projection = self.registry.build_feishu_projection(RESOURCE_TYPE, RESOURCE_ID)

        self.assertEqual(projection, {TENANT_PROJECTION_FIELD: "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"})

    def test_matching_projection_does_not_create_repair(self) -> None:
        self.create_owner()

        result = self.registry.inspect_feishu_projection(
            RESOURCE_TYPE,
            RESOURCE_ID,
            observed_tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37",
            projection_source="feishu:content_os_tasks/rec_01",
        )

        self.assertIsNone(result)
        self.assertEqual(self.registry.list_repairs(), [])

    def test_projection_mismatches_create_deduplicated_repairs_only(self) -> None:
        cases = (
            (None, "missing", None, "rec_missing"),
            ("tenant-a", "invalid", "tenant-a", "rec_invalid"),
            ("775e0c03-febc-4a39-8ad0-3e18bb8a6d45", "mismatch", "775e0c03-febc-4a39-8ad0-3e18bb8a6d45", "rec_mismatch"),
        )
        for observed, kind, stored_observed, record_id in cases:
            with self.subTest(kind=kind):
                resource_id = f"task_{kind}"
                self.create_owner(resource_id=resource_id)
                source = f"feishu:content_os_tasks/{record_id}"
                first = self.registry.inspect_feishu_projection(
                    RESOURCE_TYPE,
                    resource_id,
                    observed_tenant_id=observed,
                    projection_source=source,
                )
                duplicate = self.registry.inspect_feishu_projection(
                    RESOURCE_TYPE,
                    resource_id,
                    observed_tenant_id=observed,
                    projection_source=source,
                )

                self.assertIsNotNone(first)
                self.assertEqual(duplicate, first)
                self.assertEqual(first.mismatch_kind, kind)  # type: ignore[union-attr]
                self.assertEqual(first.observed_tenant_id, stored_observed)  # type: ignore[union-attr]
                self.assertEqual(first.canonical_tenant_id, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")  # type: ignore[union-attr]
                self.assertEqual(self.registry.get(RESOURCE_TYPE, resource_id).tenant_id, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")

        self.assertEqual(len(self.registry.list_repairs()), 3)

    def test_projection_assertion_fails_closed_after_queueing_repair(self) -> None:
        self.create_owner()

        with self.assertRaises(ResourceOwnerProjectionMismatch):
            self.registry.assert_feishu_projection(
                RESOURCE_TYPE,
                RESOURCE_ID,
                observed_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
                projection_source="feishu:content_os_tasks/rec_01",
            )

        self.assertEqual(self.registry.get(RESOURCE_TYPE, RESOURCE_ID).tenant_id, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        self.assertEqual(len(self.registry.list_repairs()), 1)

    def test_resolving_repair_never_changes_owner(self) -> None:
        self.create_owner()
        repair = self.registry.inspect_feishu_projection(
            RESOURCE_TYPE,
            RESOURCE_ID,
            observed_tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45",
            projection_source="feishu:content_os_tasks/rec_01",
        )
        self.assertIsNotNone(repair)

        self.registry.resolve_repair(
            repair.repair_id,  # type: ignore[union-attr]
            actor_user_id="3bf214ac-5948-4e30-9bd1-5c50cdd62a3c",
            resolution_note="projection corrected outside owner registry",
        )

        self.assertEqual(self.registry.get(RESOURCE_TYPE, RESOURCE_ID).tenant_id, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        self.assertEqual(self.registry.list_repairs(), [])
        resolved = self.registry.list_repairs(status="resolved")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].repair_id, repair.repair_id)  # type: ignore[union-attr]

    def test_sqlite_uniqueness_holds_across_concurrent_registry_instances(self) -> None:
        second_registry = ResourceOwnerRegistry(self.db_path)
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        outcome_lock = threading.Lock()

        def create(registry: ResourceOwnerRegistry, tenant_id: str) -> None:
            barrier.wait()
            try:
                registry.create(
                    RESOURCE_TYPE,
                    RESOURCE_ID,
                    session_tenant_id=tenant_id,
                )
                outcome = "created"
            except ResourceOwnerConflict:
                outcome = "conflict"
            with outcome_lock:
                outcomes.append(outcome)

        threads = (
            threading.Thread(target=create, args=(self.registry, "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")),
            threading.Thread(target=create, args=(second_registry, "775e0c03-febc-4a39-8ad0-3e18bb8a6d45")),
        )
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ["created", "conflict"])
        self.assertIn(self.registry.get(RESOURCE_TYPE, RESOURCE_ID).tenant_id, {"618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"})

    def test_database_enforces_positive_decimal_tenant_invariant(self) -> None:
        invalid_values = ("", "0", "01", "-1", "1.0", "abc")
        for index, tenant_id in enumerate(invalid_values):
            with self.subTest(tenant_id=tenant_id):
                with sqlite3.connect(self.db_path) as connection:
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(
                            """
                            INSERT INTO resource_owners (
                                resource_type, canonical_resource_id, tenant_id,
                                owner_revision, status, created_at
                            ) VALUES (?, ?, ?, 1, 'active', ?)
                            """,
                            (RESOURCE_TYPE, f"task_invalid_{index}", tenant_id, 1),
                        )

    def test_migration_is_single_owner_schema_source_without_fallback_fields(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "openclaw_app"
            / "migrations"
            / "001_resource_owner_registry.sql"
        )
        schema = migration.read_text(encoding="utf-8")

        self.assertEqual(schema.count("CREATE TABLE IF NOT EXISTS resource_owners"), 1)
        self.assertNotIn("legacy", schema.lower())
        self.assertNotIn("fallback", schema.lower())
        with sqlite3.connect(self.db_path) as connection:
            owner_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(resource_owners)")
            }
        self.assertEqual(
            owner_columns,
            {
                "resource_type",
                "canonical_resource_id",
                "tenant_id",
                "owner_revision",
                "status",
                "created_at",
                "archived_at",
            },
        )

    def test_content_os_contracts_are_projection_only(self) -> None:
        for resource_type, contract in (
            ("content_os.task", CONTENT_OS_TASK_OWNER_CONTRACT),
            ("content_os.post_review", CONTENT_OS_POST_REVIEW_OWNER_CONTRACT),
        ):
            with self.subTest(resource_type=resource_type):
                self.assertIn(resource_type, CANONICAL_RESOURCE_CONTRACTS)
                self.assertEqual(contract["resource_type"], resource_type)
                self.assertEqual(contract["tenant_projection_field"], TENANT_PROJECTION_FIELD)
                self.assertEqual(contract["authorization_source"], "resource_owner_registry")
                self.assertEqual(
                    contract["projection_direction"],
                    "canonical_owner_to_feishu_only",
                )
                self.assertEqual(contract["activation"], "pending_live_schema_readback")


if __name__ == "__main__":
    unittest.main()
