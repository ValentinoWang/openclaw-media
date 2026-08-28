from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "runtime" / "cli" / "selfmedia.py"


def test_runtime_entrypoint_docs_use_repository_relative_paths() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    env_example = (ROOT / "runtime" / "cli" / "selfmedia.env.example").read_text(encoding="utf-8")
    deconstruct_readme = (ROOT / "selfmedia" / "deconstruct" / "viral_content" / "README.md").read_text(encoding="utf-8")

    assert "/home/ubuntu/selfmedia-tools" not in architecture
    assert "/home/ubuntu/selfmedia-tools" not in env_example
    assert "/home/ubuntu/selfmedia-tools" not in deconstruct_readme
    assert "runtime/cli/selfmedia.py" in architecture
    assert "root `.env.local`" in env_example


def test_selfmedia_help_uses_the_checkout_independent_entrypoint_description() -> None:
    completed = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Selfmedia module unified entrypoint." in completed.stdout
    assert "/home/ubuntu/selfmedia-tools" not in completed.stdout
