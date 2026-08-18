#!/usr/bin/env python3
"""Bind the existing Media pilot account to its Feishu organization.

The script is intentionally idempotent and only touches the Media OS tenant,
its Lark binding, member identities, and the platform-admin account.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timezone

import bcrypt
import psycopg
import requests

ORG_NAME = "清华AI小王冲一级的自媒体工作室"
OWNER_USERNAME = "wsy_9523"
ADMIN_USERNAME = "p_admin"
ADMIN_EMAIL = "admin@tsinghua.edu.cn"
ADMIN_DISPLAY_NAME = "P_Admin"
MEDIA_TABLES = (
    "assets", "material_deconstructions", "creative_patterns", "creation_runs",
    "published_posts", "business_accounts", "business_opportunities",
    "creator_profiles", "tracks", "material_usages", "decision_traces",
    "track_creator_memberships", "metric_snapshots", "account_metric_snapshots",
    "growth_summaries",
)


def db_url() -> str:
    value = os.environ.get("OPENCLAW_ACCOUNT_DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("OPENCLAW_ACCOUNT_DATABASE_URL is required")
    return value


def lark_members() -> tuple[str, list[dict]]:
    app_id = os.environ["FEISHU_APP_ID"]
    app_secret = os.environ["FEISHU_APP_SECRET"]
    base = os.environ.get("FEISHU_API_BASE_URL", "https://open.feishu.cn/open-apis").rstrip("/")
    token_response = requests.post(
        base + "/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret}, timeout=20,
    )
    token_response.raise_for_status()
    token_payload = token_response.json()
    if token_payload.get("code") != 0:
        raise RuntimeError("Feishu token exchange failed")
    token = token_payload["tenant_access_token"]
    headers = {"Authorization": "Bearer " + token}
    tenant_response = requests.get(base + "/tenant/v2/tenant/query", headers=headers, timeout=20)
    tenant_response.raise_for_status()
    tenant = (tenant_response.json().get("data") or {}).get("tenant") or {}
    tenant_key = str(tenant.get("tenant_key") or "").strip()
    if not tenant_key:
        raise RuntimeError("Feishu tenant_key was not returned")
    response = requests.get(
        base + "/contact/v3/users/find_by_department",
        params={"department_id": "0", "department_id_type": "open_department_id", "user_id_type": "open_id", "page_size": 50},
        headers=headers, timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError("Feishu member listing failed")
    return tenant_key, list((payload.get("data") or {}).get("items") or [])


def safe_username(open_id: str) -> str:
    suffix = re.sub(r"[^a-z0-9]", "", open_id.lower())[-24:] or secrets.token_hex(8)
    return "lark_" + suffix


def password_hash() -> str:
    return bcrypt.hashpw(secrets.token_urlsafe(32).encode(), bcrypt.gensalt(rounds=12)).decode("ascii")


def main() -> None:
    tenant_key, members = lark_members()
    space_id = os.environ.get("FEISHU_KB_SPACE_ID", "").strip()
    parent = os.environ.get("FEISHU_KB_PARENT_NODE_TOKEN", "").strip()
    if not space_id or not parent:
        raise RuntimeError("FEISHU_KB_SPACE_ID and FEISHU_KB_PARENT_NODE_TOKEN are required")
    with psycopg.connect(db_url()) as conn:
        with conn.cursor() as cur:
            owner = cur.execute(
                "SELECT id FROM openclaw_account.users WHERE username=%s", (OWNER_USERNAME,)
            ).fetchone()
            if owner is None:
                raise RuntimeError("wsy_9523 account not found")
            owner_id = owner[0]
            tenant = cur.execute(
                "SELECT id FROM openclaw_account.tenants WHERE primary_user_id=%s FOR UPDATE", (owner_id,)
            ).fetchone()
            if tenant is None:
                raise RuntimeError("owner tenant not found")
            tenant_id = tenant[0]
            cur.execute(
                """INSERT INTO openclaw_account.affiliate_profiles(user_id, invite_code)
                   VALUES (%s, upper(substr(md5(%s::text || ':mediaclaw-affiliate-v1'), 1, 20)))
                   ON CONFLICT (user_id) DO NOTHING""",
                (owner_id, owner_id),
            )
            cur.execute(
                """UPDATE openclaw_account.tenants
                   SET tenant_type='organization', workspace_mode='organization_lark',
                       body_authority='lark', organization_name=%s, updated_at=now()
                   WHERE id=%s""", (ORG_NAME, tenant_id)
            )
            cur.execute(
                """INSERT INTO media_product.lark_tenant_bindings
                   (tenant_id, tenant_key, installation_public_id, app_id, app_secret_ref, space_id, parent_node_token, status, verified_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'active',now())
                   ON CONFLICT (tenant_id) DO UPDATE SET tenant_key=EXCLUDED.tenant_key,
                     app_id=EXCLUDED.app_id, space_id=EXCLUDED.space_id,
                     parent_node_token=EXCLUDED.parent_node_token, status='active', verified_at=now(), updated_at=now()""",
                (tenant_id, tenant_key, "media-pilot", os.environ["FEISHU_APP_ID"], "env:FEISHU_APP_SECRET", space_id, parent),
            )
            # Preserve the explicitly selected owner even when Feishu member names change.
            cur.execute("UPDATE openclaw_account.tenant_members SET role='owner', status='active' WHERE tenant_id=%s AND user_id=%s", (tenant_id, owner_id))
            seen: set[str] = set()
            upserted = 0
            for item in members:
                external_id = str(item.get("open_id") or item.get("union_id") or "").strip()
                if not external_id:
                    continue
                seen.add(external_id)
                display_name = str(item.get("name") or external_id).strip()[:80]
                email = str(item.get("email") or "").strip().lower() or None
                identity = cur.execute(
                    "SELECT user_id FROM openclaw_account.tenant_member_identities WHERE tenant_id=%s AND external_user_id=%s",
                    (tenant_id, external_id),
                ).fetchone()
                if identity:
                    user_id = identity[0]
                    cur.execute("UPDATE openclaw_account.users SET display_name=%s, email=COALESCE(%s,email), updated_at=now() WHERE id=%s", (display_name, email, user_id))
                else:
                    username = safe_username(external_id)
                    suffix = 1
                    while cur.execute("SELECT 1 FROM openclaw_account.users WHERE username=%s", (username,)).fetchone():
                        suffix += 1
                        username = safe_username(external_id)[:57] + str(suffix)
                    user_id = uuid.uuid4()
                    cur.execute("INSERT INTO openclaw_account.users(id,username,email,password_hash,role,status,display_name) VALUES (%s,%s,%s,%s,'user','active',%s)", (user_id, username, email, password_hash(), display_name))
                    cur.execute("INSERT INTO openclaw_account.tenant_members(tenant_id,user_id,role,status) VALUES (%s,%s,'member','active') ON CONFLICT DO NOTHING", (tenant_id, user_id))
                    cur.execute("INSERT INTO openclaw_account.tenant_member_identities(tenant_id,user_id,tenant_key,open_id,union_id,external_user_id,display_name,email) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (tenant_id, user_id, tenant_key, item.get("open_id"), item.get("union_id"), external_id, display_name, email))
                    upserted += 1
                cur.execute(
                    """INSERT INTO openclaw_account.affiliate_profiles(user_id, invite_code)
                       VALUES (%s, upper(substr(md5(%s::text || ':mediaclaw-affiliate-v1'), 1, 20)))
                       ON CONFLICT (user_id) DO NOTHING""",
                    (user_id, user_id),
                )
                cur.execute("UPDATE openclaw_account.tenant_member_identities SET display_name=%s,email=COALESCE(%s,email),external_status='active',last_synced_at=now(),updated_at=now() WHERE tenant_id=%s AND external_user_id=%s", (display_name, email, tenant_id, external_id))
            cur.execute("UPDATE openclaw_account.tenant_member_identities SET external_status='inactive',updated_at=now() WHERE tenant_id=%s AND external_user_id <> ALL(%s)", (tenant_id, list(seen) or [""]))
            cur.execute("INSERT INTO media_product.lark_member_sync_runs(tenant_id,fetched_count,upserted_count,disabled_count,status,finished_at) VALUES (%s,%s,%s,(SELECT count(*) FROM openclaw_account.tenant_member_identities WHERE tenant_id=%s AND external_status='inactive'),'succeeded',now())", (tenant_id, len(members), upserted, tenant_id))
            for table in MEDIA_TABLES:
                count = cur.execute(f"SELECT count(*) FROM media_product.{table} WHERE tenant_id=%s", (tenant_id,)).fetchone()[0]
                cur.execute("INSERT INTO media_product.tenant_data_migration_audit(source_tenant_id,target_tenant_id,table_name,migrated_count,disposition,reason) VALUES (%s,%s,%s,%s,'migrated','Media OS v2 allowlist; source and target are the pilot tenant') ON CONFLICT (source_tenant_id,target_tenant_id,table_name) DO UPDATE SET migrated_count=EXCLUDED.migrated_count,disposition=EXCLUDED.disposition,reason=EXCLUDED.reason,created_at=now()", (tenant_id, tenant_id, table, count))
            # Create the independent platform administrator requested by the owner.
            cur.execute("UPDATE openclaw_account.users SET email=NULL, updated_at=now() WHERE id=%s AND username=%s", (owner_id, OWNER_USERNAME))
            admin = cur.execute("SELECT id FROM openclaw_account.users WHERE username=%s", (ADMIN_USERNAME,)).fetchone()
            if admin is None:
                admin_id = uuid.uuid4()
                cur.execute("INSERT INTO openclaw_account.users(id,username,email,password_hash,role,status,display_name) VALUES (%s,%s,%s,%s,'admin','active',%s)", (admin_id, ADMIN_USERNAME, ADMIN_EMAIL, bcrypt.hashpw(b"123Qwe,.", bcrypt.gensalt(rounds=12)).decode("ascii"), ADMIN_DISPLAY_NAME))
                admin_tenant_id = uuid.uuid4()
                cur.execute("INSERT INTO openclaw_account.tenants(id,primary_user_id) VALUES (%s,%s)", (admin_tenant_id, admin_id))
                cur.execute("INSERT INTO openclaw_account.tenant_members(tenant_id,user_id,role,status) VALUES (%s,%s,'owner','active')", (admin_tenant_id, admin_id))
            else:
                cur.execute("UPDATE openclaw_account.users SET email=%s,display_name=%s,role='admin',status='active',updated_at=now() WHERE id=%s", (ADMIN_EMAIL, ADMIN_DISPLAY_NAME, admin[0]))
                cur.execute("INSERT INTO openclaw_account.tenant_members(tenant_id,user_id,role,status) SELECT id,%s,'owner','active' FROM openclaw_account.tenants WHERE primary_user_id=%s ON CONFLICT (tenant_id,user_id) DO UPDATE SET role='owner',status='active'", (admin[0], admin[0]))
                admin_id = admin[0]
            cur.execute(
                """INSERT INTO openclaw_account.affiliate_profiles(user_id, invite_code)
                   VALUES (%s, upper(substr(md5(%s::text || ':mediaclaw-affiliate-v1'), 1, 20)))
                   ON CONFLICT (user_id) DO NOTHING""",
                (admin_id, admin_id),
            )
            cur.execute("UPDATE openclaw_account.users SET is_maintainer=false, role='user', updated_at=now() WHERE id=%s AND username=%s", (owner_id, OWNER_USERNAME))
        conn.commit()
    print(f"pilot_tenant={tenant_id} tenant_key={tenant_key} members_fetched={len(members)} new_members={upserted}")


if __name__ == "__main__":
    main()
