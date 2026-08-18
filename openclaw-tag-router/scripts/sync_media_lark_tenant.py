"""RETIRED compatibility entrypoint.

Use ``scripts/sync_lark_resources.py`` for the canonical tenant-scoped Lark
resource sync.  This entrypoint is deliberately fail-closed so the former
projection path cannot be invoked accidentally.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "retired: use scripts/sync_lark_resources.py for canonical Lark sync",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
