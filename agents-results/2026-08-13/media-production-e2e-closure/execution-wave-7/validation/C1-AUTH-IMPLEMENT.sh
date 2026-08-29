#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
front="$root/.codex-work/c1-20260814T020215CST/frontend"
back="$root/.codex-work/c1-20260814T020215CST/backend"
protected="$root/scripts/acceptance/test-mpe2e-auth-web.sh"

test "$(shasum -a 256 "$protected" | awk '{print $1}')" = "b52c61bbeaf71ad3db874a5493479d8d0d0ae5a53362cadc2ebe67cc1976c204"
python3 -m py_compile \
  "$back/openclaw_app/account/auth.py" \
  "$back/openclaw_app/account/repository.py" \
  "$back/tests/test_account_auth.py" \
  "$front/production-qa/media_role_qa_foundation.py" \
  "$front/production-qa/manage_media_qa_identities.py" \
  "$front/production-qa/expire_media_qa_session.py" \
  "$front/production-qa/run_media_auth_production_qa.py"

cd "$front"
python3 -m unittest production-qa/test_media_role_qa.py
node_modules/.bin/tsx scripts/qa/checkMediaLoginContract.ts
node_modules/.bin/tsc --noEmit -p tsconfig.media-u12b.json
node_modules/.bin/oxlint scripts/qa/checkMediaAuthProduction.ts
npm run build:media

rg -F 'information_schema.tables AS t' production-qa/run_media_auth_production_qa.py
rg -F 'information_schema.columns AS c' production-qa/run_media_auth_production_qa.py
rg -F 'real empty collection' scripts/qa/checkMediaAuthProduction.ts

test "$(shasum -a 256 "$protected" | awk '{print $1}')" = "b52c61bbeaf71ad3db874a5493479d8d0d0ae5a53362cadc2ebe67cc1976c204"
