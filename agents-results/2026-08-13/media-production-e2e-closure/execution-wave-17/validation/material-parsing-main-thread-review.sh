#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
backend="$root/.codex-work/merge-candidate-v4/backend"
image="sha256:edb4dc9c110bb4b0303d7e85d2f3e73e9dd1a777282c10c73fc664c6d6557db3"
scratch=""
container="material-parsing-http-review-$$"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then
    case "$scratch" in
      /tmp/material-parsing-main-review.*) rm -rf -- "$scratch" ;;
      *) echo "refusing to clean unexpected path: $scratch" >&2 ;;
    esac
  fi
}
trap cleanup EXIT INT TERM

if [ "${MATERIAL_REVIEW_HTTP_ONLY:-0}" != "1" ]; then
  bash "$bundle/execution-wave-16/C4-MATERIAL-PARSING-BACKEND/validation/C4-MATERIAL-PARSING-BACKEND.sh"
  bash "$bundle/execution-wave-16/C3-MATERIAL-PARSING-FRONTEND/validation/C3-MATERIAL-PARSING-FRONTEND.sh"
fi

contract="$bundle/contracts/material-parsing-coverage-v1.json"
test "$(shasum -a 256 "$contract" | awk '{print $1}')" = "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56"
cmp "$contract" "$backend/contracts/material-parsing-coverage-v1.json"
cmp "$contract" "$root/.codex-work/merge-candidate-v4/frontend/contracts/material-parsing-coverage-v1.json"
if rg -n '_expected_failure|URL_AUTO_PARSERS' "$backend/openclaw_app/services/material_parsing.py"; then
  echo "backend contains a second maintained material parsing matrix" >&2
  exit 1
fi

scratch="$(mktemp -d /tmp/material-parsing-main-review.XXXXXX)"
mkdir -p "$scratch/external"
: > "$scratch/external/reminder.py"
: > "$scratch/external/setup_media_bitable_registry.py"
jq -n '
  {
    defaults: {bin: "/usr/bin/false", agent: "knowledge", timeout: 1, cwd: "/tmp", codex_home: "/tmp/codex"},
    model_tiers: {qa: {model: "qa-model", reasoning: "off"}},
    bots: {knowledge: {provider: "qa", model_tier: "qa"}},
    profiles: {
      knowledge_delegate: {bot: "knowledge", provider: "qa", model_tier: "qa"},
      media_creation: {bot: "knowledge", provider: "qa", model_tier: "qa"},
      media_analysis: {bot: "knowledge", provider: "qa", model_tier: "qa"},
      content_cleaner: {bot: "knowledge", provider: "qa", model_tier: "qa", enabled: false, max_chars: 20000, max_tokens: 8192}
    },
    providers: {qa: {base_url: "http://127.0.0.1:9", api_key: "qa-no-secret", api_type: "openai_chat_completions", timeout: 1, default_model_tier: "qa"}}
  }
' > "$scratch/openclaw_bots.json"

docker run --rm --name "$container" --network none \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/backend \
  -v "$backend:/work/backend:ro" \
  -v "$backend/media-agent-cli:/home/ubuntu/selfmedia-tools/media-agent-cli:ro" \
  -v "$backend/contracts/openclaw-media-product-contract.json:/home/ubuntu/docs/ai-harness/openclaw-media-product-contract.json:ro" \
  -v "$scratch/openclaw_bots.json:/home/ubuntu/selfmedia-tools/config/openclaw_bots.json:ro" \
  -v "$scratch/external:/home/ubuntu/openclaw-feishu-reminder:ro" \
  -w /work/backend \
  "$image" \
  bash -lc '
    set -euo pipefail
    python=/opt/c4-venv/bin/python
    PYTHONPYCACHEPREFIX=/tmp/material-parsing-http-pycache "$python" -m py_compile \
      openclaw_app/services/material_parsing.py \
      openclaw_app/services/media_web_tasks.py \
      openclaw_app/adapters/http_api.py
    PYTHONPYCACHEPREFIX=/tmp/material-parsing-http-pycache "$python" -m pytest -q -p no:cacheprovider \
      tests/test_http_api.py::MaterialParsingHttpSerializationTests::test_material_parsing_failure_returns_422_with_browser_readable_details
  '

echo "material parsing main-thread review passed"
