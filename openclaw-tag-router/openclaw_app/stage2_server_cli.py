"""Current-main owning CLI for the isolated authenticated Stage-2 service."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path

from .account import (
    AccountAuthService,
    AccountDatabase,
    AccountDatabaseSettings,
    AccountSchemaService,
)
from .adapters.http_api import AuthConfig, load_auth_environment
from .adapters.stage2_http_api import Stage2HttpAuthority, make_stage2_http_server
from .services.stage2_main_composition import (
    DEFAULT_STAGE2_CONTRACT,
    build_main_stage2_app,
)


def _loopback(value: str) -> bool:
    if value.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Authenticated OpenClaw Stage-2 isolated HTTP service"
    )
    parser.add_argument(
        "--settings",
        default="/home/ubuntu/.openclaw/extensions/openclaw-tag-router/config/settings.yaml",
    )
    parser.add_argument(
        "--auth-env",
        default="/home/ubuntu/.config/openclaw-bot-center/auth.env",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8892)
    parser.add_argument(
        "--public-origin", default=os.getenv("OPENCLAW_STAGE2_PUBLIC_ORIGIN", "")
    )
    parser.add_argument(
        "--contract", default=os.getenv("OPENCLAW_STAGE2_CONTRACT", str(DEFAULT_STAGE2_CONTRACT))
    )
    parser.add_argument(
        "--factory",
        default=os.getenv(
            "OPENCLAW_STAGE2_FACTORY",
            "openclaw_app.services.stage2_production_factory:build_production_stage2_gateway",
        ),
    )
    parser.add_argument(
        "--acceptance-mode",
        action="store_true",
        help="Allow a provisional contract only on a loopback-only isolated acceptance server.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Assemble all production dependencies and exit without binding a socket.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise RuntimeError("Stage-2 port must be between 1 and 65535")
    if args.acceptance_mode and not _loopback(args.host):
        raise RuntimeError("acceptance mode is restricted to a loopback host")
    if not args.public_origin:
        if args.verify_only:
            args.public_origin = f"http://127.0.0.1:{args.port}"
        else:
            raise RuntimeError("OPENCLAW_STAGE2_PUBLIC_ORIGIN or --public-origin is required")

    auth_environment = load_auth_environment(args.auth_env)
    auth_config = AuthConfig.from_environment(auth_environment)
    account_database = AccountDatabase(
        AccountDatabaseSettings.from_environment(auth_environment)
    )
    AccountSchemaService(account_database).ensure_current()
    account_auth = AccountAuthService(
        account_database,
        csrf_secret=auth_config.session_secret,
        session_ttl_seconds=auth_config.session_ttl_seconds,
    )

    app, identity = build_main_stage2_app(
        settings_path=str(Path(args.settings).expanduser().resolve()),
        contract_path=str(Path(args.contract).expanduser().resolve()),
        factory_reference=args.factory,
        acceptance_mode=args.acceptance_mode,
    )
    if args.verify_only:
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "acceptance" if args.acceptance_mode else "production",
                    "contract": identity.as_dict(),
                    "socketBound": False,
                    "secretsEmitted": False,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 0

    server = make_stage2_http_server(
        args.host,
        args.port,
        stage2_app=app,
        account_auth=account_auth,
        authority=Stage2HttpAuthority(args.public_origin),
        contract_identity=identity,
    )
    print(
        json.dumps(
            {
                "event": "stage2_listening",
                "host": args.host,
                "port": args.port,
                "contractDigest": identity.digest,
                "contractStatus": identity.status,
                "acceptanceMode": identity.acceptance_mode,
                "secretsEmitted": False,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
