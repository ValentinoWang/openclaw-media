"""Shared, host-portable defaults for external tool roots.

Split out from ``common/social_runtime.py`` (rather than added there)
because that module had a concurrent in-flight edit from another agent at
the time this was written -- see the pe-06/pe-01 audit notes. Nothing here
depends on social_runtime; feel free to fold it back in once that file is
free, but it works standalone.
"""

from __future__ import annotations

import os
from pathlib import Path


def feishu_reminder_root() -> Path:
    """Resolve the openclaw-feishu-reminder checkout root.

    ``OPENCLAW_FEISHU_REMINDER_ROOT`` overrides the default of
    ``~/openclaw-feishu-reminder``. Several call sites re-derived this same
    fallback independently (and some hardcoded ``/home/ubuntu`` instead of
    resolving the home directory), so this is the one place that should own
    it going forward.
    """
    return Path(os.getenv("OPENCLAW_FEISHU_REMINDER_ROOT") or Path.home() / "openclaw-feishu-reminder").expanduser()
