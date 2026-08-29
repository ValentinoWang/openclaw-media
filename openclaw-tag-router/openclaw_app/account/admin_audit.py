"""Single canonical INSERT for ``openclaw_account.admin_audit``.

``AccountAuthRepository.write_admin_audit`` (see ``repository.py``) is the
authoritative caller: 5 call sites across ``registration.py``/``auth.py``,
all using the 7-column base form. Six other call sites across
``media_business/admin_access.py``, ``media_business/admin_upstreams.py``,
``media_business/admin_billing.py``, ``media_business/admin_tenants.py``
(x2), and ``retail_admin.py`` (x2) carried byte-for-byte or near-identical
copies of the same INSERT. This module is the one place that owns the SQL
text so those copies can delegate instead of drifting.

``stage1_postgres_provisioning.py`` writes a 12-column extended form: the
base 7 columns plus 5 of the 6 columns the 027 migration added
(``target_tenant_id``, ``target_public_tenant_id``, ``operation_id``,
``idempotency_key``, ``request_fingerprint`` -- none of the current call
sites populate ``request_id``, though the column exists and is accepted
here for completeness). Those six columns are optional keyword-only
parameters: a caller that supplies none of them gets the exact 7-column
``ADMIN_AUDIT_INSERT_SQL`` statement byte-for-byte, so the 7-column callers
this consolidation touches are unaffected. A caller that supplies some of
them gets only those columns appended -- we never pad a 7-column caller
out to 12 columns of NULLs, and we never force stage1's 5-of-6 shape into
a fixed 12-column statement that would also bind an unused ``request_id``.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID


ADMIN_AUDIT_INSERT_SQL = """
INSERT INTO openclaw_account.admin_audit(
    id, actor_user_id, actor_session_id, action, target_user_id, reason, metadata
) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
"""

# Columns the 027 migration added, in the order every existing 12-column
# call site binds them.
_EXTENSION_COLUMNS = (
    "request_id",
    "operation_id",
    "target_tenant_id",
    "target_public_tenant_id",
    "idempotency_key",
    "request_fingerprint",
)


def _serialize_metadata(metadata: Any) -> str:
    if isinstance(metadata, str):
        return metadata
    if isinstance(metadata, Mapping):
        return json.dumps(dict(metadata), ensure_ascii=False, separators=(",", ":"))
    raise TypeError("admin_audit metadata must be a JSON string or a mapping")


def write_admin_audit(
    connection: Any,
    *,
    audit_id: UUID,
    actor_user_id: UUID,
    actor_session_id: UUID,
    action: str,
    target_user_id: UUID | None,
    reason: str,
    metadata: Any,
    request_id: UUID | None = None,
    operation_id: str | None = None,
    target_tenant_id: UUID | None = None,
    target_public_tenant_id: str | None = None,
    idempotency_key: str | None = None,
    request_fingerprint: bytes | None = None,
) -> None:
    """Insert one ``openclaw_account.admin_audit`` row.

    ``audit_id`` is always caller-supplied (never generated here) because
    some callers (``admin_billing.save_audit``, ``retail_admin.grant``)
    need the id back to use as ``ledger_entries.source_id``.

    ``metadata`` accepts either a mapping (serialized with
    ``json.dumps(..., ensure_ascii=False, separators=(",", ":"))``) or an
    already-serialized JSON string, which is passed through unchanged.

    The six 027-migration extension columns are bound only when the
    caller supplies a non-None value for them; any left as ``None`` are
    left out of the emitted statement entirely (equivalent to binding
    NULL, since none of these columns has a non-NULL default) so base
    7-column callers are unaffected.
    """
    serialized_metadata = _serialize_metadata(metadata)
    extension_values = {
        "request_id": request_id,
        "operation_id": operation_id,
        "target_tenant_id": target_tenant_id,
        "target_public_tenant_id": target_public_tenant_id,
        "idempotency_key": idempotency_key,
        "request_fingerprint": request_fingerprint,
    }
    extra_columns = [name for name in _EXTENSION_COLUMNS if extension_values[name] is not None]

    if not extra_columns:
        connection.execute(
            ADMIN_AUDIT_INSERT_SQL,
            (audit_id, actor_user_id, actor_session_id, action, target_user_id, reason, serialized_metadata),
        )
        return

    columns = (
        "id, actor_user_id, actor_session_id, action, target_user_id, reason, metadata, "
        + ", ".join(extra_columns)
    )
    placeholders = ", ".join(["%s"] * 6 + ["%s::jsonb"] + ["%s"] * len(extra_columns))
    sql = f"""
INSERT INTO openclaw_account.admin_audit(
    {columns}
) VALUES ({placeholders})
"""
    values = [audit_id, actor_user_id, actor_session_id, action, target_user_id, reason, serialized_metadata]
    values.extend(extension_values[name] for name in extra_columns)
    connection.execute(sql, tuple(values))
