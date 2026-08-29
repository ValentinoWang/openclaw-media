#!/usr/bin/env bash
set -euo pipefail

root='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/pr-rel-manifest-impl'
design='bfa10178959e7cbde3bca9be6aa961f65d6343a5'
task_root="$root/docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-MANIFEST"
contract="$task_root/acceptance-contract.md"
test_file="$root/openclaw-tag-router/tests/test_production_release_manifest.py"
skill='/Users/vsiyo/.codex/skills/design-acceptance-contract'

test "$(shasum -a 256 "$contract" | awk '{print $1}')" = '8ffe2adebbf86aad61b0c1396b623a1321a6a97958eb1f327177481024000537'
test "$(shasum -a 256 "$test_file" | awk '{print $1}')" = 'dd653b45ebce1d09593f232673506262e7720dff571474fe5f1afc19737e0187'
test -f "$root/openclaw-tag-router/openclaw_app/services/production_release_manifest.py"
test -f "$root/openclaw-tag-router/openclaw_app/contracts/production-release-manifest.v1.schema.json"
test -f "$root/openclaw-tag-router/scripts/build_production_release_manifest.py"
python3 "$skill/scripts/check_acceptance_contract.py" "$contract" --project-root "$root"
python3 "$skill/scripts/manage_acceptance_artifacts.py" check "$task_root" --project-root "$root"
python3 -m json.tool "$root/openclaw-tag-router/openclaw_app/contracts/production-release-manifest.v1.schema.json" >/dev/null
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/openclaw-tag-router" uv run --python 3.12 --with pytest python -m pytest -q "$test_file"
python3 -m py_compile "$root/openclaw-tag-router/openclaw_app/services/production_release_manifest.py" "$root/openclaw-tag-router/scripts/build_production_release_manifest.py"
test "$(git -C "$root" rev-parse HEAD)" != "$design"
test -z "$(git -C "$root" status --porcelain=v1 | grep -v '^?? acceptance/index.md$')"
git -C "$root" diff --check "$design" HEAD
git -C "$root" log --format='%s' "$design"..HEAD | grep -Fx 'feat(release): implement production manifest tooling' >/dev/null
git -C "$root" log --format='%s' "$design"..HEAD | grep -Fx 'test(release): record manifest implementation evidence' >/dev/null

while IFS= read -r changed_path; do
  case "$changed_path" in
    openclaw-tag-router/openclaw_app/services/production_release_manifest.py|openclaw-tag-router/openclaw_app/contracts/production-release-manifest.v1.schema.json|openclaw-tag-router/scripts/build_production_release_manifest.py|docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-MANIFEST/acceptance/index.md) ;;
    docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-MANIFEST/acceptance/machine/unit/runs/*)
      if git -C "$root" cat-file -e "$design:$changed_path" 2>/dev/null; then
        echo "existing evidence changed: $changed_path" >&2
        exit 1
      fi
      ;;
    *) echo "out-of-scope implementation path: $changed_path" >&2; exit 1 ;;
  esac
done < <(git -C "$root" diff --name-only "$design" HEAD)
