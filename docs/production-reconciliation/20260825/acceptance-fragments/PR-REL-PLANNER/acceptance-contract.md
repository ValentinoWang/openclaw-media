# Acceptance Contract: PR-REL-PLANNER

- Task ID: PR-REL-PLANNER
- Contract version: 1
- Contract status: APPROVED
- Test baseline: LOCKED
- Acceptance owner: User-authorized source-only Production Reconciliation owner
- Approval evidence: The supplied 2026-08-25 Production Reconciliation baseline (`BASELINE=59e2adfd34853b6929d9fa69e69585806ac9c83a`) and subsequent continuation authorization (`TASK_SOURCE_SHA256=a639ea7ae4b95fe6b2689fcbb5357d3851bd83a9e70f31d36b18bcad4fbb62a`). This records source-only acceptance authority only; it is not product, deployment, release, or production acceptance.
- Request source: Bounded task PR-REL-PLANNER supplied by the user on 2026-08-25
- SSOT node: none
- SSOT path: none
- Readiness mode: FORMAL
- Decision refs: none
- Assumption IDs: none
- Invalidation keys: pr-rel-planner.contract, production-reconciliation-20260825.source-shas, production-reconciliation-20260825.deployment-gate, production-release-manifest-v1, production-reconciliation-planner-v1
- Baseline identity: branch `codex/pr-rel-planner-design`, commit `59e2adfd34853b6929d9fa69e69585806ac9c83a`, parent source authority GitHub main `5f06780569568ccc3197f0ab16aad74bdf9d1c6f`
- Human acceptance workspace: acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER
- UI Change declaration: none

## User and scenario

The source-only release engineer or future implementation owner needs a deterministic local plan before any Production Reconciliation activation or rollback is authorized. The supported surface is one in-memory request containing a full Git SHA, an immutable release identity, a prevalidated production-release manifest, an expected and observed current-pointer identity, a rollback-compatible previous release, and optional user-systemd and observation intent.

The reserved future public surface is:

```python
plan_production_reconciliation(request: Mapping[str, object]) -> dict[str, object]
canonical_plan_json(plan: Mapping[str, object]) -> str
PlannerValidationError.code: str
```

`plan_production_reconciliation` consumes request data only. It does not discover state. The request is the complete, redacted observation boundary for this fragment; the planner may validate the supplied manifest and identity relationships but must not read a checkout, release root, pointer, service manager, database, HTTP endpoint, Feishu, environment, or secret store.

## Problem

The frozen production evidence separates GitHub main, a remote candidate, the server worktree, and an active release, and explicitly states that those identities are not interchangeable. The existing deploy reference performs subprocess, rsync, install, systemd, OpenClaw, NPM, and runtime actions. A future reconciliation flow needs a fail-closed plan that can describe the complete activation and rollback sequence without silently converting planning into deployment.

Without this contract, a planner could accept an abbreviated or branch identity, derive a release root that is not bound to the full SHA, trust a stale pointer expectation, reuse a colliding release ID, omit the rollback target or compatibility proof, serialize manifest contents or secrets, emit non-canonical volatile output, or execute an implicit external step while appearing to be a dry run.

## Expected outcome

Version 1 accepts only a complete request and returns a deterministic mapping with exactly these top-level keys:

