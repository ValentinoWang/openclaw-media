#!/usr/bin/env bash
set -euo pipefail

root='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/production-reconciliation-20260825'
skill='/Users/vsiyo/.codex/skills/design-acceptance-contract'
head='a61b812a822fe3e00bc6ba194b39fbdfc6bb9355'

test "$(git -C "$root" rev-parse HEAD)" = "$head"
test -z "$(git -C "$root" status --porcelain=v1)"

for task in PR-REL-MANIFEST PR-REL-READBACK PR-REL-PLANNER; do
  python3 "$skill/scripts/check_acceptance_contract.py" \
    "$root/docs/production-reconciliation/20260825/acceptance-fragments/$task/acceptance-contract.md" \
    --project-root "$root"
  python3 "$skill/scripts/manage_acceptance_artifacts.py" check \
    "$root/docs/production-reconciliation/20260825/acceptance-fragments/$task" \
    --project-root "$root"
done

env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/openclaw-tag-router" \
  uv run --python 3.12 --with pytest python -m pytest -q -p no:cacheprovider \
  "$root/openclaw-tag-router/tests/test_production_release_manifest.py" \
  "$root/openclaw-tag-router/tests/test_stage2_release_readback.py" \
  "$root/openclaw-tag-router/tests/test_production_reconciliation_planner.py" \
  "$root/openclaw-tag-router/tests/test_stage2_release_gate.py"

test "$(sha256sum "$root/openclaw-tag-router/tests/test_production_release_manifest.py" | awk '{print $1}')" = dd653b45ebce1d09593f232673506262e7720dff571474fe5f1afc19737e0187
test "$(sha256sum "$root/openclaw-tag-router/tests/test_stage2_release_readback.py" | awk '{print $1}')" = a70096254718873de191d3cef266d8fa3ae820b26ffcf516649a3fc42d255ace
test "$(sha256sum "$root/openclaw-tag-router/tests/test_production_reconciliation_planner.py" | awk '{print $1}')" = b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898

git -C "$root" diff --check 5f06780569568ccc3197f0ab16aad74bdf9d1c6f.."$head"
test -z "$(git -C "$root" status --porcelain=v1)"
