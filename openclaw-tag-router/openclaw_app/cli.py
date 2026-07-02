from __future__ import annotations

import argparse
import json

from .app import OpenClawApp


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw 标签路由 MVP")
    parser.add_argument("message", nargs="?", help="例如：【灵感】以后所有碎片想法都从飞书进入")
    parser.add_argument("--settings", default="/home/ubuntu/.openclaw/extensions/openclaw-tag-router/config/settings.yaml")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.message:
        raise SystemExit("请提供消息文本")
    app = OpenClawApp(args.settings)
    result = app.process_text(args.message)
    if args.json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, default=str))
    else:
        print(result.reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
