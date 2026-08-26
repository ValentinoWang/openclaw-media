# Planner contract repair — 2026-08-26

## Why this repair exists

The first current-main reconciliation commit introduced a facade around a copied `production_reconciliation_planner_legacy.py` and added a planner-local `paths == sorted(paths)` guard. That shape conflicted with the already locked planner test fixture and duplicated responsibility already owned by `production_release_manifest`.

This repair makes the boundary explicit and removes the duplicate implementation.

## Canonical decision

- `production_reconciliation_planner.py` is again the sole planner implementation.
- `production_reconciliation_planner_legacy.py` is deleted.
- The existing protected planner test remains byte-for-byte frozen at SHA-256 `b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898`.
- Planner-local validation requires safe, unique manifest entries but does not independently require lexicographic file-list order.
- Actual immutable release manifests still require sorted inventory because `production_release_manifest.build_manifest` sorts and `production_release_manifest.validate_manifest` rejects unsorted inventories.
- PR-REL-PLANNER v2 is now the active human binding for this distinction.

## Current Stage-2 source names

The canonical source files are:

- `openclaw-tag-router/openclaw_app/adapters/stage2_http_api.py`
- `openclaw-tag-router/openclaw_app/services/stage2_main_composition.py`
- `openclaw-tag-router/openclaw_app/stage2_server_cli.py`

No document should refer to a nonexistent `stage2_http_bridge.py` as the implemented file.

## Merge/deploy boundary

This repair is source-only. Before production deployment, the resulting `main` SHA must still pass the immutable manifest validator, full Router suite, Stage-2 focused tests, remote-branch convergence gate, dependency/Binding/Feishu preflight, isolated authenticated acceptance and rollback checks. The active 2026-08-19 release is not modified by this repair.
