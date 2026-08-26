# Planner contract repair — 2026-08-26

## Why this repair exists

PR #7 merged a Planner facade around a copied `production_reconciliation_planner_legacy.py` and added a planner-local `paths == sorted(paths)` guard. That shape conflicted with the already locked planner fixture and duplicated responsibility already owned by `production_release_manifest`.

This corrective source-only pass removes that duplication before any new immutable release candidate is built.

## Canonical decision

- `production_reconciliation_planner.py` is the sole Planner implementation.
- `production_reconciliation_planner_legacy.py` is deleted.
- The protected Planner test remains byte-for-byte frozen at SHA-256 `b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898`.
- The original PR-REL-PLANNER v1 contract is retained with amendment 1.1 for the inventory-ordering responsibility.
- Planner-local validation requires safe, unique manifest entries but does not duplicate filesystem-backed lexicographic order validation.
- Real immutable release manifests still require sorted inventory because `production_release_manifest.build_manifest` sorts and `production_release_manifest.validate_manifest` rejects unsorted inventories.
- `test_production_reconciliation_contract_boundary.py` locks this cross-module boundary.
- `scripts/repository/check_remote_branch_divergence.py` is the read-only remote-branch convergence gate.

## Current Stage-2 source names

The implemented current-main Stage-2 source files are:

- `openclaw-tag-router/openclaw_app/adapters/stage2_http_api.py`
- `openclaw-tag-router/openclaw_app/services/stage2_main_composition.py`
- `openclaw-tag-router/openclaw_app/stage2_server_cli.py`

There is no implemented `stage2_http_bridge.py` file.

## Merge and deployment boundary

Before this repair can merge, the protected suites, full Router suite, compile/diff hygiene and remote-branch convergence gate must execute successfully. Before production deployment, the resulting merged `main` SHA must additionally pass immutable release-manifest validation, dependency/Binding/Feishu preflight, isolated authenticated personal/organization acceptance, Feishu readback and rollback checks.

This document is not a deployment record. It does not modify the active 2026-08-19 release, systemd, production pointers or the formal Stage-2 SSOT.
