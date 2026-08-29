#!/usr/bin/env bash
set -euo pipefail

host="ubuntu@106.52.146.37"
active="/home/ubuntu/openclaw-bot-center"
copy="/home/ubuntu/worktrees/media-production-e2e-c1-op02-v2"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$host" "set -euo pipefail
  test -d '$copy'
  test -f '$copy/production-qa/run_media_role_qa.py'
  python3 -m py_compile '$copy/production-qa/run_media_role_qa.py'
  if test -f '$copy/production-qa/test_media_role_qa.py'; then
    cd '$copy' && python3 -m unittest discover -s production-qa -p 'test_media_role_qa.py'
  elif test -f '$copy/production-qa/test_run_media_role_qa.py'; then
    cd '$copy' && python3 -m unittest discover -s production-qa -p 'test_run_media_role_qa.py'
  else
    echo 'focused C1 identity/session test is missing' >&2
    exit 1
  fi
  actual=\$(sha256sum \
    '$active/production-qa/run_media_role_qa.py' \
    '$active/scripts/qa/captureMediaRolePages.ts' \
    '$active/scripts/qa/checkMediaWebChannel.ts' \
    '$active/AGENTS.md')
  printf '%s\n' \"\$actual\" | rg -F 'b684351bf639659ceb6b144f3ddf9d44a5d4c3efd654c6665a6568a4612f2b63  $active/production-qa/run_media_role_qa.py'
  printf '%s\n' \"\$actual\" | rg -F '96be1d153e395f93bf879b9dcb2975e6ef63f8dec4573bb2d145c1b823126153  $active/scripts/qa/captureMediaRolePages.ts'
  printf '%s\n' \"\$actual\" | rg -F 'de6165bbeb827b343b3a2dea7b71009c734e6c6b690a7f49b18dbd3c367b44b7  $active/scripts/qa/checkMediaWebChannel.ts'
  printf '%s\n' \"\$actual\" | rg -F '2c1626033f500a00417a8276081264f7e1d46d975590d2f840b62d904debe92b  $active/AGENTS.md'
"
