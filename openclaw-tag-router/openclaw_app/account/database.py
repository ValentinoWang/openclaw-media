from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from .contract import AccountContract, load_account_contract
from .errors import AccountContractError


@dataclass(frozen=True)
class AccountDatabaseSettings:
    database_url: str

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        contract: AccountContract | None = None,
    ) -> "AccountDatabaseSettings":
        source = os.environ if environment is None else environment
        active_contract = contract or load_account_contract()
        value = str(source.get(active_contract.database_environment_key) or "").strip()
        if not value:
            raise AccountContractError("account_database_unavailable", "OPENCLAW_ACCOUNT_DATABASE_URL is required")
        scheme = urlsplit(value).scheme.lower()
        if scheme not in {"postgresql", "postgres"}:
            raise AccountContractError("account_contract_invalid", "account database must use PostgreSQL")
        return cls(database_url=value)


class AccountDatabase:
    def __init__(self, settings: AccountDatabaseSettings) -> None:
        self._settings = settings

    def connect(self):
        try:
            import psycopg
            from psycopg.types.string import StrDumperUnknown

            connection = psycopg.connect(self._settings.database_url, autocommit=False)
            # Service contracts carry UUIDs as strings. Let PostgreSQL infer the
            # target type instead of forcing every string parameter to text.
            connection.adapters.register_dumper(str, StrDumperUnknown)
            return connection
        except Exception as exc:
            raise AccountContractError("account_database_unavailable", "cannot connect to canonical account database") from exc
