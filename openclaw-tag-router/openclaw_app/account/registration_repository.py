from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class AdmissionCodeRow:
    code_id: UUID
    status: str


@dataclass(frozen=True)
class AffiliateSourceRow:
    user_id: UUID
    signup_enabled: bool
    signup_quota: int
    signup_used: int
    signup_expires_at: datetime | None
    user_status: str


@dataclass(frozen=True)
class AffiliateProfileRow:
    user_id: UUID
    username: str
    invite_code: str
    signup_enabled: bool
    signup_quota: int
    signup_used: int
    signup_expires_at: datetime | None


class AccountRegistrationRepository:
    def registration_mode_for_registration(self, connection: Any) -> str:
        row = connection.execute(
            "SELECT mode FROM openclaw_account.registration_policy WHERE singleton FOR SHARE"
        ).fetchone()
        if row is None:
            raise RuntimeError("registration policy singleton is missing")
        return str(row[0])

    def registration_mode(self, connection: Any) -> str:
        row = connection.execute(
            "SELECT mode FROM openclaw_account.registration_policy WHERE singleton"
        ).fetchone()
        if row is None:
            raise RuntimeError("registration policy singleton is missing")
        return str(row[0])

    def require_admin(self, connection: Any, user_id: UUID) -> None:
        row = connection.execute(
            "SELECT role, status FROM openclaw_account.users WHERE id = %s FOR UPDATE",
            (user_id,),
        ).fetchone()
        if row is None or row[0] != "admin" or row[1] != "active":
            raise PermissionError("admin_required")

    def admission_code_for_update(self, connection: Any, code_hmac: bytes) -> AdmissionCodeRow | None:
        row = connection.execute(
            """
            SELECT code.id, code.status
            FROM openclaw_account.admission_codes AS code
            JOIN openclaw_account.admission_batches AS batch ON batch.id = code.batch_id
            WHERE code.code_hmac = %s AND batch.status = 'active'
            FOR UPDATE OF code
            """,
            (code_hmac,),
        ).fetchone()
        return None if row is None else AdmissionCodeRow(*row)

    def affiliate_source_for_update(self, connection: Any, invite_code: str) -> AffiliateSourceRow | None:
        row = connection.execute(
            """
            SELECT profile.user_id, profile.signup_enabled, profile.signup_quota,
                   profile.signup_used, profile.signup_expires_at, users.status
            FROM openclaw_account.affiliate_profiles AS profile
            JOIN openclaw_account.users AS users ON users.id = profile.user_id
            WHERE profile.invite_code = %s
            FOR UPDATE OF profile
            """,
            (invite_code,),
        ).fetchone()
        return None if row is None else AffiliateSourceRow(*row)

    def create_account(
        self,
        connection: Any,
        *,
        user_id: UUID,
        tenant_id: UUID,
        wallet_id: UUID,
        username: str,
        email: str | None,
        password_hash: str,
        invite_code: str,
        display_name: str,
        tenant_type: str,
        workspace_mode: str,
        body_authority: str,
        organization_name: str | None,
    ) -> None:
        connection.execute(
            "INSERT INTO openclaw_account.users(id, username, email, password_hash, role, display_name) VALUES (%s, %s, %s, %s, 'user', %s)",
            (user_id, username, email, password_hash, display_name),
        )
        connection.execute(
            """INSERT INTO openclaw_account.tenants(
                id, primary_user_id, tenant_type, workspace_mode, body_authority,
                organization_name
            ) VALUES (%s, %s, %s, %s, %s, %s)""",
            (tenant_id, user_id, tenant_type, workspace_mode, body_authority, organization_name),
        )
        connection.execute(
            "INSERT INTO openclaw_account.tenant_members(tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (tenant_id, user_id),
        )
        connection.execute(
            "INSERT INTO openclaw_account.wallet_accounts(id, tenant_id) VALUES (%s, %s)",
            (wallet_id, tenant_id),
        )
        connection.execute(
            "INSERT INTO openclaw_account.affiliate_profiles(user_id, invite_code) VALUES (%s, %s)",
            (user_id, invite_code),
        )

    def consume_admission_code(self, connection: Any, code_id: UUID, user_id: UUID) -> None:
        cursor = connection.execute(
            """
            UPDATE openclaw_account.admission_codes
            SET status = 'consumed', consumed_by_user_id = %s, consumed_at = now()
            WHERE id = %s AND status = 'active'
            """,
            (user_id, code_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("locked admission code could not be consumed")

    def consume_affiliate_quota(self, connection: Any, inviter_user_id: UUID) -> None:
        cursor = connection.execute(
            """
            UPDATE openclaw_account.affiliate_profiles
            SET signup_used = signup_used + 1, updated_at = now()
            WHERE user_id = %s AND signup_enabled AND signup_used < signup_quota
              AND (signup_expires_at IS NULL OR signup_expires_at > now())
            """,
            (inviter_user_id,),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("locked affiliate quota could not be consumed")

    def create_affiliate_edge(
        self,
        connection: Any,
        *,
        edge_id: UUID,
        inviter_user_id: UUID,
        invitee_user_id: UUID,
    ) -> None:
        connection.execute(
            "INSERT INTO openclaw_account.affiliate_edges(id, inviter_user_id, invitee_user_id) VALUES (%s, %s, %s)",
            (edge_id, inviter_user_id, invitee_user_id),
        )

    def set_registration_policy(
        self,
        connection: Any,
        *,
        mode: str,
        actor_user_id: UUID,
        reason: str,
    ) -> None:
        connection.execute(
            """
            UPDATE openclaw_account.registration_policy
            SET mode = %s, updated_by_user_id = %s, reason = %s, updated_at = now()
            WHERE singleton
            """,
            (mode, actor_user_id, reason),
        )

    def create_admission_batch(
        self,
        connection: Any,
        *,
        batch_id: UUID,
        name: str,
        code_count: int,
        actor_user_id: UUID,
        reason: str,
        codes: list[tuple[UUID, bytes, bytes]],
    ) -> None:
        connection.execute(
            """
            INSERT INTO openclaw_account.admission_batches(
                id, name, code_count, created_by_user_id, created_reason
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (batch_id, name, code_count, actor_user_id, reason),
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO openclaw_account.admission_codes(id, batch_id, code_hmac, code_ciphertext) VALUES (%s, %s, %s, %s)",
                [
                    (code_id, batch_id, code_hmac, code_ciphertext)
                    for code_id, code_hmac, code_ciphertext in codes
                ],
            )

    def disable_admission_batch(
        self,
        connection: Any,
        *,
        batch_id: UUID,
        actor_user_id: UUID,
        reason: str,
    ) -> bool:
        cursor = connection.execute(
            """
            UPDATE openclaw_account.admission_batches
            SET status = 'disabled', disabled_by_user_id = %s,
                disabled_reason = %s, disabled_at = now()
            WHERE id = %s AND status = 'active'
            """,
            (actor_user_id, reason, batch_id),
        )
        return cursor.rowcount == 1

    def update_affiliate_profile(
        self,
        connection: Any,
        *,
        target_user_id: UUID,
        signup_enabled: bool,
        signup_quota: int,
        signup_expires_at: datetime | None,
    ) -> AffiliateProfileRow | None:
        row = connection.execute(
            """
            UPDATE openclaw_account.affiliate_profiles
            SET signup_enabled = %s, signup_quota = %s,
                signup_expires_at = %s, updated_at = now()
            WHERE user_id = %s AND signup_used <= %s
            RETURNING user_id,
                (SELECT username FROM openclaw_account.users WHERE id = user_id),
                invite_code, signup_enabled, signup_quota, signup_used, signup_expires_at
            """,
            (signup_enabled, signup_quota, signup_expires_at, target_user_id, signup_quota),
        ).fetchone()
        return None if row is None else AffiliateProfileRow(*row)

    def affiliate_profile(self, connection: Any, user_id: UUID) -> AffiliateProfileRow | None:
        row = connection.execute(
            """
            SELECT profile.user_id, users.username, profile.invite_code,
                   profile.signup_enabled, profile.signup_quota, profile.signup_used,
                   profile.signup_expires_at
            FROM openclaw_account.affiliate_profiles AS profile
            JOIN openclaw_account.users AS users ON users.id = profile.user_id
            WHERE profile.user_id = %s
            """,
            (user_id,),
        ).fetchone()
        return None if row is None else AffiliateProfileRow(*row)

    def invitees(self, connection: Any, inviter_user_id: UUID, *, limit: int, offset: int) -> tuple[list[Any], int]:
        rows = connection.execute(
            """
            SELECT users.id, users.username, users.created_at
            FROM openclaw_account.affiliate_edges AS edge
            JOIN openclaw_account.users AS users ON users.id = edge.invitee_user_id
            WHERE edge.inviter_user_id = %s
            ORDER BY edge.created_at DESC, users.id
            LIMIT %s OFFSET %s
            """,
            (inviter_user_id, limit, offset),
        ).fetchall()
        total = connection.execute(
            "SELECT count(*) FROM openclaw_account.affiliate_edges WHERE inviter_user_id = %s",
            (inviter_user_id,),
        ).fetchone()[0]
        return list(rows), int(total)

    def admission_batches(self, connection: Any, *, limit: int, offset: int) -> tuple[list[Any], int]:
        rows = connection.execute(
            """
            SELECT batch.id, batch.name, batch.status, batch.code_count,
                   count(code.id) FILTER (WHERE code.status = 'consumed') AS consumed_count,
                   batch.created_at, batch.disabled_at
            FROM openclaw_account.admission_batches AS batch
            LEFT JOIN openclaw_account.admission_codes AS code ON code.batch_id = batch.id
            GROUP BY batch.id
            ORDER BY batch.created_at DESC, batch.id
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        ).fetchall()
        total = connection.execute("SELECT count(*) FROM openclaw_account.admission_batches").fetchone()[0]
        return list(rows), int(total)

    def admission_codes_for_batches(self, connection: Any, batch_ids: list[UUID]) -> list[Any]:
        if not batch_ids:
            return []
        rows = connection.execute(
            """
            SELECT id, batch_id, code_hmac, code_ciphertext, status, consumed_at
            FROM openclaw_account.admission_codes
            WHERE batch_id = ANY(%s) AND code_ciphertext IS NOT NULL
            ORDER BY batch_id, created_at, id
            """,
            (batch_ids,),
        ).fetchall()
        return list(rows)

    def affiliate_users(
        self,
        connection: Any,
        *,
        search: str,
        limit: int,
        offset: int,
    ) -> tuple[list[AffiliateProfileRow], int]:
        pattern = f"%{search}%"
        rows = connection.execute(
            """
            SELECT profile.user_id, users.username, profile.invite_code,
                   profile.signup_enabled, profile.signup_quota, profile.signup_used,
                   profile.signup_expires_at
            FROM openclaw_account.affiliate_profiles AS profile
            JOIN openclaw_account.users AS users ON users.id = profile.user_id
            WHERE %s = '' OR users.username ILIKE %s
            ORDER BY users.created_at DESC, users.id
            LIMIT %s OFFSET %s
            """,
            (search, pattern, limit, offset),
        ).fetchall()
        total = connection.execute(
            """
            SELECT count(*)
            FROM openclaw_account.affiliate_profiles AS profile
            JOIN openclaw_account.users AS users ON users.id = profile.user_id
            WHERE %s = '' OR users.username ILIKE %s
            """,
            (search, pattern),
        ).fetchone()[0]
        return [AffiliateProfileRow(*row) for row in rows], int(total)
