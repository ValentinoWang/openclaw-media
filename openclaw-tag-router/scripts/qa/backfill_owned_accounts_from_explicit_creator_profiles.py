#!/usr/bin/env python3
"""One-time, allowlisted recovery and ledger migration for owned accounts.

This migration copies two user-confirmed creator-profile identities into the
canonical B02 ``owned_media_accounts`` read model.  It also enriches records
created by the v1 recovery and deletes its retired authorization field.  It
never treats ``creator_profiles`` as a runtime fallback and never invents
operational status or organizational responsibility.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import psycopg


TENANT_ID = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
TRACK_ID = "record_008bbc93d6"
RECOVERY_CONTRACT = "owned_media_account_recovery_v2"
LEGACY_RECOVERY_CONTRACT = "owned_media_account_recovery_v1"
RECOVERY_REASON = "user_confirmed_previous_owned_account_visibility"
CREATOR_IDS = (
    "creator_rec27ontOogTd2",
    "creator_rec27ontOogY7R",
)


def _database_url(value: str | None) -> str:
    url = (value or os.environ.get("OPENCLAW_ACCOUNT_DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("OPENCLAW_ACCOUNT_DATABASE_URL is required")
    return url


def _row_to_payload(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        creator_id,
        canonical_data,
        account_name,
        platform,
        profile_url,
        source_record_id,
    ) = row
    if not isinstance(canonical_data, dict):
        raise RuntimeError(f"creator profile {creator_id} canonical_data is not an object")
    source_fields = canonical_data.get("fields")
    account_positioning = source_fields.get("身份定位") if isinstance(source_fields, dict) else None
    author_id = canonical_data.get("author_id")
    if not isinstance(author_id, str) or not author_id.strip():
        source_fields = canonical_data.get("fields")
        author_id = source_fields.get("作者ID") if isinstance(source_fields, dict) else None
    avatar_url = canonical_data.get("avatar_url")
    if (
        not account_name
        or not platform
        or not profile_url
        or not source_record_id
        or not isinstance(author_id, str)
        or not author_id.strip()
        or not isinstance(avatar_url, str)
        or not avatar_url.strip()
        or not isinstance(account_positioning, str)
        or not account_positioning.strip()
    ):
        raise RuntimeError(f"creator profile {creator_id} is missing explicit ledger fields")
    return {
        "account_name": account_name,
        "platform": platform,
        "operational_status": None,
        "responsible_person": None,
        "team_name": None,
        "account_positioning": account_positioning.strip(),
        "data_source": "feishu_creator_profile",
        "author_id": author_id.strip(),
        "profile_url": profile_url,
        "avatar_url": avatar_url.strip(),
        "public_track_ids": [TRACK_ID],
        "last_synced_at": None,
        "source_creator_profile_id": creator_id,
        "source": {
            "provider": "feishu",
            "table": "06_CreatorProfiles_达人账号档案",
            "record_id": source_record_id,
            "recovery_contract": RECOVERY_CONTRACT,
            "recovery_reason": RECOVERY_REASON,
        },
        "source_profile_snapshot": {
            "creator_role": canonical_data.get("creator_role"),
            "identity_tags": canonical_data.get("identity_tags", []),
            "expertise_domains": canonical_data.get("expertise_domains", []),
        },
    }


def _enrich_recovered_payload(
    creator_id: str,
    prior: dict[str, Any],
    source_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = prior.get("source")
    if (
        not isinstance(source, dict)
        or source.get("recovery_contract") not in {LEGACY_RECOVERY_CONTRACT, RECOVERY_CONTRACT}
    ):
        raise RuntimeError(f"owned account {creator_id} already exists outside this recovery contract")
    enriched = dict(prior)
    changes: dict[str, Any] = {}
    if "authorization_status" in enriched:
        enriched.pop("authorization_status")
        changes["authorization_status"] = None
    if source.get("recovery_contract") != RECOVERY_CONTRACT:
        enriched["source"] = dict(source, recovery_contract=RECOVERY_CONTRACT)
        changes["source.recovery_contract"] = RECOVERY_CONTRACT
    for field in ("author_id", "avatar_url"):
        source_value = source_payload[field]
        prior_value = prior.get(field)
        if prior_value in (None, ""):
            enriched[field] = source_value
            changes[field] = source_value
        elif prior_value != source_value:
            raise RuntimeError(f"owned account {creator_id} has conflicting {field}")
    for field in ("operational_status", "responsible_person", "team_name"):
        if field not in prior:
            enriched[field] = source_payload[field]
            changes[field] = source_payload[field]
    for field in ("account_positioning", "data_source"):
        source_value = source_payload[field]
        prior_value = prior.get(field)
        if prior_value in (None, ""):
            enriched[field] = source_value
            changes[field] = source_value
        elif prior_value != source_value:
            raise RuntimeError(f"owned account {creator_id} has conflicting {field}")
    return enriched, changes


def _avatar_host(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return urlsplit(value.strip()).hostname


def recover(database_url: str, *, execute: bool) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.public_id, c.canonical_data,
                       c.canonical_data->>'account_name',
                       c.canonical_data->>'platform',
                       c.canonical_data->>'profile_url',
                       c.canonical_data->'source'->>'record_id'
                FROM media_product.creator_profiles AS c
                WHERE c.tenant_id = %s AND c.public_id = ANY(%s)
                ORDER BY c.public_id
                """,
                (TENANT_ID, list(CREATOR_IDS)),
            )
            creator_rows = cursor.fetchall()
            found = {str(row[0]) for row in creator_rows}
            missing = sorted(set(CREATOR_IDS) - found)
            if missing:
                raise RuntimeError("allowlisted creator profiles are missing: " + ", ".join(missing))

            cursor.execute(
                """
                SELECT public_id, canonical_data
                FROM media_product.owned_media_accounts
                WHERE tenant_id = %s AND public_id = ANY(%s)
                ORDER BY public_id
                """,
                (TENANT_ID, list(CREATOR_IDS)),
            )
            existing = {str(row[0]): row[1] for row in cursor.fetchall()}
            entries: list[dict[str, Any]] = []
            for row in creator_rows:
                creator_id = str(row[0])
                payload = _row_to_payload(row)
                creator_data = row[1]
                source_enriched = not isinstance(creator_data.get("author_id"), str) or not creator_data["author_id"].strip()
                if execute and source_enriched:
                    enriched_creator_data = dict(creator_data, author_id=payload["author_id"])
                    cursor.execute(
                        """
                        UPDATE media_product.creator_profiles
                        SET canonical_data = %s::jsonb,
                            revision = revision + 1,
                            updated_at = %s
                        WHERE tenant_id = %s AND public_id = %s
                        """,
                        (json.dumps(enriched_creator_data, ensure_ascii=False), now, TENANT_ID, creator_id),
                    )
                prior = existing.get(creator_id)
                if prior is not None:
                    if not isinstance(prior, dict):
                        raise RuntimeError(f"owned account {creator_id} canonical_data is not an object")
                    enriched, changes = _enrich_recovered_payload(creator_id, prior, payload)
                    action = "enrich" if changes else "already_recovered"
                    entries.append(
                        {
                            "public_id": creator_id,
                            "action": action,
                            "enriched_fields": sorted(changes),
                            "source_creator_enriched": source_enriched,
                        }
                    )
                    if execute and changes:
                        cursor.execute(
                            """
                            UPDATE media_product.owned_media_accounts
                            SET canonical_data = %s::jsonb,
                                revision = revision + 1,
                                updated_at = %s
                            WHERE tenant_id = %s AND public_id = %s
                            """,
                            (json.dumps(enriched, ensure_ascii=False), now, TENANT_ID, creator_id),
                        )
                    continue
                entries.append(
                    {
                        "public_id": creator_id,
                        "action": "insert",
                        "enriched_fields": [
                            "account_positioning",
                            "author_id",
                            "avatar_url",
                            "data_source",
                            "operational_status",
                            "responsible_person",
                            "team_name",
                        ],
                        "source_creator_enriched": source_enriched,
                    }
                )
                if execute:
                    cursor.execute(
                        """
                        INSERT INTO media_product.owned_media_accounts
                            (tenant_id, public_id, revision, canonical_data, created_at, updated_at)
                        VALUES (%s, %s, 1, %s::jsonb, %s, %s)
                        """,
                        (TENANT_ID, creator_id, json.dumps(payload, ensure_ascii=False), now, now),
                    )
            if execute:
                connection.commit()
            else:
                connection.rollback()
            cursor.execute(
                """
                SELECT public_id, canonical_data->>'account_name',
                       canonical_data->>'platform',
                       canonical_data ? 'authorization_status',
                       canonical_data->>'operational_status',
                       canonical_data->>'responsible_person',
                       canonical_data->>'team_name',
                       canonical_data->>'account_positioning',
                       canonical_data->>'data_source',
                       canonical_data->'public_track_ids',
                       canonical_data->>'author_id',
                       canonical_data->>'avatar_url',
                       canonical_data ?& ARRAY[
                           'operational_status', 'responsible_person', 'team_name',
                           'account_positioning', 'data_source'
                       ]
                FROM media_product.owned_media_accounts
                WHERE tenant_id = %s AND public_id = ANY(%s)
                ORDER BY public_id
                """,
                (TENANT_ID, list(CREATOR_IDS)),
            )
            readback = [
                {
                    "public_id": str(row[0]),
                    "account_name": row[1],
                    "platform": row[2],
                    "retired_authorization_field_present": row[3],
                    "operational_status": row[4],
                    "responsible_person": row[5],
                    "team_name": row[6],
                    "account_positioning": row[7],
                    "data_source": row[8],
                    "public_track_ids": row[9],
                    "author_id": row[10],
                    "avatar_host": _avatar_host(row[11]),
                    "ledger_keys_present": row[12],
                }
                for row in cursor.fetchall()
            ]
            if execute and len(readback) != len(CREATOR_IDS):
                raise RuntimeError("owned account readback count did not match recovery set")
            if execute and any(item["retired_authorization_field_present"] for item in readback):
                raise RuntimeError("owned account readback still contains retired authorization field")
            if execute and any(not item["ledger_keys_present"] for item in readback):
                raise RuntimeError("owned account ledger field readback is incomplete")
            if execute and any(
                not item["account_positioning"] or item["data_source"] != "feishu_creator_profile"
                for item in readback
            ):
                raise RuntimeError("owned account ledger source facts are incomplete")
            cursor.execute(
                """
                SELECT public_id, canonical_data->>'author_id',
                       canonical_data->'fields'->>'身份定位'
                FROM media_product.creator_profiles
                WHERE tenant_id = %s AND public_id = ANY(%s)
                ORDER BY public_id
                """,
                (TENANT_ID, list(CREATOR_IDS)),
            )
            source_readback = [
                {"public_id": str(row[0]), "author_id": row[1], "account_positioning": row[2]}
                for row in cursor.fetchall()
            ]
            if execute and any(
                not item["author_id"] or not item["account_positioning"]
                for item in source_readback
            ):
                raise RuntimeError("creator profile ledger source readback is incomplete")
            return {
                "contract": RECOVERY_CONTRACT,
                "tenant_id": TENANT_ID,
                "track_id": TRACK_ID,
                "execute": execute,
                "entries": entries,
                "readback": readback,
                "source_readback": source_readback,
            }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover and migrate confirmed B02 owned accounts")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true", help="insert the allowlisted records")
    parser.add_argument("--output", default="-", help="JSON output path, or - for stdout")
    args = parser.parse_args()
    result = recover(_database_url(args.database_url), execute=args.apply)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(encoded)
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