```json
{
  "schema_version": "production-reconciliation-plan.v1",
  "plan_id": "64 lowercase hexadecimal characters",
  "operation": "activate or rollback",
  "source": {"git_sha": "40 lowercase hexadecimal characters"},
  "target_release": {
    "release_id": "openclaw-stage2-<full git sha>",
    "git_sha": "40 lowercase hexadecimal characters",
    "root": "safe absolute release root",
    "manifest_sha256": "64 lowercase hexadecimal characters"
  },
  "expected_current": {
    "release_id": "...",
    "git_sha": "40 lowercase hexadecimal characters",
    "root": "safe absolute release root",
    "manifest_sha256": "64 lowercase hexadecimal characters"
  },
  "preflight": [
    {"id": "source_identity", "result": "pass"},
    {"id": "release_identity", "result": "pass"},
    {"id": "manifest", "result": "pass"},
    {"id": "pointer_cas", "result": "pass"},
    {"id": "rollback_compatibility", "result": "pass"},
    {"id": "identity_collision", "result": "pass"}
  ],
  "steps": [
    {"id": "manifest_preflight", "kind": "manifest_preflight", "effect": "none"},
    {"id": "pointer_cas", "kind": "expected_current_pointer_cas", "effect": "planned_only"},
    {"id": "atomic_switch", "kind": "planned_atomic_switch", "effect": "planned_only"},
    {"id": "user_systemd", "kind": "optional_user_systemd", "effect": "planned_only"},
    {"id": "same_round_readback", "kind": "same_round_readback", "effect": "planned_only"},
    {"id": "observation", "kind": "observation", "effect": "planned_only"},
    {"id": "rollback", "kind": "rollback", "effect": "planned_only"}
  ],
  "external_actions": [],
  "redaction": {
    "secret_values_emitted": false,
    "manifest_file_bytes_emitted": false,
    "volatile_values_emitted": false
  }
}
```

The mapping contains no manifest file bytes, environment values, credentials, tokens, URLs, shell commands, host commands, timestamps, random IDs, or raw caller extensions. `canonical_plan_json` serializes an accepted plan as compact, recursively key-sorted, ASCII-safe JSON without a trailing newline. Equivalent key order produces byte-identical output. `plan_id` is derived only from the normalized non-secret request and is stable for identical input.

The request has this v1 shape. Unknown fields fail closed; secret-looking unknown fields fail with `SECRET_DISCLOSURE` without echoing their values.

```json
{
  "operation": "activate",
  "source": {"git_sha": "<full sha>"},
  "layout": {
    "release_base": "/srv/openclaw/releases",
    "current_pointer": "/srv/openclaw/current"
  },
  "target_release": {
    "release_id": "openclaw-stage2-<full sha>",
    "git_sha": "<full sha>",
    "root": "/srv/openclaw/releases/openclaw-stage2-<full sha>",
    "manifest": "production-release-manifest.v1 object"
  },
  "pointer": {
    "expected": "release identity object",
    "observed": "release identity object"
  },
  "previous_release": {
    "release_id": "openclaw-stage2-<full sha>",
    "git_sha": "<full sha>",
    "root": "/srv/openclaw/releases/openclaw-stage2-<full sha>",
    "manifest_sha256": "<64 hex>",
    "manifest_schema": "production-release-manifest.v1",
    "rollback_compatible": true
  },
  "known_releases": [],
  "user_systemd": {
    "enabled": false,
    "units": [],
    "actions": []
  },
  "observation": {
    "window_seconds": 300,
    "signals": ["health", "readiness"]
  }
}
```

The planner derives `release_id` as `openclaw-stage2-` plus the exact full SHA and derives the target root as `layout.release_base / release_id`; caller-provided values must equal those derivations. The supplied manifest must satisfy the linked `production-release-manifest.v1` shape at the identity boundary: schema version, clean source SHA, target root `.`, a non-empty sorted unique regular-file inventory, lower-case digests, allowed modes, a matching manifest digest, and a previous-release identity matching `previous_release`. The planner does not replace the manifest validator and does not read the target root.

Paths are absolute POSIX paths only. They must contain no NUL, backslash, `..`, `.` segments, glob metacharacters, or unresolved home/drive syntax; they must be normalized and non-rooting. The release base must be a dedicated directory with at least two non-root components and may not be `/`, `/home`, `/var`, `/tmp`, `/etc`, `/usr`, `/opt`, or `/srv` itself. The current pointer must be a sibling of the release base under that dedicated parent. Release roots must be exact children of the release base and end in the derived full-SHA release ID. Manifest paths use the stricter target-relative policy from `production-release-manifest.v1` and reject traversal, absolute, mutable, runtime, secret, or broad paths.

## Non-goals

