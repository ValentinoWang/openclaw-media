"""Single canonical INSERT for ``openclaw_account.ledger_entries``.

Seven call sites across ``retail_billing.py`` (x3), ``retail_fulfillment.py``
(x3), and ``retail_admin.py`` (x1) carried byte-for-byte identical 11-column
``ledger_entries`` INSERT statements, differing only in the ``entry_type``
and ``source_type`` literals and the bound values. This module owns that one
statement so the seven call sites can delegate instead of drifting.

Deliberately out of scope, per the HIGH-27 audit: the wallet_accounts UPDATE
that always precedes each of these inserts. ``retail_billing.py``'s three
sites update ``available + reserved + version`` (they hold/settle/release
funds); ``retail_fulfillment.py``'s and ``retail_admin.py``'s four sites
update only ``available + version`` (they never touch ``reserved``). Those
are two real, different shapes -- merging them would risk writing to
``reserved`` on a code path that has never touched it. Callers keep their
own wallet UPDATE; this module only wraps the ledger_entries INSERT that
follows it.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID


LEDGER_ENTRY_INSERT_SQL = """
INSERT INTO openclaw_account.ledger_entries(
    id, tenant_id, wallet_account_id, entry_type, available_delta, reserved_delta,
    available_after, reserved_after, source_type, source_id, idempotency_key
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def post_ledger_entry(
    connection: Any,
    *,
    entry_id: UUID,
    tenant_id: UUID,
    wallet_account_id: UUID,
    entry_type: str,
    available_delta: Decimal,
    reserved_delta: Decimal,
    available_after: Decimal,
    reserved_after: Decimal,
    source_type: str,
    source_id: Any,
    idempotency_key: str,
) -> None:
    """Insert one ``openclaw_account.ledger_entries`` row.

    Wraps only the INSERT itself -- the preceding ``wallet_accounts`` UPDATE
    (whether it also moves ``reserved`` or not) and the caller's
    idempotency-key prefix convention (some callers namespace it, e.g.
    ``f"settle:{operation_id}"``; ``retail_admin.grant`` passes the raw
    caller-supplied key with no prefix, by design -- see the docstring
    above) both stay the caller's responsibility.
    """
    connection.execute(
        LEDGER_ENTRY_INSERT_SQL,
        (
            entry_id,
            tenant_id,
            wallet_account_id,
            entry_type,
            available_delta,
            reserved_delta,
            available_after,
            reserved_after,
            source_type,
            source_id,
            idempotency_key,
        ),
    )
