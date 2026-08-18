#!/usr/bin/env python3
"""Apply the closed C-M1 PostgreSQL migration inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE.parent / "openclaw_app" / "migrations" / "postgres_manifest.json"
ID_RE = re.compile(r"^cm1-[0-9]{3}-[a-z0-9-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DOLLAR_TAG_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
CANONICAL_LEDGER_COLUMNS = ["migration_id", "checksum", "depends_on", "applied_at"]
LEGACY_LEDGER_COLUMNS = {"revision", "applied_at"}
LEGACY_MEDIA_LEDGER_COLUMNS = {"version", "name", "applied_at"}
LOCK_KEY = "openclaw.cm1.postgresql.migrations.v1"
class RunnerError(RuntimeError):
    """Expected migration validation or database-state failure."""


class ManifestError(RunnerError):
    pass


class SourceError(RunnerError):
    pass


class LedgerError(RunnerError):
    pass


def _row_value(row: Any, index: int, key: str) -> Any:
    if isinstance(row, Mapping):
        return row[key]
    return row[index]


def _cursor_execute(connection: Any, statement: str, params: Sequence[Any] | None = None) -> None:
    cursor = connection.cursor()
    try:
        if params is None:
            cursor.execute(statement)
        else:
            cursor.execute(statement, params)
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()


def _fetchall(connection: Any, statement: str, params: Sequence[Any] | None = None) -> list[Any]:
    cursor = connection.cursor()
    try:
        if params is None:
            cursor.execute(statement)
        else:
            cursor.execute(statement, params)
        return list(cursor.fetchall())
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()


def _fetchone(connection: Any, statement: str, params: Sequence[Any] | None = None) -> Any | None:
    cursor = connection.cursor()
    try:
        if params is None:
            cursor.execute(statement)
        else:
            cursor.execute(statement, params)
        return cursor.fetchone()
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()


def _commit(connection: Any) -> None:
    connection.commit()


def _rollback(connection: Any) -> None:
    rollback = getattr(connection, "rollback", None)
    if rollback is not None:
        rollback()


def _lock(connection: Any) -> None:
    _cursor_execute(
        connection,
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (LOCK_KEY,),
    )


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest: {path}: {exc}") from exc
    validate_manifest(manifest)
    return manifest


def _validate_relative_source(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{label} must be a string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ManifestError(f"{label} must be a safe relative path: {value!r}")
    if not value.startswith("openclaw_app/migrations/canonical/"):
        raise ManifestError(f"{label} must be inside openclaw_app/migrations: {value!r}")
    return value


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schemaVersion") != "openclaw.cm1.postgresql-migration-manifest.v2":
        raise ManifestError("unsupported manifest schemaVersion")
    contract = manifest.get("contract")
    if not isinstance(contract, Mapping):
        raise ManifestError("manifest contract is missing")
    if contract.get("runtimeDatabase") != "PostgreSQL":
        raise ManifestError("runtimeDatabase must be PostgreSQL")
    if contract.get("legacyRuntimeReadFallback") is not False:
        raise ManifestError("legacyRuntimeReadFallback must be false")
    if contract.get("dualWriteAllowed") is not False:
        raise ManifestError("dualWriteAllowed must be false")
    if contract.get("sourceInventoryIsClosed") is not True:
        raise ManifestError("sourceInventoryIsClosed must be true")
    if contract.get("ledgerTable") != "openclaw_account.schema_migrations":
        raise ManifestError("the canonical ledger table is fixed")
    if contract.get("ledgerColumns") != CANONICAL_LEDGER_COLUMNS:
        raise ManifestError("canonical ledger columns must be ordered and complete")

    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise ManifestError("manifest source section is missing")
    if source.get("migrationDirectory") != "openclaw_app/migrations/canonical":
        raise ManifestError("migrationDirectory must identify the closed remote inventory")
    if set(source.get("rejectSuffixes", [])) != {".orig", ".rej"}:
        raise ManifestError(".orig and .rej must both be rejected")
    normalization = source.get("normalization")
    normalization_keys = {
        "rejectTransactionControl",
        "rejectLegacyLedgerStatements",
        "rejectPragmaStatements",
    }
    if (
        not isinstance(normalization, Mapping)
        or set(normalization) != normalization_keys
        or any(normalization.get(key) is not True for key in normalization_keys)
    ):
        raise ManifestError("unsafe SQL execution contract")

    entries = manifest.get("migrations")
    excluded = manifest.get("excludedMigrations")
    if not isinstance(entries, list) or len(entries) != 32:
        raise ManifestError("migrations must contain the exact 32-entry C-M1 inventory")
    if not isinstance(excluded, list) or len(excluded) != 7:
        raise ManifestError("excludedMigrations must contain the exact seven excluded sources")

    ids: set[str] = set()
    sources: set[str] = set()
    orders: set[int] = set()
    legacy_revisions: dict[str, str] = {}
    legacy_media_keys: dict[tuple[int, str], str] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ManifestError("migration entry must be an object")
        migration_id = entry.get("id")
        if not isinstance(migration_id, str) or not ID_RE.fullmatch(migration_id):
            raise ManifestError(f"invalid immutable migration id: {migration_id!r}")
        if migration_id in ids:
            raise ManifestError(f"duplicate migration id: {migration_id}")
        ids.add(migration_id)
        source_path = _validate_relative_source(entry.get("source"), "migration source")
        if source_path in sources:
            raise ManifestError(f"duplicate source path: {source_path}")
        sources.add(source_path)
        source_checksum = entry.get("sourceSha256")
        if not isinstance(source_checksum, str) or not SHA256_RE.fullmatch(source_checksum):
            raise ManifestError(f"invalid source checksum for {migration_id}")
        ledger_checksum = entry.get("ledgerChecksum")
        if not isinstance(ledger_checksum, str) or not SHA256_RE.fullmatch(ledger_checksum):
            raise ManifestError(f"invalid ledger checksum for {migration_id}")
        order = entry.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order <= 0 or order in orders:
            raise ManifestError(f"migration order must be unique and positive: {migration_id}")
        orders.add(order)
        dependencies = entry.get("dependsOn")
        if not isinstance(dependencies, list):
            raise ManifestError(f"dependsOn must be a unique list: {migration_id}")
        if any(not isinstance(dependency, str) or not dependency for dependency in dependencies):
            raise ManifestError(f"dependsOn entries must be non-empty strings: {migration_id}")
        if len(dependencies) != len(set(dependencies)):
            raise ManifestError(f"dependsOn must be a unique list: {migration_id}")
        if "sourceTransforms" in entry:
            raise ManifestError(f"runtime source transforms are forbidden: {migration_id}")
        account_revisions = entry.get("legacyAccountRevisions", [])
        if not isinstance(account_revisions, list) or len(account_revisions) != len(set(account_revisions)):
            raise ManifestError(f"legacyAccountRevisions must be a unique list: {migration_id}")
        for revision in account_revisions:
            if not isinstance(revision, str) or not revision:
                raise ManifestError(f"legacy account revision must be non-empty: {migration_id}")
            previous = legacy_revisions.get(revision)
            if previous is not None:
                raise ManifestError(f"legacy account revision is mapped twice: {revision}")
            legacy_revisions[revision] = migration_id
        media_ledger = entry.get("legacyMediaLedger", [])
        if not isinstance(media_ledger, list):
            raise ManifestError(f"legacyMediaLedger must be a list: {migration_id}")
        for media_entry in media_ledger:
            if not isinstance(media_entry, Mapping):
                raise ManifestError(f"legacy media ledger entry must be an object: {migration_id}")
            version = media_entry.get("version")
            name = media_entry.get("name")
            if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
                raise ManifestError(f"legacy media version must be positive: {migration_id}")
            if not isinstance(name, str) or not name:
                raise ManifestError(f"legacy media name must be non-empty: {migration_id}")
            media_key = (version, name)
            previous = legacy_media_keys.get(media_key)
            if previous is not None:
                raise ManifestError(f"legacy media ledger key is mapped twice: {version}:{name}")
            legacy_media_keys[media_key] = migration_id

    expected_orders = list(range(10, 10 * (len(entries) + 1), 10))
    if [entry["order"] for entry in entries] != expected_orders:
        raise ManifestError("manifest order must be the exact contiguous canonical order")

    positions = {entry["id"]: position for position, entry in enumerate(entries)}
    for entry in entries:
        source_version = Path(entry["source"]).name[:3]
        if entry["id"][4:7] != source_version:
            raise ManifestError(f"migration id/source version mismatch: {entry['id']}")
        for dependency in entry["dependsOn"]:
            if dependency not in ids:
                raise ManifestError(f"{entry['id']} depends on unknown migration {dependency}")
            if dependency == entry["id"]:
                raise ManifestError(f"migration cannot depend on itself: {dependency}")
            if positions[dependency] >= positions[entry["id"]]:
                raise ManifestError(f"migration dependency must point backward: {entry['id']} -> {dependency}")

    b03 = next(entry for entry in entries if entry["id"] == "cm1-017-b03-assets")
    if b03.get("legacyMediaLedger") != [{"version": 14, "name": "b03_assets_read_model"}]:
        raise ManifestError("B03 legacy marker must be 14:b03_assets_read_model")

    for entry in excluded:
        if not isinstance(entry, Mapping):
            raise ManifestError("excluded migration entry must be an object")
        source_path = _validate_relative_source(entry.get("source"), "excluded source")
        if source_path in sources:
            raise ManifestError(f"source appears in both applied and excluded inventory: {source_path}")
        sources.add(source_path)
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or not SHA256_RE.fullmatch(checksum):
            raise ManifestError(f"invalid excluded source checksum: {source_path}")
        if entry.get("status") != "excluded" or not entry.get("reason"):
            raise ManifestError(f"excluded source needs a reason: {source_path}")
        superseded_by = entry.get("supersededBy")
        if superseded_by is not None and superseded_by not in ids:
            raise ManifestError(f"excluded source points to unknown replacement: {source_path}")
        account_revisions = entry.get("legacyAccountRevisions", [])
        if not isinstance(account_revisions, list) or len(account_revisions) != len(set(account_revisions)):
            raise ManifestError(f"excluded legacyAccountRevisions must be unique: {source_path}")
        for revision in account_revisions:
            if not isinstance(revision, str) or not revision:
                raise ManifestError(f"excluded legacy account revision must be non-empty: {source_path}")
            previous = legacy_revisions.get(revision)
            if previous is not None:
                raise ManifestError(f"legacy account revision is mapped twice: {revision}")
            legacy_revisions[revision] = source_path

    required_schemas = manifest.get("requiredSchemas")
    required_tables = manifest.get("requiredTables")
    if required_schemas != ["openclaw_account", "media_product", "media_document"]:
        raise ManifestError("requiredSchemas must cover the three PostgreSQL domains in order")
    if not isinstance(required_tables, list) or len(required_tables) != len(set(required_tables)):
        raise ManifestError("requiredTables must be a unique list")
    for table in required_tables:
        if not isinstance(table, str) or table.count(".") != 1:
            raise ManifestError(f"required table must be schema-qualified: {table!r}")
    required_table_set = set(required_tables)
    for table in (
        "media_product.document_artifacts",
        "media_product.document_revisions",
        "media_document.revision_bodies",
        "media_document.exports",
        "openclaw_account.if2_idempotency_receipts",
    ):
        if table not in required_table_set:
            raise ManifestError(f"requiredTables must include {table}")


def ordered_migrations(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_manifest(manifest)
    return [dict(entry) for entry in manifest["migrations"]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SourceError(f"cannot read source file: {path}: {exc}") from exc
    return digest.hexdigest()


def _inventory(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [*manifest["migrations"], *manifest["excludedMigrations"]]


def _safe_source_path(source_root: Path, source: str) -> Path:
    root = source_root.resolve()
    path = (root / source).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SourceError(f"source escapes source root: {source}") from exc
    return path


def validate_source_tree(source_root: Path, manifest: Mapping[str, Any]) -> None:
    if not source_root.is_dir():
        raise SourceError(f"source root is not a directory: {source_root}")
    root = source_root.resolve()
    migration_dir = _safe_source_path(source_root, manifest["source"]["migrationDirectory"])
    if not migration_dir.is_dir():
        raise SourceError(f"migration directory is missing: {migration_dir}")
    residues = sorted(
        path.relative_to(root).as_posix()
        for path in migration_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".orig", ".rej"}
    )
    if residues:
        raise SourceError("source tree contains forbidden residue(s): " + ", ".join(residues))
    actual_sql = sorted(
        path.relative_to(root).as_posix()
        for path in migration_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".sql"
    )
    expected_sql = sorted(entry["source"] for entry in _inventory(manifest))
    if actual_sql != expected_sql:
        missing = sorted(set(expected_sql) - set(actual_sql))
        unexpected = sorted(set(actual_sql) - set(expected_sql))
        raise SourceError(f"closed SQL inventory mismatch; missing={missing}; unexpected={unexpected}")

    for entry in _inventory(manifest):
        path = _safe_source_path(source_root, entry["source"])
        actual_hash = sha256_file(path)
        expected_hash = entry.get("sourceSha256", entry.get("sha256"))
        if actual_hash != expected_hash:
            raise SourceError(
                f"source checksum mismatch for {entry['source']}: expected {expected_hash}, got {actual_hash}"
            )


def build_plan(source_root: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_manifest(manifest)
    validate_source_tree(source_root, manifest)
    plan = ordered_migrations(manifest)
    for entry in plan:
        path = _safe_source_path(source_root, entry["source"])
        try:
            source_bytes = path.read_bytes()
            source_sql = source_bytes.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise SourceError(f"cannot freeze migration source: {path}: {exc}") from exc
        digest = hashlib.sha256(source_bytes).hexdigest()
        if digest != entry["sourceSha256"]:
            raise SourceError(
                f"source changed while building plan for {entry['id']}: "
                f"expected {entry['sourceSha256']}, got {digest}"
            )
        entry["executionStatements"] = normalize_sql(source_sql)
    return plan


def _dollar_tag_at(sql: str, index: int) -> str | None:
    match = DOLLAR_TAG_RE.match(sql, index)
    return match.group(0) if match else None


def split_sql(sql: str) -> list[str]:
    """Split PostgreSQL statements while preserving quoted and dollar-quoted bodies."""

    statements: list[str] = []
    start = 0
    state = "normal"
    dollar_tag: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if state == "normal":
            if sql.startswith("--", index):
                newline = sql.find("\n", index + 2)
                index = len(sql) if newline == -1 else newline + 1
                continue
            if sql.startswith("/*", index):
                state = "block_comment"
                index += 2
                continue
            if char == "'":
                state = "single_quote"
                index += 1
                continue
            if char == '"':
                state = "double_quote"
                index += 1
                continue
            if char == "$":
                tag = _dollar_tag_at(sql, index)
                if tag:
                    state = "dollar_quote"
                    dollar_tag = tag
                    index += len(tag)
                    continue
            if char == ";":
                statement = sql[start : index + 1].strip()
                if statement:
                    statements.append(statement)
                start = index + 1
            index += 1
            continue
        if state == "block_comment":
            if sql.startswith("*/", index):
                state = "normal"
                index += 2
            else:
                index += 1
            continue
        if state == "single_quote":
            if sql.startswith("''", index):
                index += 2
            elif char == "\\":
                index += 2
            elif char == "'":
                state = "normal"
                index += 1
            else:
                index += 1
            continue
        if state == "double_quote":
            if sql.startswith('""', index):
                index += 2
            elif char == '"':
                state = "normal"
                index += 1
            else:
                index += 1
            continue
        if state == "dollar_quote":
            assert dollar_tag is not None
            if sql.startswith(dollar_tag, index):
                index += len(dollar_tag)
                state = "normal"
                dollar_tag = None
            else:
                index += 1
            continue
        raise AssertionError(f"unknown SQL scanner state: {state}")

    if state != "normal":
        raise SourceError(f"unterminated PostgreSQL {state}")
    trailing = sql[start:].strip()
    if trailing:
        statements.append(trailing)
    return statements


def _strip_leading_comments(statement: str) -> str:
    current = statement.lstrip()
    while current.startswith("--") or current.startswith("/*"):
        if current.startswith("--"):
            newline = current.find("\n")
            current = "" if newline == -1 else current[newline + 1 :].lstrip()
        else:
            end = current.find("*/", 2)
            if end == -1:
                raise SourceError("unterminated leading SQL block comment")
            current = current[end + 2 :].lstrip()
    return current


def _is_transaction_control(statement: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:BEGIN|START\s+TRANSACTION|COMMIT|END|ROLLBACK|ABORT)\s*;?",
            _strip_leading_comments(statement),
            flags=re.IGNORECASE,
        )
    )


def _references_ledger(statement: str) -> str | None:
    leading = _strip_leading_comments(statement)
    lowered = leading.lower()
    targets = ("openclaw_account.schema_migrations", "media_product.migration_ledger")
    target = next((value for value in targets if value in lowered), None)
    if target is None:
        return None
    return target


def normalize_sql(sql: str) -> list[str]:
    """Split physically canonical PostgreSQL SQL and reject alternate execution paths."""

    normalized: list[str] = []
    for statement in split_sql(sql):
        leading = _strip_leading_comments(statement)
        if not leading:
            continue
        if _is_transaction_control(leading):
            raise SourceError("migration sources must not contain transaction control")
        if re.match(r"^pragma\b", leading, flags=re.IGNORECASE):
            raise SourceError("SQLite PRAGMA is forbidden in the PostgreSQL topology")
        ledger = _references_ledger(leading)
        if ledger is not None:
            raise SourceError(f"migration sources must not access migration ledgers: {ledger}")
        normalized.append(statement.strip())
    return normalized


def _table_exists(connection: Any, schema: str, table: str) -> bool:
    row = _fetchone(
        connection,
        """
        SELECT 1
          FROM information_schema.tables
         WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return row is not None


