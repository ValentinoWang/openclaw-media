#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
image_wave="$bundle/execution-wave-14"
baseline="$root/.codex-work/production-baseline-20260814T084319Z/frontend"
frontend="$root/.codex-work/merge-candidate-v4/frontend"
backend="$root/.codex-work/merge-candidate-v4/backend"
c2_manifest="$bundle/execution-wave-10/C2-V3-FINDINGS-REPAIR/baseline/postrepair-source.sha256"
image="sha256:edb4dc9c110bb4b0303d7e85d2f3e73e9dd1a777282c10c73fc664c6d6557db3"
container="c3-frontend-verify-r4-$$"
scratch=""

sha() { shasum -a 256 "$1" | awk '{print $1}'; }

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then
    case "$scratch" in
      /tmp/c3-frontend-verify-r4.*) rm -rf -- "$scratch" ;;
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
test "$(sha "$frontend/.candidate-source.sha256")" = "17fa19526a96ff2c82df5cd57e162675511a1a9a36718ad186c4d4d619ffa51f"
test "$(wc -l < "$frontend/.candidate-source.sha256" | tr -d ' ')" = "197"
test "$(sha "$backend/.candidate-source.sha256")" = "9519c707bb842bea97e46eb770300417467c10fc5f5c8ce6916182e1f7600018"
test "$(wc -l < "$backend/.candidate-source.sha256" | tr -d ' ')" = "562"
test "$(sha "$image_wave/image/Dockerfile")" = "b1b7ea34b23463f79bed155c30e112f440d908baa8eb1c768522b26b3baf952d"
test "$(sha "$image_wave/image/build-receipt.json")" = "d8741b8c05a0ee5b36cb4fc8f748eccb3225e535d84180168335f8f1749cae2a"

(cd "$baseline" && shasum -a 256 -c .source-manifest.sha256 >/dev/null)
(cd "$root" && shasum -a 256 -c "$c2_manifest" >/dev/null)
(cd "$frontend" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)
(cd "$backend" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)

test -f "$frontend/.merge-provenance.json"
test "$(jq -r '.baseline.frontend_release' "$frontend/.merge-provenance.json")" = "20260814T084319Z-media-login-canonical"
test "$(jq -r '.inputs.c2_source_manifest_sha256' "$frontend/.merge-provenance.json")" = "23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927"
test "$(jq -r '.inputs.auth_contract_sha256' "$frontend/.merge-provenance.json")" = "a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc"

if find "$frontend" "$backend" -type l -print -quit | grep -q .; then
  echo "candidate inputs must not contain symlinks" >&2
  exit 1
fi
if find "$frontend" \( \
  -type d \( -name node_modules -o -name 'dist*' -o -name .cache -o -name __pycache__ -o -name .pytest_cache \) \
  -o -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' -o -name .DS_Store \) \
\) -print -quit | grep -q .; then
  echo "frontend candidate contains dependency, build, cache, or log residue" >&2
  exit 1
fi
if find "$backend" \( \
  -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache -o -name .cache \) \
  -o -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' -o -name .DS_Store \) \
\) -print -quit | grep -q .; then
  echo "backend candidate contains Python cache or transient residue" >&2
  exit 1
fi

for rel in \
  media.login.html \
  media.login.js \
  package.json \
  scripts/qa/checkMediaLoginContract.ts \
  scripts/qa/checkMediaSessionContract.ts; do
  cmp "$baseline/$rel" "$frontend/$rel"
done

image_json="$(docker image inspect "$image")"
test "$(jq -r '.[0].Id' <<<"$image_json")" = "$image"
test "$(jq -r '.[0].Architecture' <<<"$image_json")" = "arm64"
test "$(jq -r '.[0].Os' <<<"$image_json")" = "linux"
jq -e --arg expected "sha256:824f1a789072e648c62541c2cfa4479c4061a290d5c27766d67dc1dcbc19b321" \
  '.[0].Config.Labels["org.opencontainers.image.base.digest"] == $expected' <<<"$image_json" >/dev/null
jq -e --arg expected "f3dd4e9e3671ff2d774938b96bfacf083bdfaad454ee19d8effc9d5b96541dd7" \
  '.[0].Config.Labels["media.verify.frontend-lock.sha256"] == $expected' <<<"$image_json" >/dev/null

scratch="$(mktemp -d /tmp/c3-frontend-verify-r4.XXXXXX)"
mkdir -p "$scratch/frontend"
cp -a "$frontend/." "$scratch/frontend/"

docker run --rm --name "$container" --network none --init --ipc=host \
  -e CI=1 \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e MEDIA_CHROMIUM_LOCK_ROOT=/tmp/c3-frontend-verify-r4-locks \
  -e OPENCLAW_TAG_ROUTER_ROOT=/work/backend \
  -v "$scratch/frontend:/work/frontend" \
  -v "$backend:/work/backend:ro" \
  -w /work/frontend \
  "$image" \
  bash -lc '
    set -euo pipefail
    test "${BASH_VERSINFO[0]}" -ge 5
    command -v flock >/dev/null
    command -v python3 >/dev/null
    test "$OPENCLAW_TAG_ROUTER_ROOT" = "/work/backend"
    test -d "$OPENCLAW_TAG_ROUTER_ROOT/openclaw_app/services"
    npm ci --offline --ignore-scripts --no-audit --no-fund
    npm run qa:media-login-contract
    npm run qa:contextual-capability-launches
    npm run qa:media-recent-task-presentation
    node_modules/.bin/tsc --noEmit -p tsconfig.media-u12b.json
    npm run build:media
  '

test "$(sha "$frontend/.candidate-source.sha256")" = "17fa19526a96ff2c82df5cd57e162675511a1a9a36718ad186c4d4d619ffa51f"
test "$(sha "$backend/.candidate-source.sha256")" = "9519c707bb842bea97e46eb770300417467c10fc5f5c8ce6916182e1f7600018"
(cd "$frontend" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)
(cd "$backend" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)
echo "C3 frontend candidate validation passed in frozen offline Linux/ARM64 image"
