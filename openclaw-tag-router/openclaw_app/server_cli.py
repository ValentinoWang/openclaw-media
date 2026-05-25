from __future__ import annotations

import argparse

from .app import OpenClawApp
from .adapters.http_api import make_server


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw HTTP API")
    parser.add_argument("--settings", default="/home/ubuntu/.openclaw/extensions/openclaw-tag-router/config/settings.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    app = OpenClawApp(args.settings)
    server = make_server(args.host, args.port, app)
    print(f"listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
