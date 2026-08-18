from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
TOOL_PATH = ROOT / "scripts" / "tenant_shared_balance_migration.py"
SPEC = importlib.util.spec_from_file_location("tenant_shared_balance_migration", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = tool
assert SPEC.loader is not None
SPEC.loader.exec_module(tool)


CHECKSUM = "a" * 64
PREDECESSOR = (
    "cm1-035-document-resource-filename-check",
    "b" * 64,
    ("cm1-034-document-resource-ownership",),
)
TARGET = (tool.MIGRATION_ID, CHECKSUM, (tool.PREDECESSOR_MIGRATION_ID,))


class Cursor:
    def __init__(self, rows=(), row=None):
        self.rows = list(rows)
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, *, target=None, extra_cm1=()):
        self.target = target
        self.extra_cm1 = list(extra_cm1)
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        if "schema_migrations" in query and "column_name, data_type" in query:
            return Cursor([
                ("migration_id", "text", "text"),
                ("checksum", "character", "bpchar"),
                ("depends_on", "ARRAY", "_text"),
                ("applied_at", "timestamp with time zone", "timestamptz"),
            ])
        if "WHERE migration_id LIKE 'cm1-%'" in query:
            rows = [PREDECESSOR, *self.extra_cm1]
            if self.target is not None:
                rows.append(self.target)
            return Cursor(rows)
        if "INSERT INTO openclaw_account.schema_migrations" in query:
            self.target = (params[0], params[1], (params[2],))
            return Cursor()
        if "WHERE migration_id = %s" in query:
            return Cursor(row=self.target)
        if "table_name ||" in query:
            return Cursor([
                ("model_operations.actor_user_id",),
                ("usage_events.actor_user_id",),
                ("plans.audience",),
                ("plans.product_kind",),
            ])
        if "FROM pg_constraint" in query or "FROM pg_indexes" in query or "FROM pg_trigger" in query:
            return Cursor([(name,) for name in params[0]])
        if "FROM openclaw_account.plans" in query:
            return Cursor(row=(6, 6))
        return Cursor()


def identity():
    return tool.MigrationIdentity(tool.MIGRATION_ID, CHECKSUM, (tool.PREDECESSOR_MIGRATION_ID,))


def test_preflight_requires_the_exact_cm1_035_terminal_predecessor():
    result = tool.preflight(Connection(), identity())
    assert result == {
        "status": "ready",
        "migrationId": tool.MIGRATION_ID,
        "checksum": CHECKSUM,
        "predecessor": "cm1-035-document-resource-filename-check",
    }


def test_preflight_rejects_unknown_cm1_successor():
    with pytest.raises(tool.MigrationToolError, match="unexpected successor"):
        tool.preflight(Connection(extra_cm1=[("cm1-037-other", "c" * 64, ())]), identity())


def test_apply_runs_sql_then_writes_and_reads_back_the_exact_ledger_identity():
    connection = Connection()
    result = tool.apply(connection, "ALTER TABLE example ADD COLUMN value text;", identity())
    assert result["status"] == "applied"
    migration_index = next(i for i, (query, _) in enumerate(connection.calls) if query.startswith("ALTER TABLE example"))
    ledger_index = next(i for i, (query, _) in enumerate(connection.calls) if "INSERT INTO openclaw_account.schema_migrations" in query)
    assert migration_index < ledger_index
    assert connection.target == TARGET


def test_apply_is_idempotent_only_for_the_exact_recorded_source_identity():
    connection = Connection(target=TARGET)
    result = tool.apply(connection, "ALTER TABLE example ADD COLUMN value text;", identity())
    assert result["status"] == "already_applied"
    assert not any(query.startswith("ALTER TABLE example") for query, _ in connection.calls)


def test_migration_transaction_control_is_rejected(monkeypatch, tmp_path: Path):
    source = tmp_path / "036.sql"
    source.write_text("BEGIN; SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(tool, "MIGRATION_PATH", source)
    with pytest.raises(tool.MigrationToolError, match="must not control transactions"):
        tool.migration_sql()


def test_cli_has_no_dsn_option():
    args = tool.parse_args(["--apply"])
    assert args.apply is True
    assert not hasattr(args, "dsn")
