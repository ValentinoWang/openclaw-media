# BIZ-13 Structured Review Rendering

- Task ID: `P1-BIZ-13`
- Direct parent: `media-p1-implementation`
- Source baseline: `b8586379be58169250ed28f19c6dea805da239a9`
- Decision source: `docs/production-reconciliation/20260827/pipeline-full-audit.md#BIZ-13`
- Acceptance authority: the user's 2026-08-28 instruction to continue the P1 implementation wave.
- Invalidation keys: `data-review.structured-guidance.rendering`, `data-review.memory.serialization`
- Writable sandbox: yes

## Objective

When the data-review LLM returns structured guidance objects, user-visible
document blocks and persisted review-memory text must render readable Chinese
labels and values rather than Python dictionary representations. Preserve valid
plain-string inputs and do not change data-model schemas or retired Bitable
paths.

## Exact write scope

- `selfmedia/review/data_review.py`
- `tests/test_data_review_structured_rendering.py` (new)
- `agents-results/2026-08-28/media-p1-implementation/worker-orchestration/BIZ-13/return.json`

## Read scope

- The files above, current normalization/render helpers, and audit evidence.

## Forbidden scope

- All existing tests, `tests/test_data_review_metrics.py`, `selfmedia/context/**`,
  `selfmedia/creation/**`, `selfmedia/deconstruct/**`, `acceptance/**`,
  `agents-results/2026-08-15/**`, release/deploy files, and other lane paths.
- Do not change the LLM prompt merely to paper over rendering. Do not update SSOT status.

## Required checks

Run `/bin/bash agents-results/2026-08-28/media-p1-implementation/worker-orchestration/BIZ-13/validate.sh`.
Run `git diff --check` before returning.

## Return schema

Write `return.json` with task_id, proposed_state, acceptance_self_check,
failure_class, failure_origin, actual_changed_paths, command_results,
unverified_items, and rationale. Do not commit, push, deploy, or write shared evidence.
