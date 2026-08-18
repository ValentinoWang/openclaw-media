"""Run one tenant-scoped Lark resource discovery/sync.

Credentials must be loaded by the invoking service environment; this command
does not accept credentials as arguments and never prints environment values.
"""

from __future__ import annotations

import argparse
import os
import sys

from openclaw_app.account import AccountDatabase, AccountDatabaseSettings
from openclaw_app.services.feishu_service import FeishuService
from openclaw_app.services.lark_resource_sync import LarkResourceSyncRepository, LarkResourceSyncService


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync one tenant's Lark wiki resources")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--owner", required=True, help="Existing actor public ID")
    parser.add_argument("--root-node-token", default="")
    args = parser.parse_args()
    root = args.root_node_token.strip()
    database = AccountDatabase(AccountDatabaseSettings.from_environment(os.environ))
    with database.connect() as connection:
        if not root:
            row = connection.execute(
                "SELECT parent_node_token FROM media_product.lark_tenant_bindings WHERE tenant_id=%s AND status='active'",
                (args.tenant_id.strip(),),
            ).fetchone()
            if row is None or not str(row[0] or "").strip():
                raise RuntimeError("active Lark tenant binding has no parent node")
            root = str(row[0]).strip()
    feishu = FeishuService(
        mode="knowledge_base",
        local_docs_dir=os.getenv("OPENCLAW_DOCX_SNAPSHOT_DIR", "/tmp/openclaw-lark-discovery"),
        app_id=os.getenv("FEISHU_APP_ID", ""),
        app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        api_base_url=os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn/open-apis"),
        web_base_url=os.getenv("FEISHU_WEB_BASE_URL", "https://tcnwuebarajc.feishu.cn"),
    )
    result = LarkResourceSyncService(feishu, LarkResourceSyncRepository(database.connect)).discover_and_sync(
        args.tenant_id.strip(), args.owner.strip(), root
    )
    print(
        f"discovered={result.discovered} inserted={result.inserted} "
        f"updated={result.updated} unchanged={result.unchanged}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
