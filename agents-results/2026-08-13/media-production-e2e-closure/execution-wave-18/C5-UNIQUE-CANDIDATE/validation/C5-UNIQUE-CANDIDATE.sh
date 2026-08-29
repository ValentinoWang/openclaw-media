#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
candidate="$root/.codex-work/merge-candidate-v4"
frontend="$candidate/frontend"
backend="$candidate/backend"
contract="$bundle/contracts/material-parsing-coverage-v1.json"
manifest="$candidate/candidate-manifest.json"
manifest_checksum="$candidate/candidate-manifest.sha256"
result="$bundle/execution-wave-18/C5-UNIQUE-CANDIDATE/result.md"
scratch=""

sha() {
  shasum -a 256 "$1" | awk '{print $1}'
}

cleanup() {
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then
    case "$scratch" in
      /tmp/c5-unique-candidate.*) rm -rf -- "$scratch" ;;
      *) echo "refusing to clean unexpected path: $scratch" >&2 ;;
    esac
  fi
}
trap cleanup EXIT INT TERM

test "$(sha "$bundle/.ssot/manifest.json")" = "ff38d36843e7170ec3a6126fd200c63a0c2f7eed9380ea44c20835d33673c1fc"
test "$(sha "$bundle/.ssot/nodes/C3.json")" = "87f9b93556f99b8358540dc076bcdf9cf2fc496b7cad787d1aef8b5e611559d0"
test "$(sha "$bundle/.ssot/nodes/C4.json")" = "340a85565ab50738163742f19e1cf5eb3a0e80400d4a6faedddcd167302599f8"
test "$(sha "$bundle/.ssot/nodes/C5.json")" = "1fce14e05f8ce0fda991b16ecd2a5156e29d30f17c266f2ed7a61990db6ff0f4"
jq -e '.execution_state == "ACCEPTED"' "$bundle/.ssot/nodes/C3.json" >/dev/null
jq -e '.execution_state == "ACCEPTED"' "$bundle/.ssot/nodes/C4.json" >/dev/null
jq -e '.execution_state == "READY" and .readiness_mode == "FORMAL"' "$bundle/.ssot/nodes/C5.json" >/dev/null
test "$(sha "$contract")" = "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56"
test "$(sha "$bundle/execution-wave-17/result.md")" = "27cfc24b13d7618127996a72f57c38608f4a0df2a32f213104823b6c97021dbf"
test "$(sha "$bundle/execution-wave-17/validation/material-parsing-main-thread-review.sh")" = "fc2bec23ab69da35d18e269bb4cd1a0236eb3929c33c943ee4bff4e6da02de8b"

cmp "$contract" "$frontend/contracts/material-parsing-coverage-v1.json"
cmp "$contract" "$backend/contracts/material-parsing-coverage-v1.json"
jq -e '
  .contractId == "media-material-parsing-coverage-v1"
  and (.platforms | length) == 9
  and (.materialTypes | length) == 6
  and (.coverage | length) == 54
  and ((.coverage | map(.platform + ":" + .materialType) | unique | length) == 54)
  and .completionStatuses == ["completed_auto", "completed_manual"]
' "$contract" >/dev/null

test "$(jq -r '.schemaVersion' "$backend/.release-coordination.json")" = "openclaw-media-release-coordination-v1"
test "$(jq -r '.frontendRelease' "$backend/.release-coordination.json")" = "20260814T084319Z-media-login-canonical"
test "$(jq -r '.backendRelease' "$backend/.release-coordination.json")" = "openclaw-tag-router-media-tenant-20260814T062408Z-opc-feishu-login"

if find "$frontend" "$backend" -type l -print -quit | grep -q .; then
  echo "candidate contains a symbolic link" >&2
  exit 1
fi
if find "$frontend" "$backend" -type f \( -name '*.tmp' -o -name '*.log' -o -name '.DS_Store' \) \
  ! -path '*/node_modules/*' ! -path '*/dist*/*' ! -path '*/__pycache__/*' \
  ! -path '*/.pytest_cache/*' ! -path '*/.mypy_cache/*' ! -path '*/.ruff_cache/*' \
  -print -quit | grep -q .; then
  echo "candidate contains an unmanaged temporary or log file" >&2
  exit 1
fi

scratch="$(mktemp -d /tmp/c5-unique-candidate.XXXXXX)"
(
  cd "$frontend"
  find . \
    \( -path './node_modules' -o -path './dist*' -o -path './.vite' -o -path '*/__pycache__' \) -prune -o \
    -type f ! -name '*.pyc' ! -name '*.log' ! -name '.DS_Store' \
    ! -name '.candidate-source.sha256' ! -name '.merge-provenance.json' -print \
    | LC_ALL=C sort \
    | while IFS= read -r path; do shasum -a 256 "$path"; done
) > "$scratch/frontend.sha256"
(
  cd "$backend"
  find . \
    \( -path '*/__pycache__' -o -path './.pytest_cache' -o -path './.mypy_cache' -o \
       -path './.ruff_cache' -o -path './.cache' -o -path './.playwright-browsers' \) -prune -o \
    -type f ! -name '*.pyc' ! -name '*.log' ! -name '.DS_Store' \
    ! -name '.candidate-source.sha256' ! -name '.merge-provenance.json' -print \
    | LC_ALL=C sort \
    | while IFS= read -r path; do shasum -a 256 "$path"; done
) > "$scratch/backend.sha256"

