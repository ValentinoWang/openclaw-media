from __future__ import annotations

from pathlib import Path


MAINTENANCE_ROOT = Path(__file__).resolve().parents[1] / "runtime/maintenance"
MACHINE_SPECIFIC_PATHS = ("/home/ubuntu", "/Users/vsiyo")


def test_maintenance_scripts_do_not_embed_a_specific_machine_home() -> None:
    violations: list[str] = []
    for path in sorted(MAINTENANCE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for value in MACHINE_SPECIFIC_PATHS:
            if value in text:
                violations.append(f"{path.relative_to(MAINTENANCE_ROOT)}: {value}")

    assert not violations, "\n".join(violations)
