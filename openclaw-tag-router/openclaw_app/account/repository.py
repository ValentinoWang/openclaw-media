from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from .admin_audit import write_admin_audit as _write_admin_audit


@dataclass(frozen=True)
class AccountCredential:
    user_id: UUID
    tenant_id: UUID
    username: str
    email: str | None
    password_hash: str
    role: str
    user_status: str
    tenant_status: str
    is_maintainer: bool


@dataclass(frozen=True)
class AccountSessionRow:
    session_id: UUID
    user_id: UUID
    tenant_id: UUID
    username: str
    email: str | None
    role: str
    user_status: str
    tenant_status: str
    session_status: str
    csrf_token_hash: bytes
    expires_at: datetime
    is_maintainer: bool


class AccountSchemaRepository:
    def has_migration(self, connection: Any, migration_id: str) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM openclaw_account.schema_migrations WHERE migration_id = %s",
                (migration_id,),
            )
            row = cursor.fetchone()
        return row is not None


class AccountAuthRepository:
    def credential_for_login(self, connection: Any, identifier: str) -> AccountCredential | None:
        row = connection.execute(
            """
            SELECT u.id, t.id, u.username, u.email, u.password_hash, u.role, u.status, t.status,
                   u.is_maintainer
            FROM openclaw_account.users AS u
            JOIN openclaw_account.tenants AS t ON t.primary_user_id = u.id
            WHERE u.username = %(identifier)s OR u.email = %(identifier)s
            """,
            {"identifier": identifier},
        ).fetchone()
        return None if row is None else AccountCredential(*row)

    def credential_for_feishu_identity(
        self,
        connection: Any,
        *,
        tenant_key: str,
        open_id: str | None,
        union_id: str | None,
    ) -> AccountCredential | None:
        rows = connection.execute(
            """
            SELECT u.id, t.id, u.username, u.email, u.password_hash, u.role, u.status, t.status,
                   u.is_maintainer
            FROM openclaw_account.tenant_member_identities AS i
            JOIN openclaw_account.tenant_members AS m
              ON m.tenant_id = i.tenant_id AND m.user_id = i.user_id
            JOIN openclaw_account.users AS u ON u.id = i.user_id
            JOIN openclaw_account.tenants AS t ON t.id = i.tenant_id
            WHERE i.tenant_key = %(tenant_key)s
              AND i.external_status = 'active'
              AND m.status = 'active'
              AND (
                    (CAST(%(open_id)s AS text) IS NOT NULL
                     AND i.open_id = CAST(%(open_id)s AS text))
                 OR (CAST(%(union_id)s AS text) IS NOT NULL
                     AND i.union_id = CAST(%(union_id)s AS text))
              )
            LIMIT 2
            """,
            {"tenant_key": tenant_key, "open_id": open_id, "union_id": union_id},
        ).fetchall()
        return AccountCredential(*rows[0]) if len(rows) == 1 else None

    def create_session(
        self,
        connection: Any,
        *,
        session_id: UUID,
        session_token_hash: bytes,
        csrf_token_hash: bytes,
        user_id: UUID,
        tenant_id: UUID,
        expires_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO openclaw_account.sessions(
                id, session_token_hash, csrf_token_hash, user_id, tenant_id, expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (session_id, session_token_hash, csrf_token_hash, user_id, tenant_id, expires_at),
        )

    def session_for_update(self, connection: Any, token_hash: bytes) -> AccountSessionRow | None:
        row = connection.execute(
            """
            SELECT s.id, u.id, t.id, u.username, u.email, u.role, u.status, t.status,
                   s.status, s.csrf_token_hash, s.expires_at, u.is_maintainer
            FROM openclaw_account.sessions AS s
            JOIN openclaw_account.users AS u ON u.id = s.user_id
            JOIN openclaw_account.tenants AS t ON t.id = s.tenant_id
            JOIN openclaw_account.tenant_members AS m
              ON m.tenant_id = s.tenant_id AND m.user_id = s.user_id AND m.status = 'active'
            WHERE s.session_token_hash = %s
            FOR UPDATE OF s
            """,
            (token_hash,),
        ).fetchone()
        return None if row is None else AccountSessionRow(*row)

    def mark_seen(self, connection: Any, session_id: UUID) -> None:
        connection.execute(
            "UPDATE openclaw_account.sessions SET last_seen_at = now() WHERE id = %s",
            (session_id,),
        )

    def mark_expired(self, connection: Any, session_id: UUID) -> None:
        connection.execute(
            "UPDATE openclaw_account.sessions SET status = 'expired' WHERE id = %s AND status = 'active'",
            (session_id,),
        )

    def revoke_by_token_hash(self, connection: Any, token_hash: bytes) -> UUID | None:
        row = connection.execute(
            """
            UPDATE openclaw_account.sessions
            SET status = 'revoked', revoked_at = now()
            WHERE session_token_hash = %s AND status = 'active'
            RETURNING id
            """,
            (token_hash,),
        ).fetchone()
        return None if row is None else row[0]

    def revoke_user_sessions(self, connection: Any, user_id: UUID) -> int:
        cursor = connection.execute(
            """
            UPDATE openclaw_account.sessions
            SET status = 'revoked', revoked_at = now()
            WHERE user_id = %s AND status = 'active'
            """,
            (user_id,),
        )
        return int(cursor.rowcount)

    def update_password(self, connection: Any, user_id: UUID, password_hash: str) -> None:
        connection.execute(
            "UPDATE openclaw_account.users SET password_hash = %s, updated_at = now() WHERE id = %s",
            (password_hash, user_id),
        )

    def create_password_reset(
        self,
        connection: Any,
        *,
        reset_id: UUID,
        user_id: UUID,
        token_hash: bytes,
        expires_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO openclaw_account.password_reset_tokens(id, user_id, token_hash, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (reset_id, user_id, token_hash, expires_at),
        )

    def consume_password_reset(self, connection: Any, token_hash: bytes) -> UUID | None:
        row = connection.execute(
            """
            UPDATE openclaw_account.password_reset_tokens
            SET consumed_at = now()
            WHERE token_hash = %s AND consumed_at IS NULL AND expires_at > now()
            RETURNING user_id
            """,
            (token_hash,),
        ).fetchone()
        return None if row is None else row[0]

    def write_admin_audit(
        self,
        connection: Any,
        *,
        audit_id: UUID,
        actor_user_id: UUID,
        actor_session_id: UUID,
        action: str,
        target_user_id: UUID | None,
        reason: str,
        metadata: str,
    ) -> None:
        _write_admin_audit(
            connection,
            audit_id=audit_id,
            actor_user_id=actor_user_id,
            actor_session_id=actor_session_id,
            action=action,
            target_user_id=target_user_id,
            reason=reason,
            metadata=metadata,
        )