test "$(wc -l < "$scratch/frontend.sha256" | tr -d ' ')" = "200"
test "$(wc -l < "$scratch/backend.sha256" | tr -d ' ')" = "566"
cmp "$scratch/frontend.sha256" "$frontend/.candidate-source.sha256"
cmp "$scratch/backend.sha256" "$backend/.candidate-source.sha256"
(cd "$frontend" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)
(cd "$backend" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)

frontend_manifest_sha="$(sha "$frontend/.candidate-source.sha256")"
backend_manifest_sha="$(sha "$backend/.candidate-source.sha256")"
test "$(jq -r '.candidate.source_manifest_sha256' "$frontend/.merge-provenance.json")" = "$frontend_manifest_sha"
test "$(jq -r '.candidate.file_count_before_validation' "$frontend/.merge-provenance.json")" = "200"
test "$(jq -r '.candidate.source_manifest_sha256' "$backend/.merge-provenance.json")" = "$backend_manifest_sha"
test "$(jq -r '.candidate.file_count_before_validation' "$backend/.merge-provenance.json")" = "566"
for provenance in "$frontend/.merge-provenance.json" "$backend/.merge-provenance.json"; do
  jq -e '
    .material_parsing.contract_id == "media-material-parsing-coverage-v1"
    and .material_parsing.contract_sha256 == "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56"
    and .material_parsing.coverage_count == 54
    and .material_parsing.wave_17_result_sha256 == "27cfc24b13d7618127996a72f57c38608f4a0df2a32f213104823b6c97021dbf"
    and .material_parsing.production_accepted == false
  ' "$provenance" >/dev/null
done

test -f "$manifest"
test -f "$manifest_checksum"
test "$(wc -l < "$manifest_checksum" | tr -d ' ')" = "1"
test "$(awk '{print $2}' "$manifest_checksum")" = "candidate-manifest.json"
(cd "$candidate" && shasum -a 256 -c candidate-manifest.sha256 >/dev/null)
candidate_manifest_sha="$(sha "$manifest")"
test "$(awk '{print $1}' "$manifest_checksum")" = "$candidate_manifest_sha"
jq -e \
  --arg frontend_manifest_sha "$frontend_manifest_sha" \
  --arg backend_manifest_sha "$backend_manifest_sha" '
  .schemaVersion == "openclaw-media-unique-candidate-v1"
  and .candidateId == "media-production-e2e-v4"
  and .versions == {plan:5, dag:5, interfaceFreeze:5, nodeContract:4, ssotSchema:1}
  and .productionState == "not_deployed"
  and .baselines.frontendRelease == "20260814T084319Z-media-login-canonical"
  and .baselines.backendRelease == "20260814T062408Z-opc-feishu-login"
  and .releaseCoordination.frontendRelease == "20260814T084319Z-media-login-canonical"
  and .releaseCoordination.backendRelease == "openclaw-tag-router-media-tenant-20260814T062408Z-opc-feishu-login"
  and .components.frontend.root == "frontend"
  and .components.frontend.sourceManifest == "frontend/.candidate-source.sha256"
  and .components.frontend.sourceManifestSha256 == $frontend_manifest_sha
  and .components.frontend.managedFileCount == 200
  and .components.backend.root == "backend"
  and .components.backend.sourceManifest == "backend/.candidate-source.sha256"
  and .components.backend.sourceManifestSha256 == $backend_manifest_sha
  and .components.backend.managedFileCount == 566
  and .materialParsing.contractId == "media-material-parsing-coverage-v1"
  and .materialParsing.contractSha256 == "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56"
  and .materialParsing.coverageCount == 54
  and .materialParsing.completionStatuses == ["completed_auto", "completed_manual"]
  and .materialParsing.incompleteHttpStatus == 422
  and .materialParsing.incompleteErrorCode == "material_parsing_incomplete"
  and .validation.wave17ResultSha256 == "27cfc24b13d7618127996a72f57c38608f4a0df2a32f213104823b6c97021dbf"
  and .validation.wave17ValidationSha256 == "fc2bec23ab69da35d18e269bb4cd1a0236eb3929c33c943ee4bff4e6da02de8b"
  and .boundaries.remoteProductionTouched == false
  and .boundaries.productionDatabaseTouched == false
  and .boundaries.feishuTouched == false
  and .boundaries.realQaAccepted == false
' "$manifest" >/dev/null

test -f "$result"
rg -F -- "$candidate_manifest_sha" "$result" >/dev/null
rg -F -- "$frontend_manifest_sha" "$result" >/dev/null
rg -F -- "$backend_manifest_sha" "$result" >/dev/null
rg -F -- "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56" "$result" >/dev/null
rg -F -- "未部署" "$result" >/dev/null

bash "$bundle/execution-wave-17/validation/material-parsing-main-thread-review.sh"

cmp "$scratch/frontend.sha256" "$frontend/.candidate-source.sha256"
cmp "$scratch/backend.sha256" "$backend/.candidate-source.sha256"
(cd "$candidate" && shasum -a 256 -c candidate-manifest.sha256 >/dev/null)
echo "C5 unique candidate validation passed: $candidate_manifest_sha"