- This fragment does not implement the reserved module, CLI, manifest builder, manifest validator, readback guard, deployment runner, or release runbook.
- It does not create, copy, upload, delete, or mutate a release directory.
- It does not create or change a symlink or pointer, perform an atomic rename, invoke systemd, Nginx, SSH, subprocess, database, HTTP, Feishu, OpenClaw, Git, rsync, install, or shell command.
- It does not read filesystem contents, Git state, environment values, runtime state, secret values, database content, authenticated responses, or external service state.
- It does not restart or reload any service, enable a unit, run a health check, observe production, activate traffic, or perform rollback.
- It does not claim current-main Stage-2 route composition, external-system correctness, deployment success, release acceptance, human release approval, or Stage-1 C1/C3/DC2 acceptance.
- It does not use the root-level generated `acceptance/index.md` as acceptance authority; that projection is validation-only and remains owned by the main integrator.

## Normal path

```gherkin
Given a complete request with a lowercase 40-character Git SHA, safe layout paths, a target root and release ID derived from that SHA
And the target manifest has a clean matching source identity, safe sorted inventory, valid digest, and the previous-release identity
And pointer.expected equals pointer.observed and previous_release is present and rollback-compatible
When plan_production_reconciliation receives the request
Then it returns a production-reconciliation-plan.v1 mapping with no external actions
And it lists manifest preflight, expected-current pointer CAS, planned atomic switch, optional user-systemd intent, same-round readback, observation, and rollback in that order
And it exposes only redacted immutable identities, fixed statuses, safe paths, and deterministic step data
And canonical_plan_json returns the same bytes for repeated calls and equivalent mapping key order
```

An `operation` of `rollback` uses the same shape and plans the supplied target release as the rollback destination while still requiring the current pointer expectation, previous release identity, and compatibility proof. It never performs the rollback.

## Exception paths

- A missing, abbreviated, uppercase, non-hex, branch, tag, or otherwise non-canonical source SHA fails with `SOURCE_SHA_INVALID`.
- A root, pointer, release ID, or manifest path that is absolute-unsafe, broad, traversal-based, non-POSIX, unresolved, or not bound to the full SHA fails with `PATH_UNSAFE` or `SOURCE_ROOT_MISMATCH`.
- A missing, malformed, mismatched, dirty, incomplete, unsorted, duplicate, mutable, runtime, secret, or identity-inconsistent manifest fails with `MANIFEST_INVALID` without returning a partial plan.
- A missing, malformed, or mismatched expected/observed pointer identity fails with `POINTER_CAS_CONFLICT`; a stale observed identity never becomes a planned success.
- A missing, malformed, root-mismatched, digest-mismatched, or otherwise invalid previous release fails with `PREVIOUS_RELEASE_INVALID`.
- A false or missing `rollback_compatible`, unsupported manifest schema, or missing compatibility evidence fails with `ROLLBACK_INCOMPATIBLE`.
- A known release record that reuses a release ID or root for a different full SHA, or duplicate conflicting records, fails with `IDENTITY_COLLISION`.
- Invalid optional user-systemd units/actions or observation windows/signals fail with `SCHEMA_INVALID` or `OBSERVATION_INVALID`; no implicit defaults create external steps.
- Any secret-bearing field, including token, password, credential, private key, `.env` value, or secret-like extension, fails with `SECRET_DISCLOSURE`; neither the value nor file bytes appear in the exception or plan.
- Unknown fields, wrong types, empty required collections, or extra output fields fail with `SCHEMA_INVALID`.
- A failed operation raises `PlannerValidationError` with a stable `.code`, does not mutate the request, does not create a partial plan, and does not perform an external action.

## Invariants

1. A release identity is the exact lowercase 40-character Git commit SHA; branches, tags, timestamps, hostnames, and short SHAs are never identities.
2. The target release ID and root are deterministic functions of the full SHA and release base. Caller-supplied identity collisions or root mismatches fail closed.
3. Manifest preflight is fail-closed and identity-bound. A manifest digest, source SHA, target root, previous identity, file inventory, or mode cannot be silently substituted or inferred.
4. Pointer CAS compares the complete expected and observed release identity before any switch is described. A plan never hides a stale-current conflict.
5. A rollback target is always present, valid, schema-compatible, digest-bound, and explicitly marked compatible before a success plan is returned.
6. Every step is a declarative planned step with an explicit `effect` of `none` or `planned_only`; `external_actions` is always an empty list.
7. Optional user-systemd actions appear only when explicitly supplied and are represented as unit/action data, never as commands or execution receipts.
8. Same-round readback and observation are plan stages, not reads or probes. The plan contains signal names and a bounded window only; it contains no URL, response, status, or runtime claim.
9. Output is an allowlisted redacted projection. Manifest file bytes, secret values, arbitrary request extensions, volatile values, and environment values cannot appear.
10. Canonical output and `plan_id` are deterministic, idempotent, and free of timestamps, randomness, process IDs, host state, and mutable release state.
11. Validation is input-only. The request and all nested values remain unchanged, and no filesystem, process, network, service, database, pointer, symlink, Nginx, or Feishu mutation occurs.

