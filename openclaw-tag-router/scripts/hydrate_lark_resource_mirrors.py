"""RETIRED compatibility entrypoint.

Use ``scripts/hydrate_lark_resources.py`` for canonical append-only hydration
into the Lark read-mirror storage.  This entrypoint is deliberately
fail-closed so it cannot write through the former revision-body path.
"""

from __future__ import annotations

import sys


def hydrate(*_args, **_kwargs):
    raise RuntimeError("retired: use scripts/hydrate_lark_resources.py for canonical Lark hydration")


def main() -> int:
    print(
        "retired: use scripts/hydrate_lark_resources.py for canonical Lark hydration",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
