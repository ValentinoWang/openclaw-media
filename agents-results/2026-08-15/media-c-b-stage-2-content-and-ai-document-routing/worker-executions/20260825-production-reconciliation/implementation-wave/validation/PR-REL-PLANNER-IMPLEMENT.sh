#!/usr/bin/env bash
set -euo pipefail

root='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/pr-rel-planner-impl'
design='23b0487c8d8a9ddc0785ea68a242d2ad279d61f1'
task_root="$root/docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER"
contract="$task_root/acceptance-contract.md"
test_file="$root/openclaw-tag-router/tests/test_production_reconciliation_planner.py"
service="$root/openclaw-tag-router/openclaw_app/services/production_reconciliation_planner.py"
script="$root/openclaw-tag-router/scripts/plan_production_reconciliation.py"
skill='/Users/vsiyo/.codex/skills/design-acceptance-contract'

test "$(shasum -a 256 "$contract" | awk '{print $1}')" = 'b3db48de31efcb66970e2d77273e74294d1bfae7f20d8c0ef950dfe42f5526e4'
test "$(shasum -a 256 "$test_file" | awk '{print $1}')" = 'b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898'
test -f "$service"
test -f "$script"
python3 "$skill/scripts/check_acceptance_contract.py" "$contract" --project-root "$root"
python3 "$skill/scripts/manage_acceptance_artifacts.py" check "$task_root" --project-root "$root"
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/openclaw-tag-router" uv run --python 3.12 --with pytest python -m pytest -q "$test_file"
python3 -m py_compile "$service" "$script"
test "$(git -C "$root" rev-parse HEAD)" != "$design"
test -z "$(git -C "$root" status --porcelain=v1 | grep -v '^?? acceptance/index.md$')"
git -C "$root" diff --check "$design" HEAD
git -C "$root" log --format='%s' "$design"..HEAD | grep -Fx 'feat(release): implement reconciliation planner' >/dev/null
git -C "$root" log --format='%s' "$design"..HEAD | grep -Fx 'test(release): record planner implementation evidence' >/dev/null

while IFS= read -r changed_path; do
  case "$changed_path" in
    openclaw-tag-router/openclaw_app/services/production_reconciliation_planner.py|openclaw-tag-router/scripts/plan_production_reconciliation.py|docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER/acceptance/index.md) ;;
    docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER/acceptance/machine/unit/runs/*)
      if git -C "$root" cat-file -e "$design:$changed_path" 2>/dev/null; then
        echo "existing evidence changed: $changed_path" >&2
        exit 1
      fi
      ;;
    *) echo "out-of-scope implementation path: $changed_path" >&2; exit 1 ;;
  esac
done < <(git -C "$root" diff --name-only "$design" HEAD)
