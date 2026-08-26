# Acceptance Contract: PR-REL-PLANNER v2

- Task ID: PR-REL-PLANNER
- Contract version: 2
- Contract status: APPROVED
- Test baseline: LOCKED
- Supersedes: `acceptance-contract.md` version 1 only for planner-local manifest inventory ordering
- Protected test: `openclaw-tag-router/tests/test_production_reconciliation_planner.py`
- Protected test SHA-256: `b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898`
- Acceptance owner: User-authorized source-only Production Reconciliation owner
- SSOT node: none
- Readiness mode: FORMAL

## Decision

Version 1 mixed two different responsibilities:

1. `production-release-manifest.v1` owns canonical release-manifest construction and full target-tree validation. Its builder emits file entries in sorted order and its validator rejects unsorted inventories.
2. `production_reconciliation_planner` is a pure, source-only planner that consumes an already-observed manifest identity object. It validates identity, schema, safety, uniqueness, digest relationships, pointer CAS, rollback compatibility and redaction, but it does not duplicate the release-manifest validator's canonical-order check.

The locked planner test intentionally uses a non-lexicographic but unique manifest inventory. That fixture is legal for the planner's in-memory identity-boundary tests. It is not evidence that the same manifest would pass `production_release_manifest.validate_manifest` or be deployable.

Therefore planner-local inventory ordering is **not** an acceptance condition. Duplicate paths remain invalid. A real release candidate must still pass the separate `production-release-manifest.v1` builder/validator gate before the planner is used in a deployment workflow.

## Public surface

```python
plan_production_reconciliation(request: Mapping[str, object]) -> dict[str, object]
canonical_plan_json(plan: Mapping[str, object]) -> str
PlannerValidationError.code: str
```

The planner is implemented in exactly one source file:

`openclaw-tag-router/openclaw_app/services/production_reconciliation_planner.py`

There is no legacy copy, compatibility facade, runtime monkey-patching layer or alternate planner implementation.

## Required behavior

The planner accepts only a complete request containing:

- `operation`: `activate` or `rollback`;
- a lowercase 40-character source Git SHA;
- a safe release base and current pointer;
- a target release ID/root deterministically bound to that SHA;
- a manifest identity object with a valid digest, clean matching source identity, safe unique regular-file entries, allowed modes and previous-release identity;
- an expected and observed current-pointer identity that must match;
- a complete rollback-compatible previous release;
- collision-free known release identities;
- explicit optional user-systemd intent;
- a bounded observation window and signal list.

The planner returns a deterministic `production-reconciliation-plan.v1` mapping. It performs no filesystem, process, network, database, HTTP, Feishu, systemd, pointer, deployment or rollback action.

## Manifest ordering boundary

For planner-local validation:

- file paths must be safe;
- paths must be unique;
- each entry must contain exactly `path`, `sha256` and `mode`;
- digests and modes must be valid;
- **input list order is not semantically validated by the planner**.

For actual immutable-release construction and release verification:

- `production_release_manifest.build_manifest` emits sorted inventory;
- `production_release_manifest.validate_manifest` rejects unsorted inventory;
- deployment/release gates must use that validator and cannot substitute planner acceptance for manifest acceptance.

This separation prevents a planner fixture from redefining the release-manifest contract while also avoiding duplicated manifest-validator logic inside the planner.

## Canonicality and determinism

`canonical_plan_json` recursively sorts mapping keys and emits compact ASCII-safe JSON without a trailing newline. Reordering mapping keys must not change canonical bytes.

List order remains data. The planner does not silently reorder caller lists. Identical requests return identical plans and identical `plan_id` values; changing list order may change `plan_id` because it is a different observed request.

## Failure requirements

The planner fails closed with stable redacted error codes for:

- invalid or abbreviated source SHA;
- unsafe release/pointer paths;
- target identity not bound to the source SHA;
- malformed, dirty, digest-invalid, duplicate-path, unsafe-path or identity-inconsistent manifest data;
- stale pointer CAS;
- invalid previous release;
- rollback incompatibility;
- release identity collision;
- invalid systemd or observation input;
- secret-bearing unknown input;
- unknown fields and wrong types.

An error must not mutate caller input, emit a partial plan or perform an external action.

## Protected-test interpretation

The existing protected test file remains frozen at SHA-256:

`b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898`

Its non-lexicographic fixture is explicitly bound to this v2 planner-local contract. The test does not stand in for `production_release_manifest.validate_manifest`.

Any future change to source identity, path safety, manifest identity/digest validation, pointer CAS, rollback compatibility, redaction, external-action boundaries, output schema, or the protected-test file requires a new acceptance decision.

## Release gate

A production candidate is eligible for planning only after all of the following independently pass:

1. clean full Git SHA identity;
2. immutable release manifest build;
3. `production_release_manifest.validate_manifest`;
4. protected planner tests;
5. complete Router test suite;
6. Stage-2 focused/hardening tests;
7. branch-convergence gate proving no retained remote development branch contains unique commits outside `main`;
8. deployment dependency preflight and rollback target validation.

Planner acceptance alone never means deployable, released, production-ready or SSOT-accepted.

## Non-goals

This contract does not authorize or prove:

- production deployment or service restart;
- systemd pointer changes;
- HTTPS/TLS completion;
- authenticated personal/organization positive-path acceptance;
- Feishu write/readback correctness;
- production rollback;
- Stage-1 C1/C3/DC2 acceptance;
- Stage-2 SSOT promotion.

## Acceptance criteria

| ID | Requirement | Blocking |
| --- | --- | --- |
| V2-01 | Exactly one planner implementation file exists; no `_legacy` planner module exists. | Yes |
| V2-02 | The locked protected planner test SHA remains unchanged. | Yes |
| V2-03 | The protected planner suite passes. | Yes |
| V2-04 | Planner accepts its existing unique non-lexicographic identity fixture. | Yes |
| V2-05 | Duplicate/unsafe manifest paths still fail closed. | Yes |
| V2-06 | Release-manifest builder/validator retain their stricter sorted-inventory contract. | Yes |
| V2-07 | Full Router and Stage-2 focused suites pass on the proposed main candidate. | Yes |
| V2-08 | Branch-convergence gate reports no unique commits outside the proposed main candidate. | Yes |
| V2-09 | No production deployment or SSOT promotion is inferred from these source-only checks. | Yes |
