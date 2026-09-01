from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml


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
    assert 'ROUTER_TEST_DATABASE_URL:?' in runner
    assert "openclaw_router_test_*" in runner
    assert "scripts/run_postgres_migrations.py apply" in runner
    assert "--mode empty" in runner
    for variable in (
        "OPENCLAW_ACCOUNT_TEST_DATABASE_URL",
        "A2B_TEST_DATABASE_URL",
        "OPENCLAW_U12B_TEST_DATABASE_URL",
        "OPENCLAW_U6_TEST_DATABASE_URL",
        "OPENCLAW_U7_TEST_DATABASE_URL",
        "OPENCLAW_U8_TEST_DATABASE_URL",
    ):
        assert f'export {variable}="$test_database_url"' in runner
    assert "PYTHONDONTWRITEBYTECODE=1 \"$test_python\" -m pytest tests/" in runner
    assert "--ignore=" not in runner
    assert '--junitxml="$junit_report"' in runner
    assert "check_pytest_junit.py" in runner
    assert "pytest-output.txt" in runner
    assert "run-metadata.tsv" in runner
    assert "source_sha" in runner
    assert "requirements_sha256" in runner
    assert "Refusing non-local test database" in runner
    assert "Refusing invalid test database port" in runner
    assert 'pipeline_status=("${PIPESTATUS[@]}")' in runner
    assert "tee_exit_code" in runner


def test_main_integrity_workflow_uses_disposable_postgres_and_zero_skip_runner() -> None:
    workflow_path = ROUTER_ROOT.parent / ".github/workflows/main-integrity-gate.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["router-and-contract"]
    postgres = job["services"]["postgres"]

    assert postgres["image"] == "postgres:16"
    assert postgres["env"] == {
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "POSTGRES_DB": "openclaw_router_test_ci",
    }
    assert postgres["ports"] == ["5432:5432"]
    assert "pg_isready -U postgres -d openclaw_router_test_ci" in postgres["options"]

    complete_suite = next(step for step in job["steps"] if step.get("name") == "Run complete Router suite")
    assert complete_suite["working-directory"] == "openclaw-tag-router"
    assert complete_suite["env"] == {
        "ROUTER_TEST_DATABASE_URL": "postgresql://postgres:postgres@127.0.0.1:5432/openclaw_router_test_ci",
        "ROUTER_PYTEST_REPORT_DIR": "${{ runner.temp }}/router-pytest-report",
    }
    command = complete_suite["run"]
    assert 'ROUTER_TEST_PYTHON="$(command -v python)"' in command
    assert "scripts/qa/run_router_pytest.sh" in command
    assert "python -m pytest" not in command

    artifact = next(step for step in job["steps"] if step.get("name") == "Upload Router pytest evidence")
    assert artifact["if"] == "always()"
    assert artifact["uses"] == "actions/upload-artifact@v4"
    assert artifact["with"]["name"] == "router-pytest-report"
    assert artifact["with"]["path"] == "${{ runner.temp }}/router-pytest-report"
    assert artifact["with"]["if-no-files-found"] == "warn"


