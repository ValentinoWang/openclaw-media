from __future__ import annotations

import json
from pathlib import Path

from openclaw_app.services.guidance_plan import GuidancePlanService, GuidancePlanStore
from openclaw_app.services.message_result_store import MessageResultStore


STORE_ROOT = Path("/home/ubuntu/.openclaw/state/capability_guidance_plans")
MESSAGE_RESULT_ROOT = Path("/home/ubuntu/.openclaw/state/tag_router_message_results")


def main() -> int:
    service = GuidancePlanService(store=GuidancePlanStore(STORE_ROOT))
    result_store = MessageResultStore(MESSAGE_RESULT_ROOT)
    print(
        json.dumps(
            {
                "guidance_plans_purged": service.purge_expired(),
                "message_results_purged": result_store.purge_expired(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
