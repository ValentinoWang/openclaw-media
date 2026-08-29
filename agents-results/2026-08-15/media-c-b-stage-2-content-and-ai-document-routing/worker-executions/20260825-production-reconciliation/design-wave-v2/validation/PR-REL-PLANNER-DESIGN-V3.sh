#!/usr/bin/env bash
set -euo pipefail

root='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/pr-rel-planner-design'
baseline='59e2adfd34853b6929d9fa69e69585806ac9c83a'
v2_head='912bf53cd71147662d88b8846e5548a6e37ad8f9'
task_root="$root/docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER"
contract="$task_root/acceptance-contract.md"
test_file="$root/openclaw-tag-router/tests/test_production_reconciliation_planner.py"
skill='/Users/vsiyo/.codex/skills/design-acceptance-contract'
expected_test_sha='b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898'

test -f "$contract"
test -f "$test_file"
test -f "$root/acceptance/human/PR-REL-PLANNER/checklist.md"
test -f "$root/acceptance/human/PR-REL-PLANNER/binding.md"
test ! -e "$root/acceptance/human/PR-REL-PLANNER-DESIGN-V2"
test "$(shasum -a 256 "$test_file" | awk '{print $1}')" = "$expected_test_sha"
python3 "$skill/scripts/check_acceptance_contract.py" "$contract" --project-root "$root"
python3 "$skill/scripts/manage_acceptance_artifacts.py" check "$task_root" --project-root "$root"
test "$(git -C "$root" rev-parse HEAD)" != "$v2_head"
test -z "$(git -C "$root" status --porcelain=v1 | grep -v '^?? acceptance/index.md$')"

while IFS= read -r path; do
  case "$path" in
    docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER/*|acceptance/human/PR-REL-PLANNER/*|openclaw-tag-router/tests/test_production_reconciliation_planner.py) ;;
    *) echo "out-of-scope final path: $path" >&2; exit 1 ;;
  esac
done < <(git -C "$root" diff --name-only "$baseline" HEAD)

if env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/openclaw-tag-router" uv run --python 3.12 --with pytest python -m pytest -q "$test_file"; then
  echo 'protected tests unexpectedly passed before implementation' >&2
  exit 1
fi
