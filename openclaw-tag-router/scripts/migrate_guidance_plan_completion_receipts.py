#!/usr/bin/env python3
"""One-time migration to the required guidance completionReceipt storage key."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets


DEFAULT_ROOT = Path("/home/ubuntu/.openclaw/state/capability_guidance_plans")
TARGET_PLAN_ID = "capplan_40d30c80fea846cdabf2e1bd4e68703b"
TARGET_RECEIPT = {
    "ok": True,
    "status": "created",
    "reply": (
        "【创作>抖音】已完成。\n"
        "脚本文档：https://tcnwueberajc.feishu.cn/wiki/KkW6w5XeDiaM5fk40nEcV3dtnZe\n"
        "CreationRun：run_20260718_030838_2658"
    ),
    "task_id": "run_20260718_030838_2658",
    "local_path": "",
    "feishu_doc": "https://tcnwueberajc.feishu.cn/wiki/KkW6w5XeDiaM5fk40nEcV3dtnZe",
}


def migrate(root: Path, *, apply: bool) -> dict[str, int | bool]:
    scanned = changed = target_backfilled = 0
    for path in sorted(root.glob("capplan_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"stored plan is not an object: {path}")
        scanned += 1
        desired = TARGET_RECEIPT if payload.get("guidancePlanId") == TARGET_PLAN_ID else payload.get("completionReceipt")
        if payload.get("guidancePlanId") != TARGET_PLAN_ID and "completionReceipt" not in payload:
            desired = None
        if payload.get("completionReceipt") == desired and "completionReceipt" in payload:
            continue
        payload["completionReceipt"] = desired
        changed += 1
        if payload.get("guidancePlanId") == TARGET_PLAN_ID:
            target_backfilled += 1
        if apply:
            temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(path)
    return {"ok": True, "apply": apply, "scanned": scanned, "changed": changed, "target_backfilled": target_backfilled}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.root, apply=args.apply), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
