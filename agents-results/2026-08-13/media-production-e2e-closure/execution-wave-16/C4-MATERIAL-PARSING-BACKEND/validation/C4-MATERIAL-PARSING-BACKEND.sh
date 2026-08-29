#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
contract="$root/agents-results/2026-08-13/media-production-e2e-closure/contracts/material-parsing-coverage-v1.json"
backend="$root/.codex-work/merge-candidate-v4/backend"
image="sha256:edb4dc9c110bb4b0303d7e85d2f3e73e9dd1a777282c10c73fc664c6d6557db3"
container="c4-material-parsing-backend-$$"
scratch=""

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then
    case "$scratch" in
      /tmp/c4-material-parsing-backend.*) rm -rf -- "$scratch" ;;
      *) echo "refusing to clean unexpected path: $scratch" >&2 ;;
    esac
  fi
}
trap cleanup EXIT INT TERM

test "$(shasum -a 256 "$contract" | awk '{print $1}')" = "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56"
cmp "$contract" "$backend/contracts/material-parsing-coverage-v1.json"
jq -e '.schemaVersion == "1" and (.coverage | length == 54) and ((.coverage | map(.platform + ":" + .materialType) | unique | length) == 54)' "$backend/contracts/material-parsing-coverage-v1.json" >/dev/null
test -f "$backend/openclaw_app/services/material_parsing.py"
test -f "$backend/tests/test_material_parsing.py"

scratch="$(mktemp -d /tmp/c4-material-parsing-backend.XXXXXX)"
mkdir -p "$scratch/backend" "$scratch/external"
cp -a "$backend/." "$scratch/backend/"
: > "$scratch/external/reminder.py"
: > "$scratch/external/setup_media_bitable_registry.py"

docker run --rm --name "$container" --network none \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/backend \
  -v "$scratch/backend:/work/backend" \
  -v "$scratch/external:/home/ubuntu/openclaw-feishu-reminder:ro" \
  -w /work/backend \
  "$image" \
  bash -lc '
    set -euo pipefail
    python=/opt/c4-venv/bin/python
    PYTHONPYCACHEPREFIX=/tmp/c4-material-parsing-pycache "$python" -m py_compile \
      openclaw_app/services/material_parsing.py \
      openclaw_app/services/media_web_tasks.py \
      openclaw_app/services/capability_input_contracts.py
    "$python" -m pytest -q -p no:cacheprovider \
      tests/test_material_parsing.py \
      tests/test_media_web_tasks.py
  '

cmp "$contract" "$backend/contracts/material-parsing-coverage-v1.json"
echo "C4 material parsing backend validation passed"
