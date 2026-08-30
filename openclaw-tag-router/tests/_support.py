"""Shared helper for tests that load a standalone script (something under
scripts/ or deploy/, not an installed package) as a module via importlib,
instead of each test file hand-rolling its own copy of the same
spec_from_file_location / module_from_spec / exec_module triple.

``register`` defaults to False: most call sites never put the loaded module
into sys.modules, and unifying that behavior by default would let the same
script get shared as one module object (and any monkeypatching on it leak)
across whichever test files happen to load it in the same process. Only
pass register=True where a caller actually relied on the old local copy
registering the module (e.g. so dataclasses/pickling defined in the script
resolve by qualified name).

This module is local to the openclaw-media repo's own test suites (both
``tests/`` and ``openclaw-tag-router/tests/``, via the ``tests/conftest.py``
sys.path bridge). photo-content-os has its own independent sibling helper;
the two are not shared across repos.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_script_module(
    name: str,
    path: str | Path,
    *,
    register: bool = False,
    optional: bool = False,
) -> ModuleType | None:
    spec = importlib.util.spec_from_file_location(name, path)
    if optional and (not Path(path).is_file() or spec is None or spec.loader is None):
        return None
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
