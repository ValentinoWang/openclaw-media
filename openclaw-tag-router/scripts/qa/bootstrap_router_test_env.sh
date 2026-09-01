#!/usr/bin/env bash
set -euo pipefail

router_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bootstrap_python="${ROUTER_TEST_BOOTSTRAP_PYTHON:-python3}"
venv_dir="${ROUTER_TEST_VENV:-$router_root/.venv-router-tests}"
requirements_file="$router_root/requirements-test.txt"

"$bootstrap_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else "Router tests require Python 3.10+")'
"$bootstrap_python" -m venv "$venv_dir"

PIP_DISABLE_PIP_VERSION_CHECK=1 \
PIP_NO_INPUT=1 \
"$venv_dir/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-input \
  --progress-bar off \
  --require-hashes \
  -r "$requirements_file"

"$venv_dir/bin/python" -c 'import bcrypt, cryptography, jsonschema, PIL, psycopg, pytest, requests, yaml; from playwright.sync_api import sync_playwright; print("Router pytest environment ready")'
