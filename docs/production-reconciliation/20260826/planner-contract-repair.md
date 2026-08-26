# Main reconciliation corrective pass — 2026-08-26

## Why this correction exists

PR #7 merged `codex/main-reconciliation-20260826` before its Planner change was compatible with the locked Planner unit baseline. The merge also introduced a copied `production_reconciliation_planner_legacy.py` implementation behind a thin facade. This document records the corrective source-only pass; it is not a deployment record.

## Corrected Planner architecture

- Restore `openclaw_app/services/production_reconciliation_planner.py` as the single Planner implementation.
- Delete `production_reconciliation_planner_legacy.py`.
- Keep `tests/test_production_reconciliation_planner.py` byte-for-byte frozen from the pre-PR-#7 baseline.
- Assign lexicographic release inventory ordering to `production_release_manifest.validate_manifest`, which already validates target-root bytes, digests, modes, duplicate paths and ordering.
- Add a cross-module regression proving an unsorted real manifest is rejected before planning.
- Bind the clarification through PR-REL-PLANNER contract amendment 1.1.

## Repository gate

The repository now carries a read-only remote-branch divergence checker and a GitHub Actions gate. The gate runs the protected Planner/release tests, the complete `openclaw-tag-router/tests` suite, compilation, branch convergence and diff hygiene. It never commits, deletes branches, deploys, restarts services or changes production pointers.

## Stage-2 boundary

The Stage-2 source introduced by PR #7 remains subject to its tests. This corrective pass does not promote the Writer Contract, does not claim real personal/organization/Feishu acceptance and does not change the formal Stage-2 SSOT numerator.

## Deployment boundary

The active 106 release remains an external runtime fact. No `git pull`, release overwrite, systemd change, restart or cutover is authorized by this correction. A new immutable candidate may be built only from a post-merge `main` SHA after the reconciliation gate is green.
