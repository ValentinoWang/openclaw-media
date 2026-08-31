"""Hydrate bodies for existing tenant-scoped artifact_lark resources."""
from __future__ import annotations

import argparse
import json
import os

from openclaw_app.account import AccountDatabase, AccountDatabaseSettings
from openclaw_app.services.feishu_service import FeishuService
from openclaw_app.services.lark_resource_hydration import LarkResourceHydrationRepository, LarkResourceHydrationService


def main() -> int:
    parser = argparse.ArgumentParser(description="Hydrate existing artifact_lark resources")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--owner", default="", help="Optional existing actor public ID override")
    args = parser.parse_args()
    database = AccountDatabase(AccountDatabaseSettings.from_environment(os.environ))
    feishu = FeishuService(
        mode="knowledge_base",
        local_docs_dir=os.getenv("OPENCLAW_DOCX_SNAPSHOT_DIR", "/tmp/openclaw-lark-hydration"),
        app_id=os.getenv("FEISHU_APP_ID", ""), app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        api_base_url=os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn/open-apis"),
        web_base_url=os.getenv("FEISHU_WEB_BASE_URL", ""),
    )
    result = LarkResourceHydrationService(feishu, LarkResourceHydrationRepository(database.connect)).hydrate(args.tenant_id.strip(), args.owner.strip())
    print(json.dumps(result.__dict__, ensure_ascii=False, default=list))
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