def test_router_runner_rejects_missing_or_non_disposable_database_url(tmp_path: Path) -> None:
    runner = ROUTER_ROOT / "scripts/qa/run_router_pytest.sh"
    base_environment = dict(os.environ)
    base_environment.update(
        {
            "ROUTER_TEST_PYTHON": sys.executable,
            "ROUTER_PYTEST_REPORT_DIR": str(tmp_path / "report"),
        }
    )
    base_environment.pop("ROUTER_TEST_DATABASE_URL", None)

    missing = subprocess.run(
        ["bash", str(runner)],
        cwd=ROUTER_ROOT,
        env=base_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing.returncode != 0
    assert "ROUTER_TEST_DATABASE_URL" in missing.stderr

    unsafe_environment = {
        **base_environment,
        "ROUTER_TEST_DATABASE_URL": "postgresql:///production",
    }
    unsafe = subprocess.run(
        ["bash", str(runner)],
        cwd=ROUTER_ROOT,
        env=unsafe_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert unsafe.returncode == 2
    assert "Refusing non-disposable test database name: production" in unsafe.stderr
    assert not (tmp_path / "report/migration-output.txt").exists()

    for index, (database_url, expected_error) in enumerate(
        (
            (
                "postgresql://postgres:postgres@example.com:5432/openclaw_router_test_remote",
                "Refusing non-local test database host: example.com",
            ),
            (
                "postgresql://postgres:postgres@127.0.0.1:99999/openclaw_router_test_port",
                "Refusing invalid test database port: 99999",
            ),
        )
    ):
        rejected = subprocess.run(
            ["bash", str(runner)],
            cwd=ROUTER_ROOT,
            env={
                **base_environment,
                "ROUTER_TEST_DATABASE_URL": database_url,
                "ROUTER_PYTEST_REPORT_DIR": str(tmp_path / f"report-rejected-{index}"),
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode == 2
        assert expected_error in rejected.stderr

    (tmp_path / "report/stale.txt").write_text("stale", encoding="utf-8")
    nonempty = subprocess.run(
        ["bash", str(runner)],
        cwd=ROUTER_ROOT,
        env={
            **base_environment,
            "ROUTER_TEST_DATABASE_URL": "postgresql:///openclaw_router_test_probe",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert nonempty.returncode == 2
    assert "report directory must be empty" in nonempty.stderr


def test_router_skip_guard_has_red_and_green_runtime_proof(tmp_path: Path) -> None:
    guard = ROUTER_ROOT / "scripts/qa/check_pytest_junit.py"
    report = tmp_path / "pytest-junit.xml"
    report.write_text(
        "<testsuites><testsuite><testcase classname=\"tests.test_probe\" name=\"test_green\"/>"
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    green = subprocess.run(
        [sys.executable, str(guard), str(report)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert green.returncode == 0
    assert "0 skipped tests" in green.stdout

    report.write_text(
        '<testsuites><testsuite tests="2" skipped="0">'
        '<testcase classname="tests.test_probe" name="test_green"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    subtest_aggregate = subprocess.run(
        [sys.executable, str(guard), str(report)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert subtest_aggregate.returncode == 0
    assert "0 skipped tests" in subtest_aggregate.stdout

    report.write_text(
        "<testsuites><testsuite><testcase classname=\"tests.test_probe\" name=\"test_skipped\">"
        "<skipped message=\"missing fixture\"/></testcase></testsuite></testsuites>",
        encoding="utf-8",
    )
    red = subprocess.run(
        [sys.executable, str(guard), str(report)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert red.returncode == 3
    assert "tests.test_probe::test_skipped" in red.stderr
    assert "Repair the fixture or test environment" in red.stderr

    for invalid_xml, expected_error in (
        ("<testsuites><testsuite tests=\"0\" skipped=\"0\"/></testsuites>", "no test cases"),
        ("<report><testcase name=\"probe\"/></report>", "unexpected JUnit root"),
        (
            "<testsuites><testsuite tests=\"0\" skipped=\"0\">"
            "<testcase name=\"probe\"/></testsuite></testsuites>",
            "test count mismatch",
        ),
        (
            "<testsuites><testsuite tests=\"1\" skipped=\"1\">"
            "<testcase name=\"probe\"/></testsuite></testsuites>",
            "skip count mismatch",
        ),
        (
            "<testsuites tests=\"1\" skipped=\"0\"><testsuite tests=\"2\" skipped=\"0\">"
            "<testcase name=\"probe\"/></testsuite></testsuites>",
            "root test count mismatch",
        ),
        (
            "<testsuites tests=\"1\" skipped=\"1\"><testsuite tests=\"1\" skipped=\"0\">"
            "<testcase name=\"probe\"/></testsuite></testsuites>",
            "root skip count mismatch",
        ),
    ):
        report.write_text(invalid_xml, encoding="utf-8")
        invalid = subprocess.run(
            [sys.executable, str(guard), str(report)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert invalid.returncode == 2
        assert expected_error in invalid.stderr


def test_router_runner_propagates_the_skip_guard_failure(tmp_path: Path) -> None:
    runner = ROUTER_ROOT / "scripts/qa/run_router_pytest.sh"
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ ${{1:-}} == '-c' ]]; then
  printf 'openclaw_router_test_runner_probe\\n'
elif [[ ${{1:-}} == 'scripts/run_postgres_migrations.py' ]]; then
  exit 0
elif [[ ${{1:-}} == '--version' ]]; then
  printf 'Python runner-probe\\n'
elif [[ ${{1:-}} == '-m' && ${{2:-}} == 'pytest' ]]; then
  for argument in "$@"; do
    if [[ $argument == --junitxml=* ]]; then
      report=${{argument#--junitxml=}}
      printf '%s' '<testsuites><testsuite tests="1" skipped="1"><testcase classname="tests.probe" name="test_skip"><skipped/></testcase></testsuite></testsuites>' > "$report"
    fi
  done
  exit 0
else
  exec {sys.executable!r} "$@"
fi
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    result = subprocess.run(
        ["bash", str(runner)],
        cwd=ROUTER_ROOT,
        env={
            **os.environ,
            "ROUTER_TEST_PYTHON": str(fake_python),
            "ROUTER_PYTEST_REPORT_DIR": str(tmp_path / "report"),
            "ROUTER_TEST_DATABASE_URL": "postgresql:///openclaw_router_test_runner_probe",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 3
    assert "tests.probe::test_skip" in result.stderr
    metadata = (tmp_path / "report/run-metadata.tsv").read_text(encoding="utf-8")
    assert "skip_guard_exit_code\t3" in metadata
    assert "pytest_exit_code\t3" in metadata


def test_router_runner_propagates_tee_failure(tmp_path: Path) -> None:
    runner = ROUTER_ROOT / "scripts/qa/run_router_pytest.sh"
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ ${{1:-}} == '-c' ]]; then
  printf 'openclaw_router_test_runner_probe\\n'
elif [[ ${{1:-}} == 'scripts/run_postgres_migrations.py' ]]; then
  exit 0
elif [[ ${{1:-}} == '--version' ]]; then
  printf 'Python runner-probe\\n'
elif [[ ${{1:-}} == '-m' && ${{2:-}} == 'pytest' ]]; then
  for argument in "$@"; do
    if [[ $argument == --junitxml=* ]]; then
      report=${{argument#--junitxml=}}
      printf '%s' '<testsuites tests="1" skipped="0"><testsuite tests="1" skipped="0"><testcase classname="tests.probe" name="test_green"/></testsuite></testsuites>' > "$report"
    fi
  done
  exit 0
else
  exec {sys.executable!r} "$@"
fi
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "tee").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n/usr/bin/tee \"$@\"\nexit 7\n",
        encoding="utf-8",
    )
    (fake_bin / "tee").chmod(0o755)
    result = subprocess.run(
        ["bash", str(runner)],
        cwd=ROUTER_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "ROUTER_TEST_PYTHON": str(fake_python),
            "ROUTER_PYTEST_REPORT_DIR": str(tmp_path / "report"),
            "ROUTER_TEST_DATABASE_URL": "postgresql:///openclaw_router_test_tee_probe",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 7
    metadata = (tmp_path / "report/run-metadata.tsv").read_text(encoding="utf-8")
    assert "tee_exit_code\t7" in metadata
    assert "skip_guard_exit_code\t0" in metadata
    assert "pytest_exit_code\t7" in metadata
