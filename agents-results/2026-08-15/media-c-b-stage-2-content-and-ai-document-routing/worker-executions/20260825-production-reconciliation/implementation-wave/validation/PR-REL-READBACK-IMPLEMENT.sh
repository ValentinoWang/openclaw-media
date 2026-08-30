#!/usr/bin/env bash
set -euo pipefail

root='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/pr-rel-readback-impl'
design='5b3b628c739c84b8b02f7256c15e2b23ca033bf8'
task_root="$root/docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-READBACK"
contract="$task_root/acceptance-contract.md"
test_file="$root/openclaw-tag-router/tests/test_stage2_release_readback.py"
guard="$root/openclaw-tag-router/scripts/qa/check_stage2_release_process.py"
skill='/Users/vsiyo/.codex/skills/design-acceptance-contract'

test "$(shasum -a 256 "$contract" | awk '{print $1}')" = 'ae12561d38b281fc44a299d4589c0b72a6681109002327c60f7be1cb67ced57c'
test "$(shasum -a 256 "$test_file" | awk '{print $1}')" = 'a70096254718873de191d3cef266d8fa3ae820b26ffcf516649a3fc42d255ace'
test -f "$guard"
python3 "$skill/scripts/check_acceptance_contract.py" "$contract" --project-root "$root"
python3 "$skill/scripts/manage_acceptance_artifacts.py" check "$task_root" --project-root "$root"
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/openclaw-tag-router" uv run --python 3.12 --with pytest python -m pytest -q "$test_file"
python3 -m py_compile "$guard"
test "$(git -C "$root" rev-parse HEAD)" != "$design"
test -z "$(git -C "$root" status --porcelain=v1 | grep -v '^?? acceptance/index.md$')"
git -C "$root" diff --check "$design" HEAD
git -C "$root" log --format='%s' "$design"..HEAD | grep -Fx 'feat(release): add Stage-2 release readback guard' >/dev/null
git -C "$root" log --format='%s' "$design"..HEAD | grep -Fx 'test(release): record readback implementation evidence' >/dev/null

while IFS= read -r changed_path; do
  case "$changed_path" in
    openclaw-tag-router/scripts/qa/check_stage2_release_process.py|docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-READBACK/acceptance/index.md) ;;
    docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-READBACK/acceptance/machine/unit/runs/*)
      if git -C "$root" cat-file -e "$design:$changed_path" 2>/dev/null; then
        echo "existing evidence changed: $changed_path" >&2
        exit 1
      fi
      ;;
    *) echo "out-of-scope implementation path: $changed_path" >&2; exit 1 ;;
  esac
done < <(git -C "$root" diff --name-only "$design" HEAD)
