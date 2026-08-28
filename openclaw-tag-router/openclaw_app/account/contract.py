from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AccountContractError


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_CONTRACT_PATH = REPOSITORY_ROOT / "docs/ai-harness/openclaw-account-billing-ssot-contract.json"
LEGACY_CONTRACT_PATH = Path("/home/ubuntu/docs/ai-harness/openclaw-account-billing-ssot-contract.json")
CONTRACT_PATH_ENV = "OPENCLAW_ACCOUNT_CONTRACT_PATH"
EXPECTED_SCHEMA_VERSION = "openclaw_account_billing_ssot_v1"


def resolve_account_contract_path() -> Path:
    override = os.getenv(CONTRACT_PATH_ENV)
    if override:
        return Path(override)
    if REPOSITORY_CONTRACT_PATH.is_file():
        return REPOSITORY_CONTRACT_PATH
    return LEGACY_CONTRACT_PATH


CONTRACT_PATH = resolve_account_contract_path()


@dataclass(frozen=True)
class AccountContract:
    payload: dict[str, Any]

    @property
    def database_environment_key(self) -> str:
        return str(self.payload["database"]["environmentKey"])

    @property
    def database_namespace(self) -> str:
        return str(self.payload["database"]["namespace"])

    @property
    def migration_id(self) -> str:
        return str(self.payload["database"]["migrationId"])

    @property
    def error_codes(self) -> frozenset[str]:
        return frozenset(str(key) for key in self.payload["errors"])


def load_account_contract(path: Path = CONTRACT_PATH) -> AccountContract:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AccountContractError("account_contract_invalid", f"cannot load canonical account contract: {exc}") from exc
    if payload.get("schemaVersion") != EXPECTED_SCHEMA_VERSION:
        raise AccountContractError("account_contract_invalid", "canonical account contract version mismatch")
    database = payload.get("database") or {}
    if database.get("engine") != "postgresql" or database.get("environmentKey") != "OPENCLAW_ACCOUNT_DATABASE_URL":
        raise AccountContractError("account_contract_invalid", "canonical account database boundary mismatch")
    if database.get("migrationId") != "cm1-010-persistent-admission-codes" or "revision" in database:
        raise AccountContractError("account_contract_invalid", "canonical account migration identity mismatch")
    return AccountContract(payload=payload)
