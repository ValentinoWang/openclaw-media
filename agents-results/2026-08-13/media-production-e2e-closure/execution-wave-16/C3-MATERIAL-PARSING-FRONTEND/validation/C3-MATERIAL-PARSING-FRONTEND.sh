#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
contract="$root/agents-results/2026-08-13/media-production-e2e-closure/contracts/material-parsing-coverage-v1.json"
frontend="$root/.codex-work/merge-candidate-v4/frontend"
backend="$root/.codex-work/merge-candidate-v4/backend"
image="sha256:edb4dc9c110bb4b0303d7e85d2f3e73e9dd1a777282c10c73fc664c6d6557db3"
container="c3-material-parsing-frontend-$$"
scratch=""

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then
    case "$scratch" in
      /tmp/c3-material-parsing-frontend.*) rm -rf -- "$scratch" ;;
      *) echo "refusing to clean unexpected path: $scratch" >&2 ;;
    esac
  fi
}
trap cleanup EXIT INT TERM

test "$(shasum -a 256 "$contract" | awk '{print $1}')" = "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56"
cmp "$contract" "$frontend/contracts/material-parsing-coverage-v1.json"
jq -e '.schemaVersion == "1" and (.coverage | length == 54) and ((.coverage | map(.platform + ":" + .materialType) | unique | length) == 54)' "$frontend/contracts/material-parsing-coverage-v1.json" >/dev/null
test -f "$frontend/src/media/task-launch/materialParsing.ts"
test -f "$frontend/scripts/qa/checkMaterialParsing.ts"
rg -q '"qa:material-parsing"' "$frontend/package.json"

scratch="$(mktemp -d /tmp/c3-material-parsing-frontend.XXXXXX)"
mkdir -p "$scratch/frontend"
cp -a "$frontend/." "$scratch/frontend/"

docker run --rm --name "$container" --network none --init --ipc=host \
  -e CI=1 \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e MEDIA_CHROMIUM_LOCK_ROOT=/tmp/c3-material-parsing-locks \
  -e OPENCLAW_TAG_ROUTER_ROOT=/work/backend \
  -v "$scratch/frontend:/work/frontend" \
  -v "$backend:/work/backend:ro" \
  -w /work/frontend \
  "$image" \
  bash -lc '
    set -euo pipefail
    npm ci --offline --ignore-scripts --no-audit --no-fund
    npm run qa:material-parsing
    npm run qa:task-launch
    node_modules/.bin/tsc --noEmit -p tsconfig.media-u12b.json
    npm run build:media
  '

cmp "$contract" "$frontend/contracts/material-parsing-coverage-v1.json"
echo "C3 material parsing frontend validation passed"
