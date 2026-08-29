#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-integrated"
evidence_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-executions/wave-luna-remediation-20260817/STAGE1-LUNA-FRONTEND-ORGANIZATION-SHELL/evidence"

check_hash() {
  local expected="$1"
  local path="$2"
  local actual
  actual="$(shasum -a 256 "$path" | awk '{print $1}')"
  if [ "$actual" != "$expected" ]; then
    echo "frozen file drift: $path expected=$expected actual=$actual" >&2
    exit 65
  fi
}

check_hash "331ca8c98818f68d0c34edbc78f80e4f0641063229204914fe14a48d437a5253" "$project_root/frontend/scripts/qa/checkOrganizationWorkspaceShell.ts"
check_hash "13cdb48ff3d0ecc792e0957d98771ad45be7bbc85d577a3df9f8069f089a7953" "$project_root/frontend/scripts/qa/checkPersonalWorkspaceShell.ts"
check_hash "ecb4a33cb7cb698aeba3b3ecf77d0bb5c08730a07a9ef56345103f12f42ba56a" "$project_root/frontend/scripts/qa/checkStage1WorkspaceRuntime.ts"
check_hash "92914cb2b0a83f62e6bc66adc9e9e8f4aceb4ea141404e894e25463afc8743ff" "$project_root/frontend/src/media/mediaWebApi.ts"

mkdir -p "$evidence_root"
cd "$project_root/frontend"
npx tsx scripts/qa/checkOrganizationWorkspaceShell.ts
npx tsx scripts/qa/checkPersonalWorkspaceShell.ts
npx oxlint src/media/OrganizationWorkspaceShellPage.tsx
npx tsc -b tsconfig.media-u12b.json
STAGE1_WORKSPACE_RUNTIME_QA_OUTPUT="$evidence_root" npx tsx scripts/qa/checkStage1WorkspaceRuntime.ts

check_hash "331ca8c98818f68d0c34edbc78f80e4f0641063229204914fe14a48d437a5253" "$project_root/frontend/scripts/qa/checkOrganizationWorkspaceShell.ts"
check_hash "13cdb48ff3d0ecc792e0957d98771ad45be7bbc85d577a3df9f8069f089a7953" "$project_root/frontend/scripts/qa/checkPersonalWorkspaceShell.ts"
check_hash "ecb4a33cb7cb698aeba3b3ecf77d0bb5c08730a07a9ef56345103f12f42ba56a" "$project_root/frontend/scripts/qa/checkStage1WorkspaceRuntime.ts"
check_hash "92914cb2b0a83f62e6bc66adc9e9e8f4aceb4ea141404e894e25463afc8743ff" "$project_root/frontend/src/media/mediaWebApi.ts"
