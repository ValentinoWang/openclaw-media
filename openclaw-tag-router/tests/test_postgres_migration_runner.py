from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_postgres_migrations.py"
MANIFEST_PATH = ROOT / "openclaw_app" / "migrations" / "postgres_manifest.json"
SPEC = importlib.util.spec_from_file_location("run_postgres_migrations", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


EXPECTED_IDS = [
    "cm1-003-openclaw-account-billing",
    "cm1-004-authentication",
    "cm1-005-registration-affiliate",
    "cm1-006-retail-billing",
    "cm1-007-retail-fulfillment",
    "cm1-008-retail-plan-catalog",
    "cm1-009-retail-admin",
    "cm1-010-persistent-admission-codes",
    "cm1-013-media-product",
    "cm1-015-b01-overview",
    "cm1-016-b02-tracks",
    "cm1-017-b03-assets",
    "cm1-018-b04-decisions",
    "cm1-019-b05-runs",
    "cm1-020-b06-publishing",
    "cm1-021-b07-reviews",
    "cm1-022-b08-usage-billing",
    "cm1-023-b10-admin-overview",
    "cm1-024-b12-admin-tenants",
    "cm1-025-b13-admin-billing",
    "cm1-026-b14-admin-upstreams",
    "cm1-027-media-document-runtime",
    "cm1-028-tenant-foundation",
    "cm1-029-lark-tenant-binding",
    "cm1-030-member-sessions",
    "cm1-031-migration-audit-idempotency",
    "cm1-032-lark-read-mirrors",
    "cm1-033-document-resources",
    "cm1-034-document-resource-ownership",
    "cm1-035-document-resource-filename-check",
    "cm1-036-tenant-shared-balance",
    "cm1-037-affiliate-profile-coverage",
]


class TransactionProbe:
    def __init__(self) -> None:
        self.state: list[str] = []
        self.committed_state: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1
        self.committed_state = list(self.state)

    def rollback(self) -> None:
        self.rollbacks += 1
        self.state = list(self.committed_state)


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = runner.load_manifest(MANIFEST_PATH)

    def test_exact_closed_inventory_and_order(self) -> None:
        self.assertEqual([entry["id"] for entry in runner.ordered_migrations(self.manifest)], EXPECTED_IDS)
        self.assertEqual(len(self.manifest["migrations"]), 32)
        self.assertEqual(len(self.manifest["excludedMigrations"]), 7)
        self.assertEqual(
            len(self.manifest["migrations"]) + len(self.manifest["excludedMigrations"]),
            39,
        )
        runner.validate_source_tree(ROOT, self.manifest)

    def test_source_and_ledger_checksums_are_independently_pinned(self) -> None:
        legacy = next(entry for entry in self.manifest["migrations"] if entry["id"] == "cm1-029-lark-tenant-binding")
        self.assertNotEqual(legacy["sourceSha256"], legacy["ledgerChecksum"])
        current = next(entry for entry in self.manifest["migrations"] if entry["id"] == "cm1-036-tenant-shared-balance")
        self.assertEqual(current["sourceSha256"], current["ledgerChecksum"])
        changed = json.loads(json.dumps(self.manifest))
        changed["migrations"][-1]["ledgerChecksum"] = "invalid"
        with self.assertRaisesRegex(runner.ManifestError, "invalid ledger checksum"):
            runner.validate_manifest(changed)

    def test_manifest_order_is_not_topologically_rebatched(self) -> None:
        changed = json.loads(json.dumps(self.manifest))
        changed["migrations"][9], changed["migrations"][10] = (
            changed["migrations"][10],
            changed["migrations"][9],
        )
        with self.assertRaisesRegex(runner.ManifestError, "exact contiguous canonical order"):
            runner.validate_manifest(changed)

    def test_dependency_must_point_strictly_backward(self) -> None:
        changed = json.loads(json.dumps(self.manifest))
        changed["migrations"][0]["dependsOn"] = [EXPECTED_IDS[-1]]
        with self.assertRaisesRegex(runner.ManifestError, "must point backward"):
            runner.validate_manifest(changed)

    def test_b03_legacy_marker_is_exact(self) -> None:
        b03 = next(entry for entry in self.manifest["migrations"] if entry["id"] == "cm1-017-b03-assets")
        self.assertEqual(b03["legacyMediaLedger"], [{"version": 14, "name": "b03_assets_read_model"}])
        changed = json.loads(json.dumps(self.manifest))
        next(entry for entry in changed["migrations"] if entry["id"] == "cm1-017-b03-assets")[
            "legacyMediaLedger"
        ][0]["name"] = "b03_assets"
        with self.assertRaisesRegex(runner.ManifestError, "B03 legacy marker"):
            runner.validate_manifest(changed)

    def test_runtime_source_transforms_are_forbidden(self) -> None:
        changed = json.loads(json.dumps(self.manifest))
        changed["migrations"][0]["sourceTransforms"] = []
        with self.assertRaisesRegex(runner.ManifestError, "runtime source transforms are forbidden"):
            runner.validate_manifest(changed)

    def test_b05_is_physically_tenant_scoped(self) -> None:
        sql = (ROOT / "openclaw_app" / "migrations" / "canonical" / "019_b05_runs.sql").read_text(encoding="utf-8")
        self.assertEqual(sql.count("FOREIGN KEY (tenant_id, public_run_id)"), 3)
        self.assertEqual(
            sql.count("REFERENCES media_product.creation_runs(tenant_id, public_id) ON DELETE RESTRICT"),
            3,
        )
        self.assertNotIn("creation_runs(public_id)", sql)

    def test_execution_sources_reject_noncanonical_sql(self) -> None:
        for sql, message in (
            ("BEGIN; SELECT 1;", "transaction control"),
            ("INSERT INTO openclaw_account.schema_migrations VALUES ('x');", "migration ledgers"),
            ("PRAGMA foreign_keys = ON;", "SQLite PRAGMA"),
        ):
            with self.subTest(sql=sql), self.assertRaisesRegex(runner.SourceError, message):
                runner.normalize_sql(sql)

    def test_residue_guard_is_scoped_to_the_canonical_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / self.manifest["source"]["migrationDirectory"]
            shutil.copytree(ROOT / self.manifest["source"]["migrationDirectory"], canonical)
            outside = root / "openclaw_app" / "unrelated.py.orig"
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.write_text("unrelated dirty worktree residue", encoding="utf-8")
            runner.validate_source_tree(root, self.manifest)
            (canonical / "blocked.sql.orig").write_text("stale migration", encoding="utf-8")
            with self.assertRaisesRegex(runner.SourceError, "forbidden residue"):
                runner.validate_source_tree(root, self.manifest)


class AtomicApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = [
            {
                "id": "cm1-003-a",
                "sourceSha256": "1" * 64,
                "ledgerChecksum": "a" * 64,
                "dependsOn": [],
                "executionStatements": ["SELECT 1;"],
            },
            {
                "id": "cm1-004-b",
                "sourceSha256": "2" * 64,
                "ledgerChecksum": "b" * 64,
                "dependsOn": ["cm1-003-a"],
                "executionStatements": ["SELECT 2;"],
            },
            {
                "id": "cm1-005-c",
                "sourceSha256": "3" * 64,
                "ledgerChecksum": "c" * 64,
                "dependsOn": ["cm1-004-b"],
                "executionStatements": ["SELECT 3;"],
            },
        ]

    def _patches(self, connection: TransactionProbe, *, fail_statement: str | None = None, verify_error=None):
        def prepare(_connection, _manifest, _mode):
            connection.state.append("legacy-cutover")
            return set()

        def execute(_connection, statement, params=None):
            del params
            connection.state.append(f"ddl:{statement}")
            if statement == fail_statement:
                raise RuntimeError("injected late DDL failure")

        def record(_connection, entry):
            connection.state.append(f"ledger:{entry['id']}")

        def verify(_connection, _manifest):
            connection.state.append("verified")
            if verify_error is not None:
                raise verify_error

        return (
            mock.patch.object(runner, "build_plan", return_value=self.entries),
            mock.patch.object(runner, "_verify_server_version"),
            mock.patch.object(runner, "_lock", side_effect=lambda _connection: connection.state.append("locked")),
            mock.patch.object(runner, "prepare_ledger", side_effect=prepare),
            mock.patch.object(runner, "_ledger_row", return_value=None),
            mock.patch.object(runner, "_cursor_execute", side_effect=execute),
            mock.patch.object(runner, "_record_migration", side_effect=record),
            mock.patch.object(runner, "verify_database", side_effect=verify),
        )

    def _apply_with(self, connection: TransactionProbe, **kwargs):
        patches = self._patches(connection, **kwargs)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            return runner.apply_migrations(connection, Path("."), {}, "current")

    def test_success_commits_exactly_once_after_verification(self) -> None:
        connection = TransactionProbe()
        applied = self._apply_with(connection)
        self.assertEqual(applied, [entry["id"] for entry in self.entries])
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertEqual(connection.committed_state[-1], "verified")

    def test_late_migration_failure_rolls_back_legacy_cutover_and_prior_ddl(self) -> None:
        connection = TransactionProbe()
        with self.assertRaisesRegex(RuntimeError, "injected late DDL failure"):
            self._apply_with(connection, fail_statement="SELECT 3;")
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.state, [])

    def test_verification_failure_rolls_back_everything(self) -> None:
        connection = TransactionProbe()
        with self.assertRaisesRegex(runner.LedgerError, "catalog mismatch"):
            self._apply_with(connection, verify_error=runner.LedgerError("catalog mismatch"))
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.state, [])

    def test_unknown_legacy_state_rolls_back_without_commit(self) -> None:
        connection = TransactionProbe()
        patches = self._patches(connection)
        with (
            patches[0],
            patches[1],
            patches[2],
            mock.patch.object(
                runner,
                "prepare_ledger",
                side_effect=runner.LedgerError("unknown legacy account migration revision"),
            ),
        ):
            with self.assertRaisesRegex(runner.LedgerError, "unknown legacy"):
                runner.apply_migrations(connection, Path("."), {}, "current")
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.state, [])


class DatabaseVerificationTests(unittest.TestCase):
    def test_obsolete_candidate_ledger_is_rejected(self) -> None:
        manifest = runner.load_manifest(MANIFEST_PATH)

        def table_exists(_connection, schema: str, table: str) -> bool:
            return (schema, table) == ("openclaw_account", "postgres_migration_ledger")

        with (
            mock.patch.object(runner, "_verify_server_version"),
            mock.patch.object(runner, "_table_columns", return_value=set(runner.CANONICAL_LEDGER_COLUMNS)),
            mock.patch.object(runner, "_table_exists", side_effect=table_exists),
        ):
            with self.assertRaisesRegex(runner.LedgerError, "obsolete candidate postgres_migration_ledger"):
                runner.verify_database(object(), manifest)

    def test_immutability_probe_checks_update_and_delete(self) -> None:
        connection = object()
        with mock.patch.object(runner, "_cursor_execute") as execute:
            runner._verify_ledger_immutability(connection)
        statement = execute.call_args.args[1]
        self.assertIn("UPDATE openclaw_account.schema_migrations", statement)
        self.assertIn("DELETE FROM openclaw_account.schema_migrations", statement)
        self.assertEqual(len(execute.call_args.args), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