## Data impact

The planner reads and validates only the caller-owned in-memory mapping and returns a new in-memory mapping or raises a validation error. It does not persist a plan, update a pointer, write a manifest, create a release, record an observation, or change a database. The plan ID is a deterministic digest, not a durable idempotency record. Retrying the same request returns the same plan and does not acquire locks or change state. A different source SHA, pointer identity, manifest digest, rollback target, systemd intent, or observation window produces a distinct deterministic plan ID.

## Permissions

The source-only operator may construct and inspect a local dry-run plan. No role using this function may obtain implicit permission to deploy, switch traffic, restart a service, read secrets, access a remote host, write Feishu, read a database, or claim production acceptance. A later activation executor, if separately approved, must consume this plan as evidence and perform its own authority, authenticated readback, and human release gates; those permissions are outside this contract.

## Performance and reliability

Planning is bounded by request size and manifest inventory size, with no network wait, subprocess retry, service timeout, filesystem scan, database transaction, or external dependency. The protected tests use small in-memory fixtures and must be repeatable offline. Invalid input is terminal and fail-closed. Equivalent input order must not change output. The planner must not emit a partial result after a validation error.

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | The public planner API and v1 request/output schema are explicit, exact, and fail closed on unknown fields and wrong types. | Unit | Automatic | Yes |
| AC-02 | Only a lowercase 40-character full Git SHA is accepted as source identity. | Unit | Automatic | Yes |
| AC-03 | Release ID and release root are derived from and bound to the full SHA. | Unit | Automatic | Yes |
| AC-04 | Unsafe, broad, traversal, non-POSIX, unresolved, and root-escaping paths are rejected. | Unit | Automatic | Yes |
| AC-05 | Manifest preflight validates schema, clean source identity, target root, inventory, modes, digests, and previous identity without reading the root. | Unit | Automatic | Yes |
| AC-06 | A target root or release ID not bound to the full SHA is rejected. | Unit | Automatic | Yes |
| AC-07 | Expected-current pointer CAS rejects a stale or mismatched observed identity. | Unit | Automatic | Yes |
| AC-08 | Missing, malformed, mismatched, or root-unsafe previous releases are rejected. | Unit | Automatic | Yes |
| AC-09 | Missing or false rollback compatibility and unsupported manifest compatibility are rejected. | Unit | Automatic | Yes |
| AC-10 | Release ID/root identity collisions are rejected before a plan is returned. | Unit | Automatic | Yes |
| AC-11 | Both activation and rollback produce declarative plans without executing the switch or rollback. | Unit | Automatic | Yes |
| AC-12 | Optional user-systemd steps are included only when explicitly requested and contain no commands or execution receipts. | Unit | Automatic | Yes |
| AC-13 | Same-round readback and bounded observation are represented as planned stages without HTTP, service, or runtime reads. | Unit | Automatic | Yes |
| AC-14 | The output is canonical, compact, newline-free, recursively sorted, and free of volatile values. | Unit | Automatic | Yes |
| AC-15 | The output is redacted and excludes secrets, manifest file bytes, arbitrary extensions, URLs, and commands. | Unit | Automatic | Yes |
| AC-16 | Repeating the same request and canonicalizing equivalent key orders are idempotent and byte-identical. | Unit | Automatic | Yes |
| AC-17 | The planner performs no subprocess, SSH, filesystem mutation, symlink, systemd, Nginx, database, HTTP, Feishu, or other external action. | Unit | Automatic | Yes |
| AC-18 | Request input is not mutated and failure returns no partial plan. | Unit | Automatic | Yes |
| AC-19 | Stable error codes and redacted error text identify every required fail-closed category. | Unit | Automatic | Yes |
| AC-20 | Protected tests are red on the frozen baseline only because the intended planner module/API is absent. | Static and unit | Automatic | Yes |

