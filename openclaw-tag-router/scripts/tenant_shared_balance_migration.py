#!/usr/bin/env python3
"""Preflight, apply, and verify CM1 tenant shared-balance migration 036."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "openclaw_app" / "migrations" / "canonical" / "036_tenant_shared_balance.sql"
DSN_ENVIRONMENT_KEY = "OPENCLAW_ACCOUNT_DATABASE_URL"
PREDECESSOR_MIGRATION_ID = "cm1-035-document-resource-filename-check"
MIGRATION_ID = "cm1-036-tenant-shared-balance"
LOCK_KEY = "openclaw.cm1.tenant-shared-balance.v1"
CM1_ID = re.compile(r"^cm1-(\d{3})(?:-|$)")
TRANSACTION_CONTROL = re.compile(r"^\s*(?:BEGIN|COMMIT|ROLLBACK)\s*;", re.IGNORECASE | re.MULTILINE)


class MigrationToolError(RuntimeError):
    pass


class Cursor(Protocol):
    def fetchall(self) -> list[Sequence[Any]]: ...
    def fetchone(self) -> Sequence[Any] | None: ...


class Connection(Protocol):
    def execute(self, query: str, params: Sequence[Any] | None = None) -> Cursor: ...


@dataclass(frozen=True)
class MigrationIdentity:
    migration_id: str
    checksum: str
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class LedgerState:
    predecessor: MigrationIdentity
    target: MigrationIdentity | None


def migration_sql() -> str:
    try:
        sql = MIGRATION_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise MigrationToolError("migration source is unavailable") from exc
    if not sql.strip():
        raise MigrationToolError("migration source is empty")
    if TRANSACTION_CONTROL.search(sql):
        raise MigrationToolError("migration source must not control transactions")
    return sql


def target_identity(sql: str) -> MigrationIdentity:
    return MigrationIdentity(
        MIGRATION_ID,
        hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        (PREDECESSOR_MIGRATION_ID,),
    )


def _dependencies(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise MigrationToolError("migration ledger dependency payload is invalid")
    return tuple(value)


def _identity(row: Sequence[Any]) -> MigrationIdentity:
    if len(row) != 3 or not all(isinstance(value, str) for value in row[:2]):
        raise MigrationToolError("migration ledger row is invalid")
    return MigrationIdentity(row[0], row[1], _dependencies(row[2]))


def require_ledger_schema(connection: Connection) -> None:
    rows = connection.execute(
        """SELECT column_name, data_type, udt_name
           FROM information_schema.columns
           WHERE table_schema = 'openclaw_account' AND table_name = 'schema_migrations'"""
    ).fetchall()
    actual = {str(name): (str(data_type), str(udt_name)) for name, data_type, udt_name in rows}
    expected = {
        "migration_id": ("text", "text"),
        "checksum": ("character", "bpchar"),
        "depends_on": ("ARRAY", "_text"),
        "applied_at": ("timestamp with time zone", "timestamptz"),
    }
    if any(actual.get(name) != definition for name, definition in expected.items()):
        raise MigrationToolError("CM1 migration ledger schema is not available")


def read_ledger_state(connection: Connection) -> LedgerState:
    rows = connection.execute(
        """SELECT migration_id, checksum, depends_on
           FROM openclaw_account.schema_migrations
           WHERE migration_id LIKE 'cm1-%' ORDER BY migration_id"""
    ).fetchall()
    identities = [_identity(row) for row in rows]
    by_id = {identity.migration_id: identity for identity in identities}
    predecessor = by_id.get(PREDECESSOR_MIGRATION_ID)
    if predecessor is None:
        raise MigrationToolError(f"exact CM1 predecessor {PREDECESSOR_MIGRATION_ID} is absent")
    versions = [int(match.group(1)) for item in identities if (match := CM1_ID.match(item.migration_id))]
    if not versions or max(versions) > 36 or (max(versions) == 36 and MIGRATION_ID not in by_id):
        raise MigrationToolError("CM1 ledger has an unexpected successor")
    return LedgerState(predecessor, by_id.get(MIGRATION_ID))


def preflight_state(connection: Connection, expected: MigrationIdentity) -> LedgerState:
    require_ledger_schema(connection)
    state = read_ledger_state(connection)
    if state.target is not None and state.target != expected:
        raise MigrationToolError("cm1-036 ledger identity does not match migration source")
    return state


def _names(connection: Connection, query: str, params: Sequence[Any]) -> set[str]:
    return {str(row[0]) for row in connection.execute(query, params).fetchall()}


def verify_schema(connection: Connection, expected: MigrationIdentity) -> None:
    state = preflight_state(connection, expected)
    if state.target != expected:
        raise MigrationToolError("cm1-036 ledger row is absent")

    columns = _names(
        connection,
        """SELECT table_name || '.' || column_name FROM information_schema.columns
           WHERE table_schema = 'openclaw_account' AND (
             (table_name = 'model_operations' AND column_name = 'actor_user_id') OR
             (table_name = 'usage_events' AND column_name = 'actor_user_id') OR
             (table_name = 'plans' AND column_name IN ('audience', 'product_kind')))""",
        (),
    )
    required_columns = {"model_operations.actor_user_id", "usage_events.actor_user_id", "plans.audience", "plans.product_kind"}
    if columns != required_columns:
        raise MigrationToolError("shared-balance columns are incomplete")

    constraints = _names(
        connection,
        """SELECT conname FROM pg_constraint
           WHERE connamespace = 'openclaw_account'::regnamespace AND conname = ANY(%s)""",
        (["model_operations_actor_tenant_member_fkey", "usage_events_actor_tenant_member_fkey", "plans_audience_valid", "plans_product_kind_valid"],),
    )
    required_constraints = {"model_operations_actor_tenant_member_fkey", "usage_events_actor_tenant_member_fkey", "plans_audience_valid", "plans_product_kind_valid"}
    if constraints != required_constraints:
        raise MigrationToolError("shared-balance constraints are incomplete")

    indexes = _names(
        connection,
        """SELECT indexname FROM pg_indexes
           WHERE schemaname = 'openclaw_account' AND indexname = ANY(%s)""",
        (["model_operations_tenant_actor_created_idx", "usage_events_tenant_actor_created_idx"],),
    )
    if indexes != {"model_operations_tenant_actor_created_idx", "usage_events_tenant_actor_created_idx"}:
        raise MigrationToolError("shared-balance indexes are incomplete")

    triggers = _names(
        connection,
        """SELECT tgname FROM pg_trigger
           WHERE tgrelid IN ('openclaw_account.model_operations'::regclass, 'openclaw_account.usage_events'::regclass)
             AND NOT tgisinternal AND tgname = ANY(%s)""",
        (["model_operations_actual_actor_membership", "usage_events_actual_actor_membership"],),
    )
    if triggers != {"model_operations_actual_actor_membership", "usage_events_actual_actor_membership"}:
        raise MigrationToolError("shared-balance membership triggers are incomplete")

    plan_row = connection.execute(
        """SELECT count(*) FILTER (WHERE code = ANY(%s) AND audience = 'all' AND product_kind = 'balance_pack'),
                  count(*) FILTER (WHERE status = 'active' AND currency = 'credit' AND price_cny = credit_amount)
           FROM openclaw_account.plans""",
        (["mediaclaw-cny-1", "mediaclaw-cny-5", "mediaclaw-cny-20", "mediaclaw-cny-50", "mediaclaw-cny-100", "mediaclaw-cny-500"],),
    ).fetchone()
    if plan_row != (6, 6):
        raise MigrationToolError("shared-balance plan catalog classification is incomplete")


def record_migration(connection: Connection, expected: MigrationIdentity) -> None:
    connection.execute(
        """INSERT INTO openclaw_account.schema_migrations(migration_id, checksum, depends_on)
           VALUES (%s, %s, ARRAY[%s]::text[])""",
        (expected.migration_id, expected.checksum, expected.depends_on[0]),
    )
    row = connection.execute(
        """SELECT migration_id, checksum, depends_on FROM openclaw_account.schema_migrations
           WHERE migration_id = %s""",
        (expected.migration_id,),
    ).fetchone()
    if row is None or _identity(row) != expected:
        raise MigrationToolError("cm1-036 ledger readback does not match")


def _result(status: str, expected: MigrationIdentity, predecessor: MigrationIdentity) -> dict[str, Any]:
    return {"status": status, "migrationId": expected.migration_id, "checksum": expected.checksum, "predecessor": predecessor.migration_id}


def preflight(connection: Connection, expected: MigrationIdentity) -> dict[str, Any]:
    state = preflight_state(connection, expected)
    return _result("already_applied" if state.target else "ready", expected, state.predecessor)


def apply(connection: Connection, sql: str, expected: MigrationIdentity) -> dict[str, Any]:
    connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
    state = preflight_state(connection, expected)
    if state.target is None:
        connection.execute(sql)
        record_migration(connection, expected)
        status = "applied"
    else:
        status = "already_applied"
    verify_schema(connection, expected)
    return _result(status, expected, state.predecessor)


def verify(connection: Connection, expected: MigrationIdentity) -> dict[str, Any]:
    verify_schema(connection, expected)
    return _result("verified", expected, MigrationIdentity(PREDECESSOR_MIGRATION_ID, "", ()))


def _database_url() -> str:
    value = os.environ.get(DSN_ENVIRONMENT_KEY, "").strip()
    if not value:
        raise MigrationToolError(f"{DSN_ENVIRONMENT_KEY} is required")
    return value


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="execute migration and ledger write")
    action.add_argument("--verify", action="store_true", help="read-only schema and ledger verification")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sql = migration_sql()
        expected = target_identity(sql)
        dsn = _database_url()
        import psycopg
        with psycopg.connect(dsn, autocommit=False) as connection:
            if args.apply:
                with connection.transaction():
                    result = apply(connection, sql, expected)
            else:
                with connection.transaction():
                    connection.execute("SET TRANSACTION READ ONLY")
                    result = verify(connection, expected) if args.verify else preflight(connection, expected)
    except MigrationToolError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"status": "blocked", "error": "database operation failed"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
