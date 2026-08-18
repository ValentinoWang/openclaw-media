#!/usr/bin/env python3
"""Prepare or verify the fourteen isolated Media Web page development lanes."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


ROOT = Path("/home/ubuntu/selfmedia-tools/openclaw-tag-router")
MANIFEST = ROOT / "openclaw_app/contracts/media_web_business_pages.resources.yaml"
MIGRATIONS = (
    ROOT / "openclaw_app/migrations/003_openclaw_account_billing.sql",
    ROOT / "openclaw_app/migrations/013_media_product.sql",
)
EVIDENCE_ROOT = Path("/home/ubuntu/media-business-api-evidence/5-5-2-5")
DATABASE_PATTERN = re.compile(r"^media_b(0[1-9]|1[0-4])_a3_20260805$")
EXPECTED_COLUMNS = {
    ("media_product", "lark_document_bindings", "remote_document_version"),
    ("media_product", "lark_document_bindings", "body_checksum"),
    ("media_product", "lark_document_block_mappings", "public_block_id"),
    ("media_product", "lark_document_block_mappings", "remote_block_id"),
    ("media_product", "lark_document_block_mappings", "remote_document_version"),
}


def run(*args: str, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        input=input_text,
        check=check,
        capture_output=True,
    )


def scalar(database: str | None, statement: str) -> str:
    args = ["sudo", "-u", "postgres", "psql", "-Atqc", statement]
    if database:
        args.extend(["-d", database])
    return run(*args).stdout.strip()


def database_exists(database: str) -> bool:
    escaped = database.replace("'", "''")
    return scalar(None, f"SELECT count(*) FROM pg_database WHERE datname='{escaped}'") == "1"


def validate_manifest(data: dict[str, Any]) -> list[dict[str, Any]]:
    lanes = data.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != 14:
        raise SystemExit("resource manifest must contain exactly fourteen lanes")
    if data.get("chromiumConcurrency") != 4:
        raise SystemExit("resource manifest Chromium concurrency must be 4")
    expected_nodes = [f"B{index:02d}" for index in range(1, 15)]
    if [lane.get("node") for lane in lanes] != expected_nodes:
        raise SystemExit("resource manifest nodes must be exactly B01-B14")
    if [lane.get("port") for lane in lanes] != list(range(18001, 18015)):
        raise SystemExit("resource manifest ports must be exactly 18001-18014")
    for key in ("database", "ordinaryIdentity", "adminIdentity", "evidence"):
        values = [lane.get(key) for lane in lanes]
        if not all(isinstance(value, str) and value for value in values):
            raise SystemExit(f"resource manifest contains an invalid {key}")
        if len(set(values)) != 14:
            raise SystemExit(f"resource manifest contains duplicate {key} values")
    for lane in lanes:
        database = lane["database"]
        evidence = Path(lane["evidence"])
        if not DATABASE_PATTERN.fullmatch(database):
            raise SystemExit(f"unsafe A3 database name: {database}")
        if evidence.parent != EVIDENCE_ROOT or evidence.name != lane["node"]:
            raise SystemExit(f"unsafe A3 evidence directory: {evidence}")
    return lanes


def apply_migrations(database: str) -> None:
    for migration in MIGRATIONS:
        run(
            "sudo",
            "-u",
            "postgres",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-d",
            database,
            input_text=migration.read_text(encoding="utf-8"),
        )


def verify_database(database: str) -> None:
    if not database_exists(database):
        raise SystemExit(f"missing isolated database: {database}")
    version = scalar(database, "SELECT name FROM media_product.migration_ledger WHERE version=13")
    if version != "media_product":
        raise SystemExit(f"migration 013 is not applied in {database}")
    rows = run(
        "sudo",
        "-u",
        "postgres",
        "psql",
        "-At",
        "-F",
        "|",
        "-d",
        database,
        "-c",
        """
        SELECT table_schema, table_name, column_name
          FROM information_schema.columns
         WHERE table_schema IN ('media_product', 'media_document');
        """,
    ).stdout.splitlines()
    actual = {tuple(row.split("|", 2)) for row in rows if row}
    missing = EXPECTED_COLUMNS - actual
    if missing:
        raise SystemExit(f"{database} is missing IF2 columns: {sorted(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    lanes = validate_manifest(data)

    for lane in lanes:
        database = lane["database"]
        evidence = Path(lane["evidence"])
        if args.recreate and database_exists(database):
            run("sudo", "-u", "postgres", "dropdb", "--force", database)
        evidence.mkdir(parents=True, exist_ok=True)
        if not database_exists(database):
            if args.check:
                raise SystemExit(f"unprepared lane: {lane['node']}")
            run("sudo", "-u", "postgres", "createdb", database)
            apply_migrations(database)
        verify_database(database)
    action = "checked" if args.check else "recreated" if args.recreate else "prepared"
    print(f"{action} 14 isolated lanes")


if __name__ == "__main__":
    main()
