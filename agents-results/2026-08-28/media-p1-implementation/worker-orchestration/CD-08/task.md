# CD-08 Review Context Bandwidth

- Task ID: `P1-CD-08`
- Direct parent: `media-p1-implementation`
- Source baseline: `b8586379be58169250ed28f19c6dea805da239a9`
- Decision source: `docs/production-reconciliation/20260827/pipeline-full-audit.md#CD-08`, `#CPO-N16`
- Acceptance authority: the user's 2026-08-28 instruction to continue the P1 implementation wave.
- Invalidation keys: `creation.review-context.bandwidth`, `creation.prompt.context-priority`
- Writable sandbox: yes

## Objective

The rendered creation context must preserve review learning before profile
markdown or optional history consumes its token budget. The default budget must
be large enough for the structured review data already persisted by this
candidate worktree, while remaining configurable and bounded. Review prompt
lines must expose the lesson, performance level, key metrics with their values,
and actionable next steps. An explicitly supplied small `max_chars` still must
truncate safely and deterministically.

## Exact write scope

- `selfmedia/context/media_context.py`
- `tests/test_media_context_review_bandwidth.py` (new)
- `agents-results/2026-08-28/media-p1-implementation/worker-orchestration/CD-08/return.json`

## Read scope

- The files above, current candidate fields in `selfmedia/review/data_review.py`,
  and `docs/production-reconciliation/20260827/pipeline-full-audit.md`.

## Forbidden scope

- All existing test files, `selfmedia/review/data_review.py`, `selfmedia/style/**`,
  `selfmedia/creation/**`, `selfmedia/deconstruct/**`, `acceptance/**`,
  `agents-results/2026-08-15/**`, release/deploy files, and other lane paths.
- Do not overwrite or reformat unrelated existing dirty changes. Do not update SSOT status.

## Required checks

Run `/bin/bash agents-results/2026-08-28/media-p1-implementation/worker-orchestration/CD-08/validate.sh`.
Run `git diff --check` before returning.

## Return schema

Write `return.json` with task_id, proposed_state, acceptance_self_check,
failure_class, failure_origin, actual_changed_paths, command_results,
unverified_items, and rationale. Do not commit, push, deploy, or write shared evidence.
