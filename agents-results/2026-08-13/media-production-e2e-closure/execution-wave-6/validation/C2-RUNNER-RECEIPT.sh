#!/usr/bin/env bash
set -euo pipefail

host="ubuntu@106.52.146.37"
active_backend="/home/ubuntu/selfmedia-tools/openclaw-tag-router"
active_frontend="/home/ubuntu/openclaw-bot-center"
copy_root="/home/ubuntu/worktrees/media-production-e2e-c2-op02-v2"
copy_backend="$copy_root/backend"
copy_frontend="$copy_root/frontend"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$host" "set -euo pipefail
  export PATH='/home/ubuntu/.nvm/versions/node/v22.22.2/bin':\"\$PATH\"
  test -d '$copy_backend'
  test -d '$copy_frontend'
  test -f '$copy_backend/openclaw_app/services/media_web_tasks.py'
  test -f '$copy_backend/openclaw_app/migrations/postgres_manifest.json'
  test -f '$copy_frontend/src/media/mediaWebApi.ts'

  if grep -nE 'ThreadPoolExecutor|_executor[.]submit|media-web-task' '$copy_backend/openclaw_app/services/media_web_tasks.py'; then
    echo 'legacy in-process task executor remains' >&2
    exit 1
  fi
  grep -RIlE 'runner_id|runnerId' '$copy_backend/openclaw_app' >/dev/null
  grep -RIlE 'attempt_id|attemptId' '$copy_backend/openclaw_app' >/dev/null
  grep -RIlE 'readback|receipt' '$copy_backend/openclaw_app' >/dev/null
  grep -RIlE '已提交|排队|读回|收据' '$copy_frontend/src/media' >/dev/null

  python3 -m py_compile \
    '$copy_backend/openclaw_app/services/media_web_tasks.py' \
    '$copy_backend/openclaw_app/adapters/http_api.py' \
    '$copy_backend/openclaw_app/server_cli.py' \
    '$copy_backend/openclaw_app/services/media_business/runs.py'

  cd '$copy_backend'
  python3 -m unittest tests.test_media_web_tasks
  runner_tests=\$(find tests -maxdepth 1 -type f \
    \( -name 'test_*runner*.py' -o -name 'test_*receipt*.py' -o -name 'test_*account_binding*.py' \) \
    -print | sort)
  test -n \"\$runner_tests\"
  for test_file in \$runner_tests; do
    module=\${test_file%.py}
    module=\${module//\//.}
    python3 -m unittest \"\$module\"
  done
  python3 -m unittest tests.test_postgres_migration_runner

  cd '$copy_frontend'
  npm run build

  actual_backend=\$(sha256sum \
    '$active_backend/openclaw_app/services/media_web_tasks.py' \
    '$active_backend/openclaw_app/adapters/http_api.py' \
    '$active_backend/openclaw_app/server_cli.py' \
    '$active_backend/openclaw_app/services/media_business/runs.py' \
    '$active_backend/openclaw_app/migrations/postgres_manifest.json' \
    '$active_backend/tests/test_media_web_tasks.py')
  printf '%s\n' \"\$actual_backend\" | grep -F '0c272f9085a640f2ffc19543f2f01e91804b2b593ec6ea01561d6ad83846f1d6  $active_backend/openclaw_app/services/media_web_tasks.py'
  printf '%s\n' \"\$actual_backend\" | grep -F '1a03f08b71a4871346904c247462218ac805a4758ec7f273031b6b357167e83d  $active_backend/openclaw_app/adapters/http_api.py'
  printf '%s\n' \"\$actual_backend\" | grep -F '18aa8ed7add4a4fcfcd726a95903acc5073d568d85cccba081273c99c40a6443  $active_backend/openclaw_app/server_cli.py'
  printf '%s\n' \"\$actual_backend\" | grep -F '8e1bd11a89e6353fd7b381f11f7a61bd6623eb43c3d722532910415ce8872c29  $active_backend/openclaw_app/services/media_business/runs.py'
  printf '%s\n' \"\$actual_backend\" | grep -F 'c81eafb9478119be87a9b713cc3479f40e85e557fc4840063b977e8c69e24960  $active_backend/openclaw_app/migrations/postgres_manifest.json'
  printf '%s\n' \"\$actual_backend\" | grep -F 'f4c38a45e21d110188f3171a025b5b8892d1f14a2e2ce9b0d90e4817638abd2e  $active_backend/tests/test_media_web_tasks.py'

  actual_frontend=\$(sha256sum \
    '$active_frontend/src/media/mediaWebApi.ts' \
    '$active_frontend/src/media/MediaWebWorkspace.tsx' \
    '$active_frontend/src/media/pages/ordinary/RunsPage.tsx' \
    '$active_frontend/src/media/pages/ordinary/OverviewPage.tsx' \
    '$active_frontend/package.json' \
    '$active_frontend/AGENTS.md')
  printf '%s\n' \"\$actual_frontend\" | grep -F '7505c1fa803e02fa5d805758195e9e2f423a7e660c9b1b2dea62b94bacfe26a7  $active_frontend/src/media/mediaWebApi.ts'
  printf '%s\n' \"\$actual_frontend\" | grep -F 'db5443b8538bb93026f5a769dd379e878fb40b9b23479fa82fa965827075deb5  $active_frontend/src/media/MediaWebWorkspace.tsx'
  printf '%s\n' \"\$actual_frontend\" | grep -F 'e200993baca156e12a7aa4d84aa69177c35718040fc646e135678aac824fd033  $active_frontend/src/media/pages/ordinary/RunsPage.tsx'
  printf '%s\n' \"\$actual_frontend\" | grep -F 'fcaf6d9bf8b39e9eb76cec60dcce413dbb2d2766501d09554a5de0d159b945f3  $active_frontend/src/media/pages/ordinary/OverviewPage.tsx'
  printf '%s\n' \"\$actual_frontend\" | grep -F 'dff0ce56f5e0c1f72a2d54869ebff4d36cf6a7498eb1c6184cf0f84a3b36c2aa  $active_frontend/package.json'
  printf '%s\n' \"\$actual_frontend\" | grep -F '2c1626033f500a00417a8276081264f7e1d46d975590d2f840b62d904debe92b  $active_frontend/AGENTS.md'
"

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
test "$(shasum -a 256 "$bundle/acceptance-fragments/MPE2E-TASK-RUN/acceptance-contract.md" | awk '{print $1}')" = "f2f97099c514b8a9b5570c7626cc5e746ce99394370985000cdddd5094a18bf2"
test "$(shasum -a 256 "$root/scripts/acceptance/test-mpe2e-task-run.sh" | awk '{print $1}')" = "334d2393059e54980a8434a99d59bef1b1f82d1466549f540aa40e4f5f0e50d0"
