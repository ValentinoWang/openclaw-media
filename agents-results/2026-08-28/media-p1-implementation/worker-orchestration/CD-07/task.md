# CD-07 Keyframe Failure Semantics

- Task ID: `P1-CD-07`
- Direct parent: `media-p1-implementation`
- Source baseline: `b8586379be58169250ed28f19c6dea805da239a9`
- Decision source: `docs/production-reconciliation/20260827/pipeline-full-audit.md#CD-07`
- Acceptance authority: the user's 2026-08-28 instruction to continue the P1 implementation wave.
- Readiness: user-authorized implementation scope; this is not formal Stage-2 release acceptance.
- Invalidation keys: `deconstruction.keyframe-observation.failure-semantics`, `evidence-store.modality-status`
- Writable sandbox: yes

## Objective

Make a keyframe-observation LLM failure observably different from a genuine
absence of frame assets. A real no-frame case remains `not_applicable`. With
frame assets, an exception, malformed LLM payload, or an empty normalized result
must produce `status="failed"` and a stable, non-sensitive `missing_reason`.

## Exact write scope

- `selfmedia/deconstruct/viral_content/src/evidence/modality_dag.py`
- `selfmedia/deconstruct/viral_content/tests/test_keyframe_observation_failure.py` (new)
- `agents-results/2026-08-28/media-p1-implementation/worker-orchestration/CD-07/return.json`

## Read scope

- The files above, `.../src/evidence/schemas.py`, and existing relevant tests.
- `docs/production-reconciliation/20260827/pipeline-full-audit.md` lines 197-213.

## Forbidden scope

- All existing test files, `tests/test_creation_v1.py`, `selfmedia/creation/**`,
  `selfmedia/style/**`, `.git/**`, `acceptance/**`, `agents-results/2026-08-15/**`,
  release/deploy files, and every path owned by P1-CPC-07.
- Do not touch or weaken protected/current tests. Do not update SSOT status.

## Required checks

Run `/bin/bash agents-results/2026-08-28/media-p1-implementation/worker-orchestration/CD-07/validate.sh`.
Run `git diff --check` before returning.

## Return schema

Write `return.json` with task_id, proposed_state (`IMPLEMENTED`, `FAILED`, or
`BLOCKED`), failure_class, failure_origin, actual_changed_paths, command_results,
unverified_items, and a concise rationale. Do not commit, push, deploy, or edit
the shared orchestration evidence.
