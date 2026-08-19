from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
from typing import Any

from .services.stage2_contract_validator import contract_digest, validate_contract_file
from .services.stage2_gateway import Stage2Gateway
from .services.stage2_production import Stage2ProductionAssemblyError


DEFAULT_STAGE2_CONTRACT = Path(__file__).resolve().parent / "contracts" / "stage2_writer_contract.json"
_REQUIRED_STAGE2_ENDPOINTS = frozenset({"/stage2/personal", "/stage2/organization"})


def _assert_production_contract(path: str | Path, *, expected_digest: str | None = None) -> None:
    try:
        contract = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise Stage2ProductionAssemblyError(
            "production_contract_unavailable",
            "the Stage-2 production contract is unavailable",
        ) from exc
    if not isinstance(contract, dict):
        raise Stage2ProductionAssemblyError(
            "production_contract_invalid",
            "the Stage-2 production contract must be an object",
        )
    if contract.get("status") != "accepted" or contract.get("runtimeIntegration") is not True:
        raise Stage2ProductionAssemblyError(
            "production_contract_not_accepted",
            "Stage-2 production runtime integration is not accepted",
        )
    endpoints: set[str] = set()
    raw_endpoints = contract.get("endpoints")
    if isinstance(raw_endpoints, list):
        for item in raw_endpoints:
            if isinstance(item, str):
                endpoints.add(item)
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                endpoints.add(item["path"])
    if not _REQUIRED_STAGE2_ENDPOINTS.issubset(endpoints):
        raise Stage2ProductionAssemblyError(
            "production_endpoints_not_accepted",
            "the accepted Stage-2 production endpoints are incomplete",
        )
    if expected_digest is not None and contract_digest(contract) != expected_digest:
        raise Stage2ProductionAssemblyError(
            "production_contract_changed",
            "the Stage-2 production contract changed after validation",
        )


def _load_production_gateway(
    factory_spec: str | None,
    *,
    settings_path: str,
    contract_path: str,
    contract_digest: str,
) -> Stage2Gateway:
    _assert_production_contract(contract_path, expected_digest=contract_digest)
    if not isinstance(factory_spec, str) or ":" not in factory_spec:
        raise Stage2ProductionAssemblyError(
            "production_factory_required",
            "a module:function Stage-2 production factory is required",
        )
    module_name, attribute = (part.strip() for part in factory_spec.split(":", 1))
    if not module_name or not attribute:
        raise Stage2ProductionAssemblyError(
            "production_factory_required",
            "a module:function Stage-2 production factory is required",
        )
    try:
        factory: Any = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise Stage2ProductionAssemblyError(
            "production_factory_unavailable",
            "the Stage-2 production factory is unavailable",
        ) from exc
    if not callable(factory):
        raise Stage2ProductionAssemblyError(
            "production_factory_invalid",
            "the Stage-2 production factory must be callable",
        )
    try:
        gateway = factory(
            settings_path=settings_path,
            contract_path=contract_path,
            contract_digest=contract_digest,
        )
    except Stage2ProductionAssemblyError:
        raise
    except Exception as exc:
        raise Stage2ProductionAssemblyError(
            "production_factory_failed",
            "the Stage-2 production factory failed to assemble a gateway",
        ) from exc
    if not isinstance(gateway, Stage2Gateway):
        raise Stage2ProductionAssemblyError(
            "production_gateway_invalid",
            "the Stage-2 production factory returned an invalid gateway",
        )
    return gateway


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw HTTP API")
    parser.add_argument("--settings", default="/home/ubuntu/.openclaw/extensions/openclaw-tag-router/config/settings.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--stage2-contract",
        default=str(DEFAULT_STAGE2_CONTRACT),
        help="Stage-2 writer contract loaded and validated before the server starts",
    )
    parser.add_argument(
        "--stage2-runtime",
        choices=("disabled", "production"),
        default="disabled",
        help="Stage-2 remains disabled unless an accepted production composition is requested",
    )
    parser.add_argument(
        "--stage2-factory",
        default=None,
        help="module:function that returns a fully composed production Stage2Gateway",
    )
    args = parser.parse_args()
    receipt = validate_contract_file(args.stage2_contract)
    print(f"validated Stage-2 contract {receipt['contractDigest']}", flush=True)
    stage2_gateway = None
    if args.stage2_runtime == "production":
        try:
            stage2_gateway = _load_production_gateway(
                args.stage2_factory,
                settings_path=args.settings,
                contract_path=args.stage2_contract,
                contract_digest=receipt["contractDigest"],
            )
        except Stage2ProductionAssemblyError as exc:
            print(
                f"Stage-2 production startup blocked [{exc.code}]: {exc.message}",
                file=sys.stderr,
                flush=True,
            )
            return 2
    # Import the application only after the immutable contract gate passes.
    # This keeps unrelated router configuration from running before startup
    # has established the Stage-2 contract boundary.
    from .adapters.http_api import make_server
    if args.stage2_runtime == "production":
        from .stage2_server_app import Stage2ServerApp

        app = Stage2ServerApp(args.settings, stage2_gateway=stage2_gateway)
    else:
        from .app import OpenClawApp

        app = OpenClawApp(args.settings, stage2_gateway=stage2_gateway)
    server = make_server(args.host, args.port, app)
    print(f"listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
