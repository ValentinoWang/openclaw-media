#!/usr/bin/env python3
"""Run redacted personal/organization Stage-2 acceptance against an isolated server.

Session tokens are read from environment variables and never written to the
report. This runner does not create accounts, mutate systemd, deploy a release,
or claim formal acceptance; it only records the authenticated route evidence it
actually observes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _request(base_url: str, route: str, token: str, operation_id: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + route,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": operation_id,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except Exception:
            payload = {"ok": False, "error": {"code": "invalid_error_body"}}
        return exc.code, payload


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _redacted_result(label: str, first: tuple[int, dict[str, Any]], replay: tuple[int, dict[str, Any]]) -> dict[str, Any]:
    status, body = first
    replay_status, replay_body = replay
    receipt = body.get("receipt") if isinstance(body, dict) else None
    replay_receipt = replay_body.get("receipt") if isinstance(replay_body, dict) else None
    return {
        "label": label,
        "status": status,
        "ok": status == 200 and body.get("ok") is True,
        "receiptDigest": _digest(receipt),
        "replayStatus": replay_status,
        "replayOk": replay_status == 200 and replay_body.get("ok") is True,
        "replayReceiptDigest": _digest(replay_receipt),
        "sameReceipt": _digest(receipt) == _digest(replay_receipt),
        "remoteRefPresent": bool(
            isinstance(receipt, dict)
            and isinstance(receipt.get("artifact"), dict)
            and receipt["artifact"].get("remoteRef")
        ),
        "readbackPresent": bool(
            isinstance(receipt, dict)
            and (receipt.get("mirror") or receipt.get("state"))
        ),
        "errorCode": None if status == 200 else (body.get("error") or {}).get("code"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--personal-session-env", default="STAGE2_ACCEPTANCE_PERSONAL_SESSION")
    parser.add_argument("--organization-session-env", default="STAGE2_ACCEPTANCE_ORGANIZATION_SESSION")
    args = parser.parse_args()

    personal = os.getenv(args.personal_session_env, "").strip()
    organization = os.getenv(args.organization_session_env, "").strip()
    if not personal or not organization:
        raise SystemExit("both disposable acceptance session environment variables are required")

    nonce = secrets.token_hex(8)
    personal_op = f"accept-personal-{nonce}"
    organization_op = f"accept-organization-{nonce}"
    personal_body = {
        "title": "Stage-2 personal acceptance",
        "topic": "source reconciliation",
        "target": "verify personal internal writer and readback",
        "confirmedBy": "acceptance-runner",
        "confirmationRef": f"confirmation-{nonce}",
        "body": f"Personal acceptance marker {nonce}",
        "tradeoffs": [],
        "risks": [],
        "platformConstraints": {},
    }
    organization_body = {
        "title": "Stage-2 organization acceptance",
        "body": f"Organization Feishu readback marker {nonce}",
    }

    personal_first = _request(args.base_url, "/stage2/personal", personal, personal_op, personal_body)
    personal_replay = _request(args.base_url, "/stage2/personal", personal, personal_op, personal_body)
    organization_first = _request(args.base_url, "/stage2/organization", organization, organization_op, organization_body)
    organization_replay = _request(args.base_url, "/stage2/organization", organization, organization_op, organization_body)
    personal_cross = _request(args.base_url, "/stage2/organization", personal, f"cross-p-{nonce}", organization_body)
    organization_cross = _request(args.base_url, "/stage2/personal", organization, f"cross-o-{nonce}", personal_body)

    report = {
        "schemaVersion": "stage2.authenticated-acceptance.v1",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "baseUrlDigest": hashlib.sha256(args.base_url.encode()).hexdigest(),
        "personal": _redacted_result("personal", personal_first, personal_replay),
        "organization": _redacted_result("organization", organization_first, organization_replay),
        "negative": {
            "personalCannotUseOrganization": {
                "status": personal_cross[0],
                "errorCode": (personal_cross[1].get("error") or {}).get("code"),
            },
            "organizationCannotUsePersonal": {
                "status": organization_cross[0],
                "errorCode": (organization_cross[1].get("error") or {}).get("code"),
            },
        },
        "secretsEmitted": False,
        "formalAcceptanceClaimed": False,
        "deploymentPerformed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if report["personal"]["ok"] and report["organization"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
