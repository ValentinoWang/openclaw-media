"""Import roots for the root test suite.

Mirrors openclaw-tag-router/tests/conftest.py's approach: this directory
has no __init__.py, so pytest only puts *this* directory on sys.path for
each collected test file. A few of these tests share the
``load_script_module`` helper that lives in
``openclaw-tag-router/tests/_support.py`` (the directory name has a hyphen,
so it can't be reached via a dotted package import) — put that directory on
sys.path too so ``from _support import load_script_module`` resolves.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROUTER_TESTS_DIR = Path(__file__).resolve().parent.parent / "openclaw-tag-router" / "tests"

entry = str(ROUTER_TESTS_DIR)
if entry not in sys.path:
    sys.path.insert(0, entry)
