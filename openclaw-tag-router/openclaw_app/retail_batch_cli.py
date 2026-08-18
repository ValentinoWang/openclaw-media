from __future__ import annotations

import argparse
import json

from .account import AccountDatabase, AccountDatabaseSettings
from .adapters.http_api import load_auth_environment
from .services.retail_fulfillment import RetailFulfillmentService, load_redemption_secret


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a protected OpenClaw redemption-code batch")
    parser.add_argument("--auth-env", required=True)
    parser.add_argument("--redemption-hmac-secret-file", required=True)
    parser.add_argument("--export-root", required=True)
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--plan-code", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args()

    environment = load_auth_environment(args.auth_env)
    service = RetailFulfillmentService(
        AccountDatabase(AccountDatabaseSettings.from_environment(environment)),
        code_secret=load_redemption_secret(args.redemption_hmac_secret_file),
        export_root=args.export_root,
    )
    issue = service.create_batch(
        actor_user_id=args.actor_user_id,
        plan_code=args.plan_code,
        count=args.count,
        idempotency_key=args.idempotency_key,
    )
    print(
        json.dumps(
            {
                "batchId": str(issue.batch_id),
                "codeCount": issue.code_count,
                "exportPath": str(issue.export_path),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
