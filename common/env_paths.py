"""Single source of truth for the media-agent secrets root and its env files.

`OPENCLAW_MEDIA_AGENT_ROOT` controls where the media-agent secrets directory
lives (MEDIA_OS_*, FEISHU_*, and similar tokens read from `.env`/`.env.local`
there). Prior to this module, `selfmedia/business/id_business.py` and
`selfmedia/deconstruct/viral_content/src/feishu_writer.py` each re-derived
the same default independently, and the latter only loaded `.env.local`
(never `.env`) -- this module is the shared implementation both now delegate
to so the default and the load order can't drift apart again.

`selfmedia/creation/retrieval.py` intentionally keeps its own fallback chain
(a different default root plus `OPENCLAW_MEDIA_ENV_FILE` support) and is not
routed through here for its no-override-set case; see that module.
"""

from __future__ import annotations

import os
from pathlib import Path

from common.social_runtime import load_env_file

DEFAULT_MEDIA_AGENT_ROOT = Path.home() / ".openclaw" / "agents" / "media"


def media_agent_root() -> Path:
    """Resolve the media-agent secrets root.

    `OPENCLAW_MEDIA_AGENT_ROOT` overrides the default of
    `~/.openclaw/agents/media`.
    """
    return Path(os.getenv("OPENCLAW_MEDIA_AGENT_ROOT") or DEFAULT_MEDIA_AGENT_ROOT).expanduser()


def load_media_agent_env_files(root: Path | None = None) -> None:
    """Load `.env` then `.env.local` from the media-agent secrets root.

    Both files are loaded (`load_env_file` only fills keys not already in
    `os.environ`, so `.env` takes precedence over `.env.local` for any key
    present in both -- matching the existing id_business.py load order).
    """
    base = root if root is not None else media_agent_root()
    for path in (base / ".env", base / ".env.local"):
        load_env_file(path)
