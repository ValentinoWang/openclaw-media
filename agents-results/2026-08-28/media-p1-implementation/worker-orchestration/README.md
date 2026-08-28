# P1 Worker Orchestration Evidence

This is a non-SSOT execution-evidence directory for the 2026-08-28 P1
implementation wave. It does not change the Stage-2 SSOT or its formal status.

- Source baseline: `b8586379be58169250ed28f19c6dea805da239a9`
- Source branch: `codex/p1-pipeline-20260828`
- Shared dirty-worktree snapshot SHA-256:
  `592379051e729d34010b96a3f4eab41e79e6fdf10c922ab65143cfde4f386cba`
- Decision source: `docs/production-reconciliation/20260827/pipeline-full-audit.md`
- User authority: 2026-08-28 Codex request to continue P1 development.
- Executor selection: `lw-terra`; the user explicitly prohibited Luna for this
  wave, so the supervisor's exceptional L3 slot is also bound to the inspected
  Terra wrapper rather than invoking `run-l3.sh`.

The two lanes own disjoint production and test paths. Neither lane may modify
the Stage-2 SSOT, release/human-acceptance artifacts, shared existing tests, or
another lane's files.