## Human acceptance

Human judgment is limited to source-only boundary clarity and implementation handoff. It does not repeat deterministic schema, path, digest, CAS, rollback, canonicalization, or no-execution assertions.

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | The source-only boundary and remaining production blockers are understandable to an operator. | acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/checklist.md#h-01 | Production reconciliation owner | No |
| H-02 | The activation and rollback sequence is understandable as a plan and is not mistaken for an execution receipt. | acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/checklist.md#h-02 | Production reconciliation owner | No |
| H-03 | The reserved implementation paths, protected test, and handoff limits are unambiguous. | acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/checklist.md#h-03 | Production reconciliation owner | No |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| openclaw-tag-router/tests/test_production_reconciliation_planner.py | b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898 | AC-01 through AC-20: full-SHA identity, safe paths, manifest preflight, pointer CAS, previous and rollback validation, collisions, optional systemd/readback/observation planning, canonical redacted idempotent output, no external actions, non-mutation, stable errors, and baseline red proof |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | Protected API/schema tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-02 | Protected full-SHA parameterization | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-03 | Protected derived identity tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-04 | Protected path safety tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-05 | Protected manifest preflight tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-06 | Protected root binding tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-07 | Protected pointer CAS tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-08 | Protected previous release tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-09 | Protected rollback compatibility tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-10 | Protected identity collision tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-11 | Protected activation and rollback plan tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-12 | Protected explicit user-systemd tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-13 | Protected readback and observation tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-14 | Protected canonical serializer tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-15 | Protected redaction and secret rejection tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-16 | Protected idempotency tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-17 | Protected no-execution audit tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-18 | Protected input non-mutation tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-19 | Protected stable error and red-proof tests | openclaw-tag-router/tests/test_production_reconciliation_planner.py | Automatic | Yes |
| AC-20 | CPython 3.12 baseline red run | docs/production-reconciliation/20260825/acceptance/machine/unit/runs/<run-id>/result.md | Automatic | Yes |
| H-01 | Scripted human boundary review | acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/checklist.md#h-01 | Human | No |
| H-02 | Scripted plan-versus-execution review | acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/checklist.md#h-02 | Human | No |
| H-03 | Scripted implementation handoff review | acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/checklist.md#h-03 | Human | No |

## Exploratory testing

No exploratory run is required for this source-only fragment. Future implementation review should probe reordered mappings, duplicate normalized paths, full-SHA changes, stale pointer snapshots, previous-release schema changes, conflicting release catalogs, explicit systemd actions, zero or very large observation windows, secret-like unknown fields, and interruption between planned stages. These probes are not a substitute for the protected deterministic tests.

## Production monitoring and rollback

No production monitoring or rollback execution is authorized or claimed. The plan itself must include an observation stage and a rollback stage, but both are declarative `planned_only` steps. A later production release must define authenticated same-round readback, signal collection, operator ownership, thresholds, human approval, and an independently authorized rollback runbook before any production claim.

## Risks and open decisions

Known boundaries and evidence gaps:

- `docs/production-reconciliation/20260825/source-shas.json` records separate GitHub, candidate, server-worktree, and active-release identities; this fragment never merges them.
- The reference deploy script is behavior evidence only and is intentionally not reused as an execution helper.
- The protected test is expected to fail on the frozen baseline because the reserved planner module/API is absent. That is red design evidence, not implementation or release evidence.
- Real manifest creation, readback, service state, authenticated HTTP, database state, Feishu state, authorized activation, authorized rollback, and human release approval remain unverified.
- The root-level generated `acceptance/index.md` is a validation-only projection and must remain uncommitted for the main integrator.

Open decisions for a later implementation authority:

- The implementation must preserve the exact public API, error-code boundary, input-only behavior, and output allowlist unless a new accepted contract supersedes this v1.
- The later executor must define how a validated plan is handed to a separately authorized mutating workflow; this contract does not grant that authority.
- Any change to release ID format, path policy, manifest schema compatibility, pointer identity, rollback compatibility, step ordering, redaction policy, or external-action boundary invalidates this fragment and its protected-test hash.
