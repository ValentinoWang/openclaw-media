"""Import roots for the Router test suite.

`openclaw_app` lives in this directory and `common` lives in the repository
root, so the protected release suites need both on ``sys.path``. Binding them
here keeps a plain ``pytest tests`` run identical to the CI gate instead of
depending on a per-machine ``PYTHONPATH``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROUTER_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = ROUTER_ROOT.parent

# Insert in reverse priority order: the Router root owns `integrations`, which
# must shadow the repository-root package of the same name.
for root in (REPOSITORY_ROOT, ROUTER_ROOT):
    entry = str(root)
    if entry in sys.path:
        sys.path.remove(entry)
    sys.path.insert(0, entry)
