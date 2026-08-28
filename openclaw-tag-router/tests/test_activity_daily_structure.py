from __future__ import annotations

import ast
from pathlib import Path


def test_activity_daily_mixin_has_no_shadowed_methods() -> None:
    path = Path(__file__).resolve().parents[1] / "openclaw_app" / "router" / "activity_daily.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    activity_mixin = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ActivityDailyMixin"
    )
    names = [node.name for node in activity_mixin.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    assert duplicated == []
