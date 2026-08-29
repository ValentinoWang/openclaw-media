#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
baseline="$root/.codex-work/production-baseline-20260814T084319Z/frontend"
candidate="$root/.codex-work/merge-candidate-v4/frontend"
c2_manifest="$bundle/execution-wave-10/C2-V3-FINDINGS-REPAIR/baseline/postrepair-source.sha256"
image="mcr.microsoft.com/playwright:v1.61.1-noble@sha256:824f1a789072e648c62541c2cfa4479c4061a290d5c27766d67dc1dcbc19b321"
container="c3-frontend-verify-r2-$$"
scratch=""

sha() { shasum -a 256 "$1" | awk '{print $1}'; }

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then
    case "$scratch" in
      /tmp/c3-frontend-verify-r2.*) rm -rf -- "$scratch" ;;
      *) echo "refusing to clean unexpected path: $scratch" >&2 ;;
    esac
  fi
}
trap cleanup EXIT INT TERM

test "$(sha "$bundle/.ssot/manifest.json")" = "c6aca57fc2676e8a51704bb607c84245a0e55681bd4202270e659a8290ce9782"
test "$(sha "$bundle/.ssot/nodes/B1.json")" = "cd561d9e4d8b2184b4932da81fc143ae105bf917fc0e520849b6547ca92fabbc"
test "$(sha "$bundle/.ssot/nodes/C3.json")" = "eacf1c368b583ff4f512ec217fad6ed0110613e15107ec22b9842923aa3ec7f3"
test "$(sha "$bundle/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md")" = "a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc"
test "$(sha "$baseline/.source-manifest.sha256")" = "7e27523e6fbb3f5297a15917672ad03082e3c7b919cb99fccf9cba738bc80f14"
test "$(sha "$c2_manifest")" = "23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927"
test "$(sha "$candidate/.candidate-source.sha256")" = "17fa19526a96ff2c82df5cd57e162675511a1a9a36718ad186c4d4d619ffa51f"
test "$(wc -l < "$candidate/.candidate-source.sha256" | tr -d ' ')" = "197"

(cd "$baseline" && shasum -a 256 -c .source-manifest.sha256 >/dev/null)
(cd "$root" && shasum -a 256 -c "$c2_manifest" >/dev/null)
(cd "$candidate" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)

test -f "$candidate/.merge-provenance.json"
test "$(jq -r '.baseline.frontend_release' "$candidate/.merge-provenance.json")" = "20260814T084319Z-media-login-canonical"
test "$(jq -r '.inputs.c2_source_manifest_sha256' "$candidate/.merge-provenance.json")" = "23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927"
test "$(jq -r '.inputs.auth_contract_sha256' "$candidate/.merge-provenance.json")" = "a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc"

if find "$candidate" -type l -print -quit | grep -q .; then
  echo "candidate must not contain symlinks" >&2
  exit 1
fi
if find "$candidate" \( \
  -type d \( -name node_modules -o -name 'dist*' -o -name .cache -o -name __pycache__ -o -name .pytest_cache \) \
  -o -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' -o -name .DS_Store \) \
\) -print -quit | grep -q .; then
  echo "candidate contains dependency, build, cache, or log residue" >&2
  exit 1
fi

for rel in \
  media.login.html \
  media.login.js \
  package.json \
  scripts/qa/checkMediaLoginContract.ts \
  scripts/qa/checkMediaSessionContract.ts; do
  cmp "$baseline/$rel" "$candidate/$rel"
done

rg -n 'required_input_missing|account_relationship_unavailable|account_relationship_conflict' \
  "$candidate/src/media" "$candidate/src/schemas/mediaWebTaskSchema.ts" >/dev/null
rg -n 'runner|executor|receipt|readback|settlement' "$candidate/src/media" >/dev/null
rg -n 'feishu|qr|account|session' \
  "$candidate/media.login.js" "$candidate/scripts/qa/checkMediaLoginContract.ts" >/dev/null

test "$(docker image inspect "$image" --format '{{.Architecture}}')" = "arm64"
test "$(docker image inspect "$image" --format '{{.Os}}')" = "linux"
docker image inspect "$image" --format '{{json .RepoDigests}}' | \
  grep -F 'mcr.microsoft.com/playwright@sha256:824f1a789072e648c62541c2cfa4479c4061a290d5c27766d67dc1dcbc19b321' >/dev/null

scratch="$(mktemp -d /tmp/c3-frontend-verify-r2.XXXXXX)"
cp -a "$candidate/." "$scratch/"

docker run --rm --name "$container" --init --ipc=host \
  -e CI=1 \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e MEDIA_CHROMIUM_LOCK_ROOT=/tmp/c3-frontend-verify-r2-locks \
  -v "$scratch:/work" \
  -w /work \
  "$image" \
  bash -lc '
    set -euo pipefail
    test "${BASH_VERSINFO[0]}" -ge 5
    command -v flock >/dev/null
    node --version
    npm --version
    npm ci --ignore-scripts --no-audit --no-fund
    npm run qa:media-login-contract
    npm run qa:contextual-capability-launches
    npm run qa:media-recent-task-presentation
    node_modules/.bin/tsc --noEmit -p tsconfig.media-u12b.json
    npm run build:media
  '

test "$(sha "$candidate/.candidate-source.sha256")" = "17fa19526a96ff2c82df5cd57e162675511a1a9a36718ad186c4d4d619ffa51f"
(cd "$candidate" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)
echo "C3 frontend candidate validation passed in pinned Linux/ARM64 Playwright image"
