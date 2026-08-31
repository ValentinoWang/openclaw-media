#!/usr/bin/env bash
set -euo pipefail
npx tsx scripts/qa/checkMediaPrimitiveAdoption.ts --self-test
npx oxlint scripts/qa/checkMediaPrimitiveAdoption.ts scripts/qa/checkMediaPrimitiveCoverage.ts
git diff --check -- scripts/qa/checkMediaPrimitiveAdoption.ts scripts/qa/checkMediaPrimitiveCoverage.ts
