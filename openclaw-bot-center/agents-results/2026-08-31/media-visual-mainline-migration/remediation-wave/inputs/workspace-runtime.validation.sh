#!/usr/bin/env bash
set -euo pipefail
npx oxlint scripts/qa/checkStage1WorkspaceRuntime.ts
git diff --check -- scripts/qa/checkStage1WorkspaceRuntime.ts
