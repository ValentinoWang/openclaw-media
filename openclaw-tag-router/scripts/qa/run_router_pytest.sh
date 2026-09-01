#!/usr/bin/env bash
set -euo pipefail

router_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_python="${ROUTER_TEST_PYTHON:-$router_root/.venv-router-tests/bin/python}"
report_dir="${ROUTER_PYTEST_REPORT_DIR:?Set ROUTER_PYTEST_REPORT_DIR to an empty report directory.}"
test_database_url="${ROUTER_TEST_DATABASE_URL:?Set ROUTER_TEST_DATABASE_URL to a disposable empty PostgreSQL database.}"
requirements_file="$router_root/requirements-test.txt"

if [[ ! -x "$test_python" ]]; then
  printf 'Router test Python is unavailable: %s\n' "$test_python" >&2
  exit 2
fi

if [[ -e "$report_dir" && ! -d "$report_dir" ]]; then
  printf 'Router pytest report path is not a directory: %s\n' "$report_dir" >&2
  exit 2
fi
if [[ -d "$report_dir" ]] && [[ -n "$(find "$report_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  printf 'Router pytest report directory must be empty: %s\n' "$report_dir" >&2
  exit 2
fi
mkdir -p "$report_dir"

test_database_name="$(
  "$test_python" -c \
    'import sys; from psycopg.conninfo import conninfo_to_dict; print(conninfo_to_dict(sys.argv[1]).get("dbname", ""))' \
    "$test_database_url"
)"
case "$test_database_name" in
  openclaw_router_test_*) ;;
  *)
    printf 'Refusing non-disposable test database name: %s\n' "$test_database_name" >&2
    exit 2
    ;;
esac

(
  cd "$router_root"
  "$test_python" scripts/run_postgres_migrations.py apply \
    --source-root . \
    --dsn "$test_database_url" \
    --mode empty
) >"$report_dir/migration-output.txt"

export OPENCLAW_ACCOUNT_TEST_DATABASE_URL="$test_database_url"
export A2B_TEST_DATABASE_URL="$test_database_url"
export OPENCLAW_U12B_TEST_DATABASE_URL="$test_database_url"
export OPENCLAW_U6_TEST_DATABASE_URL="$test_database_url"
export OPENCLAW_U7_TEST_DATABASE_URL="$test_database_url"
export OPENCLAW_U8_TEST_DATABASE_URL="$test_database_url"

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
junit_report="$report_dir/pytest-junit.xml"
command_text="PYTHONDONTWRITEBYTECODE=1 $test_python -m pytest tests/ --junitxml=$junit_report (six PostgreSQL test variables bound to ROUTER_TEST_DATABASE_URL; zero skips required)"

set +e
(
  cd "$router_root"
  PYTHONDONTWRITEBYTECODE=1 "$test_python" -m pytest tests/ --junitxml="$junit_report"
) 2>&1 | tee "$report_dir/pytest-output.txt"
pytest_status=${PIPESTATUS[0]}
"$test_python" "$router_root/scripts/qa/check_pytest_junit.py" "$junit_report"
skip_guard_status=$?
set -e

if [[ "$pytest_status" -eq 0 && "$skip_guard_status" -ne 0 ]]; then
  pytest_status="$skip_guard_status"
fi

{
  printf 'source_sha\t%s\n' "$source_sha"
  printf 'requirements_sha256\t%s\n' "$requirements_sha"
  printf 'python_version\t%s\n' "$python_version"
  printf 'test_database_name\t%s\n' "$test_database_name"
  printf 'command\t%s\n' "$command_text"
  printf 'skip_guard_exit_code\t%s\n' "$skip_guard_status"
  printf 'pytest_exit_code\t%s\n' "$pytest_status"
} > "$report_dir/run-metadata.tsv"

exit "$pytest_status"
