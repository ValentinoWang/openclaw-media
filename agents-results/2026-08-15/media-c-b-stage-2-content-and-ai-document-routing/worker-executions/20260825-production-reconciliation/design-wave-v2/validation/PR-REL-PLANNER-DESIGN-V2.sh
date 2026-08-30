#!/usr/bin/env bash
set -euo pipefail
root='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/pr-rel-planner-design'
task_root="$root/docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER"
contract="$task_root/acceptance-contract.md"
test_file="$root/openclaw-tag-router/tests/test_production_reconciliation_planner.py"
skill='/Users/vsiyo/.codex/skills/design-acceptance-contract'
test -f "$contract"
test -f "$test_file"
python3 "$skill/scripts/check_acceptance_contract.py" "$contract" --project-root "$root"
python3 "$skill/scripts/manage_acceptance_artifacts.py" check "$task_root" --project-root "$root"
test "$(git -C "$root" rev-parse HEAD)" != '59e2adfd34853b6929d9fa69e69585806ac9c83a'
test -z "$(git -C "$root" status --porcelain=v1 | grep -v '^?? acceptance/index.md$')"
if env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/openclaw-tag-router" uv run --python 3.12 --with pytest python -m pytest -q "$test_file"; then
  echo 'protected tests unexpectedly passed before implementation' >&2
  exit 1
fi
