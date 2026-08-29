#!/usr/bin/env bash
set -euo pipefail

candidate="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-integrated/backend"
cd "$candidate"
export PYTHONPATH="$candidate"
python_bin="$candidate/.venv/bin/python"
test -x "$python_bin"

"$python_bin" -m compileall -q \
  openclaw_app/account openclaw_app/server_cli.py

"$python_bin" -m pytest -q -p no:cacheprovider \
  tests/test_personal_auth_postgres_composition.py \
  tests/test_stage1_personal_auth_lifecycle.py \
  tests/test_server_cli_stage1_composition.py \
  tests/test_account_identity_postgres.py \
  tests/test_account_registration_http_postgres.py

test "$(shasum -a 256 tests/test_stage1_personal_auth_lifecycle.py | awk '{print $1}')" = \
  "d149a683ee0ef2825e5151005d0679f0d883e62b5810aeede637a5c87e7e1e6d"
test "$(shasum -a 256 /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/ssot-development-paths.md | awk '{print $1}')" = \
  "558b40b11c399fd6f5d8b9e766562a07e7ecd8968c83df9a07a60496112659e6"
