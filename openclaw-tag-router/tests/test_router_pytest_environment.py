from __future__ import annotations

from pathlib import Path


ROUTER_ROOT = Path(__file__).resolve().parent.parent
DIRECT_REQUIREMENTS = {
    "bcrypt": "5.0.0",
    "cryptography": "50.0.0",
    "jsonschema": "4.26.0",
    "Pillow": "12.3.0",
    "playwright": "1.62.0",
    "psycopg[binary]": "3.3.5",
    "pytest": "9.1.1",
    "PyYAML": "6.0.3",
    "requests": "2.34.2",
}


def test_router_test_lock_covers_every_direct_third_party_import() -> None:
    input_text = (ROUTER_ROOT / "requirements-test.in").read_text(encoding="utf-8")
    locked_text = (ROUTER_ROOT / "requirements-test.txt").read_text(encoding="utf-8")
    locked_packages = {
        line.split("==", 1)[0]: line.split("==", 1)[1].split()[0]
        for line in locked_text.splitlines()
        if "==" in line and line.endswith("\\")
    }

    for dependency, version in DIRECT_REQUIREMENTS.items():
        assert f"{dependency}=={version}" in input_text
        normalized_name = dependency.split("[", 1)[0].lower()
        assert locked_packages[normalized_name] == version

    assert "--hash=sha256:" in locked_text


def test_router_test_scripts_preserve_the_stage2_command_and_report_binding() -> None:
    bootstrap = (ROUTER_ROOT / "scripts/qa/bootstrap_router_test_env.sh").read_text(encoding="utf-8")
    runner = (ROUTER_ROOT / "scripts/qa/run_router_pytest.sh").read_text(encoding="utf-8")

    assert "sys.version_info >= (3, 10)" in bootstrap
    assert "PIP_NO_INPUT=1" in bootstrap
    assert "--require-hashes" in bootstrap
    assert "requirements-test.txt" in bootstrap
    assert "from playwright.sync_api import sync_playwright" in bootstrap

    assert "git -C \"$router_root\" rev-parse HEAD" in runner
    assert "PYTHONDONTWRITEBYTECODE=1 \"$test_python\" -m pytest tests/" in runner
    assert "--ignore=tests/test_sync_lark_base_projection.py" in runner
    assert "pytest-output.txt" in runner
    assert "run-metadata.tsv" in runner
    assert "source_sha" in runner
    assert "requirements_sha256" in runner
