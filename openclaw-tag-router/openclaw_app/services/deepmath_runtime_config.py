"""Canonical resolver for the isolated DeepMath Feishu account."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

DEEPMATH_ROOT_ENV = "OPENCLAW_DEEPMATH_ROOT"
DEEPMATH_ENV_FILE_ENV = "OPENCLAW_DEEPMATH_ENV_FILE"
DEEPMATH_CONFIG_FILE_ENV = "OPENCLAW_DEEPMATH_CONFIG_FILE"
DEEPMATH_ACCOUNT_ID = "deepmath"
DEEPMATH_AGENT_ID = "deepmath-office"
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}\Z")


class DeepMathRuntimeConfigError(ValueError):
    pass


def deepmath_root() -> Path:
    """Resolve the isolated DeepMath state root.

    ``OPENCLAW_DEEPMATH_ROOT`` overrides the default of
    ``~/.openclaw-deepmath``. Read at call time (not baked in as an import-time
    constant or a function-signature default) so it stays monkeypatchable and
    portable across hosts -- the previous ``/home/ubuntu/.openclaw-deepmath``
    literal broke on any host where that isn't the actual home directory.
    """
    configured = os.environ.get(DEEPMATH_ROOT_ENV, "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".openclaw-deepmath"


def deepmath_env_file() -> Path:
    """Resolve the DeepMath openclaw.env file.

    ``OPENCLAW_DEEPMATH_ENV_FILE`` overrides the whole path (matching the
    override this repo's other DeepMath call sites already honor); otherwise
    falls back to ``deepmath_root() / "openclaw.env"``.
    """
    configured = os.environ.get(DEEPMATH_ENV_FILE_ENV, "").strip()
    return Path(configured).expanduser() if configured else deepmath_root() / "openclaw.env"


def deepmath_config_file() -> Path:
    """Resolve the DeepMath openclaw.json file.

    ``OPENCLAW_DEEPMATH_CONFIG_FILE`` overrides the whole path; otherwise
    falls back to ``deepmath_root() / "openclaw.json"``.
    """
    configured = os.environ.get(DEEPMATH_CONFIG_FILE_ENV, "").strip()
    return Path(configured).expanduser() if configured else deepmath_root() / "openclaw.json"


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
    config_path: str | Path | None = None,
    env_path: str | Path | None = None,
) -> tuple[str, str]:
    resolved_config_path = Path(config_path) if config_path is not None else deepmath_config_file()
    try:
        config = json.loads(resolved_config_path.read_text(encoding="utf-8"))
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
    resolved_env_path = Path(env_path) if env_path is not None else deepmath_env_file()
    env = _read_env(resolved_env_path)
    return _resolve(account.get("appId"), env, field="appId"), _resolve(account.get("appSecret"), env, field="appSecret")


def load_deepmath_allowed_senders(
    config_path: str | Path | None = None,
) -> frozenset[str]:
    resolved_config_path = Path(config_path) if config_path is not None else deepmath_config_file()
    try:
        config = json.loads(resolved_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeepMathRuntimeConfigError("DeepMath OpenClaw config is unavailable") from exc
    feishu = (config.get("channels") or {}).get("feishu") or {}
    account = (feishu.get("accounts") or {}).get(DEEPMATH_ACCOUNT_ID) or {}
    raw = account.get("allowFrom") or feishu.get("allowFrom") or []
    allowed = frozenset(str(value).strip() for value in raw if str(value).strip())
    if not allowed or "*" in allowed:
        raise DeepMathRuntimeConfigError("DeepMath sender allowlist must be explicit and non-empty")
    return allowed
