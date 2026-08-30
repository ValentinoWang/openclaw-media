from __future__ import annotations

from pathlib import Path

import pytest

from _support import load_script_module


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "qa"
    / "backfill_owned_accounts_from_explicit_creator_profiles.py"
)
backfill = load_script_module("backfill_owned_accounts", SCRIPT)


def creator_row() -> tuple[object, ...]:
    canonical_data = {
        "author_id": "93130816637",
        "avatar_url": "https://cdn.example.test/avatar.jpg",
        "creator_role": "creator",
        "identity_tags": ["校园"],
        "expertise_domains": ["短跑"],
        "fields": {"身份定位": "面向校园人群的短跑训练账号。"},
    }
    return (
        "creator_rec123456",
        canonical_data,
        "测试账号",
        "抖音",
        "https://www.douyin.com/user/example",
        "rec123456",
    )


def test_recovery_payload_copies_explicit_ledger_facts_without_authorization() -> None:
    payload = backfill._row_to_payload(creator_row())

    assert payload["author_id"] == "93130816637"
    assert payload["avatar_url"] == "https://cdn.example.test/avatar.jpg"
    assert payload["operational_status"] is None
    assert payload["responsible_person"] is None
    assert payload["team_name"] is None
    assert payload["account_positioning"] == "面向校园人群的短跑训练账号。"
    assert payload["data_source"] == "feishu_creator_profile"
    assert "authorization_status" not in payload


def test_v1_recovery_is_migrated_and_enriched_idempotently() -> None:
    source_payload = backfill._row_to_payload(creator_row())
    prior = dict(source_payload)
    for field in (
        "author_id",
        "avatar_url",
        "operational_status",
        "responsible_person",
        "team_name",
        "account_positioning",
        "data_source",
    ):
        prior.pop(field)
    prior["authorization_status"] = "pending"
    prior["source"] = dict(
        source_payload["source"],
        recovery_contract=backfill.LEGACY_RECOVERY_CONTRACT,
    )

    enriched, changes = backfill._enrich_recovered_payload(
        "creator_rec123456",
        prior,
        source_payload,
    )
    repeated, repeated_changes = backfill._enrich_recovered_payload(
        "creator_rec123456",
        enriched,
        source_payload,
    )

    assert "authorization_status" not in enriched
    assert enriched["operational_status"] is None
    assert enriched["responsible_person"] is None
    assert enriched["team_name"] is None
    assert enriched["account_positioning"] == "面向校园人群的短跑训练账号。"
    assert enriched["data_source"] == "feishu_creator_profile"
    assert enriched["source"]["recovery_contract"] == backfill.RECOVERY_CONTRACT
    assert set(changes) == {
        "account_positioning",
        "authorization_status",
        "author_id",
        "avatar_url",
        "data_source",
        "operational_status",
        "responsible_person",
        "source.recovery_contract",
        "team_name",
    }
    assert repeated == enriched
    assert repeated_changes == {}


def test_existing_recovery_with_conflicting_avatar_fails_closed() -> None:
    source_payload = backfill._row_to_payload(creator_row())
    prior = dict(source_payload, avatar_url="https://cdn.example.test/other.jpg")

    with pytest.raises(RuntimeError, match="conflicting avatar_url"):
        backfill._enrich_recovered_payload("creator_rec123456", prior, source_payload)


def test_recovery_without_explicit_account_positioning_fails_closed() -> None:
    row = list(creator_row())
    canonical_data = dict(row[1])
    canonical_data["fields"] = {}
    row[1] = canonical_data

    with pytest.raises(RuntimeError, match="missing explicit ledger fields"):
        backfill._row_to_payload(tuple(row))
