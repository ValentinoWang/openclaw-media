#!/usr/bin/env bash
set -euo pipefail

router_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_python="${ROUTER_TEST_PYTHON:-$router_root/.venv-router-tests/bin/python}"
report_dir="${ROUTER_PYTEST_REPORT_DIR:?Set ROUTER_PYTEST_REPORT_DIR to an empty report directory.}"
requirements_file="$router_root/requirements-test.txt"

if [[ ! -x "$test_python" ]]; then
  printf 'Router test Python is unavailable: %s\n' "$test_python" >&2
  exit 2
fi

mkdir -p "$report_dir"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

source_sha="$(git -C "$router_root" rev-parse HEAD)"
requirements_sha="$(sha256_file "$requirements_file")"
python_version="$("$test_python" --version)"
command_text="PYTHONDONTWRITEBYTECODE=1 $test_python -m pytest tests/ --ignore=tests/test_sync_lark_base_projection.py"

set +e
(
  cd "$router_root"
  PYTHONDONTWRITEBYTECODE=1 "$test_python" -m pytest tests/ --ignore=tests/test_sync_lark_base_projection.py
) 2>&1 | tee "$report_dir/pytest-output.txt"
pytest_status=${PIPESTATUS[0]}
set -e

{
  printf 'source_sha\t%s\n' "$source_sha"
  printf 'requirements_sha256\t%s\n' "$requirements_sha"
  printf 'python_version\t%s\n' "$python_version"
  printf 'command\t%s\n' "$command_text"
  printf 'pytest_exit_code\t%s\n' "$pytest_status"
} > "$report_dir/run-metadata.tsv"

exit "$pytest_status"