def _table_columns(connection: Any, schema: str, table: str) -> set[str]:
    rows = _fetchall(
        connection,
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return {_row_value(row, 0, "column_name") for row in rows}


def _schema_exists(connection: Any, schema: str) -> bool:
    return _fetchone(
        connection,
        "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
        (schema,),
    ) is not None


def _has_state(connection: Any, manifest: Mapping[str, Any]) -> bool:
    if any(_schema_exists(connection, schema) for schema in manifest["requiredSchemas"]):
        return True
    return any(
        _table_exists(connection, *qualified_table.split(".", 1))
        for qualified_table in manifest["requiredTables"]
    )


def _has_media_state(connection: Any) -> bool:
    return _schema_exists(connection, "media_product") or _schema_exists(connection, "media_document")


def _create_canonical_ledger(connection: Any) -> None:
    _cursor_execute(connection, "CREATE SCHEMA IF NOT EXISTS openclaw_account")
    _cursor_execute(
        connection,
        """
        CREATE TABLE openclaw_account.schema_migrations (
            migration_id TEXT NOT NULL
                CHECK (migration_id ~ '^cm1-[0-9]{3}-[a-z0-9-]+$'),
            checksum CHAR(64) NOT NULL
                CHECK (checksum ~ '^[a-f0-9]{64}$'),
            depends_on TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            applied_at TIMESTAMPTZ DEFAULT now()
                CONSTRAINT cm1_schema_migrations_applied_at_not_null NOT NULL,
            CONSTRAINT cm1_schema_migrations_pkey PRIMARY KEY (migration_id)
        )
        """,
    )


def _ensure_ledger_guard(connection: Any) -> None:
    _cursor_execute(
        connection,
        """
        CREATE OR REPLACE FUNCTION openclaw_account.reject_cm1_ledger_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'C-M1 migration ledger is immutable' USING ERRCODE = '55000';
        END;
        $$
        """,
    )
    _cursor_execute(
        connection,
        "DROP TRIGGER IF EXISTS cm1_schema_migrations_immutable ON openclaw_account.schema_migrations",
    )
    _cursor_execute(
        connection,
        """
        CREATE TRIGGER cm1_schema_migrations_immutable
        BEFORE UPDATE OR DELETE ON openclaw_account.schema_migrations
        FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_cm1_ledger_mutation()
        """,
    )


def _verify_ledger_immutability(connection: Any) -> None:
    _cursor_execute(
        connection,
        """
        DO $cm1_ledger_guard$
        BEGIN
            BEGIN
                UPDATE openclaw_account.schema_migrations
                   SET checksum = checksum
                 WHERE migration_id = (
                     SELECT min(migration_id) FROM openclaw_account.schema_migrations
                 );
                RAISE EXCEPTION 'canonical ledger UPDATE unexpectedly succeeded';
            EXCEPTION WHEN SQLSTATE '55000' THEN
                NULL;
            END;
            BEGIN
                DELETE FROM openclaw_account.schema_migrations
                 WHERE migration_id = (
                     SELECT min(migration_id) FROM openclaw_account.schema_migrations
                 );
                RAISE EXCEPTION 'canonical ledger DELETE unexpectedly succeeded';
            EXCEPTION WHEN SQLSTATE '55000' THEN
                NULL;
            END;
        END
        $cm1_ledger_guard$
        """,
    )


def _manifest_by_id(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {entry["id"]: entry for entry in manifest["migrations"]}


def _legacy_lookups(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[tuple[int, str], Mapping[str, Any]]]:
    by_revision: dict[str, Mapping[str, Any]] = {}
    by_media_key: dict[tuple[int, str], Mapping[str, Any]] = {}
    for entry in manifest["migrations"]:
        for revision in entry.get("legacyAccountRevisions", []):
            by_revision[revision] = entry
        for media_entry in entry.get("legacyMediaLedger", []):
            by_media_key[(int(media_entry["version"]), media_entry["name"])] = entry
    for entry in manifest["excludedMigrations"]:
        for revision in entry.get("legacyAccountRevisions", []):
            by_revision[revision] = entry
    return by_revision, by_media_key


def _canonical_state(connection: Any) -> dict[str, tuple[str, list[str]]]:
    rows = _fetchall(
        connection,
        "SELECT migration_id, checksum, depends_on FROM openclaw_account.schema_migrations ORDER BY migration_id",
    )
    state: dict[str, tuple[str, list[str]]] = {}
    for row in rows:
        migration_id = str(_row_value(row, 0, "migration_id"))
        if migration_id in state:
            raise LedgerError(f"duplicate canonical migration id: {migration_id}")
        state[migration_id] = (
            str(_row_value(row, 1, "checksum")),
            list(_row_value(row, 2, "depends_on")),
        )
    return state


def _validate_dependency_closure(
    ids: set[str],
    manifest: Mapping[str, Any],
    already_present: set[str] | None = None,
) -> None:
    known = _manifest_by_id(manifest)
    available = set(already_present or ()) | ids
    for migration_id in ids:
        missing = [dependency for dependency in known[migration_id]["dependsOn"] if dependency not in available]
        if missing:
            raise LedgerError(f"legacy adoption has missing dependencies for {migration_id}: {missing}")


def _insert_or_validate_ledger_row(
    connection: Any,
    entry: Mapping[str, Any],
    applied_at: Any | None = None,
) -> None:
    existing = _fetchone(
        connection,
        "SELECT checksum, depends_on FROM openclaw_account.schema_migrations WHERE migration_id = %s",
        (entry["id"],),
    )
    if existing is not None:
        checksum = str(_row_value(existing, 0, "checksum"))
        depends_on = list(_row_value(existing, 1, "depends_on"))
        if checksum != entry["ledgerChecksum"] or depends_on != list(entry["dependsOn"]):
            raise LedgerError(f"checksum or dependency drift in canonical ledger: {entry['id']}")
        return
    _cursor_execute(
        connection,
        """
        INSERT INTO openclaw_account.schema_migrations
            (migration_id, checksum, depends_on, applied_at)
        VALUES (%s, %s, %s, COALESCE(%s, now()))
        """,
        (entry["id"], entry["ledgerChecksum"], entry["dependsOn"], applied_at),
    )


def _adopt_legacy_rows(
    connection: Any,
    manifest: Mapping[str, Any],
    account_rows: Iterable[Any],
    media_rows: Iterable[Any],
    already_present: set[str],
) -> set[str]:
    by_revision, by_media_key = _legacy_lookups(manifest)
    selected: dict[str, tuple[Mapping[str, Any], Any | None]] = {}

    for row in account_rows:
        revision = str(_row_value(row, 0, "revision"))
        entry = by_revision.get(revision)
        if entry is None:
            raise LedgerError(f"unknown legacy account migration revision: {revision}")
        if entry.get("status") == "excluded":
            replacement = entry.get("supersededBy", "none")
            raise LedgerError(f"superseded legacy migration is present: {revision}; use {replacement}")
        migration_id = entry["id"]
        if migration_id in selected:
            raise LedgerError(f"legacy rows map to the same immutable id twice: {migration_id}")
        selected[migration_id] = (entry, _row_value(row, 1, "applied_at"))

    for row in media_rows:
        version = int(_row_value(row, 0, "version"))
        name = str(_row_value(row, 1, "name"))
        entry = by_media_key.get((version, name))
        if entry is None:
            raise LedgerError(f"unknown legacy media migration ledger entry: {version}:{name}")
        migration_id = entry["id"]
        if migration_id in selected:
            raise LedgerError(f"legacy rows map to the same immutable id twice: {migration_id}")
        selected[migration_id] = (entry, _row_value(row, 2, "applied_at"))

    selected_ids = set(selected)
    media_ids = {
        entry["id"]
        for entry, _applied_at in selected.values()
        if entry.get("legacyMediaLedger")
    }
    if media_ids - {"cm1-013-media-product"} and "cm1-013-media-product" not in selected_ids | already_present:
        raise LedgerError("legacy page migration marker exists without the 013 media-product marker")
    for entry, applied_at in sorted(selected.values(), key=lambda value: (value[0]["order"], value[0]["id"])):
        _insert_or_validate_ledger_row(connection, entry, applied_at)
    return selected_ids


def _validate_canonical_state(
    state: Mapping[str, tuple[str, list[str]]],
    manifest: Mapping[str, Any],
) -> None:
    known = _manifest_by_id(manifest)
    for migration_id, (checksum, depends_on) in state.items():
        entry = known.get(migration_id)
        if entry is None:
            raise LedgerError(f"canonical ledger contains unknown migration: {migration_id}")
        if checksum != entry["ledgerChecksum"]:
            raise LedgerError(f"canonical ledger checksum drift: {migration_id}")
        if depends_on != list(entry["dependsOn"]):
            raise LedgerError(f"canonical ledger dependency drift: {migration_id}")
    _validate_dependency_closure(set(state), manifest)


def _read_media_ledger(connection: Any) -> list[Any]:
    columns = _table_columns(connection, "media_product", "migration_ledger")
    if columns != LEGACY_MEDIA_LEDGER_COLUMNS:
        raise LedgerError(f"unsupported media migration ledger layout: {sorted(columns)}")
    return _fetchall(
        connection,
        "SELECT version, name, applied_at FROM media_product.migration_ledger ORDER BY version, name",
    )


def prepare_ledger(connection: Any, manifest: Mapping[str, Any], mode: str) -> set[str]:
    """Create the sole ledger or perform the explicit one-time legacy adoption."""

    if mode not in {"empty", "current"}:
        raise LedgerError(f"unsupported database mode: {mode}")
    ledger_present = _table_exists(connection, "openclaw_account", "schema_migrations")
    media_ledger_present = _table_exists(connection, "media_product", "migration_ledger")
    has_state = _has_state(connection, manifest)
    has_media_state = _has_media_state(connection)
    columns = _table_columns(connection, "openclaw_account", "schema_migrations")

    if mode == "empty":
        if ledger_present or media_ledger_present or has_state:
            raise LedgerError("empty mode requires a database without C-M1 state")
        _create_canonical_ledger(connection)
        _ensure_ledger_guard(connection)
        return set()

    if not ledger_present:
        raise LedgerError("current mode requires an existing legacy or canonical migration ledger")
    if media_ledger_present and not has_media_state:
        raise LedgerError("current mode found a media migration ledger without media state")

    if columns == LEGACY_LEDGER_COLUMNS:
        account_rows = _fetchall(
            connection,
            "SELECT revision, applied_at FROM openclaw_account.schema_migrations ORDER BY revision",
        )
        media_rows = _read_media_ledger(connection) if media_ledger_present else []
        if not account_rows and not media_rows:
            raise LedgerError("current mode found an empty legacy ledger")
        if has_media_state and not media_ledger_present:
            raise LedgerError("media state exists without its legacy media ledger")
        _cursor_execute(
            connection,
            "ALTER TABLE openclaw_account.schema_migrations RENAME TO cm1_legacy_schema_migrations",
        )
        _create_canonical_ledger(connection)
        adopted = _adopt_legacy_rows(connection, manifest, account_rows, media_rows, set())
        _cursor_execute(connection, "DROP TABLE openclaw_account.cm1_legacy_schema_migrations")
        if media_ledger_present:
            _cursor_execute(connection, "DROP TABLE media_product.migration_ledger")
        _ensure_ledger_guard(connection)
        return adopted

    if columns == set(CANONICAL_LEDGER_COLUMNS):
        state = _canonical_state(connection)
        _validate_canonical_state(state, manifest)
        if not state and has_state:
            raise LedgerError("current mode found C-M1 tables without canonical migration rows")
        if has_media_state and not media_ledger_present and "cm1-013-media-product" not in state:
            raise LedgerError("media state exists without 013 provenance")
        if media_ledger_present:
            media_rows = _read_media_ledger(connection)
            adopted = _adopt_legacy_rows(connection, manifest, [], media_rows, set(state))
            state = _canonical_state(connection)
            _cursor_execute(connection, "DROP TABLE media_product.migration_ledger")
            state_ids = set(state) | adopted
        else:
            state_ids = set(state)
        _ensure_ledger_guard(connection)
        return state_ids

    raise LedgerError(f"unsupported schema_migrations layout: {sorted(columns)}")


def _ledger_row(connection: Any, migration_id: str) -> tuple[str, list[str]] | None:
    row = _fetchone(
        connection,
        "SELECT checksum, depends_on FROM openclaw_account.schema_migrations WHERE migration_id = %s",
        (migration_id,),
    )
    if row is None:
        return None
    return str(_row_value(row, 0, "checksum")), list(_row_value(row, 1, "depends_on"))


def _record_migration(connection: Any, entry: Mapping[str, Any]) -> None:
    _cursor_execute(
        connection,
        """
        INSERT INTO openclaw_account.schema_migrations
            (migration_id, checksum, depends_on)
        VALUES (%s, %s, %s)
        """,
        (entry["id"], entry["ledgerChecksum"], entry["dependsOn"]),
    )


def _verify_server_version(connection: Any) -> None:
    row = _fetchone(connection, "SHOW server_version_num")
    if row is None:
        raise LedgerError("cannot read PostgreSQL server_version_num")
    version_num = int(_row_value(row, 0, "server_version_num"))
    if version_num // 10000 != 16:
        raise LedgerError(f"C-M1 requires PostgreSQL 16, got server_version_num={version_num}")


def apply_migrations(
    connection: Any,
    source_root: Path,
    manifest: Mapping[str, Any],
    mode: str,
) -> list[str]:
    plan = build_plan(source_root, manifest)
    applied_now: list[str] = []
    try:
        _verify_server_version(connection)
        _lock(connection)
        applied = prepare_ledger(connection, manifest, mode)
        for entry in plan:
            recorded = _ledger_row(connection, entry["id"])
            if recorded is not None:
                checksum, depends_on = recorded
                if checksum != entry["ledgerChecksum"]:
                    raise LedgerError(f"migration checksum mismatch: {entry['id']}")
                if depends_on != list(entry["dependsOn"]):
                    raise LedgerError(f"migration dependency mismatch: {entry['id']}")
                missing_dependencies = [
                    dependency for dependency in entry["dependsOn"] if dependency not in applied
                ]
                if missing_dependencies:
                    raise LedgerError(f"recorded migration has missing dependencies: {entry['id']}")
                continue

            missing_dependencies = [dependency for dependency in entry["dependsOn"] if dependency not in applied]
            if missing_dependencies:
                raise LedgerError(f"dependency not applied for {entry['id']}: {missing_dependencies}")
            for statement in entry["executionStatements"]:
                _cursor_execute(connection, statement)
            _record_migration(connection, entry)
            applied.add(entry["id"])
            applied_now.append(entry["id"])
        verify_database(connection, manifest)
        _commit(connection)
    except Exception:
        _rollback(connection)
        raise
    return applied_now


def verify_database(connection: Any, manifest: Mapping[str, Any]) -> None:
    _verify_server_version(connection)
    columns = _table_columns(connection, "openclaw_account", "schema_migrations")
    if columns != set(CANONICAL_LEDGER_COLUMNS):
        raise LedgerError(f"canonical schema_migrations layout is invalid: {sorted(columns)}")
    if _table_exists(connection, "media_product", "migration_ledger"):
        raise LedgerError("legacy media_product.migration_ledger still exists")
    if _table_exists(connection, "openclaw_account", "cm1_legacy_schema_migrations"):
        raise LedgerError("legacy account migration ledger staging table still exists")
    if _table_exists(connection, "openclaw_account", "postgres_migration_ledger"):
        raise LedgerError("obsolete candidate postgres_migration_ledger still exists")

    primary_keys = _fetchall(
        connection,
        """
        SELECT constraint_row.conname,
               array_agg(attribute.attname ORDER BY key_column.ordinality)
          FROM pg_constraint AS constraint_row
          JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid
          JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
          CROSS JOIN LATERAL unnest(constraint_row.conkey)
              WITH ORDINALITY AS key_column(attnum, ordinality)
          JOIN pg_attribute AS attribute
            ON attribute.attrelid = relation.oid
           AND attribute.attnum = key_column.attnum
         WHERE namespace.nspname = 'openclaw_account'
           AND relation.relname = 'schema_migrations'
           AND constraint_row.contype = 'p'
         GROUP BY constraint_row.conname
        """,
    )
    if len(primary_keys) != 1:
        raise LedgerError("canonical ledger must have exactly one primary key")
    primary_key_name = str(_row_value(primary_keys[0], 0, "conname"))
    primary_key_columns = list(_row_value(primary_keys[0], 1, "array_agg"))
    if primary_key_name != "cm1_schema_migrations_pkey" or primary_key_columns != ["migration_id"]:
        raise LedgerError(
            "canonical ledger primary key drift: "
            f"name={primary_key_name}, columns={primary_key_columns}"
        )

    applied_at = _fetchone(
        connection,
        """
        SELECT attribute.attnotnull
          FROM pg_attribute AS attribute
          JOIN pg_class AS relation ON relation.oid = attribute.attrelid
          JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
         WHERE namespace.nspname = 'openclaw_account'
           AND relation.relname = 'schema_migrations'
           AND attribute.attname = 'applied_at'
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped
        """,
    )
    if applied_at is None or _row_value(applied_at, 0, "attnotnull") is not True:
        raise LedgerError("canonical ledger applied_at must be NOT NULL")

    triggers = _fetchall(
        connection,
        """
        SELECT trigger_row.tgname,
               trigger_row.tgenabled,
               function_namespace.nspname,
               function_row.proname,
               pg_get_triggerdef(trigger_row.oid)
          FROM pg_trigger AS trigger_row
          JOIN pg_class AS relation ON relation.oid = trigger_row.tgrelid
          JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
          JOIN pg_proc AS function_row ON function_row.oid = trigger_row.tgfoid
          JOIN pg_namespace AS function_namespace ON function_namespace.oid = function_row.pronamespace
         WHERE namespace.nspname = 'openclaw_account'
           AND relation.relname = 'schema_migrations'
           AND NOT trigger_row.tgisinternal
        """,
    )
    if len(triggers) != 1:
        raise LedgerError("canonical ledger must have exactly one user trigger")
    trigger = triggers[0]
    trigger_values = (
        str(_row_value(trigger, 0, "tgname")),
        str(_row_value(trigger, 1, "tgenabled")),
        str(_row_value(trigger, 2, "nspname")),
        str(_row_value(trigger, 3, "proname")),
    )
    trigger_definition = str(_row_value(trigger, 4, "pg_get_triggerdef")).upper()
    if trigger_values != (
        "cm1_schema_migrations_immutable",
        "O",
        "openclaw_account",
        "reject_cm1_ledger_mutation",
    ) or not all(token in trigger_definition for token in ("BEFORE", "UPDATE", "DELETE")):
        raise LedgerError(f"canonical ledger immutable trigger drift: {trigger_values}")
    _verify_ledger_immutability(connection)

    for schema in manifest["requiredSchemas"]:
        if _fetchone(
            connection,
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
            (schema,),
        ) is None:
            raise LedgerError(f"required schema is missing: {schema}")
    for qualified_table in manifest["requiredTables"]:
        schema, table = qualified_table.split(".", 1)
        if not _table_exists(connection, schema, table):
            raise LedgerError(f"required table is missing: {qualified_table}")

    state = _canonical_state(connection)
    _validate_canonical_state(state, manifest)
    expected = _manifest_by_id(manifest)
    if set(state) != set(expected):
        missing = sorted(set(expected) - set(state))
        extra = sorted(set(state) - set(expected))
        raise LedgerError(f"canonical ledger is not complete: missing={missing}; extra={extra}")


def _connect(dsn: str) -> Any:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on the target runtime
        raise RunnerError("psycopg 3 is required for the runner CLI") from exc
    return psycopg.connect(dsn)


def _print_plan(source_root: Path, manifest: Mapping[str, Any]) -> None:
    plan = build_plan(source_root, manifest)
    print(
        json.dumps(
            {
                "sourceRoot": str(source_root),
                "orderedMigrationIds": [entry["id"] for entry in plan],
                "excludedSources": [entry["source"] for entry in manifest["excludedMigrations"]],
            },
            indent=2,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--source-root", type=Path, required=True)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--source-root", type=Path, required=True)
    apply_parser.add_argument("--dsn", required=True)
    apply_parser.add_argument("--mode", choices=("empty", "current"), required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--source-root", type=Path, required=True)
    verify_parser.add_argument("--dsn", required=True)

    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "plan":
            _print_plan(args.source_root, manifest)
            return 0
        connection = _connect(args.dsn)
        try:
            if args.command == "apply":
                applied = apply_migrations(connection, args.source_root, manifest, args.mode)
                print(json.dumps({"appliedNow": applied, "status": "verified"}, indent=2))
            else:
                build_plan(args.source_root, manifest)
                verify_database(connection, manifest)
                print(json.dumps({"status": "verified"}, indent=2))
        finally:
            connection.close()
        return 0
    except RunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
