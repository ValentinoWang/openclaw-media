"""Canonical resolver for the isolated DeepMath Feishu account."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

DEFAULT_OPENCLAW_CONFIG = Path("/home/ubuntu/.openclaw-deepmath/openclaw.json")
DEFAULT_OPENCLAW_ENV = Path("/home/ubuntu/.openclaw-deepmath/openclaw.env")
DEEPMATH_ACCOUNT_ID = "deepmath"
DEEPMATH_AGENT_ID = "deepmath-office"
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}\Z")


class DeepMathRuntimeConfigError(ValueError):
    pass


def _read_env(path: Path) -> dict[str, str]:
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DeepMathRuntimeConfigError("DeepMath environment file is unavailable") from exc
    values: dict[str, str] = {}
    for raw in rows:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _resolve(value: Any, env: dict[str, str], *, field: str) -> str:
    text = str(value or "").strip()
    match = _ENV_REFERENCE.fullmatch(text)
    if match:
        text = env.get(match.group(1), "").strip()
    if not text or _ENV_REFERENCE.fullmatch(text):
        raise DeepMathRuntimeConfigError(f"DeepMath {field} is unresolved")
    return text


def load_deepmath_account(
    config_path: str | Path = DEFAULT_OPENCLAW_CONFIG,
    env_path: str | Path = DEFAULT_OPENCLAW_ENV,
) -> tuple[str, str]:
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeepMathRuntimeConfigError("DeepMath OpenClaw config is unavailable") from exc
    account = (((config.get("channels") or {}).get("feishu") or {}).get("accounts") or {}).get(DEEPMATH_ACCOUNT_ID) or {}
    bindings = [
        item for item in config.get("bindings") or []
        if item.get("agentId") == DEEPMATH_AGENT_ID
        and (item.get("match") or {}).get("channel") == "feishu"
        and (item.get("match") or {}).get("accountId") == DEEPMATH_ACCOUNT_ID
    ]
    if len(bindings) != 1:
        raise DeepMathRuntimeConfigError("DeepMath account requires exactly one deepmath-office binding")
    env = _read_env(Path(env_path))
    return _resolve(account.get("appId"), env, field="appId"), _resolve(account.get("appSecret"), env, field="appSecret")


def load_deepmath_allowed_senders(
    config_path: str | Path = DEFAULT_OPENCLAW_CONFIG,
) -> frozenset[str]:
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeepMathRuntimeConfigError("DeepMath OpenClaw config is unavailable") from exc
    feishu = (config.get("channels") or {}).get("feishu") or {}
    account = (feishu.get("accounts") or {}).get(DEEPMATH_ACCOUNT_ID) or {}
    raw = account.get("allowFrom") or feishu.get("allowFrom") or []
    allowed = frozenset(str(value).strip() for value in raw if str(value).strip())
    if not allowed or "*" in allowed:
        raise DeepMathRuntimeConfigError("DeepMath sender allowlist must be explicit and non-empty")
    return allowed
