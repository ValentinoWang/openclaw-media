# CPC-07 Creation Anti-Pattern Validation

- Task ID: `P1-CPC-07`
- Direct parent: `media-p1-implementation`
- Source baseline: `b8586379be58169250ed28f19c6dea805da239a9`
- Decision source: `docs/production-reconciliation/20260827/pipeline-full-audit.md#CPC-07`
- Acceptance authority: the user's 2026-08-28 instruction to continue the P1 implementation wave.
- Readiness: user-authorized implementation scope; this is not formal Stage-2 release acceptance.
- Invalidation keys: `creation.llm-draft.anti-pattern-validation`, `style.anti-patterns.shared-source`
- Writable sandbox: yes

## Objective

Use the existing `selfmedia/style/assets/anti_patterns.yaml` as the single
source for the creation chain too. `validate_llm_draft_payload` must reject a
recommended user-visible draft whose title, final copy, hook, or voiceover
contains a configured anti-pattern. Preserve `must_keep` semantics and avoid
inventing a second phrase list. The error must identify the user-visible field
and matched phrase so the existing LLM retry path can repair it.

## Exact write scope

- `selfmedia/creation/llm_generator.py`
- `selfmedia/style/context_loader.py` only if a small reusable loader is needed
  to avoid duplicating YAML parsing
- `tests/test_creation_anti_pattern_validation.py` (new)
- `agents-results/2026-08-28/media-p1-implementation/worker-orchestration/CPC-07/return.json`

## Read scope

- The files above, `selfmedia/style/assets/anti_patterns.yaml`, the current
  validation helpers, and relevant existing test fixtures.
- `docs/production-reconciliation/20260827/pipeline-full-audit.md` lines 1072-1083.

## Forbidden scope

- All existing test files, `tests/test_creation_v1.py`, `selfmedia/deconstruct/**`,
  `.git/**`, `acceptance/**`, `agents-results/2026-08-15/**`, release/deploy files,
  and every path owned by P1-CD-07.
- Do not alter anti-pattern content in YAML for this task. Do not update SSOT status.

## Required checks

Run `/bin/bash agents-results/2026-08-28/media-p1-implementation/worker-orchestration/CPC-07/validate.sh`.
Run `git diff --check` before returning.

## Return schema

Write `return.json` with task_id, proposed_state (`IMPLEMENTED`, `FAILED`, or
`BLOCKED`), failure_class, failure_origin, actual_changed_paths, command_results,
unverified_items, and a concise rationale. Do not commit, push, deploy, or edit
the shared orchestration evidence.
