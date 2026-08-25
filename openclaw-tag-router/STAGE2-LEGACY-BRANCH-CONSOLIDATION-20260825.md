# Legacy Stage-2 branch consolidation — 2026-08-25

This record documents the history-only consolidation of the remaining parallel
Stage-2 development branches after the final handoff implementation was safely
merged into `main`.

## Branch histories consolidated

- `codex/stage2-integration-20260818`
- `codex/stage2-writer-context-20260818`
- `codex/stage2-org-readback-luna-20260818`
- `codex/stage2-s4-luna-20260818`
- `codex/stage2-personal-luna-20260818`
- `codex/stage2-organization-luna-20260818`

## Audit result

The branches contain earlier parallel implementations of the Stage-2 writer
contract, execution context, writer router, artifact/readback state, external
document boundary, and personal/organization pipelines, together with their
focused tests. After the resolved final-handoff merge, every affected module
exists on `main` in an equal or newer form. None of these branches introduces a
separate product area or a production capability absent from the current tree.

## Resolution

The branch tips are preserved as parents of a consolidation merge commit, while
the resulting worktree deliberately retains the current `main` versions. This
is an explicit superseded-code resolution, not an accidental conflict choice:

- commit history and authorship remain reachable;
- old implementations do not overwrite current runtime, authority, persistence,
  or tests;
- the branches can be removed after ancestry verification;
- no Stage-2 SSOT or production-acceptance status is changed by this merge.

The code-bearing Stage-2 merge and its production-entrypoint resolution are
recorded separately in `STAGE2-MERGE-RESOLUTION-20260825.md`.
